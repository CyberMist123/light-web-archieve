"""本机「选文件夹」对话框（1009 她：「选本机文件夹」要真的弹得出来）。

插件里 Electron 的 dialog 在新版 Obsidian 拿不到（electron.remote 没了），由这里弹：
先 tkinter（Tk 8.6 在 Windows 上是系统新式的选文件夹对话框），没有 tkinter / 出错就退回 PowerShell 的
FolderBrowserDialog。两种都挂一个置顶的无形窗口当主人——以前隐藏窗口的子进程弹框常常躲在 Obsidian 后面，看着像「没反应」。

`python -m link_brain pick-folder [--title T] [--initial DIR]` → 最后一行 JSON：
`{ok, code, message, path, canceled, via}`；她点了取消 = ok:true + canceled:true（不是失败）。
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from typing import Any

DEFAULT_TITLE = "选一个文件夹"


def _tk(title: str, initial: str | None) -> dict[str, Any]:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        path = filedialog.askdirectory(parent=root, title=title, initialdir=initial or None, mustexist=True)
    finally:
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
    path = os.path.normpath(path) if path else ""
    return {"path": path, "canceled": not path, "via": "tk"}


_PS = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$o=New-Object System.Windows.Forms.Form -Property @{{TopMost=$true;ShowInTaskbar=$false;"
    "StartPosition='CenterScreen';Width=1;Height=1;Opacity=0}};$o.Show();$o.Activate();"
    "$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description={title};$d.ShowNewFolderButton=$true;"
    "{initial}"
    "if($d.ShowDialog($o) -eq [System.Windows.Forms.DialogResult]::OK){{[Console]::Out.Write($d.SelectedPath)}};"
    "$o.Close();$o.Dispose()"
)


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _powershell(title: str, initial: str | None, timeout: float) -> dict[str, Any]:
    init = f"$d.SelectedPath={_ps_quote(initial)};" if initial else ""
    script = _PS.format(title=_ps_quote(title), initial=init)
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand", enc], capture_output=True,
                          timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    path = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0 and not path:
        raise RuntimeError(((proc.stderr or b"").decode("utf-8", "replace").strip().splitlines() or ["PowerShell 出错"])[-1])
    return {"path": os.path.normpath(path) if path else "", "canceled": not path, "via": "powershell"}


def pick(title: str = DEFAULT_TITLE, initial: str | None = None, *, timeout: float = 600) -> dict[str, Any]:
    """弹系统选文件夹对话框，等她选完。返回 {ok, code, message, path, canceled, via}。"""
    from .read import outcome
    errors = []
    for how in (_tk, None):
        try:
            got = how(title, initial) if how else (_powershell(title, initial, timeout) if os.name == "nt" else None)
        except Exception as exc:  # noqa: BLE001 - 这一种弹不出来就换下一种
            errors.append(f"{'tkinter' if how else 'PowerShell'}：{type(exc).__name__}: {exc}"[:160])
            continue
        if got is None:
            break
        msg = "没选（取消了）" if got["canceled"] else f"选了 {got['path']}"
        return outcome(got, ok=True, message=msg)
    why = "；".join(errors) or "这台电脑没有可用的选文件夹对话框"
    return outcome({"path": "", "canceled": False, "via": ""}, ok=False, code="",
                   message=f"选文件夹的对话框弹不出来（{why}）：请直接粘贴路径")


def add_parser(sub) -> None:
    p = sub.add_parser("pick-folder", help="弹本机「选文件夹」对话框（插件「选本机文件夹」用），输出 JSON")
    p.add_argument("--title", default=DEFAULT_TITLE)
    p.add_argument("--initial", default="", help="一开始停在哪个文件夹")


def run(args) -> int:
    from .read import dump_json
    out = pick(args.title or DEFAULT_TITLE, args.initial or None)
    if not out.get("ok"):
        print(out.get("message"), file=sys.stderr)
    dump_json(out)
    return 0 if out.get("ok") else 1
