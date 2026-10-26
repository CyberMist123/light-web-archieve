import pytest

from link_brain import ai_config, providers, comment_fill
from link_brain.setup import pipeline, components


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setattr(components, "check", lambda targets: {"results": []})
    monkeypatch.setattr(pipeline, "selected", lambda: list(pipeline.LIGHT))
    monkeypatch.setattr(providers, "resolve", lambda cap: None)
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True})
    monkeypatch.setattr(comment_fill, "survey", lambda: {"pending": 0, "missing": 0})


def test_selected_default_and_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setattr(ai_config, "load", lambda: {"setup": {"selected": []}})
    result = pipeline.selected()
    assert result == pipeline.LIGHT
    assert result is not pipeline.LIGHT
    configured = ["core", "ai_text"]
    monkeypatch.setattr(ai_config, "load", lambda: {"setup": {"selected": configured}})
    assert pipeline.selected() == configured
    assert pipeline.selected() is not configured


def test_selected_load_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    def fail():
        raise ValueError("invalid config")
    monkeypatch.setattr(ai_config, "load", fail)
    assert pipeline.selected() == pipeline.LIGHT


def test_ai_requires_selection_and_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "resolve", lambda cap: calls.append(cap) or object())
    assert not pipeline._ai_on([], "visionAI")
    assert calls == []
    assert pipeline._ai_on(["ai_vision"], "visionAI")
    assert pipeline._ai_on(["ai_text"], "embedAI")
    def fail(cap):
        raise ValueError("unconfigured")
    monkeypatch.setattr(providers, "resolve", fail)
    assert not pipeline._ai_on(["ai_text"], "summaryAI")


def test_light_run_orders_children_and_progress(isolated):
    calls, events = [], []
    def child(args, **kwargs):
        calls.append((args, kwargs["timeout_min"], kwargs["env_extra"]))
        kwargs["on_line"]("progress")
        return 0, False
    result = pipeline.run(events.append, child=child, account_check=lambda: ("", ""))
    assert result["ok"]
    assert calls == [(["sync-favorites", "--limit", "0", "--extract"], 170,
                      {"LINK_BRAIN_SYNC_TRIGGER": "manual"}), (["catalog"], 10, None)]
    assert [r["id"] for r in result["stages"]] == [s for s, _ in pipeline.STAGES]
    assert any(e["text"] == "progress" for e in events)


def test_blocked_account_keeps_offline_catalog(isolated):
    calls = []
    def child(args, **kwargs):
        calls.append(args)
        return 0, False
    result = pipeline.run(lambda ev: None, child=child, account_check=lambda: ("LOGIN", "login required"))
    assert not result["ok"]
    assert result["code"] == "NEEDS_HUMAN"
    assert calls == [["catalog"]]
    states = {r["id"]: r["state"] for r in result["stages"]}
    assert states["sync"] == states["comments"] == "skipped"
    assert states["catalog"] == "ok"


def test_ai_run_partial_sync_and_catalog_timeout(isolated, monkeypatch):
    monkeypatch.setattr(pipeline, "selected", lambda: ["ai_text", "ai_vision"])
    monkeypatch.setattr(providers, "resolve", lambda cap: object())
    calls = []
    def child(args, **kwargs):
        calls.append(args[0])
        return (None, True) if args == ["catalog"] else (2, False)
    result = pipeline.run(lambda ev: None, child=child, account_check=lambda: ("", ""))
    assert calls == ["sync-favorites", "enrich", "catalog", "embed"]
    assert not result["ok"]
    states = {r["id"]: r["state"] for r in result["stages"]}
    assert states["sync"] == states["enrich"] == states["embed"] == "ok"
    assert states["catalog"] == "failed"
