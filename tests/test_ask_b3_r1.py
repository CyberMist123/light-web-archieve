"""1015 第三批 R1：检索证据链（选篇 → 字段内扩窗 → 全局装箱；多轮独立问句；输出形态解耦；零命中复核）。"""
import sys
import types

from link_brain import ask, ask_intent, ask_turns, evidence_pack


def _it(i, body="", **fs):
    return {"id": i, "title": fs.pop("title", i), "tags": [], "summary": "", "search_fields": {"body": body, **fs}}


# ── 证据：字段内扩窗 + 全局装箱 ──

def test_short_main_doc_goes_whole_including_deep_comment():
    """F24：整篇不长的主来源整篇给——「猪皮」在评论第 259 字之后也进证据。"""
    doc = _it("a", "江西烫粉做法。", comments="甲" * 300 + "要放猪皮和红薯粉。")
    out = evidence_pack.pack([doc], ["烫粉"], cap=8000)
    text = " ".join(p["text"] for p in out["a"])
    assert "猪皮" in text and [p["field"] for p in out["a"]] == ["body", "comments"]


def test_hit_window_stays_in_its_field_and_respects_cap():
    long_comments = ("路人闲聊。" * 300) + "其实Aldi也有类似的辣椒酱，更便宜。" + ("别的话题。" * 300)
    doc = _it("a", "澳洲超市辣椒酱推荐。" * 3, comments=long_comments, ocr="图片文字" * 2000)
    other = _it("b", "无关", ocr="辣椒酱" + "噪音" * 3000)
    out = evidence_pack.pack([doc, other], ["辣椒酱", "aldi"], cap=3000, core=["辣椒酱"])
    parts = out["a"]
    assert any(p["field"] == "comments" and "Aldi" in p["text"] for p in parts)
    for p in parts:   # 窗口不跨字段：每段都是该字段原文的切片
        assert p["text"] in doc["search_fields"][p["field"]]
        assert "offset" in p
    total = sum(len(p["text"]) for ps in out.values() for p in ps)
    assert total <= 3000
    assert out["b"]   # 第 2 篇也保底一段


def test_sentence_window_snaps_to_boundaries():
    text = "第一句话。第二句里有关键词。第三句话。" * 20
    lo, hi = evidence_pack._sentence_window(text, text.find("关键词"), text.find("关键词") + 3, 30)
    assert text[lo:hi].startswith("第二句") or text[lo - 1] in "。"


# ── 选篇 ──

def test_select_primary_uses_lexical_gap_not_flat_rrf():
    pool = [{**_it("a", "蒜香鱼片"), "_fused_score": .033}, {**_it("b", "鱼片"), "_fused_score": .032},
            {**_it("c", "鱼片"), "_fused_score": .031}]
    und = {"goal": "ask", "core": ""}
    n, why = ask.select_primary("蒜香鱼片怎么做", pool, und, pool, lex={"a": 2229, "b": 342, "c": 300})
    assert n == 1 and why.startswith("relevance")
    n, _ = ask.select_primary("鱼片怎么做", pool, und, pool, lex={"a": 500, "b": 450, "c": 100})
    assert n == 2


def test_select_primary_inherited_and_survey_cap():
    pool = [_it(str(i), "x") for i in range(8)]
    assert ask.select_primary("需要哪些调料", pool, {"goal": "ask"}, pool, inherited=pool[:1]) == (1, "inherited")
    n, _ = ask.select_primary("有哪些", pool, {"goal": "survey"}, pool, lex={str(i): 10 for i in range(8)})
    assert n == ask.SELECT_MAX["survey"]


def test_lead_by_dominance_promotes_clear_lexical_winner():
    pool = [_it("noise"), _it("gold"), _it("x")]
    sem = {"noise": {"score": .41}, "gold": {"score": .40}}
    out = ask.lead_by_dominance(pool, {"noise": 376, "gold": 666}, sem)
    assert [i["id"] for i in out] == ["gold", "noise", "x"]
    # 语义上明显更差就不换
    out = ask.lead_by_dominance(pool, {"noise": 376, "gold": 666}, {"noise": {"score": .67}, "gold": {"score": .53}})
    assert out[0]["id"] == "noise"


