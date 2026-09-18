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
