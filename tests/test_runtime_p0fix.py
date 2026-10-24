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
