"""视频画面文字（2026-09-26）：小红书视频的信息多半烧在画面上（字幕、文字卡），
背景音乐转写出来常是歌词。参考 video-subtitle-extractor 的思路：

- 定时抽帧（每 2 秒一帧，最多 90 帧）而不是只按场景切换——字幕换了画面不一定变。
- 每帧本地 OCR（rapidocr），相邻帧文字几乎相同（相似度 ≥ 85）只留一次，记下首次出现的秒数。
- 全程本地、免费；放在夜跑里做，不挡导入。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

FRAME_EVERY_SECONDS = 2
MAX_FRAMES = 90
SIMILAR = 85


def extract(video: Path) -> dict[str, Any]:
    from rapidfuzz import fuzz

    from . import visual
    if not visual.available():
        return {"status": "skipped", "error": "未安装 rapidocr_onnxruntime"}
    with tempfile.TemporaryDirectory(prefix="lb-frames-") as tmp:
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=1/{FRAME_EVERY_SECONDS},scale=720:-2",
                            "-frames:v", str(MAX_FRAMES), str(Path(tmp) / "f%04d.jpg")],
                           check=True, capture_output=True, timeout=300)
        except (subprocess.SubprocessError, OSError) as exc:
            return {"status": "failed", "error": f"抽帧失败: {type(exc).__name__}"}
        segments: list[dict[str, Any]] = []
        for i, frame in enumerate(sorted(Path(tmp).glob("f*.jpg"))):
            result = visual.local_ocr(frame)
            text = " ".join(line["text"] for line in result.get("lines") or [] if line["score"] >= 0.6).strip()
            if not text:
                continue
            if segments and fuzz.ratio(text, segments[-1]["text"]) >= SIMILAR:
                continue
            segments.append({"t": i * FRAME_EVERY_SECONDS, "text": text})
    return {"status": "ok", "segments": segments, "text": "\n".join(s["text"] for s in segments)}
