"""语音识别执行器（CONVENTIONS §4）：`transcribe(wav_path, cfg)` → R。视频转写和问 AI 的麦克风都走这里。

设置 asrAI.mode 三选一：
- capswriter：本机 CapsWriter-Offline（开源 HaujetZhao/CapsWriter-Offline）的识别服务端，websocket，免费、离线、声音不出电脑。
  协议照它的 core/protocol.py：客户端发 JSON `AudioMessage`（base64 的 float32 / 16kHz / 单声道 PCM，`is_final` 收尾），
  服务端回 JSON `RecognitionMessage`（`is_final=true` 那条带整段 `text`）。连接要带子协议 `binary`。
  服务端没开 → skipped（SKIPPED.NOT_CONFIGURED「语音识别没开」），不算失败。
- http：OpenAI 兼容 `/audio/transcriptions`（云端或本地 whisper 服务都行），HTTP 状态翻成故障码。
- off：关。

长音频先按静音点切段（每段不超过 asrAI.segmentSec，默认 50 秒；切点挑最后 10 秒里最安静的 0.3 秒），一段一段识别再拼。
输入固定是 16kHz 单声道 16 位 wav（调用方用 ffmpeg 转好）。
"""

from __future__ import annotations

import base64
import io
import json
import socket
import time
import uuid
import wave
from pathlib import Path
from typing import Any

from . import providers

RATE = 16000
SEARCH_SEC = 10.0  # 在每段最后这么多秒里找切点
FRAME_SEC = 0.3
STEP_SEC = 0.1


# --------------------------------------------------------------------------
# 读 wav + 切段
# --------------------------------------------------------------------------

def read_pcm16(path: Path) -> bytes:
    """16kHz 单声道 16 位 wav 的 PCM 字节；格式不对抛 ValueError。"""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"音频要 16kHz 单声道 16 位（拿到 {w.getframerate()}Hz / {w.getnchannels()} 声道 / "
                             f"{w.getsampwidth() * 8} 位）")
        return w.readframes(w.getnframes())


def split_points(pcm: bytes, max_sec: float) -> list[tuple[int, int]]:
    """按静音切段，返回 [(起, 止)] 样本下标。每段 ≤ max_sec；切点在段尾 SEARCH_SEC 秒里最安静的地方。"""
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    total = len(samples)
    limit = max(int(max_sec * RATE), int(2 * SEARCH_SEC * RATE))
    if total <= limit:
        return [(0, total)] if total else []
    frame, step = int(FRAME_SEC * RATE), int(STEP_SEC * RATE)
    out: list[tuple[int, int]] = []
    start = 0
    while total - start > limit:
        lo = start + limit - int(SEARCH_SEC * RATE)
        hi = start + limit - frame
        best, best_energy = start + limit, None
        for pos in range(lo, hi + 1, step):
            energy = float(np.mean(samples[pos:pos + frame] ** 2))
            if best_energy is None or energy < best_energy:
                best, best_energy = pos + frame // 2, energy
        out.append((start, best))
        start = best
    out.append((start, total))
    return out


def _join(parts: list[str]) -> str:
    text = ""
    for part in (p.strip() for p in parts):
        if not part:
            continue
        if text and (text[-1].isascii() and text[-1].isalnum()) and (part[0].isascii() and part[0].isalnum()):
            text += " "
        text += part
    return text


# --------------------------------------------------------------------------
# CapsWriter websocket
# --------------------------------------------------------------------------

def capswriter_url(cfg: dict[str, Any]) -> str:
    return f"ws://{cfg.get('host') or '127.0.0.1'}:{int(cfg.get('port') or providers.capswriter_port(cfg))}"


def available(cfg: dict[str, Any] | None) -> bool:
    """capswriter：端口能连上才算开着（1 秒探一下，抽音轨之前先看，别白跑 ffmpeg）；其他方式只看配没配。"""
    if not cfg:
        return False
    if cfg.get("mode") != "capswriter":
        return True
    try:
        with socket.create_connection((cfg.get("host") or "127.0.0.1", int(cfg.get("port") or 0)), timeout=1.0):
            return True
    except (OSError, ValueError):
        return False


def not_running(cfg: dict[str, Any]) -> dict[str, Any]:
    return providers.skipped("asrAI", f"语音识别没开：连不上本机 CapsWriter 服务端（{capswriter_url(cfg)}）。"
                                      "打开 CapsWriter-Offline 的服务端，或在设置里改端口 / 换方式")


def _connect(url: str, timeout: float):
    from websockets.sync.client import connect
    kwargs: dict[str, Any] = dict(subprotocols=["binary"], max_size=None, open_timeout=min(timeout, 10))
    try:
        return connect(url, proxy=None, **kwargs)  # 本机连接不走系统代理（websockets ≥ 15 默认会读代理设置）
    except TypeError:
        return connect(url, **kwargs)


