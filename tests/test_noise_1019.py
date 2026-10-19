"""1019 她：Gemini 换 key / 换备用是自然的，不该报错；掉登录只报一次（熔断中那条不再单推）。"""
from __future__ import annotations

from link_brain import ai_health, problems, providers

from test_ai_health_1008 import configured  # noqa: F401 - fixture


def _open(step):
    return [r for r in problems.load() if r.get("step") == step and not r.get("resolved_at")]


def test_switched_429_is_not_listed(configured):
    cfg = providers.resolve("visionAI")
    ai_health.record("visionAI", providers.http_failure(429, "quota"), cfg=cfg, switched_to="通义千问 qwen")
    assert _open("ai.vision") == []
    assert ai_health.status()["visionAI"]["switched_to"] == "通义千问 qwen"  # 诊断里照样看得到


def test_switched_but_key_rejected_still_listed(configured):
    cfg = providers.resolve("summaryAI")
    ai_health.record("summaryAI", providers.http_failure(403, '{"code":"InvalidApiKey"}'), cfg=cfg, switched_to="千问")
    assert len(_open("ai.summary")) == 1, "key 被拒要人换，备用补上了也照实挂着"


def test_unswitched_429_still_listed(configured):
    cfg = providers.resolve("visionAI")
    ai_health.record("visionAI", providers.http_failure(429, "quota"), item_id="xhs-" + "0" * 24, cfg=cfg)
    assert len(_open("ai.vision")) == 1


def test_exhausted_pool_is_not_not_configured(monkeypatch):
    monkeypatch.setenv("LWA_GEMINI_KEYS", "k1,k2")
    providers._POOL_DEAD.clear()
    try:
        for k in ("k1", "k2"):
            providers.pool_mark_dead("gemini", k, "TRANSIENT.HTTP_429", True)
        cfg, why = providers._check("summaryAI", {"mode": "http", "endpoint": "https://g/v1/chat/completions",
                                                  "model": "g", "keyPool": "gemini", "requireKey": True})
        assert cfg is not None and not why, "池配了只是今天用光：照样给配置，让调用方换备用"
        got = providers.call_with_pool(cfg, lambda c: providers.result("ok"))
        assert got["code"] == "TRANSIENT.HTTP_429"
        monkeypatch.setenv("LWA_GEMINI_KEYS", "")
        cfg, why = providers._check("summaryAI", {"mode": "http", "endpoint": "https://g/v1/chat/completions",
                                                  "model": "g", "keyPool": "gemini", "requireKey": True})
        assert cfg is None and why, "一把都没配才是没配"
    finally:
        providers._POOL_DEAD.clear()


def test_risk_hold_not_pushed_when_cause_open(monkeypatch):
    pushed = []
    monkeypatch.setattr(problems, "_push", lambda row: pushed.append(row["code"]))
    problems.report("login", "NEEDS_HUMAN.NOT_LOGGED_IN", "掉登录")
    problems.report("login", "NEEDS_HUMAN.RISK_HOLD", "熔断中（NOT_LOGGED_IN）")
    assert pushed == ["NEEDS_HUMAN.NOT_LOGGED_IN"]
    assert [r["code"] for r in problems.load(include_minor=False) if not r.get("resolved_at")] == ["NEEDS_HUMAN.NOT_LOGGED_IN"]


def test_risk_hold_alone_still_pushed(monkeypatch):
    pushed = []
    monkeypatch.setattr(problems, "_push", lambda row: pushed.append(row["code"]))
    problems.report("login", "NEEDS_HUMAN.RISK_HOLD", "熔断中")
    assert pushed == ["NEEDS_HUMAN.RISK_HOLD"]


def test_delete_drops_from_catalog_data_without_rebuild(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from link_brain import catalog, remove
    data = tmp_path / "_archive" / catalog.DATA_NAME
    data.parent.mkdir(parents=True)
    data.write_text(json.dumps({"count": 2, "items": [{"id": "a"}, {"id": "b"}]}), "utf-8")
    monkeypatch.setattr(catalog.storage, "vault_root", lambda: tmp_path)
    monkeypatch.setattr(remove, "delete_items", lambda ids: {"ok": True, "results": [{"item_id": "a", "status": "deleted"}]})
    monkeypatch.setattr(remove, "publish_trash", lambda *a, **k: None)
    built = []
    monkeypatch.setattr(catalog, "build", lambda *a, **k: built.append(1))
    remove.run(SimpleNamespace(command="delete", item_ids=["a"]))
    got = json.loads(data.read_text("utf-8"))
    assert [i["id"] for i in got["items"]] == ["b"] and got["count"] == 1 and built == []


def test_interrupted_sync_is_minor():
    problems.report("sync.favorites", "TRANSIENT.INTERRUPTED", "上次同步中途被打断")
    assert [r for r in problems.load(include_minor=False) if not r.get("resolved_at")] == []
