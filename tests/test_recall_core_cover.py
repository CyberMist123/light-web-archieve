"""r5 补测：问收藏召回的公共半边（纯函数 + 禁用外呼的 Probe 路径；分词用本机 jieba，不出网）。"""
from __future__ import annotations

from link_brain import recall_core as rc


def test_previous_question_takes_last_user_message():
    hist = [{"role": "assistant", "content": "答"}, {"role": "user", "content": " 上一句 "}, {"role": "user", "content": "   "}]
    assert rc.previous_question(hist) == " 上一句 "   # 只用它判非空，返回原文（不 strip）
    assert rc.previous_question([{"role": "user", "content": "字" * 400}]) == "字" * 300  # 截到 300
    assert rc.previous_question(None) == "" and rc.previous_question([]) == ""
    assert rc.previous_question([{"role": "assistant", "content": "只有机器说过"}]) == ""


def test_feedback_terms_agree_in_top_docs_and_not_generic():
    titles = ["烤箱测评第一篇", "烤箱测评第二篇", "烤箱相关第三篇"] + [f"完全无关的内容{k}" for k in range(17)]
    items = [{"id": f"i{k}", "title": t, "tags": []} for k, t in enumerate(titles)]
    out = rc.feedback_terms(items, items[:2], ["自己做"], ())
    # 前两篇共有、库里不泛不孤（df 2–3）的词入选；同分按 df、再按词排；自己的词不重复扩
    assert out == ["测评", "烤箱"]
    # 自己已带的词（含变体）绝不二轮再扩
    assert "烤箱" not in rc.feedback_terms(items, items[:2], ["烤箱"], ())
    # 没有共有的合格词 → 空
    lone = [{"id": "a", "title": "甲乙丙丁", "tags": []}, {"id": "b", "title": "戊己庚辛", "tags": []}]
    assert rc.feedback_terms(lone, lone, []) == []


def test_route_order_and_route_ids_union():
    routes = {"lexical": ["a", "b"], "semantic": ["c"], "expansion": {"词x": ["d"], "词y": ["d2"]},
              "expanded_semantic": [], "feedback": {"f词": ["g"]}, "keyword": ["e"], "place": ["h"]}
    assert list(rc._route_order(routes)) == ["a", "b", "c", "d", "d2", "g", "e", "h"]  # 各路依次摊平
    assert rc.route_ids(routes) == {"a", "b", "c", "d", "d2", "g", "e", "h"}


def _found():
    return {"routes": {"lexical": ["a", "b"], "semantic": ["c"], "expansion": {"词x": ["d"]},
                       "expanded_semantic": [], "feedback": {}, "keyword": ["e"], "place": []},
            "candidates": [{"id": x} for x in ["a", "c", "b", "d", "f"]], "matches": [{"id": "a"}, {"id": "c"}],
            "out_of_scope": ["z"], "intent": {"goal": "find"}, "mode": "normal"}


def test_stages_records_lost_and_window():
    s = rc.stages(_found())
    assert s["lexical"] == ["a", "b"] and s["expansion"] == [{"term": "词x", "ids": ["d"]}]
    assert s["candidate_set"] == ["a", "c", "b", "d", "f"] and s["window"] == ["a", "c"]
    assert s["beyond_window"] == 3
    assert s["lost"] == ["e"]          # keyword 路检出了 e、候选集里没有 → 记进 lost
    assert s["out_of_scope"] == ["z"] and s["intent"] == {"goal": "find"} and s["mode"] == "normal"
    fused = [{"id": "f"}, {"id": "a"}]
    assert rc.stages(_found(), fused)["fusion"] == ["f", "a"]   # 给了融合名单就用那份


def test_page_paging_semantics():
    found = _found()
    rows, meta = rc.page(found, 1, 2)
    assert [r["id"] for r in rows] == ["c", "b"]
    assert meta == {"total": 5, "offset": 1, "returned": 2, "next_offset": 3, "has_more": True}
    rows, meta = rc.page(found, 0)
    assert len(rows) == 5 and meta["next_offset"] is None and meta["has_more"] is False  # 不限条数 = 到底
    rows, meta = rc.page(found, -5, 3)
    assert meta["offset"] == 0 and [r["id"] for r in rows] == ["a", "c", "b"]  # 负偏移按 0
    rows, meta = rc.page(found, 99, 3)
    assert rows == [] and meta["returned"] == 0 and meta["next_offset"] is None and meta["has_more"] is False


def test_probe_disabled_paths_fail_open():
    p = rc.Probe("空气炸锅怎么做", None, semantic=False, expand=False)
    assert p.llm() == {"terms": [], "status": "skipped"}   # 不扩词 = 明说 skipped
    assert p.sem() is None                                 # 不走语义 = 纯词法


def test_semantic_deeper_must_contain_shallow(monkeypatch):
    import link_brain.retrieval as retrieval
    calls = {}

    def hits(q):
        calls.setdefault("hits", []).append(q)
        return ["s1", "s2"]

    def deep(q):
        calls.setdefault("deep", []).append(q)
        return ["s1", "s2", "s3"]

    monkeypatch.setattr(retrieval, "semantic_hits", hits)
    monkeypatch.setattr(retrieval, "semantic_deep", deep)
    assert rc._semantic("问") == ["s1", "s2", "s3"]        # 续取那份包含浅份 → 用深的（长尾不丢）

    def deep_missing(q):                                   # 续取丢了浅份里的 → fail-open 用浅份
        return ["s9"]

    monkeypatch.setattr(retrieval, "semantic_deep", deep_missing)
    assert rc._semantic("问") == ["s1", "s2"]

    monkeypatch.setattr(retrieval, "semantic_hits", lambda q: [])
    assert rc._semantic("问") == []                        # 浅份为空直接返回，不再深取
    assert calls["deep"] == ["问"]                         # 第二次没再调 deep
