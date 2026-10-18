"""1018：Gemini 免费 key 用完 → 第一层识图备用先走同代便宜模型（别一上来就 qwen3.8-max，1017 一晚 ≈ ¥12.5）；
key 池全歇着时照实报「额度用完 / 限流」而不是「key 坏了」（概览不再挂「去换一把 key」）。"""
from __future__ import annotations

import pytest

from link_brain import providers, vision

STRONG = {"endpoint": "https://ws.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
          "apiKey": "ali-key-123456", "model": "qwen3.8-max"}
PRIMARY = {"endpoint": vision.GEMINI_ENDPOINT, "keyPool": "gemini", "model": "gemini-3.5-flash"}


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    monkeypatch.setenv("LWA_GEMINI_KEYS", "k1,k2")
    providers._POOL_DEAD.clear()
    providers._POOL_WHY.clear()
    yield
    providers._POOL_DEAD.clear()
    providers._POOL_WHY.clear()


def test_cheap_twin_is_same_family_flash():
    twin = vision.cheap_twin(STRONG)
    assert twin["model"] == "qwen3.8-flash", "max 的同代便宜看图模型，不是更老的 qwen3-vl-flash"
    assert twin["endpoint"] == STRONG["endpoint"] and twin["apiKey"] == STRONG["apiKey"]
    assert vision.cheap_twin({**STRONG, "model": "qwen3.8-flash"}) is None, "已经是便宜的就没有更便宜的同代"
    assert vision.cheap_twin({**STRONG, "model": "没在价格表里"}) is None
    assert vision.cheap_twin(STRONG, "qwen3-vl-flash")["model"] == "qwen3-vl-flash", "设置 backupModel 指定的优先"


def test_backups_put_cheap_before_strong(monkeypatch):
    monkeypatch.setattr(vision, "strong_config", lambda: dict(STRONG))
    monkeypatch.delenv("LWA_GEMINI_KEYS")
    models = [c["model"] for c in vision.vision_backups(PRIMARY)]
    assert models == ["qwen3.8-flash", "qwen3.8-max"]


def test_pool_all_daily_limited_is_not_auth_failed():
    for k in ("k1", "k2"):
        providers.pool_mark_dead("gemini", k, "TRANSIENT.HTTP_429", daily=True)
    got = providers.call_with_pool({"keyPool": "gemini"}, lambda c: pytest.fail("不该再调"))
    assert got["code"] == "TRANSIENT.HTTP_429" and got["daily_limit"] is True
    assert "明天自动恢复" in got["error"]


def test_pool_per_minute_limit_says_wait():
    for k in ("k1", "k2"):
        providers.pool_mark_dead("gemini", k, "TRANSIENT.HTTP_429", daily=False)
    got = providers.call_with_pool({"keyPool": "gemini"}, lambda c: pytest.fail("不该再调"))
    assert got["code"] == "TRANSIENT.HTTP_429" and not got.get("daily_limit")


def test_pool_with_a_rejected_key_still_needs_human():
    providers.pool_mark_dead("gemini", "k1", "TRANSIENT.HTTP_429", daily=True)
    providers.pool_mark_dead("gemini", "k2", "NEEDS_HUMAN.AUTH_FAILED")
    got = providers.call_with_pool({"keyPool": "gemini"}, lambda c: pytest.fail("不该再调"))
    assert got["code"] == "NEEDS_HUMAN.AUTH_FAILED" and "1 把被拒" in got["error"]


def test_empty_pool_says_not_configured(monkeypatch):
    monkeypatch.delenv("LWA_GEMINI_KEYS")
    monkeypatch.setattr(providers, "pool_keys", lambda name: [])
    got = providers.call_with_pool({"keyPool": "gemini"}, lambda c: pytest.fail("不该再调"))
    assert got["code"] == "NEEDS_HUMAN.AUTH_FAILED" and "没配" in got["error"]
