"""r5 补测：语音转文字的调度层（asr / ffmpeg / providers 全打桩——本机可能真跑着 CapsWriter，绝不碰）。"""
from __future__ import annotations

from pathlib import Path

from link_brain import asr, providers, voice


def test_not_configured_says_where_to_turn_on(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "resolve", lambda cap: None)
    r = voice.transcribe(tmp_path / "a.mp3")
    assert r["status"] == "skipped" and r["code"] == "SKIPPED.NOT_CONFIGURED"
    assert r["error"].startswith("语音识别没配置")
    assert r["error"].endswith("在设置 → AI → 语音识别里打开。")


def test_capswriter_mode_requires_running_service(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "resolve", lambda cap: {"mode": "capswriter", "host": "127.0.0.1", "port": 6016})
    monkeypatch.setattr(asr, "available", lambda cfg: False)
    r = voice.transcribe(tmp_path / "a.mp3")
    assert r["status"] == "skipped"
    assert "连不上本机 CapsWriter" in r["error"] and "CapsWriter-Offline" in r["error"]


def test_ready_wav_skips_ffmpeg(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(providers, "resolve", lambda cap: {"mode": "capswriter"})
    monkeypatch.setattr(asr, "available", lambda cfg: True)
    monkeypatch.setattr(asr, "read_pcm16", lambda p: calls.update(read=p))
    monkeypatch.setattr(voice, "_to_wav", lambda src, dest: calls.update(ffmpeg=dest))   # 走到就是错
    monkeypatch.setattr(asr, "transcribe", lambda wav, cfg: calls.update(wav=wav) or {"status": "ok", "text": "你好"})
    src = tmp_path / "现成.wav"
    src.write_bytes(b"RIFF")
    r = voice.transcribe(src)
    assert r == {"status": "ok", "text": "你好"} and calls["wav"] == src   # 原文件直送，不起 ffmpeg
    assert "ffmpeg" not in calls


def test_blank_text_becomes_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "resolve", lambda cap: {"mode": "capswriter"})
    monkeypatch.setattr(asr, "available", lambda cfg: True)
    monkeypatch.setattr(asr, "read_pcm16", lambda p: None)
    monkeypatch.setattr(asr, "transcribe", lambda wav, cfg: {"status": "ok", "text": "   "})
    assert voice.transcribe(tmp_path / "a.wav")["status"] == "empty"


def test_other_audio_converted_via_ffmpeg(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(providers, "resolve", lambda cap: {"mode": "capswriter"})
    monkeypatch.setattr(asr, "available", lambda cfg: True)

    def bad_pcm(p):
        raise ValueError("不是 wav")

    def fake_to_wav(src, dest):
        calls["converted"] = dest
        Path(dest).write_bytes(b"WAV")

    monkeypatch.setattr(asr, "read_pcm16", bad_pcm)
    monkeypatch.setattr(voice, "_to_wav", fake_to_wav)
    monkeypatch.setattr(asr, "transcribe", lambda wav, cfg: {"status": "ok", "text": "转写", "wav": str(wav)})
    src = tmp_path / "录音.m4a"
    src.write_bytes(b"m4a")
    r = voice.transcribe(src)
    assert r["status"] == "ok" and r["wav"] == str(calls["converted"])    # 送转写的是转换出的 wav
    assert r["wav"] != str(src)


def test_ffmpeg_failure_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "resolve", lambda cap: {"mode": "capswriter"})
    monkeypatch.setattr(asr, "available", lambda cfg: True)

    def bad_pcm(p):
        raise ValueError("不是 wav")

    def boom(src, dest):
        raise OSError("ffmpeg 不在 PATH")

    monkeypatch.setattr(asr, "read_pcm16", bad_pcm)
    monkeypatch.setattr(voice, "_to_wav", boom)
    r = voice.transcribe(tmp_path / "a.amr")
    assert r["status"] == "failed" and r["code"] == "PERMANENT.NO_AUDIO"
    assert r["error"] == "录音格式转换失败：需要安装 ffmpeg 并加入 PATH。"


def test_run_exit_codes_and_empty_message(monkeypatch, capsys):
    from link_brain import read as read_mod

    def check(result, expected_rc):
        monkeypatch.setattr(voice, "transcribe", lambda p: dict(result))
        rc = voice.run(type("A", (), {"file": "x.wav"})())
        out = capsys.readouterr().out
        assert rc == expected_rc and "status" in out
        return out

    assert "没听清，再说一次试试。" in check({"status": "empty", "error": None}, 1)   # empty 补人话
    check({"status": "ok", "text": "你好", "error": None}, 0)
    check({"status": "skipped", "error": "没配置", "code": "SKIPPED.NOT_CONFIGURED"}, 0)
    check({"status": "failed", "error": "x", "code": "PERMANENT.NO_AUDIO"}, 1)
