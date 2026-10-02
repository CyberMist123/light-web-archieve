"""语音输入转文字（2026-09-26）：给「问 AI」的麦克风按钮用，也是设置页「测试语音识别」的后端。

`link-brain transcribe <音频文件> --json` → {"status": "ok", "text": "..."}。
录音先用 ffmpeg 转成 16kHz 单声道 wav，再交给 `asr.transcribe`（设置里的「语音识别」：本机 CapsWriter / 自定义接口 / 关闭）。
没开 / 没配：status=skipped，error 是一句能直接给人看的原因。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import asr, providers

SAMPLE = Path(__file__).resolve().parent / "assets" / "asr-sample.wav"  # 随包的合成人声样例（约 3 秒）


def _to_wav(src: Path, dest: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
                    str(dest)], check=True, capture_output=True, timeout=60)


def transcribe(path: Path) -> dict[str, Any]:
    cfg = providers.resolve("asrAI")
    if cfg is None:
        r = providers.skipped_for("asrAI")
        return {**r, "error": f"{r['error']}：在设置 → AI → 语音识别里打开。"}
    if cfg.get("mode") == "capswriter" and not asr.available(cfg):
        return asr.not_running(cfg)
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix="lb-voice-") as tmp:
        wav = Path(tmp) / "voice.wav"
        try:
            asr.read_pcm16(path)
            wav = path  # 已经是 16kHz 单声道 wav（随包样例就是）：不用 ffmpeg
        except Exception:  # noqa: BLE001 - 不是现成的 wav 就转
            try:
                _to_wav(path, wav)
            except (subprocess.SubprocessError, OSError):
                return providers.result("failed", code="PERMANENT.NO_AUDIO",
                                        error="录音格式转换失败：需要安装 ffmpeg 并加入 PATH。")
        result = asr.transcribe(wav, cfg)
    if result.get("status") == "ok" and not (result.get("text") or "").strip():
        result["status"] = "empty"
    return result


def run(args) -> int:
    from .read import dump_json
    result = transcribe(Path(args.file))
    if result["status"] == "empty":
        result["error"] = "没听清，再说一次试试。"
    dump_json(result)
    return 0 if result["status"] in ("ok", "skipped") else 1
