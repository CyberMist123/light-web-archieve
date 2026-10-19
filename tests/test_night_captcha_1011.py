"""1011（作者：夜里正常跑就行）：没人看着时撞的验证码先不推，冷却 45 分钟自查一次（只开本号主页），干净就自动恢复接着跑；
还在就今晚安静停，连着两晚才推一次「小红书弹了验证（不是掉登录）」。掉登录 / 风控跳页照旧当场推。

读取服务一律是假的（accounts.api 替身），不起服务、不联网、不开页。合成数据。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from link_brain import accounts, cli, comment_fill, night_captcha, problems, storage, sync_state
from link_brain import nightly as nightly_mod

TZ = timezone(timedelta(hours=11))
T0 = datetime(2026, 10, 11, 4, 2, 37, tzinfo=TZ)   # 撞验证的时刻


def _hold(code="CAPTCHA_REQUIRED", since=T0):
    return {"code": code, "since": since.isoformat(), "detail": "captcha-element", "tab": "fav", "want_tab": "fav"}


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += timedelta(seconds=s)


class FakeReader:
    """假读取服务：/login/session 回熔断；/risk/probe 按脚本回结论（cleared 时熔断跟着没了）。"""

    def __init__(self, monkeypatch, hold, probe="cleared"):
        self.hold, self.probe, self.calls = hold, probe, []
        monkeypatch.setattr(accounts, "api", self)
        monkeypatch.setattr(accounts, "ensure_reader", lambda **k: {"risk_hold": self.hold})

    def __call__(self, method, route, **kw):
        self.calls.append((method, route, kw.get("body")))
        if route == "/api/v1/risk/probe":
            if isinstance(self.probe, Exception):
                raise self.probe
            res = self.probe
            if res == "cleared":
                self.hold = None
            return {"result": res, "hold_since": T0.isoformat()}
        if route == "/api/v1/login/session":
            return {"risk_hold": self.hold}
        raise AssertionError(f"不该调 {route}")

    def probes(self):
        return [c for c in self.calls if c[1] == "/api/v1/risk/probe"]


@pytest.fixture
def pushes(monkeypatch):
    out = []
    monkeypatch.setattr("link_brain.alert._alert", lambda kind, title, body, **k: out.append((title, body, k)) or True)
    return out


@pytest.fixture
def night(monkeypatch):
    monkeypatch.setenv(night_captcha.ENV_UNATTENDED, "nightly")


def _rows(step="login", include_resolved=False):
    return [r for r in problems.load(include_resolved=include_resolved) if r["step"] == step]


# ---------------------------------------------------------------- 撞上时：先不叫她

def test_night_captcha_is_listed_not_pushed(night, pushes):
    problems.report_blocked("sync.favorites", "CAPTCHA_REQUIRED", "读收藏时判到验证")
    sync_state.account_problem("CAPTCHA_REQUIRED", "再从别的路撞见一次")
    assert pushes == [], "夜里撞验证不当场推"
    rows = _rows()
    assert [r["code"] for r in rows] == ["TRANSIENT.NIGHT_CAPTCHA"]
    assert rows[0]["group"] == "auto" and "不是掉登录" in rows[0]["reason"] and "冷却 45 分钟" in rows[0]["reason"]
    assert night_captcha.night()["incidents"] == 2
    from link_brain import repair
    plan = repair.plan(rows[0])
    assert plan["kind"] == "wait", "自愈轮绝不开页、不清熔断"


def test_daytime_captcha_also_deferred(pushes):
    """1019 她：非她本人不可的才叫她——白天撞的验证也先冷却自查。"""
    problems.report_blocked("sync.favorites", "CAPTCHA_REQUIRED", "她自己点的同步撞了验证")
    assert pushes == []
    assert _rows()[0]["code"] == "TRANSIENT.NIGHT_CAPTCHA"


def test_night_login_expired_and_risk_jump_still_pushed(night, pushes):
    problems.report_blocked("sync.favorites", "NOT_LOGGED_IN", "游客")
    problems.report_blocked("sync.favorites", "ACCOUNT_RISK", "跳到安全页")
    assert [p[2]["code"] for p in pushes] == ["NEEDS_HUMAN.NOT_LOGGED_IN", "NEEDS_HUMAN.ACCOUNT_RISK"]


def test_night_risk_hold_deferred_only_when_cause_is_captcha(night, pushes, monkeypatch):
    profile = accounts.profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "risk-hold.json").write_text(json.dumps(_hold()), "utf-8")
    problems.report_blocked("attachments.download", "RISK_HOLD", "熔断中")
    assert pushes == [] and _rows()[0]["code"] == "TRANSIENT.NIGHT_CAPTCHA"
    (profile / "risk-hold.json").write_text(json.dumps(_hold("NOT_LOGGED_IN")), "utf-8")
    problems.report_blocked("attachments.download", "RISK_HOLD", "熔断中")
    assert [p[2]["code"] for p in pushes] == ["NEEDS_HUMAN.RISK_HOLD"]


# ---------------------------------------------------------------- 冷却后自查

def test_cooling_opens_nothing(night, pushes, monkeypatch):
    fake = FakeReader(monkeypatch, _hold())
    clock = Clock(T0 + timedelta(minutes=10))
    out = night_captcha.recover(now_fn=clock)
    assert out["result"] == "cooling" and out["exit"] == 5 and fake.probes() == []
    assert 34 * 60 <= out["retry_after_s"] <= 35 * 60 + 1


def test_wait_then_probe_clean_recovers_and_leaves_audit(night, pushes, monkeypatch):
    problems.report_blocked("sync.favorites", "CAPTCHA_REQUIRED", "读收藏时判到验证")
    fake = FakeReader(monkeypatch, _hold())
    clock = Clock(T0 + timedelta(minutes=5))
    seen_probe_at = []
    real = fake.__call__

    def spy(method, route, **kw):
        if route == "/api/v1/risk/probe":
            seen_probe_at.append(clock.now)
        return real(method, route, **kw)
    monkeypatch.setattr(accounts, "api", spy)
    out = night_captcha.recover(wait=True, sleep=clock.sleep, now_fn=clock)
    assert out["result"] == "cleared" and out["exit"] == 0
    assert seen_probe_at and seen_probe_at[0] >= T0 + timedelta(minutes=45), "冷却满 45 分钟才查"
    assert fake.probes()[0][2]["cooldown_s"] == 45 * 60
    assert pushes == []
    assert _rows() == [], "列表里不留（已解决）"
    audit = [r for r in _rows(include_resolved=True) if r["code"] == "TRANSIENT.NIGHT_CAPTCHA"]
    assert audit and audit[0]["resolved_at"] and night_captcha.AUTO_CLEAR_REASON in audit[0]["reason"]
    assert night_captcha.night(night_captcha.night_key(clock.now))["result"] == "recovered"
    assert not accounts.lock_path().exists(), "查完放掉账号锁"


def test_probe_takes_account_lock(night, monkeypatch):
    FakeReader(monkeypatch, _hold())

    def busy(owner, wait_s=0, **k):
        raise accounts.AccountBusyError({"owner": "sync-favorites"})
    monkeypatch.setattr(accounts, "account_session", busy)
    out = night_captcha.recover(now_fn=Clock(T0 + timedelta(hours=1)))
    assert out["result"] == "busy" and out["exit"] == 6
    assert not night_captcha.night(night_captcha.night_key(T0 + timedelta(hours=1))).get("probe_at"), "没查就不算查过"


def test_not_captcha_keeps_old_behaviour(night, monkeypatch):
    fake = FakeReader(monkeypatch, _hold("NOT_LOGGED_IN"))
    out = night_captcha.recover(wait=True, now_fn=Clock(T0 + timedelta(hours=2)))
    assert out["result"] == "not_captcha" and out["exit"] == 5 and fake.probes() == []


def test_still_there_stops_quietly_then_second_night_pushes_once(night, pushes, monkeypatch):
    problems.report_blocked("sync.favorites", "CAPTCHA_REQUIRED", "第一晚")
    fake = FakeReader(monkeypatch, _hold(), probe="still_risk")
    first = night_captcha.recover(now_fn=Clock(T0 + timedelta(minutes=50)))
    assert first["result"] == "still_risk" and first["exit"] == 5 and not first["escalated"]
    assert pushes == [], "第一晚还在：今晚安静停"
    assert _rows()[0]["code"] == "TRANSIENT.NIGHT_CAPTCHA"
    # 同一晚再来一次（比如后台补评论又撞上）：不再开页
    again = night_captcha.recover(now_fn=Clock(T0 + timedelta(hours=3)))
    assert again["result"] == "already_tried" and len(fake.probes()) == 1 and pushes == []
    # 第二晚：熔断留到了下一晚，冷却早过了，自查还在 → 推一次
    second = night_captcha.recover(now_fn=Clock(T0 + timedelta(days=1, minutes=45)))
    assert second["result"] == "still_risk" and second["escalated"] is True
    assert len(pushes) == 1 and pushes[0][0] == "小红书弹了验证（不是掉登录）"
    assert "连着 2 晚" in pushes[0][1]
    codes = [r["code"] for r in _rows()]
    assert codes == ["NEEDS_HUMAN.CAPTCHA_REQUIRED"], codes
    # 同一晚再撞：不再推
    night_captcha.recover(now_fn=Clock(T0 + timedelta(days=1, hours=5)))
    assert len(pushes) == 1


def test_recovered_night_breaks_the_streak(night, pushes, monkeypatch):
    fake = FakeReader(monkeypatch, _hold(), probe="still_risk")
    night_captcha.recover(now_fn=Clock(T0 + timedelta(minutes=50)))
    fake.hold, fake.probe = _hold(since=T0 + timedelta(days=1)), "cleared"
    assert night_captcha.recover(now_fn=Clock(T0 + timedelta(days=1, minutes=50)))["exit"] == 0
    fake.hold, fake.probe = _hold(since=T0 + timedelta(days=2)), "still_risk"
    out = night_captcha.recover(now_fn=Clock(T0 + timedelta(days=2, minutes=50)))
    assert out["escalated"] is False and pushes == [], "中间那晚自己好了：不算连着两晚"


def test_once_per_night_even_after_recovery(night, monkeypatch):
    fake = FakeReader(monkeypatch, _hold())
    assert night_captcha.recover(now_fn=Clock(T0 + timedelta(minutes=46)))["exit"] == 0
    fake.hold = _hold(since=T0 + timedelta(hours=2))   # 恢复后同一晚又撞了一次
    out = night_captcha.recover(now_fn=Clock(T0 + timedelta(hours=4)))
    assert out["result"] == "already_tried" and len(fake.probes()) == 1


def test_probe_finds_guest_pushes_login(night, pushes, monkeypatch):
    FakeReader(monkeypatch, _hold(), probe="not_logged_in")
    out = night_captcha.recover(now_fn=Clock(T0 + timedelta(hours=1)))
    assert out["result"] == "not_logged_in" and out["exit"] == 5
    assert [p[2]["code"] for p in pushes] == ["NEEDS_HUMAN.NOT_LOGGED_IN"], "掉登录照旧当场推"


def test_old_reader_without_probe_counts_as_unrecovered(night, pushes, monkeypatch):
    FakeReader(monkeypatch, _hold(), probe=accounts.ReaderError("HTTP_404", "not found"))
    out = night_captcha.recover(now_fn=Clock(T0 + timedelta(hours=1)))
    assert out["result"] == "unsupported" and out["exit"] == 5 and pushes == []


def test_cooldown_floor(monkeypatch):
    monkeypatch.setenv(night_captcha.ENV_COOLDOWN, "1")
    assert night_captcha.cooldown_min() == 30
    assert night_captcha.cooldown_min(60) == 60


def test_cli_prints_one_json_and_exit(night, monkeypatch, capsys):
    FakeReader(monkeypatch, _hold(since=datetime.now().astimezone() - timedelta(hours=1)))
    code = cli.main(["captcha-recover", "--cooldown-min", "45"])
    lines = capsys.readouterr().out.strip().splitlines()
    out = json.loads(lines[-1]) if lines[-1].startswith("{") else json.loads("\n".join(lines))
    assert code == 0 and out["result"] == "cleared" and out["ok"] is True


# ---------------------------------------------------------------- 后台补评论

def test_background_fill_cools_down_probes_then_resumes(monkeypatch, pushes, tmp_path):
    """后台补评论撞验证：等冷却（不开页）→ 自查干净 → 接着补；不推送。"""
    answers = iter([("CAPTCHA_REQUIRED", "要验证"), ("CAPTCHA_REQUIRED", "要验证"), ("", "")])
    monkeypatch.setattr(comment_fill, "account_wait_reason", lambda: next(answers, ("", "")))
    monkeypatch.setattr(comment_fill, "nightly_busy", lambda *a, **k: "")
    monkeypatch.setattr(accounts, "lock_wanted", lambda: False)
    results = iter([{"result": "cooling", "retry_after_s": 600, "ready_at": "2026-10-11T04:47:37+11:00"},
                    {"result": "cleared"}])
    calls = []
    monkeypatch.setattr(night_captcha, "recover", lambda **k: calls.append(k) or next(results))
    ready = [{"item_id": "xhs-a", "title": "t"}]
    monkeypatch.setattr(comment_fill, "survey", lambda floors=None: {"ready": ready if not filled else [], "cooling": [],
                                                                    "pending": 0 if filled else 1, "stuck": [],
                                                                    "floors": 10, "total": 1, "missing": 0})
    filled = []
    monkeypatch.setattr(comment_fill, "fill_one", lambda item_id, **k: filled.append(item_id) or {"done": True, "filled": 1})
    monkeypatch.setattr(comment_fill.Status, "counts", lambda self, sv: None)
    naps = []
    assert comment_fill.run(SimpleNamespace(until_done=True, budget_min=0, limit=0, verbose=False), sleep=naps.append) == 0
    assert filled == ["xhs-a"], "自查干净后接着补"
    assert len(calls) == 2 and all(k.get("wait") is False for k in calls), "后台不在自查里干等，按冷却时间打盹"
    assert sum(naps) >= 600
    assert night_captcha.unattended(), "后台补评论标了「没人看着」"
    assert pushes == []


def test_background_fill_stops_quietly_when_still_there(monkeypatch, pushes):
    monkeypatch.setattr(comment_fill, "account_wait_reason", lambda: ("CAPTCHA_REQUIRED", "要验证"))
    monkeypatch.setattr(comment_fill, "nightly_busy", lambda *a, **k: "")
    monkeypatch.setattr(accounts, "lock_wanted", lambda: False)
    monkeypatch.setattr(night_captcha, "recover", lambda **k: {"result": "still_risk", "message": "冷却后自查验证还在：今晚先停"})
    monkeypatch.setattr(comment_fill, "survey", lambda floors=None: {"ready": [{"item_id": "xhs-a", "title": "t"}],
                                                                    "cooling": [], "pending": 1, "stuck": [],
                                                                    "floors": 10, "total": 1, "missing": 0})
    monkeypatch.setattr(comment_fill, "fill_one", lambda *a, **k: pytest.fail("验证还在：一页不开"))
    monkeypatch.setattr(comment_fill.Status, "counts", lambda self, sv: None)
    rc = comment_fill.run(SimpleNamespace(until_done=True, budget_min=0, limit=0, verbose=False), sleep=lambda s: None)
    assert rc == 0 and pushes == []


# ---------------------------------------------------------------- 包内夜跑

def test_nightly_recovers_and_reruns_skipped_account_steps(tmp_path, monkeypatch):
    """收藏同步撞验证退出 5 → 离线步骤照跑 → 自查（退出 0）→ 按名单补抓 + 补跑跳过的碰号步骤。不读收藏列表第二次。"""
    ran = []
    codes = {"sync-favorites": 5, "captcha-recover": 0}

    def fake_run_step(self, step, *, env_extra=None):
        r = nightly_mod.StepResult(step.name)
        if step.account and self.account_stop:
            r.skipped = True
            self.skipped_account.append(step)
            ran.append(("skip", step.name))
            return r
        r.code = codes.get(step.name, 0)
        ran.append(("run", step.name, tuple(step.args)))
        self._classify(step, r, step.timeout_min)
        return r

    monkeypatch.setattr(nightly_mod.Nightly, "run_step", fake_run_step)
    monkeypatch.setattr(nightly_mod.Nightly, "_sync_with_retry", lambda self, step: self.run_step(step))
    monkeypatch.setattr(nightly_mod.Nightly, "_refine", lambda self, step: self.run_step(step))
    monkeypatch.setattr(nightly_mod.Nightly, "_audit", lambda self, step: (self.run_step(step), 0))
    monkeypatch.setattr(nightly_mod.Nightly, "_repair_round", lambda self, since: None)
    job = nightly_mod.Nightly(log_path=tmp_path / "n.log")
    job.run()
    names = [x[1] for x in ran]
    i = names.index("captcha-recover")
    assert names.index("videos --transcribe") < i < names.index("embed"), "离线步骤跑完再自查"
    assert ("skip", "attachments --all") in ran and ("skip", "comments --fill-pending") in ran
    after = names[i + 1:]
    assert after[:4] == ["sync-favorites --from-snapshot", "attachments --all",
                         "attachments --recheck --logged-in-tail", "comments --fill-pending"]
    assert names.count("sync-favorites") == 1, "收藏列表不再读第二次"
    snap = next(x for x in ran if x[1] == "sync-favorites --from-snapshot")
    assert "--from-snapshot" in snap[2]
    assert not job.account_stop
    env = job._env()
    assert env[night_captcha.ENV_UNATTENDED] == "nightly"


def test_nightly_stays_stopped_when_recover_fails(tmp_path, monkeypatch):
    ran = []
    codes = {"sync-favorites": 5, "captcha-recover": 5}

    def fake_run_step(self, step, *, env_extra=None):
        r = nightly_mod.StepResult(step.name)
        if step.account and self.account_stop:
            r.skipped = True
            self.skipped_account.append(step)
            ran.append(("skip", step.name))
            return r
        r.code = codes.get(step.name, 0)
        ran.append(("run", step.name))
        self._classify(step, r, step.timeout_min)
        return r

    monkeypatch.setattr(nightly_mod.Nightly, "run_step", fake_run_step)
    monkeypatch.setattr(nightly_mod.Nightly, "_sync_with_retry", lambda self, step: self.run_step(step))
    monkeypatch.setattr(nightly_mod.Nightly, "_refine", lambda self, step: self.run_step(step))
    monkeypatch.setattr(nightly_mod.Nightly, "_audit", lambda self, step: (self.run_step(step), 0))
    monkeypatch.setattr(nightly_mod.Nightly, "_repair_round", lambda self, since: None)
    job = nightly_mod.Nightly(log_path=tmp_path / "n.log")
    out = job.run()
    names = [x[1] for x in ran if x[0] == "run"]
    assert "captcha-recover" in names and "sync-favorites --from-snapshot" not in names
    assert names.count("captcha-recover") == 1 and job.account_stop and out["exit"] == nightly_mod.EXIT_NEEDS_HUMAN
