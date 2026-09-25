"""0926：版面判断（表格 / 图片 / 文字）、语音识别自定义接口、视频画面文字去重。都不联网。"""
import json
from pathlib import Path

import httpx

from link_brain import screentext, visual, voice


def _line(text, x, y, w=80, h=20):
    return {"text": text, "box": [x, y, x + w, y + h], "score": 0.9}


def test_table_needs_aligned_columns():
    rows = [("控制对象", "默认值", "到期后"), ("Frequency", "normal", "恢复 normal"),
            ("factor", "1", "恢复 1"), ("Source", "enabled", "恢复 enabled")]
    lines = [_line(cell, 20 + j * 200, 100 + i * 50) for i, row in enumerate(rows) for j, cell in enumerate(row)]
    assert visual.classify(lines) == "table"


def test_paragraph_text_is_not_a_table():
    lines = [_line("这是一段很长的正文，被图片宽度折断成很多行" * 2, 20, 100 + i * 40, w=900) for i in range(8)]
    assert visual.classify(lines) == "text"


def test_scattered_labels_are_not_a_table():
    lines = [_line("标题文字比较长一些", 20, 100), _line("价格", 500, 104), _line("一段说明文字写在这里", 60, 300),
             _line("另一句", 700, 500), _line("最后一行说明文字", 30, 700)]
    assert visual.classify(lines) == "text"


def test_almost_no_text_is_a_picture():
    assert visual.classify([_line("封面", 10, 10)]) == "picture"
    assert visual.classify([]) == "picture"


def test_voice_custom_endpoint(monkeypatch, tmp_path):
    audio = tmp_path / "a.webm"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(voice.ai_config, "load", lambda: {"asrAI": {
        "mode": "http", "endpoint": "https://asr.example/v1/audio/transcriptions", "apiKey": "k", "model": "whisper-1"}})
    monkeypatch.setattr(voice, "_to_wav", lambda src, dest: dest.write_bytes(b"RIFF"))
    seen = {}

    def post(url, headers, timeout, data, files):
        seen.update(url=url, auth=headers.get("Authorization"), model=data["model"], name=files["file"][0])
        return httpx.Response(200, json={"text": " 最近收藏的菜谱有哪些 "}, request=httpx.Request("POST", url))
    monkeypatch.setattr(voice.httpx, "post", post)
    assert voice.transcribe(audio) == {"status": "ok", "text": "最近收藏的菜谱有哪些"}
    assert seen == {"url": "https://asr.example/v1/audio/transcriptions", "auth": "Bearer k",
                    "model": "whisper-1", "name": "voice.wav"}


def test_voice_off_and_missing_endpoint(monkeypatch, tmp_path):
    audio = tmp_path / "a.webm"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(voice.ai_config, "load", lambda: {"asrAI": {"mode": "off"}})
    assert voice.transcribe(audio)["status"] == "off"
    monkeypatch.setattr(voice.ai_config, "load", lambda: {"asrAI": {"mode": "http", "endpoint": ""}})
    monkeypatch.setattr(voice, "_to_wav", lambda src, dest: dest.write_bytes(b"RIFF"))
    assert "接口地址" in voice.transcribe(audio)["error"]


def test_screen_text_keeps_first_time_and_drops_repeats(monkeypatch, tmp_path):
    frames = ["蒜香鱼片", "蒜香鱼片", "水开关火鱼片放下去煮开捞出", "水开关火鱼片放下去煮开捞出。", "", "最后撒上葱花即可"]

    def fake_ffmpeg(cmd, **kw):
        out = Path(cmd[-1]).parent
        for i in range(len(frames)):
            (out / f"f{i + 1:04d}.jpg").write_bytes(b"x")
    monkeypatch.setattr(screentext.subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(visual, "available", lambda: True)
    monkeypatch.setattr(visual, "local_ocr", lambda p: {"lines": [{"text": frames[int(p.stem[1:]) - 1], "score": 0.9}]
                                                          if frames[int(p.stem[1:]) - 1] else []})
    result = screentext.extract(tmp_path / "v.mp4")
    assert [(s["t"], s["text"]) for s in result["segments"]] == [
        (0, "蒜香鱼片"), (4, "水开关火鱼片放下去煮开捞出"), (10, "最后撒上葱花即可")]