def test_rerank_hook_fuses_not_replaces(monkeypatch):
    pool = [_it("a"), _it("b"), _it("c")]
    assert ask.rerank_pool("q", pool, {"rerank": {"enabled": False}})[0] == pool
    fake = types.ModuleType("link_brain.rerank")
    fake.rerank = lambda q, docs, settings=None, trace=None: [{**docs[2], "rerank_score": .9}, {**docs[1], "rerank_score": .5},
                                                               {**docs[0], "rerank_score": .1}]
    monkeypatch.setitem(sys.modules, "link_brain.rerank", fake)
    import link_brain
    monkeypatch.setattr(link_brain, "rerank", fake, raising=False)
    trace = {}
    order, scores = ask.rerank_pool("q", pool, {"rerank": {"enabled": True}}, trace)
    # 现序 a b c × 精排 c b a，RRF(k=10)：a、c 同分（现序在前的先）、b 两边都第 2 垫底——不是直接换成 c b a
    assert [i["id"] for i in order] == ["a", "c", "b"] and scores is None and trace["rerank"] == "fused"

    def boom(q, docs, settings=None, trace=None):
        raise TimeoutError("503")
    fake.rerank = boom
    trace = {}
    order, _ = ask.rerank_pool("q", pool, {"rerank": {"enabled": True}}, trace)
    assert order == pool and trace["rerank"].startswith("fallback")


# ── 多轮 ──

def test_switch_uses_standalone_and_drops_replaced_condition():
    items = [_it("sh", "上海 好吃的 本帮菜"), _it("au", "澳洲 好吃的 餐厅"), _it("au2", "澳洲 超市 行李")] +         [_it(f"f{i}", f"填充 {i}") for i in range(6)]
    hist = [{"role": "user", "content": "上海好吃的"}, {"role": "assistant", "content": "略"}]
    matches, mode, prior = ask.qa_matches("那澳洲的呢", items, ask.query_terms("那澳洲的呢"), None, hist,
                                          intent={"context": "switch"}, standalone="澳洲好吃的")
    assert mode == "switch" and matches[0]["id"] == "au"
    assert "上海" not in prior


def test_parse_s1_keeps_standalone_query_and_scope_as_advice():
    s1 = ask_intent.parse_s1({"standalone_query": "澳洲好吃的", "intent": {"scope": "single"}, "goal": "survey"}, "那澳洲的呢")
    assert s1["standalone_query"] == "澳洲好吃的" and s1["scope"] == "single"
    und = ask_intent.understand("那澳洲的呢", [], s1=s1)
    assert und["standalone_query"] == "澳洲好吃的" and und["scope"] == "single"
    assert "standalone_query" not in ask_intent.parse_s1({"standalone_query": "完全无关的别的东西呀"}, "鱼露")


def test_turn_lookup_by_question(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "t.json"))
    ask_turns.record("t1", {"q": "蒜香鱼片怎么做", "mode": "direct", "ids": ["a", "b"], "primary_ids": ["a"]})
    row = ask_turns.latest_for("蒜香鱼片怎么做")
    assert row["primary_ids"] == ["a"]
    items = [_it("a", "蒜香鱼片"), _it("b", "鱼片")]
    got = ask.inherited_sources([{"role": "user", "content": "蒜香鱼片怎么做"}], items)
    assert [i["id"] for i in got] == ["a"]


def test_inherited_falls_back_to_previous_question_retrieval(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "none.json"))
    items = [_it("a", "蒜香鱼片 蒜香鱼片 做法"), _it("b", "三文鱼")]
    got = ask.inherited_sources([{"role": "user", "content": "蒜香鱼片怎么做"}], items)
    assert got and got[0]["id"] == "a"


# ── 输出形态 / 规则路由 / 零命中复核 ──

def test_list_question_routes_to_survey_and_shell_strips_post_word():
    und = ask_intent.understand("澳洲做越南菜要买啥 在哪买", [], s1={"goal": "ask"})
    assert und["goal"] == "survey" and und["goal_source"] == "rule-list"
    assert ask_intent.understand("江西那个烫粉要放啥", [], s1={"goal": "find"})["goal"] == "find"
    assert ask_intent.strip_shell("讲鱼片怎么做的帖子") == "讲鱼片怎么做"
    assert ask_intent.strip_shell("写笔记 怎么做") == "写笔记 怎么做"


def test_survey_toc_not_overridden_by_deep(monkeypatch):
    pool = [_it(str(i), "越南菜 食材") for i in range(6)]
    monkeypatch.setattr(ask, "core_words", lambda u, items: ["越南菜"])
    mode, info = ask.decide_mode({"goal": "survey", "core": "越南菜"}, pool, pool, deep=True)
    assert mode == "toc" and info["reason"] == "survey"


def test_semantic_clear_guards_zero_hit_rule():
    assert ask.semantic_clear({"a": {"score": .70}}) is True
    assert ask.semantic_clear({"a": {"score": .51}, "b": {"score": .54}}) is False
    assert ask.semantic_clear(None) is False
