"""知识库问答 ask.py 的网络无关单测。

覆盖：检索词切分、OR 召回排序、意图识别、github/links 纯本地出结果、
qa 走模型（把 call_text 换成假的，验证 token 控制与材料计数），全程不联网、不花钱。
"""

from __future__ import annotations

import pytest

from link_brain import ask


FAKE_ITEMS = [
    {
        "id": "a", "title": "AI 会做梦吗", "note": "Web/Xiaohongshu/做梦__a.md",
        "summary": "关于大模型做梦与梦境生成的讨论",
        "search_text": "关于大模型做梦与梦境生成的讨论。dream 相关实验。",
        "tags": ["AI", "记忆"], "author": "小明", "url": "https://www.xiaohongshu.com/explore/a",
        "github_urls": ["https://github.com/foo/dreamer"], "suggested_links": [],
        "ts": "2026-09-10T00:00:00+08:00",
    },
    {
        "id": "b", "title": "本周菜谱", "note": "Web/Xiaohongshu/菜谱__b.md",
        "summary": "十分钟快手菜", "search_text": "十分钟快手菜，减脂餐。",
        "tags": ["吃的"], "author": "小红", "url": "https://www.xiaohongshu.com/explore/b",
        "github_urls": [], "suggested_links": [{"url": "", "hint": "SomeRepo 项目", "why": "作者提到"}],
        "ts": "2026-09-12T00:00:00+08:00",
    },
    {
        "id": "c", "title": "梦的记忆整理", "note": "Web/Xiaohongshu/梦记忆__c.md",
        "summary": "把梦写进记忆库", "search_text": "把梦写进记忆库，dream journal。",
        "tags": ["记忆", "AI"], "author": "小刚", "url": "https://www.xiaohongshu.com/explore/c",
        "github_urls": ["https://github.com/foo/dreamer", "https://github.com/bar/memo"],
        "suggested_links": [], "ts": "2026-09-11T00:00:00+08:00",
    },
]


@pytest.fixture(autouse=True)
def fake_index(monkeypatch):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in FAKE_ITEMS])
    # 默认不真发模型：qa 用例各自覆盖
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))


def test_query_terms_splits_and_dedups():
    terms = ask.query_terms("所有 AI 做梦 相关")
    assert "ai" in terms
    assert "做梦" in terms
    assert "所有" not in terms  # 停用词去掉


def test_retrieve_or_recall_and_rank():
    hits = ask.retrieve([dict(x) for x in FAKE_ITEMS], ["做梦", "梦"])
    ids = [it["id"] for it in hits]
    assert "a" in ids and "c" in ids
    assert "b" not in ids  # 菜谱不该命中


def test_detect_intent():
    assert ask.detect_intent("提取所有 github 地址") == "github"
    assert ask.detect_intent("把相关链接都给我") == "links"
    assert ask.detect_intent("AI 做梦是怎么回事") == "qa"


def test_github_intent_local_only(monkeypatch):
    # github 意图纯本地，绝不调模型
    monkeypatch.setattr(ask, "call_text", lambda *a, **k: pytest.fail("github 不该调模型"))
    r = ask.answer("提取所有 github 地址")
    assert r["intent"] == "github"
    assert r["model_called"] is False
    assert r["matches"] == 2  # dreamer + memo 去重
    assert "github.com/foo/dreamer" in r["markdown"]
    assert "github.com/bar/memo" in r["markdown"]


def test_links_intent_lists_all_matches(monkeypatch):
    monkeypatch.setattr(ask, "call_text", lambda *a, **k: pytest.fail("links 不该调模型"))
    r = ask.answer("所有做梦相关的链接给我")
    assert r["intent"] == "links"
    assert "[[Web/Xiaohongshu/做梦__a|AI 会做梦吗]]" in r["markdown"]
    assert "[原文](https://www.xiaohongshu.com/explore/a)" in r["markdown"]


