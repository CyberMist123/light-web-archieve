"""每晚收藏巡检的周期设置（Owner 2026-09-16：设置里能选每天 / 每周 / 关闭）。

巡检本体是 Windows 计划任务 `XhsFavSync`（跑 ~/.xiaohongshu-mcp/xhs-fav-sync.ps1，仓库外的 ops）。
这里只**调它的触发频率 / 启停**，不碰它的动作。改法走 PowerShell 的 ScheduledTasks 模块，
只 Set-ScheduledTask 换触发器、Enable/Disable 启停——不删不重建，最小动作。

开源用户没有这个任务：命令会如实报「找不到任务」，不炸。任务名可用 env LINK_BRAIN_SYNC_TASK 覆盖。
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

TASK = os.environ.get("LINK_BRAIN_SYNC_TASK", "XhsFavSync")
AT = "4:00AM"  # 默认凌晨 4 点
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _norm_time(at: str | None) -> str:
    """接受 '4:00AM' / '04:00' / '16:30' 这类，交给 PowerShell 解析，非法就回默认。"""
    at = (at or "").strip()
    return at or AT


def _ps(cmd: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    return proc.returncode == 0, (err or out)


def get_schedule() -> dict[str, Any]:
    """读当前状态：freq(daily/weekly/unknown/none) + enabled。"""
    ok, out = _ps(
        f"$t=Get-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue;"
        "if(-not $t){'none'}else{"
        "$tr=$t.Triggers[0];$state=$t.State;"
        "if($tr.CimClass.CimClassName -like '*Weekly*'){$f='weekly'}"
        "elseif($tr.CimClass.CimClassName -like '*Daily*'){$f='daily'}else{$f='unknown'};"
        "$hm='';try{$hm=([datetime]$tr.StartBoundary).ToString('HH:mm')}catch{};"
        "$day='';try{if($tr.DaysOfWeek){$day=[string]$tr.DaysOfWeek}}catch{};"
        f"$info=Get-ScheduledTaskInfo -TaskName '{TASK}';"
        "\"$f|$state|$($info.LastRunTime.ToString('s'))|$($info.LastTaskResult)|$($info.NextRunTime.ToString('s'))|$hm|$day\"}"
    )
    if not ok:
        return {"task": TASK, "freq": "none", "enabled": False, "error": out}
    val = out.strip()
    if val == "none":
        return {"task": TASK, "freq": "none", "enabled": False}
    parts = (val.split("|") + [""] * 7)[:7]
    return {"task": TASK, "freq": parts[0], "enabled": parts[1].strip() != "Disabled",
            "last_run": parts[2], "last_result": _int(parts[3]), "next_run": parts[4],
            "time": parts[5] or "04:00", "day": parts[6]}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def set_schedule(freq: str, at: str | None = None, day: str | None = None) -> dict[str, Any]:
    """freq: daily / weekly / off；at: 'HH:mm' 或 '4:00AM'（可选）；day: 周几（weekly，可选）。"""
    at = _norm_time(at)
    if freq == "off":
        ok, out = _ps(f"Disable-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop")
    elif freq in ("daily", "weekly"):
        if freq == "daily":
            trig = f"New-ScheduledTaskTrigger -Daily -At '{at}'"
        else:
            wd = day if day in DAYS else "Monday"
            trig = f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {wd} -At '{at}'"
        ok, out = _ps(
            f"Enable-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop | Out-Null;"
            f"Set-ScheduledTask -TaskName '{TASK}' -Trigger ({trig}) -ErrorAction Stop | Out-Null;'ok'"
        )
    else:
        return {"ok": False, "freq": freq, "error": f"未知周期: {freq}（要 daily/weekly/off）"}
    if not ok and ("Access is denied" in out or "拒绝访问" in out):
        out += "（改计划任务可能要管理员权限；可在任务计划程序里手动改 XhsFavSync 的触发器）"
    return {"ok": ok, "freq": freq, "task": TASK, "detail": out[:240]}


def run(args) -> int:
    from .read import EXIT_ERROR, EXIT_OK, dump_json

    if getattr(args, "set", None):
        result = set_schedule(args.set, getattr(args, "at", None), getattr(args, "day", None))
        dump_json(result)
        return EXIT_OK if result.get("ok") else EXIT_ERROR
    dump_json(get_schedule())
    return EXIT_OK

# ==================================================================================================
# 第 5 批：注册 / 删除跑 `python -m link_brain nightly` 的计划任务（`sync-schedule --install / --uninstall`）。
# 给开源用户用，任务名 LinkBrainNightly（env LINK_BRAIN_NIGHTLY_TASK 可改，测试 / 验收用）；
# 绝不碰作者现有的 XhsFavSync（名字撞上直接拒绝）。上面的触发器读写函数不动。
# ==================================================================================================

NIGHTLY_TASK = "LinkBrainNightly"
LEGACY_TASKS = ("XhsFavSync",)


def nightly_task_name() -> str:
    return os.environ.get("LINK_BRAIN_NIGHTLY_TASK") or NIGHTLY_TASK


def _psq(text: str) -> str:
    """PowerShell 单引号字面量。"""
    return "'" + str(text).replace("'", "''") + "'"


def _winarg(text: str) -> str:
    """Windows 命令行参数：有空白 / 引号才加双引号（路径里常有空格）。"""
    s = str(text)
    if s and not any(c in s for c in ' \t"'):
        return s
    return '"' + s.replace('"', '\\"') + '"'


def _hour_minute(at: str) -> tuple[int, int] | None:
    """'04:00' / '4:00AM' / '10:30 pm' → (时, 分)；格式不对 None。"""
    import re
    m = re.match(r"^(\d{1,2}):([0-5]\d)(\s?[AaPp][Mm])?$", (at or "").strip())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").strip().lower()
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = (hour % 12) + (12 if ampm == "pm" else 0)
    elif hour > 23:
        return None
    return hour, minute


def nightly_python() -> str:
    """计划任务用的解释器：当前 Python 旁边的 pythonw.exe（不弹黑窗）；没有才用当前的。"""
    import sys
    from pathlib import Path
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.is_file() else exe)


def nightly_args(vault: str) -> list[str]:
    return ["-m", "link_brain", "nightly", "--vault", str(vault)]


def nightly_install_script(exe: str, args: list[str], workdir: str, hh: int, mm: int, limit_hours: int) -> str:
    """注册（或覆盖）夜跑任务：当前用户、普通权限、只在登录时运行（不要管理员、不存密码）；每天 hh:mm；
    错过（关机 / 睡眠）就在下次能跑时尽快补跑（StartWhenAvailable）；执行时限 limit_hours 小时；
    上一趟还在跑就不再起（IgnoreNew）；用电池也跑。动作不依赖 Obsidian。"""
    name = _psq(nightly_task_name())
    argline = " ".join(_winarg(a) for a in args)
    return (
        "$ErrorActionPreference='Stop';"
        "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
        f"$a=New-ScheduledTaskAction -Execute {_psq(exe)} -Argument {_psq(argline)} -WorkingDirectory {_psq(workdir)};"
        f"$t=New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours({hh}).AddMinutes({mm}));"
        "$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        f"-ExecutionTimeLimit (New-TimeSpan -Hours {int(limit_hours)}) -MultipleInstances IgnoreNew;"
        "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited;"
        f"Register-ScheduledTask -TaskName {name} -Action $a -Trigger $t -Settings $s -Principal $p "
        f"-Description {_psq('Link Brain 每晚同步收藏并补处理（python -m link_brain nightly）。日志在 ~/.link-brain/nightly.log；在 Link Brain 设置里关闭定时同步会停用或删除本任务。')} "
        "-Force | Out-Null;'ok'"
    )


def nightly_uninstall_script() -> str:
    """删掉夜跑任务。正在跑的这一趟不停（停在半路会伤号），删了以后不再触发。"""
    name = _psq(nightly_task_name())
    return (f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
            "if(-not $t){'none'}else{"
            f"Unregister-ScheduledTask -TaskName {name} -Confirm:$false -ErrorAction Stop;'ok'}}")


def nightly_cron_line(python: str, vault: str, hh: int, mm: int) -> str:
    import shlex
    return (f"{mm} {hh} * * * {shlex.quote(python)} -m link_brain nightly --vault {shlex.quote(str(vault))}"
            " >/dev/null 2>&1")


def nightly_launchd_plist(python: str, vault: str, hh: int, mm: int) -> str:
    from xml.sax.saxutils import escape
    args = "".join(f"<string>{escape(a)}</string>" for a in [python, *nightly_args(vault)])
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            '<key>Label</key><string>com.linkbrain.nightly</string>'
            f'<key>ProgramArguments</key><array>{args}</array>'
            f'<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hh}</integer>'
            f'<key>Minute</key><integer>{mm}</integer></dict>'
            '</dict></plist>\n')


def install_nightly(at: str | None = None, vault: str | None = None, *, platform: str | None = None) -> dict[str, Any]:
    """注册每天跑 nightly 的计划任务。Windows 真注册；macOS / Linux 只给 cron / launchd 建议行。"""
    import sys
    from pathlib import Path
    from . import nightly, storage

    name = nightly_task_name()
    if name in LEGACY_TASKS:
        return {"ok": False, "code": "", "task": name,
                "message": f"任务名 {name} 是旧夜跑脚本的任务，不覆盖它；换一个 LINK_BRAIN_NIGHTLY_TASK"}
    hm = _hour_minute(at or "04:00")
    if hm is None:
        return {"ok": False, "code": "", "task": name, "message": f"时间格式不对：{at}（写成 04:00 或 22:30）"}
    hh, mm = hm
    vault_path = Path(vault).expanduser().resolve() if vault else storage.vault_root()
    if not vault_path.is_dir():
        return {"ok": False, "code": "", "task": name, "message": f"收藏库不存在：{vault_path}（先选好收藏库位置）"}
    platform = platform or sys.platform
    if platform != "win32":
        py = sys.executable
        return {"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "task": name, "time": f"{hh:02d}:{mm:02d}",
                "message": "这台电脑不是 Windows：没有自动注册，请把下面的 cron 行（Linux）或 launchd 配置（macOS）加进系统定时任务",
                "cron": nightly_cron_line(py, str(vault_path), hh, mm),
                "launchd": nightly_launchd_plist(py, str(vault_path), hh, mm)}
    workdir = storage.link_brain_home()
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    script = nightly_install_script(nightly_python(), nightly_args(str(vault_path)), str(workdir), hh, mm,
                                    nightly.TASK_LIMIT_HOURS)
    ok, out = _ps(script)
    if not ok:
        if "Access is denied" in out or "拒绝访问" in out:
            out += "（注册计划任务被拒绝：可能被系统策略限制）"
        return {"ok": False, "code": "", "task": name, "message": "没注册上计划任务：" + out[:300]}
    return {"ok": True, "code": "", "task": name, "time": f"{hh:02d}:{mm:02d}", "vault": str(vault_path),
            "message": f"已注册计划任务 {name}：每天 {hh:02d}:{mm:02d} 夜跑（错过会在开机登录后补跑）"}


def uninstall_nightly(*, platform: str | None = None) -> dict[str, Any]:
    import sys
    name = nightly_task_name()
    if name in LEGACY_TASKS:
        return {"ok": False, "code": "", "task": name, "message": f"任务名 {name} 是旧夜跑脚本的任务，不删它"}
    if (platform or sys.platform) != "win32":
        return {"ok": True, "code": "", "task": name,
                "message": "这台电脑不是 Windows：没有计划任务要删；自己加的 cron / launchd 请自己去掉"}
    ok, out = _ps(nightly_uninstall_script())
    if not ok:
        return {"ok": False, "code": "", "task": name, "message": "计划任务没删掉：" + out[:300]}
    gone = out.strip().endswith("ok")
    return {"ok": True, "code": "", "task": name, "message": f"已删除计划任务 {name}" if gone else "本来就没有这个计划任务"}


def run_install(args) -> int:
    """`sync-schedule --install [--at HH:mm] [--vault 路径]` / `--uninstall`。"""
    from .read import EXIT_ERROR, EXIT_OK, dump_json
    import sys
    if getattr(args, "uninstall", False):
        result = uninstall_nightly()
    else:
        result = install_nightly(getattr(args, "at", None), getattr(args, "vault", None))
    if not result.get("ok"):
        print(result.get("message", ""), file=sys.stderr)
    dump_json(result)
    return EXIT_OK if result.get("ok") else EXIT_ERROR
