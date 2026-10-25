"""1018 问收藏 v2.1 第①②步：作答层重写（判断＋导读、隐藏想法块、按任务模板、撤缓存注入）、理解层最小字段（task / note / clues）、
自检新指标（防御句 / 搬运度 / 流水账 / 导读）、MCP 会话状态（thread_id / 兜底绑定 / 指代解析）。全部合成数据，不调模型。"""
from __future__ import annotations


import io
import json
from datetime import datetime, timedelta

import pytest

from link_brain import answer_check, answer_prompt, ask, ask_followup, ask_intent, ask_turns, storage
from link_brain import mcp_tools as mt
from link_brain.remote.policy import Policy

from test_ask_ui2_1004 import ITEMS, _setup


# ---------------------------------------------------------------- 作答提示词

def test_task_mapping_from_goal_and_wording():
    assert answer_prompt.task_for({"goal": "find"}, "有个帖子讲做梦的") == "find"
    assert answer_prompt.task_for({"goal": "ask"}, "晚上吃啥") == "howto"
    assert answer_prompt.task_for({"goal": "ask"}, "ai 做梦设计") == "synthesize"
    assert answer_prompt.task_for({"goal": "ask"}, "这家店值不值得去") == "evaluate"
    assert answer_prompt.task_for({"goal": "ask"}, "租房不能动墙，能借鉴什么") == "adapt"
    assert answer_prompt.task_for({"goal": "survey"}, "中国旅行推荐") == "survey"
    assert answer_prompt.task_for({"goal": "survey", "task": "inspire"}, "x") == "inspire"
    assert answer_prompt.task_for({"task": "bogus", "goal": "ask"}, "x") == "synthesize"


def test_system_prompt_has_one_template_and_no_old_bad_lines():
    p = answer_prompt.system_prompt("synthesize")
    assert "【本题模板：综合研究】" in p and "【本题模板：做法】" not in p and "【本题模板：找回】" not in p
    assert "## 来源导读" in p and "<想法>" in p
    for bad in ("缺口单独简述", "相关的材料都要照顾到", "尽量保留原文的措辞", "个中文字内", "每项保留重要细节"):
        assert bad not in p
    assert "不写「未披露" in p
    assert "【本题模板：找回】" in answer_prompt.system_prompt("absence")
    assert "【本题模板：推荐盘点】" in answer_prompt.system_prompt("inspire")
    styled = answer_prompt.system_prompt("find", style="多用短句")
    assert styled.endswith("多用短句")


def test_max_tokens_per_task_respects_bigger_user_setting():
    assert answer_prompt.max_tokens("find", 1200) == 1200
    assert answer_prompt.max_tokens("find", 2400) == 2400
    assert answer_prompt.max_tokens("synthesize", 2400) == 4000
    assert answer_prompt.max_tokens("howto", None) == 2400


def test_split_thought_and_fail_open():
    t, body = answer_prompt.split_thought("<想法>\n1 核心判断：两类\n</想法>\n\n收藏里的做梦分两类[来源1]。")
    assert t.startswith("1 核心判断") and body.startswith("收藏里的做梦")
    assert answer_prompt.split_thought("直接答[来源1]") == ("", "直接答[来源1]")
    t, body = answer_prompt.split_thought("<想法>没闭合的想法 然后正文")
    assert t == "" and body == "没闭合的想法 然后正文"


def test_thought_gate_hides_block_until_closed_and_passes_rest():
    out = []
    g = answer_prompt.ThoughtGate(out.append)
    for piece in ["<想", "法>\n1 核心", "判断：x\n</想", "法>\n\n第一段判断", "[来源1]"]:
        g(piece)
    g.finish()
    assert "".join(out) == "第一段判断[来源1]"
    # 没有标签：原样透传（首段先攒几个字看清不是标签）
    out2 = []
    g2 = answer_prompt.ThoughtGate(out2.append)
    for piece in ["收藏里", "分两类[来源1]"]:
        g2(piece)
    g2.finish()
    assert "".join(out2) == "收藏里分两类[来源1]"
    # 只有开标签没闭合：finish 时把正文放出来
    out3 = []
    g3 = answer_prompt.ThoughtGate(out3.append)
    g3("<想法>想了想 然后忘了闭合 正文在这")
    g3.finish()
    assert "".join(out3) == "想了想 然后忘了闭合 正文在这"