def test_qa_sends_limited_fragments(monkeypatch):
    captured = {}

    def fake_call(instruction, input_text, settings):
        captured["input"] = input_text
        captured["instruction"] = instruction
        return {"status": "ok", "text": "这是回答。", "usage": {"total_tokens": 42}, "error": None}

    monkeypatch.setattr(ask, "call_text", fake_call)
    # 关掉扩词，避免额外一次调用干扰断言
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(
        ask.ai_config.DEFAULTS, {"retrieval": {"expandTerms": False, "totalCharLimit": 8000, "fragChars": 800, "topK": 8}}))
    r = ask.answer("AI 做梦是怎么回事")
    assert r["intent"] == "qa"
    assert r["model_called"] is True
    assert r["matches"] >= 2
    assert r["materials"] >= 1
    assert "这是回答。" in r["markdown"]
    # 送模型的输入受总字符上限约束
    assert len(captured["input"]) <= 8000 + 500  # 片段拼装 + 问题包头的余量


def test_qa_model_failure_still_lists_notes(monkeypatch):
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(
        ask.ai_config.DEFAULTS, {"retrieval": {"expandTerms": False}}))
    monkeypatch.setattr(ask, "call_text", lambda *a, **k: {"status": "failed", "text": None, "error": "boom"})
    r = ask.answer("AI 做梦")
    assert r["status"] == "ok"  # 不阻断
    assert "boom" in r["markdown"]
    assert "[[Web/Xiaohongshu/" in r["markdown"]  # 至少把命中的笔记列出来


def test_empty_question():
    r = ask.answer("   ")
    assert r["status"] == "error"


# ── URL 清洗（xhs.clean_url / clean_share_text）──────────────────────────────

def test_clean_url_keeps_only_token_and_source():
    from link_brain.adapters import xiaohongshu as xhs
    r = xhs.clean_url(
        "https://www.rednote.com/discovery/item/6aa?xsec_token=TK&source=web&xhsshare=pc&shareRedId=z&xsec_source=pc_feed"
    )
    assert r["clean"] == "https://www.rednote.com/discovery/item/6aa?xsec_token=TK&xsec_source=pc_feed"
    assert r["has_token"] is True
    assert "source=web" not in r["clean"] and "xhsshare" not in r["clean"]


def test_clean_url_no_token_not_fabricated():
    from link_brain.adapters import xiaohongshu as xhs
    r = xhs.clean_url("https://www.xiaohongshu.com/explore/6bb?source=web")
    assert r["has_token"] is False
    assert r["clean"] == "https://www.xiaohongshu.com/explore/6bb"  # 保留 path，不拼 token


def test_clean_url_follows_shortlink(monkeypatch):
    from link_brain.adapters import xiaohongshu as xhs
    monkeypatch.setattr(
        xhs, "resolve_shortlink",
        lambda url, **kw: "https://www.xiaohongshu.com/explore/6cc?xsec_token=TK&xsec_source=pc_feed&app=1",
    )
    r = xhs.clean_url("https://xhslink.cn/o/abc")
    assert r["resolved_from_shortlink"] is True
    assert r["clean"] == "https://www.xiaohongshu.com/explore/6cc?xsec_token=TK&xsec_source=pc_feed"


def test_clean_share_text_extracts_dedups_and_filters(monkeypatch):
    from link_brain.adapters import xiaohongshu as xhs
    monkeypatch.setattr(xhs, "resolve_shortlink", lambda url, **kw: "https://www.xiaohongshu.com/explore/6dd?xsec_token=TK")
    text = ("看这个 https://www.rednote.com/discovery/item/6aa?xsec_token=T1&source=web 还有短链 "
            "https://xhslink.cn/o/abc 以及非小红书 https://example.com/x 重复 "
            "https://www.rednote.com/discovery/item/6aa?xsec_token=T1&source=web")
    out = xhs.clean_share_text(text)
    cleans = [u["clean"] for u in out]
    assert "https://example.com/x" not in " ".join(cleans)  # 非白名单不收
    assert any("6aa" in c for c in cleans) and any("6dd" in c for c in cleans)
    assert len(cleans) == len(set(cleans)) == 2  # 去重后两条


def test_catalog_cats_override(monkeypatch):
    from link_brain import ai_config, catalog
    monkeypatch.setattr(ai_config, "load", lambda: {"catalogCats": [{"name": "自定义", "keywords": ["喵", "汪"]}]})
    cats = catalog.effective_big_cats()
    assert cats == [("自定义", ("喵", "汪"))]
    assert catalog._cats(["今天很喵"], cats) == ["自定义"]
    assert catalog._cats(["无关标签"], cats) == [catalog.OTHER_CAT]
