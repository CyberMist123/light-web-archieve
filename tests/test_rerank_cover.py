"""r4-d1 补测：精排适配器的配置解析与坏返回路径（不联网，_post 打桩）。"""
from __future__ import annotations

import pytest

from link_brain import ai_config, rerank


def _settings(**rr):
    s = ai_config._deep_merge(ai_config.DEFAULTS, {"summaryAI": {"mode": "http",
                                                                 "endpoint": "https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
                                                                 "apiKey": "sk-test"}})
    s["rerank"] = {**s["rerank"], **rr}
    return s


def _docs(n):
    return [{"id": f"d{i}", "title": f"标题{i}", "search_fields": {"body": f"正文{i}"}} for i in range(n)]


def test_aliyun_base_keeps_scheme_host_drops_path():
    assert rerank._aliyun_base("https://dashscope.aliyuncs.com/api/v1/x?y=1") == "https://dashscope.aliyuncs.com"
    assert rerank._aliyun_base("http://gw.cn-hangzhou.aliyuncs.com:8080/v1") == "http://gw.cn-hangzhou.aliyuncs.com:8080"
    assert rerank._aliyun_base("https://api.deepseek.com/v1") == ""
    assert rerank._aliyun_base("ftp://x.aliyuncs.com/a") == ""  # 只认 http(s)
    assert rerank._aliyun_base("") == "" and rerank._aliyun_base(None) == ""


def test_enabled_reads_explicit_settings_or_loaded_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    assert rerank.enabled(_settings(enabled=True)) is True
    assert rerank.enabled(_settings()) is False
    # settings=None 走 ai_config.load()：空 home 里没有 data.json，fail-open 回纯默认（默认关）
    assert rerank.enabled(None) is False


def test_endpoint_borrow_order_and_whitespace(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    # summaryAI 不是 aliyun 时依次往下借：textAI 的 aliyun 主机接上精排路径
    s = _settings()
    s["summaryAI"]["endpoint"] = "https://api.deepseek.com/chat/completions"
    s["textAI"] = {"endpoint": "https://t.aliyuncs.com/adaptor/v1"}
    assert rerank.endpoint(s) == "https://t.aliyuncs.com" + rerank.RERANK_PATH
    # 显式 endpoint 带空白也原样保留（只 strip 首尾），别的配置不影响
    assert rerank.endpoint(_settings(endpoint=" https://e.example/r ")) == "https://e.example/r"
    # 没有可借的就回落官方域名
    s2 = ai_config._deep_merge(ai_config.DEFAULTS, {})
    assert rerank.endpoint(s2) == rerank.DEFAULT_HOST + rerank.RERANK_PATH


def test_compact_doc_parts_and_limits():
    item = {"title": "T", "tags": [f"t{i}" for i in range(15)], "summary": "概" * 300,
            "search_fields": {"body": "a" * 600, "ocr": " b", "transcript": " c"}}
    text = rerank.compact_doc(item)
    assert text.splitlines()[0] == "标题：T"
    assert f"标签：{' '.join(f't{i}' for i in range(12))}" in text and "t12" not in text
    assert "概要：" + "概" * 200 in text.splitlines()  # 概要截到 200（不进 300 全文）
    body_line = [ln for ln in text.splitlines() if ln.startswith("正文：")][0]
    assert len(body_line) == len("正文：") + rerank.BODY_CHARS  # 正文拼 ocr/transcript 后截 500
    # 什么都没有的 item 只剩标题一行，不抛
    assert rerank.compact_doc({}) == "标题："


def test_scores_valid_shapes_and_error_kinds():
    ok = rerank._scores({"output": {"results": [{"index": 1, "relevance_score": 0.25}, {"index": 0, "relevance_score": 1}]}}, 2)
    assert ok == {1: 0.25, 0: 1.0}
    with pytest.raises(rerank.RerankError, match="缺 output.results"):
        rerank._scores({}, 2)
    with pytest.raises(rerank.RerankError, match="缺 output.results"):
        rerank._scores(None, 2)
    with pytest.raises(rerank.RerankError, match="格式不对"):
        rerank._scores({"output": {"results": [{"index": 0, "relevance_score": "高"}]}}, 1)
    with pytest.raises(rerank.RerankError, match="越界或重复"):
        rerank._scores({"output": {"results": [{"index": 0, "relevance_score": 1}, {"index": 0, "relevance_score": 1}]}}, 1)
    with pytest.raises(rerank.RerankError, match="不完整"):
        rerank._scores({"output": {"results": [{"index": 0, "relevance_score": 1}]}}, 2)


def test_rerank_post_failure_sets_trace_error(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))

    def boom(url, key, payload, timeout):
        raise rerank.RerankError("连不上精排接口：URLError")

    monkeypatch.setattr(rerank, "_post", boom)
    trace = {}
    with pytest.raises(rerank.RerankError, match="连不上"):
        rerank.rerank("问", _docs(2), _settings(), trace=trace)
    assert trace["rerank"]["status"] == "error"
    assert trace["rerank"]["error"] == "连不上精排接口：URLError"
    assert trace["rerank"]["model"] == "qwen3-rerank" and trace["rerank"]["docs"] == 2
    assert "seconds" in trace["rerank"]  # finally 里补时耗

    # HTTP 类失败：错误信息进 trace，key 不进
    monkeypatch.setattr(rerank, "_post", lambda *a: (_ for _ in ()).throw(rerank.RerankError("精排接口 HTTP 503（x）")))
    trace2 = {}
    with pytest.raises(rerank.RerankError):
        rerank.rerank("问", _docs(2), _settings(), trace=trace2)
    assert trace2["rerank"]["status"] == "error" and "HTTP 503" in trace2["rerank"]["error"]
    assert "sk-test" not in repr(trace2)


def test_rerank_garbage_data_and_tie_keeps_input_order(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    # 乱数据（非 dict / 缺 output）都归到 RerankError，不抛别的类型
    for garbage in ([1, 2], {"nope": 1}, {"output": {}}):
        monkeypatch.setattr(rerank, "_post", lambda *a, g=garbage: g)
        trace = {}
        with pytest.raises(rerank.RerankError, match="缺 output.results"):
            rerank.rerank("问", _docs(2), _settings(), trace=trace)
        assert trace["rerank"]["status"] == "error"

    # 同分时按输入顺序排（sorted 的次键是原 index）
    monkeypatch.setattr(rerank, "_post",
                        lambda *a: {"output": {"results": [{"index": 1, "relevance_score": 0.5},
                                                            {"index": 0, "relevance_score": 0.5}]}})
    out = rerank.rerank("问", _docs(2), _settings())
    assert [d["id"] for d in out] == ["d0", "d1"]
