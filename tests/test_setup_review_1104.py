"""1104 安装审查（GPT 报告第 1 / 3 / 4 / 5 / 7 / 8 / 9 条）：`setup run` 的选择补齐、读设置半截重读、整轮锁、
中途出错收尾、组件安装走限时子进程、部分完成的说法、子进程后代攥着管道不挂住。子进程全用替身（不起真安装、不碰号）。"""
from __future__ import annotations

import json
import sys
import threading
import time

from link_brain import ai_config, comment_fill, problems, storage
from link_brain.setup import components, pipeline


def _settings(selected, **extra):
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(p, {"setup": {"selected": selected, "aiSynced": True}, **extra})


def _ready(ids):
    return {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]}


def _ocr_missing(ids):
    return {"ok": True, "results": [{"item_id": i, "status": "missing" if i == "ocr" else "ready", "fix": "auto"} for i in ids]}


def _run(monkeypatch, *, child=None, check=None, install=None):
    monkeypatch.setattr(components, "check", check or _ready)
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    events = []
    out = pipeline.run(events.append, child=child or (lambda args, **k: (0, False)), install=install,
                       account_check=lambda: ("", ""), bili_check=lambda: False)
    return out, events


def test_normalize_selection_adds_required_and_keeps_unknown():
    assert components.normalize_selection(["ocr"]) == ["core", "reader", "ocr"]
    assert components.normalize_selection([]) == ["core", "reader"]
    assert components.normalize_selection(["ai_vision", "dataview"])[-1] == "dataview"


def test_selection_missing_reader_is_completed_before_install(monkeypatch):
    """审查 1：老配置 / 手改的选择缺了必选的读取组件——装组件那一步照样把它算进去（不再「没装它、随后又要检查它」）。"""
    _settings(["core", "ocr"])
    seen = []
    out, _ = _run(monkeypatch, check=lambda ids: seen.append(list(ids)) or _ready(ids))
    assert "reader" in seen[0]
    assert out["selected"][:3] == ["core", "reader", "ocr"]


