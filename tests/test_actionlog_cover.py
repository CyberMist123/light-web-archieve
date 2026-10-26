"""r5 补测：用号行为日志（tmp home 落盘 + 纯逻辑；不联网、不起进程）。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from link_brain import actionlog, storage
from link_brain.sources.xiaohongshu import accounts


def _tz(h: float) -> datetime:
    return datetime.now(timezone.utc).astimezone() + timedelta(hours=h)


def test_parse_extracts_three_kinds():
    assert actionlog.parse("读取服务报 [XHS_RATE_LIMITED]，error_code=300013，触发接口=sub_comments") == \
        {"code": "XHS_RATE_LIMITED", "error_code": "300013", "reject": "sub_comments"}
    assert actionlog.parse("error_code: 300011 别的没提") == {"code": "", "error_code": "300011", "reject": ""}
    assert actionlog.parse("comment/sub/page 撞了") == {"code": "", "error_code": "", "reject": "sub_comments"}
    assert actionlog.parse("") == {"code": "", "error_code": "", "reject": ""}
    assert actionlog.parse("小写 [code] 不算")["code"] == ""   # 括号码要求全大写


def test_trigger_env_then_argv(monkeypatch):
    monkeypatch.setenv("LWA_TRIGGER", " 夜跑 ")
    assert actionlog.trigger() == "夜跑"
    monkeypatch.delenv("LWA_TRIGGER", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "sync", "favorites", "--quiet"])
    assert actionlog.trigger() == "sync favorites"          # 没环境变量：取命令行前两个非参数
    monkeypatch.setattr(sys, "argv", ["prog"])
    assert actionlog.trigger() == "manual"


def test_record_and_read_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    row = actionlog.record("comments", ok=False, item="xhs-1", detail="[ACCOUNT_RISK] error_code=300011",
                           secs=3.14159, note="extra", empty=None)
    assert row["action"] == "comments" and row["ok"] is False and row["item"] == "xhs-1"
    assert row["code"] == "ACCOUNT_RISK" and row["error_code"] == "300011"   # code 没给就从 detail 取
    assert row["secs"] == 3.1 and row["detail"] == "[ACCOUNT_RISK] error_code=300011"
    assert row["note"] == "extra" and "empty" not in row and "ts" in row and "trigger" in row
    ok_row = actionlog.record("note", ok=True, detail="成功的 detail 不留")
    assert "detail" not in ok_row                             # detail 只在失败时留
    rows = actionlog.read()
    assert [r["action"] for r in rows] == ["comments", "note"]  # 旧在前
    assert actionlog.read(limit=1) == [rows[1]]
    since = datetime.now().astimezone() + timedelta(hours=1)
    assert actionlog.read(since=since) == []                   # 全在窗口外
    # 家目录写不进去（home 变成一个文件）：返回 None，不抛
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "blocker"))
    (tmp_path / "blocker").write_text("不是目录", encoding="utf-8")
    assert actionlog.record("note", ok=True) is None


def test_record_repairs_half_written_line(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    p = actionlog.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'{"ts": "2026-10-25T10:00:00+11:00", "action": "favorites"}')   # 没换行的半行
    actionlog.record("note", ok=True)
    lines, bad = storage.read_jsonl(p)
    assert len(lines) == 2 and bad == 0                       # 新行没粘在半行后面


def test_rotation_keeps_one_backup(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    p = actionlog.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        f.write(b"x" * (actionlog.MAX_BYTES + 10))            # 超过 5 MB 触发轮转
    actionlog.record("note", ok=True)
    assert p.with_name(actionlog.FILE + ".1").exists()        # 旧的整个挪成 .1
    rows = actionlog.read()
    assert len(rows) == 1 and rows[0]["action"] == "note"     # 新文件从一行开始


def test_repeat_pause_logic():
    now = datetime(2026, 10, 26, 12, 0).astimezone()

    def hit(hours_ago: float, code="300013", action="comments"):
        return {"action": action, "ok": False, "code": "XHS_RATE_LIMITED", "error_code": code,
                "ts": (now - timedelta(hours=hours_ago)).isoformat(timespec="seconds")}
    assert actionlog.repeat_pause("comments", [hit(1)], now=now) == ("", None)        # 只拦一次归熔断管
    why, until = actionlog.repeat_pause("comments", [hit(10), hit(2)], now=now)
    assert why.startswith("「读评论 / 楼中楼」72 小时内被小红书拦了 2 次（300013）")
    assert until == now - timedelta(hours=2) + actionlog.REPEAT_PAUSE                 # 从最后一次起 24h
    _, until3 = actionlog.repeat_pause("comments", [hit(30), hit(10), hit(2)], now=now)
    assert until3 == now - timedelta(hours=2) + actionlog.REPEAT_PAUSE * 2            # 第 3 次 = 48h
    # 都过期了不拦；别的行为 / 成功的不算
    assert actionlog.repeat_pause("comments", [hit(80), hit(79)], now=now) == ("", None)
    assert actionlog.repeat_pause("favorites", [hit(1), hit(2)], now=now) == ("", None)
    assert actionlog.repeat_pause("comments", [hit(1), {**hit(2), "ok": True, "code": ""}], now=now) == ("", None)


def test_is_risk_codes():
    assert actionlog.is_risk({"ok": False, "code": "ACCOUNT_RISK"}) is True
    assert actionlog.is_risk({"ok": False, "code": "CAPTCHA_REQUIRED"}) is True
    assert actionlog.is_risk({"ok": False, "code": "RATE_LIMITED"}) is False   # 本地码不算号被拦
    assert actionlog.is_risk({"ok": True, "code": "ACCOUNT_RISK"}) is False


def test_action_for_tool_and_route():
    assert actionlog.action_for_tool("get_feed_detail", {}) == "note"
    assert actionlog.action_for_tool("get_feed_detail", {"load_all_comments": True}) == "comments"
    assert actionlog.action_for_tool("get_feed_detail", {"expand_floors": "all"}) == "comments"
    assert actionlog.action_for_tool("check_login_status", {}) == "login_check"
    assert actionlog.action_for_tool("别的工具", {}) == "别的工具"
    assert actionlog.action_for_route("/api/v1/favorites?x=1") == "favorites"
    assert actionlog.action_for_route("/api/v1/notes/related-file") == "attachments"
    assert actionlog.action_for_route("/api/v1/login/status") == "login_check"
    assert actionlog.action_for_route("/api/v1/risk/probe") == "probe"
    assert actionlog.action_for_route("/不认识的") == ""
