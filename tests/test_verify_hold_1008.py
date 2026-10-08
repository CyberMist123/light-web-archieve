"""1008（L6·B1 / S4 / 读取组件 d7 交接）：打开验证先查再开、关窗后如实回报、「没看到验证，恢复」要她亲手确认；
浅查不拉起服务不开页；扫码成功不等于熔断已解；读收藏「这次先停」的两种不走退出码 5；证据路径不出本机。

读取服务一律是假的（FakeReader / monkeypatch），不起服务、不联网。合成数据。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from link_brain import accounts, cli, favorites, problems, sync_state
from test_accounts import FakeReader, clean  # noqa: F401 - fixture

EV = "C:\\Users\\someone\\.link-brain\\risk-evidence\\20261008-051957"
HOLD = {"code": "CAPTCHA_REQUIRED", "since": "2026-10-08T05:19:57+11:00", "detail": "captcha-element",
        "tab": "fav", "want_tab": "fav", "incident_page": "profile", "evidence": EV}


def _args(**kw):
    base = dict(status=False, verify=False, logout=False, qr=False, json=True, force=False, timeout=60,
                shallow=False, wait=False, clear_hold=False, by_owner=False)
    return SimpleNamespace(**{**base, **kw})


def test_open_verify_skips_window_when_no_hold(clean, monkeypatch):
    problems.report("login", "CAPTCHA_REQUIRED", "要验证")
    fake = FakeReader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "logged_in": True}})
    r = accounts.open_verify()
    assert "/api/v1/verify/window" not in fake.calls and "/api/v1/login/status" not in fake.calls
    assert r["state"] == "ready" and "不用再验证" in r["message"]
    assert not problems.is_open("login", None, "CAPTCHA_REQUIRED"), "面板跟着刷掉"


def test_open_verify_no_hold_but_logged_out_does_not_turn_green(clean, monkeypatch):
    FakeReader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "logged_in": False}})
    assert accounts.open_verify()["state"] != "ready"


def test_open_verify_wait_reports_no_captcha_seen(clean, monkeypatch, capsys):
    problems.report("login", "CAPTCHA_REQUIRED", "要验证")
    seq = iter([{"risk_hold": HOLD, "verifying": False},
                {"risk_hold": HOLD, "verifying": True},
                {"risk_hold": HOLD, "verifying": False, "verify_result": "no_captcha_seen"}])
    fake = FakeReader(monkeypatch, {"/api/v1/login/session": lambda: next(seq), "/api/v1/verify/window": {"opened": True}})
    rc = accounts.run_login(_args(verify=True, wait=True))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert fake.calls.count("/api/v1/verify/window") == 1 and "/api/v1/risk/clear" not in fake.calls
    assert out["verify_result"] == "no_captcha_seen" and "没出现验证" in out["message"]
    assert "没看到验证，恢复" in out["next_step"] and rc == 1
    assert "risk-evidence" not in json.dumps(out) and out["risk_hold"]["evidence_id"] == "20261008-051957"
    row = next(r for r in problems.load() if r["step"] == "login")
    assert row["verify_result"] == "no_captcha_seen", "面板据此给「没看到验证，恢复」"


def test_open_verify_wait_not_logged_in_says_scan(clean, monkeypatch):
    seq = iter([{"risk_hold": HOLD}, {"risk_hold": HOLD, "verifying": False, "verify_result": "not_logged_in"}])
    FakeReader(monkeypatch, {"/api/v1/login/session": lambda: next(seq), "/api/v1/verify/window": {"opened": True}})
    r = accounts.open_verify(wait=True)
    assert r["action"] == "login" and "扫码登录" in r["next_step"]


def test_open_verify_wait_cleared_turns_green(clean, monkeypatch):
    problems.report("login", "CAPTCHA_REQUIRED", "要验证")
    seq = iter([{"risk_hold": HOLD}, {"risk_hold": None, "verifying": False, "verify_result": "cleared", "logged_in": True},
                {"risk_hold": None, "logged_in": True}, {"risk_hold": None, "logged_in": True}])
    FakeReader(monkeypatch, {"/api/v1/login/session": lambda: next(seq), "/api/v1/verify/window": {"opened": True}})
    r = accounts.open_verify(wait=True)
    assert r["state"] == "ready" and "验证完成" in r["message"]
    assert not problems.is_open("login", None, "CAPTCHA_REQUIRED")


def test_clear_hold_requires_owner_and_posts_once(clean, monkeypatch, capsys):
    problems.report("login", "CAPTCHA_REQUIRED", "要验证")
    state = {"hold": HOLD}

    def session():
        return {"risk_hold": state["hold"], "logged_in": True}

    def clear():
        state["hold"] = None
        return {"cleared": True}

    fake = FakeReader(monkeypatch, {"/api/v1/login/session": session, "/api/v1/risk/clear": clear})
    assert accounts.run_login(_args(clear_hold=True)) == 1
    assert "/api/v1/risk/clear" not in fake.calls, "没带 --by-owner 绝不清"
    capsys.readouterr()
    assert cli.main(["login", "--clear-hold", "--by-owner", "--json"]) == 0
    assert fake.calls.count("/api/v1/risk/clear") == 1
    raw = [json.loads(x) for x in problems.path().read_text("utf-8").splitlines()]
    assert any("她确认没看到验证" in str(x.get("repair_note")) for x in raw), "问题记录里留痕"
    assert not problems.is_open("login", None, "CAPTCHA_REQUIRED")


def test_shallow_status_never_launches_or_opens_page(clean, monkeypatch, capsys):
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: pytest.fail("浅查不许拉起服务"))

    def down():
        raise accounts.ReaderError("DISCONNECTED")

    fake = FakeReader(monkeypatch, {"/api/v1/login/session": down})
    assert cli.main(["login", "--status", "--shallow", "--json"]) == 4
    assert json.loads(capsys.readouterr().out)["state"] == "idle"
    fake.routes["/api/v1/login/session"] = {"logged_in": None, "state": "idle"}
    assert cli.main(["login", "--status", "--shallow", "--json"]) == 4
    capsys.readouterr()
    fake.routes["/api/v1/login/session"] = {"logged_in": True, "state": "idle"}
    assert cli.main(["login", "--status", "--shallow", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "ready"
    fake.routes["/api/v1/login/session"] = {"logged_in": True, "risk_hold": HOLD}
    assert cli.main(["login", "--status", "--shallow", "--json"]) == 5
    out = capsys.readouterr().out
    assert "risk-evidence" not in out and "20261008-051957" in out and "读收藏时判到验证" in out
    assert "/api/v1/login/status" not in fake.calls


def test_login_success_with_captcha_hold_still_reports_hold(clean, monkeypatch):
    seq = iter([{"state": "idle"}, {"state": "success", "nickname": "alice", "user_id": "u1", "risk_hold": HOLD}])
    FakeReader(monkeypatch, {"/api/v1/login/session": lambda: next(seq), "/api/v1/login/window": {"opened": True}})
    r = accounts.login()
    assert r["state"] != "ready" and "暂停还在" in r["message"] and r["action"] == "verify"


@pytest.mark.parametrize("code", ["HIDDEN_WIDGET", "FAV_TAB_STUCK"])
def test_soft_stop_codes_do_not_exit_5(clean, monkeypatch, capsys, code):
    alerts = []
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: alerts.append(a))
    FakeReader(monkeypatch, {"/api/v1/login/session": {"state": "idle"},
                             "/api/v1/favorites": accounts.ReaderError(code, "这次先停，下次照常读")})
    rc = cli.main(["sync-favorites", "--limit", "0"])
    assert rc == favorites.EXIT_PARTIAL, "只停收藏，不是要人处理（夜跑不挡当晚其它碰号步骤）"
    rows = problems.load()
    assert [(r["step"], r["code"]) for r in rows] == [("sync.favorites", f"TRANSIENT.{code}")] and not alerts
    assert sync_state.load()["code"] == code


def test_stop_reason_texts_follow_reader_d7():
    for key in ("stalled", "hidden_widget", "api_refused"):
        assert key in favorites.STOP_REASON_TEXT
    assert "stuck_has_more" not in favorites.STOP_REASON_TEXT
    why = favorites.suspicious_reason(1150, 1216, {"partial": True, "stop_reason": "stalled"})
    assert "换了一种滚法" in why


def test_captcha_texts_mention_fav_tab():
    assert "收藏" in accounts.SOLUTIONS["CAPTCHA_REQUIRED"][2]
    assert "「收藏」页签" in problems.STATE_REGISTRY["NEEDS_HUMAN.CAPTCHA_REQUIRED"]["hover"]


def test_evidence_never_leaves_the_machine(clean, monkeypatch):
    monkeypatch.setenv("XHS_PROFILE_DIR", str(clean / "profile"))
    (clean / "profile").mkdir()
    (clean / "profile" / "risk-hold.json").write_text(json.dumps(HOLD), "utf-8")
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: True)
    row = problems.report_blocked("sync.favorites", "CAPTCHA_REQUIRED", f"读收藏撞验证（证据 {EV}）")
    assert row["evidence_id"] == "20261008-051957"
    text = problems.export_redacted()
    assert "risk-evidence" not in text and "<本机证据目录>" in text
    assert "risk-evidence" not in json.dumps(accounts.hold_row(HOLD), ensure_ascii=False)
    assert accounts.hold_text(HOLD).endswith("在读收藏时判到验证")


def test_page_summary_has_last_risk_for_sync_button_note(monkeypatch):
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: True)
    problems.report("login", "CAPTCHA_REQUIRED", "10-08 05:19 在读收藏时判到验证")
    lr = problems.page_summary()["last_risk"]
    assert lr["code"] == "NEEDS_HUMAN.CAPTCHA_REQUIRED" and lr["open"] is True
