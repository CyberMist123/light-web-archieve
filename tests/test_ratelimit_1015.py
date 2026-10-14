"""1015（她：点开「等你处理」无事发生）：10-12 起的 ACCOUNT_RISK 全是小红书回 300013「访问频繁」（展开楼中楼时）。
读取组件 reader-8 把它记成限频冷却（熔断 code=XHS_RATE_LIMITED，带 until / strikes / probing），Python 这侧：
冷却中一页不开但不要人处理、不推送（TRANSIENT，记在 login 一把 key）；冷却到点当没有熔断（下一个请求就是自探）。
另：同一次熔断（起因那条 + 之后各步的 RISK_HOLD）面板只显示一条、只计一次。

读取服务一律是假的（accounts.api / ensure_reader 替身），不起服务、不联网、不开页。合成数据。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from link_brain import accounts, alert as alert_mod, comment_fill, favorites, night_captcha, problems
from link_brain.adapters import xiaohongshu as xhs

TZ = timezone(timedelta(hours=11))
T0 = datetime(2026, 10, 15, 4, 0, 0, tzinfo=TZ)


def _rl(until=T0 + timedelta(hours=2), strikes=1, probing=False):
    h = {"code": "XHS_RATE_LIMITED", "since": T0.isoformat(), "detail": "访问频繁", "until": until.isoformat(),
         "strikes": strikes}
    if probing:
        h["probing"] = True
    return h


@pytest.fixture(autouse=True)
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_mod, "_alert", lambda *a, **k: sent.append(a) or True)
    return sent


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += timedelta(seconds=s)


# ---------------------------------------------------------------- accounts

def test_cooling_hold_is_a_hold_probing_is_not():
    far = datetime.now().astimezone() + timedelta(hours=2)
    assert accounts.hold_from_session({"risk_hold": _rl(until=far)})["code"] == "XHS_RATE_LIMITED"
    assert accounts.hold_from_session({"risk_hold": _rl(probing=True)}) is None, "冷却到点：放行自探"
    past = datetime.now().astimezone() - timedelta(minutes=1)
    assert accounts.hold_from_session({"risk_hold": _rl(until=past)}) is None, "until 已过（老服务没给 probing）也放行"
    assert accounts.hold_from_session({"risk_hold": {"code": "ACCOUNT_RISK", "since": "x"}})["code"] == "ACCOUNT_RISK"


def test_check_risk_hold_raises_rate_limited_not_risk_hold(monkeypatch):
    far = datetime.now().astimezone() + timedelta(hours=2)
    monkeypatch.setattr(accounts, "risk_hold", lambda: _rl(until=far))
    with pytest.raises(accounts.ReaderError) as e:
        accounts.check_risk_hold()
    assert e.value.code == "XHS_RATE_LIMITED"
    assert "不用处理" in e.value.detail and "限频" in e.value.detail
    assert "XHS_RATE_LIMITED" not in accounts.NEEDS_HUMAN_CODES


def test_hold_row_says_wait_no_login_or_verify_button():
    row = accounts.hold_row(_rl(strikes=2))
    assert row["code"] == "XHS_RATE_LIMITED" and row["action"] == "wait" and row["state"] == "busy"
    assert "第 2 次" in row["next_step"]
    assert row["risk_hold"]["until"]


def test_api_423_with_rate_limit_hold_maps_to_rate_limited(monkeypatch):
    class Resp:
        status_code = 423

        def json(self):
            return {"error": "读取服务在限频冷却中", "code": "RISK_HOLD", "details": "冷却到 06:00", "hold": _rl()}

    monkeypatch.setattr(accounts.httpx, "request", lambda *a, **k: Resp())
    monkeypatch.setattr(accounts, "base_url", lambda: "http://127.0.0.1:1")
    with pytest.raises(accounts.ReaderError) as e:
        accounts.api("GET", "/api/v1/login/status")
    assert e.value.code == "XHS_RATE_LIMITED"


def test_mcp_text_risk_code():
    fresh = "[XHS_RATE_LIMITED] 小红书说访问太频繁（/website-login/error error_code=300013，限频不是封号），已停止操作、自动冷却"
    held = "[RISK_HOLD] 读取服务在限频冷却中（XHS_RATE_LIMITED，第 1 次，冷却到 x）：…/website-login/error…"
    assert xhs.risk_code(fresh) == "XHS_RATE_LIMITED"
    assert xhs.risk_code(held) == "XHS_RATE_LIMITED"
    assert xhs.risk_code("[ACCOUNT_RISK] 跳到 /website-login/error") == "ACCOUNT_RISK"


# ---------------------------------------------------------------- 问题记录：不要人、不推、一把 key

def test_report_blocked_rate_limited_is_transient_on_login_and_not_pushed(pushes):
    problems.report_blocked("comments.fill", "XHS_RATE_LIMITED", "小红书说访问太频繁，已冷却到 06:00")
    problems.report_blocked("sync.favorites", "XHS_RATE_LIMITED", "小红书说访问太频繁，已冷却到 06:00")
    rows = problems.load()
    assert len(rows) == 1
    assert rows[0]["step"] == "login" and rows[0]["code"] == "TRANSIENT.XHS_RATE_LIMITED"
    assert rows[0]["group"] == "auto" and rows[0]["label"] == "小红书限频冷却中"
    s = problems.summary()
    assert s["needs_human"] == 0 and s["auto"] == 1
    assert pushes == []


def test_same_hold_shows_once_in_panel_and_counts():
    problems.report_blocked("sync.favorites", "ACCOUNT_RISK", "被跳到登录 / 安全页")
    problems.report_blocked("attachments.download", "RISK_HOLD", "风控暂停中")
    rows = problems.load()
    assert [r["code"] for r in rows] == ["NEEDS_HUMAN.ACCOUNT_RISK"], "起因那条代表整次熔断"
    assert problems.summary()["needs_human"] == 1
    problems.resolve("login", None, "ACCOUNT_RISK")
    rows = problems.load()
    assert [r["code"] for r in rows] == ["NEEDS_HUMAN.RISK_HOLD"], "起因解决了而熔断还挂着：RISK_HOLD 照实显示"


def test_lone_risk_hold_still_shown():
    problems.report_blocked("sync.favorites", "RISK_HOLD", "风控暂停中")
    assert [r["code"] for r in problems.load()] == ["NEEDS_HUMAN.RISK_HOLD"]
    assert problems.summary()["needs_human"] == 1


# ---------------------------------------------------------------- 调用方

def test_sync_favorites_exit_code_rate_limited(capsys):
    payload = {"items": [{"status": "blocked", "code": "XHS_RATE_LIMITED", "error": "x"}]}
    assert favorites._exit_code(payload) == favorites.EXIT_NEEDS_HUMAN  # 夜跑据此今晚不开页，交给 captcha-recover 等冷却
    assert "不用处理" in capsys.readouterr().err


def test_comment_fill_waits_on_rate_limit(monkeypatch):
    far = datetime.now().astimezone() + timedelta(hours=2)
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: {"risk_hold": _rl(until=far)})
    code, why = comment_fill.account_wait_reason()
    assert code == "XHS_RATE_LIMITED" and "不用处理" in why


def test_night_recover_rate_limit_cooling_then_cleared(monkeypatch):
    clock = Clock(T0 + timedelta(minutes=30))
    hold = _rl(until=T0 + timedelta(hours=2))
    monkeypatch.setattr(accounts, "risk_hold", lambda: hold)
    calls = []
    monkeypatch.setattr(accounts, "api", lambda *a, **k: calls.append(a) or {})

    r = night_captcha.recover(wait=False, now_fn=clock)
    assert r["result"] == "cooling" and r["exit"] != 0 and r["retry_after_s"] > 0
    r = night_captcha.recover(wait=True, max_wait_min=30, now_fn=clock, sleep=clock.sleep)
    assert r["result"] == "cooling", "等不到冷却结束就不等"
    r = night_captcha.recover(wait=True, max_wait_min=180, now_fn=clock, sleep=clock.sleep)
    assert r["result"] == "cleared" and r["exit"] == 0
    assert clock.now >= T0 + timedelta(hours=2)
    assert calls == [], "限频冷却不调 /risk/probe：读取组件到点自己放行自探"


def test_repair_never_opens_pages_for_rate_limit():
    from link_brain import repair
    row = problems.report("login", "TRANSIENT.XHS_RATE_LIMITED", "小红书说访问太频繁")
    p = repair.plan(row, T0)
    assert p["kind"] == "wait", p
