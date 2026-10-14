"""1008 Owner（煮蛋案例：信息全但啰嗦没重点）：回答按问题类型组织、单来源不逐行标引用、不单开「原文摘录」节；
模型写 `[看图：来源N 图M]` 占位，后端换成 vault 里的真图，对不上材料的占位删掉。"""
import json

from link_brain import ask, storage

from test_ask_ui2_1004 import _setup


def test_prompt_carries_format_rules_and_drops_excerpt_section_request(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    ask.answer("机场到市区怎么走")
    prompt, material = seen[-1]
    assert "配方 / 流程 / 操作类" in prompt and "知识 / 学术 / 概念类" in prompt
    assert "只有一条来源时，在每个小节标题末尾标一次[来源N]" in prompt
    assert "不要单开「原文摘录」节" in prompt
    assert "[看图：来源N 图M]" in prompt
    assert "重点项附1至3段短原文摘录" not in material and "逐段标[来源N]" not in material
    assert "按上面的「回答组织」规则选一种结构" in material


def test_excerpt_tag_carries_image_and_comment_identity():
    # 1015 第二批：标签改成她看得懂的来源类型名；locate_excerpts 实际给的键是 comment_labels（以前只认 comments，楼号从没带上），
    # 评论另带说话人
    assert ask._excerpt_tag({"field": "ocr", "text": "x", "images": ["图2", "图3"]}) == "[图片文字 图2、图3]"
    assert ask._excerpt_tag({"field": "comments", "text": "x", "comments": ["c5", "c5.1"]}) == "[评论区 c5、c5.1]"
    assert ask._excerpt_tag({"field": "comments", "text": "x", "comment_labels": ["c3"],
                             "speakers": ["评论者：小王（不是作者）"]}) == "[评论区 c3 · 评论者：小王（不是作者）]"
    assert ask._excerpt_tag({"field": "body", "text": "x"}) == "[正文]"


def _vault_with_images(tmp_path, monkeypatch, n=3):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    obj = tmp_path / "_archive" / "xiaohongshu" / "abc"
    assets = obj / "raw" / "v0001" / "assets"
    assets.mkdir(parents=True)
    (obj / "derived").mkdir()
    images = []
    for i in range(1, n + 1):
        (assets / f"image-{i:03d}.webp").write_bytes(b"RIFF")
        images.append({"asset": f"raw/v0001/assets/image-{i:03d}.webp", "status": "ok"})
    (obj / "derived" / "vision.json").write_text(json.dumps({"images": images}), encoding="utf-8")
    return [{"citation": 1, "agent_md": str(obj / "derived" / "agent.md")}]


def test_embed_images_replaces_known_placeholders_and_drops_unknown(tmp_path, monkeypatch):
    sources = _vault_with_images(tmp_path, monkeypatch)
    md = "步骤 1：煮 5 分半\n[看图：来源1 图2]\n步骤 2：冰水\n[看图：来源1 图9]\n[看图：来源2 图1]\n[看图: 来源1, 图3]"
    out = ask.embed_images(md, sources)
    assert "![[_archive/xiaohongshu/abc/raw/v0001/assets/image-002.webp|360]]" in out
    assert "![[_archive/xiaohongshu/abc/raw/v0001/assets/image-003.webp|360]]" in out
    assert "图9" not in out and "来源2" not in out and "[看图" not in out
    assert "步骤 1：煮 5 分半" in out and "步骤 2：冰水" in out


def test_embed_images_caps_at_three_and_survives_missing_vision(tmp_path, monkeypatch):
    sources = _vault_with_images(tmp_path, monkeypatch, n=5)
    md = "\n".join(f"[看图：来源1 图{i}]" for i in range(1, 6))
    out = ask.embed_images(md, sources)
    assert out.count("![[") == ask.MAX_EMBEDS
    # vision.json 没有 / agent_md 为空：占位删掉，正文不动
    assert ask.embed_images("a [看图：来源1 图1] b", [{"citation": 1, "agent_md": None}]) == "a b"
    assert ask.embed_images("a [看图：来源1 图1] b", []) == "a b"


def test_answer_pipeline_embeds_image(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path, answer="## 做法[来源1]\n1. 煮 5 分半\n[看图：来源1 图1]")
    obj = tmp_path / "_archive" / "xiaohongshu" / "t0"
    (obj / "raw" / "v0001" / "assets").mkdir(parents=True)
    (obj / "derived").mkdir()
    (obj / "raw" / "v0001" / "assets" / "image-001.webp").write_bytes(b"RIFF")
    (obj / "derived" / "vision.json").write_text(json.dumps({"images": [{"asset": "raw/v0001/assets/image-001.webp", "status": "ok"}]}), encoding="utf-8")
    items = [dict(x) for x in __import__("test_ask_ui2_1004").ITEMS]
    items[0]["agent_md"] = "_archive/xiaohongshu/t0/derived/agent.md"
    monkeypatch.setattr(ask, "load_items", lambda: items)
    r = ask.answer("交通攻略 0")
    assert r["sources"][0]["id"] == "t0"
    assert "![[_archive/xiaohongshu/t0/raw/v0001/assets/image-001.webp|360]]" in r["markdown"]
    assert "[看图" not in r["markdown"]
