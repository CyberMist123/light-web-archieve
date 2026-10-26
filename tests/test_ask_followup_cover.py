"""ask_followup 的补充用例（test_ask_v21_1018.py 已盖 resolve 各 kind、bind_parent 四种绑定、
objects_from 的表格 / 加粗条目主路径、parent_from_context；test_cite_jump_1021.py 盖 _CITE）。

这里钉边界：空串 / None 输入、_n 的中英数字（含「两 / 十一 / 二十」）、is_followup 的 switch 长度闸、
expand_question 的直接调用（REGION_WORDS 和地名表各去掉一次限定）、只有 ids 没写标题的 parent 回退、
objects_from 的清洗规则（单字 / 纯数字跳过、无分隔行的表格不收、行中加粗不算、20 个封顶）。全部纯函数。
"""

from __future__ import annotations

from link_brain import ask_followup as F


def test_empty_and_none_question_inputs():
    assert F.is_followup("") is False and F.is_followup(None) is False
    assert F.is_deictic("") is False and F.is_deictic(None) is False
    out = F.resolve("", {"q": "中国旅行推荐"})
    assert out == {"kind": "none", "question": "", "note": ""}    # 有 parent 但问句空 → 照常检索态
    assert F.resolve(None, None)["kind"] == "none"


def test_n_parses_chinese_and_arabic_numerals():
    assert F._n("3") == 3 and F._n(" 2 ") == 2                    # isdigit 前先 strip
    assert F._n("两") == 2 and F._n("十") == 10
    assert F._n("十一") == 11 and F._n("二十") == 20              # 十X / X十 两种组合
    assert F._n("第") is None and F._n("abc") is None


def test_is_followup_switch_length_gate_and_markers():
    assert F.is_followup("换成东京旅行怎么样") is True             # SWITCH 命中
    assert F.is_followup("那东京的呢") is True
    assert F.is_followup("那么" + "非常长的问题" * 6 + "呢") is False   # switch 超 30 字不认
    assert F.is_followup("再来几个") is True                      # EXPAND（再来…几）
    assert F.is_followup("上一篇") is True                        # THIS_ONE


def test_expand_question_drops_region_or_place_once():
    assert F.expand_question("中国旅行推荐", "旅游") == ("旅游推荐", "中国")   # REGION_WORDS 去掉「中国」
    assert F.expand_question("中国旅行推荐", "") == ("旅行推荐", "中国")      # 没给 Y 也去限定
    assert F.expand_question("日本东京旅行", "日本") == ("日本东京旅行", "")   # 限定词在 Y 里也出现 → 不去
    assert F.expand_question("澳洲旅行推荐", "旅游") == ("旅游推荐", "澳洲")   # 不在 REGION_WORDS → 查地名表
    assert F.expand_question("火锅推荐", "火锅") == ("火锅推荐", "")          # Y 已在新题里 → 原样


def test_resolve_ids_only_parent_and_missing_falls_through():
    p = {"q": "收藏里的帖", "ids": ["a1", "a2"], "objects": []}
    r = F.resolve("第2篇", p)                                     # 没 ordered_sources → 按 ids 补 n/角色
    assert r["kind"] == "single" and r["source_ids"] == ["a2"]
    assert r["question"] == "第2篇"                               # 没标题不加「只看《…》」前缀
    titled = {"q": "x",
              "ordered_sources": [{"n": 1, "id": "a1", "title": "", "role": "A"}, {"n": 2, "id": "a2", "title": "", "role": "A"}],
              "objects": [{"name": "甲", "ns": [1]}, {"name": "乙", "ns": [2]}]}
    r2 = F.resolve("第二个", titled)
    assert r2["kind"] == "object" and r2["object"] == "乙" and r2["source_ids"] == ["a2"]
    r3 = F.resolve("第三个", titled)                               # 2 个对象 2 篇，n=3 → 落到篇数也不够
    assert r3["kind"] == "missing" and "没有第 3 篇" in r3["note"]


def test_objects_from_skips_short_numeric_and_requires_table_separator():
    assert F.objects_from("- **A**：太短\n- **123**：纯数字\n| 悉尼：海景 | x |\n") == []   # 单字 / 纯数字跳过；表格没分隔行不收
    assert F.objects_from("| 名 |\n| 悉尼 |") == []              # 同上：只有表头行 + 无分隔行
    got = F.objects_from("看看 **行中加粗** 不算\n- **「括号名」**：x")
    assert [o["name"] for o in got] == ["括号名"]                 # 行中加粗不算；「」剥掉；ns 空列表


def test_objects_from_caps_at_twenty():
    md = "\n".join(f"- **条目{i:02d}名**：说明" for i in range(25))
    objs = F.objects_from(md)
    assert len(objs) == F.OBJECTS_MAX == 20 and objs[0]["name"] == "条目00名"