def test_guide_parse_attach_and_ordered_sources():
    md = ("两类做梦[来源2][来源1]。\n\n也可以看：《别的》\n\n## 来源导读\n"
          "- [来源2]《池又雨》— 体验型，梦会被忘掉。必看：图1、评论 c2\n"
          "- [来源1]《Lucie》— 最完整的整理型。选看：图1–3\n")
    sources = [{"citation": 1, "id": "a", "title": "Lucie", "tier": "primary"}, {"citation": 2, "id": "b", "title": "池又雨", "tier": "primary"},
               {"citation": 3, "id": "c", "title": "也提到", "tier": "also"}]
    ordered = answer_prompt.attach_guides(sources, md)
    assert sources[1]["guide"].startswith("[来源2]《池又雨》") and "guide" not in sources[2]
    assert [o["id"] for o in ordered] == ["b", "a", "c"] and ordered[2]["role"] == "M" and ordered[0]["role"] == "A"
    assert answer_prompt.body_citations(md) == [2, 1]


def test_image_catalog_reads_vision_descriptions(tmp_path):
    obj = tmp_path / "_archive" / "xiaohongshu" / "abc"
    (obj / "derived").mkdir(parents=True)
    (obj / "derived" / "vision.json").write_text(json.dumps({"images": [
        {"asset": "raw/v0001/assets/image-001.webp", "status": "ok", "visual": {"text": "封面只有标题字：AI 做梦机制"}},
        {"asset": "raw/v0001/assets/image-003.webp", "status": "ok", "ocr": "三层处理流程\n触发 素材 产出", "visual": {}},
        {"asset": "raw/v0001/assets/image-002.webp", "status": "failed"}]}, ensure_ascii=False), encoding="utf-8")
    cat = answer_prompt.image_catalog(str(obj / "derived" / "agent.md"))
    assert cat.startswith("图目录：图1 封面只有标题字：AI 做梦机制") and "图3 三层处理流程" in cat and "图2" not in cat
    assert answer_prompt.image_catalog(None) == "" and answer_prompt.image_catalog(str(tmp_path / "nope" / "derived" / "agent.md")) == ""


# ---------------------------------------------------------------- 理解层

def test_shell_keeps_wangdiao_and_s1_minimal_fields():
    assert "忘掉" in ask_intent.strip_shell("有个帖子教人怎么不让机把过去的事忘掉")
    assert ask_intent.strip_shell("我有个鱼露忘了哪儿了") == "鱼露"
    s1 = ask_intent.parse_s1({"goal": "find", "core": "吵架楼", "task": "find", "note": "她记得的是帖子的形态——评论很长、在吵架，不是主题。",
                              "clues": ["评论特别长", "评论里在吵"], "task_x": "ignored"}, "有一个评论很长的吵架楼 找找")
    assert s1["task"] == "find" and s1["clues"] == ["评论特别长", "评论里在吵"] and s1["note"].startswith("她记得")
    assert "task" not in ask_intent.parse_s1({"task": "poem"}, "x")
    assert "note" not in ask_intent.parse_s1({"note": "短"}, "x")
    und = ask_intent.understand("有一个评论很长的吵架楼 找找", [], s1=s1)
    assert und["task"] == "find" and und["note"] and und["clues"]
    assert ask_intent.understand("ai 做梦设计", [], s1={})["task"] == "synthesize"
    assert ask_intent.understand("晚上吃啥", [], s1={})["task"] == "howto"


def test_research_note_falls_back_to_fields():
    assert answer_prompt.research_note({"note": "她在设计做梦功能。"}, "q") == "她在设计做梦功能。"
    n = answer_prompt.research_note({"goal": "find", "core": "鱼露", "clues": ["瓶子是红的"]}, "q")
    assert "找回" in n and "鱼露" in n and "瓶子是红的" in n


