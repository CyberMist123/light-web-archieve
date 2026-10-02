"""1001 审计 A-6 / xc-5：视频转写失败留原因、没人声/没音轨算结论、同因连败退避。

走生产入口 videos.run(--transcribe)：index 里的视频行 → transcribe → transcript.json → 退出码。
ffmpeg 用假 subprocess.run，语音识别用假 asr.transcribe（第 1B 批起走设置里的语音识别，不连真 CapsWriter）。
"""
from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from link_brain import asr, problems, render, screentext, storage, videos

T0 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone(timedelta(hours=10)))


@pytest.fixture
def video_vault(monkeypatch):
    obj = storage.object_dir("xiaohongshu", "v1")
    raw = obj / "raw" / "v0001" / "assets"
    raw.mkdir(parents=True)
    (raw / "video.mp4").write_bytes(b"\x00\x00\x00\x20ftyp" + b"0" * 50)
    storage.write_json(obj / "meta.json", {"item_id": "xhs-v1", "current_version": 1})
    storage.write_json(obj / "raw" / "v0001" / "manifest.json",
                       {"media": [{"role": "video", "file": "raw/v0001/assets/video.mp4"}]})
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE objects(item_id, source, source_id, kind)")
    conn.execute("INSERT INTO objects VALUES('xhs-v1','xiaohongshu','v1','video')")
    monkeypatch.setattr(videos.index, "connect", lambda: _NoClose(conn))
    monkeypatch.setattr(render, "render_object", lambda *a, **k: None)
    monkeypatch.setattr(screentext, "extract", lambda path: {"status": "ok", "segments": [], "text": "画面字"})
    import link_brain.catalog as catalog
    monkeypatch.setattr(catalog, "build", lambda *a, **k: None)
    state = SimpleNamespace(now=T0, calls=[], ffmpeg_err=None, running=True,
                            asr={"status": "ok", "text": "转写文字", "code": "", "error": None, "engine": "CapsWriter-Offline"})
    monkeypatch.setattr(videos, "_now", lambda: state.now)

    def fake_run(args, **kw):
        state.calls.append(args[0])
        if state.ffmpeg_err:
            raise subprocess.CalledProcessError(1, args, b"", state.ffmpeg_err.encode())
        open(args[-1], "wb").write(b"RIFF")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def fake_asr(path, cfg=None):
        state.calls.append("asr")
        return dict(state.asr)
    monkeypatch.setattr(videos.subprocess, "run", fake_run)
    monkeypatch.setattr(asr, "transcribe", fake_asr)
    monkeypatch.setattr(asr, "available", lambda cfg: state.running)
    state.doc = lambda: storage.read_json(obj / "derived" / "transcript.json")
    return state


class _NoClose:
    def __init__(self, conn): self.conn = conn
    def execute(self, *a): return self.conn.execute(*a)
    def close(self): pass


def run_once(capsys=None):
    return videos.run(SimpleNamespace(target=None, transcribe=True))


def test_no_speech_is_a_conclusion_not_a_nightly_failure(video_vault):
    video_vault.asr = {"status": "ok", "text": "", "code": "", "error": None}
    assert run_once() == 0
    doc = video_vault.doc()
    assert doc["status"] == "no_speech" and doc["screen"]["text"] == "画面字"
    assert [r["code"] for r in problems.load() if r["step"] == "videos.transcribe"] == ["PERMANENT.NO_SPEECH"]
    video_vault.calls.clear()
    assert run_once() == 0 and video_vault.calls == []  # 第二晚不再抽音轨、不再上传


def test_video_without_audio_track_is_no_audio(video_vault):
    video_vault.ffmpeg_err = "[out#0/wav @ 0x1] Output file does not contain any stream\nError opening output files"
    assert run_once() == 0
    assert video_vault.doc()["status"] == "no_audio"


