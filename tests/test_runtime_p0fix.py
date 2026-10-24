"""1024 第一波返修（复审 runtime#3 / #4）：判活查不清算活着；sync-status 锁里不等问题记录锁。"""

from __future__ import annotations

import os
import threading
import time

import pytest

from link_brain import alert as alert_mod, problems, procs, storage, sync_state


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    monkeypatch.setattr(alert_mod, "_alert", lambda *a, **k: True)


def test_alive_when_creation_time_unknown(monkeypatch):
    """runtime#3：OpenProcess 被拒 / 快照失败 → created_of 返回 None：查不清 = 当活着，不把在跑的同步标成被打断。"""
    monkeypatch.setattr(storage, "pid_state", lambda pid: "alive")
    monkeypatch.setattr(procs, "created_of", lambda pid, table=None: None)
    assert sync_state._alive(os.getpid(), 1234.0) is True
    storage.write_json(sync_state.path(), {"state": "running", "pid": os.getpid(), "pid_created": 1234.0})
    assert sync_state.load()["state"] == "running"


@pytest.mark.skipif(os.name != "nt", reason="单进程取创建时间只在 Windows 上走 GetProcessTimes")
def test_created_of_single_pid_does_not_enumerate_all_processes(monkeypatch):
    """runtime#3：判活每次都全表枚举太重——只问这一个 pid。"""
    monkeypatch.setattr(procs, "process_table", lambda: pytest.fail("不该整表枚举"))
    got = procs.created_of(os.getpid())
    assert got is not None and abs(got - time.time()) < 24 * 3600


def _hold_problems_lock(release: threading.Event, ready: threading.Event):
    with storage.file_lock("problems", wait_s=5):
        ready.set()
        release.wait(20)


@pytest.mark.parametrize("call", [
    lambda: sync_state.account_problem("NOT_LOGGED_IN", "掉登录"),
    lambda: sync_state.record("failed", message="同步没做完"),
    lambda: sync_state.account_ok(),
])
def test_sync_status_lock_not_held_while_waiting_for_problems_lock(monkeypatch, call):
    """runtime#4：问题记录锁被占着时，拿着 sync-status 锁去登记问题会把别人卡到 LockBusy（同步收尾直接崩）。"""
    monkeypatch.setattr(problems, "LOCK_WAIT_S", 2)
    # account_ok 要有没解决的 login 行才会去等问题记录锁
    problems.report("login", "NEEDS_HUMAN.NOT_LOGGED_IN", "掉登录")
    storage.write_json(sync_state.path(), {"state": "ready", "message": "旧"})
    release, ready = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_problems_lock, args=(release, ready), daemon=True)
    holder.start()
    assert ready.wait(5)
    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    time.sleep(0.5)
    try:
        with storage.file_lock(sync_state.LOCK, wait_s=1):
            pass
    except storage.LockBusy:
        pytest.fail("修前：sync-status 锁被拿着去等问题记录锁")
    finally:
        release.set()
        worker.join(30)
        holder.join(5)


# ---------------------------------------------------------------- runtime#6：mcp / 问答崩溃，下次成功自动解决；不归「AI 接口」


def test_mcp_crash_resolved_by_next_success(monkeypatch, capsys):
    from link_brain import mcp_server, mcp_tools
    monkeypatch.setattr(mcp_server, "_ctx", lambda: None)
    monkeypatch.setattr(mcp_tools, "call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("索引坏了")))
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search", "arguments": {}}}
    mcp_server._dispatch(msg)
    assert [r for r in problems.load() if r["step"] == "mcp"]
    monkeypatch.setattr(mcp_tools, "call", lambda *a, **k: {"status": "ok"})
    mcp_server._dispatch({**msg, "id": 2})
    assert not [r for r in problems.load() if r["step"] == "mcp"], "修前：崩溃登记后永远挂着，3 天后升级推送"


def test_ask_crash_resolved_by_next_success_and_not_api_category(monkeypatch):
    import io
    import sys
    from types import SimpleNamespace
    from link_brain import serve
    from test_batch3_feedback import _Stdin

    calls = []

    def answer(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("代码 bug")
        return {"status": "ok", "markdown": "答"}

    monkeypatch.setattr(serve.ask, "answer", answer)
    monkeypatch.setattr(serve, "_warm", lambda: None)
    stdin, out = _Stdin(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", out)
    worker = threading.Thread(target=serve.run, args=(SimpleNamespace(),), daemon=True)
    worker.start()
    stdin.put({"id": "1", "question": "随便"})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and out.getvalue().count('"type": "result"') < 1:
        time.sleep(0.05)
    [row] = [r for r in problems.load() if r["code"] == "TRANSIENT.STEP_CRASHED"]
    assert problems.category(row) != "api", "代码崩溃不是 AI 接口的问题"
    stdin.put({"id": "2", "question": "再问"})
    while time.monotonic() < deadline and out.getvalue().count('"type": "result"') < 2:
        time.sleep(0.05)
    stdin.put(None)
    worker.join(5)
    assert not [r for r in problems.load() if r["code"] == "TRANSIENT.STEP_CRASHED"]


def test_catalog_problem_context_sees_rows_only_in_pending(monkeypatch):
    """runtime#7：她点的「隐藏」等不到锁写进了旁路，目录卡片不用等并回就该看到。"""
    import json as _json
    from link_brain import catalog
    row = {"ts": "2026-10-01T04:00:00+10:00", "key": "ocr|xhs-p|OCR_EMPTY", "step": "ocr", "item_id": "xhs-p",
           "code": "PERMANENT.OCR_EMPTY", "reason": "x", "count": 1, "resolved_at": None}
    problems.path().parent.mkdir(parents=True, exist_ok=True)
    problems.path().write_text(_json.dumps(row) + "\n", "utf-8")
    assert ("xhs-p", "OCR_EMPTY") not in catalog._problem_context()["hidden"]
    problems.pending_dir().mkdir(parents=True, exist_ok=True)
    (problems.pending_dir() / "1-1-1.jsonl").write_text(
        _json.dumps({"ts": "2026-10-01T05:00:00+10:00", "key": row["key"], "dismiss": True}) + "\n", "utf-8")
    assert ("xhs-p", "OCR_EMPTY") in catalog._problem_context()["hidden"], "修前：按主文件 mtime 缓存，旁路的隐藏看不到"
