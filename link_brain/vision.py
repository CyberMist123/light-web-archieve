"""对 assets/ 里的图 subprocess 调 media.py image --ocr，结果落 derived/vision.json。

规则（docs/FORMAT.md、docs/TASKBOOK.md Lot 3）：
- 每张图一条记录，`asset` 回指相对对象目录的 RAW 路径（`raw/v0001/assets/xxx.webp`）。
- 按 sha256 跳过已经识别过的图，避免重复调用 media.py。
- 单张图调用失败记 `status:"failed"`，不阻断整体流程。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import storage

MEDIA_PY = r"C:\Users\18717\Documents\cyberlink\Fluffy-SelfHood\tools\scripts\media.py"

IMAGE_SUFFIXES = {".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif", ".heic", ".bmp"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def run_ocr(image_path: Path, *, timeout: int = 120) -> dict[str, Any]:
    """subprocess 调 media.py image <path> --ocr，返回 {status, ocr|error}。"""
    try:
        proc = subprocess.run(
            ["python", MEDIA_PY, "image", str(image_path), "--ocr"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - 调用失败记进 vision.json，不炸流程
        return {"status": "failed", "ocr": None, "error": f"subprocess 调用失败: {type(exc).__name__}: {exc}"}

    text = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or text or f"media.py 退出码 {proc.returncode}"
        return {"status": "failed", "ocr": None, "error": err}
    return {"status": "ok", "ocr": text, "error": None}


def build_vision(source_key: str, source_id: str, *, verbose: bool = False) -> dict[str, Any]:
    """对当前版本 `raw/vNNNN/assets/` 下每张图跑 OCR，落 `derived/vision.json`。

    按 sha256 跳过已识别的图（已有 vision.json 里同 sha256 且 status=ok 的条目原样保留）。
    返回写盘的 vision.json 内容。
    """
    object_dir = storage.object_dir(source_key, source_id)
    meta_path = object_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"没有归档过: {source_key}/{source_id}")
    meta = storage.read_json(meta_path)
    version = meta["current_version"]
    raw_dir = storage.raw_dir(source_key, source_id, version)
    assets_dir = raw_dir / "assets"
    rel_prefix = f"raw/{storage.version_name(version)}/assets"

    derived_dir = storage.derived_dir(source_key, source_id)
    vision_path = derived_dir / "vision.json"
    existing: dict[str, Any] = {}
    if vision_path.exists():
        prior = storage.read_json(vision_path)
        for item in prior.get("images", []):
            if item.get("sha256"):
                existing[item["sha256"]] = item

    images: list[dict[str, Any]] = []
    if assets_dir.is_dir():
        for path in sorted(assets_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            sha = _sha256_file(path)
            asset_rel = f"{rel_prefix}/{path.name}"
            cached = existing.get(sha)
            if cached and cached.get("status") == "ok":
                images.append({**cached, "asset": asset_rel, "sha256": sha})
                if verbose:
                    print(f"[vision] 跳过（已识别）{asset_rel}", file=sys.stderr)
                continue
            if verbose:
                print(f"[vision] OCR {asset_rel}", file=sys.stderr)
            result = run_ocr(path)
            images.append({"asset": asset_rel, "sha256": sha, **result})

    doc = {
        "schema_version": 1,
        "version": version,
        "images": images,
    }
    storage.write_json(vision_path, doc)
    return doc
