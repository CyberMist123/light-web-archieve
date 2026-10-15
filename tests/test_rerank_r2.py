"""1015 第三批 R2：精排适配器（不联网，_post 打桩）。"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from link_brain import ai_config, rerank


def _settings(**rr):
    s = ai_config._deep_merge(ai_config.DEFAULTS, {
        "summaryAI": {"mode": "http", "endpoint": "https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
                      "apiKey": "sk-test"}})
    s["rerank"] = {**s["rerank"], **rr}
    return s


def _docs(n):
    return [{"id": f"d{i}", "title": f"标题{i}", "tags": ["t"], "summary": "", "search_fields": {"body": "正" * 900}}
            for i in range(n)]


def test_defaults_off_and_registered():
    assert ai_config.DEFAULTS["rerank"]["enabled"] is False
    assert ai_config.DEFAULTS["rerank"]["model"] == "qwen3-rerank"
    assert rerank.enabled(ai_config._deep_merge(ai_config.DEFAULTS, {})) is False
    assert rerank.enabled(_settings(enabled=True)) is True


def test_endpoint_follows_aliyun_host_and_explicit_wins():
    s = _settings()
    assert rerank.endpoint(s) == "https://ws-x.cn-beijing.maas.aliyuncs.com" + rerank.RERANK_PATH
    assert rerank.endpoint(_settings(endpoint="https://e.example/r")) == "https://e.example/r"
    plain = ai_config._deep_merge(ai_config.DEFAULTS, {"summaryAI": {"endpoint": "https://api.deepseek.com/v1/chat/completions"},
                                                       "embedAI": {"endpoint": ""}})
    assert rerank.endpoint(plain) == rerank.DEFAULT_HOST + rerank.RERANK_PATH


def test_compact_doc_cuts_body():
    text = rerank.compact_doc(_docs(1)[0])
    assert text.startswith("标题：标题0") and "标签：t" in text
    assert text.count("正") == rerank.BODY_CHARS + 1  # 「正文：」本身一个


def test_reorders_by_index_and_keeps_tail(monkeypatch):
    seen = {}

    def fake(url, key, payload, timeout):
        seen.update(url=url, key=key, payload=payload, timeout=timeout)
        return {"output": {"results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.5},
                                       {"index": 1, "relevance_score": 0.1}]}, "usage": {"total_tokens": 42}}

    monkeypatch.setattr(rerank, "_post", fake)
    trace = {}
    out = rerank.rerank("问", _docs(5), _settings(topN=3), trace=trace)
    assert [d["id"] for d in out] == ["d2", "d0", "d1", "d3", "d4"]
    assert [d["rerank_score"] for d in out] == [0.9, 0.5, 0.1, None, None]
    assert seen["key"] == "sk-test" and seen["payload"]["parameters"]["top_n"] == 3
    assert len(seen["payload"]["input"]["documents"]) == 3
    assert trace["rerank"]["status"] == "ok" and trace["rerank"]["docs"] == 3 and trace["rerank"]["tokens"] == 42
    assert "sk-test" not in json.dumps(trace, ensure_ascii=False)


@pytest.mark.parametrize("data", [
    {},
    {"output": {"results": [{"index": 0, "relevance_score": 0.3}]}},
    {"output": {"results": [{"index": 0, "relevance_score": 0.3}, {"index": 0, "relevance_score": 0.2}]}},
    {"output": {"results": [{"index": 0, "relevance_score": 0.3}, {"index": 5, "relevance_score": 0.2}]}},
    {"output": {"results": [{"index": 0}, {"index": 1, "relevance_score": 0.2}]}},
])
def test_bad_response_raises(monkeypatch, data):
    monkeypatch.setattr(rerank, "_post", lambda *a: data)
    trace = {}
    with pytest.raises(rerank.RerankError):
        rerank.rerank("问", _docs(2), _settings(), trace=trace)
    assert trace["rerank"]["status"] == "error"


def test_http_503_and_timeout_raise(monkeypatch):
    def h503(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b'{"code":"ServiceUnavailable"}'))

    monkeypatch.setattr(rerank.urllib.request, "urlopen", h503)
    with pytest.raises(rerank.RerankError) as err:
        rerank.rerank("问", _docs(2), _settings())
    assert "503" in str(err.value) and "sk-test" not in str(err.value)

    def slow(req, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(rerank.urllib.request, "urlopen", slow)
    with pytest.raises(rerank.RerankError):
        rerank.rerank("问", _docs(2), _settings())


def test_no_key_raises(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    s = ai_config._deep_merge(ai_config.DEFAULTS, {})
    for cap in ("summaryAI", "textAI", "visionAI", "embedAI"):
        s[cap] = {**s[cap], "apiKey": "", "keyFile": "", "apiKeyEnv": ""}
    with pytest.raises(rerank.RerankError):
        rerank.rerank("问", _docs(2), s)


def test_empty_docs():
    assert rerank.rerank("问", [], _settings()) == []
