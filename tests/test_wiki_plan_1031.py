"""个人 Wiki「按我的思路搭框架」（10-31 第二块，link_brain/wiki_plan.py）：出计划、按节检索（问收藏同一套 retrieve_payload）、
只许引候选编号（程序换回 [标题](lwa:id)、删掉不存在的）、原话核对（不是原帖逐字子串的标出来）、她写的字不动只往节下补、相反的说法单列。

conftest 已把 vault 指到 tmp；检索和模型一律 monkeypatch，不联网。合成内容。
"""
import io
import json
import sys

import pytest

from link_brain import personal_wiki as pw, wiki_plan

ITEMS = {
    "xhs-a1": {"id": "xhs-a1", "title": "分层记忆分享", "summary": "", "search_fields": {"body": "短期记忆很简单直接塞20轮全量。中期记忆：近12小时摘要。"}},
    "xhs-b2": {"id": "xhs-b2", "title": "召回门槛笔记", "summary": "", "search_fields": {"body": "召回门槛宁肯高一些也不要乱召回。"}},
    "bili-c3": {"id": "bili-c3", "title": "反对分层的视频", "summary": "", "search_fields": {"transcript": "每条记忆互相链接形成网络，不分层。"}},
}


@pytest.fixture()
def fake(monkeypatch):
    from link_brain import ask, indextree, retrieval, text_stream
    seen = {"calls": [], "queries": []}
    monkeypatch.setattr(indextree, "text_ai", lambda: ({"mode": "cli", "model": "demo-model", "command": "demo"}, ""))
    monkeypatch.setattr(ask, "load_items", lambda: list(ITEMS.values()))
    monkeypatch.setattr(retrieval, "_content_fields", lambda it: dict(it.get("search_fields") or {}))
    hits = {"分层": ["xhs-a1", "bili-c3"], "门槛": ["xhs-b2", "xhs-a1"]}

    def retrieve(q, top_k=8, offset=0):
        seen["queries"].append(q)
        ids = next((v for k, v in hits.items() if k in q), [])
        return {"results": [{"item_id": i, "title": ITEMS[i]["title"], "excerpts": [{"field": "body", "text": next(iter(ITEMS[i]["search_fields"].values()))}]} for i in ids]}
    monkeypatch.setattr(retrieval, "retrieve_payload", retrieve)

    def call(instruction, text, cfg, on_delta=None, **kw):
        seen["calls"].append((instruction, text))
        return {"status": "ok", "text": seen["reply"] if isinstance(seen.get("reply"), str) else json.dumps(seen["reply"], ensure_ascii=False)}
    monkeypatch.setattr(text_stream, "call", call)
    return seen


def test_plan_returns_sections_from_her_idea(fake):
    p = pw.create_page("记忆", body="我自己的看法：要分层。")["page"]
    fake["reply"] = "好的：\n```json\n" + json.dumps({"sections": [{"title": "分层", "query": "记忆 分层", "why": "各层存什么"}, {"title": "  ", "query": "x"},
                                                                {"title": "召回门槛", "query": "召回 门槛", "why": ""}]}, ensure_ascii=False) + "\n```"
    res = wiki_plan.make_plan({"id": p["id"], "idea": "想要两节：分层、召回门槛"})
    assert [s["title"] for s in res["sections"]] == ["分层", "召回门槛"]   # 空标题的节丢掉
    ins, text = fake["calls"][0]
    assert "只出计划" in ins and "想要两节" in text and "我自己的看法" in text
    with pytest.raises(pw.WikiError) as e:
        wiki_plan.make_plan({"id": p["id"], "idea": "  "})
    assert e.value.code == "BAD_ARGS"


