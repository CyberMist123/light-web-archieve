"""语音识别执行器（第 1B 批）：CapsWriter websocket 协议、长音频按静音切段、没开 = skipped。

**不连真 CapsWriter**：起一个本进程里的假 websocket 服务端（随机端口），照 CapsWriter-Offline core/protocol.py 的
消息格式收发：客户端发 AudioMessage（base64 float32 16kHz 单声道），服务端回 RecognitionMessage（is_final 那条带 text）。
"""

from __future__ import annotations

import base64
import math
import struct
from pathlib import Path

import pytest

from _samples import FakeCapsWriter, free_port
from link_brain import ai_config, asr, providers, voice

RATE = 16000


def tone(seconds: float, amp: float = 0.3, freq: float = 440.0) -> bytes:
    n = int(seconds * RATE)
    return b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / RATE))) for i in range(n))


def silence(seconds: float) -> bytes:
    return b"\0\0" * int(seconds * RATE)


def wav(path: Path, pcm: bytes) -> Path:
    path.write_bytes(asr._wav_bytes(pcm))
    return path


@pytest.fixture
def fake_server():
    srv = FakeCapsWriter()
    yield srv
    srv.close()


def caps_cfg(port, **extra):
    return {"mode": "capswriter", "host": "127.0.0.1", "port": port, "segmentSec": 50, "timeoutSec": 10, **extra}


def test_short_audio_is_one_final_message_in_capswriter_format(fake_server, tmp_path):
    out = asr.transcribe(wav(tmp_path / "a.wav", tone(2.0)), caps_cfg(fake_server.port))
    assert out["status"] == "ok" and out["text"] == "第1段" and out["engine"] == "CapsWriter-Offline"
    assert fake_server.subprotocols == ["binary"]
    (msg,) = fake_server.received
    assert msg["source"] == "file" and msg["is_final"] is True
    assert set(msg) >= {"task_id", "data", "time_start", "seg_duration", "seg_overlap", "context", "language"}
    floats = base64.b64decode(msg["data"])
    assert len(floats) == 2 * RATE * 4, "float32 / 16kHz / 单声道"
    first = struct.unpack("<f", floats[4:8])[0]
    assert -1.0 <= first <= 1.0


def test_long_audio_is_cut_at_silence_and_joined(fake_server, tmp_path):
    # 45 秒有声 + 1 秒静音 + 45 秒有声 + 1 秒静音 + 20 秒：切点应落在两段静音里
    pcm = tone(45) + silence(1) + tone(45) + silence(1) + tone(20)
    cuts = asr.split_points(pcm, 50)
    assert len(cuts) == 3
    for (a, b), quiet_at in zip(cuts[:2], (45.0, 91.0)):
        assert quiet_at <= b / RATE <= quiet_at + 1.0, f"切点 {b / RATE:.2f}s 没落在静音里"
    out = asr.transcribe(wav(tmp_path / "long.wav", pcm), caps_cfg(fake_server.port))
    assert out["status"] == "ok" and out["text"] == "第1段第2段第3段" and out["segments"] == 3
    assert all(m["is_final"] for m in fake_server.received)
    assert sum(len(base64.b64decode(m["data"])) for m in fake_server.received) == len(pcm) * 2


def test_no_silence_falls_back_to_fixed_length_segments():
    cuts = asr.split_points(tone(130), 50)
    assert all((b - a) / RATE <= 50 for a, b in cuts) and cuts[-1][1] == 130 * RATE


def test_capswriter_not_running_is_skipped(tmp_path):
    out = asr.transcribe(wav(tmp_path / "a.wav", tone(1)), caps_cfg(free_port()))
    assert out["status"] == "skipped" and out["code"] == "SKIPPED.NOT_CONFIGURED"
    assert "语音识别没开" in out["error"]
    assert asr.available(caps_cfg(free_port())) is False


def test_capswriter_silent_server_times_out_as_transient(tmp_path):
    srv = FakeCapsWriter(reply=False)
    try:
        out = asr.transcribe(wav(tmp_path / "a.wav", tone(1)), caps_cfg(srv.port, timeoutSec=1))
    finally:
        srv.close()
    assert out["status"] == "failed" and out["code"] == "TRANSIENT.STEP_TIMEOUT"


def test_port_default_comes_from_capswriter_config(tmp_path):
    (tmp_path / "config_server.py").write_text("class ServerConfig:\n    addr = '0.0.0.0'\n    port = '6123'\n",
                                               encoding="utf-8")
    assert providers.capswriter_port({"capsWriterDir": str(tmp_path)}) == 6123
    assert providers.capswriter_port({}) == providers.CAPSWRITER_DEFAULT_PORT == 6016
    # 设置里填了 CapsWriter 目录、端口留空：resolve 用它 config_server.py 里的端口
    s = ai_config._deep_merge(ai_config.DEFAULTS, {"voice": {"capsWriterDir": str(tmp_path)}})
    assert providers.resolve("asrAI", s)["port"] == 6123
    s = ai_config._deep_merge(ai_config.DEFAULTS, {"voice": {"capsWriterDir": str(tmp_path)}, "asrAI": {"port": "7000"}})
    assert providers.resolve("asrAI", s)["port"] == 7000
    assert "端口" in providers.why_not("asrAI", ai_config._deep_merge(ai_config.DEFAULTS, {"asrAI": {"port": "abc"}}))


def test_voice_transcribe_goes_through_capswriter(fake_server, monkeypatch):
    """麦克风 / 设置页测试按钮的那条路：voice.transcribe → asr（随包样例本身就是 16kHz wav，不经 ffmpeg）。"""
    monkeypatch.setattr(ai_config, "load", lambda: ai_config._deep_merge(
        ai_config.DEFAULTS, {"asrAI": {"mode": "capswriter", "port": fake_server.port}}))
    assert voice.SAMPLE.is_file()
    out = voice.transcribe(voice.SAMPLE)
    assert out["status"] == "ok" and out["text"] == "第1段"


def test_default_asr_without_capswriter_is_skipped_by_voice(monkeypatch):
    monkeypatch.setattr(ai_config, "load", lambda: ai_config._deep_merge(
        ai_config.DEFAULTS, {"asrAI": {"port": free_port()}}))
    out = voice.transcribe(voice.SAMPLE)
    assert out["status"] == "skipped" and out["code"] == "SKIPPED.NOT_CONFIGURED"