# ---------------------------------------------------------------- 自检新指标

SRC = [{"citation": 1, "id": "a", "title": "AI伴侣做梦机制思路", "excerpts": [{"field": "body", "text": "做梦模块分三层处理：先把当天的日页面和未处理碎片整理成素材，再按语义注入场景，最后生成犯困提示。"}]},
       {"citation": 2, "id": "b", "title": "我想学会做梦", "excerpts": [{"field": "body", "text": "梦不进自动召回，只在聊到的时候浮现一次。"}]}]


def test_defense_sentences_counted_with_one_allowed_for_attribute_questions():
    md = "做梦分两类[来源1]。价格原文未披露，需自行核实。\n\n## 缺口\n没有提到成本。"
    d = answer_check.defense_check(md, question="ai 做梦设计")
    assert d["hits"] == 2 and d["gap_headings"] == 1 and d["over"]
    d2 = answer_check.defense_check("票价收藏里没写，官网查得到[来源1]。", question="这个展票价多少钱")
    assert d2["allowed"] == 1 and not d2["over"]
    c = answer_check.run(md, SRC, question="ai 做梦设计", task="synthesize")
    assert c["defense"]["over"] and any("防御性措辞" in w for w in c["warnings"])
    assert not answer_check.run("两类[来源1]。", SRC, question="x")["defense"]["over"]


def test_copy_ratio_detects_verbatim_lifting_but_ignores_quotes():
    lifted = "做梦模块分三层处理：先把当天的日页面和未处理碎片整理成素材，再按语义注入场景，最后生成犯困提示[来源1]。"
    c = answer_check.copy_check(lifted, SRC)
    assert c["ratio"] > 0.8 and c["over"]
    own = "整理型的核心是夜里把碎片合并成场景[来源1]，体验型让梦会被忘掉[来源2]。原句「梦不进自动召回，只在聊到的时候浮现一次」很有画面。"
    c2 = answer_check.copy_check(own, SRC)
    assert c2["ratio"] < 0.25 and not c2["over"]
    assert answer_check.copy_check(lifted, SRC, task="howto")["limit"] == answer_check.THRESHOLDS["copy_ratio_howto"]


def test_per_source_running_account_and_title_headings():
    by_n = {1: SRC[0], 2: SRC[1], 3: {"citation": 3, "title": "第三篇"}}
    md = "第一篇讲整理[来源1]。\n\n第二篇讲体验[来源2]。\n\n第三篇讲别的[来源3]。\n\n## 来源导读\n- [来源1]《x》— y"
    assert answer_check.per_source_check(md, by_n)["flagged"]
    md2 = "两类[来源1][来源2]。\n\n怎么选[来源1]。\n\n细节[来源2][来源3]。\n\n再说[来源3]。"
    assert not answer_check.per_source_check(md2, by_n)["flagged"]
    md3 = "## AI伴侣做梦机制思路[来源1]\n内容。"
    assert answer_check.per_source_check(md3, by_n)["title_headings"]


