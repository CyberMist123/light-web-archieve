"""1009 她：「选本机文件夹」要真的弹得出来。插件拿不到 Electron 对话框时由 Python 弹（tkinter → PowerShell 兜底）。
真机弹框截图见验收记录；这里只测分支和输出形状（不弹框）。"""

from __future__ import annotations

import json

from link_brain import cli, pickfolder


def test_tk_result_is_returned(monkeypatch, capsys):
    monkeypatch.setattr(pickfolder, "_tk", lambda title, initial: {"path": r"D:\笔记", "canceled": False, "via": "tk"})
    assert cli.main(["pick-folder", "--title", "选一个"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["path"] == r"D:\笔记" and out["via"] == "tk"


def test_cancel_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(pickfolder, "_tk", lambda title, initial: {"path": "", "canceled": True, "via": "tk"})
    out = pickfolder.pick()
    assert out["ok"] is True and out["canceled"] is True and "取消" in out["message"]


def test_falls_back_to_powershell_then_reports_plainly(monkeypatch):
    def broken(*a):
        raise RuntimeError("no display")
    monkeypatch.setattr(pickfolder, "_tk", broken)
    monkeypatch.setattr(pickfolder.os, "name", "nt")
    monkeypatch.setattr(pickfolder, "_powershell", lambda title, initial, timeout: {"path": r"E:\资料", "canceled": False, "via": "powershell"})
    assert pickfolder.pick()["via"] == "powershell"
    monkeypatch.setattr(pickfolder, "_powershell", broken)
    out = pickfolder.pick()
    assert out["ok"] is False and "请直接粘贴路径" in out["message"] and "tkinter" in out["message"]
