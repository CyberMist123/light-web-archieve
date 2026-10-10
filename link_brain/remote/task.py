"""Windows 计划任务 `LwaMcp`（10-09 前叫 LinkBrainRemote）：远程 MCP 服务的「常驻」做法（不挂在 Obsidian 下）。

- 启用 = 注册（当前用户、只在登录时运行、普通权限，不要管理员）+ 立即启动：
  · 触发器 1：登录时；触发器 2：从现在起每 5 分钟一次（没在跑就拉起，在跑就忽略——MultipleInstances IgnoreNew），
    等于一个看门狗：服务崩了 / 端口改了自己退出后，最迟 5 分钟回来。
  · 动作：`pythonw.exe -m link_brain remote serve --vault <vault> --state-dir <状态目录> [--settings <data.json>]`，
    工作目录 = 程序目录；没有 pythonw 才用 python.exe。
- 停用 = Stop-ScheduledTask + Unregister-ScheduledTask，再确认服务进程真的没了。
- 重启 / 停用（1010 修）：Stop-ScheduledTask 杀不到动作底下的子孙（hiddenrun → pwsh 启动脚本 → python），旧 python
  占着端口、新实例起来就因端口被占退出，`status` 还是旧进程在应答。所以停任务后再按端口找真正在听的那个进程：
  命令行含 `link_brain remote serve` 的才停，连同它的父进程（仅当父进程是跑 .ps1 的 pwsh / powershell）；只按 PID 停、
  绝不 taskkill /T，绝不碰别的进程（读取服务 link-brain-reader 和它的 chrome）。重启后要看到一个**新的** PID 在听
  才算重启成功，否则如实返回失败。脚本只用 ASCII（本机 .ps1 字面量含非 ASCII 会坏）；找 / 停进程出错一律放过（fail-open）。
- 改法照 sync_schedule.py：PowerShell ScheduledTasks 模块；任务名可用 env LINK_BRAIN_REMOTE_TASK 覆盖（测试 / 验收用）。
- 非 Windows：不自动注册，如实返回「请手动启动」和命令。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .. import sync_schedule

DEFAULT_TASK = "LwaMcp"
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
        f"-Description {_q('LWA MCP 远程服务（搜索 / 阅读 / 主题 / 暗号 / 问收藏，只监听 127.0.0.1）。在 Obsidian → Link Brain 设置 → 远程 MCP 里停用会删掉本任务。')} -Force | Out-Null;"
        f"Start-ScheduledTask -TaskName {name};'ok'"
    )


def _srv_fn(port: int) -> str:
    """PowerShell：$port 上在听、命令行含 link_brain remote serve 的进程（Win32_Process 对象）。出错返回空。"""
    return (f"$port={int(port)};"
            "function Get-LwaSrv{$r=@();"
            "try{$ls=@(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop)}catch{$ls=@()};"
            "foreach($c in $ls){try{$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$c.OwningProcess) -ErrorAction Stop}catch{$p=$null};"
            "if($p -and $p.CommandLine -match 'link_brain\\s+remote\\s+serve' -and -not ($r|Where-Object{$_.ProcessId -eq $p.ProcessId})){$r+=$p}};"
            "return ,$r};")


def _kill_fn() -> str:
    """PowerShell：停 Get-LwaSrv 找到的服务进程和它跑 .ps1 的 pwsh 父进程（先父后子，免得父进程再拉一个），只按 PID、不带进程树。"""
    return ("function Stop-LwaSrv($procs){$k=@();"
            "foreach($p in $procs){"
            "try{$pp=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$p.ParentProcessId) -ErrorAction Stop}catch{$pp=$null};"
            "if($pp -and $pp.Name -match '^(pwsh|powershell)\\.exe$' -and $pp.CommandLine -match '\\.ps1'){"
            "try{Stop-Process -Id $pp.ProcessId -Force -ErrorAction Stop;$k+=$pp.ProcessId}catch{}};"
            "try{Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop;$k+=$p.ProcessId}catch{}};"
            "for($i=0;$i -lt 10 -and @(Get-LwaSrv).Count -gt 0;$i++){Start-Sleep -Milliseconds 500};"
            "return ,$k};")


def unregister_script(port: int | None = None) -> str:
    name = _q(task_name())
    if port is None:
        kill = ""
        head = ""
    else:
        head = "$ErrorActionPreference='SilentlyContinue';" + _srv_fn(port) + _kill_fn()
        kill = "$k=Stop-LwaSrv (Get-LwaSrv);\"killed:$($k -join ',')\";"
    return (head + f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
            "if(-not $t){" + kill + "'none'}else{"
            f"Stop-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;" + kill +
            f"Unregister-ScheduledTask -TaskName {name} -Confirm:$false -ErrorAction Stop;'ok'}}")


def restart_script(port: int, wait_s: int = 30) -> str:
    """停任务 → 停真正在听的旧服务 → 起任务 → 等一个新 PID 在听。输出几行 key:value，最后一行 ok / none。"""
    name = _q(task_name())
    return ("$ErrorActionPreference='SilentlyContinue';" + _srv_fn(port) + _kill_fn() +
            f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
            "if(-not $t){'none'}else{"
            "$old=@(Get-LwaSrv|ForEach-Object{[int]$_.ProcessId});\"old:$($old -join ',')\";"
            f"Stop-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;Start-Sleep -Milliseconds 800;"
            "$k=Stop-LwaSrv (Get-LwaSrv);\"killed:$($k -join ',')\";"
            "$left=@(Get-LwaSrv|ForEach-Object{[int]$_.ProcessId});\"left:$($left -join ',')\";"
            f"Start-ScheduledTask -TaskName {name} -ErrorAction Stop;"
            "$new=@();"
            f"for($i=0;$i -lt {int(wait_s)};$i++){{Start-Sleep -Seconds 1;"
            "$new=@(Get-LwaSrv|ForEach-Object{[int]$_.ProcessId}|Where-Object{$old -notcontains $_});if($new.Count){break}};"
            "\"new:$($new -join ',')\";'ok'}")


def _pids(out: str, key: str) -> list[int]:
    for line in out.splitlines():
        line = line.strip()
        if line.startswith(key + ":"):
            return [int(x) for x in line[len(key) + 1:].split(",") if x.strip().isdigit()]
    return []


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


def unregister(port: int | None = None) -> dict[str, Any]:
    if not supported():
        return {"ok": True, "code": "", "message": "这台电脑不是 Windows：没有计划任务要删；手动起的服务请自己关掉"}
    ok, out = _ps(unregister_script(port))
    if not ok:
        msg = "计划任务没删掉：" + _denied_hint(out)[:300]
        return {"ok": False, "code": _failed(msg), "message": msg}
    _resolved()
    return {"ok": True, "code": "", "message": "已停止并删除计划任务" if out.strip().endswith("ok") else "本来就没有计划任务"}


def restart(port: int = 18071, *, wait_s: int = 30) -> dict[str, Any]:
    if not supported():
        return {"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "message": "这台电脑不是 Windows：请手动重启服务"}
    ok, out = _ps(restart_script(port, wait_s))
    if not ok:
        msg = "重启没成功：" + out[:300]
        return {"ok": False, "code": _failed(msg), "message": msg}
    if out.strip().endswith("none"):
        return {"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "message": "还没启用（没有计划任务）"}
    old, killed, left, new = (_pids(out, k) for k in ("old", "killed", "left", "new"))
    info = {"old_pids": old, "killed_pids": killed, "new_pids": new}
    if left:
        msg = f"重启没成功：旧服务进程（PID {','.join(map(str, left))}）停不掉，还占着端口 {port}，新代码 / 设置没生效"
        return {"ok": False, "code": _failed(msg), "message": msg, **info}
    if not new:
        msg = (f"重启没确认：计划任务已拉起，但 {wait_s} 秒内没看到新的服务进程在听端口 {port}"
               "（机器忙时可能还在启动，稍后看状态；一直没有就看 remote status / 问题列表）")
        return {"ok": False, "code": _failed(msg), "message": msg, **info}
    _resolved()
    was = f"{','.join(map(str, old))} → " if old else ""
    return {"ok": True, "code": "", "message": f"已重启（服务进程 {was}{','.join(map(str, new))}）", **info}


def state() -> dict[str, Any]:
    if not supported():
        return {"supported": False, "registered": False}
    ok, out = _ps(state_script())
    if not ok:
        return {"supported": True, "registered": None, "error": out[:300]}
    val = out.strip().splitlines()[-1] if out.strip() else ""
    if val == "none":
        return {"supported": True, "registered": False, "name": task_name()}
    parts = (val.split("|") + [""] * 5)[:5]
    try:
        last = int(parts[2])
    except ValueError:
        last = None
    return {"supported": True, "registered": True, "name": task_name(), "state": parts[0], "last_run": parts[1], "last_result": last,
            "execute": parts[3], "arguments": parts[4]}
