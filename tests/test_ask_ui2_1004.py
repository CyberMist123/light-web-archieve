"""10-04 问收藏第二批（车 C）后端：称呼规则 + 作者昵称进材料、手动加入的来源重答时真用上、「我保存的」作为附加来源进召回。

全部合成数据，不调模型（call_text 打桩，只看送进去的提示词和材料）。"""
import json

from link_brain import ask, saved_sources, storage

ITEMS = [{"id": f"t{i}", "title": f"交通攻略 {i}", "tags": [], "summary": "", "note": f"t{i}.md", "url": "",
          "author": f"旅人{i}", "search_fields": {"body": f"机场到市区的交通路线 {i}，地铁和巴士。"}} for i in range(4)]
ITEMS.append({"id": "food", "title": "甜品店", "tags": [], "summary": "", "note": "food.md", "url": "", "author": "",
              "search_fields": {"body": "这家蛋糕很好吃。"}})


def _setup(monkeypatch, tmp_path, entries=None, answer="答[来源1]"):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    (tmp_path / "_archive").mkdir(exist_ok=True)
    if entries is not None:
        (tmp_path / "_archive" / "chat-archive.json").write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    monkeypatch.setattr(ask, "llm_expansions", lambda *a, **k: {"terms": [], "status": "mock"})
    monkeypatch.setattr("link_brain.retrieval.semantic_hits", lambda *a: None)
    monkeypatch.setattr(ask.answer_cache, "record", lambda *a, **k: None)
    monkeypatch.setattr(ask.answer_cache, "lookup", lambda *a, **k: None)
    monkeypatch.setattr(ask.answer_cache, "question_vector", lambda *a, **k: None)
    seen = []
    monkeypatch.setattr(ask, "call_text", lambda p, text, s: seen.append((p, text)) or {"status": "ok", "text": answer})
    return seen


# ── 1. 回答里别写「作者说」：提示词明说称呼规则，材料里带具体昵称（没有昵称不写，不编） ──

