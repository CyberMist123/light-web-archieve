"""1103 干净 Win11 实测：没装 VC++ 运行库时 rapidocr（pyclipper）导入报 DLL load failed。
OCR 安装那一步缺运行库就补装 msvc-runtime；装了还加载不上如实说去装微软的可再发行程序包；不是 Windows / 已有就什么都不做。
check 那一行：Windows 上缺运行库算 partial（点安装自动补），不再说「可用」。"""
from __future__ import annotations

import pytest

from link_brain.setup import components as C
from link_brain.setup.common import SetupError


def test_not_windows_does_nothing(monkeypatch):
    monkeypatch.setattr(C.sys, "platform", "linux")
    monkeypatch.setattr(C, "_pip_install", lambda *a, **k: pytest.fail("不该装"))
    assert C._ensure_vc_runtime(None) is False


def test_already_there_does_nothing(monkeypatch):
    monkeypatch.setattr(C.sys, "platform", "win32")
    monkeypatch.setattr(C, "_vc_runtime_ok", lambda: True)
    monkeypatch.setattr(C, "_pip_install", lambda *a, **k: pytest.fail("不该装"))
    assert C._ensure_vc_runtime(None) is False


def test_missing_installs_msvc_runtime(monkeypatch):
    monkeypatch.setattr(C.sys, "platform", "win32")
    state = {"ok": False}
    monkeypatch.setattr(C, "_vc_runtime_ok", lambda: state["ok"])
    calls, events = [], []

    def fake_pip(component, specs, emit):
        calls.append((component, specs))
        state["ok"] = True
    monkeypatch.setattr(C, "_pip_install", fake_pip)
    assert C._ensure_vc_runtime(events.append) is True
    assert calls == [("ocr", [C.VC_RUNTIME_SPEC])]
    assert events and events[0]["phase"] == "补运行库"


def test_still_missing_says_what_to_do(monkeypatch):
    monkeypatch.setattr(C.sys, "platform", "win32")
    monkeypatch.setattr(C, "_vc_runtime_ok", lambda: False)
    monkeypatch.setattr(C, "_pip_install", lambda *a, **k: None)
    with pytest.raises(SetupError) as e:
        C._ensure_vc_runtime(None)
    assert e.value.code == "PERMANENT.BAD_PACKAGE"
    assert "Visual C++" in e.value.message


def test_check_row_partial_when_runtime_missing(monkeypatch):
    monkeypatch.setattr(C.sys, "platform", "win32")
    monkeypatch.setattr(C, "_vc_runtime_ok", lambda: False)
    monkeypatch.setattr(C, "_has", lambda m: True)
    monkeypatch.setattr(C, "_ocr_settings", lambda: ("small", "", "local"))
    row = C._ocr()["row"]
    assert row["status"] == "partial"
    assert "VC++" in row["detail"]
