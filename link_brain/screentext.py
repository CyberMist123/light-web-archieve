"""视频画面文字（2026-09-26）：小红书视频的信息多半烧在画面上（字幕、文字卡），
背景音乐转写出来常是歌词。参考 video-subtitle-extractor 的思路：

- 定时抽帧（每 2 秒一帧，最多 90 帧）而不是只按场景切换——字幕换了画面不一定变。
- 每帧本地 OCR（rapidocr），记下每段首次出现的秒数。
- 10-08（v2）：帧内保留 OCR 的行结构（不再用空格拼成一行）；每行和**之前所有已留下的行**比（相似度 ≥ 85 算重复，
  以前只和上一帧比，同一页来回出现就重复写）；乱码行（UI 控件、二进制装饰、≤2 个有效字符）丢掉。
  一帧里有新行才记一段，段的 text 是这些新行（换行分开）。
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
VERSION = 2


def extract(video: Path) -> dict[str, Any]:
    from rapidfuzz import fuzz, process

    from . import visual
    from .agentmd import junk_line, norm
    if not visual.available():
        return {"status": "skipped", "error": "未安装本地 OCR（pip install rapidocr）"}
    with tempfile.TemporaryDirectory(prefix="lb-frames-") as tmp:
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=1/{FRAME_EVERY_SECONDS},scale=720:-2",
                            "-frames:v", str(MAX_FRAMES), str(Path(tmp) / "f%04d.jpg")],
                           check=True, capture_output=True, timeout=300)
        except (subprocess.SubprocessError, OSError) as exc:
            return {"status": "failed", "error": f"抽帧失败: {type(exc).__name__}"}
        segments: list[dict[str, Any]] = []
        kept: list[str] = []   # 已留下的行（归一化后），帧级去重和全部已留下的比
        for i, frame in enumerate(sorted(Path(tmp).glob("f*.jpg"))):
            result = visual.local_ocr(frame)
            fresh = []
            for line in result.get("lines") or []:
                text = str(line.get("text") or "").strip()
                key = norm(text)
                if line.get("score", 0) < 0.6 or not key or junk_line(text):
                    continue
                if key in kept or (kept and process.extractOne(key, kept, scorer=fuzz.ratio, score_cutoff=SIMILAR)):
                    continue
                kept.append(key)
                fresh.append(text)
            if fresh:
                segments.append({"t": i * FRAME_EVERY_SECONDS, "text": "\n".join(fresh)})
    return {"status": "ok", "v": VERSION, "segments": segments, "text": "\n".join(s["text"] for s in segments)}
