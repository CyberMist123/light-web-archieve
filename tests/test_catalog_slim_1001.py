"""1001 审计 ui-4：catalog-data.json 的全文只存一份（search_fields），搜索和摘录不退化。"""
from __future__ import annotations

import json

from link_brain import ask, catalog, retrieval, storage
from tests.test_catalog import _make_object

PHRASE = "附件里才有的独特句子：番茄炒蛋先炒蛋"


def _build(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _make_object(tmp_path, "a1", title="家常菜合集", tags=["吃的"], summary="一段概要", stem="家常菜合集")
    att = tmp_path / "_archive/xiaohongshu/a1/derived/attachments"
    att.mkdir(parents=True)
    (att / "d1.md").write_text("# 菜谱\n\n" + PHRASE + "。" + "其余内容。" * 50, encoding="utf-8")
    _, _, data_path = catalog.build()
    return data_path


def test_full_text_is_stored_once(tmp_path, monkeypatch):
    data_path = _build(tmp_path, monkeypatch)
    raw = data_path.read_text(encoding="utf-8")
    item = json.loads(raw)["items"][0]
    assert "search_text" not in item
    # 1015：全文拆进 catalog-search-index.json，目录数据里一处都不留
    assert "search_fields" not in item and "pinyin" not in item and PHRASE not in raw
    index_raw = (data_path.parent / catalog.SEARCH_NAME).read_text(encoding="utf-8")
    assert PHRASE in json.loads(index_raw)["items"]["xhs-a1"]["search_fields"]["attachments"]
    assert index_raw.count(PHRASE) == 1


def test_search_and_ask_still_find_attachment_text(tmp_path, monkeypatch):
    _build(tmp_path, monkeypatch)
    ask._ITEM_CACHE.clear()
    found = retrieval.search("番茄炒蛋")
    assert found["found"] == 1 and PHRASE in found["results"][0]["excerpts"][0]["text"]
    hits = ask.retrieve(ask.load_items(), ask.query_terms("番茄炒蛋"))
    assert hits and hits[0]["id"] == "xhs-a1"


def test_excerpt_fallback_without_search_text():
    item = {"id": "x", "summary": "概要", "search_fields": {"body": "", "attachments": "甲" * 900}}
    parts = retrieval.excerpts(item, ["不存在的词"], 400)
    assert parts and all(p["field"] == "attachments" for p in parts)


def test_index_readers_get_search_fields_back(tmp_path, monkeypatch):
    """1015：拆出去之后，indextree.catalog_items（索引 AI 的签名 / wiki 取文）照样拿得到全文；旧格式不受影响。"""
    from link_brain import indextree
    _build(tmp_path, monkeypatch)
    items, _ = indextree.catalog_items(tmp_path)
    assert PHRASE in items[0]["search_fields"]["attachments"] and "pinyin" in items[0]
    legacy = [{"id": "x", "search_fields": {"body": "旧"}}]
    assert catalog.merge_search_index(legacy, tmp_path)[0]["search_fields"] == {"body": "旧"}
