"""Lot B：chunk 索引 + embedding 旁挂 + hybrid 检索。全部 mock provider，不打真网。"""
import json

import pytest

from link_brain import ask, semantic, storage
from link_brain.retrieval import rank, rank_query, retrieve_payload, semantic_hits


def _vec(text):
    # 确定性假向量：四个维度分别数「梦 / 鱼 / 猫」出现次数，末位常数防零向量
    return [float(text.count("梦") + (5 if "sleep" in text else 0)),
            float(text.count("鱼")), float(text.count("猫")), 1.0]


@pytest.fixture(autouse=True)
def isolated_vault(monkeypatch, tmp_path):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "vault"))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("LINK_BRAIN_MODELS_DIR", str(tmp_path / "no-keys"))
    semantic._MATRIX_CACHE.update(stamp=None, data=None)
    semantic._QUERY_VEC_CACHE.clear()
    yield


@pytest.fixture
def mock_provider(monkeypatch):
    calls = []
    def fake(texts, cfg, timeout):
        calls.append(list(texts))
        return [_vec(t) for t in texts]
    monkeypatch.setattr(semantic, "_post_embeddings", fake)
    return calls


def _write_catalog(items):
    storage.write_json(storage.archive_root() / "catalog-data.json", {"items": items})


ITEMS = [
    {"id": "dream", "title": "离线整理", "search_fields": {"body": "夜里做梦，把白天的事重放。" * 20}},
    {"id": "fish", "title": "鱼片菜谱", "search_fields": {"body": "蒜香鱼片，先腌后煎。" * 20}},
    {"id": "cat", "title": "猫粮测评", "search_fields": {"body": "猫咪爱吃这一款。" * 20}},
]


def test_chunking_respects_size_and_fields():
    body = "\n\n".join("# 第%d步\n" % i + "这一步的具体做法说明。" * 12 for i in range(6))
    item = {"id": "x", "title": "标题", "tags": ["菜谱"], "summary": "概要",
            "search_fields": {"body": body, "ocr": "图里的字。" * 10, "comments": "好评。" * 5,
                              "transcript": "", "attachments": ""}}
    chunks = semantic.chunk_item(item)
    fields = {f for f, _, _ in chunks}
    assert {"meta", "body", "ocr", "comments"} <= fields
    assert "transcript" not in fields  # 空字段不产块
    for _, _, text in chunks:
        assert len(text) <= semantic.CHUNK_MAX
    body_chunks = [t for f, _, t in chunks if f == "body"]
    assert len(body_chunks) >= 2 and all(len(t) >= 100 for t in body_chunks[:-1])


def test_embed_is_incremental_and_all_recomputes(mock_provider):
    _write_catalog(ITEMS)
    first = semantic.run_embed()
    assert first["status"] == "ok" and first["embedded_now"] > 0
    assert semantic.db_path().is_file()
    again = semantic.run_embed()
    assert again["embedded_now"] == 0 and again["embedded_total"] == first["embedded_total"]
    redo = semantic.run_embed(re_embed=True)
    assert redo["embedded_now"] == first["embedded_total"]


@pytest.mark.real_embeddings  # 走真 provider 代码：env/CSV 都被 fixture 清空，no-api-key 在发包前就抛
def test_embed_without_key_fails_closed_but_search_fails_open():
    _write_catalog(ITEMS)
    result = semantic.run_embed()  # 真实 provider 路径：没 key 直接 no-api-key，不联网
    assert result["status"] == "failed" and "error" in result
    assert semantic.query_hits("做梦") is None
    assert rank_query(ITEMS, "做梦") == rank(ITEMS, ask.query_terms("做梦"))


def test_no_db_means_pure_lexical():
    assert semantic.query_hits("任何问题") is None
    assert semantic_hits("任何问题") is None
    hits = rank_query(ITEMS, "做梦")
    assert hits == rank(ITEMS, ask.query_terms("做梦"))


def test_hybrid_surfaces_semantic_only_hit_and_chunk_evidence(monkeypatch, mock_provider):
    _write_catalog(ITEMS)
    assert semantic.run_embed()["status"] == "ok"
    question = "sleep replay"  # 词法零命中；假查询向量与「梦」chunk 同向
    assert rank(ITEMS, ask.query_terms(question)) == []
    hits = rank_query(ITEMS, question)
    assert hits and hits[0][1]["id"] == "dream"
    monkeypatch.setattr(ask, "load_items", lambda: ITEMS)
    payload = retrieve_payload(question)
    top = payload["results"][0]
    assert top["item_id"] == "dream"
    assert "做梦" in top["excerpts"][0]["text"]  # 命中 chunk 原文优先当证据
    assert payload["model_called"] is False


def test_query_vector_lru_avoids_second_http(mock_provider):
    _write_catalog(ITEMS)
    semantic.run_embed()
    embed_calls = len(mock_provider)
    assert semantic.query_hits("做梦的方案") is not None
    assert semantic.query_hits("做梦的方案") is not None
    assert len(mock_provider) == embed_calls + 1  # 第二问吃缓存，不再发 HTTP


def test_query_http_failure_falls_back(monkeypatch, mock_provider):
    _write_catalog(ITEMS)
    semantic.run_embed()
    def boom(texts, cfg, timeout):
        raise RuntimeError("timeout")
    monkeypatch.setattr(semantic, "_post_embeddings", boom)
    assert semantic.query_hits("新问题没缓存") is None
    assert rank_query(ITEMS, "做梦") == rank(ITEMS, ask.query_terms("做梦"))


def test_numpy_missing_falls_back(monkeypatch, mock_provider):
    _write_catalog(ITEMS)
    semantic.run_embed()
    monkeypatch.setitem(__import__("sys").modules, "numpy", None)
    assert semantic.query_hits("做梦") is None


def test_embed_cli_wiring(mock_provider, capsys):
    _write_catalog(ITEMS)
    from link_brain.cli import main
    assert main(["embed"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok" and out["chunks"] > 0
