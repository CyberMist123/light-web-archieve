"""第 10 批「问收藏宁广勿漏」：多路召回 + 小模型扩词 + 批注进检索 + 按留下的来源重答。全部假模型，不联网。"""
from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from link_brain import ask, note, retrieval, semantic, storage, text_stream


def _item(i, title, body="", tags=(), notes_path=None, **fields):
    return {"id": i, "title": title, "tags": list(tags), "summary": "", "note": f"Web/{i}.md", "url": "",
            "search_fields": {"body": body, **fields}, **({"notes_path": notes_path} if notes_path else {})}


ITEMS = [
    _item("au-1", "日本便利店的松饼", "日本留学早餐"),
    _item("au-2", "日本草莓甜不甜", "超市草莓"),
    _item("syd-1", "东京这家自助烤肉", "周三特价", tags=["东京美食"]),
    _item("syd-2", "刚到东京求餐厅", "第一次来东京"),
    _item("mel-1", "大阪咖啡地图", "小巷咖啡"),
    _item("food-1", "潮汕牛肉丸", "手打牛肉丸"),
    _item("food-2", "成都苍蝇馆子", "麻辣"),
    _item("misc-1", "整理桌面的小技巧", "收纳"),
]


@pytest.fixture
def no_semantic(monkeypatch):
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: None)


def _settings(**retrieval_cfg):
    from link_brain import ai_config
    return ai_config._deep_merge(ai_config.DEFAULTS, {"retrieval": retrieval_cfg})


# ── 多路召回：扩出的词各开一路，原词路权重更高 ──

def test_expanded_terms_pull_in_items_the_query_never_mentions(monkeypatch, no_semantic):
    """问「日本」：只写了东京 / 大阪、全文没有「日本」的篇，靠小模型扩出来的城市名进候选池；原词命中的排前面。"""
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": ["东京", "大阪", "札幌", "Tokyo"], "status": "ok"})
    found = ask.recall("日本", ITEMS, _settings())
    ids = [it["id"] for it in found["matches"]]
    assert set(ids[:1]) == {"au-1"}  # 原词命中在前
    assert {"syd-1", "syd-2", "mel-1"} <= set(ids)
    assert ids.index("au-1") < ids.index("syd-1")
    assert "札幌" not in found["expansion"]["terms"], "库里一篇都没有的词不单开一路"
    assert "东京" in found["expansion"]["terms"]


def test_without_expansion_pool_is_lexical_only(monkeypatch, no_semantic):
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": [], "status": "no-model"})
    ids = [it["id"] for it in ask.recall("日本", ITEMS, _settings())["matches"]]
    assert "syd-1" not in ids


def test_generic_expansion_terms_are_dropped(monkeypatch, no_semantic):
    """全库四成以上都有的词（太泛）不单开一路；推荐 / 教程这类泛词也不要。"""
    items = ITEMS + [_item(f"g{i}", f"女生日常 {i}", "女生") for i in range(10)]
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": ["女生", "推荐", "东京"], "status": "ok"})
    terms = ask.recall("日本", items, _settings())["expansion"]["terms"]
    assert terms == ["东京"]


# ── 小模型扩词：缓存、超时、失败、关掉 ──

