"""Obsidian 人类版 UI 契约：响应式小红书详情页，不碰 RAW/agent。"""

from pathlib import Path

from link_brain import render


def _source():
    return {
        "note": {
            "title": "测试标题",
            "kind": "image",
            "body": "第一段正文。\n\n第二段正文。\n#AI[话题]#",
            "hashtags": ["AI", "Claude"],
            "links": [],
            "author": {"user_id": "u-owner", "nickname": "示例作者"},
            "published_at": "2026-09-04T12:00:00+10:00",
            "ip_location": "浙江",
            "engagement": {"liked": 83, "collected": 38, "comment_count": 152},
        },
        "comments": [
            {
                "comment_id": "c1",
                "author": {"user_id": "u-momo", "nickname": "momo"},
                "created_at": "2026-09-03T10:00:00+08:00",
                "ip_location": "上海",
                "text": "一级评论",
                "like_count": 10,
                "sub_comment_count": 2,
                "sub_comments": [
                    {
                        "comment_id": "c2",
                        "author": {"user_id": "u-owner", "nickname": "示例作者"},
                        "created_at": "2026-09-03T11:00:00+08:00",
                        "ip_location": "北京",
                        "target_nickname": "momo",
                        "text": "楼主回复",
                        "like_count": 1,
                        "sub_comments": [
                            {
                                "comment_id": "c3",
                                "author": {"user_id": "u-zen", "nickname": "Zen"},
                                "target_nickname": "示例作者",
                                "text": "三级回复",
                                "like_count": 0,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _manifest():
    return {
        "media": [
            {"role": "note_image", "file": "raw/v0001/assets/image-001.webp", "download_status": "ok"},
            {"role": "note_image", "file": "raw/v0001/assets/image-002.webp", "download_status": "ok"},
        ]
    }


def _meta():
    return {
        "item_id": "xhs-deadbeef",
        "source": "xiaohongshu",
        "source_id": "0000000000000000deadbeef",
        "canonical_url": "https://www.xiaohongshu.com/explore/0000000000000000deadbeef",
        "origin": "cli",
        "ingest_kind": "shared",
        "actor": "human",
        "first_archived_at": "2026-09-04T12:00:00+10:00",
        "current_version": 1,
        "images_complete": True,
        "comments_complete": True,
        "note": "顶部留言",
    }


def test_human_view_is_xhs_layout_without_debug_sections():
    text = render.render_visible_md(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
        existing_text=None,
    )

    assert "cssclasses: [link-brain, xhs-note]" in text
    assert 'class="lb-cols"' in text
    assert 'class="lb-carousel"' in text
    assert 'class="lb-detail"' in text
    assert 'class="lb-comments-scroller"' in text
    assert 'class="lb-replies"' in text
    assert "1 / 2" in text and "2 / 2" in text
    assert 'class="lb-arrow lb-arrow-left"' in text
    assert 'class="lb-arrow lb-arrow-right"' in text
    assert "#AI" in text and "#Claude" in text
    assert "#AI[话题]#" not in text

    assert "## 评论" not in text
    assert "## 归档信息" not in text
    assert "原图 1" not in text
    assert "原链接" not in text
    assert "# 测试标题" not in text


def test_author_badge_stable_avatar_and_op_reply_follow_author():
    source = _source()
    text = render.render_content_block(
        source=source,
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )

    assert 'class="lb-author-badge">作者<' in text
    assert 'class="lb-op-badge">作者<' in text
    assert "lb-is-op" in text
    assert "lb-author-avatar" in text
    assert "lb-comment-avatar" in text
    assert "示" in text

    owner_color = render._stable_avatar_color(source["note"]["author"])
    assert text.count(owner_color) >= 2
    assert render._stable_avatar_color({"user_id": "u-momo", "nickname": "momo"}) != owner_color


def test_complex_nested_replies_are_recursive_and_keep_reply_targets():
    text = render.render_content_block(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )
    assert 'data-depth="0"' in text
    assert 'data-depth="1"' in text
    assert 'data-depth="2"' in text
    assert "回复 momo：" in text
    assert "回复 示例作者：" in text
    assert "三级回复" in text


def test_human_comments_hide_date_location_and_overall_count():
    text = render.render_content_block(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )
    assert "momo" in text and "示例作者" in text
    assert "一级评论" in text and "楼主回复" in text
    assert "lb-comment-date" not in text
    assert "2026-09-03" not in text
    assert "上海" not in text and "北京" not in text
    assert "评论 152" not in text
    assert "浙江" not in text


def test_video_human_view_marks_not_downloaded_without_original_link():
    source = _source()
    source["note"]["kind"] = "video"
    manifest = {
        "media": [
            {"role": "video_cover", "file": "raw/v0001/assets/video-cover.webp", "download_status": "ok"}
        ]
    }
    text = render.render_content_block(
        source=source,
        manifest=manifest,
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )
    assert "视频 · 未下载" in text
    assert "原链接" not in text


def test_css_supports_hover_arrows_inline_tags_and_independent_comment_scroll():
    css = (Path(render.__file__).resolve().parent / "assets" / "link-brain.css").read_text(encoding="utf-8")

    assert ".markdown-preview-view.xhs-note .markdown-preview-sizer" in css
    assert ".markdown-source-view.xhs-note .cm-contentContainer" in css
    assert "container-name: link-brain-note" in css
    assert "@container link-brain-note (min-width: 980px)" in css

    assert "scroll-snap-type: x mandatory" in css
    assert "flex: 0 0 100%" in css
    assert ".lb-arrow-left" in css and ".lb-arrow-right" in css
    assert ".lb-media:hover .lb-arrow" in css
    assert ".lb-media:hover .lb-counter" in css

    assert ".lb-tag" in css
    assert "background: transparent" in css

    assert ".lb-comments-scroller" in css
    assert "overflow-y: auto" in css
    assert "max-height: clamp(280px, 43vh, 540px)" in css
    assert "position: sticky" in css

    assert ".cm-line:has(.cm-comment)" in css
    assert ".metadata-container" in css


def test_comment_css_uses_kaiti_grey_author_avatar_and_subtle_reply_line():
    css = (Path(render.__file__).resolve().parent / "assets" / "link-brain.css").read_text(encoding="utf-8")
    assert '"Kaiti SC"' in css
    assert "STKaiti" in css
    assert "KaiTi" in css
    assert ".lb-comment-author" in css
    assert "color: var(--lb-muted)" in css
    assert ".lb-comment-avatar" in css
    assert "--lb-avatar-color" in css
    assert "--lb-reply-line" in css
    assert "border-left: 1px solid var(--lb-reply-line)" in css
    assert ".lb-op-badge" in css
