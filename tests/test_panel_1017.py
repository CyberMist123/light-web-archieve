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
    ("note.restricted", "PERMANENT.NOTE_RESTRICTED", "account"),
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
    assert cats == {"xhs-a": "account", "xhs-b": "other"}
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
