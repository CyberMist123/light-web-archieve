"""Windows 计划任务 `LinkBrainRemote`：远程阅读服务的「常驻」做法（不挂在 Obsidian 下）。

- 启用 = 注册（当前用户、只在登录时运行、普通权限，不要管理员）+ 立即启动：
  · 触发器 1：登录时；触发器 2：从现在起每 5 分钟一次（没在跑就拉起，在跑就忽略——MultipleInstances IgnoreNew），
    等于一个看门狗：服务崩了 / 端口改了自己退出后，最迟 5 分钟回来。
  · 动作：`pythonw.exe -m link_brain remote serve --vault <vault> --state-dir <状态目录> [--settings <data.json>]`，
    工作目录 = 程序目录；没有 pythonw 才用 python.exe。
- 停用 = Stop-ScheduledTask + Unregister-ScheduledTask，再确认服务进程真的没了。
- 改法照 sync_schedule.py：PowerShell ScheduledTasks 模块；任务名可用 env LINK_BRAIN_REMOTE_TASK 覆盖（测试 / 验收用）。
- 非 Windows：不自动注册，如实返回「请手动启动」和命令。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .. import sync_schedule

DEFAULT_TASK = "LinkBrainRemote"
REPEAT_MIN = 5


def task_name() -> str:
    return os.environ.get("LINK_BRAIN_REMOTE_TASK") or DEFAULT_TASK


def supported() -> bool:
    return sys.platform == "win32"


def _ps(cmd: str) -> tuple[bool, str]:
    return sync_schedule._ps(cmd)


def _q(text: str) -> str:
    """PowerShell 单引号字面量。"""
    return "'" + str(text).replace("'", "''") + "'"


def _arg(text: str) -> str:
    """Windows 命令行参数：有空格 / 引号才加双引号（路径里常有空格）。"""
    s = str(text)
    if s and not any(c in s for c in ' \t"'):
        return s
    return '"' + s.replace('"', '\\"') + '"'


def pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.is_file() else exe)


def serve_args(vault: str, state_dir: str, settings: str | None = None) -> list[str]:
    args = ["-m", "link_brain", "remote", "serve", "--vault", vault, "--state-dir", state_dir]
    if settings:
        args += ["--settings", settings]
    return args


def manual_command(vault: str, state_dir: str, settings: str | None = None) -> str:
    return " ".join(["python"] + [_arg(a) for a in serve_args(vault, state_dir, settings)])


def register_script(exe: str, args: list[str], workdir: str) -> str:
    name = _q(task_name())
    argline = " ".join(_arg(a) for a in args)
    return (
        "$ErrorActionPreference='Stop';"
        "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
        f"$a=New-ScheduledTaskAction -Execute {_q(exe)} -Argument {_q(argline)} -WorkingDirectory {_q(workdir)};"
        "$t1=New-ScheduledTaskTrigger -AtLogOn -User $u;"
        f"$t2=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes {REPEAT_MIN});"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1);"
        "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited;"
        f"Register-ScheduledTask -TaskName {name} -Action $a -Trigger @($t1,$t2) -Settings $s -Principal $p "
        f"-Description {_q('Link Brain 远程阅读（只读 MCP，只监听 127.0.0.1）。在 Obsidian → Link Brain 设置 → 高级设置 → 远程阅读里停用会删掉本任务。')} -Force | Out-Null;"
        f"Start-ScheduledTask -TaskName {name};'ok'"
    )


def unregister_script() -> str:
    name = _q(task_name())
    return (f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
            "if(-not $t){'none'}else{"
            f"Stop-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
            f"Unregister-ScheduledTask -TaskName {name} -Confirm:$false -ErrorAction Stop;'ok'}}")


def state_script() -> str:
    name = _q(task_name())
    return (f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
            "if(-not $t){'none'}else{"
            f"$i=Get-ScheduledTaskInfo -TaskName {name};"
            "\"$($t.State)|$($i.LastRunTime.ToString('s'))|$($i.LastTaskResult)|$($t.Actions[0].Execute)|$($t.Actions[0].Arguments)\"}")


def _denied_hint(out: str) -> str:
    if "Access is denied" in out or "拒绝访问" in out:
        return out + "（注册计划任务被拒绝：可能被系统策略限制。可以改用手动启动命令）"
    return out


def _failed(msg: str) -> str:
    """计划任务操作失败：进问题记录（问题列表里查得到），返回故障码。"""
    try:
        from .. import problems
        problems.report("remote", "PERMANENT.REMOTE_TASK_FAILED", msg)
    except Exception:  # noqa: BLE001
        pass
    return "PERMANENT.REMOTE_TASK_FAILED"


def _resolved() -> None:
    try:
        from .. import problems
        problems.resolve("remote", code="PERMANENT.REMOTE_TASK_FAILED")
    except Exception:  # noqa: BLE001
        pass


def register(vault: str, state_dir: str, settings: str | None = None, *, repo: str | None = None) -> dict[str, Any]:
    from .. import storage
    if not supported():
        return {"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "message": "这台电脑不是 Windows：请手动启动（命令见下）",
                "command": manual_command(vault, state_dir, settings)}
    ok, out = _ps(register_script(pythonw(), serve_args(vault, state_dir, settings), repo or str(storage.repo_root())))
    if not ok:
        return {"ok": False, "code": _failed("没注册上计划任务：" + _denied_hint(out)[:300]), "message": "没注册上计划任务：" + _denied_hint(out)[:300],
                "command": manual_command(vault, state_dir, settings)}
    _resolved()
    return {"ok": True, "code": "", "message": f"已注册并启动计划任务 {task_name()}", "task": task_name()}


def unregister() -> dict[str, Any]:
    if not supported():
        return {"ok": True, "code": "", "message": "这台电脑不是 Windows：没有计划任务要删；手动起的服务请自己关掉"}
    ok, out = _ps(unregister_script())
    if not ok:
        msg = "计划任务没删掉：" + _denied_hint(out)[:300]
        return {"ok": False, "code": _failed(msg), "message": msg}
    _resolved()
    return {"ok": True, "code": "", "message": "已停止并删除计划任务" if out.strip().endswith("ok") else "本来就没有计划任务"}


def restart() -> dict[str, Any]:
    if not supported():
        return {"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "message": "这台电脑不是 Windows：请手动重启服务"}
    name = _q(task_name())
    ok, out = _ps(f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
                  f"if(-not $t){{'none'}}else{{Stop-ScheduledTask -TaskName {name};Start-Sleep -Milliseconds 800;"
                  f"Start-ScheduledTask -TaskName {name};'ok'}}")
    if not ok:
        msg = "重启没成功：" + out[:300]
        return {"ok": False, "code": _failed(msg), "message": msg}
    if out.strip().endswith("none"):
        return {"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "message": "还没启用（没有计划任务）"}
    return {"ok": True, "code": "", "message": "已重启"}


def state() -> dict[str, Any]:
    if not supported():
        return {"supported": False, "registered": False}
    ok, out = _ps(state_script())
    if not ok:
        return {"supported": True, "registered": None, "error": out[:300]}
    val = out.strip().splitlines()[-1] if out.strip() else ""
    if val == "none":
        return {"supported": True, "registered": False}
    parts = (val.split("|") + [""] * 5)[:5]
    try:
        last = int(parts[2])
    except ValueError:
        last = None
    return {"supported": True, "registered": True, "state": parts[0], "last_run": parts[1], "last_result": last,
            "execute": parts[3], "arguments": parts[4]}
