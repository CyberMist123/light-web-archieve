"""1020 问收藏陈列版（技能 layout: board）后端：技能字段、陈列格式块只给 board 技能、网址只认材料里逐字出现的。离线、不调模型。"""
from __future__ import annotations

from link_brain import ask, skills


def test_builtin_report_skills_use_board_layout():
    by_id = {s["id"]: s for s in skills.load_all()[0]}
    assert {sid for sid, s in by_id.items() if s.get("layout") == "board"} == {"wiki", "board", "travel"}
    assert by_id["research"].get("layout") is None   # 调研对比是「对象 × 维度」表格，不做陈列
    assert by_id["general"].get("layout") is None


def test_layout_field_is_whitelisted():
    md = "---\nname: mine\ndescription: 我的\nlwa:\n  layout: {}\n---\n正文"
    assert skills.parse(md.format("board"))["layout"] == "board"
    assert skills.parse(md.format("html-page"))["layout"] is None   # 不认识的版式当没写


def test_board_format_block_only_when_report_switch_and_board_skill():
    by_id = {s["id"]: s for s in skills.load_all()[0]}
    assert "【陈列格式】" in skills.prompt_block(by_id["wiki"], board=True)
    assert "【陈列格式】" not in skills.prompt_block(by_id["wiki"])          # 1020：没开「报告」开关，wiki 照常回答
    assert "【陈列格式】" not in skills.prompt_block(by_id["recipe"], board=True)
    assert skills.prompt_block(by_id["general"], board=True) == ""


def test_research_skill_no_longer_claims_deep_report():
    """1020 她：问题里写「深度报告」被路由成调研对比，出了表格 + 大段文字。报告改由页面开关触发。"""
    r = {s["id"]: s for s in skills.load_all()[0]}["research"]
    assert "深度报告" not in r["description"] and "深度报告" not in r["aliases"]


def test_report_mark_forces_board_layout_with_wiki_skill(monkeypatch):
    """页面「报告」开关 → 问题前加 /报告：后端去掉标记、技能不是陈列型就换 wiki、作答附陈列格式、响应带 layout=board、直接答不出目录。"""
    items = [{"id": str(i), "title": f"项目 {i}", "tags": [], "summary": "", "note": f"{i}.md", "url": "",
              "search_fields": {"body": f"多agent群聊项目 {i} 的说明。"}} for i in range(6)]
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in items])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {"retrieval": {"judgeSelect": False}}))
    seen = []

    def model(prompt, text, settings):
        seen.append((prompt, text))
        return {"status": "ok", "text": "# 清单\n## 框架\n- **项目 1** · 看原帖 —— 帖里：a；借鉴：b[来源1]"}
    monkeypatch.setattr(ask, "call_text", model)
    r = ask.answer("/报告 多agent群聊项目", mode=None)
    assert r["status"] == "ok" and r.get("layout") == "board" and r["mode"] == "direct"
    assert any("【陈列格式】" in p for p, _ in seen)
    assert not any("/报告" in t for _, t in seen), "标记不进模型"
    r2 = ask.answer("多agent群聊项目", mode="direct")
    assert "layout" not in r2


def test_unseen_links_keep_only_links_in_evidence():
    ev = "官网 https://raven.dev/docs ，评论区补了 github.com/foo/bar"
    md = ("- **Raven** · https://raven.dev/docs/ —— 帖里：x[来源1]\n"
          "- **Bar** · https://github.com/foo/bar —— y\n"
          "- **Fake** · https://fake.example.com/x —— z\n"
          "- 见[官网](https://made.up/page)")
    out = ask.unseen_links(md, ev)
    assert "https://raven.dev/docs/" in out and "https://github.com/foo/bar" in out
    assert "fake.example.com" not in out and "**Fake** · 看原帖" in out
    assert "made.up" not in out and "官网（看原帖）" in out


def test_unseen_links_checks_bare_domains_in_board_rows():
    ev = "仓库地址 github.com/CyberSealNull/CcCompanion ，官网 Minimal.Gallery"
    md = ("- **CcC** · github.com/CyberSealNull/CcCompanion —— 帖里：a\n"
          "- **Gallery** · minimal.gallery —— 帖里：b\n"
          "- **Pin** · pinterest.com —— 帖里：c")
    out = ask.unseen_links(md, ev)
    assert "· github.com/CyberSealNull/CcCompanion ——" in out and "· minimal.gallery ——" in out
    assert "**Pin** · 看原帖 ——" in out
