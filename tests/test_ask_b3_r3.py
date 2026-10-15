"""1015 第三批 R3：查询侧碎词 / 停用词抑制 + 地名层级（合成数据，不联网）。"""
from __future__ import annotations

import pytest

from link_brain import answer_cache, ask, places, retrieval


def _item(i, title, body="", tags=(), **fields):
    return {"id": i, "title": title, "tags": list(tags), "summary": "", "note": f"Web/{i}.md", "url": "",
            "search_fields": {"body": body, **fields}}


@pytest.fixture
def no_semantic(monkeypatch):
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: None)


def _settings():
    from link_brain import ai_config
    return ai_config._deep_merge(ai_config.DEFAULTS, {})


# ── 碎词抑制 ──

@pytest.mark.parametrize("question,must,never", [
    ("澳洲超市辣椒酱评论区有人说哪里还有便宜的", {"澳洲", "超市", "辣椒酱", "便宜"},
     {"有人", "说", "哪里", "洲超", "市辣", "酱评", "说哪", "澳洲超市辣椒酱评论区有人说哪里"}),
    ("澳洲做越南菜要买啥 在哪买", {"澳洲", "越南"}, {"菜要", "买", "啥", "要买", "买啥", "洲做"}),
    ("江西那个烫粉要放啥", {"江西", "烫", "粉"}, {"粉要", "放", "啥", "放啥", "要放"}),
    ("那澳洲的呢", {"澳洲"}, {"那澳洲的呢", "那澳"}),
    ("2024年存的租房攻略", {"2024", "租房", "攻略"}, {"年存", "存"}),
    ("会生长的AI伴侣记忆系统讲了什么", {"生长", "ai", "伴侣", "记忆系统", "记忆"}, {"会", "讲", "侣记", "统讲"}),
])
def test_query_terms_drop_colloquial_fragments(question, must, never):
    terms = set(ask.query_terms(question))
    assert must <= terms, terms
    assert not (never & terms), never & terms


def test_query_terms_keep_rare_single_chars_and_proper_nouns():
    assert ask.query_terms("鱼") == ["鱼"]
    assert "汤" in ask.query_terms("担担面有没有汤")
    assert "醋" in ask.query_terms("收藏里有寿司醋的配方吗")
    # jieba 不认识的专名整个留着，另带 2-gram
    t = ask.query_terms("科科科酱发过哪些")
    assert "科科科酱" in t and "科科" in t
    assert "鱼路" in ask.query_terms("鱼路是哪篇") and "西尼" in ask.query_terms("西尼那家自助")


def test_stopword_table_loaded_and_documented():
    assert {"啥", "放", "说", "有人", "要买"} <= ask.STOPWORDS
    head = (ask.Path(ask.__file__).parent / "assets" / "stopwords-zh.txt").read_text(encoding="utf-8")[:400]
    assert "goto456" in head and "没有拷贝" in head


def test_common_terms_are_damped(no_semantic):
    """全库 ≥60% 都有的词和不泛的词一起问时降权：只沾泛词的篇不能靠它压过中了稀有词的篇。"""
    items = [_item(f"c{i}", f"日常 {i}", "区 区 区 区") for i in range(8)]
    items += [_item("rare", "随手记", "鸭汤"), _item("both", "区里", "区")]
    order = [it["id"] for _, it in retrieval.rank(items, ["区", "鸭汤"])]
    assert order[0] == "rare"


def test_answer_cache_compares_with_legacy_terms():
    """检索切词改了，问答缓存仍按旧切词比两问（阈值按它标定，answers.json 里存的也是旧词）。"""
    entries = [{"ts": "2026-09-01T00:00:00+08:00", "question": "AI 会做梦吗", "terms": ["ai", "做梦"], "item_ids": []}]
    assert answer_cache.lookup("AI 做梦的记忆", ask.query_terms("AI 做梦的记忆"), entries) is None
    entries = [{"ts": "2026-09-01T00:00:00+08:00", "question": "睡不好怎么办", "terms": [], "item_ids": []}]
    assert answer_cache.lookup("晚上睡不好怎么改善", [], entries)


# ── 地名层级 ──

ITEMS = [
    _item("snack", "澳洲零食饼干品鉴", "零食", tags=["好吃的零食", "澳洲"]),
    _item("tasty", "澳洲这个松饼真的太好吃了", "好吃"),
    _item("syd", "悉尼女生这家自助", "chatswood 好吃", tags=["悉尼美食"]),
    _item("cs", "潮汕太好吃了", "好吃 好吃"),
    _item("law", "澳洲法律术语", "案例"),
    _item("misc", "整理桌面", "收纳"),
] + [_item(f"f{i}", f"日常记录 {i}", "今天也在学习") for i in range(10)]


def test_place_table_expands_country_to_cities():
    row = places.place_of("澳大利亚")
    assert row and "悉尼" in row["children"] and "chatswood" in row["children"]
    assert "墨尔本" in places.expand_variants("澳洲") and "澳洲" in places.expand_variants("🇦🇺")
    assert places.place_of("悉尼") is None  # 下级地名不往下展开
    assert [r["names"][0] for r in places.query_places("🇦🇺有什么好吃的")] == ["澳洲"]
    assert places.expand_variants("火锅") == retrieval.variants("火锅")


def test_place_route_and_boost(monkeypatch, no_semantic):
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": [], "status": "no-model"})
    ids = [it["id"] for it in ask.recall("澳洲好吃的", ITEMS, _settings())["matches"]]
    assert ids[0] == "tasty"                     # 标题写着澳洲 + 好吃
    assert "syd" in ids                          # 只写了悉尼 / chatswood 也召回
    assert ids.index("syd") < ids.index("cs")    # 没沾地名的「潮汕好吃」往后，但不删
    assert "cs" in ids


def test_place_boost_is_noop_without_place(no_semantic):
    pool = list(ITEMS)
    assert places.boost(pool, ["好吃"], ITEMS, question="好吃的") is pool


def test_place_coverage_counts_children():
    syd = ITEMS[2]
    assert ask._core_cover(syd, ["澳洲", "好吃"]) == 2
    assert ask._has_all(syd, ["澳洲"])


def test_place_table_missing_is_fail_open(monkeypatch):
    monkeypatch.setattr(places, "_TABLE", [])
    assert places.query_places("澳洲") == [] and places.boost(list(ITEMS), ["澳洲"], ITEMS, question="澳洲") == list(ITEMS)