def test_failure_reason_is_kept_and_same_reason_backs_off(video_vault, capsys):
    video_vault.asr = {"status": "failed", "text": None, "code": "TRANSIENT.SERVICE_BUSY", "error": "model crashed"}
    for night in range(1, 4):
        video_vault.now = T0 + timedelta(days=night - 1)
        assert run_once() == 2  # 真失败照样让这步亮红
        doc = video_vault.doc()
        assert doc["error"] == "model crashed" and doc["fail_count"] == night
        assert doc["code"] == "TRANSIENT.SERVICE_BUSY"
    assert "model crashed" in capsys.readouterr().err  # 夜跑日志里看得到原因
    assert datetime.fromisoformat(doc["retry_after"]) == T0 + timedelta(days=2 + videos.BACKOFF_DAYS)
    # 退避期：不重试、不算失败
    video_vault.calls.clear()
    video_vault.now = T0 + timedelta(days=5)
    assert run_once() == 0 and video_vault.calls == []
    # 过了退避期再试一次；修好了就转成 ok
    video_vault.now = T0 + timedelta(days=10)
    video_vault.asr = {"status": "ok", "text": "终于转出来了", "code": "", "error": None}
    assert run_once() == 0 and video_vault.doc()["status"] == "ok"
    assert not [r for r in problems.load() if r["step"] == "videos.transcribe"], "转出来了就标已解决"


def test_different_reason_restarts_the_count(video_vault):
    video_vault.asr = {"status": "failed", "text": None, "code": "TRANSIENT.SERVICE_BUSY", "error": "model crashed"}
    run_once(); run_once()
    video_vault.asr = {"status": "failed", "text": None, "code": "TRANSIENT.NETWORK", "error": "服务端中途断开了"}
    assert run_once() == 2
    doc = video_vault.doc()
    assert doc["fail_count"] == 1 and "retry_after" not in doc


def test_old_failed_record_without_reason_is_retried(video_vault):
    storage.write_json(storage.object_dir("xiaohongshu", "v1") / "derived" / "transcript.json",
                       {"status": "failed", "text": "", "error": "本机转写失败"})
    video_vault.asr = {"status": "ok", "text": "", "code": "", "error": None}
    assert run_once() == 0 and video_vault.doc()["status"] == "no_speech"


def test_retry_reuses_screen_text_already_extracted(video_vault, monkeypatch):
    video_vault.asr = {"status": "failed", "text": None, "code": "TRANSIENT.SERVICE_BUSY", "error": "boom"}
    run_once()
    monkeypatch.setattr(screentext, "extract", lambda path: pytest.fail("画面文字抽过了，不该重抽"))
    run_once()
    assert video_vault.doc()["screen"]["text"] == "画面字"


def test_asr_not_running_is_skipped_without_touching_ffmpeg(video_vault):
    """CapsWriter 没开（或语音识别没配）：不抽音轨、不写 transcript.json、不算失败，问题记录里一条步骤级 SKIPPED。"""
    video_vault.running = False
    assert run_once() == 0 and video_vault.calls == []
    assert not (storage.object_dir("xiaohongshu", "v1") / "derived" / "transcript.json").exists()
    rows = [r for r in problems.load() if r["step"] == "videos.transcribe"]
    assert len(rows) == 1 and rows[0]["code"] == "SKIPPED.NOT_CONFIGURED" and rows[0]["item_id"] is None
    assert "语音识别没开" in rows[0]["reason"]
    # 开了以后照常转，并把那条 SKIPPED 标成已解决
    video_vault.running = True
    assert run_once() == 0 and video_vault.doc()["status"] == "ok"
    assert not [r for r in problems.load() if r["step"] == "videos.transcribe"]


def test_asr_off_in_settings_is_skipped(video_vault, monkeypatch):
    from link_brain import ai_config
    monkeypatch.setattr(ai_config, "load", lambda: ai_config._deep_merge(ai_config.DEFAULTS, {"asrAI": {"mode": "off"}}))
    assert run_once() == 0 and video_vault.calls == []
    rows = [r for r in problems.load() if r["step"] == "videos.transcribe"]
    assert rows and rows[0]["code"] == "SKIPPED.DISABLED"
