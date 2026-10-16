"""1016：Gemini 多把 key 轮流用（keyPool），用坏换下一把；全坏才走备用（概要 → 百炼 → 文本 AI；识图第二层 → 百炼）。"""
from __future__ import annotations

import pytest

from link_brain import providers, semantic


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    monkeypatch.setenv("LWA_GEMINI_KEYS", "k1,k2,k3")
    providers._POOL_DEAD.clear()
    yield
    providers._POOL_DEAD.clear()


def test_pool_keys_from_env_and_file(monkeypatch, tmp_path):
    assert providers.pool_keys("gemini") == ["k1", "k2", "k3"]
    monkeypatch.delenv("LWA_GEMINI_KEYS")
    f = tmp_path / "keys.txt"
    f.write_text("a1\na2\n\na1\n", encoding="utf-8")
    from link_brain import storage
    monkeypatch.setattr(storage, "user_config", lambda: {"gemini_keys_file": str(f)})
    assert providers.pool_keys("gemini") == ["a1", "a2"]


def test_call_with_pool_rotates_on_dead_key_codes():
    seen = []

    def call(cfg):
        seen.append(cfg["apiKey"])
        if cfg["apiKey"] == "k1":
            return providers.result("failed", code="NEEDS_HUMAN.AUTH_FAILED")
        if cfg["apiKey"] == "k2":
            return providers.result("failed", code="TRANSIENT.HTTP_429")
        return providers.result("ok", "好")

    got = providers.call_with_pool({"keyPool": "gemini"}, call)
    assert got["status"] == "ok" and got["pool_key_index"] == 3 and seen == ["k1", "k2", "k3"]
    # 今天用坏的不再试
    seen.clear()
    providers.call_with_pool({"keyPool": "gemini"}, call)
    assert seen == ["k3"]
    assert providers.resolve_key({"keyPool": "gemini"}) == ("k3", "")


def test_call_with_pool_does_not_rotate_on_content_errors():
    seen = []

    def call(cfg):
        seen.append(cfg["apiKey"])
        return providers.result("failed", code="PERMANENT.MODEL_OUTPUT_INVALID")

    got = providers.call_with_pool({"keyPool": "gemini"}, call)
    assert got["code"] == "PERMANENT.MODEL_OUTPUT_INVALID" and seen == ["k1"], "内容不合格不是 key 的事，不换 key"


def test_call_with_pool_all_dead():
    got = providers.call_with_pool({"keyPool": "gemini"},
                                   lambda c: providers.result("failed", code="NEEDS_HUMAN.QUOTA_EXCEEDED"))
    assert got["status"] == "failed" and got["code"] == "NEEDS_HUMAN.QUOTA_EXCEEDED"
    got = providers.call_with_pool({"keyPool": "gemini"}, lambda c: providers.result("ok"))
    assert got["code"] == "NEEDS_HUMAN.AUTH_FAILED", "全用坏了：直接报，交给备用"


def test_no_pool_calls_once():
    assert providers.call_with_pool({"apiKey": "x"}, lambda c: providers.result("ok", c["apiKey"]))["text"] == "x"


def test_embeddings_rotate_keys(monkeypatch):
    monkeypatch.setattr(providers, "resolve", lambda cap, settings=None: {"keyPool": "gemini", "endpoint": "https://e/embeddings"})
    tried = []

    def once(texts, cfg, timeout, endpoint, key):
        tried.append(key)
        if key != "k2":
            raise semantic.EmbedHTTPError(429, "quota")
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(semantic, "_post_embeddings_once", once)
    assert semantic._embed_with_pool(["a"], {"model": "m"}, 5) == [[0.1, 0.2]]
    assert tried == ["k1", "k2"]


def test_embeddings_non_key_error_raises_without_rotating(monkeypatch):
    monkeypatch.setattr(providers, "resolve", lambda cap, settings=None: {"keyPool": "gemini", "endpoint": "https://e"})
    tried = []

    def once(texts, cfg, timeout, endpoint, key):
        tried.append(key)
        raise semantic.EmbedHTTPError(400, "bad input")

    monkeypatch.setattr(semantic, "_post_embeddings_once", once)
    with pytest.raises(semantic.EmbedHTTPError):
        semantic._embed_with_pool(["a"], {"model": "m"}, 5)
    assert tried == ["k1"]


def test_refine_can_have_its_own_endpoint():
    settings = {"visionAI": {"mode": "http", "endpoint": "https://gemini/x", "keyPool": "gemini", "model": "g-flash",
                             "refine": {"endpoint": "https://dashscope/x", "keyFile": "k.csv", "model": "qwen-max"}}}
    cfg = providers.raw_config("visionAI.refine", settings)
    assert cfg["endpoint"] == "https://dashscope/x" and cfg["model"] == "qwen-max"
    assert "keyPool" not in cfg and cfg["keyFile"] == "k.csv" and "refine" not in cfg
    plain = providers.raw_config("visionAI.refine", {"visionAI": {"mode": "http", "endpoint": "https://a", "model": "m",
                                                                  "refineModel": "mm"}})
    assert plain["model"] == "mm" and plain["endpoint"] == "https://a"


def test_summary_fallbacks_order(monkeypatch):
    from link_brain import llm
    primary = {"endpoint": "https://gemini/chat", "model": "g", "apiKey": "k1", "keyPool": "gemini"}
    monkeypatch.setattr(providers, "finalize", lambda cap, cfg: ({**cfg, "apiKey": "bk"}, ""))
    monkeypatch.setattr(llm, "alternate_summary_config",
                        lambda p, s: {"endpoint": "https://deepseek/chat", "model": "ds", "apiKey": "dk"})
    out = llm.summary_fallbacks(primary, {"summaryAI": {"fallback": {"endpoint": "https://dashscope/chat", "model": "q"}}})
    assert [c["model"] for c in out] == ["q", "ds"], "她定：Gemini 不行先换百炼，再换文本 AI"
