"""1017（她）：问题面板——账号只认一个状态、限频冷却不挂、按「是什么事」分区、缺标题从目录补。"""
from __future__ import annotations

import json

import pytest

from link_brain import accounts, alert as alert_mod, problems, storage, sync_state


@pytest.fixture(autouse=True)
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_mod, "_alert", lambda *a, **k: sent.append(a) or True)
    return sent


def _open_login():
    return [r for r in problems.load() if r.get("step") == "login"]


OK_SESSION = {"logged_in": True, "risk_hold": None, "state": "idle", "verifying": False}


def test_reconcile_clears_stale_rate_limit_and_login_rows_when_account_is_fine():
    problems.report_blocked("comments.fill", "XHS_RATE_LIMITED", "读取账号需要处理：请在 Link Brain 设置页检查并重新扫码。详情：300013")
    problems.report_blocked("sync.favorites", "CAPTCHA_REQUIRED", "弹了验证")
    assert len(_open_login()) == 2
    assert problems.reconcile_account(OK_SESSION) == 2
    assert _open_login() == []
    assert problems.summary()["needs_human"] == 0


@pytest.mark.parametrize("session", [
    {"logged_in": True, "risk_hold": {"code": "ACCOUNT_RISK", "since": "2026-10-17T01:00:00+11:00"}},
    {"logged_in": False, "risk_hold": None},
    {"logged_in": True, "risk_hold": None, "verifying": True},
    {"logged_in": None},
])
def test_reconcile_leaves_rows_when_account_is_not_clearly_fine(session):
    problems.report_blocked("sync.favorites", "CAPTCHA_REQUIRED", "弹了验证")
    assert problems.reconcile_account(session) == 0
    assert len(_open_login()) == 1


def test_reconcile_is_fail_open_when_reader_is_down():
    # conftest：读取服务默认「没在跑」
    problems.report_blocked("sync.favorites", "NOT_LOGGED_IN", "掉登录")
    assert problems.reconcile_account() == 0
    assert len(_open_login()) == 1


def test_rate_limit_cooling_until_passed_counts_as_fine():
    problems.report_blocked("comments.fill", "XHS_RATE_LIMITED", "限频")
    hold = {"code": "XHS_RATE_LIMITED", "until": "2026-10-15T13:44:00+11:00", "strikes": 1}
    assert problems.reconcile_account({"logged_in": True, "risk_hold": hold}) == 1


def test_account_ok_also_resolves_rate_limit_and_night_captcha():
    problems.report("login", "TRANSIENT.XHS_RATE_LIMITED", "限频")
    problems.report("login", "TRANSIENT.NIGHT_CAPTCHA", "夜里验证")
    sync_state.account_ok()
    assert _open_login() == []


def test_rate_limit_is_quiet_and_reason_has_no_rescan_wording(monkeypatch):
    monkeypatch.setattr(accounts, "_hold_file", lambda: None)
    problems.report_blocked("comments.fill", "XHS_RATE_LIMITED", "读取账号需要处理：请在 Link Brain 设置页检查并重新扫码。")
    row = problems.load()[0]
    assert "扫码" not in row["reason"] and "限频" in row["reason"]
    assert row["minor"] is True
    assert problems.load(include_minor=False) == []
    s = problems.summary()
    assert s["auto"] == 0 and s["minor"] == 1