def test_guide_coverage_and_location_validity(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    obj = tmp_path / "_archive" / "xiaohongshu" / "abc"
    (obj / "derived").mkdir(parents=True)
    (obj / "derived" / "vision.json").write_text(json.dumps({"images": [{"asset": "raw/v0001/assets/image-001.webp", "status": "ok"},
                                                                      {"asset": "raw/v0001/assets/image-002.webp", "status": "ok"}]}), encoding="utf-8")
    srcs = [{**SRC[0], "agent_md": str(obj / "derived" / "agent.md")}, SRC[1]]
    md = "两类[来源1][来源2]。\n\n## 来源导读\n- [来源1]《AI伴侣做梦机制思路》— 最完整的整理型。必看：图1–2\n"
    g = answer_check.guide_check(md, {1: srcs[0], 2: srcs[1]}, {})
    assert g["present"] and g["missing"] == [2] and g["coverage"] == 0.5 and not g["bad_locations"]
    md2 = "两类[来源1]。\n\n## 来源导读\n- [来源1]《AI伴侣做梦机制思路》— 相关内容。必看：图7\n"
    g2 = answer_check.guide_check(md2, {1: srcs[0]}, {})
    assert g2["bad_locations"] == ["来源1 图7"] and g2["empty_phrases"] == [1] and not g2["missing"]
    c = answer_check.run("两类[来源1]。", srcs, question="x")
    assert c["guide"]["present"] is False and c["guide"]["missing"] == [1]


# ---------------------------------------------------------------- 作答流水线

def test_answer_pipeline_uses_template_strips_thought_and_attaches_guide(monkeypatch, tmp_path):
    answer = ("<想法>\n1 核心判断：交通只有一条路\n</想法>\n\n机场到市区就一条主路线，地铁最稳[来源1]。\n\n## 来源导读\n"
              "- [来源1]《交通攻略 0》— 唯一讲地铁换乘的。必看：正文「地铁」那段\n")
    seen = _setup(monkeypatch, tmp_path, answer=answer)
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "t.json"))
    calls = []
    orig = ask.call_text
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: calls.append(s) or orig(p, t, s))
    r = ask.answer("机场到市区怎么走", who="本机")
    prompt, material = seen[-1]
    assert "【本题模板：做法】" in prompt and "你是读过她这些收藏的人" in prompt
    assert "【她的原话】机场到市区怎么走" in material and "【研究笔记】" in material and "【今天】" in material
    assert "【证据】" in material and "【原始材料】" not in material
    for bad in ("缺口", "约", "尽量保留原文"):
        assert bad not in prompt.split("【本题模板")[0] or bad == "约"
    assert r["status"] == "ok" and r["task"] == "howto"
    assert r["thought"].startswith("1 核心判断") and "<想法>" not in r["markdown"] and r["markdown"].startswith("机场到市区")
    assert r["sources"][0]["guide"].startswith("[来源1]《交通攻略 0》")
    assert r["turn"]["thread_id"].startswith("th") and r["turn"]["turn_id"] == r["turn_id"] and r["turn"]["parent_turn_id"] is None
    assert r["turn"]["ordered_sources"][0]["id"] == "t0" and r["turn"]["scope"]["task"] == "howto"
    assert r["cached"] is False and "answer_cache" not in r
    # maxTokens 按任务：howto 2400（设置里 1200 不比它大）
    assert calls[-1]["textAI"]["maxTokens"] == 2400
    # 登记里带 thread / who / ordered_sources / head
    row = ask_turns.get(r["turn_id"])
    assert row["thread_id"] == r["turn"]["thread_id"] and row["who"] == "本机" and row["ordered_sources"][0]["id"] == "t0"
    assert row["head"].startswith("机场到市区")


def test_cache_hit_is_only_recorded_not_injected(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    hit = {"ts": "2026-09-10T12:00:00+08:00", "question": "机场交通", "item_ids": ["t0"], "first_line": "上次说走地铁", "match": {"method": "terms", "score": 0.7}}
    monkeypatch.setattr(ask.answer_cache, "lookup", lambda *a, **k: dict(hit))
    r = ask.answer("机场到市区怎么走")
    assert r["cached"] is True and r["answer_cache"]["match"]["method"] == "terms"
    assert "以前问过" not in seen[-1][1] and "结论可沿用" not in seen[-1][1] and "以前问过" not in r["markdown"]


def test_stored_old_default_prompt_is_not_appended_as_style(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    old = ask.ai_config.LEGACY_ANSWER_PROMPT_1017.replace("，不虚构", "")
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {"prompts": {"answer": old}}))
    ask.answer("机场到市区怎么走")
    assert "风格偏好" not in seen[-1][0]
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {"prompts": {"answer": "多用短句，少表格"}}))
    ask.answer("机场到市区怎么走")
    assert "风格偏好（和上面冲突时以上面为准）：多用短句，少表格" in seen[-1][0]


