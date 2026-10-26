"""1021 她：问收藏回答里点引用要跳到正文那一处（Gemini 式索引对照）。

后端这半边：
- render：正文每段 <p data-p=段序号>、评论 <article data-cid=楼号>（楼号同 llm.comment_labels / 机读版）；
- locate_excerpts：每段证据带 seg（1 起），正文 / 文字稿段按 offset 算出落在哪几段 paras（同 body_paragraph_spans）；
- 送模型的段标签 [段k · 正文]，模型写 [来源N 段k]；所有认 [来源N] 的正则都认 [来源N 段k]（findall 仍只回来源号）。
"""
from __future__ import annotations

import json

from link_brain import answer_check, answer_prompt, ask, ask_followup, render, storage


def test_body_paragraph_spans_match_rendered_paragraphs():
    body = "第一段第一行\n第一段第二行\n\n#话题[话题]#\n\n   \n第三段\n\n\n\n第四段 #tag[话题]# 尾巴\n"
    spans = render.body_paragraph_spans(body)
    html = render._body_html(body)
    assert len(spans) == html.count("<p data-p=")
    assert [body[a:b].split("\n")[0] for a, b in spans] == ["第一段第一行", "第三段", "第四段 #tag[话题]# 尾巴"]
    assert '<p data-p="0">第一段第一行<br>第一段第二行</p>' in html
    assert '<p data-p="2">第四段  尾巴</p>' in html
    assert render._body_html("") == '<div class="lb-body"><p>（无正文）</p></div>'
    assert render._body_html("#只有话题[话题]#") == '<div class="lb-body"><p>（无正文）</p></div>'


def test_comments_carry_floor_labels():
    comments = [{"comment_id": "a", "text": "一楼", "author": {"nickname": "甲"},
                 "sub_comments": [{"comment_id": "a1", "text": "一楼回复", "author": {"nickname": "乙"}}]},
                {"comment_id": "b", "text": "二楼", "author": {"nickname": "丙"}}]
    html = render._comments_html({"hashtags": [], "engagement": {}}, comments, {"files": []}, "_archive/xiaohongshu/x")
    assert '<article class="lb-comment" data-cid="c1">' in html
    assert '<article class="lb-comment lb-reply" data-cid="c1.1">' in html
    assert '<article class="lb-comment" data-cid="c2">' in html


def test_locate_excerpts_numbers_segments_and_maps_body_paragraphs(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    body = "开头一段。\n\n中间这段讲做法：先腌后煎。\n\n结尾一段。"
    item = {"id": "x1", "search_fields": {"body": body, "transcript": "稿子第一段\n\n稿子第二段"}}
    off = body.index("先腌后煎")
    parts = ask.locate_excerpts(item, [
        {"field": "body", "text": "先腌后煎", "offset": off},
        {"field": "body", "text": body, "offset": 0},
        {"field": "transcript", "text": "稿子第二段", "offset": item["search_fields"]["transcript"].index("稿子第二段")},
        {"field": "body", "text": "没 offset 的旧证据"},
        {"field": "body", "text": "对不上的 offset", "offset": 9999},
    ])
    assert [p["seg"] for p in parts] == [1, 2, 3, 4, 5]
    assert parts[0]["paras"] == [1]
    assert parts[1]["paras"] == [0, 1, 2]
    assert parts[2]["paras"] == [1]
    assert "paras" not in parts[3]
    assert parts[4]["paras"] == []      # 前端退回按原文找
    # 段序号和渲染出的 <p data-p> 一致
    html = render._body_html(body)
    assert '<p data-p="1">中间这段讲做法：先腌后煎。</p>' in html


def test_excerpt_tag_with_segment_number():
    assert ask._excerpt_tag({"field": "body", "text": "x"}, 3) == "[段3 · 正文]"
    assert ask._excerpt_tag({"field": "comments", "text": "x", "comment_labels": ["c5"], "speakers": ["评论者：小王（不是作者）"]}, 2) \
        == "[段2 · 评论区 c5 · 评论者：小王（不是作者）]"
    assert ask._excerpt_tag({"field": "ocr", "text": "x", "images": ["图2"]}) == "[图片文字 图2]"   # 没段号 = 老样子


def test_citation_regexes_accept_segment_numbers():
    md = "一 [来源1]。二 [来源2 段3]。三 [来源4·段12]。四 [来源5段1][来源6]。\n## 来源导读\n- [来源2 段3]《标题》— 最完整"
    assert ask.CITE_ANY.findall(md) == ["1", "2", "4", "5", "6", "2"]
    assert answer_prompt.body_citations(md) == [1, 2, 4, 5, 6]
    assert answer_prompt.parse_guide(md) == [{"n": 2, "text": "[来源2 段3]《标题》— 最完整"}]
    assert answer_check.CITE_RE.findall("[来源2 段3][来源7]") == ["2", "7"]
    assert answer_check.CITE_RE.sub("", "事实[来源2 段3]。") == "事实。"
    assert ask_followup._CITE.findall("- **对象**[来源3 段2]") == ["3"]
    # 看图占位不受影响
    assert ask._SEE_IMG.search("[看图：来源2 图3]")
    # 1026：模型也写 [来源N 图M] / [来源N 段k 图M]，都算引用了来源 N；看图占位不算引用
    md2 = "甲 [来源1 段2 图1]。乙 [来源6 图5]。丙 [看图：来源3 图2]"
    assert ask.CITE_ANY.findall(md2) == ["1", "6"]
    assert answer_prompt.body_citations(md2) == [1, 6]
    assert answer_check.CITE_RE.sub("", "事实[来源6 图5]。") == "事实。"
    assert ask_followup._CITE.findall("- **对象**[来源3 段2 图4]") == ["3"]


def test_prompt_rules_ask_for_segment_citations():
    assert "[来源N 段k]" in answer_prompt.CORE_RULES
    assert "[段k · 正文]" in answer_prompt.CORE_RULES


def test_uncited_pins_note_counts_segment_citations():
    pinned = [{"citation": 2, "title": "甲"}, {"citation": 3, "title": "乙"}]
    note = ask.uncited_pins_note("用到 [来源2 段1]", pinned)
    assert "来源2" not in note and "来源3" in note
