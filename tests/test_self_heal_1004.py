"""10-04：F1 Python 侧（读收藏读不全）+ 当场自愈（repair）+ 同一件事只报一条。

入口尽量走真的：favorites.run / sync_state.record / nightly.Nightly / problems CLI / repair.run / vision.refine_object /
llm.extract / semantic.run / videos.run / render.render_item；网络、模型、读取服务一律换成假的。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from link_brain import (accounts, cli, favorites, llm as llm_mod, nightly, problems, render, repair, semantic,
                        storage, sync_state, vision, visual)
from link_brain.nightly import Nightly, Step

from link_brain.asr import ensure_running as _real_ensure_running  # conftest 每个用例把它换成假的：这里留一份真的

from test_account_safety import _fav
from test_night_sync import _ids, _run, env  # noqa: F401 - env 是 fixture

PY = sys.executable
TZ = timezone(timedelta(hours=10))


def _open(step=None):
    return [r for r in problems.load() if step is None or r["step"] == step]


# --------------------------------------------------------------------------
# B1：读收藏把基准传给读取服务、认 partial、当晚不重读、基准不被一截顶掉
# --------------------------------------------------------------------------


def test_route_passes_baseline_only_when_known(monkeypatch):
    routes = []
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: None)
    monkeypatch.setattr(accounts, "pace", lambda *a, **k: 0)
    monkeypatch.setattr(accounts, "api", lambda m, route, **k: routes.append((route, k.get("timeout"))) or
                        {"items": [], "nickname": "n"})
    favorites.fetch_favorites(limit=0)
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 1159})
    favorites.fetch_favorites(limit=0)
    assert routes == [("/api/v1/favorites", 780), ("/api/v1/favorites?expect=1159", 780)], \
        "没有基准不带参数（旧读取服务行为不变）；客户端超时 780 秒 ≥ 660"


def test_partial_read_ingests_new_ones_flags_once_and_keeps_baseline(env, capsys):
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 10})
    env.favs = [_fav(i) for i in _ids(8)]   # 8 / 10 不到一半以下，旧规矩不算可疑——但读取服务明说只读到一截
    env.read = {"partial": True, "stop_reason": "budget", "has_more": True, "expect": 10,
                "scroll": {"scrolls": 40, "level": 3, "seconds": 419.5}}
    code, out = _run(capsys)
    assert code == favorites.EXIT_PARTIAL == 3
    assert len(env.fetched) == 8, "这一截里的新收藏照抓"
    assert out["partial"] is True and out["stop_reason"] == "budget" and out["no_reread"] is True
    assert "只读到一截" in out["suspicious"] and "滚动时间用完" in out["suspicious"]
    status = sync_state.load()
    assert status["state"] == "failed" and status["code"] == "FAVORITES_SUSPICIOUS"
    assert status["last_favorites"] == 10, "一截不顶掉基准"
    rows = [r for r in _open() if r["step"].startswith(("sync", "nightly"))]  # 样本笔记的附件在测试里下不了，不看那几条
    assert [(r["step"], r["code"]) for r in rows] == [("sync.favorites", "TRANSIENT.FAVORITES_SUSPICIOUS")]
    reason = rows[0]["reason"]
    assert reason.count("只读到一截") == 1, "原因只说一遍：" + reason
    assert env.alerts == []


def test_partial_with_failed_notes_still_one_row_and_no_retry_code(env, capsys):
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 10})
    ids = _ids(2)
    env.favs = [_fav(i) for i in ids]
    env.fail = {ids[0]}
    env.read = {"partial": True, "stop_reason": "stuck_has_more", "has_more": True, "expect": 10}
    code, out = _run(capsys)
    assert code == favorites.EXIT_PARTIAL, "有篇没抓到也不退 1：退 1 夜跑会等 25 分钟再读一次列表"
    rows = _open("sync.favorites")
    assert [r["code"] for r in rows] == ["TRANSIENT.FAVORITES_SUSPICIOUS"]
    assert "另有 1 篇没抓到" in rows[0]["reason"]


@pytest.mark.parametrize("payload,last,want", [
    ({"favorites_total": 1059, "stop_reason": "has_more_false", "partial": False}, 1159, 1059),   # 她真删了：认
    ({"favorites_total": 1120, "stop_reason": "budget", "partial": True, "suspicious": "x"}, 1159, 1159),  # 一截：不认
    ({"favorites_total": 1170, "stop_reason": "budget", "partial": True, "suspicious": "x"}, 1159, 1159),  # 一截哪怕更多：不认
    ({"favorites_total": 1100, "stop_reason": "stable", "partial": False}, 1159, 1159),  # 明显低于基准（<95%）没读到底：不认
    ({"favorites_total": 1110, "stop_reason": "stable", "partial": False}, 1159, 1110),  # 差不多：认
    ({"favorites_total": 1200}, 1159, 1200),                                               # 旧读取服务、变多：认
    ({"favorites_total": 50}, 1159, 1159),                                                 # 10-03：只读到第一页 50 条：永不认
])
def test_baseline_only_from_trustworthy_reads(payload, last, want):
    status = {"last_favorites": last}
    for _ in range(4):  # 连着几晚同一个数也不认（以前第 3 晚就认成基准了）
        sync_state._update_baseline(status, dict(payload))
    assert status["last_favorites"] == want


def test_reason_dedup_message_and_detail():
    sync_state.record("running", message="正在同步收藏")
    sync_state.record("finished", payload={"favorites": 0, "synced": 0, "items": [], "favorites_total": 0,
                                           "suspicious": "收藏读回 0 条：同一句", "code": "FAVORITES_SUSPICIOUS"})
    [row] = _open("sync.favorites")
    assert row["reason"] == "收藏读回 0 条：同一句"


# --------------------------------------------------------------------------
# B1.4 / B1.5：夜跑——退出 3 不重读、不另登记步骤出错
# --------------------------------------------------------------------------


@pytest.fixture
def job(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir(exist_ok=True)
    monkeypatch.setattr(Nightly, "running_sync", lambda self: None)

    def make(steps, **kw):
        sleeps = []
        j = Nightly(steps=steps, workdir=tmp_path, log_path=tmp_path / "nightly.log", sleep=sleeps.append, **kw)
        j.sleeps = sleeps
        return j
    return make


def test_nightly_partial_sync_no_reread_and_single_problem(job):
    problems.report("sync.favorites", "TRANSIENT.FAVORITES_SUSPICIOUS", "收藏只读到一截：读回 540 条")
    code = "import json;print(json.dumps({'suspicious':'x','no_reread':True,'partial':True}));raise SystemExit(3)"
    j = job([Step("sync-favorites", [], 1, account=True, argv=[PY, "-c", code], reserve_min=0)])
    out = j.run()
    assert j.sleeps == [], "只读到一截：今晚不等 25 分钟再读"
    assert "今晚不再重读列表" in j.log_path.read_text("utf-8")
    assert [r["step"] for r in _open()] == ["sync.favorites"], "不另登记 nightly.sync-favorites（同一件事一条）"
    assert out["exit"] == 1 and any("sync.favorites" in p for p in out["problems"])


def test_nightly_exit1_still_retries(job):
    j = job([Step("sync-favorites", [], 1, account=True, argv=[PY, "-c", "raise SystemExit(1)"], reserve_min=0)],
            sync_retry_wait_min=0)
    j.run()
    assert len(j.sleeps) == 1, "其它失败照旧：等一会儿再试一次"


def test_nightly_repair_round_fixes_and_drops_from_summary(job, monkeypatch, no_real_repair_children):
    """夜跑收尾的自愈轮：本次登记的 nightly.catalog 出错 → 跑 catalog 修复动作 → 退出 0 代为 resolve → 汇总里去掉。"""
    def ok_child(argv, timeout):
        no_real_repair_children.append(list(argv))
        return 0, "", False
    monkeypatch.setattr(repair, "_child_run", ok_child)
    j = job([Step("catalog", [], 1, argv=[PY, "-c", "raise SystemExit(1)"], reserve_min=0)])
    out = j.run()
    assert ["catalog"] in no_real_repair_children
    assert _open("nightly.catalog") == []
    assert out["exit"] == 0 and out["problems"] == []
    log = j.log_path.read_text("utf-8")
    assert "[自愈] 自愈：修好 1 条" in log and "汇总里 1 条已当场修好" in log


def test_nightly_repair_round_leaves_note_when_not_fixed(job):
    j = job([Step("catalog", [], 1, argv=[PY, "-c", "raise SystemExit(1)"], reserve_min=0)])
    out = j.run()
    [row] = _open("nightly.catalog")
    assert row["repair_state"] == "failed" and row["repair_note"].startswith("已试：重写目录页")
    assert "没好：" in row["repair_note"] and "下一步：" in row["repair_note"]
    assert row["count"] == 1, "自愈注记不算又出现一次"
    assert out["exit"] == 1


def test_interrupted_cleared_at_next_complete_night(job):
    j = job([Step("catalog", [], 1, argv=[PY, "-c", "pass"], reserve_min=0)])
    j.log_path.write_text(f"2026-10-02 04:00:00  {nightly.START_MARK}\r\n", "utf-8")
    j.run()
    assert [r["code"] for r in _open("nightly.run")] == ["TRANSIENT.INTERRUPTED"], "被打断那晚之后挂一整天"
    job([Step("catalog", [], 1, argv=[PY, "-c", "pass"], reserve_min=0)]).run()
    assert _open("nightly.run") == [], "下一晚开头看到上一晚走完了：标已解决"


# --------------------------------------------------------------------------
# repair：动作表、等待类、人工类、执行与注记
# --------------------------------------------------------------------------


NOW = datetime(2026, 10, 4, 10, 0, tzinfo=TZ)


def _row(step, code, item=None, ts=NOW):
    full = problems.normalize(code)
    return {"key": problems.make_key(step, item, full), "step": step, "item_id": item, "code": full,
            "ts": ts.isoformat(), "reason": "r"}


@pytest.mark.parametrize("step,code,item,kind,action,auto", [
    ("vision.layer1", "TRANSIENT.HTTP_5XX", "xhs-a", "run", "enrich", True),
    ("enrich.summary", "PERMANENT.MODEL_OUTPUT_INVALID", "xhs-a", "run", "enrich", False),
    ("enrich.summary", "TRANSIENT.RETRY_EXHAUSTED", "xhs-a", "run", "enrich", True),
    ("vision.refine", "PERMANENT.MODEL_OUTPUT_INVALID", "xhs-a", "run", "refine_item", False),
    ("vision.refine", "TRANSIENT.SERVICE_BUSY", None, "run", "refine_run", True),
    ("attachments.convert", "TRANSIENT.SERVICE_BUSY", "xhs-a", "run", "convert", True),
    ("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "xhs-a", "run", "convert", False),
    ("videos.transcribe", "TRANSIENT.SERVICE_BUSY", "xhs-a", "run", "transcribe", True),
    ("videos.transcribe", "PERMANENT.NO_SPEECH", "xhs-a", "run", "screen", False),
    ("embed", "TRANSIENT.NETWORK", None, "run", "embed", True),
    ("nightly.catalog-final", "TRANSIENT.STEP_TIMEOUT", None, "run", "catalog", True),
    ("nightly.embed", "TRANSIENT.STEP_CRASHED", None, "run", "embed", True),
    ("ingest", "TRANSIENT.DISCONNECTED", None, "run", "reader", True),
    ("sync.favorites", "TRANSIENT.FAVORITES_FAILED", None, "run", "sync", False),
    ("login", "NEEDS_HUMAN.CAPTCHA_REQUIRED", None, "human", None, False),
    ("login", "NEEDS_HUMAN.RISK_HOLD", None, "human", None, False),
    ("embed", "NEEDS_HUMAN.AUTH_FAILED", None, "human", None, False),
    ("enrich.summary", "SKIPPED.NOT_CONFIGURED", None, "none", None, False),
    ("nightly.vision-refine", "PERMANENT.STEP_ARGS", None, "manual", None, False),
])
def test_plan_table(step, code, item, kind, action, auto, monkeypatch):
    monkeypatch.setattr(repair, "_last_list_read", lambda: None)
    p = repair.plan(_row(step, code, item), NOW)
    assert (p["kind"], p.get("action"), bool(p.get("auto"))) == (kind, action, auto)


def test_partial_favorites_waits_until_next_nightly_with_reason():
    row = _row("sync.favorites", "TRANSIENT.FAVORITES_SUSPICIOUS", ts=datetime(2026, 10, 4, 4, 30, tzinfo=TZ))
    p = repair.plan(row, datetime(2026, 10, 4, 9, 0, tzinfo=TZ))
    assert p["kind"] == "wait" and p["wait_until"].startswith("2026-10-05T04:00")
    d = repair.describe(row, datetime(2026, 10, 4, 9, 0, tzinfo=TZ))
    assert d["repairable"] is False and d["status_text"].startswith("等到 10-05 04:00：")
    assert "下晚" not in d["status_text"]


def test_sync_reread_guard_30_minutes(monkeypatch):
    monkeypatch.setattr(repair, "_last_list_read", lambda: NOW - timedelta(minutes=10))
    p = repair.plan(_row("sync.favorites", "TRANSIENT.FAVORITES_FAILED"), NOW)
    assert p["kind"] == "wait" and p["wait_until"].startswith("2026-10-04T10:20")


def test_run_key_resolves_and_reports(no_real_repair_children):
    problems.report("nightly.catalog", "TRANSIENT.STEP_CRASHED", "catalog 出错")
    [row] = _open()
    out = repair.run(key=row["key"], execute=lambda argv, t: (0, "", False))
    assert out["fixed"] == 1 and out["ok"] and _open() == []


def test_run_never_touches_human_rows():
    problems.report("login", "NEEDS_HUMAN.CAPTCHA_REQUIRED", "要验证")
    called = []
    out = repair.run(execute=lambda argv, t: called.append(argv) or (0, "", False))
    assert called == [] and out["results"] == []
    [row] = _open()
    out = repair.run(key=row["key"], execute=lambda argv, t: called.append(argv) or (0, "", False))
    assert called == [] and "要你处理" in out["message"]


def test_account_actions_skipped_when_account_needs_human():
    old = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")
    problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id="xhs-a")
    rows = problems._read_rows()
    rows[0]["ts"] = old
    problems.path().write_text(json.dumps(rows[0], ensure_ascii=False) + "\n", encoding="utf-8")
    called = []
    out = repair.run(auto=True, allow_account=False, execute=lambda argv, t: called.append(argv) or (0, "", False))
    assert called == [] and out["results"][0]["status"] == "skipped"
    out = repair.run(auto=True, execute=lambda argv, t: called.append(argv) or (0, "", False))
    assert called == [["attachments", "xhs-a", "--budget-min", "7"]]


def test_attachment_not_reopened_within_20_minutes():
    problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "504", item_id="xhs-a")
    called = []
    out = repair.run(execute=lambda argv, t: called.append(argv) or (0, "", False))
    assert called == [] and out["results"][0]["status"] == "waiting" and "20 分钟" in out["results"][0]["message"]


def test_auto_round_only_new_and_auto_rows():
    problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "有密码", item_id="xhs-p")  # PERMANENT：不自动重试
    problems.report("embed", "TRANSIENT.NETWORK", "连不上")
    called = []
    future = (datetime.now().astimezone() + timedelta(hours=1)).isoformat(timespec="seconds")
    repair.run(auto=True, since=future, execute=lambda argv, t: called.append(argv) or (1, "x", False))
    assert called == [], "since 之前登记的不算本次运行的"
    repair.run(auto=True, execute=lambda argv, t: called.append(argv) or (1, "x", False))
    assert called == [["embed"]]
    repair.run(execute=lambda argv, t: called.append(argv) or (1, "x", False))  # 全部修一遍：PERMANENT 也再试一次
    assert ["pdf2md", "xhs-p", "--force"] in called


def test_round_stops_before_0650(monkeypatch):
    problems.report("embed", "TRANSIENT.NETWORK", "连不上")
    called = []
    out = repair.run(auto=True, execute=lambda argv, t: called.append(argv) or (0, "", False),
                     now_fn=lambda: datetime(2026, 10, 5, 6, 55, tzinfo=TZ))
    assert called == [] and out["results"][0]["status"] == "deferred"


def test_describe_running_shows_eta():
    problems.report("embed", "TRANSIENT.NETWORK", "连不上")
    [row] = _open()
    problems.annotate(row, repair_state="running", repair_at=datetime.now().astimezone().isoformat(), repair_eta_min=4)
    [row] = _open()
    assert row["status_text"] == "正在修 / 预计 4 分钟" and row["repairable"] is True and row["count"] == 1


def test_cli_repair_key(capsys):
    problems.report("nightly.catalog", "TRANSIENT.STEP_CRASHED", "catalog 出错")
    [row] = _open()
    assert cli.main(["problems", "repair", "--key", row["key"]]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["left"] == 1 and "已试：" in out["results"][0]["message"]


def test_list_has_repair_fields(capsys):
    problems.report("embed", "TRANSIENT.NETWORK", "连不上")
    assert cli.main(["problems", "list"]) == 0
    [row] = json.loads(capsys.readouterr().out)["problems"]
    assert row["repairable"] and row["repair_minutes"] == 4 and row["status_text"].startswith("待修复")


# --------------------------------------------------------------------------
# 各步骤自己那次运行里的换策略重试
# --------------------------------------------------------------------------


def _vision_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "render_object", lambda *a, **k: None)
    monkeypatch.setattr(vision, "REFINE_GAP_SECONDS", (0, 0))
    e = {"asset": "raw/v0001/assets/image-000.webp", "status": "ok", "lines": [{"text": "x", "score": 0.9}],
         "visual": {"kind": "diagram", "status": "ok", "text": "第一层"}}
    vision.mark_refine(e, "流程图且字多")
    vpath = storage.derived_dir("xiaohongshu", "abc") / "vision.json"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(vpath, {"schema_version": 1, "version": 1, "images": [e]})
    return vpath


BAD = {"status": "failed", "error": "出现复读", "code": "PERMANENT.MODEL_OUTPUT_INVALID", "text": "复读复读"}


def test_refine_ladder_heals_with_new_params(tmp_path, monkeypatch):
    vpath = _vision_setup(tmp_path, monkeypatch)
    seen = []

    def fake(path, lines, kind, cfg):
        seen.append(cfg.get("temperature"))
        return dict(BAD) if cfg.get("temperature") is None else {"status": "ok", "kind": "diagram", "text": "好", "model": "m"}
    monkeypatch.setattr(visual, "refine", fake)
    tally = vision.refine_object("xiaohongshu", "abc", {"model": "m", "endpoint": "e"})
    ref = storage.read_json(vpath)["images"][0]["refine"]
    assert seen == [None, vision.RETRY_TEMPERATURE] and tally["done"] == 1
    assert ref["status"] == "done" and "换参数" in ref["healed"]


def test_refine_ladder_switches_model_then_falls_back_to_layer1(tmp_path, monkeypatch):
    vpath = _vision_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(vision, "strong_config", lambda: {"model": "强", "endpoint": "e2"})
    monkeypatch.setattr(visual, "vision_config", lambda: {"model": "m", "endpoint": "e"})  # 和第一路同一个：不重复试
    seen = []
    monkeypatch.setattr(visual, "refine", lambda p, l, k, cfg: seen.append(cfg["model"]) or dict(BAD))
    vision.refine_object("xiaohongshu", "abc", {"model": "m", "endpoint": "e"})
    ref = storage.read_json(vpath)["images"][0]["refine"]
    assert seen == ["m", "m", "强"], "原样 → 换参数 → 换模型（去重）"
    assert ref["status"] == "failed" and ref["fallback"] == "layer1", "同一次运行里放弃，退回第一层，不留到明晚"
    [row] = _open("vision.refine")
    assert row["code"] == "PERMANENT.MODEL_OUTPUT_INVALID" and "退回第一层" in row["reason"]


def test_refine_retry_failed_only_remarks_failed_images(tmp_path, monkeypatch):
    vpath = _vision_setup(tmp_path, monkeypatch)
    doc = storage.read_json(vpath)
    doc["images"][0]["refine"]["status"] = "failed"
    doc["images"].append({"asset": "raw/v0001/assets/image-001.webp", "visual": {"kind": "text"},
                          "refine": {"status": "done"}})
    storage.write_json(vpath, doc)
    import link_brain.index as index_mod
    monkeypatch.setattr(index_mod, "get_object", lambda conn, i: {"source": "xiaohongshu", "source_id": "abc"})
    monkeypatch.setattr(index_mod, "connect", lambda: SimpleNamespace(close=lambda: None))
    vision.run_refine_mark(SimpleNamespace(refine_mark="xhs-abc", asset=None, now=False, retry_failed=True))
    refs = [e["refine"]["status"] for e in storage.read_json(vpath)["images"]]
    assert refs == ["pending", "done"]


def test_summary_switches_to_text_model_when_configured(tmp_path, monkeypatch):
    primary = {"mode": "http", "endpoint": "e1", "model": "小"}
    alt = {"mode": "http", "endpoint": "e2", "model": "大"}
    monkeypatch.setattr(llm_mod, "alternate_summary_config", lambda p, s: alt)
    calls = []

    def fake(instruction, text, cfg):
        calls.append((cfg["model"], llm_mod.STRICT_JSON_SUFFIX in instruction))
        if cfg is alt:
            return {"status": "ok", "text": json.dumps(GOOD), "error": None}
        return {"status": "ok", "text": "不是 JSON", "error": None}
    monkeypatch.setattr(llm_mod, "call_model", fake)
    from link_brain import providers
    monkeypatch.setattr(providers, "resolve", lambda cap, s=None: primary if cap == "summaryAI" else None)
    _note(tmp_path)
    doc = llm_mod.extract("xiaohongshu", "n1")
    assert calls == [("小", False), ("小", True), ("大", True)], "重试一次（把只回 JSON 说死）→ 换文本模型"
    assert doc["status"] == "ok" and doc["fallback_model"] is True and doc["model"] == "大"


GOOD = {"summary": "一句话概要。", "key_points": ["要点"], "tags": ["测试"], "links_worth_opening": [],
        "valuable_comments": [], "ads_or_noise": []}


def _note(tmp_path):
    obj = storage.object_dir("xiaohongshu", "n1")
    raw = obj / "raw" / "v0001"
    raw.mkdir(parents=True)
    storage.write_json(obj / "meta.json", {"item_id": "xhs-n1", "current_version": 1, "title": "T"})
    storage.write_json(raw / "source.json", {"note": {"title": "T", "body": "正文"}, "comments": []})


def test_alternate_summary_config_none_when_same(monkeypatch):
    from link_brain import providers
    same = {"mode": "http", "endpoint": "e", "model": "m"}
    monkeypatch.setattr(providers, "resolve", lambda cap, s=None: dict(same))
    assert llm_mod.alternate_summary_config(dict(same), {}) is None


def test_embed_retries_transient_then_succeeds(monkeypatch):
    seq = iter([semantic.EmbedHTTPError(503), semantic.EmbedHTTPError(429)])

    def flaky(texts, cfg, timeout):
        nxt = next(seq, None)
        if nxt:
            raise nxt
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(semantic, "_post_embeddings", flaky)
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("link_brain.ask.load_items", lambda: [{"id": "a", "title": "t", "body": "正文" * 80}])
    out = semantic.run_embed()
    assert out["status"] == "ok" and out["retried"] == 2


@pytest.mark.parametrize("exc,had,code,exit_code", [
    (semantic.EmbedHTTPError(503), False, "TRANSIENT.HTTP_5XX", 3),
    (semantic.EmbedHTTPError(401), False, "NEEDS_HUMAN.AUTH_FAILED", 3),
    (RuntimeError("no-api-key"), True, "NEEDS_HUMAN.AUTH_FAILED", 3),   # 以前能用、现在丢了 key：要人看
    (RuntimeError("no-api-key"), False, "SKIPPED.NOT_CONFIGURED", 0),   # 从没配过：未开启，不算失败
])
def test_embed_failure_is_registered_once(monkeypatch, capsys, exc, had, code, exit_code):
    monkeypatch.setattr(semantic, "run_embed", lambda re_embed=False: {
        "status": "failed", "error": "x", "code": semantic.embed_error_code(exc), "had_vectors": had})
    assert semantic.run(SimpleNamespace(all=False)) == exit_code
    assert [r["code"] for r in problems.load()] == [code]


def test_render_survives_vision_crash(tmp_path, monkeypatch):
    """B2.4 入档不被阻断：识图出意外，笔记照样渲染，问题登记一条（自愈轮会重跑这篇）。"""
    monkeypatch.setattr(vision, "build_vision", lambda *a, **k: (_ for _ in ()).throw(TypeError("坏图")))
    monkeypatch.setattr(vision, "_item_id", lambda k, s: "xhs-n1")
    rendered = []
    monkeypatch.setattr(render, "render_object", lambda *a, **k: rendered.append(a) or {"ok": True})
    assert render.render_item("xiaohongshu", "n1") == {"ok": True} and rendered
    [row] = _open("vision.layer1")
    assert row["code"] == "TRANSIENT.STEP_CRASHED" and "正文已入档" in row["reason"]


def test_videos_try_to_start_asr_once(monkeypatch):
    from link_brain import asr, videos
    calls = []
    monkeypatch.setattr(asr, "available", lambda cfg: bool(calls))
    monkeypatch.setattr(asr, "ensure_running", lambda cfg, **k: calls.append(cfg) or (True, "已拉起转写服务"))
    cfg = {"mode": "capswriter", "host": "127.0.0.1", "port": 6016}
    assert videos._asr_ready(cfg) is True and videos._asr_ready(cfg) is True
    assert len(calls) == 1, "一次运行只拉一次"


def test_asr_ensure_running_not_capswriter():
    ok, why = _real_ensure_running({"mode": "http", "endpoint": "x"})
    assert ok is True  # http 方式只看配没配，不在本机起服务
    ok, why = _real_ensure_running(None)
    assert ok is False and "CapsWriter" in why
