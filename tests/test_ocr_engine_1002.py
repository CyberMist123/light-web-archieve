"""1002：本地 OCR 升到 RapidOCR 3.x + PP-OCRv6；档位 / 模型目录来自设置，老包只做兜底。"""
import sys
import types

import pytest

from link_brain import visual


class _FakeRes:
    def __init__(self):
        self.boxes = [[[0, 0], [10, 0], [10, 5], [0, 5]]]
        self.txts = ("你好",)
        self.scores = (0.9,)


def _install_fake_rapidocr(monkeypatch, seen):
    mod = types.ModuleType("rapidocr")

    class RapidOCR:
        def __init__(self, params=None):
            seen.append(params)

        def __call__(self, path):
            return _FakeRes()

    mod.RapidOCR = RapidOCR
    utils = types.ModuleType("rapidocr.utils")
    typings = types.ModuleType("rapidocr.utils.typings")
    typings.ModelType = lambda v: f"MT:{v}"

    class OCRVersion:
        PPOCRV6 = "PP-OCRv6"

    typings.OCRVersion = OCRVersion
    monkeypatch.setitem(sys.modules, "rapidocr", mod)
    monkeypatch.setitem(sys.modules, "rapidocr.utils", utils)
    monkeypatch.setitem(sys.modules, "rapidocr.utils.typings", typings)
    monkeypatch.setattr(visual, "_ENGINE", None)
    monkeypatch.setattr(visual, "_ENGINE_KEY", None)


def test_v3_engine_uses_ppocrv6_and_configured_tier(monkeypatch, tmp_path):
    seen = []
    _install_fake_rapidocr(monkeypatch, seen)
    (tmp_path / "PP-OCRv6_det_medium.onnx").write_bytes(b"x")
    (tmp_path / "PP-OCRv6_rec_medium.onnx").write_bytes(b"x")
    monkeypatch.setattr(visual, "ocr_settings", lambda: ("medium", str(tmp_path)))
    lines = visual._ocr_lines(tmp_path / "a.png")
    assert lines and lines[0]["text"] == "你好"
    p = seen[-1]
    assert p["Det.ocr_version"] == "PP-OCRv6" and p["Rec.model_type"] == "MT:medium" and p["Global.log_level"] == "warning"
    assert p["Det.model_path"].endswith("PP-OCRv6_det_medium.onnx")
    assert visual.engine_label() == "rapidocr-ppocrv6-medium"


def test_missing_model_dir_files_is_an_error_not_a_silent_downgrade(monkeypatch, tmp_path):
    _install_fake_rapidocr(monkeypatch, [])
    monkeypatch.setattr(visual, "ocr_settings", lambda: ("medium", str(tmp_path)))
    with pytest.raises(FileNotFoundError):
        visual._engine()


def test_bundled_small_needs_no_model_dir(monkeypatch, tmp_path):
    seen = []
    _install_fake_rapidocr(monkeypatch, seen)
    monkeypatch.setattr(visual, "ocr_settings", lambda: ("small", ""))
    visual._engine()
    assert "Det.model_path" not in seen[-1]


def test_medium_default_falls_back_to_small_when_model_cannot_load(monkeypatch, tmp_path):
    seen = []
    _install_fake_rapidocr(monkeypatch, seen)
    import rapidocr

    real = rapidocr.RapidOCR

    class Flaky(real):
        def __init__(self, params=None):
            if params and params.get("Det.model_type") == "MT:medium":
                raise OSError("download failed")
            super().__init__(params)

    monkeypatch.setattr(rapidocr, "RapidOCR", Flaky)
    reported = []
    monkeypatch.setattr(visual, "_report_fallback", lambda tier, exc: reported.append(tier))
    monkeypatch.setattr(visual, "ocr_settings", lambda: ("medium", ""))
    visual._engine()
    assert reported == ["medium"] and seen[-1]["Det.model_type"] == "MT:small"
    assert visual.engine_label() == "rapidocr-ppocrv6-small"


def test_default_tier_is_medium(monkeypatch):
    from link_brain import ai_config
    monkeypatch.setattr(ai_config, "load", lambda: {"ocr": {"mode": "local"}})
    assert visual.ocr_settings() == ("medium", "")
