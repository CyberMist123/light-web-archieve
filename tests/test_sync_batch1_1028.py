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


# ---------------------------------------------------------------- A5 拉起读取服务限流 + 等待按墙钟
import os
import types


def test_ensure_reader_spawns_at_most_once_per_gap(tmp_path, monkeypatch):
    from link_brain import procs
    from link_brain.sources.xiaohongshu import accounts
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.delenv("LINK_BRAIN_XHS_ENDPOINT", raising=False)
    monkeypatch.setattr(accounts, "reader_exe", lambda: str(tmp_path / "link-brain-reader.exe"))
    monkeypatch.setattr(accounts, "api", lambda *a, **k: (_ for _ in ()).throw(accounts.ReaderError("DISCONNECTED")))
    spawned = []
    monkeypatch.setattr(procs, "spawn_detached", lambda argv, **k: spawned.append(argv) or 4242)
    for _ in range(3):
        try:
            accounts.ensure_reader(wait=0)
        except accounts.ReaderError as exc:
            assert exc.code == "DISCONNECTED"
        else:
            raise AssertionError("服务没应答该抛 DISCONNECTED")
    assert len(spawned) == 1, "10 分钟内只拉起一次"
    assert 0 <= (accounts.last_spawn_age() or 0) < 5
    # 时间戳过期了（别的进程 11 分钟前拉的）→ 再拉一次
    (tmp_path / "home" / "reader-spawn.txt").write_text(str(__import__("time").time() - 11 * 60), "utf-8")
    try:
        accounts.ensure_reader(wait=0)
    except accounts.ReaderError:
        pass
    assert len(spawned) == 2
    # 时间戳坏了：当没拉过
    (tmp_path / "home" / "reader-spawn.txt").write_text("坏的", "utf-8")
    assert accounts.last_spawn_age() is None


def _loop_env(tmp_path, monkeypatch, entries):
    """跑 comment_fill.run 的最小环境：survey 固定、fill_one 打桩、状态写入记到列表。"""
    seen = []
    monkeypatch.setattr(cf.Status, "update", lambda self, **f: (self.data.update(f), seen.append(dict(self.data))))
    monkeypatch.setattr(cf, "survey", lambda *a, **k: {"floors": 10, "ready": list(entries), "cooling": [], "stuck": [],
                                                       "restricted": [], "missing": sum(e["missing"] for e in entries),
                                                       "pending": len(entries)})
    monkeypatch.setattr(cf, "_rebuild_catalog", lambda: None)
    monkeypatch.setattr(cf, "forget_unproven_gone", lambda: 0)
    monkeypatch.setattr(cf, "remember_reached_end", lambda: 0)
    monkeypatch.setattr(cf, "nightly_busy", lambda *a, **k: "")
    from link_brain.sources.xiaohongshu import accounts
    monkeypatch.setattr(accounts, "lock_wanted", lambda: False)
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    (tmp_path / "vault" / "_archive").mkdir(parents=True, exist_ok=True)
    return seen


ENTRY = {"item_id": "xhs-a", "title": "a", "mode": "floors", "targets": [], "missing": 3, "more_floors": True, "attempts": 0}


def test_wait_budget_counts_wall_clock_not_only_naps(tmp_path, monkeypatch):
    """号要人处理时的 12 小时上限按墙钟算：拉起服务 / 深查花掉的时间也算进去，不会因为「只歇了 N 次」多等。"""
    seen = _loop_env(tmp_path, monkeypatch, [ENTRY])
    monkeypatch.setattr(cf, "account_wait_reason", lambda: ("ACCOUNT_RISK", "被跳到安全页"))
    monkeypatch.setattr(cf, "sub_quota", lambda now=None: (30, None))
    clock = [0.0]
    naps = []

    def sleep(s):
        naps.append(s)
        clock[0] += s + 3600  # 每次歇完还被别的事（拉起服务 / 深查）耗掉一小时

    args = types.SimpleNamespace(until_done=True, budget_min=0, limit=0, verbose=False, only=None, floors="",
                                 then_background=False, wait_lock_min=2)
    assert cf.run(args, sleep=sleep, clock=lambda: clock[0]) == 0
    assert sum(naps) < cf.MAX_WAIT_S, "按歇的时间算远没到 12 小时，按墙钟算到了"
    assert clock[0] > cf.MAX_WAIT_S
    assert "等了 12 小时" in str(seen[-1]["message"])


# ---------------------------------------------------------------- B2 续读期间的心跳 + 自动解熔断看截止时间
import time as _time


