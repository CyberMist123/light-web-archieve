"""1001 审计 ask-7 / ask-9：问收藏送给模型的证据 + 资料筛选 fail-open。

全部走生产入口 ask.answer；语义层用 test_semantic 同款确定性假 provider，不打真网。
"""
from __future__ import annotations

import pytest

from link_brain import ask, semantic, storage
from link_brain.retrieval import evidence

HEAD = "开头无关的铺垫话。" * 300
TAIL = "结尾无关的客套话。" * 300
MIDDLE = "夜里做梦，把白天的事重放一遍再存档。" * 6

LONG = {"id": "dream", "title": "离线整理", "tags": [], "summary": "", "note": "dream.md", "url": "",
        "search_fields": {"body": HEAD + "\n\n" + MIDDLE + "\n\n" + TAIL}}
OTHERS = [{"id": "fish", "title": "鱼片菜谱", "tags": [], "summary": "", "note": "fish.md", "url": "",
           "search_fields": {"body": "蒜香鱼片，先腌后煎。" * 20}}]


def _vec(text):
    return [float(text.count("梦") + (5 if "sleep" in text else 0)), float(text.count("鱼")), 1.0]


@pytest.fixture
def semantic_vault(monkeypatch, tmp_path):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("LINK_BRAIN_MODELS_DIR", str(tmp_path / "no-keys"))
    semantic._MATRIX_CACHE.update(stamp=None, data=None)
    semantic._QUERY_VEC_CACHE.clear()
    monkeypatch.setattr(semantic, "_post_embeddings", lambda texts, cfg, timeout: [_vec(t) for t in texts])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    storage.write_json(storage.archive_root() / "catalog-data.json", {"items": [LONG, *OTHERS]})
    assert semantic.run_embed()["status"] == "ok"
    yield


def test_semantic_only_hit_sends_the_matching_chunk_not_head_and_tail(semantic_vault, monkeypatch):
    seen = []
    monkeypatch.setattr(ask, "call_text", lambda p, text, s: seen.append(text) or {"status": "ok", "text": "答[来源1]"})
    r = ask.answer("sleep replay")  # 词法零命中，只靠语义召回
    assert r["status"] == "ok" and r["sources"][0]["id"] == "dream"
    prompt = seen[-1]
    # 真正相关的中间那段送进去了（以前是开头一半 + 结尾一半，这句根本不在里面），而且排在证据第一位
    assert "夜里做梦" in prompt
    assert "夜里做梦" in r["sources"][0]["excerpts"][0]["text"]


def test_without_semantic_layer_falls_back_to_head_and_tail():
    parts = evidence(LONG, ["sleep"], 1000, None)
    assert parts[0]["text"].startswith("开头无关") and parts[-1]["text"].endswith("客套话。")


def test_semantic_chunks_lead_and_lexical_windows_fill_the_budget():
    item = {"id": "x", "search_fields": {"body": "甲" * 600 + "关键词出现在这里" + "乙" * 600}}
    sem = {"x": {"score": 0.9, "chunks": [{"field": "meta", "text": "标题块"}, {"field": "body", "text": "语义片段原文"}]}}
    parts = evidence(item, ["关键词"], 800, sem)
    assert parts[0]["text"] == "语义片段原文"          # meta 块不当证据
    assert any("关键词出现在这里" in p["text"] for p in parts[1:])
    assert sum(len(p["text"]) for p in parts) <= 800


ITEMS = [{"id": str(i), "title": f"项目 {i}", "tags": [], "summary": "", "note": f"{i}.md", "url": "",
          "search_fields": {"body": f"相关项目 {i} 的说明。"}} for i in range(12)]


@pytest.mark.parametrize("selector_reply", ["好的，我挑了这些：第1和第3个", "", "[1, 2]"])
def test_selector_bad_format_fails_open_to_plain_retrieval(monkeypatch, selector_reply):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    calls = []

    def model(prompt, text, settings):
        calls.append(text)
        if len(calls) == 1:  # 第一次是资料筛选
            return {"status": "ok", "text": selector_reply}
        return {"status": "ok", "text": "整理如下[来源1]"}
    monkeypatch.setattr(ask, "call_text", model)
    r = ask.answer("推荐相关项目")
    assert r["status"] == "ok" and r["selection_failed"] is True
    # 第 10 批：篇数按字数预算（8000 字 → 11 篇），筛选失败照检索顺序；其余候选在 related
    assert len(r["sources"]) == ask.primary_count(8000, 8, 12) == 11 and len(calls) == 2
    assert len(r["related"]) == 1


def test_selector_http_error_also_fails_open(monkeypatch):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    replies = iter([{"status": "failed", "error": "timeout"}, {"status": "ok", "text": "答[来源1]"}])
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: next(replies))
    r = ask.answer("推荐相关项目")
    assert r["status"] == "ok" and r.get("selection_failed") is True


def test_selector_chatty_json_is_parsed_leniently(monkeypatch):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    replies = iter([{"status": "ok", "text": '好的：\n```json\n{"selected":[2]}\n```\n以上'},
                    {"status": "ok", "text": "答[来源1]"}])
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: next(replies))
    r = ask.answer("推荐相关项目")
    assert r["status"] == "ok" and "selection_failed" not in r
    assert r["candidates"] > 8 and len(r["sources"]) >= 1
