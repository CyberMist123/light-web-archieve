"""pickfolder 的补充用例（现有 test_pickfolder_1009.py 已盖 CLI 形状；这里钉分支选择和 PowerShell 转义）。

**全程不弹真窗口**：`_tk` / `_powershell` 都用 monkeypatch 换掉，只测 `pick` 的分支选择、
`_ps_quote` 的单引号转义、`_PS` 模板的占位符替换和 `run` 的退出码。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from link_brain import pickfolder
from link_brain import read as _read  # noqa: F401 - pick() 里才 import；先载入，免得在下面把 os.name 换成 nt 时才第一次 import


def test_ps_quote_escapes_single_quotes():
    assert pickfolder._ps_quote("C:\\x") == "'C:\\x'"
    assert pickfolder._ps_quote("O'Brien") == "'O''Brien'"      # 单引号翻倍
    assert pickfolder._ps_quote(123) == "'123'"                 # 非字符串先 str()


def test_ps_template_takes_title_and_initial():
    script = pickfolder._PS.format(title=pickfolder._ps_quote("选一个文件夹"), initial="")
    assert "$d.Description='选一个文件夹'" in script and "{title}" not in script
    script2 = pickfolder._PS.format(title=pickfolder._ps_quote("T"),
                                    initial=f"$d.SelectedPath={pickfolder._ps_quote('D:\\\\x')};")
    assert "$d.SelectedPath='D:\\\\x';" in script2


def test_pick_prefers_tk_and_reports_selection(monkeypatch):
    monkeypatch.setattr(pickfolder, "_tk", lambda title, initial: {"path": "D:\\相册", "canceled": False, "via": "tk"})
    out = pickfolder.pick("选相册", "D:\\")
    assert out["ok"] is True and out["via"] == "tk" and out["path"] == "D:\\相册"
    assert out["canceled"] is False and "选了" in out["message"]


def test_pick_reports_cancel_as_ok(monkeypatch):
    monkeypatch.setattr(pickfolder, "_tk", lambda title, initial: {"path": "", "canceled": True, "via": "tk"})
    out = pickfolder.pick()
    assert out["ok"] is True and out["canceled"] is True and "取消" in out["message"]


def test_pick_falls_back_to_powershell_when_tk_dies(monkeypatch):
    monkeypatch.setattr(pickfolder.os, "name", "nt")             # PowerShell 回退只在 Windows 走；Linux CI 上也要测到
    def boom(title, initial):
        raise RuntimeError("没有 tkinter")
    monkeypatch.setattr(pickfolder, "_tk", boom)
    monkeypatch.setattr(pickfolder, "_powershell",
                        lambda title, initial, timeout: {"path": "C:\\收到", "canceled": False, "via": "powershell"})
    out = pickfolder.pick()
    assert out["ok"] is True and out["via"] == "powershell" and out["path"] == "C:\\收到"


def test_pick_collects_both_errors_and_suggests_paste(monkeypatch):
    monkeypatch.setattr(pickfolder.os, "name", "nt")             # PowerShell 回退只在 Windows 走；Linux CI 上也要测到
    def tk_boom(title, initial):
        raise RuntimeError("没有 tkinter")
    def ps_boom(title, initial, timeout):
        raise OSError("对话框挂了")
    monkeypatch.setattr(pickfolder, "_tk", tk_boom)
    monkeypatch.setattr(pickfolder, "_powershell", ps_boom)
    out = pickfolder.pick()
    assert out["ok"] is False
    assert "tkinter：RuntimeError: 没有 tkinter" in out["message"]
    assert "PowerShell：OSError: 对话框挂了" in out["message"]
    assert "请直接粘贴路径" in out["message"]


def test_pick_non_windows_skips_powershell(monkeypatch):
    def tk_boom(title, initial):
        raise RuntimeError("没有 tkinter")
    called = []
    monkeypatch.setattr(pickfolder, "_tk", tk_boom)
    monkeypatch.setattr(pickfolder, "_powershell", lambda *a, **k: called.append(1))
    monkeypatch.setattr(pickfolder.os, "name", "posix")
    out = pickfolder.pick()
    assert out["ok"] is False and not called
    assert "PowerShell" not in out["message"]                    # 非 Windows 不试 PowerShell


def test_run_exit_codes_and_json(monkeypatch, capsys):
    monkeypatch.setattr(pickfolder, "pick", lambda *a, **k: {"ok": True, "code": "", "message": "选了 D:\\x",
                                                             "path": "D:\\x", "canceled": False, "via": "tk"})
    assert pickfolder.run(SimpleNamespace(title="", initial="")) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(last)["ok"] is True

    monkeypatch.setattr(pickfolder, "pick", lambda *a, **k: {"ok": False, "code": "", "message": "弹不出来",
                                                             "path": "", "canceled": False, "via": ""})
    assert pickfolder.run(SimpleNamespace(title="", initial="")) == 1
    captured = capsys.readouterr()
    assert "弹不出来" in captured.err
    assert json.loads(captured.out.strip().splitlines()[-1])["ok"] is False
