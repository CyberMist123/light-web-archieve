"""1001 收藏自动化：抓取阶段只用号抓原文、歇够、连续失败停批、预算收尾、每日额度、已在库不重渲、
收藏数骤降报警、限频不冲掉旧失败；enrich 子进程限时整棵杀；catch 的账号锁与纯 JSON stdout；附件断线不崩。

入口一律是真的（favorites.run / cli.main / catch / attachments.run），只把网络那一侧换成假的。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from link_brain import (accounts, alert as alert_mod, attachments as att_mod, cli, enrich,
                        favorites, index as index_mod, llm as llm_mod, render as render_mod, storage, sync_state)
from link_brain import vision as vision_mod
from link_brain.adapters import xiaohongshu as xhs

from test_account_safety import Reader, _fav, _other_process_holds_lock

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
SESSION = {"state": "idle", "risk_hold": None, "lock": None}



@pytest.fixture(autouse=True)
def summary_model_configured(monkeypatch):
    """第 1B 批起概要走设置里的模型：这里给一个假的 OpenAI 兼容接口（调用本身被 llm.call_model 的替身接住，不出网）。"""
    from link_brain import ai_config
    settings = ai_config._deep_merge(ai_config.DEFAULTS, {"textAI": {
        "mode": "http", "endpoint": "https://llm.example.invalid/v1/chat/completions", "model": "fake-model"}})
    monkeypatch.setattr(ai_config, "load", lambda: settings)


def _ids(n, prefix="bbbbbbbbbbbbbbbb"):
    return [f"{prefix}{i:04d}" for i in range(n)]


@pytest.fixture
def env(monkeypatch):
    """假读取服务 + 假抓详情（原文用脱敏样本）；记下开了哪几篇、歇了几次。"""
    state = SimpleNamespace(favs=[], fetched=[], sleeps=[], alerts=[], fail=set(), reader=None)
    state.reader = Reader(monkeypatch, {"/api/v1/login/session": SESSION,
                                        "/api/v1/favorites": lambda: {"nickname": "alice", "items": state.favs}})

    def fake_fetch(note_id, token, **kw):
        state.fetched.append(note_id)
        if note_id in state.fail:
            raise xhs.AdapterError("MCP get_feed_detail 报错: 笔记不存在")
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(xhs, "fetch_detail", fake_fetch)
    monkeypatch.setattr(vision_mod, "run_ocr", lambda path, timeout=120: {"status": "ok", "ocr": "t", "error": None})
    monkeypatch.setattr(favorites, "_sleep", lambda s: state.sleeps.append(s))
    # 原文里的图片不真下（样本里是 example.com 的地址）
    from link_brain import ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "download_image", lambda url, dest, stem, client: {
        "file": None, "requested_url": url, "mime": None, "width": None, "height": None, "bytes": None,
        "sha256": None, "download_status": "failed", "error": "测试不联网"})
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: state.alerts.append(a) or True)
    monkeypatch.setenv("LWA_FETCH_REST", "60,180")
    return state


def _run(capsys, **kw):
    args = dict(limit=0, origin="cli", actor="human", verbose=False, extract=False, budget_min=0, wait_lock_min=0)
    args.update(kw)
    code = favorites.run(SimpleNamespace(**args))
    return code, json.loads(capsys.readouterr().out)


def _in_index(note_id):
    conn = index_mod.connect()
    try:
        return index_mod.get_object(conn, f"xhs-{note_id}") is not None
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 抓取阶段：不调模型、不识图；每次联网后歇 60–180 秒；标待 enrich
# --------------------------------------------------------------------------


def test_fetch_phase_is_local_render_only_and_rests_between_fetches(env, monkeypatch, capsys):
    env.favs = [_fav(i) for i in _ids(3)]
    monkeypatch.setattr(vision_mod, "build_vision", lambda *a, **k: pytest.fail("抓取阶段不许识图"))
    monkeypatch.setattr(llm_mod, "extract", lambda *a, **k: pytest.fail("抓取阶段不许调模型"))
    code, out = _run(capsys)
    assert code == 0 and [x["status"] for x in out["items"]] == ["new"] * 3
    assert env.fetched == _ids(3)
    rests = [s for s in env.sleeps if s >= 60]
    assert len(rests) == 2 and all(60 <= s <= 180 for s in rests)  # 两次抓取之间各歇一次，最后一篇后不白等
    for sid in _ids(3):
        assert enrich.load_state("xiaohongshu", sid)["pending"] is True
        meta = storage.read_json(storage.object_dir("xiaohongshu", sid) / "meta.json")
        assert (storage.vault_root() / meta["visible_note"]).exists()
    assert out["fetched_new"] == _ids(3)
    assert sync_state.load()["last_favorites"] == 3


def test_hit_is_not_rerendered_unless_visible_note_is_gone(env, monkeypatch, capsys):
    env.favs = [_fav(i) for i in _ids(2)]
    _run(capsys)
    calls = []
    real = render_mod.render_object
    monkeypatch.setattr(render_mod, "render_object", lambda *a, **k: calls.append(k) or real(*a, **k))
    monkeypatch.setattr(vision_mod, "build_vision", lambda *a, **k: pytest.fail("已在库的不许重跑识图"))
    code, out = _run(capsys)
    assert code == 0 and [x["status"] for x in out["items"]] == ["hit", "hit"] and calls == []
    assert env.fetched == _ids(2)  # 第二次一篇都没联网
    meta = storage.read_json(storage.object_dir("xiaohongshu", _ids(2)[0]) / "meta.json")
    (storage.vault_root() / meta["visible_note"]).unlink()
    _run(capsys)
    assert calls == [{"verbose": False, "llm": False}]  # 只补丢了的那一篇，本地渲染


def test_three_consecutive_fetch_failures_stop_the_batch(env, capsys):
    ids = _ids(5)
    env.favs = [_fav(i) for i in ids]
    env.fail = set(ids[:4])
    code, out = _run(capsys)
    assert code == 1 and out["code"] == "TOO_MANY_FAILURES"
    assert env.fetched == ids[:3]  # 第 3 篇失败就停，没接着开第 4 篇
    assert len([s for s in env.sleeps if s >= 60]) == 2  # 失败之间照样歇
    # 第 4 批：连着几篇抓不到但没撞风控 = TRANSIENT.TOO_MANY_FAILURES，只记不推
    assert not env.alerts
    from link_brain import problems
    assert [(r["step"], r["code"]) for r in problems.load()] == [("sync.favorites", "TRANSIENT.TOO_MANY_FAILURES")]
    failures = storage.read_json(storage.archive_root() / "sync-failures.json")
    assert set(failures) == set(ids[:3]) and all(v["count"] == 1 for v in failures.values())
    # 下一晚：抓失败过的排到最后，新的先抓；已知坏篇再失败不算「连续失败」
    env.fetched.clear()
    env.fail = set(ids[:3])
    code, out = _run(capsys)
    assert env.fetched[:2] == ids[3:] and set(env.fetched[2:]) == set(ids[:3])
    assert out.get("code") != "TOO_MANY_FAILURES"


def test_note_failing_three_nights_is_skipped_for_a_week(env, capsys):
    bad, good = _ids(2)
    env.favs = [_fav(bad), _fav(good)]
    env.fail = {bad}
    for _ in range(3):
        _run(capsys)
    env.fetched.clear()
    code, out = _run(capsys)
    assert bad not in env.fetched and out["skipped_failing"] == 1


def test_daily_limit_zero_is_unlimited_and_blank_falls_back_to_50():
    # 第 5 批 4.1：0 = 不限；空 / 乱填 / 负数 = 默认 50（以前 `or 0` 让清空变成不限）
    from link_brain import ai_config
    f = ai_config.daily_new_limit
    assert [f(None), f(""), f("  "), f("abc"), f(-3), f(True)] == [50] * 6
    assert [f(0), f("0"), f(30), f("120")] == [0, 0, 30, 120]


def test_daily_limit_defaults_to_50_and_is_shared_with_the_plugin(env, capsys):
    from datetime import date
    from link_brain import ai_config
    assert ai_config.sync_options()["dailyNewLimit"] == 50
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(storage.archive_root() / "sync-quota.json", {"date": date.today().isoformat(), "new": 49})
    env.favs = [_fav(i) for i in _ids(3)]
    code, out = _run(capsys)
    assert code == 0 and env.fetched == _ids(1) and out["deferred"] == 2 and out["deferred_reason"] == "daily_limit"
    assert "明天继续" in sync_state.load()["message"]


def test_budget_ends_gracefully(env, monkeypatch, capsys):
    clock = {"t": 1000.0}
    monkeypatch.setattr(favorites, "_clock", lambda: clock["t"])

    def fetch_and_tick(note_id, token, **kw):
        clock["t"] += 40 * 60  # 一篇 40 分钟
        env.fetched.append(note_id)
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(xhs, "fetch_detail", fetch_and_tick)
    env.favs = [_fav(i) for i in _ids(5)]
    code, out = _run(capsys, budget_min=100)
    assert code == 0 and len(env.fetched) == 3 and out["deferred"] == 2 and out["deferred_reason"] == "budget"
    status = sync_state.load()
    assert status["state"] == "ready" and status["message"] == "今天先到这，剩 2 篇明天继续"


def test_extract_runs_enrich_after_the_account_lock_is_released(env, monkeypatch, capsys):
    env.favs = [_fav(i) for i in _ids(2)]
    seen = {}

    def fake_enrich(targets, *, llm, deadline, **kw):
        seen["lock_file"] = accounts.lock_path().exists()
        seen["targets"] = targets
        return {"done": [f"xhs-{s}" for _, s in targets], "failed": [], "deferred": 0}

    monkeypatch.setattr(enrich, "enrich_items", fake_enrich)
    code, out = _run(capsys, extract=True)
    assert code == 0 and seen["lock_file"] is False
    assert seen["targets"] == [("xiaohongshu", s) for s in _ids(2)] and out["enrich"]["done"]


@pytest.mark.parametrize("last,read,alarm", [(10, 4, True), (10, 0, True), (10, 6, False)])
def test_favorites_count_sanity(env, capsys, last, read, alarm):
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": last})
    env.favs = [_fav(i) for i in _ids(read)]
    code, out = _run(capsys)
    status = sync_state.load()
    if alarm:
        assert code == 1 and status["state"] == "failed" and status["code"] == "FAVORITES_SUSPICIOUS"
        # 第 4 批：可疑 = 停车待人看 NEEDS_HUMAN.FAVORITES_SUSPICIOUS，经 problems 唯一出口推一次
        assert [a[1] for a in env.alerts] == ["收藏数异常：收藏同步"] and env.alerts[0][0] == "problem"
        assert status["last_favorites"] == last  # 可疑的那次不顶掉基准
        assert len(env.fetched) == read  # 读到的照常处理
    else:
        assert code == 0 and status["state"] == "ready" and status["last_favorites"] == read


def test_rate_limited_keeps_earlier_failure_and_last_success(env, capsys):
    sync_state.record("finished", payload={"favorites": 1, "synced": 1, "items": [{"status": "hit"}]})
    ok_at = sync_state.load()["last_success"]
    sync_state.account_problem("NOT_LOGGED_IN", "登录检查：未登录")
    assert len(env.alerts) == 1  # 掉登录本身推一次（NEEDS_HUMAN）
    env.alerts.clear()
    env.reader.routes["/api/v1/favorites"] = httpx.Response(429, json={"code": "RATE_LIMITED", "error": "刚读过"})
    code, out = _run(capsys)
    status = sync_state.load()
    assert code == 0
    assert status["state"] == "blocked" and status["code"] == "NOT_LOGGED_IN" and status["last_success"] == ok_at
    assert not env.alerts  # 限频不打扰人


def test_logged_in_probe_hitting_guest_stops_the_batch(env, monkeypatch, capsys):
    """入库时游客探测失败 → 用登录号补看；补看发现号掉了 → 整批停车（exit 5），不再开下一篇。"""
    monkeypatch.setattr(att_mod, "_probe_logged_in",
                        lambda n, t: {"ok": False, "needs_human": True, "code": "NOT_LOGGED_IN", "error": "没登录"})
    env.favs = [_fav(i) for i in _ids(3)]
    code, out = _run(capsys)
    assert code == 5 and env.fetched == _ids(1) and not _in_index(_ids(1)[0])


# --------------------------------------------------------------------------
# enrich：候选、次数、子进程限时整棵杀
# --------------------------------------------------------------------------

GOOD = {"summary": "一句话概要。", "key_points": ["要点"], "tags": ["测试"], "links_worth_opening": [],
        "valuable_comments": [], "ads_or_noise": []}


def _model(ok=True, calls=None):
    def call(instruction, input_text, cfg):
        if calls is not None:
            calls.append(1)
        if not ok:
            return {"status": "failed", "text": None, "error": "接口 500"}
        return {"status": "ok", "text": json.dumps(GOOD, ensure_ascii=False), "error": None}
    return call


def test_enrich_pending_fills_summary_and_clears_mark(env, monkeypatch, capsys):
    env.favs = [_fav(i) for i in _ids(2)]
    _run(capsys)
    monkeypatch.setattr(llm_mod, "call_model", _model())
    assert cli.main(["enrich", "--pending"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert sorted(out["done"]) == sorted(f"xhs-{i}" for i in _ids(2))
    for sid in _ids(2):
        assert enrich.load_state("xiaohongshu", sid)["pending"] is False
        assert llm_mod.load_extracted("xiaohongshu", sid)["status"] == "ok"
    assert cli.main(["enrich", "--pending"]) == 0
    assert json.loads(capsys.readouterr().out)["candidates"] == 0


def test_enrich_gives_up_after_three_failures_but_item_still_works(env, monkeypatch, capsys):
    from link_brain import problems
    env.favs = [_fav(_ids(1)[0])]
    _run(capsys)
    monkeypatch.setattr(llm_mod, "call_model", _model(ok=False))
    alerts = []
    monkeypatch.setattr(alert_mod, "_alert", lambda *a, **k: alerts.append(a))
    for n in range(3):
        assert cli.main(["enrich", "--pending"]) == 1
        capsys.readouterr()
    state = enrich.load_state("xiaohongshu", _ids(1)[0])
    assert state["fails"] == 3 and state["retry_after"]
    # 第 4 批：暂时放弃不推送，登记 TRANSIENT.RETRY_EXHAUSTED（action=gave_up，带 next_at）
    assert alerts == []
    row = next(r for r in problems.load() if r["code"] == "TRANSIENT.RETRY_EXHAUSTED")
    assert row["action"] == "gave_up" and row["next_at"] == state["retry_after"] and row["item_id"] == f"xhs-{_ids(1)[0]}"
    assert cli.main(["enrich", "--pending"]) == 0
    assert json.loads(capsys.readouterr().out)["candidates"] == 0  # 退避中：今晚不自动重试
    monkeypatch.setattr(llm_mod, "call_model", _model(ok=True))
    assert cli.main(["enrich", "--item", f"xhs-{_ids(1)[0]}"]) == 0  # 点名照跑
    assert enrich.load_state("xiaohongshu", _ids(1)[0])["fails"] == 0


SLEEPER = r"""
import subprocess, sys, time
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(sys.argv[1], "w").write(str(p.pid))
time.sleep(120)
"""


def test_enrich_timeout_kills_the_whole_process_tree(env, monkeypatch, tmp_path, capsys):
    env.favs = [_fav(_ids(1)[0])]
    _run(capsys)
    pid_file = tmp_path / "grandchild.pid"
    monkeypatch.delenv("LINK_BRAIN_RENDER_INPROC")
    monkeypatch.setattr(enrich, "ITEM_TIMEOUT_SECONDS", 4)
    monkeypatch.setattr(enrich, "_child_argv", lambda *a: [sys.executable, "-c", SLEEPER, str(pid_file)])
    started = time.monotonic()
    assert cli.main(["enrich", "--item", f"xhs-{_ids(1)[0]}"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert time.monotonic() - started < 60
    assert "超过" in out["failed"][0]["error"] and out["failed"][0]["fails"] == 1
    grandchild = int(pid_file.read_text())
    for _ in range(50):
        if not sync_state._alive(grandchild):
            break
        time.sleep(0.1)
    assert not sync_state._alive(grandchild)  # 孙进程（OCR / 识图脚本那一层）也被杀了


# --------------------------------------------------------------------------
# catch：账号锁、stdout 只有 JSON、识图挪到锁外
# --------------------------------------------------------------------------

URL = "https://www.xiaohongshu.com/explore/cccccccccccccccc0001?xsec_token=T"


def test_catch_waits_for_lock_and_exits_6_with_json_only(env, capsys):
    with _other_process_holds_lock():
        code = cli.main(["catch", f"存一下 {URL}", "--wait-lock-min", "0"])
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert code == 6 and out["items"][0]["status"] == "busy" and "稍后再收" in out["items"][0]["error"]
    assert env.fetched == []


def test_catch_hit_does_not_need_the_lock(env, capsys):
    assert cli.main(["catch", f"存一下 {URL}"]) == 0
    capsys.readouterr()
    with _other_process_holds_lock():
        code = cli.main(["catch", f"又发一次 {URL}", "--wait-lock-min", "0"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["items"][0]["status"] == "hit"


def test_catch_stdout_is_only_the_final_json_even_when_things_print(env, monkeypatch, capsys):
    def noisy(*a, **k):
        print("附件排队中……（这句以前会混进 stdout）")
        print("[alert] 某个报警", file=sys.stderr)
    monkeypatch.setattr(att_mod, "grab_after_ingest", noisy)
    code = cli.main(["catch", f"存一下 {URL}", "--extract"])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["items"][0]["status"] == "new"  # 整个 stdout 就是一个 JSON
    assert "附件排队中" in captured.err


def test_catch_runs_vision_after_releasing_the_lock(env, monkeypatch, capsys):
    seen = []
    real = enrich.enrich_one

    def spy(key, sid, **kw):
        seen.append((accounts.lock_path().exists(), kw.get("llm")))
        return real(key, sid, **kw)
    monkeypatch.setattr(enrich, "enrich_one", spy)
    assert cli.main(["catch", f"存一下 {URL}"]) == 0
    capsys.readouterr()
    assert seen == [(False, False)]  # 锁已放；没 --extract 不调概要


def test_catch_refresh_is_accepted(env, capsys):
    assert cli.main(["catch", f"存一下 {URL}"]) == 0
    capsys.readouterr()
    assert cli.main(["catch", f"再抓一次 {URL}", "--refresh"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["status"] == "hit"  # 内容没变 = 不写新版本
    assert len(env.fetched) == 2


# --------------------------------------------------------------------------
# 附件：下载途中断线不崩；已手动挂好的线索不再开页；补查撞掉登录退出 5
# --------------------------------------------------------------------------

RELATED = {"name": "教程.pdf", "docId": "7658854832003020032", "bizExtra": '{"page_num":1}'}


def _archive_with_attachment(env, monkeypatch, capsys, related=RELATED):
    monkeypatch.setattr(xhs, "fetch_related_file", lambda n, t, **kw: {
        "ok": True, "related_file": related, "url": "https://example.invalid/n", "error": None})
    monkeypatch.setattr(att_mod, "grab_after_ingest", lambda *a, **k: None)
    assert cli.main(["catch", f"存一下 {URL}"]) == 0
    capsys.readouterr()


def test_attachments_all_survives_connection_reset_mid_download(env, monkeypatch, capsys):
    _archive_with_attachment(env, monkeypatch, capsys)
    env.reader.routes["/api/v1/attachments/download"] = httpx.ReadError("[WinError 10054] 远程主机强迫关闭了一个现有的连接")
    code = cli.main(["attachments", "--all"])
    captured = capsys.readouterr()
    assert code == 1  # 记失败、报出来，但没有整晚崩掉
    assert "读取服务没有运行" in captured.err or "DISCONNECTED" in captured.err
    state = storage.read_json(storage.object_dir("xiaohongshu", "cccccccccccccccc0001") / "attachment-state.json")
    assert state["errors"]


def test_hint_already_attached_by_hand_is_not_probed_again(env, monkeypatch, capsys):
    monkeypatch.setattr(att_mod, "grab_after_ingest", lambda *a, **k: None)
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["data"]["note"]["desc"] = "本篇文案依旧放在附件，请自助"
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: payload)
    assert cli.main(["catch", f"存一下 {URL}"]) == 0
    capsys.readouterr()
    hint = storage.read_json(storage.raw_dir("xiaohongshu", "cccccccccccccccc0001", 1) / "source.json")["note"]["attachments"][0]["hint"]
    f = Path(os.environ["LINK_BRAIN_VAULT"]).parent / "hand.pdf"
    f.write_bytes(b"%PDF-1.4 hand")
    att_mod.manual_attach("xiaohongshu", "cccccccccccccccc0001", str(f))
    assert storage.read_json(att_mod.attachments_path("xiaohongshu", "cccccccccccccccc0001"))["files"][0]["name"] == hint
    monkeypatch.setattr(att_mod, "resolve_hint", lambda *a, **k: pytest.fail("已经挂好的线索不许再开页"))
    monkeypatch.setattr(att_mod, "convert_downloads", lambda *a, **k: [])
    assert cli.main(["attachments", "--all"]) == 0


def test_recheck_hitting_logged_out_exits_5(env, monkeypatch, capsys):
    monkeypatch.setattr(att_mod, "grab_after_ingest", lambda *a, **k: None)
    assert cli.main(["catch", f"存一下 {URL}"]) == 0  # conftest：网页探测失败 → 待补查
    capsys.readouterr()
    monkeypatch.setattr(att_mod, "_probe_logged_in",
                        lambda n, t: {"ok": False, "needs_human": True, "code": "ACCOUNT_RISK", "error": "跳到了登录异常页"})
    monkeypatch.setattr("link_brain.alert._alert", lambda *a, **k: None)
    assert cli.main(["attachments", "--recheck", "--limit", "20"]) == 5
    assert json.loads(capsys.readouterr().out)["blocked"] == "ACCOUNT_RISK"


def test_attachment_download_hitting_risk_stops_the_sync(env, monkeypatch, capsys):
    """新收藏入库后顺手下附件，下载时读取服务回熔断（423）→ 这篇照样存好，但整批停车、退出 5。"""
    monkeypatch.setattr(xhs, "fetch_related_file", lambda n, t, **kw: {
        "ok": True, "related_file": RELATED, "url": "https://example.invalid/n", "error": None})
    env.reader.routes["/api/v1/attachments/download"] = httpx.Response(
        423, json={"code": "RISK_HOLD", "hold": {"code": "CAPTCHA_REQUIRED", "since": "x"}})
    env.favs = [_fav(i) for i in _ids(3)]
    code, out = _run(capsys)
    assert code == 5 and env.fetched == _ids(1)
    assert out["items"][0]["status"] == "new" and out["items"][-1]["code"] == "RISK_HOLD"
    assert env.reader.calls.count("/api/v1/attachments/download") == 1  # 撞了就停，不重试
    assert sync_state.load()["state"] == "blocked"