@pytest.fixture
def fake_model(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_EXPAND_CACHE", str(tmp_path / "expand-cache.json"))
    ask._EXPAND_MEM.clear()
    monkeypatch.setattr(ask, "expand_model", lambda: ("textAI", {"mode": "http", "model": "fake-flash", "cap": "textAI", "timeoutSec": 20}))
    calls = []

    def call(instruction, text, cfg, on_delta=None, *, cap="textAI"):
        calls.append({"text": text, "cfg": cfg, "cap": cap})
        return calls.reply(text) if hasattr(calls, "reply") else {"status": "ok", "text": '{"terms": ["东京", "大阪", "Tokyo"]}'}

    class Calls(list):
        pass
    calls = Calls()
    monkeypatch.setattr(text_stream, "call", call)
    return calls


def test_llm_expansion_is_cached_per_question(fake_model, tmp_path):
    first = ask.llm_expansions("日本好吃的")
    assert first["status"] == "ok" and first["terms"] == ["东京", "大阪", "Tokyo"]
    assert fake_model[0]["cfg"]["noThinking"] is True and fake_model[0]["cfg"]["maxTokens"] == 300
    ask._EXPAND_MEM.clear()  # 进程重启：从缓存文件读
    second = ask.llm_expansions("日本好吃的")
    assert second["status"] == "cached" and second["terms"] == first["terms"]
    assert len(fake_model) == 1, "同一问题只调一次"
    assert json.loads((tmp_path / "expand-cache.json").read_text(encoding="utf-8"))


def test_llm_expansion_fails_open(fake_model):
    fake_model.reply = lambda text: {"status": "failed", "error": "HTTP 500"}
    assert ask.llm_expansions("三体") == {"terms": [], "status": "failed", "model": "fake-flash", "error": "HTTP 500"}
    fake_model.reply = lambda text: {"status": "ok", "text": "好的，这些词：罗辑、章北海"}  # 没给 JSON
    assert ask.llm_expansions("三体 2")["terms"] == []


def test_llm_expansion_does_not_hold_up_the_answer(fake_model):
    gate = threading.Event()

    def slow(text):
        gate.wait(5)
        return {"status": "ok", "text": '{"terms": ["罗辑"]}'}
    fake_model.reply = slow
    start = time.perf_counter()
    r = ask.llm_expansions("慢问题", wait=0.2)
    assert r["status"] == "timeout" and time.perf_counter() - start < 2
    gate.set()
    for _ in range(50):  # 后台那次答完照样进缓存，下次同一问题直接用
        if ask._EXPAND_MEM:
            break
        time.sleep(0.05)
    assert ask.llm_expansions("慢问题")["status"] == "cached"


def test_llm_expansion_switch_and_no_model(monkeypatch, fake_model):
    from link_brain import ai_config
    monkeypatch.setattr(ai_config, "load", lambda: _settings(queryExpand=False))
    assert ask.llm_expansions("日本")["status"] == "off"
    monkeypatch.setattr(ai_config, "load", lambda: _settings())
    monkeypatch.setattr(ask, "expand_model", lambda: ("", None))
    assert ask.llm_expansions("日本")["status"] == "no-model"
    assert not fake_model


def test_expand_model_prefers_http_text_ai_and_skips_cli(monkeypatch):
    from link_brain import ai_config
    base = {"textAI": {"mode": "cli", "command": "claude -p"},
            "summaryAI": {"mode": "http", "endpoint": "https://x.invalid/v1", "model": "small", "apiKey": "k"}}
    monkeypatch.setattr(ai_config, "load", lambda: ai_config._deep_merge(ai_config.DEFAULTS, base))
    cap, cfg = ask.expand_model()
    assert cap == "summaryAI" and cfg["model"] == "small"
    base["textAI"] = {"mode": "http", "endpoint": "https://y.invalid/v1", "model": "flash", "apiKey": "k"}
    cap, cfg = ask.expand_model()
    assert cap == "textAI" and cfg["model"] == "flash"


def test_no_thinking_flag_reaches_qwen_body(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(text_stream, "_CLIENT", httpx.Client(transport=httpx.MockTransport(handler)))
    text_stream.http_call("规则", "问题", {"endpoint": "https://example.invalid", "model": "qwen3.7-flash", "noThinking": True})
    assert seen["enable_thinking"] is False
    seen.clear()
    text_stream.http_call("规则", "问题", {"endpoint": "https://example.invalid", "model": "qwen3.7-flash"})
    assert "enable_thinking" not in seen


# ── 作答：候选池全部回给页面，送模型的篇数按字数预算；按留下的来源重答 ──

def _answer_env(monkeypatch, items):
    calls = []

    def model(prompt, text, settings):
        calls.append(text)
        return {"status": "ok", "text": "据材料作答。[来源1]"}
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in items])
    monkeypatch.setattr(ask, "call_text", model)
    monkeypatch.setattr(ask.ai_config, "load", lambda: _settings(totalCharLimit=1400))
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: None)
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": ["东京", "大阪"], "status": "ok"})
    return calls


def test_answer_returns_whole_pool_in_two_tiers(monkeypatch):
    calls = _answer_env(monkeypatch, ITEMS)
    r = ask.answer("日本")
    assert r["status"] == "ok"
    primary, related = [s["id"] for s in r["sources"]], [s["id"] for s in r["related"]]
    assert len(primary) == ask.primary_count(1400, 8, len(primary) + len(related))
    assert {"au-1", "au-2", "syd-1", "syd-2", "mel-1"} <= set(primary + related)
    assert not set(primary) & set(related)
    assert all(s["citation"] == n for n, s in enumerate(r["sources"], 1))
    assert r["expansion"]["terms"] == ["东京", "大阪"]
    assert len(calls) == 1


def test_primary_count_follows_budget():
    assert ask.primary_count(8000, 8, 80) == 11
    assert ask.primary_count(20000, 8, 80) == 20
    assert ask.primary_count(3000, 8, 80) == 8
    assert ask.primary_count(8000, 8, 5) == 5


def test_reanswer_uses_only_the_kept_sources(monkeypatch):
    calls = _answer_env(monkeypatch, ITEMS)
    monkeypatch.setattr(ask, "_select_sources", lambda *a, **k: pytest.fail("按留下的来源重答不挑材料"))
    monkeypatch.setattr(ask, "recall", lambda *a, **k: pytest.fail("按留下的来源重答不重新检索"))
    r = ask.answer("推荐日本相关的项目", source_ids=["mel-1", "syd-2", "gone"])
    assert r["status"] == "ok" and r.get("pinned") is True
    assert [s["id"] for s in r["sources"]] == ["mel-1", "syd-2"]
    assert "大阪咖啡地图" in calls[0] and "潮汕" not in calls[0]
    assert "用户自己留下的来源" in calls[0]