def test_prompt_forbids_generic_author_said_and_material_carries_nickname(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    ask.answer("交通路线")
    prompt, material = seen[-1]
    # 1018 v2.1：称呼规则并进 answer_prompt.CORE_RULES 第 6 条（评论者的话不能安到作者头上；只在身份要紧时点名）
    assert "评论者的话不能安到作者头上" in prompt and "评论区·某某" in prompt
    assert "作者：旅人0" in material
    assert "作者原话" not in material and "区分作者说法" not in material
    # 没昵称的那篇不写「作者：」行，也不写「未提供昵称」
    header = ask.source_header(1, ITEMS[-1])
    assert header == "[来源1] 甜品店\n" and "作者" not in header


def test_default_prompt_stored_in_settings_is_not_appended_twice(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(
        ask.ai_config.DEFAULTS, {"prompts": {"answer": ask.ai_config.DEFAULT_ANSWER_PROMPT}}))
    ask.answer("交通路线")
    assert "用户的回答风格偏好" not in seen[-1][0]


# ── 2. 手动加入的来源：重答 / 追问时排最前、拿够证据、提示词逐条点名，回答没引用到就在末尾如实列出 ──

def test_pinned_source_used_first_in_reask_with_explicit_citation_rule(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path, answer="只说交通[来源2]")
    # 页面「按剩下的重新回答」：sourceIds = 留下的；pinIds = 她手动加入（保留 / 提上来）的
    r = ask.answer("交通路线", source_ids=["t0", "t1"], pin_ids=["food"])
    primary = [s["id"] for s in r["sources"]]
    assert primary[0] == "food" and set(primary) == {"food", "t0", "t1"}
    material = seen[-1][1]
    assert "[来源1] 是用户手动加入的来源" in material and "必须逐条用到" in material
    assert "这家蛋糕很好吃" in material
    # 模型没引用 [来源1]：回答末尾如实列出
    assert r["markdown"].endswith("> 你手动加入的来源这次回答没有引用到：[来源1] 甜品店")


def test_pinned_sources_cited_leave_no_footer(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, answer="甜品[来源1]，交通[来源2]")
    r = ask.answer("交通路线", pin_ids=["food"])
    assert r["sources"][0]["id"] == "food" and "没有引用到" not in r["markdown"]


def test_many_pins_all_get_into_primary_with_budget(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(
        ask.ai_config.DEFAULTS, {"retrieval": {"totalCharLimit": 500, "topK": 1}}))
    r = ask.answer("交通路线", pin_ids=["food", "t3", "t2"])
    assert [s["id"] for s in r["sources"]][:3] == ["food", "t3", "t2"]
    assert "[来源1]、[来源2]、[来源3] 是用户手动加入的来源" in seen[-1][1]


def test_uncited_note_helper():
    srcs = [{"citation": 2, "title": "甲"}, {"citation": 4, "title": "乙"}]
    assert ask.uncited_pins_note("见[来源2]", srcs) == "\n\n> 你手动加入的来源这次回答没有引用到：[来源4] 乙"
    assert ask.uncited_pins_note("[来源2][来源4]", srcs) == ""


# ── 7. 「我保存的」进召回：短文本也能中，字段身份 saved，和收藏笔记区分 ──

def test_short_saved_note_is_found_by_short_questions(monkeypatch, tmp_path):
    entries = [{"id": "n1", "ts": "2026-10-04T10:00:00+10:00", "kind": "note", "title": "", "content": "做梦是1"},
               {"id": "r1", "ts": "2026-10-03T10:00:00+10:00", "kind": "report", "title": "交通怎么走", "content": "坐地铁最快[来源1]。"}]
    seen = _setup(monkeypatch, tmp_path, entries)
    for q in ("做梦", "做梦是"):
        r = ask.answer(q)
        first = r["sources"][0]
        assert first["id"] == "saved:n1" and first["source_kind"] == "saved" and first["saved_kind"] == "note"
        assert first["excerpts"][0]["field"] == "saved" and "做梦是1" in first["excerpts"][0]["text"]
        assert "类型：我保存的（用户自己写的判断）" in seen[-1][1]


def test_saved_report_joins_but_notes_still_come(monkeypatch, tmp_path):
    entries = [{"id": "r1", "ts": "x", "kind": "report", "title": "交通路线怎么走", "content": "坐地铁最快。"}]
    _setup(monkeypatch, tmp_path, entries)
    r = ask.answer("交通路线")
    ids = [s["id"] for s in r["sources"]]
    # 1015 第三批 R1：收藏笔记照样进来源（篇数由选篇规则定，直接答最多 SELECT_MAX 篇），「我保存的」排最前不占名额
    notes = [i for i in ids if not i.startswith("saved:")]
    assert ids[0] == "saved:r1" and notes and set(notes) <= {"t0", "t1", "t2", "t3"}


def test_saved_respects_exclusion_and_pin(monkeypatch, tmp_path):
    entries = [{"id": "n1", "ts": "x", "kind": "note", "title": "", "content": "做梦是1"}]
    _setup(monkeypatch, tmp_path, entries)
    r = ask.answer("做梦", exclude_ids=["saved:n1"])
    assert all(s["id"] != "saved:n1" for s in r.get("sources", []) + r.get("related", []))
    # 保留的「我保存的」在重答里也解析得到
    r = ask.answer("交通路线", source_ids=["t0"], pin_ids=["saved:n1"])
    assert r["sources"][0]["id"] == "saved:n1"


def test_saved_sources_fail_open_and_strength(monkeypatch, tmp_path):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    assert saved_sources.load() == []           # 没有文件
    (tmp_path / "_archive").mkdir()
    (tmp_path / "_archive" / "chat-archive.json").write_text("{坏的", encoding="utf-8")
    assert saved_sources.load() == []           # 坏文件
    note = saved_sources._item({"id": "a", "kind": "note", "content": "做梦是1"})
    assert saved_sources.strength("做梦", note, ["做梦"]) == 2
    assert saved_sources.strength("做梦是什么意思", note, ["做梦", "做梦是", "意思"]) == 2
    assert saved_sources.strength("东京美食", note, ["东京", "美食"]) == 0
    assert saved_sources._item({"id": "b", "content": "  "}) is None
    merged = saved_sources.merge("做梦", [{"id": "x"}], [note], ["做梦"], after=0)
    assert [m["id"] for m in merged] == ["saved:a", "x"]
