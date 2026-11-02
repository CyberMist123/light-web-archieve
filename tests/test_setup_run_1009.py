"""1009 作者：装好插件 → 填 API（可选）→ 点一次「一键装好 / 跑完」→ 同步、OCR / 识图、概要、目录、索引一口气跑完；
不填 API 也一口气跑完轻量版。`setup run` 的步骤编排（子进程用替身，不起真进程、不碰号）。"""

from __future__ import annotations

import json

import pytest

from link_brain import ai_config, comment_fill, storage
from link_brain.setup import components, pipeline


def _settings(selected, **extra):
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(p, {"setup": {"selected": selected, "aiSynced": True}, **extra})


def _fake_env(monkeypatch, *, account=("", ""), rc=None, bili=False):
    calls = []

    def child(args, *, timeout_min, on_line, env_extra=None):
        calls.append(list(args))
        on_line(f"[fake] {args[0]} 跑着")
        return (rc or {}).get(args[0], 0), False
    monkeypatch.setattr(components, "check", lambda ids: {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    events = []
    out = pipeline.run(events.append, child=child, account_check=lambda: account, bili_check=lambda: bili)
    return out, calls, events


def test_light_mode_runs_sync_catalog_and_hands_comments_to_background(monkeypatch):
    _settings(["core", "reader", "ocr"])
    out, calls, events = _fake_env(monkeypatch)
    assert out["ok"] is True and "轻量版" in out["message"]
    assert [c[0] for c in calls] == ["sync-favorites", "catalog"]  # 没开 AI：不跑概要 / 索引
    assert calls[0] == ["sync-favorites", "--limit", "0", "--extract"]
    st = {s["id"]: s["state"] for s in out["stages"]}
    assert st == {"install": "ok", "login": "ok", "sync": "ok", "enrich": "skipped", "catalog": "ok", "embed": "skipped",
                  "comments": "ok"}
    assert any(e.get("type") == "progress" and e.get("stage") == "sync" and "跑着" in e.get("text", "") for e in events)


def test_ai_selected_and_configured_adds_enrich_and_embed(monkeypatch):
    _settings(["core", "reader", "ocr", "ai_text", "ai_vision"])
    monkeypatch.setattr(pipeline, "_ai_on", lambda sel, cap: True)
    out, calls, _ = _fake_env(monkeypatch)
    assert [c[0] for c in calls] == ["sync-favorites", "enrich", "catalog", "embed"]
    assert out["ok"] is True and "轻量版" not in out["message"]


def test_not_logged_in_skips_account_steps_but_still_tidies_and_says_what_to_do(monkeypatch):
    _settings(["core", "reader", "ocr"])
    out, calls, _ = _fake_env(monkeypatch, account=("NOT_LOGGED_IN", "小红书掉登录了：扫码登录"))
    assert [c[0] for c in calls] == ["catalog"]
    assert out["ok"] is False and out["code"] == "NEEDS_HUMAN" and "扫码登录" in out["message"]
    st = {s["id"]: s["state"] for s in out["stages"]}
    assert st["sync"] == "skipped" and st["comments"] == "skipped" and st["login"] == "failed"


def test_bili_only_user_skips_xhs_steps_without_needs_human(monkeypatch):
    """1101：只登了 B 站（没登小红书）→ 小红书的同步 / 补评论跳过，整理目录照跑，不报「先处理小红书」。"""
    _settings(["core", "reader", "ocr"])
    out, calls, _ = _fake_env(monkeypatch, account=("NOT_LOGGED_IN", "小红书掉登录了：扫码登录"), bili=True)
    assert [c[0] for c in calls] == ["catalog"]
    assert out["ok"] is True and out["code"] == "" and "B 站" in out["message"]
    st = {s["id"]: s["state"] for s in out["stages"]}
    assert st["login"] == "skipped" and st["sync"] == "skipped" and st["comments"] == "skipped"


def test_captcha_still_needs_human_even_with_bili(monkeypatch):
    """登了 B 站也不吞掉小红书的验证：那是号出事，照旧要人处理。"""
    _settings(["core", "reader", "ocr"])
    out, _, _ = _fake_env(monkeypatch, account=("CAPTCHA_REQUIRED", "小红书弹了验证"), bili=True)
    assert out["ok"] is False and out["code"] == "NEEDS_HUMAN"


def test_failed_step_is_reported_plainly_and_the_rest_still_runs(monkeypatch):
    _settings(["core", "reader", "ocr"])
    out, calls, _ = _fake_env(monkeypatch, rc={"sync-favorites": 1})
    assert [c[0] for c in calls] == ["sync-favorites", "catalog"]
    assert out["ok"] is False and "同步收藏" in out["message"]


def test_cli_streams_events_then_result(monkeypatch, capsys):
    from link_brain import cli
    _settings(["core", "reader", "ocr"])
    monkeypatch.setattr(pipeline, "run", lambda emit: (emit({"type": "progress", "stage": "sync", "state": "running"}) or
                                                       {"type": "result", "ok": True, "code": "", "message": "都跑完了", "stages": []}))
    assert cli.main(["setup", "run"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    assert lines[0]["type"] == "progress" and lines[-1]["type"] == "result" and lines[-1]["message"] == "都跑完了"


# ---------------------------------------------------------------- 1102 安装审查 6 / 7 / 8


def test_reader_down_is_not_an_account_problem(monkeypatch):
    """读取服务没起来（被杀毒隔离 / 端口被占 / 崩了）：login 记 failed，但 code 是 TRANSIENT.DISCONNECTED、不引导扫码。"""
    _settings(["core", "reader", "ocr"])
    out, calls, _ = _fake_env(monkeypatch, account=("DISCONNECTED", "读取服务没连上（DISCONNECTED）：点「重试」会再拉起一次"))
    assert [c[0] for c in calls] == ["catalog"]   # 碰号 / 碰读取服务的步骤跳过，离线的照跑
    assert out["ok"] is False and out["code"] == "TRANSIENT.DISCONNECTED"
    assert out["message"].startswith(pipeline.READER_MESSAGE) and "扫码" not in out["message"]
    st = {s["id"]: (s["state"], s["text"]) for s in out["stages"]}
    assert st["login"][0] == "failed" and st["sync"] == ("skipped", "读取组件没起来（见上一步）")
    assert st["comments"][0] == "skipped" and "读取组件" in st["comments"][1]


def test_not_installed_has_its_own_code(monkeypatch):
    _settings(["core", "reader", "ocr"])
    out, _, _ = _fake_env(monkeypatch, account=("NOT_INSTALLED", "没装读取组件：点「重试」会再装一次"))
    assert out["ok"] is False and out["code"] == "NEEDS_HUMAN.NOT_INSTALLED"
    assert out["message"].startswith(pipeline.READER_MESSAGE) and "扫码" not in out["message"]
    # 登了 B 站照旧只用 B 站（1101 的规则不变）
    out2, _, _ = _fake_env(monkeypatch, account=("NOT_INSTALLED", "没装"), bili=True)
    assert out2["ok"] is True and out2["code"] == ""


def test_account_codes_still_say_scan(monkeypatch):
    _settings(["core", "reader", "ocr"])
    for code in ("NOT_LOGGED_IN", "CAPTCHA_REQUIRED", "ACCOUNT_RISK", "BLOCKED"):
        out, _, _ = _fake_env(monkeypatch, account=(code, "号的事"))
        assert out["code"] == "NEEDS_HUMAN", code
        assert out["message"].startswith("先处理小红书"), code
    assert pipeline.login_code("") == "" and pipeline.login_code("TIMEOUT") == "TRANSIENT.DISCONNECTED"


def test_account_state_wording_for_reader_down(monkeypatch):
    from link_brain.sources.xiaohongshu import comment_fill as xcf
    monkeypatch.setattr(xcf, "account_wait_reason", lambda: ("DISCONNECTED", "读取服务没连上（DISCONNECTED），稍后自动再试"))
    code, why = pipeline._account_state()
    assert code == "DISCONNECTED" and "reader.log" in why and "重试" in why and "扫码" not in why
    monkeypatch.setattr(xcf, "account_wait_reason", lambda: ("NOT_INSTALLED", ""))
    code, why = pipeline._account_state()
    assert code == "NOT_INSTALLED" and "重试" in why and "扫码" not in why


def test_cli_exit_code_follows_login_code(monkeypatch, capsys):
    from link_brain import cli
    _settings(["core", "reader", "ocr"])
    for code, rc in (("TRANSIENT.DISCONNECTED", 1), ("NEEDS_HUMAN.NOT_INSTALLED", 5), ("NEEDS_HUMAN", 5), ("", 0)):
        monkeypatch.setattr(pipeline, "run", lambda emit, code=code: {"type": "result", "ok": not code, "code": code, "message": "m", "stages": []})
        assert cli.main(["setup", "run"]) == rc, code
        capsys.readouterr()


def test_check_only_manual_is_needs_you_not_failed(monkeypatch):
    """只能检查、要用户自己在 Obsidian 里装的（check_only + fix=manual）单列 needs_you，不算 failed；其余都成时 ok=true、退出 0，
    message 末尾附一句。1102 起 Dataview 不再是这一类（页面由插件自己显示），这里用一个假的 check_only 项验分类逻辑还在。"""
    _settings(["core", "reader", "ocr", "fake_plugin"])
    fake = {"id": "fake_plugin", "name": "某个 Obsidian 插件", "required": False, "check_only": True}
    monkeypatch.setattr(components, "COMPONENTS", components.COMPONENTS + [fake])
    monkeypatch.setitem(pipeline.NEEDS_YOU_TEXT, "fake_plugin", "还要你装某插件（打开第三方插件）")
    calls = []

    def child(args, *, timeout_min, on_line, env_extra=None):
        calls.append(list(args))
        return 0, False
    monkeypatch.setattr(components, "check", lambda ids: {"ok": True, "results": [
        {"item_id": i, "status": "ready", "fix": "", "fix_hint": ""} if i != "fake_plugin" else
        {"item_id": "fake_plugin", "status": "missing", "fix": "manual", "fix_hint": "在社区插件里装"}
        for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    out = pipeline.run(lambda ev: None, child=child, account_check=lambda: ("", ""), bili_check=lambda: False)
    assert out["ok"] is True and out["code"] == ""
    assert out["message"].endswith("；还要你装某插件（打开第三方插件）")
    assert out["needs_you"] == [{"item_id": "fake_plugin", "status": "missing", "text": "还要你装某插件（打开第三方插件）",
                                 "hint": "在社区插件里装"}]
    st = {s["id"]: s for s in out["stages"]}
    assert st["install"]["state"] == "ok" and "某插件" in st["install"]["text"]
    from link_brain import setup as setup_mod
    monkeypatch.setattr(pipeline, "run", lambda emit: out)
    assert setup_mod.run(type("A", (), {"setup_command": "run"})()) == 0


def test_no_dataview_in_needs_you(monkeypatch):
    """1102：老设置里还勾着 dataview 也不进 needs_you（退役项不检查），新用户开场没有「还要你装 Dataview」。"""
    _settings(["core", "reader", "dataview", "ocr"])
    seen = []
    monkeypatch.setattr(components, "check", lambda ids: seen.append(list(ids)) or {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    out = pipeline.run(lambda ev: None, child=lambda *a, **k: (0, False), account_check=lambda: ("", ""), bili_check=lambda: False)
    assert out["needs_you"] == [] and "Dataview" not in out["message"]
    assert seen and all("dataview" not in ids for ids in seen)


def test_manual_non_check_only_item_is_still_failed(monkeypatch):
    """Python 太旧这种（不是 check_only 的手动项）照旧算 failed——needs_you 只给 check_only 这类只能检查的。"""
    _settings(["core", "reader", "ocr"])
    monkeypatch.setattr(components, "check", lambda ids: {"ok": True, "results": [
        {"item_id": i, "status": "ready", "fix": ""} if i != "core" else
        {"item_id": "core", "status": "failed", "fix": "manual", "fix_hint": "装 Python 3.11+"} for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True})
    out = pipeline.run(lambda ev: None, child=lambda *a, **k: (0, False), account_check=lambda: ("", ""), bili_check=lambda: False)
    assert out["ok"] is False and out["needs_you"] == []
    assert {s["id"]: s["state"] for s in out["stages"]}["install"] == "failed"


def test_state_file_written_on_every_stage_change(monkeypatch):
    """每步状态一变就写 _archive/setup-run.json（Obsidian 关了、stdout 断了进度也在）；跑完写最终 result。"""
    import os
    _settings(["core", "reader", "ocr"])
    seen = []

    def emit(ev):
        if ev.get("type") == "progress":
            seen.append((ev["stage"], ev["state"], json.loads(pipeline.state_path().read_text("utf-8"))))
    monkeypatch.setattr(components, "check", lambda ids: {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    out = pipeline.run(emit, child=lambda args, **k: (0, False), account_check=lambda: ("", ""), bili_check=lambda: False)
    assert seen, "每个进度事件之前文件都已经写好"
    running = [s for s in seen if s[1] == "running"]
    assert all(s["running"] is True and s["pid"] == os.getpid() and s["current"] == stage for stage, _, s in running)
    sync_ok = next(s for stage, state, s in seen if stage == "sync" and state == "ok")
    assert [r["id"] for r in sync_ok["stages"]] == ["install", "login", "sync"] and sync_ok["current"] is None
    final = json.loads(pipeline.state_path().read_text("utf-8"))
    assert final["running"] is False and final["result"]["ok"] is True and final["result"]["message"] == out["message"]
    assert final["started_at"] and final["updated_at"]
    assert len(final["stages"]) == len(pipeline.STAGES)


def test_state_file_failure_does_not_break_the_run(monkeypatch):
    from link_brain import storage
    _settings(["core", "reader", "ocr"])

    def boom(path, data):
        raise OSError(13, "拒绝访问")
    monkeypatch.setattr(storage, "write_json", boom)
    out, calls, _ = _fake_env(monkeypatch)
    assert out["ok"] is True and [c[0] for c in calls] == ["sync-favorites", "catalog"]


def test_stdout_emit_broken_pipe_switches_to_log(monkeypatch, tmp_path):
    """Obsidian 关掉后 stdout 管道断了：不抛、切到 ~/.link-brain/logs/setup-run.log 接着写，之后的事件不再碰 stdout。"""
    import sys
    from link_brain.setup import common
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    writes = []

    class Buf:
        def write(self, b):
            writes.append(b)
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            pass

    class Out:
        buffer = Buf()

        def flush(self):
            pass

        def fileno(self):
            raise ValueError("no fileno")
    monkeypatch.setattr(sys, "stdout", Out())
    common.reset_fallback()
    try:
        common.stdout_emit({"type": "progress", "stage": "sync", "state": "running"})
        common.stdout_emit({"type": "result", "ok": True})
        log = common.fallback_log_path()
        assert log == tmp_path / "home" / "logs" / "setup-run.log"
        lines = log.read_text("utf-8").splitlines()
        assert len(lines) == 3 and "stdout 断了" in lines[0]
        assert json.loads(lines[1].split(" ", 1)[1]) == {"type": "progress", "stage": "sync", "state": "running"}
        assert json.loads(lines[2].split(" ", 1)[1]) == {"type": "result", "ok": True}
        assert len(writes) == 1, "断了之后不再往 stdout 写"
    finally:
        common.reset_fallback()


def test_stdout_emit_other_oserror_still_raises(monkeypatch):
    import sys
    from link_brain.setup import common

    class Buf:
        def write(self, b):
            raise OSError(28, "No space left")

        def flush(self):
            pass

    class Out:
        buffer = Buf()

        def flush(self):
            pass
    monkeypatch.setattr(sys, "stdout", Out())
    common.reset_fallback()
    try:
        with pytest.raises(OSError):
            common.stdout_emit({"a": 1})
    finally:
        common.reset_fallback()


def test_say_tolerates_broken_stderr(monkeypatch):
    import sys
    from link_brain import setup as setup_mod

    class Err:
        def write(self, s):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            pass
    monkeypatch.setattr(sys, "stderr", Err())
    setup_mod._say("原因")   # 不抛


def test_reader_final_mentions_antivirus_when_gone_after_install(monkeypatch):
    monkeypatch.setattr(components, "check", lambda ids: {"results": [
        {"item_id": ids[0], "status": "missing", "detail": "还没装读取组件", "fix": "auto", "fix_hint": ""}]})
    out = components._final("reader", True, "", "读取组件已装好（2 个文件）")
    assert out["ok"] is False and out["code"] == "TRANSIENT.STEP_CRASHED"
    assert "装完再检查还不是就绪" in out["message"] and "杀毒软件隔离" in out["message"] and "Windows 安全中心" in out["message"]
    other = components._final("ocr", True, "", "装好了")
    assert "杀毒" not in other["message"]


def test_enrich_pending_is_single_instance(capsys, monkeypatch):
    """夜跑、「一键装好 / 跑完」、自愈轮都会调 enrich --pending：同一时刻只跑一份，别把同一篇补两遍、花两份钱。"""
    import os, time as _t
    from link_brain import cli, enrich
    lock = storage.locks_dir() / "enrich-pending.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getppid(), "owner": "enrich --pending", "heartbeat_ts": _t.time()}), "utf-8")
    monkeypatch.setattr(enrich, "candidates", lambda: (_ for _ in ()).throw(AssertionError("不该开工")))
    assert cli.main(["enrich", "--pending"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["already_running"] is True and out["candidates"] == 0
    lock.unlink()
    monkeypatch.setattr(enrich, "candidates", lambda: [])
    assert cli.main(["enrich", "--pending"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["candidates"] == 0
    assert not lock.exists(), "跑完放锁"
