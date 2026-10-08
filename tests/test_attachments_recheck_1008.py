"""1008（L6·B3）附件补查：游客段不碰号、熔断夜照跑（开关 + 60 分钟 + ≤10 篇）、无条件保险丝、号被占用就让路；
收尾段只看游客读不到的、/login 停车不判删帖、服务失败第一次就收工、两晚 /explore（或新口令一次）才判原帖打不开；
本地对账、下载跨夜退避、状态文件（跳过也写）、面板如实的状态句、夜跑跳过收尾段也记一笔。

全部用合成对象（tests 里的 id 都是合成的），网页探测 / 登录号补看 / 下载一律假的，不联网、不起读取服务。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from link_brain import accounts, attachments as att, cli, nightly, problems, repair, storage
from link_brain.adapters import xiaohongshu as xhs

TZ = timezone(timedelta(hours=11))


def _obj(sid: str, *, web_ok=False, mark=None, title="合成笔记"):
    obj = storage.archive_root() / "xiaohongshu" / sid
    raw = obj / "raw" / "v0001"
    raw.mkdir(parents=True, exist_ok=True)
    storage.write_json(obj / "meta.json", {"item_id": f"xhs-{sid}", "current_version": 1, "title": title})
    storage.write_json(raw / "source.json", {"note": {"attachments": [], "xsec_token": "OLD_FAKE_TOKEN"}})
    storage.write_json(raw / "web_raw.json", {"ok": web_ok, "url": f"https://example.invalid/{sid}?xsec_token=OLD_FAKE_TOKEN"})
    if mark is not None:
        (obj / "derived").mkdir(parents=True, exist_ok=True)
        storage.write_json(obj / "derived" / "web_recheck.json", mark)
    return obj


def _mark(sid):
    return storage.read_json(storage.archive_root() / "xiaohongshu" / sid / "derived" / "web_recheck.json")


@pytest.fixture
def guest_env(monkeypatch, tmp_path):
    """账号那一侧任何调用都炸：游客段一次都不许碰。"""
    monkeypatch.setattr(att, "PROBE_GAP_SECONDS", (0, 0))
    monkeypatch.setenv("XHS_PROFILE_DIR", str(tmp_path / "profile"))
    (tmp_path / "profile").mkdir()

    def boom(*a, **k):
        raise AssertionError("游客段碰了号")

    for name in ("ensure_reader", "api", "account_session", "check_risk_hold", "risk_hold", "pace"):
        monkeypatch.setattr(accounts, name, boom)
    monkeypatch.setattr(att, "_probe_logged_in", boom)
    monkeypatch.setattr(att, "acquire", boom)
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: None)
    return tmp_path


def _hold(tmp_path, minutes_ago):
    since = (datetime.now().astimezone() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    storage.write_json(tmp_path / "profile" / "risk-hold.json", {"code": "CAPTCHA_REQUIRED", "since": since})


def _probes(monkeypatch, plan):
    """plan: sid -> 结果 dict（缺省 = 没附件的正常笔记）。返回调用记录。"""
    calls = []

    def fake(note_id, token, **kw):
        calls.append((note_id, token, kw.get("stop_on_captcha")))
        return {"ok": True, "related_file": None, "url": "u", "error": None, **plan.get(note_id, {})}

    monkeypatch.setattr(xhs, "fetch_related_file", fake)
    return calls


RF = {"docId": "fake-doc-0001", "name": "合成附件.pdf", "bizExtra": "{\"page_num\": 3}"}


# --------------------------------------------------------------------------
# 游客段
# --------------------------------------------------------------------------


def test_guest_only_never_touches_account_and_runs_during_old_hold(guest_env, monkeypatch, capsys):
    for i in range(14):
        _obj(f"aa{i:02d}")
    _hold(guest_env, minutes_ago=120)
    calls = _probes(monkeypatch, {"aa01": {"related_file": RF}, "aa03": {"ok": False, "error": "登录墙"}})
    assert cli.main(["attachments", "--recheck", "--guest-only", "--budget-min", "30"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["account_hold"] is True and out["limit"] == 10 and out["checked"] == 10, "熔断夜：≤10 篇"
    assert all(c[2] is True for c in calls), "游客探测带保险丝（验证页不起浏览器兜底）"
    assert out["found"] == [{"id": "aa01", "file": "合成附件.pdf"}]
    resolved = storage.read_json(storage.archive_root() / "xiaohongshu" / "aa01" / att.RESOLVED_NAME)["resolved"]
    assert resolved[0]["doc_id"] == "fake-doc-0001", "探到附件只登记，交给 --all 去下"
    assert _mark("aa03")["stage"] == "guest_unseen"
    st = storage.read_json(att.status_path())
    assert st["guest"]["account_hold"] is True and st["guest"]["checked"] == 10


def test_guest_skips_when_hold_is_recent_or_switch_off(guest_env, monkeypatch, capsys):
    _obj("bb01")
    calls = _probes(monkeypatch, {})
    _hold(guest_env, minutes_ago=20)
    assert cli.main(["attachments", "--recheck", "--guest-only"]) == 0
    assert calls == [] and json.loads(capsys.readouterr().out)["stopped_reason"] == "hold_too_recent"
    _hold(guest_env, minutes_ago=200)
    monkeypatch.setenv("LWA_GUEST_RECHECK_DURING_HOLD", "0")
    assert cli.main(["attachments", "--recheck", "--guest-only"]) == 0
    assert calls == [] and json.loads(capsys.readouterr().out)["stopped_reason"] == "account_hold"
    assert storage.read_json(att.status_path())["guest"]["stopped_reason"] == "account_hold"


def test_guest_budget_reaches_limit_with_220s_reserve(guest_env, monkeypatch):
    for i in range(45):
        _obj(f"cc{i:02d}")
    now = [0.0]
    monkeypatch.setattr(att, "_clock", lambda: now[0])

    def slow(note_id, token, **kw):
        now[0] += 78
        return {"ok": True, "related_file": None, "url": "u", "error": None}

    monkeypatch.setattr(xhs, "fetch_related_file", slow)
    out = att.recheck_guest(budget_left=att.budget_from_minutes(150))
    assert out["limit"] == 40 and out["checked"] == 40, "积压期（>20 篇）上限 40，预算按 220 秒/篇够用"
    now[0] = 0.0
    for i in range(45, 70):
        _obj(f"cc{i:02d}")
    out = att.recheck_guest(budget_left=att.budget_from_minutes(30))
    assert out["checked"] == int((1800 - att.guest_cost()) // 78) + 1 and out["stopped_reason"] == "out_of_time"
    monkeypatch.setattr(att, "PROBE_GAP_SECONDS", (30, 90))
    assert att.guest_cost() == 220


def test_guest_fuse_and_captcha_stop(guest_env, monkeypatch):
    for i in range(5):
        _obj(f"dd{i:02d}")
    calls = _probes(monkeypatch, {"dd00": {"ok": False, "error": "x"}, "dd01": {"ok": False, "error": "y"}})
    out = att.recheck_guest()
    assert out["stopped_reason"] == "fuse" and len(calls) == 2, "连续 2 篇读不到：当晚停"
    calls = _probes(monkeypatch, {"dd02": {"ok": False, "captcha": True, "error": "安全验证"}})
    out = att.recheck_guest()
    assert out["stopped_reason"] == "captcha" and len(calls) == 1
    assert problems.is_open("attachments.recheck", None, "TRANSIENT.WEB_PROBE_BLOCKED")
    calls = _probes(monkeypatch, {"dd02": {"ok": False, "browser_error": True, "error": "游客浏览器探测失败"}})
    out = att.recheck_guest()
    assert out["stopped_reason"] == "guest_browser_error" and len(calls) == 1


def test_guest_yields_when_account_is_busy(guest_env, monkeypatch):
    _obj("ee01")
    calls = _probes(monkeypatch, {})
    monkeypatch.setattr(accounts, "lock_holder", lambda: {"owner": "sync-favorites", "pid": 1})
    out = att.recheck_guest()
    assert calls == [] and out["stopped_reason"] == "account_busy"


def test_order_never_checked_first_then_oldest(guest_env, monkeypatch):
    _obj("ff03", mark={"ok": False, "checked_at": "2026-10-07T04:30:00"})
    _obj("ff02", mark={"ok": False, "checked_at": "2026-09-27T04:30:00"})
    _obj("ff01")
    calls = _probes(monkeypatch, {})
    att.recheck_guest()
    assert [c[0] for c in calls] == ["ff01", "ff02", "ff03"]


# --------------------------------------------------------------------------
# 收尾段
# --------------------------------------------------------------------------


def _unseen(sid, **extra):
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return _obj(sid, mark={"ok": False, "stage": "guest_unseen", "guest_at": now, "checked_at": now, **extra})


@pytest.fixture
def tail_env(monkeypatch, tmp_path):
    monkeypatch.setenv("XHS_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: None)
    monkeypatch.setattr(att, "fetch_related_file", None, raising=False)
    return tmp_path


def test_tail_only_looks_at_guest_unseen_and_gone_needs_two_nights(tail_env, monkeypatch, capsys):
    _unseen("gg01")
    _obj("gg02")  # 没查过的归游客段，收尾段不看
    seen = []
    monkeypatch.setattr(att, "_probe_logged_in", lambda n, t: seen.append(n) or {
        "ok": False, "path": "/explore", "wall": True, "has_note": False, "gone_like": True, "error": "落到 /explore"})
    monkeypatch.setattr(att, "_now_local", lambda: datetime(2026, 10, 9, 4, 30, tzinfo=TZ))
    assert cli.main(["attachments", "--recheck", "--logged-in-tail"]) == 0
    capsys.readouterr()
    assert seen == ["gg01"] and _mark("gg01")["stage"] == "gone_suspected" and not _mark("gg01").get("gone")
    monkeypatch.setattr(att, "_now_local", lambda: datetime(2026, 10, 10, 4, 30, tzinfo=TZ))
    storage.write_json(storage.archive_root() / "xiaohongshu" / "gg01" / "derived" / "web_recheck.json",
                       {**_mark("gg01"), "guest_at": "2026-10-10T04:00:00+11:00"})
    assert cli.main(["attachments", "--recheck", "--logged-in-tail"]) == 0
    m = _mark("gg01")
    assert m["gone"] is True and att.probe_state(storage.archive_root() / "xiaohongshu" / "gg01") == "gone"
    audit = json.loads((capsys.readouterr().out.strip().splitlines() or ["{}"])[-1])
    assert audit["gone"] == 1


def test_tail_fresh_token_settles_gone_in_one_night(tail_env, monkeypatch, capsys):
    _unseen("hh01")
    storage.write_json(att.fav_tokens_path(), {"tokens": {"hh01": {"token": "NEW_FAKE",
                                                                  "at": datetime.now().astimezone().isoformat()}}})
    used = []
    monkeypatch.setattr(att, "_probe_logged_in", lambda n, t: used.append(t) or {
        "ok": False, "path": "/404", "gone_like": True, "error": "404"})
    att.recheck_tail()
    assert used == ["NEW_FAKE"] and _mark("hh01")["gone"] is True


def test_tail_login_wall_stops_and_never_judges_gone(tail_env, monkeypatch, capsys):
    _unseen("ii01")
    _unseen("ii02")
    calls = []
    monkeypatch.setattr(att, "_probe_logged_in", lambda n, t: calls.append(n) or {
        "ok": False, "needs_human": True, "code": "NOT_LOGGED_IN", "path": "/login", "error": "游客"})
    assert cli.main(["attachments", "--recheck", "--logged-in-tail"]) == 5
    assert len(calls) == 1 and not _mark("ii01").get("gone")


def test_tail_stops_on_first_service_failure(tail_env, monkeypatch, capsys):
    for i in range(4):
        _unseen(f"jj{i:02d}")
    calls = []
    monkeypatch.setattr(att, "_probe_logged_in", lambda n, t: calls.append(n) or {
        "ok": False, "code": "TIMEOUT", "error": "TIMEOUT 读取服务响应超时"})
    assert cli.main(["attachments", "--recheck", "--logged-in-tail"]) == 0
    assert len(calls) == 1, "09-29 连着 4 次 TIMEOUT 还开页：第一次就收工"
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["stopped_reason"] == "service"


def test_tail_limit_five(tail_env, monkeypatch, capsys):
    for i in range(8):
        _unseen(f"kk{i:02d}")
    calls = []
    monkeypatch.setattr(att, "_probe_logged_in", lambda n, t: calls.append(n) or {"ok": True, "related_file": None})
    assert cli.main(["attachments", "--recheck", "--logged-in-tail"]) == 0
    assert len(calls) == 5


# --------------------------------------------------------------------------
# 本地对账 / 下载退避 / 状态 / 面板 / 夜跑
# --------------------------------------------------------------------------


def test_reconcile_declares_found_file_and_turns_explore_evidence_into_gone(capsys):
    a = _obj("ll01", mark={"ok": True, "related_file": RF, "download_error": "下载 3 次超时"})
    _obj("ll02", mark={"ok": False, "checked_at": "2026-10-05T04:40:00",
                       "error": "笔记页里没有这条笔记；登录看：登录也打不开这篇（/explore：多半已删或仅作者可见）"})
    problems.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", "没查清", item_id="xhs-ll02")
    assert cli.main(["attachments", "--reconcile"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out == {"cleared": 1, "declared": 1, "gone": 1}
    assert att.probe_state(a) == "checked" and att.inventory(a)["missing"] == 1, "如实显示「未下载 1 个」，不说全部已保存"
    assert _mark("ll02")["gone"] is True and not problems.is_open("attachments.recheck", "xhs-ll02", "PROBE_FAILED")
    assert cli.main(["attachments", "--reconcile"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"cleared": 0, "declared": 0, "gone": 0}


def test_download_backoff_across_nights(monkeypatch):
    obj = _obj("mm01", mark={"ok": True, "related_file": RF})
    att.reconcile()
    tries = []

    def failing(source_key, source_id, **kw):
        tries.append(kw.get("tries"))
        raise att.AttachmentError("下载超时")

    monkeypatch.setattr(att, "acquire", failing)
    monkeypatch.setattr(att, "local_download", lambda name: None)
    att.download_for_object("xiaohongshu", "mm01")
    assert tries == [None]
    out = att.download_for_object("xiaohongshu", "mm01")
    assert tries == [None] and out["results"][0]["status"] == "backoff", "退避期内不开页"
    state = storage.read_json(obj / "attachment-state.json")
    state["download_backoff"]["fake-doc-0001"]["next_at"] = "2020-01-01T00:00:00+11:00"
    storage.write_json(obj / "attachment-state.json", state)
    att.download_for_object("xiaohongshu", "mm01")
    assert tries == [None, 1], "退避到点后一晚只试 1 次"


def test_skipped_tail_is_recorded_and_shows_in_last_runs(capsys):
    _unseen("nn01")
    assert cli.main(["attachments", "--recheck-status", "--skipped", "号要验证，碰号的步骤今晚跳过"]) == 0
    st = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert st["tail_pending"] == 1 and "没跑" in st["text"]
    run = problems.summary()["last_runs"]["attachments.recheck"]
    assert run["skipped"].startswith("号要验证")


def test_repair_describe_recheck_reports_real_state(monkeypatch):
    _unseen("oo01")
    att.write_recheck_status("tail", {"checked": 0, "skipped": "号要验证", "stopped_reason": "skipped"})
    three_days = lambda: datetime.now().astimezone() - timedelta(days=3)  # noqa: E731
    problems.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", "没查清", item_id="xhs-oo01", _now_fn=three_days)
    row = next(r for r in problems.load() if r["item_id"] == "xhs-oo01")
    assert "已经 3 晚没进展" in row["status_text"] and "号处理好后的第一晚" in row["status_text"]
    assert "等到" not in row["status_text"]


def test_nightly_skipped_tail_writes_status(tmp_path):
    _unseen("pp01")
    n = nightly.Nightly(log_path=tmp_path / "n.log", workdir=tmp_path)
    n.account_stop, n.account_stop_why = True, "收藏同步退出 5（要人处理）"
    step = next(s for s in nightly.default_steps() if s.name == nightly.TAIL_STEP)
    assert n.run_step(step).skipped
    st = storage.read_json(att.status_path())
    assert st["tail"]["skipped"].startswith("号要处理") and st["phase"] == "tail"
    guest = next(s for s in nightly.default_steps() if "--guest-only" in s.args)
    assert guest.account is False, "游客段不算碰号：号出事的晚上照跑"
    names = [s.name for s in nightly.default_steps()]
    assert names.index(guest.name) < names.index("attachments --all") < names.index(nightly.TAIL_STEP)


@pytest.mark.real_web_probe
def test_captcha_page_stops_before_guest_browser(monkeypatch):
    """游客页上有验证专用词：带保险丝时立刻停、不起游客浏览器兜底；不带（入库探测）照旧兜底。"""
    class FakeResp:
        text = '<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{}}}</script><div>请完成安全验证 滑块</div>'

        def raise_for_status(self):
            return None

    browser = []
    monkeypatch.setattr(xhs.httpx, "get", lambda *a, **k: FakeResp())
    monkeypatch.setattr(xhs, "_probe_related_file_via_browser",
                        lambda *a, **k: browser.append(1) or {"ok": False, "error": "游客浏览器也没读到这条笔记"})
    out = xhs.fetch_related_file("0000000000000000deadbeef", "tok", stop_on_captcha=True)
    assert out["captcha"] is True and out["ok"] is False and browser == []
    out = xhs.fetch_related_file("0000000000000000deadbeef", "tok")
    assert browser == [1] and not out.get("captcha") and out.get("browser_error") is False


class _Resp:
    def __init__(self, text="", status=200, url="https://example.invalid/explore/x"):
        self.text, self.status_code, self.url = text, status, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.mark.parametrize("resp", [
    _Resp("<html><div>访问频繁，请稍后再试</div></html>"),                      # 没有 __INITIAL_STATE__ 的验证页
    _Resp("<html>blocked</html>", status=461),                                  # 风控状态码
    _Resp("<html>请登录</html>", url="https://example.invalid/website-login/captcha?redirectPath=x"),  # 302 跳到验证
], ids=["no-state-captcha", "status-461", "redirect-website-login"])
@pytest.mark.real_web_probe
def test_captcha_variants_stop_without_browser(guest_env, monkeypatch, resp):
    """审查意见：各种验证页形态都要立刻停——不起游客浏览器兜底，补查第 1 篇就以 captcha 停下。"""
    browser = []
    monkeypatch.setattr(xhs.httpx, "get", lambda *a, **k: resp)
    monkeypatch.setattr(xhs, "_probe_related_file_via_browser",
                        lambda *a, **k: browser.append(1) or {"ok": False, "error": "游客浏览器也没读到这条笔记"})
    out = xhs.fetch_related_file("0000000000000000deadbeef", "tok", stop_on_captcha=True)
    assert out["captcha"] is True and out["ok"] is False and browser == []
    for i in range(3):
        _obj(f"cv{i:02d}")
    out = att.recheck_guest()
    assert out["stopped_reason"] == "captcha" and browser == []


@pytest.mark.real_web_probe
def test_normal_page_mentioning_captcha_word_is_not_stopped(monkeypatch):
    """正常笔记页正文里提到「验证码」不算撞验证。"""
    page = ('<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"0000000000000000deadbeef":'
            '{"note":{"title":"教你收验证码"}}}}}</script>')
    monkeypatch.setattr(xhs.httpx, "get", lambda *a, **k: _Resp(page))
    out = xhs.fetch_related_file("0000000000000000deadbeef", "tok", stop_on_captcha=True)
    assert out["ok"] is True and not out.get("captcha")
