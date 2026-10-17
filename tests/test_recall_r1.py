"""Lot R1「召回统一与截断治理」：宽召回核心（recall_core）、四入口一致、候选集不截断 / 不补满、语义续取、
二轮扩词、CJK 子词回退、意图分类（搭在扩词调用里）+ 无 key 回退、评论独有事实进候选池。全部合成数据 + 假模型，不联网。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import ask, recall_core, retrieval, storage, text_stream
from link_brain.remote import tools as rtools
from link_brain.remote.policy import Policy


def _item(i, title, body="", tags=(), **fields):
    return {"id": i, "title": title, "tags": list(tags), "summary": "", "note": f"Web/Xiaohongshu/{i}.md", "url": "",
            "search_fields": {"body": body, **fields}}


def _filler(n, word="", start=0):
    """n 篇填充：带 word（让它们都成为某个词的命中，造长尾）或什么都不带。"""
    return [_item(f"fill-{start + k:03d}", f"随手记 {start + k}", f"今天天气不错 {word} 第{k}条", tags=["日常"]) for k in range(n)]


@pytest.fixture
def lexical_only(monkeypatch):
    """无 key 的样子：没有语义、没有扩词模型。"""
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: None)
    monkeypatch.setattr(retrieval, "semantic_deep", lambda q: None)
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": [], "status": "no-model"})


# ── 1. 候选集全量记录、不静默丢失、不补满 ──

def test_candidate_set_records_everything_and_window_has_no_padding(lexical_only):
    items = _filler(130, "回避") + _filler(40, "", start=200) + [_item("gold", "回避型依恋怎么改", "回避 吵架")]
    found = recall_core.candidates("回避", items, trace=True)
    ids = [it["id"] for it in found["candidates"]]
    # 131 篇都中了「回避」：首屏窗口只取各路保底前 40（不补满到 80），其余 91 篇按同一顺序留在候选集里
    assert len(found["matches"]) == recall_core.POOL_HEADS["lexical"]
    assert len(ids) == 131 and len(set(ids)) == 131
    assert ids[:40] == [it["id"] for it in found["matches"]]
    assert not any(i.startswith("fill-2") for i in ids), "一路都没中的篇不许混进来凑数"
    st = found["stages"]
    assert st["lost"] == [] and st["beyond_window"] == 91
    assert recall_core.route_ids(found["routes"]) <= set(ids)


def test_three_relevant_means_three(lexical_only):
    items = _filler(60) + [_item("a", "面包做法", "烤箱"), _item("b", "面包配方", "黄油"), _item("c", "全麦面包", "")]
    found = recall_core.candidates("面包", items)
    assert sorted(it["id"] for it in found["matches"]) == ["a", "b", "c"]
    assert len(found["candidates"]) == 3


def test_semantic_route_is_continued_past_top_items(monkeypatch):
    items = [_item(f"s{k}", f"笔记{k}", "无关正文") for k in range(60)]
    top = {f"s{k}": {"score": 1 - k / 100, "chunks": []} for k in range(40)}
    deep = {f"s{k}": {"score": 1 - k / 100, "chunks": []} for k in range(55)}
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: top)
    monkeypatch.setattr(retrieval, "semantic_deep", lambda q: deep)
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": [], "status": "no-model"})
    found = recall_core.candidates("换个说法问的问题", items, trace=True)
    assert len(found["routes"]["semantic"]) == 55          # 语义路续取到相对下限以上的全部
    # 续取到的语义长尾都在相对下限以上 = 有具体证据，按融合顺序进首屏（不超过 POOL_MAX）
    assert len(found["matches"]) == 55 and [it["id"] for it in found["matches"]][:3] == ["s0", "s1", "s2"]
    assert {f"s{k}" for k in range(55)} == {it["id"] for it in found["candidates"]}
    # 续取那份和前一份对不上（不包含它）就不用，退回前一份
    monkeypatch.setattr(retrieval, "semantic_deep", lambda q: {"zzz": {"score": 1, "chunks": []}})
    assert set(recall_core.candidates("换个说法问的问题", items)["routes"]["semantic"]) == set(top)


def test_query_hits_top_items_none_keeps_everything_above_floor(monkeypatch):
    from link_brain import semantic
    import numpy as np
    rows = [(f"i{k}", "body", f"t{k}") for k in range(50)]
    matrix = np.eye(50, dtype=np.float32)
    q = np.array([1.0] * 46 + [0.0] * 4, dtype=np.float32)   # 46 篇同分（都在相对下限以上），4 篇不沾
    q = q / np.linalg.norm(q)
    monkeypatch.setattr(semantic, "db_path", lambda: Path(__file__))
    monkeypatch.setattr(semantic, "_load_matrix", lambda model: (matrix, rows))
    monkeypatch.setattr(semantic, "query_vector", lambda question: q)
    capped = semantic.query_hits("x")
    full = semantic.query_hits("x", top_items=None)
    assert len(capped) == semantic.TOP_ITEMS and len(full) > semantic.TOP_ITEMS and set(capped) <= set(full)


# ── 2. 二轮扩词：只补窗口空位、只提第一轮检出过的长尾 ──

def test_feedback_terms_promote_corroborated_long_tail(lexical_only, monkeypatch):
    monkeypatch.setitem(recall_core.POOL_HEADS, "lexical", 3)
    top = [_item(f"t{k}", f"人机恋 回避 第{k}篇", "回避") for k in range(3)]
    tail = [_item(f"x{k}", f"杂记{k}", "回避 回避") for k in range(5)]
    corroborated = _item("gold", "人机恋里的等指令依赖症", "提到一次回避")
    feedback_only = _item("loner", "人机恋话题集", "完全没提那个词")
    items = top + tail + [corroborated, feedback_only] + _filler(80)
    found = recall_core.candidates("回避", items)
    window = [it["id"] for it in found["matches"]]
    assert any(term in corroborated["title"] for term in found["feedback"])
    assert window[:3] == [it["id"] for it in found["candidates"][:3]]   # 第一轮排序不动
    assert "gold" in window and window.index("gold") >= 3               # 只补在窗口尾部
    assert "loner" not in window                                        # 只沾反馈词的不进首屏
    assert "loner" in {it["id"] for it in found["candidates"]}          # 但记进候选集


# ── 3. 四入口一致：问收藏 / lb_retrieve / 远程 search 同一个候选集同一个顺序；目录关键词结果是它的子集 ──

@pytest.fixture
def four_entry(monkeypatch, lexical_only):
    items = ([_item(f"m{k:02d}", f"记忆系统{k}", "记忆 权重 衰减" * (k % 3 + 1)) for k in range(30)]
             + [_item("cmt", "陪伴型AI不再转头就忘", "正文只讲陪伴", comments="评论区：记忆加固要按被想起的次数")]
             + _filler(20))
    monkeypatch.setattr(ask, "load_items", lambda: items)
    return items


def test_four_entries_share_one_candidate_set(four_entry, monkeypatch):
    q = "记忆 加固"
    core = [it["id"] for it in ask.recall(q, four_entry, {}, [])["candidates"]]
    # lb_retrieve：翻页拼起来 == 问收藏的候选集（条数差只来自 top_k / offset）
    pages, offset = [], 0
    while offset is not None:
        page = retrieval.retrieve_payload(q, top_k=7, offset=offset)
        pages += [r["item_id"] for r in page["results"]]
        assert page["total"] == len(core)
        offset = page["next_offset"]
    assert pages == core
    # 远程 search：同上，found = 一共几条，returned = 这一页几条
    policy = Policy.build(storage.vault_root(), ["@xhs"])
    got, offset = [], 0
    while offset is not None:
        res = rtools.search(policy, {"query": q, "limit": 4, "offset": offset})
        assert res["found"] == len(core) and res["returned"] == len(res["results"]) <= 4
        assert res["has_more"] == (res["next_offset"] is not None)
        got += [r["item_id"] for r in res["results"]]
        offset = res["next_offset"]
    assert got == core
    # 目录关键词（lb_search / catalog-search.js 同规则）找得到的，问收藏的候选集里一定有
    kw = {it["id"] for _, _, it in retrieval.keyword_hits(q, four_entry)}
    assert kw and kw <= set(core)
    # lb_search：total = 一共几篇，found = 这一页几篇，has_more / next_offset 续取，翻完 == 关键词筛选全量
    q2 = "记忆 衰减"
    kw2 = [it["id"] for _, _, it in retrieval.keyword_hits(q2, four_entry)]
    assert len(kw2) > 3 and set(kw2) <= {it["id"] for it in ask.recall(q2, four_entry, {}, [])["candidates"]}
    lb = retrieval.search(q2, limit=3)
    assert lb["total"] == len(kw2) and lb["found"] == 3 and lb["has_more"] and lb["next_offset"] == 3
    rest = retrieval.search(q2, limit=50, offset=3)
    assert [r["item_id"] for r in lb["results"]] + [r["item_id"] for r in rest["results"]] == kw2
    assert not rest["has_more"] and rest["next_offset"] is None


def test_remote_found_is_total_not_page_size(four_entry):
    policy = Policy.build(storage.vault_root(), ["@xhs"])
    res = rtools.search(policy, {"query": "记忆", "limit": 2})
    assert res["returned"] == 2 and res["found"] > 2 and res["has_more"] and res["next_offset"] == 2


def test_remote_search_never_calls_the_expand_model(four_entry, monkeypatch):
    seen = []
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: seen.append(k) or {"terms": [], "status": "no-cache"})
    rtools.search(Policy.build(storage.vault_root(), ["@xhs"]), {"query": "记忆"})
    assert seen and all(k.get("allow_call") is False for k in seen)
    # lb_retrieve 同样只吃扩词缓存（README：不花模型钱）
    seen.clear()
    retrieval.retrieve_payload("记忆")
    assert seen and all(k.get("allow_call") is False for k in seen)


def test_comment_only_fact_enters_window_and_evidence(four_entry):
    found = ask.recall("记忆 加固 被想起", four_entry, {}, [])
    window = [it["id"] for it in found["matches"]]
    assert "cmt" in window[:5]
    item = next(it for it in four_entry if it["id"] == "cmt")
    parts = retrieval.evidence(item, found["terms"], 700)
    assert any(p["field"] == "comments" and "被想起" in p["text"] for p in parts)


# ── 4. CJK 复合词子词回退（目录关键词和 BM25 同一规则；JS 版见 tests/test_catalog_subword_r1.cjs，读同一份夹具） ──

SUB = json.loads((Path(__file__).parent / "fixtures" / "subword_r1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", SUB["cases"], ids=[c["query"] for c in SUB["cases"]])
def test_subword_fallback_keyword(case):
    hits = retrieval.keyword_hits(case["query"], SUB["items"])
    exact = [it["id"] for _, fuzzy, it in hits if not fuzzy]
    possible = [it["id"] for _, fuzzy, it in hits if fuzzy]
    assert sorted(exact) == sorted(case["exact"])
    assert set(case["possible_include"]) <= set(possible)
    assert not set(case["exclude"]) & set(exact + possible)


def test_subword_fallback_bm25_whole_word_first():
    ranked = [it["id"] for _, it in retrieval.rank(SUB["items"], ask.query_terms("面点"))]
    assert ranked[0] == "mian-dian"
    assert {"noodle-title", "noodle-body", "dimsum"} <= set(ranked) and "hike" not in ranked
    # 整词命中多（> 2 篇）：不拆
    assert {it["id"] for _, it in retrieval.rank(SUB["items"], ["快手"])} == {"noodle-title", "noodle-body", "quick3"}
    assert retrieval.subword_parts("面点") == ["面", "点"]
    assert retrieval.subword_parts("面点", ["面点", "面"]) == []        # 查询里已经拆过
    assert retrieval.subword_parts("pasta") == [] and retrieval.subword_parts("的了") == []


def test_subword_not_used_for_long_questions():
    items = SUB["items"]
    long_q = ask.query_terms("想找适合新手的面点和步道路线推荐")
    assert len(long_q) > retrieval.SUBWORD_MAX_TERMS
    assert "dimsum" not in [it["id"] for _, it in retrieval.rank(items, long_q)]


# ── 5. 意图分类：搭在扩词那次调用里（不多调）、输出不可信、没 key 退回启发式 ──

@pytest.fixture
def fake_expand(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_EXPAND_CACHE", str(tmp_path / "expand-cache.json"))
    ask._EXPAND_MEM.clear()
    monkeypatch.setattr(ask, "expand_model", lambda: ("textAI", {"mode": "http", "model": "fake-flash", "cap": "textAI", "timeoutSec": 20}))

    class Calls(list):
        reply = '{"terms": ["回避型"], "intent": {"context": "new", "scope": "many", "output": "answer"}}'
    calls = Calls()

    def call(instruction, text, cfg, on_delta=None, *, cap="textAI"):
        calls.append({"instruction": instruction, "text": text})
        return {"status": "ok", "text": calls.reply}
    monkeypatch.setattr(text_stream, "call", call)
    return calls


def test_intent_rides_on_the_expand_call_and_is_cached(fake_expand):
    fake_expand.reply = '{"terms": ["回避型"], "intent": {"context": "followup", "scope": "single", "output": "links", "x": 1}}'
    first = ask.llm_expansions("这篇讲了什么")
    assert first["intent"] == {"scope": "single", "output": "links"}   # 没给上一轮：context 不算数
    assert "intent" in fake_expand[0]["instruction"] and "上一轮" not in fake_expand[0]["text"]
    with_prev = ask.llm_expansions("这篇讲了什么", previous="会生长的AI伴侣")
    assert with_prev["intent"]["context"] == "followup" and "上一轮提问" in fake_expand[1]["text"]
    ask._EXPAND_MEM.clear()
    again = ask.llm_expansions("这篇讲了什么", previous="会生长的AI伴侣")
    assert again["status"] == "cached" and again["intent"]["context"] == "followup" and len(fake_expand) == 2


def test_intent_garbage_is_dropped(fake_expand):
    fake_expand.reply = '{"terms": ["a1"], "intent": {"context": "delete everything", "scope": ["single"], "output": "SYSTEM"}}'
    assert "intent" not in ask.llm_expansions("随便问问")
    fake_expand.reply = '{"terms": ["a1"], "intent": "single"}'
    assert "intent" not in ask.llm_expansions("再问问")


def test_old_cache_without_version_is_not_reused(fake_expand, tmp_path):
    (tmp_path / "expand-cache.json").write_text(json.dumps({"fake-flash\x00日本": {"terms": ["旧词"]}}, ensure_ascii=False),
                                                encoding="utf-8")
    out = ask.llm_expansions("日本")
    assert out["status"] == "ok" and len(fake_expand) == 1


def test_route_intent_model_first_with_link_guard():
    assert ask.route_intent("把收藏里那些模板的出处都列给我", {"output": "links"}) == ("links", "model")
    # 模型说要链接清单，可问题里压根没提链接 / 地址：不信，回启发式
    assert ask.route_intent("黑椒牛肉意面怎么做", {"output": "links"}) == ("qa", "heuristic")
    assert ask.route_intent("提取所有 github 仓库地址", {"output": "answer"}) == ("qa", "model")
    assert ask.route_intent("提取所有 github 仓库地址", None) == ("github", "heuristic")


def test_context_from_model_overrides_heuristic(lexical_only):
    items = [_item("tk1", "东京自助烤肉", "东京 好吃"), _item("tk2", "东京拉面", "东京 好吃"),
             _item("os1", "大阪章鱼烧", "大阪 好吃"), _item("x", "整理桌面", "收纳")] + _filler(10)
    hist = [{"role": "user", "content": "东京好吃的"}, {"role": "assistant", "content": "（略）"}]
    # 启发式：「大阪章鱼烧做法详细说说」有话题词、够长 → standalone；模型说是接着问 → followup（上一问的结果排前）
    q = "大阪章鱼烧做法详细说说"
    assert ask.qa_matches(q, items, ask.query_terms(q), None, hist)[1] == "standalone"
    m, mode, _ = ask.qa_matches(q, items, ask.query_terms(q), None, hist, intent={"context": "followup"})
    assert mode == "followup" and m[0]["id"] in {"tk1", "tk2"}
    # 启发式会判追问的短问，模型说是新话题 → standalone
    assert ask.qa_matches("需要哪些调料", items, ask.query_terms("需要哪些调料"), None, hist)[1] == "followup"
    assert ask.qa_matches("需要哪些调料", items, ask.query_terms("需要哪些调料"), None, hist,
                          intent={"context": "new"})[1] == "standalone"
    # switch：说换对象但这一问没有库里的新对象 → 按追问
    assert ask.qa_matches("那个呢", items, ask.query_terms("那个呢"), None, hist, intent={"context": "switch"})[1] == "followup"


def test_deep_read_follows_model_scope_and_keeps_pin_guard():
    pool = [_item("a", "做了很多年的黑椒牛肉意面配方", "黑椒 牛肉 意面"), _item("b", "番茄意面", "意面"),
            _item("c", "奶油意面", "意面")]
    q = "那个意面怎么做"   # 启发式：没点名标题、没融合分 → 不深读
    assert ask.prompt_count(q, pool, 8000, 8) == (3, False)
    assert ask.prompt_count(q, pool, 8000, 8, intent={"scope": "single"}) == (1, True)
    assert ask.prompt_count(q, pool, 8000, 8, intent={"scope": "many"}) == (3, False)
    # 模型说单篇，但第 1 名和这一问一个词都不沾：不深读
    assert ask.prompt_count("量子计算入门", pool, 8000, 8, intent={"scope": "single"}) == (3, False)
    # 她留了来源重答 / 会话里保留了来源：从不深读，意图也不例外
    assert ask.prompt_count(q, pool, 8000, 8, pinned=True, intent={"scope": "single"}) == (3, False)
    # 启发式三道护栏照旧（无 key 时的 fallback）
    assert ask.deep_read_wanted("做了很多年的黑椒牛肉意面配方的完整做法", pool) is True
    assert ask.deep_read_wanted("意面有哪些做法", [{**pool[0], "_fused_score": 9}, {**pool[1], "_fused_score": 1}]) is False


def _answer_env(monkeypatch, items):
    calls = []

    def model(prompt, text, settings):
        calls.append(text)
        return {"status": "ok", "text": "据材料作答。[来源1]"}
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in items])
    monkeypatch.setattr(ask, "call_text", model)
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: None)
    monkeypatch.setattr(retrieval, "semantic_deep", lambda q: None)
    return calls


def test_answer_makes_exactly_one_expand_call_and_uses_its_intent(monkeypatch, fake_expand):
    items = [_item("gold", "做了很多年的黑椒牛肉意面配方", "黑椒牛肉意面 步骤一二三", ocr="小贴士四条"),
             _item("b", "番茄意面", "意面"), _item("c", "奶油意面", "意面")] + _filler(10)
    calls = _answer_env(monkeypatch, items)
    fake_expand.reply = '{"terms": ["黑胡椒"], "intent": {"scope": "single", "output": "answer"}}'
    r = ask.answer("那个黑椒意面的完整做法")
    assert r["status"] == "ok" and len(fake_expand) == 1 and len([c for c in calls if "【证据】" in c]) == 1
    assert r["intent_source"] == "model" and r["intent_model"]["scope"] == "single"
    assert r["deep_read"] is True and [s["id"] for s in r["sources"]] == ["gold"]
    assert r["candidate_set"]["total"] >= 3 and isinstance(r["candidate_set"]["more"], list)


def test_answer_links_route_from_model(monkeypatch, fake_expand):
    items = [_item("a", "Notion 模板合集", "模板地址 https://example.com/t")]
    items[0]["url"] = "https://example.com/a"
    calls = _answer_env(monkeypatch, items)
    fake_expand.reply = '{"terms": [], "intent": {"output": "links"}}'
    r = ask.answer("把 notion 模板的原帖地址都给我")
    assert r["intent"] == "links" and r["intent_source"] == "model" and not calls


def test_no_key_lexical_path_is_unchanged(monkeypatch):
    """fail-open 回归：没 key（扩词 no-model、没语义）时，意图走启发式、mode 走启发式、检索纯词法，照常作答。"""
    items = [_item("a", "东京自助烤肉", "东京 好吃"), _item("b", "东京拉面", "好吃"), _item("c", "整理桌面", "收纳")]
    calls = _answer_env(monkeypatch, items)
    monkeypatch.setattr(ask, "expand_model", lambda: ("", None))
    r = ask.answer("东京好吃的")
    assert r["status"] == "ok" and r["intent"] == "qa" and r["intent_source"] == "heuristic"
    assert r["expansion"]["status"] == "no-model" and "intent_model" not in r
    assert {s["id"] for s in r["sources"]} == {"a", "b"} and len([c for c in calls if "【证据】" in c]) == 1
    assert ask.answer("提取所有 github 仓库地址")["intent"] == "github"
    hist = r["history"]
    follow = ask.answer("第二个详细说说", hist)
    assert follow["status"] == "ok"


# ── 6. R1 收尾（10-04 真库评测查出的四条）──

def test_out_of_scope_semantic_ids_are_recorded_not_lost(monkeypatch):
    """语义索引里还留着已删 / 进回收站的篇：不算「检出了却丢了」（lost 恒为空），单独记 out_of_scope，也不进候选集。"""
    items = [_item("a", "回避型依恋", "回避"), _item("b", "吵架以后", "吵架")] + _filler(10)
    sem = {"gone": {"score": .9, "chunks": []}, "a": {"score": .8, "chunks": []}}
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: sem)
    monkeypatch.setattr(retrieval, "semantic_deep", lambda q: sem)
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": [], "status": "no-model"})
    found = recall_core.candidates("回避 吵架", items, trace=True)
    ids = [it["id"] for it in found["candidates"]]
    assert "gone" not in ids and "gone" not in found["routes"]["semantic"]
    assert found["out_of_scope"] == ["gone"] and found["stages"]["out_of_scope"] == ["gone"]
    assert found["stages"]["lost"] == []
    assert {"a", "b"} <= set(ids)


def test_window_keeps_route_heads_before_semantic_tail(monkeypatch):
    """首屏窗口先保各路保底名次（这里是扩词一路的前几名），语义续取的长尾只补空位——不许把保底篇挤出 80。"""
    sem_items = [_item(f"s{k:03d}", f"笔记{k}", "无关正文") for k in range(120)]
    exp_items = [_item(f"e{k}", f"依恋小记{k}", "依恋") for k in range(10)]
    items = sem_items + exp_items + _filler(30)
    top = {f"s{k:03d}": {"score": 1 - k / 1000, "chunks": []} for k in range(40)}
    deep = {f"s{k:03d}": {"score": 1 - k / 1000, "chunks": []} for k in range(120)}
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: top)
    monkeypatch.setattr(retrieval, "semantic_deep", lambda q: deep)
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": ["依恋"], "status": "cached"})
    found = recall_core.candidates("怎么才能不忘事", items, trace=True)
    window = [it["id"] for it in found["matches"]]
    assert len(window) == recall_core.POOL_MAX
    assert {f"e{k}" for k in range(10)} <= set(window), "扩词路保底的篇被语义长尾挤出了首屏"
    assert {f"s{k:03d}" for k in range(40)} <= set(window)
    # 窗口外的语义长尾一篇不丢，按顺序接在候选集后面
    assert {f"s{k:03d}" for k in range(120)} <= {it["id"] for it in found["candidates"]}
    assert found["stages"]["lost"] == []


def test_expansion_routes_do_not_split_into_single_chars(lexical_only, monkeypatch):
    """扩词 / 反馈词单开一路时不走 CJK 子词回退：「布里斯班」整词只中 2 篇，拆成单字会拉进几十篇不相干的。"""
    items = ([_item("bne1", "布里斯班一日游", "布里斯班"), _item("bne2", "南岸公园", "在布里斯班")]
             + [_item(f"x{k}", f"班级里的事{k}", "里面 上班 斯文") for k in range(40)])
    assert {it["id"] for _, it in retrieval.rank(items, ["布里斯班"], subword=False)} == {"bne1", "bne2"}
    assert len(retrieval.rank(items, ["布里斯班"])) > 2   # 她原话里的稀有词照旧回退（目录 / 问收藏的原词路）
    assert {it["id"] for _, it in retrieval.rank(items, ["布里斯班"], subword=False)} == \
        {it["id"] for _, it in retrieval.rank(items, ["布里斯班"], subword=False)}  # 记忆化按 subword 分开存
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": ["布里斯班"], "status": "cached"})
    found = recall_core.candidates("澳洲旅行", items + [_item("au", "澳洲旅行清单", "澳洲旅行")])
    assert set(found["routes"]["expansion"]["布里斯班"]) == {"bne1", "bne2"}
    assert not any(it["id"].startswith("x") for it in found["candidates"])


def test_generic_term_counts_its_best_field_only():
    """泛词（全库四成以上都有，如「ai」）和不泛的词一起问时只算最好的那个字段：只沾 ai 的篇不许压过提到一次「回避」的篇。"""
    loud = [_item(f"ai{k}", f"AI 工具{k}", "ai " * 5, tags=["AI"], ocr="AI 截图 ai", comments="ai ai")
            for k in range(30)]
    gold = _item("gold", "AI 被动等指令的毛病", "怎么让它主动一点", attachments="很长的附件 " * 300 + "这其实是一种回避 " + "附件 " * 300)
    plain = _filler(20)
    items = loud + [gold] + plain
    ranked = [it["id"] for _, it in retrieval.rank(items, ["ai", "回避"])]
    assert ranked[0] == "gold"
    # 只问泛词时照旧逐字段累加：处处是 ai 的排在只有标题带 AI 的前面
    title_only = _item("t", "AI 一句话", "无关")
    ranked_ai = [it["id"] for _, it in retrieval.rank(loud + [title_only] + plain, ["ai"])]
    assert ranked_ai.index("t") > ranked_ai.index("ai0")


def test_deep_read_title_named_beats_model_many_unless_listing():
    """模型说 many（它「拿不准就填 many」），可问题点名了第 1 篇标题、又没有盘点口气：仍深读。追问时不按第 1 名收窄。"""
    pool = [_item("z", "陪伴型AI记忆调研：Zep 与 Graphiti", "zep graphiti"), _item("m", "记忆系统合集", "记忆"),
            _item("n", "向量库对比", "向量")]
    many = {"scope": "many", "output": "answer"}
    assert ask.prompt_count("陪伴型AI记忆调研里 Zep/Graphiti 的经验", pool, 8000, 8, intent=many) == (1, True)
    assert ask.prompt_count("推荐几篇陪伴型AI记忆调研", pool, 8000, 8, intent=many) == (3, False)
    assert ask.prompt_count("向量数据库怎么选", pool, 8000, 8, intent=many) == (3, False)
    # 追问：候选第 1 名是上一问的第 1 篇，不是「第二个」——模型说 single 也不收窄
    follow = {"context": "followup", "scope": "single", "output": "answer"}
    assert ask.prompt_count("第二个详细说说", pool, 8000, 8, intent=follow) == (3, False)
    # 追问里点名了标题：照样深读
    assert ask.prompt_count("陪伴型AI记忆调研那篇详细说说", pool, 8000, 8, intent=follow)[1] is True


def test_four_entries_agree_with_semantic_and_expansion_on(four_entry, monkeypatch):
    """同 scope 同配置（语义层开着、扩词缓存里有这一问）：问收藏 / lb_retrieve / 远程 search 候选集同一份同一顺序。"""
    sem = {f"m{k:02d}": {"score": 1 - k / 100, "chunks": []} for k in range(0, 30, 2)}
    sem["cmt"] = {"score": .99, "chunks": [{"field": "comments", "text": "记忆加固", "score": .99}]}
    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: sem)
    monkeypatch.setattr(retrieval, "semantic_deep", lambda q: sem)
    # 扩词缓存命中：三个入口拿到同一份（lb_retrieve / 远程只吃缓存，问收藏会调模型——缓存里有就不调）
    monkeypatch.setattr(ask, "llm_expansions", lambda q, **k: {"terms": ["权重"], "status": "cached"})
    q = "记忆 加固"
    core = [it["id"] for it in ask.recall(q, four_entry, {}, [])["candidates"]]
    assert "cmt" in core and len(core) > 20
    pages, offset = [], 0
    while offset is not None:
        payload = retrieval.retrieve_payload(q, top_k=7, offset=offset)
        assert payload["total"] == len(core)
        pages += [r["item_id"] for r in payload["results"]]
        offset = payload["next_offset"]
    assert pages == core
    got, offset = [], 0
    while offset is not None:
        res = rtools.search(Policy.build(storage.vault_root(), ["@xhs"]), {"query": q, "limit": 9, "offset": offset})
        assert res["found"] == len(core)
        got += [r["item_id"] for r in res["results"]]
        offset = res["next_offset"]
    assert got == core