@pytest.mark.parametrize("step,code,want", [
    ("login", "NEEDS_HUMAN.NOT_LOGGED_IN", "account"),
    ("note.restricted", "PERMANENT.NOTE_RESTRICTED", "fetch"),
    ("ai.summary", "NEEDS_HUMAN.AUTH_FAILED", "api"),
    ("vision.refine", "PERMANENT.MODEL_OUTPUT_INVALID", "api"),
    ("comments.fill", "PERMANENT.COMMENTS_INCOMPLETE", "fetch"),
    ("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "fetch"),
    ("ingest", "PERMANENT.NOTE_GONE", "fetch"),
    ("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "other"),
    ("enrich.summary", "SKIPPED.NOT_CONFIGURED", "off"),
])
def test_category(step, code, want):
    assert problems.category({"step": step, "code": code}) == want


def test_load_rows_carry_category_and_dismiss_by_category():
    problems.report("note.restricted", "PERMANENT.NOTE_RESTRICTED", "要验证", item_id="xhs-a")
    problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "有密码", item_id="xhs-b")
    cats = {r["item_id"]: r["category"] for r in problems.load()}
    assert cats == {"xhs-a": "fetch", "xhs-b": "other"}
    out = problems.dismiss(category_name="other")
    assert out["ok"] and len(out["dismissed"]) == 1
    hidden = {r["item_id"]: r["hidden"] for r in problems.load()}
    assert hidden == {"xhs-a": False, "xhs-b": True}
    assert problems.dismiss(category_name="nope")["ok"] is False


def test_missing_title_filled_from_catalog():
    (storage.archive_root()).mkdir(parents=True, exist_ok=True)
    (storage.archive_root() / "catalog-data.json").write_text(
        json.dumps({"items": [{"id": "xhs-t", "title": "合成标题"}]}, ensure_ascii=False), "utf-8")
    problems.report("note.restricted", "PERMANENT.NOTE_RESTRICTED", "要验证", item_id="xhs-t")
    assert problems.load()[0]["title"] == "合成标题"


# ---- 1017 第二轮（她：「要验证」和号只看一个状态冲突；评论没补全多条合并一条；修好就消失）

from datetime import datetime, timedelta

from link_brain import restricted


def _mark_at(sid, when, monkeypatch):
    monkeypatch.setattr(restricted, "_now", lambda: when)
    return restricted.mark(sid, item_id=f"xhs-{sid}", title="t", via="comments.fill", detail="[NOTE_RESTRICTED]")


def test_restricted_first_hit_is_only_suspected_quiet_and_retried_next_day(monkeypatch):
    t0 = datetime(2026, 10, 16, 20, 0).astimezone()
    _mark_at("n1", t0, monkeypatch)
    assert [r for r in problems.load() if r["step"] == "note.restricted"] == [], "撞见一次：不登记"
    assert restricted.view("n1") is None, "笔记页也不出「要验证」那行"
    assert restricted.is_restricted("n1") is True, "当天后台先不再开"
    monkeypatch.setattr(restricted, "_now", lambda: t0 + timedelta(hours=21))
    assert restricted.is_restricted("n1") is False, "隔天放行再开一次"


def test_restricted_confirmed_on_second_day(monkeypatch):
    t0 = datetime(2026, 10, 16, 20, 0).astimezone()
    _mark_at("n2", t0, monkeypatch)
    _mark_at("n2", t0 + timedelta(hours=21), monkeypatch)
    rows = [r for r in problems.load() if r["step"] == "note.restricted"]
    assert len(rows) == 1 and restricted.is_restricted("n2") and restricted.view("n2")


def test_restricted_reopened_clears_everything(monkeypatch):
    t0 = datetime(2026, 10, 16, 20, 0).astimezone()
    _mark_at("n3", t0, monkeypatch)
    _mark_at("n3", t0 + timedelta(days=1), monkeypatch)
    assert restricted.clear("n3", item_id="xhs-n3", why="续读打开了")
    assert [r for r in problems.load() if r["step"] == "note.restricted"] == []


def test_quiet_unconfirmed_retires_old_single_day_rows():
    problems.report("note.restricted", "PERMANENT.NOTE_RESTRICTED", "要验证", item_id="xhs-old")
    restricted.save("old", {"restricted": True, "since": "2026-10-16T19:43:10+11:00", "last_at": "2026-10-16T19:43:10+11:00"})
    assert restricted.quiet_unconfirmed() == ["xhs-old"]
    assert [r for r in problems.load() if r["step"] == "note.restricted"] == []


def test_fold_comments_into_one_row_and_unfold_when_fixed():
    for i in ("a", "b", "c"):
        problems.report("comments.fill", "PERMANENT.COMMENTS_INCOMPLETE", "楼中楼还缺 5 条", item_id=f"xhs-{i}", title=f"标题{i}")
    rows = problems.fold_rows(problems.load(include_minor=False))
    assert len(rows) == 1 and rows[0]["key"] == "fold|PERMANENT.COMMENTS_INCOMPLETE"
    assert rows[0]["title"].startswith("3 篇") and len(rows[0]["items"]) == 3 and rows[0]["category"] == "fetch"
    assert problems.summary()["gave_up"] == 1
    problems.resolve("comments.fill", "xhs-a")
    problems.resolve("comments.fill", "xhs-b")
    rows = problems.fold_rows(problems.load(include_minor=False))
    assert [r["item_id"] for r in rows] == ["xhs-c"], "只剩一篇就照原样一条"
    problems.resolve("comments.fill", "xhs-c")
    assert problems.fold_rows(problems.load(include_minor=False)) == [], "都修好：整条消失"


def test_dismiss_fold_key_hides_every_member():
    for i in ("a", "b"):
        problems.report("comments.fill", "PERMANENT.COMMENTS_INCOMPLETE", "楼中楼还缺 5 条", item_id=f"xhs-{i}")
    out = problems.dismiss("fold|PERMANENT.COMMENTS_INCOMPLETE")
    assert out["ok"] and len(out["dismissed"]) == 2


# ---- 1017 第三轮（她：我自己的号能看、验证窗口里看不到；只剩一条了）

def test_confirmed_restricted_but_archive_complete_is_not_listed(monkeypatch):
    t0 = datetime(2026, 10, 16, 20, 0).astimezone()
    monkeypatch.setattr(restricted, "archive_complete", lambda sid: True)
    _mark_at("n4", t0, monkeypatch)
    _mark_at("n4", t0 + timedelta(days=1), monkeypatch)
    assert [r for r in problems.load() if r["step"] == "note.restricted"] == [], "正文都在、只缺几条回复：不叫她"


def test_quiet_unconfirmed_also_retires_confirmed_but_complete(monkeypatch):
    problems.report("note.restricted", "PERMANENT.NOTE_RESTRICTED", "要验证", item_id="xhs-done")
    restricted.save("done", {"restricted": True, "days": ["2026-10-16", "2026-10-17"]})
    monkeypatch.setattr(restricted, "archive_complete", lambda sid: True)
    assert restricted.quiet_unconfirmed() == ["xhs-done"]


def test_archive_complete_is_false_when_unreadable():
    assert restricted.archive_complete("no-such-note") is False, "读不清就照常登记"


def test_reconcile_with_unknown_login_uses_action_log(monkeypatch):
    from link_brain import actionlog
    problems.report("login", "TRANSIENT.XHS_RATE_LIMITED", "限频")
    session = {"logged_in": None, "risk_hold": None, "state": "idle", "verifying": False}
    assert problems.reconcile_account(session) == 0, "没有用号记录：不知道就不动"
    later = (datetime.now().astimezone() + timedelta(minutes=5)).isoformat(timespec="seconds")
    monkeypatch.setattr(actionlog, "read", lambda since=None, limit=None: [{"ts": later, "action": "comments", "ok": True}])
    assert problems.reconcile_account(session) == 1, "之后号用成功过：算好着"


def test_reconcile_unknown_login_but_last_use_was_blocked(monkeypatch):
    from link_brain import actionlog
    problems.report("login", "TRANSIENT.XHS_RATE_LIMITED", "限频")
    t = datetime.now().astimezone()
    rows = [{"ts": (t + timedelta(minutes=1)).isoformat(), "ok": True},
            {"ts": (t + timedelta(minutes=2)).isoformat(), "ok": False, "code": "XHS_RATE_LIMITED"}]
    monkeypatch.setattr(actionlog, "read", lambda since=None, limit=None: rows)
    assert problems.reconcile_account({"logged_in": None, "risk_hold": None}) == 0


def test_note_page_line_hidden_when_archive_complete(monkeypatch):
    restricted.save("n5", {"restricted": True, "days": ["2026-10-16", "2026-10-17"]})
    monkeypatch.setattr(restricted, "archive_complete", lambda sid: False)
    assert restricted.view("n5")
    monkeypatch.setattr(restricted, "archive_complete", lambda sid: True)
    assert restricted.view("n5") is None
