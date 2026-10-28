"""1028 审查第一批（同步 / 登录状态 / 补评论）的回归测试。每一项对应 REVIEW-1028 的一条：

- A7 夜跑让路只看 nightly.STEPS 里 Step.account（不碰号的步骤不让）。
"""
from __future__ import annotations

from link_brain import nightly
from link_brain.sources.xiaohongshu import comment_fill as cf


RUNNING = [{"state": "Running", "next": ""}]


def test_nightly_yield_follows_step_account_flag():
    """nightly.STEPS 每一步：碰号的让路、不碰号的不让；名单里没有的照旧让（宁可多等）。"""
    for step in nightly.STEPS:
        why = cf.nightly_busy(rows=RUNNING, step=step.name)
        if step.account:
            assert why, f"{step.name} 碰号，补评论该让路"
        else:
            assert why == "", f"{step.name} 不碰号，补评论不该让路"
    # 以前的名单漏掉的两步（1028 审查 A7）：游客段附件补查 150 分钟、索引补课 30 分钟，都不碰号
    assert cf.nightly_busy(rows=RUNNING, step="attachments --recheck --guest-only") == ""
    assert cf.nightly_busy(rows=RUNNING, step="index catch-up") == ""
    assert cf.step_touches_account("attachments --recheck --guest-only") is False
    assert cf.step_touches_account("sync-favorites") is True
    # 认不出的步骤（含快照同步这种临时 Step）照旧让路
    assert cf.step_touches_account("") is None and cf.step_touches_account("没有这一步") is None
    assert cf.nightly_busy(rows=RUNNING, step="sync-favorites --from-snapshot") != ""
    assert cf.nightly_busy(rows=RUNNING, step="") != ""


# ---------------------------------------------------------------- A6 楼中楼闸口径
import json
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=11))


def _profile(tmp_path, monkeypatch):
    from link_brain.sources.xiaohongshu import accounts
    monkeypatch.setattr(accounts, "profile_dir", lambda: tmp_path)
    monkeypatch.delenv("XHS_SUB_PER_HOUR", raising=False)
    return tmp_path


def test_sub_quota_is_zero_while_reader_gate_closed_by_strikes_or_hold(tmp_path, monkeypatch):
    """读取组件的闸还看 rate-limit-strikes.json（24h × n 暂停）和熔断文件；Python 以前只数点击，限频后照样挑篇开页。"""
    prof = _profile(tmp_path, monkeypatch)
    now = datetime(2026, 10, 28, 12, 0, tzinfo=TZ)
    assert cf.sub_quota(now) == (30, None)                      # 什么文件都没有：满额
    # 10 小时前被限频 1 次 → 楼中楼暂停到 24 小时后
    last = now - timedelta(hours=10)
    (prof / "rate-limit-strikes.json").write_text(json.dumps({"strikes": 1, "last": last.isoformat()}), "utf-8")
    left, until = cf.sub_quota(now)
    assert left == 0 and until == last + timedelta(hours=24)
    assert "限频 1 次" in cf.sub_gate_closed(now)[0]
    # 2 次 → 48 小时；30 小时前的 2 次已过 24 小时窗口 → 不算
    (prof / "rate-limit-strikes.json").write_text(json.dumps({"strikes": 2, "last": last.isoformat()}), "utf-8")
    assert cf.sub_quota(now) == (0, last + timedelta(hours=48))
    old = now - timedelta(hours=30)
    (prof / "rate-limit-strikes.json").write_text(json.dumps({"strikes": 2, "last": old.isoformat()}), "utf-8")
    assert cf.sub_quota(now) == (30, None)
    # 熔断文件在（验证类，冷却自查中）→ 0；限频类 → 0 且给到点时刻；到点自探中 → 0、没有时刻
    (prof / "risk-hold.json").write_text(json.dumps({"code": "CAPTCHA_REQUIRED", "since": now.isoformat()}), "utf-8")
    assert cf.sub_quota(now) == (0, None) and "CAPTCHA_REQUIRED" in cf.sub_gate_closed(now)[0]
    until = now + timedelta(hours=2)
    (prof / "risk-hold.json").write_text(json.dumps({"code": "XHS_RATE_LIMITED", "since": now.isoformat(),
                                                     "until": until.isoformat(), "strikes": 1}), "utf-8")
    assert cf.sub_quota(now) == (0, until)
    assert cf.sub_quota(now + timedelta(hours=3)) == (0, None)
    (prof / "risk-hold.json").write_text("坏的", "utf-8")
    assert cf.sub_quota(now) == (30, None)                      # 文件坏了：当没有（真闸在读取组件里）


def test_run_loop_skips_expand_entries_while_gate_closed(tmp_path, monkeypatch):
    """闸关着：只展开楼中楼的篇不开；要多读楼的篇照常。原因写进状态文件。"""
    monkeypatch.setattr(cf, "sub_quota", lambda now=None: (0, None))
    monkeypatch.setattr(cf, "sub_gate_closed", lambda now=None: ("24 小时内被限频 1 次，楼中楼暂停到 10-29 02:00", None))
    seen = []
    monkeypatch.setattr(cf.Status, "update", lambda self, **f: (self.data.update(f), seen.append(dict(self.data))))
    monkeypatch.setattr(cf, "survey", lambda *a, **k: {"floors": 10, "ready": [
        {"item_id": "xhs-a", "title": "a", "mode": "expand", "targets": ["c1"], "missing": 3, "more_floors": False, "attempts": 0}],
        "cooling": [], "stuck": [], "restricted": [], "missing": 3, "pending": 1})
    monkeypatch.setattr(cf, "_rebuild_catalog", lambda: None)
    monkeypatch.setattr(cf, "forget_unproven_gone", lambda: 0)
    monkeypatch.setattr(cf, "remember_reached_end", lambda: 0)
    import types
    opened = []
    monkeypatch.setattr(cf, "fill_one", lambda item_id, **k: opened.append(item_id) or {})
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    (tmp_path / "vault" / "_archive").mkdir(parents=True)
    args = types.SimpleNamespace(until_done=False, budget_min=0, limit=0, verbose=False, only=None, floors="",
                                 then_background=False, wait_lock_min=2)
    assert cf.run(args, sleep=lambda s: None) == 0
    assert opened == []
    assert any("限频 1 次" in str(s.get("message")) for s in seen)
