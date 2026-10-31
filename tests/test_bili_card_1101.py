"""1101：B 站卡片要的播放量 / 时长 / 上传时间 / 本地视频进 catalog（catalog._bili_card）。"""
import json

from link_brain.catalog import _bili_card


def test_bili_card_fields(tmp_path):
    raw = tmp_path / "raw" / "v0001"
    (raw / "assets").mkdir(parents=True)
    (raw / "assets" / "video.mp4").write_bytes(b"x")
    (raw / "manifest.json").write_text(json.dumps({"media": [
        {"role": "video_cover", "file": "raw/v0001/assets/cover.jpg", "download_status": "ok"},
        {"role": "video", "file": "raw/v0001/assets/video.mp4", "download_status": "ok"}]}), encoding="utf-8")
    note = {"engagement": {"viewed": 435000}, "video": {"duration_sec": 701.4}, "published_at": "2026-10-23T12:00:00+08:00"}
    out = _bili_card(tmp_path, "bilibili", "BV1x", 1, note)
    assert out == {"views": 435000, "duration": 701, "pub_at": "2026-10-23T12:00:00+08:00",
                   "video": "_archive/bilibili/BV1x/raw/v0001/assets/video.mp4"}


def test_bili_card_no_video_file(tmp_path):
    out = _bili_card(tmp_path, "bilibili", "BV1x", 1, {"video": {"duration_sec": 0}})
    assert out == {"views": None, "duration": None, "pub_at": ""}
