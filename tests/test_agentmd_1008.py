"""10-08 批次 B：机读版 agent.md 精简。合成数据，不读真库、不联网。"""
from __future__ import annotations

from pathlib import Path

from link_brain import agentmd, ask, render, screentext, visual

BIN = "000110010101101100 0100001100001"


def _img(n, ocr, desc="", kind="picture", **extra):
    image = {"asset": f"raw/v0001/assets/image-{n:03d}.webp", "status": "ok", "ocr": ocr,
             "visual": {"status": "ok", "kind": kind, "text": desc, "v": 3, "shaky": ""} if desc else {}}
    image.update(extra)
    return image


def _render(source=None, vision=None, meta=None, extracted=None):
    source = source or {}
    source.setdefault("note", {}).setdefault("title", "合成标题")
    return render.render_agent_md(source=source, vision=vision or {"images": []},
                                  meta=meta if meta is not None else {"item_id": "xhs-t", "source_id": "t", "current_version": 1},
                                  extracted=extracted)


def _comment(cid, text, nick="路人", uid="u-x", subs=None):
    return {"comment_id": cid, "text": text, "author": {"nickname": nick, "user_id": uid}, "sub_comments": subs or []}


# ---------------------------------------------------------------- 规则 1：原图路径不逐图写


def test_origin_written_once_and_only_shaky_images_get_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    images = [_img(i, f"第{i}张图上的字") for i in range(1, 6)]
    images[2]["visual"] = {"status": "failed", "kind": "picture", "text": "", "error": "超时"}
    text = _render(vision={"images": images})
    assert text.count("原图在 `_archive/xiaohongshu/t/raw/v0001/assets/`") == 1
    assert "read_asset" in text and "细节以原图为准" not in text
    assert text.count("raw/v0001/assets/image-") == 1                      # 只有没把握的图3单独给了路径
    assert "原图：_archive/xiaohongshu/t/raw/v0001/assets/image-003.webp" in text


# ---------------------------------------------------------------- 规则 2：OCR 清洗


def test_ocr_drops_binary_watermark_and_junk_but_keeps_two_char_words():
    ocr = lambda q, a: f"@作者水印\n{BIN}\n1100013100131\n栏目名\n{q}\n88\n」 L 十 + +\n{a}\n(OCR 行数 6，均信心 0.99)"
    images = [_img(1, ocr("见家长怎么介绍自己", "网恋")), _img(2, ocr("靠什么生活", "吃软饭")),
              _img(3, ocr("家庭地位如何", "你说呢")), _img(4, "只有这一张没水印")]
    text = _render(vision={"images": images})
    assert "每张图都带：@作者水印、栏目名" in text
    assert text.count("@作者水印") == 1 and text.count("栏目名") == 1
    assert "0001100" not in text and "1100013100131" not in text and "88" not in text and "」 L" not in text
    assert "### 第1张（图1 · image-001.webp）\n\n图上文字：\n\n见家长怎么介绍自己\n网恋\n" in text   # 两个汉字的词不当乱码
    assert "### 第4张（图4 · image-004.webp）\n\n图上文字：\n\n只有这一张没水印" in text


def test_junk_line_rules():
    assert agentmd.junk_line(BIN) and agentmd.junk_line("88") and agentmd.junk_line("23:34")
    assert agentmd.junk_line("口") and agentmd.junk_line("× +")
    assert not agentmd.junk_line("网恋") and not agentmd.junk_line("AI从业者") and not agentmd.junk_line("¥39.9元")


# ---------------------------------------------------------------- 规则 3：OCR 与识图描述去重


def test_description_drops_ocr_overlap_and_repeats_and_is_capped():
    ocr = "见家长怎么介绍自己\n世界首富之子"
    d1 = ("这是一张上下两格的访谈插画，主体是穿西装的黑色球头角色。图中文字包括“见家长怎么介绍自己”和“世界首富之子”。\n"
          "图内文字转录如下：\n上半部分：见家长怎么介绍自己\n下半部分：世界首富之子")
    d2 = "这是一张上下两格的访谈插画，主体是穿西装的黑色球头角色。图中文字包括“靠什么生活”。"
    d3 = "一张很长的描述" * 30
    images = [_img(1, ocr, d1), _img(2, "靠什么生活", d2), _img(3, "第三张的字", d3)]
    text = _render(vision={"images": images})
    assert "文字转录如下" not in text and "图中文字包括" not in text and "上半部分" not in text
    assert "描述：这是一张上下两格的访谈插画" in text
    assert "描述：同第1张" in text
    line3 = next(x for x in text.splitlines() if "一张很长的描述" in x)
    assert line3 == "描述：" + d3                                         # 没句号的长描述整句保留，不截半句