def test_parent_turn_inherits_sources_and_threads(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path, answer="答[来源1]")
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "t.json"))
    ask_turns.record("tP", {"q": "机场到市区怎么走", "mode": "direct", "ids": ["t2", "t3"], "primary_ids": ["t2"], "thread_id": "thX",
                            "ordered_sources": [{"n": 1, "id": "t2", "title": "交通攻略 2", "role": "A"}], "head": "走地铁"})
    r = ask.answer("要多久", parent_turn_id="tP")
    assert r["turn"]["parent_turn_id"] == "tP" and r["turn"]["thread_id"] == "thX" and r["thread_id"] == "thX"
    assert "机场到市区怎么走" in seen[-1][1]   # 上一问进了对话上下文
    # 继承：追问模式下上一答的主来源排前
    items = [dict(x) for x in ITEMS]
    got = ask.inherited_sources([{"role": "user", "content": "机场到市区怎么走"}], items, parent=ask_turns.get("tP"))
    assert [i["id"] for i in got] == ["t2"]
    # 没有登记：退回按上一问原词重排（不再按问题原文查全局登记）
    got2 = ask.inherited_sources([{"role": "user", "content": "甜品店蛋糕"}], items)
    assert got2 and got2[0]["id"] == "food"


def test_request_stdin_passes_thread_and_parent(monkeypatch):
    seen = {}
    monkeypatch.setattr(ask, "answer", lambda q, h, inc, **kw: seen.update(kw) or {"status": "ok", "markdown": "x"})
    monkeypatch.setattr(ask, "dump_json", lambda r: None)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"question": "要多久", "history": [], "parent_turn_id": "tP", "thread_id": "thX"})))
    ask.run(type("A", (), {"request_stdin": True})())
    assert seen["parent_turn_id"] == "tP" and seen["thread_id"] == "thX"


# ---------------------------------------------------------------- 指代解析

PARENT = {"turn_id": "tA", "thread_id": "thA", "q": "中国旅行推荐", "mode": "direct", "who": "远程·GPT",
          "ordered_sources": [{"n": 1, "id": "x1", "title": "法大本硕+LLM｜大厂法务求职", "role": "A"}, {"n": 2, "id": "x2", "title": "散心评论合集", "role": "A"}],
          "objects": [{"name": "烟台", "ns": [2]}, {"name": "宁波", "ns": [1, 2]}], "scope": {"topic": "中国旅行推荐", "task": "survey"}}


def test_resolve_ordinal_single_and_object():
    r = ask_followup.resolve("只看刚才第一篇，它怎么说的", PARENT)
    assert r["kind"] == "single" and r["source_ids"] == ["x1"] and "法大本硕" in r["question"]
    r2 = ask_followup.resolve("第2篇呢", PARENT)
    assert r2["kind"] == "single" and r2["source_ids"] == ["x2"]
    r3 = ask_followup.resolve("第二个地方怎么去", PARENT)
    assert r3["kind"] == "object" and r3["object"] == "宁波" and set(r3["source_ids"]) == {"x1", "x2"}
    assert ask_followup.resolve("第五篇", PARENT)["kind"] == "missing"
    assert ask_followup.resolve("那篇讲了什么", PARENT)["source_ids"] == ["x1"]
    assert ask_followup.resolve("只看刚才第一篇", None)["kind"] == "none"


def test_resolve_expand_drops_place_and_excludes_previous():
    r = ask_followup.resolve("那其他旅游呢", PARENT)
    assert r["kind"] == "expand" and r["exclude_ids"] == ["x1", "x2"] and r["avoid"] == ["烟台", "宁波"]
    assert "中国" not in r["question"] and "旅游" in r["question"] and "中国以外" in r["note"]
    r2 = ask_followup.resolve("还有别的吗", {**PARENT, "scope": {"topic": "晚上吃啥"}})
    assert r2["kind"] == "expand" and r2["question"] == "晚上吃啥" and "上次没提的" in r2["note"]


def test_resolve_switch_and_deictic_detection():
    assert ask_followup.resolve("那东京的呢", PARENT)["kind"] == "switch"
    assert ask_followup.resolve("那东京的呢", PARENT)["switch_to"] == "东京"
    assert ask_followup.is_deictic("只看刚才第一篇") and ask_followup.is_deictic("那其他旅游呢") and not ask_followup.is_deictic("悉尼旅行推荐")
    assert ask_followup.is_followup("那其他旅游呢") and not ask_followup.is_followup("之前存的那个火锅粉")


