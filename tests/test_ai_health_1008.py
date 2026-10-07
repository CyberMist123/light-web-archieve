"""1008 Owner：AI 接口故障一个原因一条（ai_health），不按篇刷屏；接口故障不算这篇的失败；轻量版不跑 AI、不报 AI 失败。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from link_brain import ai_config, ai_health, cli, enrich, llm as llm_mod, problems, providers, repair, storage
from link_brain.adapters import xiaohongshu as xhs

from test_night_sync import _ids, _run, env  # noqa: F401 - env 是 fixture
from test_account_safety import _fav


def _settings(extra=None, selected=None):
    base = {"textAI": {"mode": "http", "endpoint": "https://llm.example.invalid/v1/chat/completions", "model": "fake-model",
                       "apiKey": "sk-test-0000-abcd"},
            "visionAI": {"mode": "http", "endpoint": "https://vl.example.invalid/v1/chat/completions", "model": "fake-vl",
                         "apiKey": "sk-vl-0000-ef12"}}
    if selected is not None:
        base["setup"] = {"selected": selected, "aiSynced": True}
    s = ai_config._deep_merge(ai_config.DEFAULTS, base)
    return ai_config._deep_merge(s, extra or {})


@pytest.fixture
def configured(monkeypatch):
    settings = _settings()
    monkeypatch.setattr(ai_config, "load", lambda: settings)
    return settings


# --------------------------------------------------------------------------
# 归并登记本身
# --------------------------------------------------------------------------


def _auth(status=403):
    return providers.http_failure(status, '{"code":"InvalidApiKey"}')


def test_record_folds_many_items_into_one_row_with_cause_key_and_estimate(configured):
    cfg = providers.resolve("summaryAI")
    for i in range(40):
        ai_health.record("summaryAI", _auth(), item_id=f"xhs-{i:024d}", cfg=cfg)
    rows = [r for r in problems.load() if not r.get("resolved_at")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["step"] == "ai.summary" and row["item_id"] is None and row["code"] == "NEEDS_HUMAN.AUTH_FAILED"
    reason = row["reason"]
    assert "HTTP 403" in reason and "尾号 abcd" in reason and "设置里填的 key" in reason
    assert "key 填错、已过期或被停用" in reason and "换一把 key" in reason
    assert "影响 40 篇" in reason and "token" in reason
    assert "sk-test" not in reason  # key 本身绝不出现
    assert len(ai_health.affected("summaryAI")) == 40
    assert row["hover"] == reason  # 面板直接显示这一句


def test_quota_and_network_have_their_own_cause_text(configured):
    cfg = providers.resolve("summaryAI")
    ai_health.record("summaryAI", providers.http_failure(402, "insufficient balance"), item_id="xhs-a", cfg=cfg)
    row = next(r for r in problems.load() if r["step"] == "ai.summary")
    assert row["code"] == "NEEDS_HUMAN.QUOTA_EXCEEDED" and "欠费或额度用完" in row["reason"] and "充值" in row["reason"]
    # 原因变了（断网）：旧那条解决、重开一条
    import httpx
    ai_health.record("summaryAI", providers.network_failure(httpx.ConnectError("x")), item_id="xhs-b", cfg=cfg)
    rows = [r for r in problems.load() if r["step"] == "ai.summary"]
    assert len(rows) == 1 and rows[0]["code"] == "TRANSIENT.NETWORK" and "断网" in rows[0]["reason"]
    assert ai_health.affected("summaryAI") == ["xhs-b"]


def test_success_clears_row_and_list(configured):
    cfg = providers.resolve("visionAI")
    ai_health.record("visionAI", _auth(401), item_id="xhs-a", cfg=cfg)
    assert any(r["step"] == "ai.vision" for r in problems.load())
    ai_health.clear("visionAI")
    assert not any(r["step"] == "ai.vision" for r in problems.load())
    assert ai_health.affected("visionAI") == []


def test_key_hint_names_file_or_env_without_leaking(configured):
    assert providers.key_source({"keyFile": r"D:\x\keys.csv", "keyField": "qwen"}) == "密钥文件 keys.csv 里的「qwen」"
    assert providers.key_source({"apiKeyEnv": "LWA_KEY"}) == "环境变量 LWA_KEY"
    assert providers.key_hint({"keySource": "设置里填的 key", "apiKey": "sk-123456789xyz"}) == "设置里填的 key（尾号 9xyz）"
    assert providers.key_hint({"keySource": "设置里填的 key", "apiKey": "short"}) == "设置里填的 key"


def test_legacy_per_item_rows_fold_into_one(configured):
    for i in range(30):
        problems.report("enrich.summary", "NEEDS_HUMAN.AUTH_FAILED", "接口拒绝了 key（HTTP 403）", item_id=f"xhs-{i}")
    for i in range(10):
        problems.report("vision.layer1", "NEEDS_HUMAN.AUTH_FAILED", "接口拒绝了 key（HTTP 403）", item_id=f"xhs-{i}")
    assert len(problems.load()) == 40
    n = ai_health.migrate_legacy_rows()
    assert n == 40
    rows = problems.load()
    assert sorted(r["step"] for r in rows) == ["ai.summary", "ai.vision"]
    assert "影响 30 篇" in next(r["reason"] for r in rows if r["step"] == "ai.summary")
    assert ai_health.migrate_legacy_rows() == 0  # 幂等


def test_problems_list_cli_migrates(configured, capsys):
    problems.report("enrich.summary", "NEEDS_HUMAN.AUTH_FAILED", "x", item_id="xhs-1")
    assert cli.main(["problems", "list"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["step"] for r in out["problems"]] == ["ai.summary"]
    assert out["summary"]["needs_human"] == 1
    # 换好 key 后能点「现在修」（repair.describe 给 repairable）
    assert out["problems"][0]["repairable"] is True


def test_plan_for_ai_rows():
    assert repair.plan({"step": "ai.summary", "code": "NEEDS_HUMAN.AUTH_FAILED"})["action"] == "enrich_pending"
    assert repair.plan({"step": "ai.summary", "code": "NEEDS_HUMAN.AUTH_FAILED"})["auto"] is False
    p = repair.plan({"step": "ai.vision", "code": "TRANSIENT.NETWORK"})
    assert p["action"] == "enrich_pending" and p["auto"] is True
    assert repair.plan({"step": "ai.embed", "code": "TRANSIENT.HTTP_5XX"})["action"] == "embed"
    assert repair.plan({"step": "ai.refine", "code": "NEEDS_HUMAN.QUOTA_EXCEEDED"})["action"] == "refine_run"
    # 账号类的码落到 ai.* 上也仍是 human（不自动处理）
    assert repair.plan({"step": "ai.summary", "code": "NEEDS_HUMAN.NOT_LOGGED_IN"})["kind"] == "human"


# --------------------------------------------------------------------------
# 概要 / 识图走到归并：enrich 不记这篇的失败次数，连着撞就收手
# --------------------------------------------------------------------------


def _fail_call(status=403):
    def call(instruction, input_text, cfg):
        return providers.http_failure(status, "")
    return call


def test_enrich_api_failure_is_one_row_no_fails_and_batch_stops(env, configured, monkeypatch, capsys):
    env.favs = [_fav(i) for i in _ids(5)]
    _run(capsys)
    monkeypatch.setattr(llm_mod, "call_model", _fail_call())
    monkeypatch.setenv("LINK_BRAIN_RENDER_INPROC", "1")
    assert cli.main(["enrich", "--pending"]) == 1
    out = json.loads(capsys.readouterr().out)
    # 连着 2 篇撞接口就收手，剩下的留着
    assert len(out["failed"]) == enrich.API_STREAK_STOP and out["deferred"] == 5 - enrich.API_STREAK_STOP
    assert all(f["api_error"] and f["fails"] == 0 for f in out["failed"])
    rows = [r for r in problems.load() if r["step"].startswith(("ai.", "enrich.", "vision."))]
    assert [r["step"] for r in rows] == ["ai.summary"], rows
    assert "影响 2 篇" in rows[0]["reason"]
    # 这篇不记失败次数，也没有 RETRY_EXHAUSTED
    for sid in _ids(5):
        assert int(enrich.load_state("xiaohongshu", sid).get("fails") or 0) == 0
    # 接口好了：下一次 enrich 全补上，归并那条消掉
    from test_night_sync import _model
    monkeypatch.setattr(llm_mod, "call_model", _model())
    assert cli.main(["enrich", "--pending"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["done"]) == 5
    assert not any(r["step"] == "ai.summary" for r in problems.load())


def test_item_own_failure_still_counts(env, configured, monkeypatch, capsys):
    """模型回了东西但不合格（这篇自己的问题）：照旧按篇记失败次数。"""
    env.favs = [_fav(_ids(1)[0])]
    _run(capsys)
    monkeypatch.setattr(llm_mod, "call_model", lambda *a: {"status": "ok", "text": "不是 JSON", "error": None})
    monkeypatch.setenv("LINK_BRAIN_RENDER_INPROC", "1")
    assert cli.main(["enrich", "--pending"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["failed"][0]["fails"] == 1 and not out["failed"][0].get("api_error")
    assert not any(r["step"].startswith("ai.") for r in problems.load())


# --------------------------------------------------------------------------
# 轻量版：选了不带 AI 的功能组合 → 概要 / 识图按「未开启」处理，不报失败
# --------------------------------------------------------------------------


def test_light_preset_turns_ai_off_with_reason(monkeypatch):
    settings = _settings(selected=["core", "reader", "dataview", "ocr"])
    monkeypatch.setattr(ai_config, "load", lambda: settings)
    assert providers.resolve("summaryAI") is None and providers.resolve("visionAI") is None
    assert providers.resolve("textAI") is None and providers.resolve("embedAI") is None
    why = providers.why_not("summaryAI")
    assert "轻量版" in why and "AI 问答 · 概要 · 打标" in why
    assert "识图" in providers.why_not("visionAI")
    # 本地能力不受影响
    assert providers.resolve("ocr") is not None


def test_recommended_or_no_selection_keeps_ai(monkeypatch):
    for sel in (["core", "reader", "dataview", "ocr", "ai_text", "ai_vision"], None):
        settings = _settings(selected=sel)
        monkeypatch.setattr(ai_config, "load", lambda s=settings: s)
        assert providers.resolve("summaryAI") is not None and providers.resolve("visionAI") is not None
    # 插件还没对齐过（aiSynced 没置）：就算 selected 停在轻量版也不拦——升级当晚不许把人家在用的 AI 关掉
    settings = _settings(selected=["core", "reader", "dataview", "ocr"])
    settings["setup"].pop("aiSynced")
    monkeypatch.setattr(ai_config, "load", lambda: settings)
    assert providers.resolve("summaryAI") is not None and providers.why_not("summaryAI") == ""


def test_light_preset_enrich_marks_skipped_not_failed(env, monkeypatch, capsys):
    env.favs = [_fav(_ids(1)[0])]
    _run(capsys)
    settings = _settings(selected=["core", "reader", "dataview", "ocr"])
    monkeypatch.setattr(ai_config, "load", lambda: settings)
    monkeypatch.setattr(llm_mod, "call_model", lambda *a: pytest.fail("轻量版不许调模型"))
    monkeypatch.setenv("LINK_BRAIN_RENDER_INPROC", "1")
    assert cli.main(["enrich", "--pending"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["done"] == [f"xhs-{_ids(1)[0]}"] and out["failed"] == []
    doc = llm_mod.load_extracted("xiaohongshu", _ids(1)[0])
    assert doc["status"] == "skipped" and "轻量版" in doc["error"]
    rows = [r for r in problems.load() if r["step"].startswith(("ai.", "enrich.", "vision."))]
    assert rows and all(r["group"] == "off" for r in rows), rows
    assert not any(r["code"].startswith(("NEEDS_HUMAN.", "TRANSIENT.")) for r in rows)