# ---------------------------------------------------------------- 规则 4：评论精选，楼号不变


def test_comments_filtered_capped_and_labels_unchanged():
    author = "u-author"
    comments = [
        _comment("a1", "哈哈哈哈[doge]"),                                                      # c1 水话
        _comment("a2", "这个配方里盐放多少克？", subs=[_comment("b1", "不够[完啦R]"),            # c2.1 水话
                                                     _comment("b2", "大概五克就够了", "作者", author)]),  # c2.2 作者回复
        _comment("a3", "我觉得第三步可以换成小火慢炖", subs=[_comment("b3", "笑死"), _comment("b4", "同意，小火更入味")]),
        _comment("a4", "看图", subs=[]),                                                     # c4 带图片文字
        _comment("a5", "这是广告位招租联系我"),                                                  # c5 小模型标噪音
        _comment("a6", "看看这个"),                                                           # c6 评论图只有表情、无文字
    ]
    vision = {"images": [
        {"asset": "raw/v0001/assets/comment-a4-001.webp", "status": "ok", "ocr": "步骤一：先焯水\n步骤二：再炖煮",
         "visual": {"status": "ok", "kind": "picture", "text": "一张截图，写着步骤", "v": 3}},
        {"asset": "raw/v0001/assets/comment-a6-001.webp", "status": "ok", "ocr": "",
         "visual": {"status": "ok", "kind": "picture", "text": "一只猫的表情包", "v": 3}},
    ]}
    text = _render(source={"note": {"title": "t", "author": {"nickname": "作者", "user_id": author}}, "comments": comments},
                   vision=vision, extracted={"valuable_comments": [{"id": "c3.2", "why": "实操"}], "ads_or_noise": ["c5"]})
    body = text.split("## 评论", 1)[1]
    assert "[c1]" not in body and "[c2.1]" not in body and "[c3.1]" not in body and "[c5]" not in body
    assert "- [c2] 路人：这个配方里盐放多少克？" in body
    assert "  - [c2.2] 作者（作者）：大概五克就够了" in body
    assert "- [c3] 路人：我觉得第三步可以换成小火慢炖" in body              # 楼中楼被选中，楼主那句带上
    assert "  - [c3.2] 路人：同意，小火更入味（值得看：实操）" in body      # c3.1 略去，c3.2 不让号
    assert "- [c4] 路人：看图" in body and "评论图1 comment-a4-001.webp：步骤一：先焯水 / 步骤二：再炖煮" in body
    assert "写着步骤" not in body and "猫" not in body                     # 识图描述 / 表情包都不要
    assert "（无文字）" not in text
    assert "另有" in body and "条评论略去" in body


def test_comment_cap_30_and_omitted_count():
    comments = [_comment(f"x{i}", f"第{i}条有内容的评论，说点具体的事情") for i in range(1, 41)]
    text = _render(source={"note": {"title": "t"}, "comments": comments})
    assert "[c30]" in text and "[c31]" not in text and "[c40]" not in text
    assert "（另有 10 条评论略去：超出上限 10 条）" in text


def test_chatter_detection():
    for t in ("哈哈哈哈[doge]", "不够[完啦R]", "笑死", "@某人", "", "好机！！", "[笑哭R][笑哭R]"):
        assert agentmd.chatter(t), t
    for t in ("我不得劲", "大概五克就够了", "求问在哪里买的"):
        assert not agentmd.chatter(t), t


# ---------------------------------------------------------------- 规则 5 / 6：元数据合并、外链去重、空节省略


