"""r4-d1 补测：视频画面抽字（ffmpeg 绝不真跑：subprocess.run 全程打桩；OCR 用假帧 + 打桩 local_ocr）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from link_brain import screentext, visual


def test_skipped_when_no_local_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "available", lambda: False)
    out = screentext.extract(tmp_path / "v.mp4")
    assert out == {"status": "skipped", "error": "未安装本地 OCR（pip install rapidocr）"}


def test_ffmpeg_failure_returns_failed_with_exc_name(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "available", lambda: True)
    seen_args = []

    def fake_run(args, **kwargs):
        seen_args.append(args)
        raise FileNotFoundError("ffmpeg 不在 PATH")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = screentext.extract(tmp_path / "v.mp4")
    assert out["status"] == "failed" and out["error"] == "抽帧失败: FileNotFoundError"
    assert out == {"status": "failed", "error": "抽帧失败: FileNotFoundError"}  # 失败时不多带别的键
    # 抽帧参数：定帧率 2 秒一帧、最多 90 帧、压到 720 宽
    args = seen_args[0]
    assert args[0] == "ffmpeg" and str(tmp_path / "v.mp4") in args
    assert f"fps=1/{screentext.FRAME_EVERY_SECONDS},scale=720:-2" in args
    assert str(screentext.MAX_FRAMES) in args

    for exc in (subprocess.CalledProcessError(1, "ffmpeg"), subprocess.TimeoutExpired("ffmpeg", 300)):
        monkeypatch.setattr(subprocess, "run", lambda *a, e=exc, **kw: (_ for _ in ()).throw(e))
        assert screentext.extract(tmp_path / "v.mp4") == {"status": "failed",
                                                          "error": f"抽帧失败: {type(exc).__name__}"}


def test_extract_keeps_fresh_lines_only(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "available", lambda: True)
    # 假抽帧：往临时目录写 4 张假帧（run 的最后一个参数是输出模板）
    def fake_run(args, **kwargs):
        out = Path(args[-1]).parent
        for i in range(1, 5):
            (out / f"f{i:04d}.jpg").write_bytes(b"x")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    scripted = {
        "f0001.jpg": [  # 第一帧：留下正文行；丢 低分 / 乱码单字 / 空文本
            {"text": "今天教你做红烧肉", "score": 0.9},
            {"text": "低分行", "score": 0.5},
            {"text": "买", "score": 0.9},
            {"text": "   ", "score": 0.9},
        ],
        "f0002.jpg": [  # 原句重复不记；新句记一段
            {"text": "今天教你做红烧肉", "score": 0.9},
            {"text": "第二步加冰糖", "score": 0.9},
        ],
        "f0003.jpg": [  # 标点差异（norm 后同 key）和 94% 相似（≥85）都不算新行；全新短句算
            {"text": "今天教你做红烧肉！", "score": 0.9},
            {"text": "今天教你做红烧肉哦", "score": 0.9},
            {"text": "成品展示", "score": 0.9},
        ],
        "f0004.jpg": None,  # 单帧 OCR 失败：没有 lines 键 → 当没字，不炸
    }

    def fake_ocr(path):
        lines = scripted.get(Path(path).name)
        return {"status": "failed"} if lines is None else {"status": "ok", "lines": lines}

    monkeypatch.setattr(visual, "local_ocr", fake_ocr)
    out = screentext.extract(tmp_path / "v.mp4")
    assert out["status"] == "ok" and out["v"] == screentext.VERSION
    assert out["segments"] == [
        {"t": 0 * screentext.FRAME_EVERY_SECONDS, "text": "今天教你做红烧肉"},
        {"t": 1 * screentext.FRAME_EVERY_SECONDS, "text": "第二步加冰糖"},
        {"t": 2 * screentext.FRAME_EVERY_SECONDS, "text": "成品展示"},
    ]
    assert out["text"] == "今天教你做红烧肉\n第二步加冰糖\n成品展示"


def test_no_frames_means_ok_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "available", lambda: True)
    ocr_calls = []

    def fake_run(args, **kwargs):  # 抽帧成功但一帧都没出（比如视频极短 / 解不出）
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(visual, "local_ocr", lambda p: ocr_calls.append(p) or {"status": "ok", "lines": []})
    out = screentext.extract(tmp_path / "v.mp4")
    assert out == {"status": "ok", "v": screentext.VERSION, "segments": [], "text": ""}
    assert ocr_calls == []  # 没帧就不调 OCR
