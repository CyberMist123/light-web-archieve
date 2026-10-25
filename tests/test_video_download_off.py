"""回归（TEST-MAP ①「关掉视频下载时不下视频、原帖链接保留」，1025 补）：

设置项是插件的 `sync.downloadVideo`，后端在 `ingest.download_media` 经 `ai_config.sync_options()` 读。
关掉时：不调 `videos.download`、manifest 里没有 role=video 的条目、`note.video.video_url` 原样保留
（原帖地址是「关掉也能补」的凭据，见 videos.backfill）。开着时对照：恰好调一次。

只造 download_media 碰到的字段，字段名照 docs/FORMAT.md §source；图片下载 mock 掉（conftest 会拦真网）。
"""

from __future__ import annotations

import pytest

from link_brain import ingest
from link_brain.ai_config import DEFAULTS

SYNC_DEFAULTS = dict(DEFAULTS["sync"])
VIDEO_URL = "https://sns-video-qc.xhscdn.com/202609/v0001.mp4"


def _video_source() -> dict:
    return {
        "schema_version": 1,
        "source": "xiaohongshu",
        "source_id": "6512ab34cd7e9f0011223344",
        "note": {
            "note_id": "6512ab34cd7e9f0011223344",
            "canonical_url": "https://www.xiaohongshu.com/explore/6512ab34cd7e9f0011223344",
            "kind": "video",
            "title": "一条视频",
            "body": "正文",
            "author": {"user_id": "5f00000000000000000000a0", "nickname": "小相机",
                       "profile_url": "https://www.xiaohongshu.com/user/profile/5f00000000000000000000a0"},
            "published_at": "2026-08-19T20:11:00+08:00",
            "images": [
                {"index": 1, "url": "https://sns-webpic-qc.xhscdn.com/202609/cover.webp",
                 "original_url": "https://sns-webpic-qc.xhscdn.com/202609/cover.webp!nd_dft_wlteh_webp_3",
                 "width": 1080, "height": 1440}
            ],
            "video": {"video_url": VIDEO_URL, "cover_url": "https://sns-webpic-qc.xhscdn.com/202609/cover.webp",
                      "duration_sec": 70, "downloaded": False},
            "attachments": [],
        },
        "comments": [],
        "capture": {"captured_at": "2026-09-04T15:02:11+10:00", "input_url": "https://xhslink.cn/o/FakeLink00",
                    "input_kind": "shortlink", "adapter": "xiaohongshu/1", "mcp_endpoint": None,
                    "mcp_tool": "get_feed_details", "comments_complete": "unknown", "notes": []},
    }


def _ok_image(url, dest, stem, client):
    """照 test_night_sync 的写法 mock 掉单图下载（download_media 里原图走它）；这里让它成功，像真下载完。"""
    return {"file": f"{stem}.jpg", "requested_url": url, "mime": "image/jpeg", "width": 10, "height": 10,
            "bytes": 4, "sha256": "0" * 64, "download_status": "ok", "error": None}


def _fake_video_entry(prefix, video):
    """照 videos.download 的返回值形状（role=video 那条 manifest 片段）。"""
    return {"role": "video", "index": 1, "file": f"{prefix}/assets/video.mp4",
            "original_url": video.get("video_url"), "mime": "video/mp4", "bytes": 123,
            "width": 720, "height": 1280, "download_status": "ok", "error": None}


def test_video_off_skips_download_and_keeps_url(tmp_path, monkeypatch):
    src = _video_source()
    monkeypatch.setattr("link_brain.ai_config.sync_options",
                        lambda: {**SYNC_DEFAULTS, "downloadVideo": False})
    monkeypatch.setattr(ingest, "download_image", _ok_image)

    def _must_not_download(*a, **k):
        pytest.fail("关掉 downloadVideo 还去下视频了")
    monkeypatch.setattr("link_brain.videos.download", _must_not_download)

    manifest = ingest.download_media(src, tmp_path / "v0001", "raw/v0001")

    assert not (tmp_path / "v0001" / "assets" / "video.mp4").exists()
    assert all(m["role"] != "video" for m in manifest["media"])
    # 封面照下（downloadImages 默认开着），原帖视频地址原样保留
    assert [m["role"] for m in manifest["media"]] == ["video_cover"]
    assert manifest["media"][0]["download_status"] == "ok"
    assert src["note"]["video"]["video_url"] == VIDEO_URL


def test_video_on_downloads_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setattr("link_brain.ai_config.sync_options",
                        lambda: {**SYNC_DEFAULTS, "downloadVideo": True})
    monkeypatch.setattr(ingest, "download_image", _ok_image)
    calls: list[dict] = []

    def fake_download(video, raw, prefix, client=None):
        calls.append(dict(video))
        return _fake_video_entry(prefix, video)

    monkeypatch.setattr("link_brain.videos.download", fake_download)

    manifest = ingest.download_media(_video_source(), tmp_path / "v0001", "raw/v0001")

    assert len(calls) == 1
    assert calls[0]["video_url"] == VIDEO_URL
    videos = [m for m in manifest["media"] if m["role"] == "video"]
    assert len(videos) == 1 and videos[0]["download_status"] == "ok"
    assert videos[0]["file"] == "raw/v0001/assets/video.mp4"