def test_fill_cites_only_numbers_checks_quotes_keeps_her_words_and_lists_opposites(fake):
    body = "我自己的看法：要分层。\n\n## 分层\n她写的一句，不能动。\n\n## 结尾\n她的结尾。"
    p = pw.create_page("记忆", body=body)["page"]
    fake["reply"] = {"sections": [
        {"title": "分层", "points": [
            {"text": "短期直接塞 20 轮。", "src": "S1", "quote": "短期记忆很简单直接塞20轮全量"},
            {"text": "编了一条不存在的。", "src": "S9", "quote": "瞎编"},
            {"text": "原话对不上的。", "src": "s1", "quote": "这句原帖里没有"}],
         "against": [{"text": "有人主张不分层、做成网络。", "src": "S2", "quote": "每条记忆互相链接形成网络"}]},
        {"title": "召回门槛", "points": [{"text": "门槛宁高勿乱。", "src": "[S3]", "quote": "召回门槛宁肯高一些"}]}]}
    res = wiki_plan.fill({"id": p["id"], "idea": "想要两节", "sections": [{"title": "分层", "query": "记忆 分层"}, {"title": "召回门槛", "query": "召回 门槛"}]})
    assert fake["queries"] == ["记忆 分层", "召回 门槛"]                      # 每节检索一次
    ins, text = fake["calls"][0]
    assert "[S1]《分层记忆分享》" in text and "[S3]《召回门槛笔记》" in text   # 全页一套编号，同一篇只编一次
    assert text.count("[S1]") == 2
    new = res["text"]
    assert new.startswith("我自己的看法：要分层。\n\n## 分层\n她写的一句，不能动。\n")   # 她的字不动
    assert "## 结尾\n她的结尾。" in new
    assert "- 短期直接塞 20 轮。 [分层记忆分享](lwa:xhs-a1)\n  > 「短期记忆很简单直接塞20轮全量」\n" in new
    assert "编了一条不存在的" not in new and res["dropped"] == 1           # 不存在的编号整条删
    assert "原帖里没找到这句" in new and res["bad_quotes"][0]["quote"] == "这句原帖里没有"
    assert "### 相反的说法\n- 有人主张不分层、做成网络。 [反对分层的视频](lwa:bili-c3)" in new
    # 已有「分层」节：补在那一节末尾（在「结尾」之前）；没有的「召回门槛」在页尾新开
    assert new.index("短期直接塞") < new.index("## 结尾") < new.index("## 召回门槛")
    assert "- 门槛宁高勿乱。 [召回门槛笔记](lwa:xhs-b2)" in new
    assert {x["n"] for x in res["sources"]} == {"S1", "S2", "S3"}
    assert pw.get_page(p["id"])["body"].strip() == body                        # 不写盘


def test_fill_errors_in_plain_words(fake, monkeypatch):
    from link_brain import retrieval
    p = pw.create_page("记忆")["page"]
    with pytest.raises(pw.WikiError) as e:
        wiki_plan.fill({"id": p["id"], "idea": "x", "sections": []})
    assert "一节都没有" in str(e.value)
    monkeypatch.setattr(retrieval, "retrieve_payload", lambda q, top_k=8, offset=0: {"results": []})
    with pytest.raises(pw.WikiError) as e:
        wiki_plan.fill({"id": p["id"], "idea": "x", "sections": [{"title": "分层", "query": "记忆"}]})
    assert e.value.code == "NOT_FOUND" and "没在收藏里搜到" in str(e.value)


def test_cli_plan_fill_go_through_wiki_plan_main(fake, monkeypatch, capsys):
    p = pw.create_page("记忆")["page"]
    fake["reply"] = {"sections": [{"title": "分层", "query": "记忆 分层", "why": ""}]}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({"id": p["id"], "idea": "分层"}).encode()), encoding="utf-8"))
    assert wiki_plan.main(["plan"]) == 0
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert j["ok"] and j["sections"][0]["title"] == "分层"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8"))
    assert wiki_plan.main(["fill"]) == 2
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert j["ok"] is False and j["code"] == "BAD_ARGS"
