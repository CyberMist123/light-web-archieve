"""1001 审查意见的回归：已知坏篇也有闸、可疑收藏数不顶掉基准、同步 / 附件的时间预算、
泛化异常不误判成「号出事」、开页间隔从上一页看完算起、锁的陈旧判定与被接管后停手、
login --status 带熔断起因、--extract 先落同步状态再补概要。

入口一律是真的（favorites.run / cli.main / catch / attachments），只把网络那一侧换成假的。
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from link_brain import accounts, attachments as att_mod, cli, enrich, favorites, ingest as ingest_mod, storage, sync_state
from link_brain import pdftext
from link_brain.adapters import xiaohongshu as xhs

from test_account_safety import HOLD, Reader, _fake_mcp, _fav
from test_night_sync import FIXTURE, SESSION, _ids, _run, env  # noqa: F401 - env 是 fixture

_real_sleep = time.sleep


def _known_bad(ids, count=1):
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    storage.write_json(storage.archive_root() / "sync-failures.json",
                       {i: {"count": count, "error": "笔记不存在", "last": now} for i in ids})


# --------------------------------------------------------------------------
# must-fix：已知坏篇排最后，但连着失败 3 篇就收手（软限流时别一路开页）
# --------------------------------------------------------------------------


def test_known_bad_tail_stops_after_three_failures(env, capsys):
    bad = _ids(5, prefix="dddddddddddddddd")
    new = _ids(1)
    _known_bad(bad)
    env.favs = [_fav(i) for i in bad + new]
    env.fail = set(bad)
    code, out = _run(capsys)
    assert env.fetched[0] == new[0]  # 新的先抓
    assert len(env.fetched) == 1 + 3  # 已知坏篇最多开 3 篇
    assert out["held_known_bad"] == 2 and out.get("code") != "TOO_MANY_FAILURES"
    assert code == 0  # 以前就抓不到的再失败不算「同步出错」，不每晚报一次
    assert not any("连续" in a[1] for a in env.alerts)
    assert sync_state.load()["state"] == "ready"
    failures = storage.read_json(storage.archive_root() / "sync-failures.json")
    assert sorted(v["count"] for v in failures.values()) == [1, 1, 2, 2, 2]


def test_known_bad_that_comes_back_resets_the_streak(env, capsys):
    bad = _ids(5, prefix="dddddddddddddddd")
    _known_bad(bad)
    env.favs = [_fav(i) for i in bad]
    env.fail = {bad[0], bad[1], bad[3], bad[4]}  # 第 3 篇又能看了
    code, out = _run(capsys)
    assert env.fetched == bad and code == 0 and "held_known_bad" not in out


# --------------------------------------------------------------------------
# should-fix：可疑的收藏数不顶掉「上次正常读到的条数」
# --------------------------------------------------------------------------


def test_two_truncated_nights_in_a_row_both_flagged_but_pushed_once(env, capsys):
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 10})
    env.favs = [_fav(i) for i in _ids(4)]
    for night in range(2):
        env.alerts.clear()
        code, _ = _run(capsys)
        status = sync_state.load()
        assert code == 1 and status["code"] == "FAVORITES_SUSPICIOUS", night
        # 两晚都标可疑（问题列表看得到、这次不算同步成功）；收藏数可疑是临时故障，不推（连着 3 个日历日才升级）
        assert status["last_favorites"] == 10 and env.alerts == [], night
    # 连着第 3 晚还是差不多这个数：多半是她真删了一批 —— 这晚照样报，之后以它为基准
    code, _ = _run(capsys)
    assert code == 1 and sync_state.load()["last_favorites"] == 4
    env.alerts.clear()
    code, _ = _run(capsys)
    assert code == 0 and sync_state.load()["state"] == "ready" and not env.alerts


def test_zero_favorites_never_becomes_the_baseline(env, capsys):
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 10})
    env.favs = []
    for _ in range(4):
        assert _run(capsys)[0] == 1
    assert sync_state.load()["last_favorites"] == 10


# --------------------------------------------------------------------------
# should-fix：同步的时间预算管到每一篇（抓详情重试、顺手下附件）
# --------------------------------------------------------------------------


@pytest.fixture
def clock(monkeypatch):
    c = {"t": 10_000.0}
    monkeypatch.setattr(favorites, "_clock", lambda: c["t"])
    monkeypatch.setattr(att_mod, "_clock", lambda: c["t"])
    return c


def _ticking_fetch(env, clock, monkeypatch, minutes):
    def fetch(note_id, token, **kw):
        clock["t"] += minutes * 60
        env.fetched.append(note_id)
        return json.loads(FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setattr(xhs, "fetch_detail", fetch)


def test_sync_grabs_attachments_only_when_time_allows(env, clock, monkeypatch, capsys):
    grabbed = []
    monkeypatch.setattr(att_mod, "grab_after_ingest",
                        lambda key, sid, budget_left=None: grabbed.append((sid, budget_left())) or "")
    _ticking_fetch(env, clock, monkeypatch, 16)
    env.favs = [_fav(i) for i in _ids(3)]
    code, out = _run(capsys, budget_min=60)
    # 第 1 篇抓完剩 44 分钟 → 顺手下附件（带着剩余预算）；第 2 篇抓完剩 28 → 也下；
    # 第 3 篇开之前只剩 28 分钟 ≥ 15 → 抓，抓完剩 12 < 20 → 附件留给 4 点
    assert [sid for sid, _ in grabbed] == _ids(2) and grabbed[0][1] == pytest.approx(44 * 60)
    assert env.fetched == _ids(3) and code == 0


def test_sync_does_not_start_a_fetch_that_cannot_finish_in_budget(env, clock, monkeypatch, capsys):
    monkeypatch.setenv("LWA_FETCH_REST", "120,120")
    monkeypatch.setattr(att_mod, "grab_after_ingest", lambda *a, **k: "")
    _ticking_fetch(env, clock, monkeypatch, 4)
    env.favs = [_fav(i) for i in _ids(3)]
    code, out = _run(capsys, budget_min=20)
    # 第 1 篇后剩 16 分钟，再歇 2 分钟只剩 14 < 15：不开了，也不白歇
    assert env.fetched == _ids(1) and out["deferred"] == 2 and out["deferred_reason"] == "budget"
    assert 120 not in env.sleeps and code == 0
    assert sync_state.load()["message"] == "今天先到这，剩 2 篇明天继续"


def test_detail_retry_is_skipped_when_budget_cannot_hold_another_attempt(env, clock, monkeypatch, capsys):
    tries = []

    def down(note_id, token, **kw):
        clock["t"] += 8 * 60
        tries.append(note_id)
        raise xhs.ServiceDownError("读取服务未连接：timeout")
    monkeypatch.setattr(xhs, "fetch_detail", down)
    monkeypatch.setattr(ingest_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: None)
    env.favs = [_fav(_ids(1)[0])]
    code, _ = _run(capsys, budget_min=30)
    # 每次重试最坏要「等一轮 + 600 秒超时 + 60 秒」≈ 11–12 分钟。30 分钟预算：第 1 次后剩 22、第 2 次后剩 14，
    # 都装得下 → 试满 3 次。25 分钟预算：第 2 次后只剩 9 分钟，装不下 → 不再试
    assert len(tries) == 3 and code == 5
    tries.clear()
    code, _ = _run(capsys, budget_min=25)
    assert len(tries) == 2 and code == 5


# --------------------------------------------------------------------------
# should-fix：attachments --all / --recheck 的时间预算
# --------------------------------------------------------------------------

RELATED = {"name": "教程.pdf", "docId": "7658854832003020032", "bizExtra": '{"page_num":1}'}


def _catch(capsys, note_id):
    url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token=T"
    assert cli.main(["catch", f"存一下 {url}"]) == 0
    capsys.readouterr()


def _fake_download(clock, monkeypatch, minutes, downloads):
    def fetch_bytes(*, doc_id, note_id, xsec_token, file_name, staging_dir, verbose=False):
        clock["t"] += minutes * 60
        downloads.append(note_id)
        staging_dir.mkdir(parents=True, exist_ok=True)
        path = staging_dir / file_name
        path.write_bytes(b"%PDF-1.4 test")
        return path
    monkeypatch.setattr(att_mod, "fetch_bytes", fetch_bytes)
    monkeypatch.setattr(pdftext, "convert_object_attachments", lambda *a, **k: [])
    monkeypatch.setattr(att_mod, "convert_downloads", lambda *a, **k: [])


def test_attachments_all_stops_before_a_download_that_does_not_fit(env, clock, monkeypatch, capsys):
    monkeypatch.setattr(xhs, "fetch_related_file", lambda n, t, **kw: {
        "ok": True, "related_file": RELATED, "url": "https://example.invalid/n", "error": None})
    monkeypatch.setattr(att_mod, "grab_after_ingest", lambda *a, **k: "")
    ids = _ids(2, prefix="eeeeeeeeeeeeeeee")
    for i in ids:
        _catch(capsys, i)
    downloads = []
    _fake_download(clock, monkeypatch, 2, downloads)
    # 测试里 PACE=0、开页间隔=0：一次尝试最坏 = 240 秒下载 + 60 秒余量 = 5 分钟
    code = cli.main(["attachments", "--all", "--budget-min", "6"])
    captured = capsys.readouterr()
    assert code == 0 and downloads == ids[:1]  # 第 2 篇开之前只剩 4 分钟：不开
    assert "还有 1 篇没看" in captured.err and "目录已重建" in captured.out  # 正常收尾


def test_attachment_attempt_deferred_is_not_a_failure(env, clock, monkeypatch, capsys):
    monkeypatch.setattr(xhs, "fetch_related_file", lambda n, t, **kw: {
        "ok": True, "related_file": RELATED, "url": "https://example.invalid/n", "error": None})
    monkeypatch.setattr(att_mod, "grab_after_ingest", lambda *a, **k: "")
    sid = _ids(1, prefix="eeeeeeeeeeeeeeee")[0]
    _catch(capsys, sid)
    downloads = []
    _fake_download(clock, monkeypatch, 2, downloads)
    alerts = []
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: alerts.append(a))
    out = att_mod.download_for_object("xiaohongshu", sid, budget_left=lambda: 200.0)
    assert [r["status"] for r in out["results"]] == ["deferred"] and downloads == [] and not alerts
    state = storage.read_json(storage.object_dir("xiaohongshu", sid) / "attachment-state.json")
    assert state["errors"] == []


def test_recheck_budget_stops_probing_and_keeps_undownloaded_note_pending(env, clock, monkeypatch, capsys):
    monkeypatch.setattr(att_mod, "grab_after_ingest", lambda *a, **k: "")
    ids = _ids(2, prefix="ffffffffffffffff")
    for i in ids:
        _catch(capsys, i)  # conftest：网页探测失败 → 待补查

    probes = []

    def logged(note_id, token):
        clock["t"] += 60
        probes.append(note_id)
        return {"ok": True, "related_file": RELATED, "error": None}
    monkeypatch.setattr(att_mod, "_probe_logged_in", logged)
    downloads = []
    _fake_download(clock, monkeypatch, 2, downloads)
    # 补查一篇最坏 = 90 秒游客 + 150 秒登录号 = 4 分钟；下载一次最坏 5 分钟
    code = cli.main(["attachments", "--recheck", "--limit", "20", "--budget-min", "5"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["checked"] == 1 and out.get("out_of_time") and downloads == []
    first = storage.object_dir("xiaohongshu", probes[0])
    assert att_mod.probe_state(first) == "unprobed"  # 探到了但没时间下：明晚接着下


# --------------------------------------------------------------------------
# should-fix：泛化异常文本里的「429」「登录后」不再误判成号出事
# --------------------------------------------------------------------------


def _raising_mcp(monkeypatch, errors, calls):
    import anyio
    import mcp
    from mcp.client import streamable_http

    @contextlib.asynccontextmanager
    async def fake_client(endpoint, timeout=None, sse_read_timeout=None):
        async with anyio.create_task_group():
            yield (None, None, None)

    class FakeSession:
        def __init__(self, reader, writer):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            return None

        async def call_tool(self, tool, arguments):
            calls.append(arguments.get("feed_id"))
            raise errors.pop(0)

    monkeypatch.setattr(streamable_http, "streamablehttp_client", fake_client)
    monkeypatch.setattr(mcp, "ClientSession", FakeSession)


def test_generic_error_mentioning_429_is_not_account_blocked(monkeypatch, capsys):
    ids = ["aaaaaaaaaaaaa4290001", "aaaaaaaaaaaaa4290002", "aaaaaaaaaaaaa4290003"]
    Reader(monkeypatch, {"/api/v1/login/session": SESSION,
                         "/api/v1/favorites": {"nickname": "alice", "items": [_fav(i) for i in ids]}})
    calls, alerts = [], []
    _raising_mcp(monkeypatch, [ValueError("解析 note 6429 的响应失败：登录后可见的字段缺失"),
                               ValueError("解析失败 429"),
                               RuntimeError("页面被跳到 https://www.xiaohongshu.com/website-login/error")], calls)
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: alerts.append(a))
    code = favorites.run(SimpleNamespace(limit=0, origin="cli", actor="human", verbose=False, extract=False,
                                         budget_min=0, wait_lock_min=0))
    out = json.loads(capsys.readouterr().out)
    assert calls == ids  # 前两篇只是这篇出错，接着看下一篇
    assert [x["status"] for x in out["items"]] == ["error", "error", "blocked"]
    assert out["items"][-1]["code"] == "ACCOUNT_RISK" and code == 5  # 明确的风险跳转照样停


# --------------------------------------------------------------------------
# nit：开页间隔从上一页「看完」算起
# --------------------------------------------------------------------------


def test_gap_is_measured_from_the_end_of_a_long_page(env, monkeypatch, capsys):
    monkeypatch.setenv("LWA_OPEN_GAP", "1,1")
    slept = []
    monkeypatch.setattr(accounts.time, "sleep", slept.append)  # time.sleep 全局被换掉：读收藏那边用真 sleep

    def slow_favorites():
        _real_sleep(1.5)  # 读收藏滚了很久
        return {"nickname": "alice", "items": env.favs}
    env.reader.routes["/api/v1/favorites"] = slow_favorites
    env.favs = [_fav(_ids(1)[0])]
    code, _ = _run(capsys)
    assert code == 0 and env.fetched == _ids(1)
    # 读收藏开页时刻已经过去 1.5 秒，但页是刚看完的：抓第 1 篇前照样要歇（以前这里是零间隔）
    assert any(0.5 < s <= 1 for s in slept)


# --------------------------------------------------------------------------
# nit：锁——打不开进程 ≠ 进程没了；锁被接管后本进程停手
# --------------------------------------------------------------------------


def _write_lock(pid, heartbeat_age):
    path = accounts.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = time.time() - heartbeat_age
    path.write_text(json.dumps({"pid": pid, "owner": "sync-favorites", "started": "x",
                                "heartbeat": datetime.fromtimestamp(ts).astimezone().isoformat(), "heartbeat_ts": ts}),
                    "utf-8")


def test_pid_state_tells_dead_from_alive():
    assert accounts._pid_state(os.getpid()) == "alive"
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=30)
    assert accounts._pid_state(p.pid) == "dead"


def test_unopenable_process_with_fresh_heartbeat_keeps_its_lock(monkeypatch):
    monkeypatch.setattr(accounts, "_pid_state", lambda pid: "unknown")  # 别的用户 / 会话：OpenProcess 拒绝访问
    _write_lock(424242, heartbeat_age=30)
    with pytest.raises(accounts.AccountBusyError):
        with accounts.account_session("catch", wait_s=0):
            pass
    _write_lock(424242, heartbeat_age=11 * 60)  # 心跳也停了十分钟以上：才当陈旧锁
    with accounts.account_session("catch", wait_s=0):
        assert json.loads(accounts.lock_path().read_text("utf-8"))["pid"] == os.getpid()


def test_sync_stops_when_its_lock_is_taken_over(env, monkeypatch, capsys):
    monkeypatch.setattr(accounts, "LOCK_HEARTBEAT_SECONDS", 0.05)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        real_fetch = xhs.fetch_detail

        def fetch_then_lose_lock(note_id, token, **kw):
            if not env.fetched:  # 第 1 篇抓的时候：笔记本睡了一觉，锁被别的进程当陈旧锁接管
                for _ in range(3):  # 心跳线程可能正好读完还没写：多写几次，直到它发现锁不是自己的了
                    _write_lock(other.pid, heartbeat_age=0)
                    _real_sleep(0.15)
            return real_fetch(note_id, token, **kw)
        monkeypatch.setattr(xhs, "fetch_detail", fetch_then_lose_lock)
        env.favs = [_fav(i) for i in _ids(3)]
        code, out = _run(capsys)
        assert code == 6 and env.fetched == _ids(1)  # 没锁了：不再开第 2 篇
        assert json.loads(accounts.lock_path().read_text("utf-8"))["pid"] == other.pid  # 别人的锁没被删
        assert sync_state.load()["state"] == "failed"
    finally:
        other.kill()
        other.wait(timeout=10)


# --------------------------------------------------------------------------
# nit：login --status 带熔断起因（掉登录 → 脚本说「去扫码」而不是「风控」）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cause", ["NOT_LOGGED_IN", "CAPTCHA_REQUIRED"])
def test_login_status_reports_hold_cause(monkeypatch, capsys, cause):
    Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "lock": None,
                                                   "risk_hold": {**HOLD, "code": cause}}})
    code = cli.main(["login", "--status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 5 and out["login_state"] == "risk_hold" and out["hold_cause"] == cause


def test_login_status_guest_has_no_hold_cause(monkeypatch, capsys):
    accounts.save({"nickname": "alice"})
    Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "lock": None},
                         "/api/v1/login/status": {"is_logged_in": False}})
    assert cli.main(["login", "--status", "--json"]) == 3
    assert json.loads(capsys.readouterr().out)["hold_cause"] == ""


# --------------------------------------------------------------------------
# nit：--extract 先把同步结果落状态，补概要不再挂着 running；没预算时补概要最多 30 分钟
# --------------------------------------------------------------------------


def test_extract_enrich_runs_after_status_is_final_and_is_capped(env, monkeypatch, capsys):
    seen = {}

    def fake_enrich(targets, *, llm, deadline, **kw):
        seen["state"] = sync_state.load()["state"]
        seen["left"] = deadline - time.monotonic()
        return {"done": [], "failed": [], "deferred": 0}
    monkeypatch.setattr(enrich, "enrich_items", fake_enrich)
    env.favs = [_fav(i) for i in _ids(2)]
    code, out = _run(capsys, extract=True)
    assert code == 0 and seen["state"] == "ready" and "enrich" in out
    assert 29 * 60 < seen["left"] <= 30 * 60