def test_half_written_settings_are_not_reset_to_defaults(monkeypatch):
    """审查 5：读到半截的 data.json 不当成「没选过 = 轻量版」——重读几次；还坏就这一轮不开跑，说清原因。"""
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"setup": {"selected": ["core", "rea', encoding="utf-8")
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    calls = []
    out, _ = _run(monkeypatch, child=lambda args, **k: (calls.append(args[0]) or (0, False)))
    assert out["ok"] is False and out["code"] == "TRANSIENT.BUSY" and "读不动" in out["message"]
    assert calls == []
    st = json.loads(pipeline.state_path().read_text("utf-8"))
    assert st["running"] is False and st["result"]["code"] == "TRANSIENT.BUSY"


def test_settings_reread_waits_out_a_partial_write():
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"setup": {"sel', encoding="utf-8")
    tries = []

    def finish_write(_s):
        tries.append(1)
        storage.write_json(p, {"setup": {"selected": ["core", "reader", "ocr", "ai_text"]}})
    pipeline._settings_readable(sleep=finish_write)
    assert tries == [1]
    assert pipeline.selected() == ["core", "reader", "ocr", "ai_text"]


def test_second_run_on_same_library_says_busy_and_leaves_progress_alone(monkeypatch):
    """审查 4：同一个收藏库已有一轮在跑（锁在别人手里）→ 后到的说忙、不写进度文件。"""
    _settings(["core", "reader", "ocr"])
    pipeline.write_state({"running": True, "pid": 1, "stages": [], "result": None, "mark": "别人的"})
    box = {}
    with storage.file_lock(pipeline._run_lock_name(), wait_s=0, owner="另一个窗口"):
        t = threading.Thread(target=lambda: box.update(out=_run(monkeypatch)[0]))
        t.start()
        t.join(30)
    assert box["out"]["busy"] is True and box["out"]["code"] == "TRANSIENT.BUSY"
    assert json.loads(pipeline.state_path().read_text("utf-8"))["mark"] == "别人的"


def test_crash_mid_run_still_closes_progress_file(monkeypatch):
    """审查 9：中途出意外，进度文件也收尾成 running=false + result，插件重开不会一直显示「在跑」。"""
    _settings(["core", "reader", "ocr"])

    def boom(ids):
        raise RuntimeError("检查炸了")
    out, _ = _run(monkeypatch, check=boom)
    assert out["ok"] is False and out["code"] == "TRANSIENT.STEP_CRASHED" and "装好要用的组件" in out["message"]
    st = json.loads(pipeline.state_path().read_text("utf-8"))
    assert st["running"] is False and st["result"]["code"] == "TRANSIENT.STEP_CRASHED"


def test_install_goes_through_time_limited_child_and_forwards_patch(monkeypatch):
    """审查 3 / 5：装一项走子进程 `setup install`（有时限）；子进程的结果（带 settings_patch）原样转给插件。"""
    _settings(["core", "reader", "ocr"])
    seen = []

    def child(args, **k):
        seen.append((args, k.get("timeout_min")))
        if args[:2] == ["setup", "install"]:
            k["on_line"]({"type": "progress", "component": "ocr", "text": "下载模型"})
            k["on_line"]({"type": "result", "ok": True, "status": "ready", "message": "好了", "settings_patch": {"ocr": {"modelDir": "M"}}})
        return 0, False
    out, events = _run(monkeypatch, child=child, check=_ocr_missing)
    assert (["setup", "install", "--component", "ocr"], pipeline.INSTALL_TIMEOUT_MIN) in seen
    done = [e for e in events if e.get("component") == "ocr" and e.get("state") == "ok"]
    assert done and done[0]["settings_patch"] == {"ocr": {"modelDir": "M"}}
    assert any(e.get("stage") == "install" and e.get("text") == "下载模型" for e in events)
    assert {s["id"]: s["state"] for s in out["stages"]}["install"] == "ok"


def test_install_child_timeout_and_silent_exit_are_reported_and_logged(monkeypatch):
    """审查 3 / 7：装一项超时、或子进程没给结果就退出 → 这一项失败，说清原因，并登记进问题记录（修复区同一份）。"""
    _settings(["core", "reader", "ocr"])
    out, events = _run(monkeypatch, child=lambda args, **k: ((None, True) if args[0] == "setup" else (0, False)), check=_ocr_missing)
    assert {s["id"]: s["state"] for s in out["stages"]}["install"] == "failed"
    assert "超过" in next(e for e in events if e.get("component") == "ocr" and e.get("state") == "failed")["text"]
    assert any(r.get("step") == "setup" and not r.get("resolved_at") for r in problems.load(50))
    _, events = _run(monkeypatch, child=lambda args, **k: (1, False), check=_ocr_missing)
    assert "没给结果" in next(e for e in events if e.get("component") == "ocr" and e.get("state") == "failed")["text"]
    # 再跑一轮全装好了 → 那条解掉
    _run(monkeypatch)
    assert not any(r.get("step") == "setup" and not r.get("resolved_at") for r in problems.load(50))


def test_reader_down_is_logged_as_a_problem(monkeypatch):
    """审查 7：读取组件没装 / 没起来也进问题记录，修复区「当前状态」不再说「没有要你处理的」。"""
    _settings(["core", "reader", "ocr"])
    monkeypatch.setattr(components, "check", _ready)
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True})
    out = pipeline.run(lambda e: None, child=lambda args, **k: (0, False),
                       account_check=lambda: ("NOT_INSTALLED", "没装读取组件"), bili_check=lambda: False)
    assert out["ok"] is False
    assert any(r.get("step") == "login" and not r.get("resolved_at") for r in problems.load(50))


def test_partial_step_carries_child_reason_without_night_promise(monkeypatch):
    """审查 8：子命令退出码 2 = 做了一部分——记 partial、带子命令自己说的原因；不再一律承诺「夜里接着做」。"""
    _settings(["core", "reader", "ocr"])

    def child(args, **k):
        if args[0] == "sync-favorites":
            k["on_line"]({"type": "result", "ok": False, "message": "3 篇图片没下全"})
            return 2, False
        return 0, False
    out, _ = _run(monkeypatch, child=child)
    sync = next(s for s in out["stages"] if s["id"] == "sync")
    assert sync["state"] == "partial" and "3 篇图片没下全" in sync["text"] and "夜里" not in sync["text"]
    assert out["ok"] is True and "只做了一部分" in out["message"] and out["synced"] is True


def test_child_does_not_hang_when_grandchild_holds_the_pipe(monkeypatch, tmp_path):
    """审查 3：父进程退了、后代还攥着 stdout——不再一直等 EOF，过了宽限期就按父进程的退出码收尾。"""
    monkeypatch.setattr(pipeline, "CHILD_EXIT_GRACE_S", 1)
    script = tmp_path / "hold.py"
    script.write_text(
        "import json, subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(25)'])\n"
        "print(json.dumps({'type': 'result', 'ok': True, 'message': 'done'}), flush=True)\n", encoding="utf-8")
    real_popen = pipeline.subprocess.Popen
    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda cmd, **kw: real_popen([sys.executable, str(script)], **kw))
    got = []
    t0 = time.monotonic()
    rc, timed_out = pipeline._child(["x"], timeout_min=1, on_line=got.append)
    assert time.monotonic() - t0 < 20
    assert rc == 0 and timed_out is False
    assert {"type": "result", "ok": True, "message": "done"} in got


