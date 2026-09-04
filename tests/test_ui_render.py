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
                "ip_location": "上海",
                "text": "一级评论",
                "like_count": 10,
                "sub_comment_count": 2,
                "sub_comments": [
                    {
                        "comment_id": "c2",
                        "author": {"nickname": "DDou"},
                        "created_at": "2026-09-03T11:00:00+08:00",
                        "ip_location": "北京",
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
    assert "#AI" in text
    assert "#AI[话题]#" not in text

    assert "## 评论" not in text
    assert "## 归档信息" not in text
    assert "原图 1" not in text
    assert "原链接" not in text
    assert "# 测试标题" not in text


def test_human_comments_hide_date_location_and_overall_count():
    text = render.render_content_block(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
    )
    assert "momo" in text and "DDou" in text
    assert "一级评论" in text and "楼中楼" in text
    assert "lb-comment-date" not in text
    assert "2026-09-03" not in text
    assert "上海" not in text and "北京" not in text
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


def test_css_supports_reading_and_live_preview_with_pane_responsiveness():
    css = (Path(render.__file__).resolve().parent / "assets" / "link-brain.css").read_text(encoding="utf-8")

    assert ".markdown-preview-view.xhs-note .markdown-preview-sizer" in css
    assert ".markdown-source-view.xhs-note .cm-contentContainer" in css
    assert "container-name: link-brain-note" in css

    assert ".xhs-note .lb-cols" in css
    assert "repeat(auto-fit" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css

    assert "scroll-snap-type: x mandatory" in css
    assert "flex: 0 0 100%" in css
    assert "overflow-x: auto" in css

    assert ".cm-line:has(.cm-comment)" in css
    assert ".metadata-container" in css

    assert "::scroll-button(left)" in css
    assert "::scroll-button(right)" in css
    assert ".lb-replies" in css


def test_comment_css_uses_kaiti_grey_author_and_subtle_reply_line():
    css = (Path(render.__file__).resolve().parent / "assets" / "link-brain.css").read_text(encoding="utf-8")
    assert '"Kaiti SC"' in css
    assert "STKaiti" in css
    assert "KaiTi" in css
    assert ".lb-comment-author" in css
    assert "color: var(--text-muted)" in css
    assert "--lb-reply-line" in css
    assert "border-left: 1px solid var(--lb-reply-line)" in css


# --------------------------------------------------------------------------
# 笔记附件（小红书的"文件"）
# --------------------------------------------------------------------------


def _with_attachment(**over):
    source = _source()
    source["note"]["attachments"] = [
        {
            "name": "p模式教程-机教版.pdf",
            "doc_id": "7658854832003020032",
            "hint": "给小机看的版本在文件～",
            "url": "https://www.xiaohongshu.com/file/7658854832003020032",
            "page_num": 19,
            "file": None,
            "status": "metadata_only",
            **over,
        }
    ]
    return source


def test_attachment_row_shows_name_pages_and_not_downloaded():
    text = render.render_visible_md(
        source=_with_attachment(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
        existing_text=None,
    )
    assert "p模式教程-机教版.pdf" in text
    assert "19 页" in text and "未下载" in text
    # 只有元数据时指原站：普通 Markdown 链接，且必须在 HTML 块外面才点得开
    assert "](https://www.xiaohongshu.com/file/7658854832003020032)" in text
    assert "<a href=" not in text.split("</div>")[-1]


def test_downloaded_attachment_points_at_local_file():
    source = _with_attachment(status="downloaded", file="raw/v0001/attachments/教程.pdf")
    text = render.render_visible_md(
        source=source,
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
        existing_text=None,
    )
    assert "已存本地" in text
    # 下下来的字节：Obsidian 自己的 wikilink（`<a href="../../…">` 在 Obsidian 里点不开，
    # 2026-09-04 Owner 实机踩到过），且这一行在 content 的 HTML 容器之外
    link = "[[_archive/xiaohongshu/0000000000000000deadbeef/raw/v0001/attachments/教程.pdf|"
    assert link in text
    assert text.index(link) > text.rindex("</div>")
    assert "<a href=" not in text


def test_no_attachments_renders_nothing():
    text = render.render_visible_md(
        source=_source(),
        manifest=_manifest(),
        meta=_meta(),
        object_rel="_archive/xiaohongshu/0000000000000000deadbeef",
        existing_text=None,
    )
    assert "lb-files" not in text
