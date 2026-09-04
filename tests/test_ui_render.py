"""Obsidian 人类版 UI 契约：响应式小红书详情页，不碰 RAW/agent。"""

from pathlib import Path

from link_brain import render


def _source():
    return {
        "note": {
            "title": "测试标题",
            "kind": "image",
            "body": "第一段正文。\n\n第二段正文。\n#AI[话题]#",
            "hashtags": ["AI", "人机恋"],
            "links": [],
            "canonical_url": "https://www.xiaohongshu.com/explore/0000000000000000deadbeef",
            "author": {"user_id": "op-1", "nickname": "示例作者"},
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
                        "author": {"user_id": "op-1", "nickname": "示例作者"},
                        "created_at": "2026-09-03T11:00:00+08:00",
                        "ip_location": "北京",
                        "target_nickname": "momo",
                        "text": "楼主回复",
                        "like_count": 1,
                        "sub_comments": [
                            {
                                "comment_id": "c3",
                                "author": {"user_id": "u-d", "nickname": "DDou"},
                                "target_nickname": "示例作者",
                                "text": "第三级回复",
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
    assert 'class="lb-comments"' in text
    assert 'class="lb-replies"' in text
    assert "1 / 2" in text and "2 / 2" in text
    assert "#AI" in text and "#人机恋" in text
    assert "#AI[话题]#" not in text

    assert "## 评论" not in text
    assert "## 归档信息" not in text
    assert "原图 1" not in text
    assert "原链接" not in text
    assert "# 测试标题" not in text


def test_arrows_are_real_radio_labels_and_image_has_double_click_open_target():
    text = render.render_content_block(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )

    assert 'class="lb-slide-toggle" type="radio"' in text
    assert 'class="lb-arrow lb-arrow-left" for=' in text
    assert 'class="lb-arrow lb-arrow-right" for=' in text
    assert '<a class="lb-arrow' not in text

    assert 'class="lb-image-double" tabindex="0"' in text
    assert 'class="lb-image-open"' in text
    assert 'href="https://www.xiaohongshu.com/explore/0000000000000000deadbeef"' in text
    assert 'target="_blank"' in text


def test_author_avatar_is_minimal_dot_and_op_is_marked_in_comments():
    text = render.render_content_block(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )

    assert 'class="lb-author-avatar"' in text
    assert 'class="lb-comment-avatar"' in text
    assert 'class="lb-author-badge">作者</span>' in text
    assert 'class="lb-op-badge">作者</span>' in text
    assert "lb-avatar-initial" not in text
    assert ">示<" not in text


def test_human_comments_hide_date_location_and_overall_count_and_render_recursive_depth():
    text = render.render_content_block(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )
    assert "momo" in text and "示例作者" in text and "DDou" in text
    assert "一级评论" in text and "楼主回复" in text and "第三级回复" in text
    assert 'data-depth="0"' in text
    assert 'data-depth="1"' in text
    assert 'data-depth="2"' in text
    assert "2026-09-03" not in text
    assert "上海" not in text and "北京" not in text and "浙江" not in text
    assert "评论 152" not in text


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


def test_css_supports_clickable_desktop_carousel_mobile_swipe_and_double_click_open():
    css = (Path(render.__file__).resolve().parent / "assets" / "link-brain.css").read_text(encoding="utf-8")

    assert ".markdown-preview-view.xhs-note .markdown-preview-sizer" in css
    assert ".markdown-source-view.xhs-note .cm-contentContainer" in css
    assert "container-name: link-brain-note" in css

    assert ".lb-slide-toggle:checked + .lb-slide" in css
    assert ".lb-arrow" in css and "cursor: pointer" in css
    assert ".lb-image-double:focus .lb-image-open" in css
    assert "pointer-events: auto" in css

    assert "scroll-snap-type: x mandatory" in css
    assert "flex: 0 0 100%" in css
    assert "overflow-x: auto" in css

    assert ".lb-comments-scroller" in css
    assert "overflow-y: auto" in css
    assert "position: sticky" in css

    assert ".cm-line:has(.cm-comment)" in css
    assert ".metadata-container" in css


def test_comment_css_uses_kaiti_grey_author_subtle_reply_line_and_plain_tags():
    css = (Path(render.__file__).resolve().parent / "assets" / "link-brain.css").read_text(encoding="utf-8")
    assert '"Kaiti SC"' in css
    assert "STKaiti" in css
    assert "KaiTi" in css
    assert ".lb-comment-author" in css
    assert "--lb-reply-line" in css
    assert "border-left: 1px solid var(--lb-reply-line)" in css
    assert ".lb-tag" in css and "background: transparent" in css
