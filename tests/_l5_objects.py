"""批次 D · L5 测试共用：在 ingest 出来的脱敏对象上补本地媒体（图 / 视频 / 评论图 / 附件 / 批注）。只写 tmp 库。"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import storage

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82")


def raw_dir(obj: dict) -> Path:
    meta = storage.read_json(obj["dir"] / "meta.json")
    return obj["dir"] / "raw" / storage.version_name(int(meta["current_version"]))


def add_media(obj: dict, *, images: int = 2, video: bool = False, comment_image: bool = False) -> dict:
    raw = raw_dir(obj)
    (raw / "assets").mkdir(parents=True, exist_ok=True)
    mpath = raw / "manifest.json"
    manifest = storage.read_json(mpath)
    media = []
    files = {}
    for i in range(1, images + 1):
        name = f"image-{i:03d}.png"
        data = PNG + bytes([i])
        (raw / "assets" / name).write_bytes(data)
        media.append({"role": "note_image", "index": i, "file": f"assets/{name}", "download_status": "ok"})
        files[name] = data
    if video:
        (raw / "assets" / "cover.png").write_bytes(PNG)
        (raw / "assets" / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"v" * 4000)
        media.append({"role": "video_cover", "file": "assets/cover.png", "download_status": "ok"})
        media.append({"role": "video", "file": "assets/video.mp4", "download_status": "ok"})
        src = storage.read_json(raw / "source.json")
        src["note"]["video"] = {"duration_sec": 62, "width": 720, "height": 1280}
        src["note"]["kind"] = "video"
        (raw / "source.json").write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
    if comment_image:
        (raw / "assets" / "comment-1.png").write_bytes(PNG + b"c")
        media.append({"role": "comment_image", "file": "assets/comment-1.png", "download_status": "ok", "floor": 1})
    manifest["media"] = media
    mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return files
