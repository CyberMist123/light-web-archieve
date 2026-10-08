"""批次 D · L3 可见笔记渲染：N2 片段写到真 configDir + note.css 同步；N6 图片 / 视频 / 评论图预先写尺寸；
N8 缺口说人话 +「现在抓全部评论」；N9 标签可点（仍是原帖话题）；N14 评论没存下来 ≠ 暂无评论；N15 .lb-note 带 data-lb-item；N17 藏 dataviewjs 源码。"""

import html.parser
from pathlib import Path

from link_brain import render, storage

ROOT = Path(__file__).resolve().parent.parent
OBJ = "_archive/xiaohongshu/0000000000000000deadbeef"


def _note(**kw):
    note = {
        "title": "测试标题", "kind": "image", "body": "正文。", "hashtags": ["做饭", "悉尼 生活"], "links": [],
        "author": {"nickname": "示例作者"}, "published_at": "2026-09-04T12:00:00+10:00",
        "engagement": {"liked": 1, "collected": 2, "comment_count": 120},
    }
    note.update(kw)
    return note


def _meta():
    return {"item_id": "xhs-deadbeef", "source": "xiaohongshu", "source_id": "0000000000000000deadbeef",
            "canonical_url": "https://www.xiaohongshu.com/explore/0000000000000000deadbeef"}


def _block(note=None, comments=None, manifest=None, capture=None):
    src = {"note": note or _note(), "comments": comments or []}
    if capture is not None:
        src["capture"] = capture
    manifest = manifest or {"media": [
        {"role": "note_image", "file": "raw/v0001/assets/image-001.webp", "download_status": "ok", "width": 600, "height": 800},
        {"role": "note_image", "file": "raw/v0001/assets/image-002.webp", "download_status": "ok"},
    ]}
    return render.render_content_block(source=src, manifest=manifest, meta=_meta(), object_rel=OBJ)


def _floor(cid, subs=0, declared=0):
    return {"comment_id": cid, "author": {"nickname": "momo"}, "text": "楼" + cid, "sub_comment_count": declared,
            "sub_comments": [{"comment_id": f"{cid}-{i}", "author": {"nickname": "r"}, "text": "回"} for i in range(subs)]}


class _Parser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.imgs = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.imgs.append(dict(attrs))


# ── N2 ──
def test_note_css_in_sync():
    a = (ROOT / "link_brain" / "assets" / "link-brain.css").read_bytes().replace(b"\r", b"")
    b = (ROOT / "obsidian-plugins" / "link-brain-actions" / "note.css").read_bytes().replace(b"\r", b"")
    assert a == b, "note.css 必须是 link-brain.css 的逐字节副本（改 assets 那份再拷过去）"
    css = a.decode("utf8")
    assert ".xhs-note pre.language-dataviewjs" in css   # N17
    assert "body.lb-actions-on .xhs-note .lb-act" in css   # N8


def test_snippet_goes_to_env_configdir(tmp_path, monkeypatch):
    vault = tmp_path / "MainVault" / "收藏"
    vault.mkdir(parents=True)
    cfg = tmp_path / "MainVault" / ".obsidian"
    cfg.mkdir()
    monkeypatch.setenv(storage.ENV_VAULT, str(vault))
    monkeypatch.setenv("LINK_BRAIN_OBSIDIAN_DIR", str(cfg))
    render.ensure_css_snippet()
    assert (cfg / "snippets" / "link-brain.css").read_text(encoding="utf-8").startswith("/*") or (cfg / "snippets" / "link-brain.css").exists()
    assert not (vault / ".obsidian").exists(), "收藏子目录里不再凭空建 .obsidian"