def test_objects_from_table_and_bold_items():
    md = ("| 方案 | 用途 |\n|---|---|\n| Lucie Dream[来源1] | 整理 |\n| 池又雨[来源2] | 经历 |\n\n"
          "- **梦要不要能被忘掉**：池又雨[来源2]\n### 悉尼 Bondi[来源3]\n\n## 来源导读\n- [来源1]《x》— y")
    objs = ask_followup.objects_from(md)
    assert [o["name"] for o in objs] == ["Lucie Dream", "池又雨", "梦要不要能被忘掉", "悉尼 Bondi"]
    assert objs[0]["ns"] == [1] and objs[3]["ns"] == [3]


def test_bind_parent_fallback_same_who_within_15_minutes(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "t.json"))
    ask_turns.record("t1", {"q": "LLM 法务面试", "who": "远程·GPT", "thread_id": "th1"})
    ask_turns.record("t2", {"q": "别人的问题", "who": "远程·别人", "thread_id": "th2"})
    row, how = ask_followup.bind_parent("只看刚才第一篇", who="远程·GPT")
    assert how == "fallback" and row["turn_id"] == "t1"
    assert ask_followup.bind_parent("只看刚才第一篇", who="远程·没问过")[1] == "none"
    assert ask_followup.bind_parent("悉尼旅行推荐", who="远程·GPT")[1] == "none"   # 不是追问不绑
    assert ask_followup.bind_parent("x", thread_id="th2")[0]["turn_id"] == "t2"
    assert ask_followup.bind_parent("x", parent_turn_id="t1")[1] == "parent"
    late = datetime.now().astimezone() + timedelta(minutes=16)
    assert ask_turns.latest_for_who("远程·GPT", now=late) is None
    assert ask_turns.latest_for_who("远程·GPT", now=late, within_s=3600)["turn_id"] == "t1"


def test_parent_from_context_resolves_ids():
    items = [{"id": "xhs-abc123", "title": "甲"}, {"id": "xhs-def456", "title": "乙"}]
    p = ask_followup.parent_from_context({"previous_question": "法务面试", "source_ids": ["abc123", "xhs-def456", "zzz"]}, items)
    assert [o["id"] for o in p["ordered_sources"]] == ["xhs-abc123", "xhs-def456"] and p["q"] == "法务面试"
    assert ask_followup.parent_from_context({}, items) is None


# ---------------------------------------------------------------- MCP ask

def _ctx(tmp_path, local=False):
    return mt.Ctx(policy=Policy.build(tmp_path, ["@xhs"]), local=local, who="远程·GPT")


def test_mcp_ask_with_thread_id_locks_first_source(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "t.json"))
    ask_turns.record("tA", {k: v for k, v in PARENT.items() if k != "turn_id"})
    seen = {}

    def fake(q, **kw):
        seen.update(kw, question=q)
        # 样本路径用 tmp_path 拼（原来写死 D:\…，Linux 上 Path 取不出文件名，整条只能在 Windows 跑）
        return {"status": "ok", "markdown": "答[来源1]", "sources": [{"citation": 1, "id": "x1", "agent_md": str(tmp_path / "abs" / "agent.md"), "attachments": [{"file": str(tmp_path / "abs" / "a.pdf")}]}],
                "related": [], "turn_id": "tB", "thread_id": "thA", "images": [], "delivery": {}, "history": []}
    monkeypatch.setattr(ask, "answer", fake)
    r = mt.ask(_ctx(tmp_path), {"question": "只看刚才第一篇，它怎么说的", "thread_id": "thA"})
    assert seen["source_ids"] == ["x1"] and seen["parent_turn_id"] == "tA" and seen["thread_id"] == "thA" and seen["who"] == "远程·GPT"
    assert seen["history"][0]["content"] == "中国旅行推荐"
    assert r["followup"] == {"bound": "thread", "kind": "single", "parent_turn_id": "tA", "question": seen["question"]}
    # 远程：剥本机路径、附件只留名字、不带 delivery / history
    assert "agent_md" not in r["sources"][0] and r["sources"][0]["attachments"] == [{"name": "a.pdf"}]
    assert "delivery" not in r and "history" not in r
    assert not r["markdown"].startswith("（接着上一问")   # 带 thread_id 的不写兜底提示