def test_status_heartbeat_keeps_updated_at_fresh_during_fill(tmp_path, monkeypatch):
    """fill_one 跑 3 个心跳周期，updated_at 至少刷 2 次；状态文件带 stale_min 给插件用。"""
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    (tmp_path / "vault" / "_archive").mkdir(parents=True)
    st = cf.Status(10, background=True)
    writes = []
    real = st.update

    def spy(**f):
        real(**f)
        writes.append(st.data["updated_at"])
    monkeypatch.setattr(st, "update", spy)
    with st.heartbeat(every=0.05):
        _time.sleep(0.3)
    assert len(writes) >= 2
    assert cf.read_status()["stale_min"] == cf.STALE_MIN == 15
    # 心跳停了之后不再写
    n = len(writes)
    _time.sleep(0.15)
    assert len(writes) == n


def test_auto_clear_refuses_when_budget_deadline_too_close(monkeypatch):
    from link_brain.sources.xiaohongshu import accounts
    monkeypatch.setattr(accounts, "CAPTCHA_AUTO_MAX", 3)
    monkeypatch.setattr(accounts, "_auto_cleared", 0)
    monkeypatch.setattr(accounts.time, "sleep", lambda s: None)
    cleared = []
    monkeypatch.setattr(accounts, "_api", lambda *a, **k: cleared.append(a) or {})
    try:
        accounts.set_auto_clear_deadline(_time.monotonic() + 120)      # 只剩 2 分钟，歇 5 分钟不够
        assert accounts._pause_and_clear("测试", 300) is False and cleared == []
        accounts.set_auto_clear_deadline(_time.monotonic() + 3600)     # 够
        assert accounts._pause_and_clear("测试", 300) is True and len(cleared) == 1
        accounts.set_auto_clear_deadline(None)                         # 不限
        assert accounts._pause_and_clear("测试", 300) is True and len(cleared) == 2
    finally:
        accounts.set_auto_clear_deadline(None)
    # 夜跑那一步的预留时间把歇 5 分钟算进去
    monkeypatch.setattr(accounts, "CAPTCHA_AUTO_MAX", 0)
    base = cf.fill_reserve_s()
    monkeypatch.setattr(accounts, "CAPTCHA_AUTO_MAX", 3)
    assert cf.fill_reserve_s() == base + accounts.CAPTCHA_PAUSE_S


# ---------------------------------------------------------------- A1 普通重抓不许把评论变少 / 变 0
from link_brain import cli, storage
from link_brain.adapters import xiaohongshu as xhs
from test_comments_fill_1009 import _floor, _raw, _ingest, NOTE_ID
from test_render import setup_env


def _floors_of(src):
    return [(c["comment_id"], len(c.get("sub_comments") or [])) for c in src.get("comments") or []]


def test_refresh_unions_comments_and_never_publishes_zero(tmp_path, monkeypatch, capsys):
    """`ingest --refresh` / `comments <链接>` 走普通抓取：评论和上一版并集；这次一楼没读到就不发布新版本。"""
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 2, 2), _floor("c2", 2, 2), _floor("c3", 2, 2)], has_more=False))
    meta0, src0 = cf.current_source("xiaohongshu", NOTE_ID)
    assert len(src0["comments"]) == 3
    url = "https://example.invalid/share"

    # ① 这次只读到 1 楼、且那楼多了 1 条回复（楼数设置比存的少 / 页面只给首屏）→ 并集：3 楼都在，c1 变 3 条
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([_floor("c1", 3, 3)], has_more=True))
    assert cli.main(["ingest", url, "--refresh"]) in (0, 2)
    capsys.readouterr()
    meta1, src1 = cf.current_source("xiaohongshu", NOTE_ID)
    assert meta1["current_version"] == meta0["current_version"] + 1
    assert dict(_floors_of(src1)) == {"c1": 3, "c2": 2, "c3": 2}
    # 上一版翻到底的结论留着（1026 规矩）：这次 has_more=true 只说明楼数上限外还有
    assert src1["capture"]["comment_load"]["has_more"] is False

    # ② 这次 0 楼（软限流回空）→ 不发布新版本、当前版本不动、照实说原因
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([], has_more=False))
    import json as _json
    assert cli.main(["comments", url]) == 0
    out = _json.loads(capsys.readouterr().out)
    assert out.get("comments_kept") is True and "没读到评论" in out["message"]
    meta2, src2 = cf.current_source("xiaohongshu", NOTE_ID)
    assert meta2["current_version"] == meta1["current_version"]
    assert dict(_floors_of(src2)) == {"c1": 3, "c2": 2, "c3": 2}
    # raw 目录里没有多出来的版本
    assert sorted(p.name for p in (storage.object_dir("xiaohongshu", NOTE_ID) / "raw").glob("v*")) == \
        [storage.version_name(meta0["current_version"]), storage.version_name(meta1["current_version"])]


