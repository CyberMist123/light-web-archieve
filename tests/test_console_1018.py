"""1018 AI 页重排：每天花费上限（只拦后台补跑的要钱模型）+「每个功能用谁」数据（routes）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from link_brain import ai_config, ai_health, budget, providers, usage, visual

BJ = timezone(timedelta(hours=8))
PAID = {"endpoint": "https://ws.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen3.8-max", "apiKey": "k-123456789"}
# 1023：免费只认显式标记——Gemini 免费 key 池（keyPool: gemini）才算免费；同一个模型用付费 key = 要钱
FREE = {"endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-3.5-flash", "apiKey": "g-123456789", "keyPool": "gemini"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    budget._cache.update(at=0.0, day="", spent=0.0)
    monkeypatch.setattr(ai_config, "load", lambda: {"budget": {"dailyYuan": 1}})
    yield


def _spend(yuan_worth_of_max_input: float, when: datetime | None = None):
    """记一笔 qwen3.8-max 调用，花费 ≈ 给定元数（input ¥12 / 百万 token）。"""
    tokens = int(yuan_worth_of_max_input / 12 * 1_000_000)
    usage.record("visionAI", PAID, {"prompt_tokens": tokens, "completion_tokens": 0}, feature="vision",
                 now=when or datetime.now().astimezone())


def test_cap_default_and_off():
    assert budget.daily_cap({}) == budget.DEFAULT_YUAN
    assert budget.daily_cap({"budget": {"dailyYuan": 0}}) == 0
    assert budget.daily_cap({"budget": {"dailyYuan": "坏的"}}) == budget.DEFAULT_YUAN


def test_paid_vs_free():
    assert budget.is_paid(PAID) and not budget.is_paid(FREE) and not budget.is_paid({"mode": "cli", "model": "qwen3.8-max"})
    assert budget.is_paid({k: v for k, v in FREE.items() if k != "keyPool"}), "没标免费的 Gemini key：按要钱的算"
    assert budget.is_paid({"model": "没听过的模型-x1"}), "价格表里查不到 = 未计价，预算按要钱的拦"


def test_background_paid_call_blocked_after_cap():
    _spend(1.2)
    with usage.tag("vision"):
        got = budget.blocked(PAID)
        assert got and got["code"] == budget.CODE and got["api_error"] is True
        assert budget.blocked(FREE) is None, "免费的照跑"
    with usage.tag("ask"):
        assert budget.blocked(PAID) is None, "她自己问收藏不拦"
    assert ai_health.is_api_failure(got), "按接口故障归并，不按篇记失败"
    assert budget.CODE in ai_health.CAUSE


def test_under_cap_or_unlimited_not_blocked(monkeypatch):
    _spend(0.5)
    with usage.tag("vision"):
        assert budget.blocked(PAID) is None
    monkeypatch.setattr(ai_config, "load", lambda: {"budget": {"dailyYuan": 0}})
    _spend(5)
    budget._cache.update(at=0.0)
    with usage.tag("vision"):
        assert budget.blocked(PAID) is None, "0 = 不限"


def test_yesterday_beijing_not_counted():
    yesterday = datetime.now(BJ).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=5)
    _spend(5, yesterday)
    assert budget.spent_today(fresh=True) < 0.01


def test_visual_chat_stops_before_network(monkeypatch, tmp_path):
    import httpx
    from PIL import Image
    _spend(1.2)
    img = tmp_path / "a.png"
    Image.new("RGB", (10, 10), "white").save(img)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("到上限了不该发请求"))
    with usage.tag("vision"):
        got = visual._chat(img, "看图", PAID, max_tokens=10, timeout=5)
    assert got["code"] == budget.CODE


def test_routes_shape_without_keys(monkeypatch):
    from link_brain import ai_routes
    settings = {"setup": {"selected": ["ai_text", "ai_vision"]},
                "textAI": {"mode": "http", **{k: v for k, v in PAID.items() if k != "model"}, "model": "deepseek-v4-flash"},
                "visionAI": {"mode": "http", **PAID, "model": "qwen3.8-flash"},
                "models": [{"name": "DeepSeek"}, {"name": "藏起来的", "hidden": True}], "activeModel": "DeepSeek"}
    monkeypatch.setattr(ai_config, "load", lambda: settings)
    monkeypatch.setattr(providers, "pool_keys", lambda name: [])
    out = ai_routes.routes(settings)
    ids = [f["id"] for f in out["features"]]
    assert ids[:3] == ["ask", "summary", "vision"]
    assert out["features"][0]["choices"] == ["DeepSeek"]
    assert "k-123456789" not in json.dumps(out, ensure_ascii=False), "输出里不能带 key"
    vis = next(f for f in out["features"] if f["id"] == "vision")
    assert vis["chain"][0]["model"] == "qwen3.8-flash" and vis["state"] == "ok"
    assert out["budget"]["daily_yuan"] == budget.DEFAULT_YUAN