def test_mcp_ask_expand_excludes_previous_and_fallback_binding_marks_lead(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "t.json"))
    ask_turns.record("tA", {k: v for k, v in PARENT.items() if k != "turn_id"})
    seen = {}
    monkeypatch.setattr(ask, "answer", lambda q, **kw: seen.update(kw, question=q) or {"status": "ok", "markdown": "新地方[来源1]", "sources": [], "related": []})
    r = mt.ask(_ctx(tmp_path), {"question": "那其他旅游呢"})   # 没带 thread_id：同凭据 15 分钟内兜底
    assert seen["exclude_ids"] == ["x1", "x2"] and seen["avoid"] == ["烟台", "宁波"] and "中国" not in seen["question"]
    assert r["markdown"].startswith("（接着上一问「中国旅行推荐」） 按「中国以外、上次没提的」来") and r["followup"]["bound"] == "fallback"
    # 换一个凭据问同样的话：绑不到，而且是指代型 → 不检索
    calls = []
    monkeypatch.setattr(ask, "answer", lambda q, **kw: calls.append(q) or {"status": "ok"})
    r2 = mt.ask(mt.Ctx(policy=Policy.build(tmp_path, ["@xhs"]), local=False, who="远程·别人"), {"question": "只看刚才第一篇"})
    assert r2["needs_context"] and r2["markdown"].startswith("找不到上一轮") and calls == []
    # 不是指代型的新问题：照常问
    r3 = mt.ask(mt.Ctx(policy=Policy.build(tmp_path, ["@xhs"]), local=False, who="远程·别人"), {"question": "悉尼旅行推荐"})
    assert calls == ["悉尼旅行推荐"]


def test_mcp_ask_context_without_state(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "t.json"))
    monkeypatch.setattr(mt, "_items", lambda: [{"id": "xhs-aaa", "title": "法大本硕"}, {"id": "xhs-bbb", "title": "英硕"}])
    seen = {}
    monkeypatch.setattr(ask, "answer", lambda q, **kw: seen.update(kw) or {"status": "ok", "markdown": "x", "sources": [], "related": []})
    mt.ask(_ctx(tmp_path), {"question": "第二篇怎么说", "context": {"previous_question": "LLM 法务面试", "source_ids": ["xhs-aaa", "xhs-bbb"]}})
    assert seen["source_ids"] == ["xhs-bbb"] and seen["history"][0]["content"] == "LLM 法务面试"


def test_remote_shape_rewrites_images_and_local_keeps_paths(tmp_path):
    res = {"markdown": "看图\n![[_archive/x/raw/v0001/assets/image-002.webp|360]]\n完", "images": [{"n": 1, "image_no": 2, "asset": "_archive/x/raw/v0001/assets/image-002.webp"}],
           "sources": [{"citation": 1, "agent_md": "D:\\\\a", "markdown_path": "D:\\\\b"}], "related": [], "delivery": {"body": "x"}}
    remote = mt._remote_shape(_ctx(tmp_path), dict(res))
    assert "（图：来源1 图2）" in remote["markdown"] and "![[" not in remote["markdown"] and remote["images"]
    assert "markdown_path" not in remote["sources"][0] and "delivery" not in remote
    assert mt._remote_shape(_ctx(tmp_path, local=True), dict(res))["sources"][0]["agent_md"] == "D:\\\\a"
    assert ask.remote_images("![[_archive/unknown.webp|360]]", []) == ""


def test_ask_schema_accepts_thread_and_context():
    tool = next(t for t in mt.TOOLS if t["name"] == "ask")
    props = tool["inputSchema"]["properties"]
    assert "thread_id" in props and "context" in props and "thread_id" in tool["description"]
    assert tool["inputSchema"]["additionalProperties"] is False