def test_pip_install_times_out_while_reading_output(monkeypatch, tmp_path):
    """审查 3：uv / pip 不出声也不退出——计时覆盖读输出全程，到点结束整棵进程树、报 TRANSIENT.TIMEOUT。"""
    from link_brain.setup.common import SetupError
    monkeypatch.setattr(components, "PIP_TIMEOUT_S", 2)
    monkeypatch.setattr(components, "managed_uv", lambda: tmp_path / "uv.exe")
    script = tmp_path / "stall.py"
    script.write_text("import time\nprint('Resolved 3 packages', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    real_popen = components.subprocess.Popen
    monkeypatch.setattr(components.subprocess, "Popen", lambda cmd, **kw: real_popen([sys.executable, str(script)], **kw))
    events = []
    t0 = time.monotonic()
    try:
        components._pip_install("ocr", ["rapidocr"], events.append)
        raise AssertionError("应该超时")
    except SetupError as exc:
        assert exc.code == "TRANSIENT.TIMEOUT"
    assert time.monotonic() - t0 < 20
    assert any("Resolved" in (e.get("text") or "") for e in events)


def test_never_logged_in_machine_does_not_start_reader_or_visit(monkeypatch):
    """1104 作者：从没扫码登录过的电脑——setup run 的登录检查不拉起读取组件、不以游客身份开小红书；直接记「等扫码」。"""
    from link_brain.sources.xiaohongshu import accounts, comment_fill as cf
    monkeypatch.setattr(accounts, "ever_logged_in", lambda: False)
    monkeypatch.setattr(accounts, "reader_exe", lambda: "C:/fake/link-brain-reader.exe")
    touched = []
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: touched.append("ensure") or {})
    monkeypatch.setattr(accounts, "api", lambda *a, **k: touched.append("api") or {})
    assert pipeline._account_state() == ("NOT_LOGGED_IN", pipeline.LOGIN_WAIT_TEXT)
    assert cf.account_wait_reason()[0] == "NOT_LOGGED_IN"
    assert touched == []
    _settings(["core", "reader", "ocr"])
    monkeypatch.setattr(components, "check", _ready)
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: touched.append("worker") or {"ok": True})
    out = pipeline.run(lambda e: None, child=lambda args, **k: (0, False), bili_check=lambda: False)
    st = {s["id"]: s["state"] for s in out["stages"]}
    assert st["login"] == "waiting" and st["sync"] == "skipped" and st["comments"] == "skipped"
    assert out["ok"] is True and touched == []
    # 没装读取组件：照旧说没装
    monkeypatch.setattr(accounts, "reader_exe", lambda: None)
    assert pipeline._account_state()[0] == "NOT_INSTALLED"


def test_ever_logged_in_reads_saved_account(monkeypatch):
    from link_brain.sources.xiaohongshu import accounts
    real = accounts._ever_logged_in_real   # conftest 默认把它换成「登录过」，原函数留在这里（家目录仍是 tmp）
    assert "lbhome" in str(accounts.home())
    assert real() is False
    accounts.save({"nickname": "某人", "user_id": "u1"})
    assert real() is True


def test_status_report_never_logged_in_answers_without_reader(monkeypatch):
    """1104 作者：从没扫码登录过——账号状态（浅查、「检查」深查都一样）直接答未登录，不问、不拉起读取组件。"""
    from link_brain.sources.xiaohongshu import accounts
    monkeypatch.setattr(accounts, "ever_logged_in", lambda: False)
    touched = []
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: touched.append("ensure") or {})
    monkeypatch.setattr(accounts, "api", lambda *a, **k: touched.append("api") or {})
    for kw in ({"deep": False, "launch": False}, {"deep": True}):
        row, st = accounts.status_report(**kw)
        assert row["state"] == "not_logged_in" and row["action"] == "login" and st == "guest"
    assert touched == []
    assert problems.STATE_REGISTRY["NEEDS_HUMAN.NOT_LOGGED_IN"]["label"] == "未登录"
