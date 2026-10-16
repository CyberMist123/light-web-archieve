"""1016：用号行为日志、同类行为反复被拦就暂停、补评论不放弃、交替抓取排班、实时终端。"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from link_brain import actionlog, comment_fill, crawl, watch

NOW = datetime(2026, 10, 16, 12, 0).astimezone()


@pytest.fixture
def home(tmp_path, monkeypatch):
    from link_brain import accounts
    monkeypatch.setattr(accounts, "home", lambda: tmp_path)
    monkeypatch.setattr(accounts, "profile_dir", lambda: tmp_path / "prof")
    monkeypatch.setenv("LWA_TRIGGER", "test")
    return tmp_path


def test_parse_reader_error_text():
    t = ("获取Feed详情失败: [ACCOUNT_RISK] 小红书说账号异常（/website-login/error error_code=300011 "
         "触发接口=sub_comments，要重新登录），已停止操作")
    assert actionlog.parse(t) == {"code": "ACCOUNT_RISK", "error_code": "300011", "reject": "sub_comments"}
    old = "[XHS_RATE_LIMITED] … rejectUrl=edith.xiaohongshu.com/api/sns/web/v2/comment/sub/page error_code=300013"
    assert actionlog.parse(old)["reject"] == "sub_comments"
    assert actionlog.parse("")["code"] == ""


def test_record_and_read(home):
    actionlog.record("comments", ok=False, item="xhs-1", detail="[XHS_RATE_LIMITED] error_code=300013 触发接口=sub_comments")
    actionlog.record("note", ok=True, item="xhs-2", secs=3.21, sub_clicks=0)
    rows = actionlog.read()
    assert [r["action"] for r in rows] == ["comments", "note"]
    assert rows[0]["code"] == "XHS_RATE_LIMITED" and rows[0]["error_code"] == "300013" and rows[0]["trigger"] == "test"
    assert actionlog.is_risk(rows[0]) and not actionlog.is_risk(rows[1])
    assert rows[1]["secs"] == 3.2 and rows[1]["sub_clicks"] == 0


def _hit(action, hours_ago, code="XHS_RATE_LIMITED"):
    return {"ts": (NOW - timedelta(hours=hours_ago)).isoformat(), "action": action, "ok": False, "code": code}


def test_repeat_pause_needs_two_hits_same_action():
    assert actionlog.repeat_pause("comments", [_hit("comments", 1)], NOW) == ("", None)
    assert actionlog.repeat_pause("comments", [_hit("comments", 1), _hit("note", 2)], NOW) == ("", None)
    why, until = actionlog.repeat_pause("comments", [_hit("comments", 5), _hit("comments", 1)], NOW)
    assert "2 次" in why and until == NOW - timedelta(hours=1) + timedelta(hours=24)
    _, until3 = actionlog.repeat_pause("comments", [_hit("comments", 30), _hit("comments", 5), _hit("comments", 1)], NOW)
    assert until3 == NOW - timedelta(hours=1) + timedelta(hours=48)
    assert actionlog.repeat_pause("comments", [_hit("comments", 40), _hit("comments", 30)], NOW)[0] == ""
    assert actionlog.repeat_pause("comments", [_hit("comments", 100), _hit("comments", 1)], NOW)[0] == ""
    assert actionlog.repeat_pause("comments", [_hit("comments", 2, "TIMEOUT"), _hit("comments", 1, "TIMEOUT")], NOW)[0] == ""


def test_action_kinds():
    assert actionlog.action_for_tool("get_feed_detail", {"load_all_comments": True}) == "comments"
    assert actionlog.action_for_tool("get_feed_detail", {"expand_floors": ["a"]}) == "comments"
    assert actionlog.action_for_tool("get_feed_detail", {}) == "note"
    assert actionlog.action_for_route("/api/v1/favorites?x=1") == "favorites"
    assert actionlog.action_for_route("/api/v1/login/session") == ""


def test_stuck_is_retried_slowly(monkeypatch):
    monkeypatch.setattr(comment_fill, "_now", lambda: NOW)
    st = {"stuck": True, "stuck_floors": 10, "stuck_at": (NOW - timedelta(days=1)).isoformat()}
    assert comment_fill.is_stuck(st, 10)
    st["stuck_at"] = (NOW - timedelta(days=3, minutes=1)).isoformat()
    assert not comment_fill.is_stuck(st, 10), "3 天后自动再试一次，不永久放弃"
    st["stuck_rounds"] = 1
    assert comment_fill.is_stuck(st, 10), "第二轮隔 7 天"
    st["stuck_rounds"] = 9
    st["stuck_at"] = (NOW - timedelta(days=14, minutes=1)).isoformat()
    assert not comment_fill.is_stuck(st, 10), "之后每 14 天一次"


def test_sub_paused_is_resumable():
    from link_brain.adapters import xiaohongshu as xhs
    assert "sub_paused" in xhs.RESUMABLE_GAPS and "sub_paused" in xhs.REPLY_GAP_CN
    assert "sub_paused" in comment_fill.NOT_A_REAL_TRY


def test_plan_block_spaces_out_list_reads():
    assert crawl.ROTATION[0][0] == "fav_new"
    assert crawl.plan_block(0, last_list_read=None, now=1000.0) == 0
    assert crawl.plan_block(0, last_list_read=1000.0, now=1000.0 + 60) == 1, "刚读过列表：先跑别的"
    assert crawl.plan_block(0, last_list_read=0.0, now=crawl.FAV_LIST_GAP_MIN * 60 + 1) == 0


def _drive(ran_stop_at, monkeypatch):
    monkeypatch.setattr(comment_fill, "WORK_MIN", 10_000)
    clock = [0.0]
    ran: list[str] = []

    def run_block(argv, block):
        ran.append(block)
        clock[0] += 600
        return 5 if len(ran) == ran_stop_at else 0

    code = crawl.run(SimpleNamespace(hours=10, fav_min=20, comments_min=25),
                     sleep=lambda s: clock.__setitem__(0, clock[0] + s), run_block=run_block,
                     clock=lambda: clock[0], busy=lambda: "")
    return code, ran


def test_crawl_rotates_and_stops_on_needs_human(home, monkeypatch):
    code, ran = _drive(3, monkeypatch)
    assert code == 5
    assert ran == ["fav_new", "comments", "fav_backlog"]
    assert crawl.read_status()["state"] == "stopped"


def test_crawl_skips_paused_behavior(home, monkeypatch):
    for _ in range(2):
        actionlog.record("comments", ok=False, detail="[XHS_RATE_LIMITED] error_code=300013")
    _, ran = _drive(2, monkeypatch)
    assert ran == ["fav_new", "fav_backlog"], "读评论反复被拦：这一块跳过，收藏照抓"


def test_watch_render_shows_grades():
    snap = {"now": NOW, "hold": {"code": "ACCOUNT_RISK", "since": "2026-10-15T13:46:57+11:00", "detail": "账号异常"},
            "sub": {"clicks": [(NOW - timedelta(minutes=5)).isoformat()]},
            "strikes": {"strikes": 1, "last": "2026-10-15T11:44"},
            "crawl": {"state": "running", "message": "补评论", "history": [{"block": "fav_new", "minutes": 3.0}]},
            "fill": {}, "sync": {},
            "rows": [{"ts": NOW.isoformat(), "action": "comments", "trigger": "crawl:comments", "item": "xhs-abcdef12",
                      "ok": False, "code": "ACCOUNT_RISK", "error_code": "300011", "reject": "sub_comments"},
                     {"ts": NOW.isoformat(), "action": "note", "trigger": "t", "item": "x", "ok": True, "secs": 2,
                      "sub_clicks": 4}]}
    text = watch.render(snap, color=False)
    assert "熔断中 ACCOUNT_RISK" in text and "10-15 13:46" in text
    assert "这一小时已展开 1 次" in text
    assert "ACCOUNT_RISK 300011 @sub_comments" in text
    assert "楼中楼点 4" in text
    assert "读评论 / 楼中楼 ok0 拦1" in text