# ---------------------------------------------------------------- 已知 bug #4：--detach 透传参数
def test_detach_passes_only_floors_limit_budget_to_worker(tmp_path, monkeypatch, capsys):
    from link_brain import procs, deps
    import json as _json
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    (tmp_path / "vault" / "_archive").mkdir(parents=True)
    monkeypatch.setattr(cf, "read_status", lambda: {})
    monkeypatch.setattr(deps, "python_exe", lambda: "py")
    seen = {}
    monkeypatch.setattr(procs, "spawn_detached", lambda argv, **k: seen.update(argv=argv) or 777)
    assert cli.main(["comments", "--fill-pending", "--detach", "--only", "xhs-a,xhs-b", "--only", "xhs-c",
                     "--floors", "50", "--limit", "3", "--budget-min", "40"]) == 0
    out = _json.loads(capsys.readouterr().out)
    assert out["ok"] and out["started"]
    argv = seen["argv"]
    assert argv[:6] == ["py", "-m", "link_brain", "comments", "--fill-pending", "--until-done"]
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--only"] == ["xhs-a", "xhs-b", "xhs-c"]
    assert argv[argv.index("--floors") + 1] == "50"
    assert argv[argv.index("--limit") + 1] == "3" and argv[argv.index("--budget-min") + 1] == "40"
    # 不带参数：和以前一模一样（--floors 的默认值 all 不传，免得把全库按「全部」补）
    assert cf.worker_argv("py") == ["py", "-m", "link_brain", "comments", "--fill-pending", "--until-done"]
    assert cli.main(["comments", "--fill-pending", "--detach"]) == 0
    capsys.readouterr()
    assert seen["argv"] == ["py", "-m", "link_brain", "comments", "--fill-pending", "--until-done"]


# ---------------------------------------------------------------- B1 熔断提示按起因说
def test_wait_reason_text_follows_hold_cause(monkeypatch):
    from link_brain.sources.xiaohongshu import accounts as acc
    since = "2026-10-28T20:32:00+11:00"
    cases = {
        "CAPTCHA_REQUIRED": ("弹了验证", "打开验证"),
        "ACCOUNT_RISK": (acc.SOLUTIONS["ACCOUNT_RISK"][1], acc.SOLUTIONS["ACCOUNT_RISK"][2]),   # 被跳到登录 / 安全页 + 它的下一步
        "NOT_LOGGED_IN": ("掉登录", "扫码登录"),
    }
    for code, (must, step) in cases.items():
        monkeypatch.setattr(acc, "ensure_reader", lambda c=code: {"state": "idle", "logged_in": True,
                                                                  "risk_hold": {"code": c, "since": since, "detail": "x"}})
        got_code, why = cf.account_wait_reason()
        assert got_code == code
        assert must in why and step in why, (code, why)
        assert why.count("小红书") <= 2 and not why.startswith("小红书小红书"), why
        if code != "CAPTCHA_REQUIRED":
            assert "弹了验证" not in why, (code, why)


# ---------------------------------------------------------------- #8 等号时不每轮全库 survey
def test_survey_is_cached_while_waiting_and_recomputed_after_a_fill(tmp_path, monkeypatch):
    _loop_env(tmp_path, monkeypatch, [ENTRY])
    calls = {"survey": 0}
    opened = []

    def counting_survey(*a, **k):
        calls["survey"] += 1
        entries = [] if opened else [ENTRY]   # 开过一次就没缺口了
        return {"floors": 10, "ready": entries, "cooling": [], "stuck": [], "restricted": [],
                "missing": 3 * len(entries), "pending": len(entries)}
    monkeypatch.setattr(cf, "survey", counting_survey)
    monkeypatch.setattr(cf, "sub_quota", lambda now=None: (30, None))
    monkeypatch.setattr(cf.actionlog, "repeat_pause", lambda *a, **k: ("", None))
    answers = iter([("ACCOUNT_RISK", "等她")] * 5)   # 先等 5 轮（每轮 180 秒），再放行
    monkeypatch.setattr(cf, "account_wait_reason", lambda: next(answers, ("", "")))
    monkeypatch.setattr(cf, "fill_one", lambda item_id, **k: opened.append(item_id) or {"done": True})
    clock = [0.0]
    sleep = lambda s: clock.__setitem__(0, clock[0] + s)  # noqa: E731
    args = types.SimpleNamespace(until_done=True, budget_min=0, limit=0, verbose=False, only=None, floors="",
                                 then_background=False, wait_lock_min=2)
    assert cf.run(args, sleep=sleep, clock=lambda: clock[0]) == 0
    assert opened == ["xhs-a"]
    # 5 轮等待 900 秒：开头 1 + 过了 600 秒重算 1 + 开页后重算 1 + 收尾 1 = 4，而不是每轮一次（7+）
    assert calls["survey"] == 4, calls
