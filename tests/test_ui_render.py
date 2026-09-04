"""Obsidian 人类版 UI 契约：响应式小红书详情页，不碰 RAW/agent。"""

from pathlib import Path

from link_brain import render


def _source():
    return {
        "note": {
            "title": "测试标题",
            "kind": "image",
            "body": "第一段正文。\n\n第二段正文。\n#AI[话题]#",
            "hashtags": ["AI"],
            "links": [],
            "author": {"nickname": "示例作者"},
            "published_at": "2026-09-04T12:00:00+10:00",
            "ip_location": "浙江",
            "engagement": {"liked": 83, "collected": 38, "comment_count": 152},
        },
        "comments": [
            {
                "comment_id": "c1",
                "author": {"nickname": "momo"},
                "created_at": "2026-09-03T10:00:00+08:00",
                "ip_location": "浙江",
                "text": "一级评论",
                "like_count": 10,
                "sub_comment_count": 2,
                "sub_comments": [
                    {
                        "comment_id": "c2",
                        "author": {"nickname": "DDou"},
                        "created_at": "2026-09-03T11:00:00+08:00",
                        "text": "楼中楼",
                        "like_count": 1,
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
    assert "评论 152" in text
    assert "#AI" in text
    assert "#AI[话题]#" not in text

    assert "## 评论" not in text
    assert "## 归档信息" not in text
    assert "原图 1" not in text
    assert "原链接" not in text
    assert "# 测试标题" not in text


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


def test_css_uses_pane_container_query_and_hides_machine_metadata():
    css = (Path(render.__file__).resolve().parent / "assets" / "link-brain.css").read_text(encoding="utf-8")
    assert "container-name: link-brain-note" in css
    assert "@container link-brain-note (max-width: 760px)" in css
    assert ".metadata-container" in css
    assert "scroll-snap-type: x mandatory" in css
    assert ".lb-replies" in css