def test_meta_line_links_and_empty_sections():
    note = {"title": "t", "body": "正文第一句。", "author": {"nickname": "某作者"}, "published_at": "2026-07-05T00:42:00+10:00",
            "engagement": {"liked": 7, "collected": 3, "comment_count": 2, "shared": None},
            "links": [{"url": "http://example.com/a", "where": "comment:cc1"}, {"url": "http://example.com/a", "where": "body"}]}
    text = _render(source={"note": note, "comments": [_comment("cc1", "链接在这 http://example.com/a")]},
                   meta={"item_id": "xhs-t", "source_id": "t", "current_version": 2, "canonical_url": "https://example.com/explore/t"},
                   extracted={"summary": "这篇讲了怎么用某工具整理收藏。", "key_points": ["怎么用某工具整理收藏", "另一个要点"],
                              "links_worth_opening": [{"url": "https://example.com/a", "why": "原帖链接"},
                                                      {"url": "", "hint": "某个仓库名", "why": "提到过"}]})
    lines = text.splitlines()
    assert lines[2] == "来源 https://example.com/explore/t · 作者 某作者 · 发布 2026-07-05 · 赞 7 / 藏 3 / 评 2 · v2"
    for gone in ("## 数据点", "## 元信息", "None", "item_id", "（未生成）", "## 图片 OCR", "某个仓库名"):
        assert gone not in text, gone
    assert text.count("example.com/a)") == 1
    assert "- [example.com/a](http://example.com/a)（评论 c1） — 小模型建议：原帖链接" in lines
    assert "- 怎么用某工具整理收藏" not in lines and "- 另一个要点" in lines   # 和概要重复的要点不写


def test_all_empty_gives_title_only():
    text = _render(source={"note": {"title": "空"}}, meta={})
    assert text == "# 空\n"


# ---------------------------------------------------------------- 规则 7：视频


