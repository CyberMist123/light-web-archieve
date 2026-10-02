"""搜索回归（第 1 批 1002）：和 JS tests/test_catalog_search.cjs 读同一份查询集 + 合成数据。

查询集 tests/fixtures/search_queries.json 每条：
- must_top：精确命中区按顺序以这几篇开头；must_include：在精确命中区；
- fuzzy_only：出现、但只在「可能相关」区（拼音整音节 / 拼写相近）；must_exclude：完全不出现；
- exact_max：精确命中区最多几篇。
Python 走真实入口 retrieval.search（CLI `link-brain search` 和 MCP lb_search 用的就是它）。
另验：精细识图 refined.text 进目录搜索字段 → 问答检索字段 → 向量切块；拼音字段是整音节格式。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import catalog, retrieval, semantic, storage

FIXTURES = Path(__file__).parent / "fixtures"
DATA = json.loads((FIXTURES / "catalog-data.sample.json").read_text(encoding="utf-8"))
QUERIES = json.loads((FIXTURES / "search_queries.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_vault():
    path = storage.vault_root() / "_archive" / "catalog-data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DATA, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("q", QUERIES, ids=[q["query"] for q in QUERIES])
def test_search_regression(sample_vault, q):
    rows = retrieval.search(q["query"], limit=100)["results"]
    exact = [r["item_id"] for r in rows if r["match"] == "exact"]
    possible = [r["item_id"] for r in rows if r["match"] == "possible"]
    # 「可能相关」整组排在原词命中之后，不混排
    assert [r["match"] for r in rows] == sorted((r["match"] for r in rows), key=lambda m: m != "exact")
    assert exact[:len(q["must_top"])] == q["must_top"], (exact, possible)
    for item_id in q.get("must_include") or []:
        assert item_id in exact, (item_id, exact)
    for item_id in q.get("fuzzy_only") or []:
        assert item_id in possible and item_id not in exact, (item_id, exact, possible)
    for item_id in q.get("must_exclude") or []:
        assert item_id not in exact + possible, (item_id, exact, possible)
    if q.get("exact_max") is not None:
        assert len(exact) <= q["exact_max"], exact


def test_fixture_pinyin_matches_catalog_format():
    """合成数据的 pinyin 字段必须就是 catalog.py 会写出来的样子，否则 JS / Python 两边测的不是同一种数据。"""
    for it in DATA["items"]:
        assert it["pinyin"] == retrieval.pinyin_text(it["title"], it["summary"], *it["tags"]), it["id"]


def test_pinyin_whole_syllables():
    sy = retrieval.syllables("悉尼Bondi徒步，新年 咖啡")
    assert sy == ["xi", "ni", "bondi", "tu", "bu", "/", "xin", "nian", "/", "ka", "fei"]
    hit = lambda term: retrieval.pinyin_match(sy, retrieval.pinyin_units(term))
    assert all(hit(t) for t in ["西尼", "xini", "新年", "xinnian", "图步"])
    # 半个音节、单个音节、跨断点、带数字都不算
    assert not any(hit(t) for t in ["xin", "xi", "西", "xinia", "步新", "悉尼2"])


def test_rank_falls_back_to_pinyin_only_when_no_literal_hit(sample_vault):
    """问答检索（BM25）：原词一篇都不中才退到拼音整音节，低权；「悉尼」有原词就不碰拼音。"""
    items = DATA["items"]
    homophone = [it["id"] for _, it in retrieval.rank(items, ["西尼"])]
    assert set(homophone) == {"syd-walk", "syd-food"}
    literal = [it["id"] for _, it in retrieval.rank(items, ["悉尼"])]
    assert "dream-a" not in literal and "noodle" not in literal and set(literal[:2]) == {"syd-walk", "syd-food"}


def test_star_boost_is_shared():
    """星标只 ×1.15：目录页 catalog-search.js 的 STAR_BOOST 和 retrieval 同一个数。"""
    js = (Path(retrieval.__file__).parent / "assets" / "catalog-search.js").read_text(encoding="utf-8")
    assert f"const STAR_BOOST = {retrieval.STAR_BOOST};" in js


def test_phrase_split_matches_split_keywords(sample_vault):
    assert retrieval.split_phrase("悉尼咖啡", DATA["items"]) == ["悉尼", "咖啡"]
    assert retrieval.split_phrase("西尼咖啡馆", DATA["items"]) == ["西尼咖啡馆"]
    assert retrieval.split_phrase("ai做梦", DATA["items"]) == ["ai", "做梦"]
    whole = [r["item_id"] for r in retrieval.search("悉尼咖啡")["results"]]
    split = [r["item_id"] for r in retrieval.search("悉尼 咖啡")["results"]]
    assert whole == split


def _object_with_vision(vault: Path, source_id: str, vision: dict) -> None:
    obj = vault / "_archive" / "xiaohongshu" / source_id
    (obj / "raw" / "v0001").mkdir(parents=True, exist_ok=True)
    (obj / "derived").mkdir(parents=True, exist_ok=True)
    (obj / "meta.json").write_text(json.dumps({
        "item_id": f"xhs-{source_id}", "title": "价目表合集", "first_archived_at": "2026-09-10T12:00:00+10:00",
        "current_version": 1, "kind": "image"}, ensure_ascii=False), encoding="utf-8")
    (obj / "raw" / "v0001" / "source.json").write_text(json.dumps({"note": {"body": "看图"}}, ensure_ascii=False), encoding="utf-8")
    (obj / "derived" / "vision.json").write_text(json.dumps(vision, ensure_ascii=False), encoding="utf-8")


def test_refined_text_reaches_catalog_retrieval_and_chunks(tmp_path, monkeypatch):
    """第二层精细识图成功：替代第一层 visual.text 进目录搜索字段；问答检索和向量切块都读这份。只读 vision.json，不调模型。"""
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _object_with_vision(tmp_path, "r1", {"images": [
        {"asset": "a1.webp", "status": "ok", "ocr": "营业 时间",
         "visual": {"status": "ok", "kind": "table", "text": "第一层粗表"},
         "refined": {"status": "ok", "kind": "table", "text": "| 周一 | 九点开门 |\n| 周二 | 休息 |"}},
        {"asset": "a2.webp", "status": "ok", "ocr": "第二张",
         "visual": {"status": "ok", "kind": "text", "text": "第二张的第一层"},
         "refine": {"status": "pending"}},
    ]})
    _, _, data_path = catalog.build()
    data = json.loads(data_path.read_text(encoding="utf-8"))
    item = data["items"][0]
    ocr = item["search_fields"]["ocr"]
    assert "九点开门" in ocr and "营业 时间" in ocr
    assert "第一层粗表" not in ocr          # 精细识图成功的图，不再留第一层
    assert "第二张的第一层" in ocr          # 还没精细识图的图照旧用第一层
    assert "九点开门" in retrieval.fields(item)["ocr"]
    assert retrieval.search("九点开门")["results"][0]["item_id"] == "xhs-r1"
    chunks = [text for field, _, text in semantic.chunk_item(item) if field == "ocr"]
    assert any("九点开门" in text for text in chunks)
    # 拼音字段整音节；拼音表带常用字（库里没出现过的同音字也能转）
    assert item["pinyin"].split()[:2] == ["jia", "mu"]
    assert data["pinyin_chars"]["西"] == "xi" and "西" not in item["title"]
