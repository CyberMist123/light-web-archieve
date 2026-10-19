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


def test_report_mode_reads_tentative_sources_too(monkeypatch):
    """1020 她：报告版比普通回答薄（只读了 3 篇）。报告模式把判定「沾边」的篇也送读（上限同 SELECT_HARD_MAX），普通回答不变。"""
    items = [{"id": str(i), "title": f"播客清单 {i}", "tags": [], "summary": "", "note": f"{i}.md", "url": "",
              "search_fields": {"body": f"推荐播客 {i}：节目甲、节目乙。"}} for i in range(8)]
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in items])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))

    def model(prompt, text, settings):
        if "deep_read" in prompt:
            return {"status": "ok", "text": "\n".join(["1|deep_read|正题"] + [f"{k}|tentative|沾边" for k in range(2, 6)])}
        return {"status": "ok", "text": "# 清单\n## 类\n- **节目甲** —— 帖里：a[来源1]"}
    monkeypatch.setattr(ask, "call_text", model)
    normal = ask.answer("推荐播客", mode="direct")
    report = ask.answer("/报告 推荐播客")
    assert len([s for s in normal["sources"] if s.get("tier") != "also"]) == 3   # deep 1 + 沾边 2（原规则）
    assert len([s for s in report["sources"] if s.get("tier") != "also"]) == 5   # deep 1 + 沾边 4


def test_board_images_map_post_and_comment_images(tmp_path):
    """1020 她：问游戏的报告没把评论区的图放进去。报告里 [看图：来源N 评论cX的图N] / [看图：来源N 图M] → 同一行里的 ![[路径|配图]]
    （不换行，否则会把陈列那一行切断）；评论区的图按证据片段 images ↔ assets 对应找文件，对不上的删掉。"""
    from link_brain import storage
    obj = storage.vault_root() / "_archive" / "xiaohongshu" / "abc"
    (obj / "raw" / "v0001" / "assets").mkdir(parents=True)
    (obj / "derived").mkdir(parents=True)
    (obj / "raw" / "v0001" / "assets" / "comment-c9-001.webp").write_bytes(b"x")
    (obj / "raw" / "v0001" / "assets" / "image-002.webp").write_bytes(b"x")
    (obj / "derived" / "vision.json").write_text('{"images": [{"asset": "raw/v0001/assets/image-002.webp"}]}', encoding="utf-8")
    src = {"citation": 1, "id": "xhs-abc", "agent_md": str(obj / "derived" / "agent.md"),
           "excerpts": [{"field": "comment_ocr", "images": ["评论c3的图1"], "assets": ["raw/v0001/assets/comment-c9-001.webp"]}]}
    md = ("- **欧卡2** —— 帖里：评论区晒了截图 [看图：来源1 评论c3的图1][来源1]\n"
          "- **光遇** —— 帖里：正文第二张图 [看图：来源1 图2][来源1]\n"
          "- **编的** —— 帖里：不存在的图 [看图：来源1 评论c8的图4][来源1]")
    out = ask.board_images(md, [src])
    lines = out.splitlines()
    assert len(lines) == 3, "不换行"
    assert "![[_archive/xiaohongshu/abc/raw/v0001/assets/comment-c9-001.webp|配图]]" in lines[0]
    assert "![[_archive/xiaohongshu/abc/raw/v0001/assets/image-002.webp|配图]]" in lines[1]
    assert "看图" not in lines[2] and "![[" not in lines[2], "对不上材料的图删掉"


def test_split_ocr_by_image_labels_each_picture():
    """1020：报告要按图配图——一段跨几张图的「图片文字」片段，按 agent.md 每张图的识别文字拆成一张一段、各标各的图号。"""
    from link_brain import storage
    obj = storage.vault_root() / "_archive" / "xiaohongshu" / "pod"
    (obj / "derived").mkdir(parents=True)
    (obj / "derived" / "agent.md").write_text(
        "# 播客\n\n## 图片 OCR\n\n### 第1张（图1 · image-001.webp）\n\n封面字\n\n"
        "### 第2张（图2 · image-002.webp）\n\n剧谈社：艺术硬核解读\n纵横四海：拆书\n\n## 评论\n\n- [c1] 甲：好\n", encoding="utf-8")
    item = {"agent_md": "_archive/xiaohongshu/pod/derived/agent.md"}
    snippets = [{"field": "body", "text": "正文"},
                {"field": "ocr", "images": ["图1", "图2"], "assets": ["raw/v0001/assets/image-001.webp", "raw/v0001/assets/image-002.webp"], "text": "封面字 剧谈社 纵横四海" * 20}]
    out = ask.split_ocr_by_image(item, snippets)
    assert [x.get("images") for x in out] == [None, ["图1"], ["图2"]]
    assert out[2]["assets"] == ["raw/v0001/assets/image-002.webp"]
    assert "剧谈社" in out[2]["text"] and "纵横四海" in out[2]["text"] and "评论" not in out[2]["text"]
    assert ask.split_ocr_by_image({"agent_md": "nope/agent.md"}, snippets) == snippets   # 读不到 = 原样