def test_source_ids_must_be_a_list_of_ids(monkeypatch):
    _answer_env(monkeypatch, ITEMS)
    assert ask.answer("日本", source_ids="mel-1")["status"] == "error"


# ── 批注进检索 ──

def test_annotation_text_skips_deleted_and_empty():
    doc = {"annotations": [{"id": "a1", "text": "复刻过"}, {"id": "a2", "text": "删掉的"}, {"id": "a3", "text": "  "},
                           {"ts": "t", "text": "老批注没 id"}], "deleted": ["a2"], "draft": "草稿不算"}
    assert note.annotation_text(doc) == "复刻过\n老批注没 id"
    assert note.annotation_text(None) == ""


def test_live_annotations_are_searchable_before_catalog_rebuild(monkeypatch):
    """页面直接写 notes.json：问收藏不等目录重建，按修改时间现读。"""
    rel = "_archive/xiaohongshu/x1/notes.json"
    items = [_item("x1", "周末的一锅炖菜", "土豆牛肉", notes_path=rel), _item("x2", "番茄炒蛋", "鸡蛋", notes_path="_archive/xiaohongshu/x2/notes.json")]
    storage.write_json(storage.archive_root() / "catalog-data.json", {"items": items})
    ask._ITEM_CACHE.clear()
    assert retrieval.rank(ask.load_items(), ["复刻"]) == []
    storage.write_json(storage.vault_root() / rel, {"starred": False, "annotations": [{"id": "a1", "text": "复刻过两次，少放盐"}]})
    loaded = ask.load_items()
    assert [it["id"] for _, it in retrieval.rank(loaded, ["复刻"])] == ["x1"]
    assert loaded[0]["search_fields"]["notes"] == "复刻过两次，少放盐"
    assert ask.load_items() is loaded, "批注没变就复用同一份（检索缓存按对象认）"


def test_annotation_chunk_is_incremental():
    """批注单独成块：加了批注，原有各块的 hash 不变（增量 embed 只补批注那一块）；两个字的批注也成块。"""
    it = _item("x1", "炖菜", "土豆胡萝卜牛肉一起炖一个小时")
    before = {(f, s): semantic.content_hash("m", t) for f, s, t in semantic.chunk_item(it)}
    it["search_fields"]["notes"] = "好吃"
    after = {(f, s): semantic.content_hash("m", t) for f, s, t in semantic.chunk_item(it)}
    assert {k: v for k, v in after.items() if k[0] != "notes"} == before
    assert ("notes", 0) in after


def test_catalog_collect_puts_annotations_in_search_fields(tmp_path):
    from link_brain import catalog
    vault = storage.vault_root()
    obj = vault / "_archive" / "xiaohongshu" / "n1"
    storage.write_json(obj / "meta.json", {"item_id": "xhs-n1", "source": "xiaohongshu", "source_id": "n1", "title": "炖菜",
                                           "current_version": 1, "first_archived_at": "2026-10-01T10:00:00+10:00"})
    storage.write_json(obj / "raw" / "v0001" / "source.json", {"note": {"body": "土豆牛肉", "tags": []}})
    storage.write_json(obj / "notes.json", {"starred": True, "annotations": [{"id": "a1", "text": "复刻过"}]})
    items = catalog.collect(vault)
    got = next(it for it in items if it["id"] == "xhs-n1")
    assert got["search_fields"]["notes"] == "复刻过" and got["starred"] is True


# ── 语义按篇聚合 ──

def test_semantic_hits_aggregate_per_item(monkeypatch):
    """一篇长文占好几块也只算一篇；按篇取最高分，带相对下限，最多 TOP_ITEMS 篇。"""
    import numpy as np
    rows = [(f"i{n // 3}", "body", f"t{n}") for n in range(30)]  # 10 篇、每篇 3 块
    sims = np.linspace(.9, .1, 30)  # 第 n 块和问题的余弦；同一篇的三块挨着
    matrix = np.zeros((30, 4), dtype=np.float32)
    matrix[:, 3], matrix[:, 0] = sims, np.sqrt(1 - sims ** 2)
    monkeypatch.setattr(semantic, "db_path", lambda: type("P", (), {"is_file": lambda self: True})())
    monkeypatch.setattr(semantic, "_load_matrix", lambda model: (matrix, rows))
    monkeypatch.setattr(semantic, "query_vector", lambda q: np.array([0, 0, 0, 1], dtype=np.float32))
    hits = semantic.query_hits("问题", top_items=3)
    assert list(hits) == ["i0", "i1", "i2"]
    assert all(len(h["chunks"]) == 2 for h in hits.values())
    wide = semantic.query_hits("问题", top_items=40)
    assert list(wide)[:4] == ["i0", "i1", "i2", "i3"] and "i9" not in wide, "低于「中位数 + 0.2 ×（第一名 − 中位数）」的不要"
