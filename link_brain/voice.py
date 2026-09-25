"""语音输入转文字（2026-09-26）：给「问 AI」的麦克风按钮用。

`link-brain transcribe <音频文件> --json` → {"status": "ok", "text": "..."}。
设置里的「语音识别接口」（ai_config asrAI）：
- media：本机 media.py audio（作者机器上接 CapsWriter / CMX，免费，声音不出电脑）；
- http ：任意 OpenAI 兼容的 /audio/transcriptions（开源用户用，如 whisper 服务）；
- off  ：关闭麦克风。
录音先用 ffmpeg 转成 16kHz 单声道 wav，两条通路都认。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from . import ai_config


def _to_wav(src: Path, dest: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(dest)],
                   check=True, capture_output=True, timeout=60)


def transcribe(path: Path) -> dict[str, Any]:
    cfg = ai_config.load().get("asrAI") or {}
    mode = cfg.get("mode") or "media"
    if mode == "off":
        return {"status": "off", "error": "语音输入已关闭：在设置 → AI → 语音识别接口里打开。"}
    with tempfile.TemporaryDirectory(prefix="lb-voice-") as tmp:
        wav = Path(tmp) / "voice.wav"
        try:
            _to_wav(path, wav)
        except (subprocess.SubprocessError, OSError):
            return {"status": "failed", "error": "录音格式转换失败：需要安装 ffmpeg 并加入 PATH。"}
        if mode == "http":
            if not cfg.get("endpoint"):
                return {"status": "failed", "error": "没有填写语音识别接口地址：设置 → AI → 语音识别接口。"}
            headers = {"Authorization": "Bearer " + cfg["apiKey"].strip()} if cfg.get("apiKey") else {}
            try:
                with wav.open("rb") as fh:
                    response = httpx.post(cfg["endpoint"], headers=headers, timeout=60,
                                          data={"model": cfg.get("model") or "whisper-1"},
                                          files={"file": ("voice.wav", fh, "audio/wav")})
                response.raise_for_status()
                text = (response.json().get("text") or "").strip()
            except (httpx.HTTPError, ValueError) as exc:
                return {"status": "failed", "error": f"语音识别接口出错：{type(exc).__name__}: {str(exc)[:160]}"}
            return {"status": "ok" if text else "empty", "text": text}
        from .vision import MEDIA_PY
        if not Path(MEDIA_PY).is_file():
            return {"status": "failed", "error": "本机没有语音识别服务：在设置 → AI → 语音识别接口里改用自定义接口。"}
        try:
            proc = subprocess.run(["python", MEDIA_PY, "audio", str(wav)], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=90)
        except (subprocess.SubprocessError, OSError) as exc:
            return {"status": "failed", "error": f"本机语音识别调用失败：{type(exc).__name__}"}
        lines = [line for line in (proc.stdout or "").strip().splitlines() if not line.startswith("(引擎 ")]
        text = "\n".join(lines).strip()
        if proc.returncode != 0:
            return {"status": "failed", "error": (proc.stderr or "本机语音识别失败").strip()[-200:]}
        return {"status": "ok" if text else "empty", "text": text}


def run(args) -> int:
    from .read import dump_json
    result = transcribe(Path(args.file))
    if result["status"] == "empty":
        result["error"] = "没听清，再说一次试试。"
    dump_json(result)
    return 0 if result["status"] == "ok" else 1
