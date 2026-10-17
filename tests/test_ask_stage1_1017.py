"""1017 阶段 1：回答自检（answer_check）、作者误过滤守卫、目录只给明说要清单的、模型判定选篇。离线、不调模型。"""
from __future__ import annotations

from link_brain import answer_check, ask, ask_intent, recall_table


def _src(n, title, text, author="作者甲", comments=""):
    return {"citation": n, "id": f"xhs-{n:024d}", "title": title, "author": author, "excerpt": text,
            "excerpts": [{"field": "body", "text": text}] + ([{"field": "comments", "text": comments}] if comments else [])}


SOURCES = [
    _src(1, "溏心蛋拉面店同款", "锅中水煮沸，放入常温无菌蛋，中火煮5分30秒，捞出放冰水冷却。味玉汁：味醂40ml、酱油80ml、凉开水80ml。",
         comments="小红薯A：我用的是七分钟\n作者甲：五分半刚好"),
    _src(2, "悉尼Bondi徒步攻略", "Circular Quay 坐轮渡到 Watsons Bay，走到 Diamond Bay，再坐 380 到 Bondi。", author="Alcoholulater"),
]


def test_alignment_passes_for_grounded_sentence_and_flags_invented_one():
    md = ("锅里水煮沸后放入常温无菌蛋，中火煮5分30秒，捞出放冰水冷却[来源1]。\n"
          "味玉汁用味醂40ml、酱油80ml和凉开水80ml调[来源1]。\n"
          "这道菜起源于江户时代的武士家庭，需要用温泉水煮七天[来源1]。")
    c = answer_check.run(md, SOURCES)
    a = c["alignment"]
    assert a["cited"] == 3 and a["aligned"] == 2
    assert "武士" in a["unaligned"][0]["text"]
    assert any("引用没对上" in w for w in c["warnings"])


def test_absence_claim_conflicts_with_evidence():
    md = "原文没有给出味玉汁的具体配比，酱油和味醂的用量未披露[来源1]。"
    c = answer_check.run(md, SOURCES)
    assert c["absence"]["claims"] == 1
    assert c["absence"]["conflicts"], "来源 1 里明明有味醂 / 酱油的用量"
    assert any("说「没有」但" in w for w in c["warnings"])


def test_speaker_unknown_and_known():
    md = "评论者「小红薯A」说自己煮七分钟[来源1]。作者 Alcoholulater 回复称按这条路线走[来源2]。评论者「肖怀特」指出站台写错了[来源2]。"
    c = answer_check.run(md, SOURCES)
    names = [u["name"] for u in c["speaker"]["unknown"]]
    assert names == ["肖怀特"]


def test_template_leak_and_padding():
    md = "按机制、触发条件、关键数字展开如下。" + "这是一段很长的无引用内容。" * 60
    c = answer_check.run(md, SOURCES[:1], evidence_chars=100)
    assert c["leak"]["found"]
    assert c["padding"]["padded"] and c["padding"]["no_citation"]
    assert answer_check.footnote(c).startswith("\n\n> ⚠ 自检")
    assert answer_check.footnote({"warnings": []}) == ""


def test_author_filter_ignores_common_word_and_food_names():
    authors = {"随便", "科科科酱", "苹果派", "Alcoholulater", "凉生"}
    f = ask_intent._author_filter
    assert f("之前看到一篇讲法务面试的，说要是随便说律所加班多，会被面试官反问", authors) is None
    assert f("苹果派怎么做", authors) is None
    assert f("科科科酱发过哪些", authors) == "科科科酱"
    assert f("看看 Alcoholulater 的攻略", authors) == "Alcoholulater"
    assert f("@随便 写的那篇", authors) == "随便"
    assert f("博主随便的那篇帖子", authors) == "随便"


def test_decide_mode_toc_only_when_she_asks_for_a_list(monkeypatch):
    items = [{"id": f"xhs-{i:024d}", "title": f"菜谱{i}", "tags": [], "summary": "", "search_fields": {"body": "做菜"}} for i in range(8)]
    monkeypatch.setattr(ask, "strong_hits", lambda pool, u, items, *a, **k: list(pool))
    monkeypatch.setattr(ask, "core_words", lambda u, items: ["做菜"])
    monkeypatch.setattr(ask, "_has_all", lambda it, words, keys=None: True)
    mode, info = ask.decide_mode({"goal": "survey", "core": "晚上建议我做什么菜"}, items, items)
    assert mode == "direct", "要建议 / 判断的盘点题不出目录"
    mode, info = ask.decide_mode({"goal": "survey", "core": "列一下我收藏的菜谱"}, items, items)
    assert mode == "toc" and info["reason"] == "survey"


def test_judge_select_reorders_and_counts(monkeypatch):
    pool = [{"id": "xhs-a", "title": "A", "summary": "", "search_fields": {"body": "溏心蛋"}},
            {"id": "xhs-b", "title": "B", "summary": "", "search_fields": {"body": "溏心蛋"}},
            {"id": "xhs-c", "title": "C", "summary": "", "search_fields": {"body": "溏心蛋"}}]
    monkeypatch.setattr(ask, "call_text", lambda *a, **k: {"status": "ok", "text": "1|reject|无关\n2|deep_read|正题\n3|tentative|沾边"})
    out = recall_table.judge_select("溏心蛋怎么做", pool, {"goal": "ask", "core": "溏心蛋怎么做"}, pool, {"textAI": {}})
    assert [it["id"] for it in out["pool"]] == ["xhs-b", "xhs-c", "xhs-a"]
    assert out["n"] == 2 and out["deep"] == 1 and out["reject"] == 1   # deep 不到 2 篇补 tentative
    monkeypatch.setattr(ask, "call_text", lambda *a, **k: {"status": "skipped", "text": None})
    assert recall_table.judge_select("溏心蛋怎么做", pool, {"goal": "ask"}, pool, {"textAI": {}}) is None


def test_citation_after_period_counts_for_that_sentence():
    md = "锅里水煮沸后放入常温无菌蛋，中火煮5分30秒，捞出放冰水冷却。[来源1]\n味玉汁用味醂40ml、酱油80ml和凉开水80ml调。[来源1]"
    c = answer_check.run(md, SOURCES)
    assert c["alignment"]["cited"] == 2 and c["alignment"]["aligned"] == 2


def test_absence_ignores_words_every_candidate_has():
    related = [{"id": f"xhs-r{i}", "title": f"长文{i}", "excerpt": "路线 时刻 各条 攻略 公交 海滩 " * 3} for i in range(6)]
    md = "收藏里没有写这条路线各个时刻的公交班次。"
    c = answer_check.run(md, SOURCES, related=related)
    assert c["absence"]["claims"] == 1 and not c["absence"]["conflicts"]


def test_speaker_pattern_stops_at_quote_and_skips_benren():
    md = "作者本人回复称“游记或者流水账”，评论者「小红薯A」补充了时间[来源1]。"
    c = answer_check.run(md, SOURCES)
    assert c["speaker"]["unknown"] == []


def test_select_count_rules():
    assert recall_table.select_count(0, 0) == 0
    assert recall_count_ok(recall_table.select_count(0, 5), 2)
    assert recall_table.select_count(1, 3) == 3
    assert recall_table.select_count(5, 9) == 5
    assert recall_table.select_count(12, 0) == ask.SELECT_HARD_MAX


def recall_count_ok(got, want):
    return got == want
