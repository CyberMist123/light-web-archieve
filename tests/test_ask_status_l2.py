"""批次 D · L2：问答失败的原因字段（A5）、没配问答 AI 时照样列出相关收藏（A6）、冷启动阶段字（A13）。

全程不联网、不起真模型：call_text 要么换成假的，要么保持原样但 textAI 关掉（call_text 根本不会被调到）。
"""

from __future__ import annotations

import pytest

from link_brain import ask, problems
from tests.test_ask import FAKE_ITEMS


def _settings(text_ai):
    return ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {"textAI": text_ai})


@pytest.fixture
def items(monkeypatch):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in FAKE_ITEMS])


@pytest.fixture
def reports(monkeypatch):
    seen = []
    monkeypatch.setattr(problems, "report", lambda step, code, *a, **k: seen.append(f"{step}|{code}"))
    return seen


def test_text_ai_off_lists_sources_without_model(items, reports, monkeypatch):
    monkeypatch.setattr(ask.ai_config, "load", lambda: _settings({"mode": "off"}))
    monkeypatch.setattr(ask, "_select_sources", lambda *a, **k: pytest.fail("没配 AI 不该挑材料"))
    phases = []
    r = ask.answer("AI 做梦", on_phase=phases.append)
    assert r["status"] == "error"
    assert r["error_kind"] == "not_configured"
    assert r["code"] == "SKIPPED.NOT_CONFIGURED"
    assert r["error"]
    assert r["markdown"].startswith("问答模型还没配好（设置 → AI → 文本 AI）：")
    assert len(r["sources"]) >= 1
    assert r["model_called"] is False
    assert not any(p.startswith("挑选材料") or p.startswith("生成回答") for p in phases), phases
    assert not any(x.endswith("|SKIPPED.FALLBACK") for x in reports)


def test_text_ai_off_with_source_ids_still_lists_them(items, monkeypatch):
    monkeypatch.setattr(ask.ai_config, "load", lambda: _settings({"mode": "off"}))
    r = ask.answer("这篇讲什么", source_ids=["a"])
    assert r["error_kind"] == "not_configured" and [s["id"] for s in r["sources"]] == ["a"]


def test_api_failure_reports_kind_and_code(items, monkeypatch):
    monkeypatch.setattr(ask.ai_config, "load", lambda: _settings({}))
    monkeypatch.setattr(ask, "call_text", lambda *a: {"status": "failed", "code": "NEEDS_HUMAN.AUTH_FAILED", "error": "401"})
    r = ask.answer("AI 做梦")
    assert r["status"] == "error"
    assert r["error_kind"] == "api"
    assert r["code"] == "NEEDS_HUMAN.AUTH_FAILED"
    assert r["error"] == "401"
    assert r["sources"]
    assert r["markdown"] == "AI 回答失败：401"   # 设置页「试问一句」照旧显示这句


def test_phases_understand_first_only_for_search_path(items, monkeypatch):
    monkeypatch.setattr(ask.ai_config, "load", lambda: _settings({}))
    monkeypatch.setattr(ask, "call_text", lambda *a: {"status": "ok", "text": "答 [来源1]"})
    phases = []
    ask.answer("AI 做梦", on_phase=phases.append)
    assert phases[0] == "理解问题"
    phases.clear()
    ask.answer("AI 做梦", source_ids=["a", "b"], on_phase=phases.append)
    assert "理解问题" not in phases
    assert any(p.startswith("检索收藏：用你留下的 ") for p in phases)
    phases.clear()
    ask.answer("这篇讲什么", source_ids=["a"], on_phase=phases.append)
    title = next(x["title"] for x in FAKE_ITEMS if x["id"] == "a")
    assert f"只看这一篇：{title[:30]}" in phases