def test_screentext_keeps_lines_and_dedupes_against_all_kept(monkeypatch, tmp_path):
    frames = [["第一页标题", "某博主"], ["第二页内容", "某博主", "88"], ["第一页标题", "某博主"], ["第二页内容。", "第三页新东西"]]

    def fake_ffmpeg(cmd, **kw):
        out = Path(cmd[-1]).parent
        for i in range(len(frames)):
            (out / f"f{i + 1:04d}.jpg").write_bytes(b"x")
    monkeypatch.setattr(screentext.subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(visual, "available", lambda: True)
    monkeypatch.setattr(visual, "local_ocr", lambda p: {"lines": [{"text": t, "score": 0.9} for t in frames[int(p.stem[1:]) - 1]]})
    result = screentext.extract(tmp_path / "v.mp4")
    assert result["v"] == 2
    assert [(s["t"], s["text"]) for s in result["segments"]] == [(0, "第一页标题\n某博主"), (2, "第二页内容"), (6, "第三页新东西")]


def test_video_transcript_and_screen_rules():
    transcript = "we we need to it's also it's also fine. " + "".join(
        "这是第3句很长的口播内容。" if i == 3 else "".join(chr(0x4e00 + (i * 211 + j * 37) % 5000) for j in range(30)) + "。"
        for i in range(120))   # 每句字都不一样，不被查重吃掉
    screen = "\n".join(["这是第3句很长的口播内容","」 L 十 + +","画面上独有的字幕一"] + ["".join(chr(0x5000 + (i * 389 + j * 53) % 4000) for j in range(80)) for i in range(30)])
    text = _render(source={"note": {"title": "t", "transcript": transcript, "screen_text": screen, "screen_v": 2}})
    stt = text.split("## 视频文字稿", 1)[1].split("## 视频画面文字", 1)[0]
    assert "we need to it's also fine." in stt and "we we" not in stt
    paras = [p for p in stt.strip().split("\n\n") if p.strip()]
    assert len(paras) > 1 and all(len(p) <= agentmd.PARAGRAPH + 60 for p in paras)
    scr = text.split("## 视频画面文字", 1)[1]
    assert "这是第3句很长的口播内容" not in scr                         # 转写里已有
    assert "」 L" not in scr
    assert "（已截断，共 31 段）" in scr
    assert sum(len(x) for x in scr.strip().splitlines()[:-1]) <= agentmd.SCREEN_LIMIT


def test_legacy_screen_text_split_by_space():
    old = "小红书 某博主 第一页\n小红书 某博主 第一页 新增一行字"
    assert agentmd.screen_units(old, "", legacy=True) == ["小红书 某博主 第一页", "新增一行字"]


# ---------------------------------------------------------------- 规则 8：限额与全文软上限


def test_image_caps_and_global_soft_limit():
    long_ocr = "\n".join(f"第{i}行很长的图上文字内容" for i in range(40))
    images = [_img(i, long_ocr + f"\n第{i}张独有") for i in range(1, 31)]
    comments = [_comment(f"z{i}", "有具体内容的评论" * 12) for i in range(1, 41)]
    body = "正文" * 2000
    text = _render(source={"note": {"title": "t", "body": body}, "comments": comments}, vision={"images": images},
                   extracted={"summary": "概要一句"})
    assert body in text and "概要一句" in text                        # 正文、概要不动
    block1 = text.split("### 第1张", 1)[1].split("### 第2张", 1)[0]
    assert "第10行很长的图上文字内容\n第11行很长的图上文字内容\n" in block1          # OCR 按原换行，一行一条
    assert sum(len(x) for x in block1.splitlines()[3:]) <= agentmd.IMAGE_LIMIT + 10
    for i in range(1, 31):                                             # 每张图的图号都在
        assert f"### 第{i}张（图{i} · image-{i:03d}.webp）" in text
    assert "（略，超出图片字数上限）" in text
    assert "条评论略去" in text
    rows = text.split("## 图片 OCR", 1)[1].split("## 评论", 1)[0].strip().splitlines()
    shown = [r for r in rows[1:] if not r.startswith("### ") and r != "（略，超出图片字数上限）"]
    assert sum(len(r) for r in shown) <= 3000                          # 图片识别总计 ≤ 3000 字（不含节头和略去行）


# ---------------------------------------------------------------- 规则 9：图号身份不变


def test_image_numbers_match_ask_labels():
    images = [_img(n, f"第{n}张") for n in (1, 3, 12)]
    text = _render(vision={"images": images})
    for image in images:
        label = ask._image_label(image, {})                              # 「图3」
        assert f"（{label} · {image['asset'].rsplit('/', 1)[1]}）" in text


def test_long_transcript_does_not_squeeze_out_valuable_comment():
    transcript = "".join("".join(chr(0x4e00 + (i * 211 + j * 37) % 5000) for j in range(30)) + "。" for i in range(500))
    long_comment = "很长的有用分析" * 100
    comments = [_comment("v1", long_comment)] + [_comment(f"n{i}", f"第{i}条普通但有内容的评论说点事") for i in range(10)]
    text = _render(source={"note": {"title": "t", "transcript": transcript}, "comments": comments},
                   extracted={"valuable_comments": [{"id": "c1", "why": "有用"}]})
    assert long_comment in text and "[c5]" in text                     # 文字稿超长时评论仍有 3000 字的位置


# ---------------------------------------------------------------- 10-15：识图描述不截半句；按图分节、描述与文字分开、保留换行


def test_description_not_cut_mid_sentence_and_sentence_cap():
    desc = "上下两幅剧照展示了女演员在办公室场景中的画面。上图为她身穿黑色职业套装、挎着米色包走在办公区过道中；下图为她与同伴并肩交谈。"
    text = _render(vision={"images": [_img(1, "合成水印字", desc)]})
    assert "描述：" + desc in text and "挎…" not in text
    long = "这是第一句很长的描述内容。" * 60
    capped = agentmd.cut_sentences(long, agentmd.DESC_LIMIT)
    assert capped.endswith("。…（略）") and len(capped) <= agentmd.DESC_LIMIT + 4


def test_image_section_layout_paragraphs_and_no_heading_leak():
    lines = [{"text": "第一段第一行", "box": [0, 0, 100, 20]}, {"text": "第一段第二行", "box": [0, 22, 100, 42]},
             {"text": "# 第二段像标题", "box": [0, 120, 100, 140]}]
    img1 = _img(1, "第一段第一行\n第一段第二行\n# 第二段像标题", "一张合成的说明图。", lines=lines)
    img2 = _img(2, "", "只有画面没有字的合成图。")
    img3 = {"asset": "raw/v0001/assets/image-003.webp", "status": "ok", "ocr": "", "visual": {}}
    text = _render(vision={"images": [img1, img2, img3]})
    sec = text.split("## 图片 OCR", 1)[1]
    assert ("### 第1张（图1 · image-001.webp）\n\n描述：一张合成的说明图。\n\n图上文字：\n\n"
            "第一段第一行\n第一段第二行\n\n\\# 第二段像标题\n") in sec
    assert "### 第2张（图2 · image-002.webp）\n\n描述：只有画面没有字的合成图。\n" in sec
    assert "第2张（图2 · image-002.webp）\n\n描述：只有画面没有字的合成图。\n\n图上文字" not in sec   # 空的不出
    assert "### 第3张（图3 · image-003.webp）\n\n（没认出文字）" in sec
    assert " / " not in sec.split("需要看原图用 read_asset。", 1)[1]
