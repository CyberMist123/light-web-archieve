"""evidence_pack 的补充用例（现有 test_ask_b3_r1.py 已盖整篇主来源 / 窗口不跨字段 / 句界吸附）。

只加测试不改代码；全部纯函数、不出网。断言都能对到 evidence_pack.py 的具体行为
（得分公式、字段先验、语义 chunk 的 1.2 加成、装箱兜底取前 2 个字段）。
"""

from __future__ import annotations

from link_brain import evidence_pack as ep


def _it(i, body="", **fs):
    return {"id": i, "title": fs.pop("title", i), "tags": [], "summary": "", "search_fields": {"body": body, **fs}}


def test_content_fields_drops_meta_and_empty():
    item = {"id": "a", "title": "标题", "tags": ["t"], "cats": [], "author": "谁", "summary": "",
            "search_fields": {"body": "正文", "comments": "", "ocr": "字"}}
    got = ep.content_fields(item)
    assert got == {"body": "正文", "ocr": "字"}          # 元字段和空字段都不要，值转 str


def test_passages_empty_inputs():
    assert ep.passages({"id": "a"}, ["词"]) == []                  # 没有内容字段
    assert ep.passages(_it("a", body="有正文"), []) == []          # 没有词也没有语义 chunk → 没有命中点


def test_core_word_outranks_equal_frequency_word():
    # 两个词各出现一次、窗口都吸附成 3 个字：核心词稀有度权重 ×2 → 得分更高
    text = "甲词。" + "填" * 500 + "。" + "乙词。" + "填" * 500 + "。"
    out = ep.passages(_it("a", body=text), ["乙词"], core=["甲词"])
    assert [p["text"] for p in out] == ["甲词。", "乙词。"]
    assert out[0]["score"] > out[1]["score"]


def test_comment_question_boosts_comments_prior():
    item = _it("a", body="正文。", comments="网友说辣椒酱好。")
    plain = ep.passages(item, ["辣椒酱"], question="辣椒酱")
    boosted = ep.passages(item, ["辣椒酱"], question="评论区怎么说辣椒酱")
    s1 = next(p["score"] for p in plain if p["field"] == "comments")
    s2 = next(p["score"] for p in boosted if p["field"] == "comments")
    assert s2 > s1                                                 # 问题问到评论区：先验 .55 → 1.0


def test_semantic_chunk_adds_span_ignores_bad_field():
    item = _it("a", body="正文在这里。")
    sem = {"a": {"chunks": [{"field": "body", "text": "正文在这里"},
                            {"field": "tags", "text": "不该出现的字段"}]}}
    out = ep.passages(item, [], sem=sem)
    assert len(out) == 1 and out[0]["field"] == "body" and "正文在这里" in out[0]["text"]


def test_hit_survives_nfkc_length_change():
    # "ﬁ" 一个字 NFKC 后变 "fi" 两个：norm 后长度变了，命中位置按比例折回原文——
    # 段里是原文字符（ﬁnd），命中点照样落得上
    out = ep.passages(_it("a", body="前句。这里写ﬁnd了。后句。"), ["find"])
    assert out and any("ﬁnd" in p["text"] for p in out)


def test_pack_no_hits_falls_back_to_first_two_fields():
    doc = _it("a", body="字" * 5000, comments="评" * 5000)
    out = ep.pack([doc], ["查无此词"], cap=8000)
    ps = out["a"]
    assert [p["field"] for p in ps] == ["body", "comments"]        # FIELD_ORDER 里的前两个
    assert all(p["offset"] == 0 and "score" not in p for p in ps)
    assert all(len(p["text"]) == 3930 for p in ps)                 # max(MIN_PIECE, share//2)，8000-140 后的一半


def test_pack_trims_when_budget_tight():
    doc = _it("a", body="短正文。", comments="闲聊。" * 80 + "辣椒酱在此。" + "闲聊。" * 80)
    out = ep.pack([doc], ["辣椒酱"], cap=300)
    ps = out["a"]
    budget = max(200, 300 - ep.HEADER_RESERVE)                    # 预算有 200 的下限
    assert sum(len(p["text"]) for p in ps) <= budget
    body = next(p for p in ps if p["field"] == "body")
    assert body["text"] == "短正文。" and "trimmed" not in body    # 主来源短正文整段先放
    seg = next(p for p in ps if p["field"] == "comments")
    assert seg.get("trimmed") is True and len(seg["text"]) <= budget - len("短正文。")


def test_pack_empty_docs():
    assert ep.pack([], ["词"]) == {}
    assert ep.pack([None], ["词"]) == {}