def _capswriter(pcm: bytes, segments: list[tuple[int, int]], cfg: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    from websockets.exceptions import ConnectionClosed, InvalidHandshake

    url = capswriter_url(cfg)
    limit = float(cfg.get("timeoutSec") or 300)
    try:
        ws = _connect(url, limit)
    except (OSError, TimeoutError, InvalidHandshake):
        return not_running(cfg)
    samples = np.frombuffer(pcm, dtype="<i2")
    texts: list[str] = []
    try:
        with ws:
            for a, b in segments:
                floats = (samples[a:b].astype(np.float32) / 32768.0).astype("<f4").tobytes()
                task_id = str(uuid.uuid1())
                ws.send(json.dumps({
                    "task_id": task_id, "source": "file", "data": base64.b64encode(floats).decode("ascii"),
                    "is_final": True, "time_start": time.time(), "seg_duration": 60.0, "seg_overlap": 4.0,
                    "context": str(cfg.get("context") or ""), "language": str(cfg.get("language") or "auto"),
                }, ensure_ascii=False))
                deadline = time.monotonic() + limit
                while True:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        return providers.result("failed", code="TRANSIENT.STEP_TIMEOUT", api_error=True,
                                                error=f"CapsWriter 超过 {limit:.0f} 秒没回结果")
                    try:
                        raw = ws.recv(timeout=left)
                    except TimeoutError:
                        continue
                    try:
                        msg = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    if msg.get("task_id") == task_id and msg.get("is_final"):
                        texts.append(str(msg.get("text") or ""))
                        break
    except ConnectionClosed:
        return providers.result("failed", code="TRANSIENT.NETWORK", api_error=True,
                                error="CapsWriter 服务端中途断开了，下次自动再试")
    except OSError as exc:
        return providers.result("failed", code="TRANSIENT.NETWORK", api_error=True,
                                error=f"和 CapsWriter 服务端通信出错：{type(exc).__name__}")
    return providers.result("ok", _join(texts), engine="CapsWriter-Offline", segments=len(segments))


# --------------------------------------------------------------------------
# OpenAI 兼容 /audio/transcriptions
# --------------------------------------------------------------------------

def _wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def _http(pcm: bytes, segments: list[tuple[int, int]], cfg: dict[str, Any]) -> dict[str, Any]:
    import httpx

    if cfg.get("keyError") and not cfg.get("apiKey"):
        return providers.result("failed", code="NEEDS_HUMAN.AUTH_FAILED", error=cfg["keyError"], api_error=True)
    headers = {"Authorization": "Bearer " + str(cfg["apiKey"]).strip()} if cfg.get("apiKey") else {}
    limit = float(cfg.get("timeoutSec") or 300)
    texts: list[str] = []
    for a, b in segments:
        body = _wav_bytes(pcm[a * 2:b * 2])
        try:
            response = httpx.post(cfg["endpoint"], headers=headers, timeout=limit,
                                  data={"model": cfg.get("model") or "whisper-1"},
                                  files={"file": ("audio.wav", body, "audio/wav")})
        except httpx.HTTPError as exc:
            return providers.network_failure(exc)
        if response.status_code >= 400:
            return providers.http_failure(response.status_code, response.text[:2000])
        try:
            texts.append(str(response.json().get("text") or ""))
        except (ValueError, AttributeError):
            return providers.result("failed", code="TRANSIENT.HTTP_5XX", api_error=True, error="语音识别接口回包坏了")
    return providers.result("ok", _join(texts), engine=f"http:{cfg.get('model') or 'whisper-1'}", segments=len(segments))


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def transcribe(wav_path: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """一段 16kHz 单声道 wav → 文字。cfg 缺省 = providers.resolve('asrAI')。返回 R（text 可能是空串 = 没听出字）。"""
    cfg = cfg if cfg is not None else providers.resolve("asrAI")
    if cfg is None:
        return providers.skipped_for("asrAI")
    try:
        pcm = read_pcm16(Path(wav_path))
    except (OSError, EOFError, wave.Error, ValueError) as exc:
        return providers.result("failed", code="PERMANENT.NO_AUDIO", error=f"音频读不了：{exc}")
    if not pcm:
        return providers.result("ok", "", engine=cfg.get("mode"), segments=0)
    try:
        max_sec = float(cfg.get("segmentSec") or 50)
    except (TypeError, ValueError):
        max_sec = 50.0
    segments = split_points(pcm, max_sec)
    if cfg.get("mode") == "capswriter":
        return _capswriter(pcm, segments, cfg)
    return _http(pcm, segments, cfg)