def test_snippet_ancestor_vault(tmp_path, monkeypatch):
    vault = tmp_path / "MainVault" / "sub" / "收藏"
    vault.mkdir(parents=True)
    (tmp_path / "MainVault" / ".obsidian").mkdir()
    (tmp_path / "MainVault" / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(storage.ENV_VAULT, str(vault))
    monkeypatch.delenv("LINK_BRAIN_OBSIDIAN_DIR", raising=False)
    assert render.snippet_targets() == [tmp_path / "MainVault" / ".obsidian" / "snippets" / "link-brain.css"]
    render.ensure_css_snippet()
    assert (tmp_path / "MainVault" / ".obsidian" / "snippets" / "link-brain.css").exists()
    assert not (vault / ".obsidian").exists()


def test_snippet_skips_when_same(tmp_path, monkeypatch):
    (tmp_path / ".obsidian").mkdir()
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.delenv("LINK_BRAIN_OBSIDIAN_DIR", raising=False)
    render.ensure_css_snippet()
    target = tmp_path / ".obsidian" / "snippets" / "link-brain.css"
    mtime = target.stat().st_mtime_ns
    writes = []
    monkeypatch.setattr(storage, "atomic_write_text", lambda *a, **k: writes.append(a))
    render.ensure_css_snippet()
    assert writes == [] and target.stat().st_mtime_ns == mtime


# ── N6 ──
def test_note_images_have_manifest_dims():
    text = _block()
    p = _Parser()
    p.feed(text)
    first, second = p.imgs[0], p.imgs[1]
    assert first["width"] == "600" and first["height"] == "800"
    assert "width" not in second and "height" not in second, "manifest 没宽高时不写属性"


def test_video_style_has_aspect_ratio():
    manifest = {"media": [
        {"role": "video", "file": "raw/v0001/assets/video.mp4", "download_status": "ok", "width": 1692, "height": 720},
        {"role": "video_cover", "file": "raw/v0001/assets/cover.webp", "download_status": "ok", "width": 900, "height": 1200},
    ]}
    text = _block(note=_note(kind="video"), manifest=manifest)
    assert "aspect-ratio:1692 / 720" in text and "height:auto" in text
    manifest["media"][0].pop("width")
    assert "aspect-ratio:900 / 1200" in _block(note=_note(kind="video"), manifest=manifest), "视频没宽高就按封面"


def test_comment_images_have_dims(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    manifest = {"media": [{"role": "comment_image", "comment_id": "c1", "file": "raw/v0001/assets/c1.webp", "width": 300, "height": 200}]}
    text = _block(comments=[_floor("c1")], manifest=manifest)
    p = _Parser()
    p.feed(text)
    ci = [i for i in p.imgs if "lb-comment-image" in i.get("class", "")]
    assert ci and ci[0]["width"] == "300" and ci[0]["height"] == "200"


# ── N8 / N14 ──
def test_gap_text_plain_language():
    c = {"comment_id": "c9"}
    assert render._gap_text(c, 7, None, 10) == "另有 7 条回复没存（只存了前 10 楼的回复）"
    assert render._gap_text(c, 7, {"c9": "not_expanded"}, 10) == "另有 7 条回复没存（只存了前 10 楼的回复）"
    assert render._gap_text(c, 3, None) == "另有 3 条回复没存（只存了前几楼的回复）"
    other = render._gap_text(c, 2, {"c9": "stalled"}, 10)
    assert other.startswith("还有 2 条回复没拿到（") and "只存了" not in other


def test_status_line_has_fetch_action():
    cap = {"comment_load": {"floors_loaded": 15, "floor_limit": 10, "replies_missing": 9,
                            "gaps": [{"comment_id": "c12", "reason": "not_expanded", "missing": 9}]}}
    comments = [_floor(f"c{i}", subs=1, declared=1) for i in range(11)] + [_floor("c12", declared=9)]
    text = _block(comments=comments, capture=cap)
    assert "lb-act-fetch-comments" in text and "现在抓全部评论" in text
    assert "另有 9 条回复没存（只存了前 10 楼的回复）" in text


def test_status_line_for_old_capture_without_comment_load():
    text = _block(comments=[_floor("c1", subs=1, declared=8)])
    assert "楼中楼还缺 7 条（只存了前几楼的回复）" in text and "现在抓全部评论" in text
    assert "楼中楼还缺" not in _block(comments=[_floor("c1", subs=2, declared=2)]), "读全了不出这一行"


def test_empty_comments_with_count_offers_fetch():
    text = _block(comments=[])
    assert "原帖有 120 条评论，这次没存下来" in text and "lb-act-fetch-comments" in text
    for n in (0, None):
        t = _block(note=_note(engagement={"comment_count": n}), comments=[])
        assert "暂无评论" in t and "lb-act-fetch-comments" not in t


# ── N9 / N15 ──
def test_tags_from_hashtags_with_title():
    text = _block(note=_note(hashtags=["做饭"]))
    assert '<span class="lb-tag" title="在目录里看带 #做饭 的收藏">#做饭</span>' in text


def test_note_has_data_lb_item():
    assert '<div class="lb-note" data-lb-item="xhs-deadbeef">' in _block()
    assert 'class="lb-note lb-no-media" data-lb-item="xhs-deadbeef"' in _block(manifest={"media": []})
