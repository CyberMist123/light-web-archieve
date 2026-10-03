"""每晚收藏巡检的周期设置（Owner 2026-09-16：设置里能选每天 / 每周 / 关闭）。

巡检本体是 Windows 计划任务 `XhsFavSync`（跑 ~/.xiaohongshu-mcp/xhs-fav-sync.ps1，仓库外的 ops）。
这里只**调它的触发频率 / 启停**，不碰它的动作。改法走 PowerShell 的 ScheduledTasks 模块，
只 Set-ScheduledTask 换触发器、Enable/Disable 启停——不删不重建，最小动作。

开源用户没有这个任务：命令会如实报「找不到任务」，不炸。任务名可用 env LINK_BRAIN_SYNC_TASK 覆盖。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from typing import Any

TASK = os.environ.get("LINK_BRAIN_SYNC_TASK", "XhsFavSync")
AT = "4:00AM"  # 默认凌晨 4 点
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


_TIME_RE = re.compile(r"^(\d{1,2}):([0-5]\d)(\s?[AaPp][Mm])?$")


def _norm_time(at: str | None) -> str | None:
    """接受 '4:00AM' / '04:00' / '16:30' 这类；空 = 默认 4 点；格式不对返回 None（调用方如实报错，不拼进命令）。"""
    at = (at or "").strip()
    if not at:
        return AT
    m = _TIME_RE.match(at)
    if not m:
        return None
    hour = int(m.group(1))
    if (m.group(3) and not 1 <= hour <= 12) or hour > 23:
        return None
    return at


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


# —— 触发器（第 5 批 4.4）：读**全部**触发器，认出「我们管的那一个」（第一个间隔为 1 的每日 / 每周触发器），
#    保存时只替换它、其余触发器（一次性、登录时、别人加的）原样保留；一个都认不出时不冒充「每天」。
_DAY_BITS = (("Sunday", 1), ("Monday", 2), ("Tuesday", 4), ("Wednesday", 8), ("Thursday", 16), ("Friday", 32),
             ("Saturday", 64))  # MSFT_TaskWeeklyTrigger.DaysOfWeek 是位掩码
_DAY_CN = {"Monday": "周一", "Tuesday": "周二", "Wednesday": "周三", "Thursday": "周四", "Friday": "周五",
           "Saturday": "周六", "Sunday": "周日"}
_KIND_CN = {"Time": "一次性", "Logon": "登录时", "Boot": "开机时", "Idle": "空闲时", "Event": "事件触发",
            "SessionStateChange": "会话变化时", "Registration": "创建任务时"}

_READ_PS = (
    "$t=Get-ScheduledTask -TaskName '{task}' -ErrorAction SilentlyContinue;"
    "if(-not $t){{'none'}}else{{"
    "$info=Get-ScheduledTaskInfo -TaskName '{task}';"
    "$tr=@($t.Triggers|Where-Object{{$_}}|ForEach-Object{{[pscustomobject]@{{cls=[string]$_.CimClass.CimClassName;"
    "start=[string]$_.StartBoundary;enabled=[bool]$_.Enabled;id=[string]$_.Id;"
    "rep=$(try{{[string]$_.Repetition.Interval}}catch{{''}});"
    "days=$(try{{[int]$_.DaysOfWeek}}catch{{0}});"
    "interval=$(try{{if($_.DaysInterval){{[int]$_.DaysInterval}}elseif($_.WeeksInterval){{[int]$_.WeeksInterval}}else{{1}}}}catch{{1}})}}}});"
    "[pscustomobject]@{{state=[string]$t.State;"
    "last_run=$(if($info.LastRunTime){{$info.LastRunTime.ToString('s')}}else{{''}});"
    "last_result=$info.LastTaskResult;"
    "next_run=$(if($info.NextRunTime){{$info.NextRunTime.ToString('s')}}else{{''}});"
    "triggers=$tr}}|ConvertTo-Json -Compress -Depth 4}}"
)


def _kind(cls: str) -> str:
    """'MSFT_TaskDailyTrigger' → 'Daily'。"""
    return re.sub(r"^MSFT_Task|Trigger$", "", str(cls or ""))


def _hm(start: str) -> str:
    m = re.search(r"T(\d{2}):(\d{2})", str(start or ""))
    return f"{m.group(1)}:{m.group(2)}" if m else ""


def _days(mask: Any) -> list[str]:
    try:
        mask = int(mask or 0)
    except (TypeError, ValueError):
        return []
    days = [name for name, bit in _DAY_BITS if mask & bit]
    return sorted(days, key=DAYS.index)


def _managed(tr: dict[str, Any]) -> bool:
    """我们的「每天 / 每周」那个：每日或每周、间隔 1（每 2 天 / 隔周这类界面表达不了，算自定义）。"""
    return _kind(tr.get("cls")) in ("Daily", "Weekly") and int(tr.get("interval") or 1) == 1


def describe_trigger(tr: dict[str, Any]) -> str:
    """一个触发器的中文一句话（给「另有…未改动」用）。"""
    kind, hm = _kind(tr.get("cls")), _hm(tr.get("start"))
    n = int(tr.get("interval") or 1)
    if kind == "Daily":
        text = ("每天" if n == 1 else f"每 {n} 天") + (f" {hm}" if hm else "")
    elif kind == "Weekly":
        days = "、".join(_DAY_CN[d] for d in _days(tr.get("days"))) or "?"
        text = ("每周" if n == 1 else f"每 {n} 周") + f" {days}" + (f" {hm}" if hm else "")
    elif kind == "Time":
        m = re.match(r"(\d{4}-\d{2}-\d{2})", str(tr.get("start") or ""))
        text = "一次性" + (f" {m.group(1)}" if m else "") + (f" {hm}" if hm else "")
    else:
        text = _KIND_CN.get(kind) or "自定义触发器"
    return text + ("（已停用）" if tr.get("enabled") is False else "")


def parse_state(out: str) -> dict[str, Any]:
    """_READ_PS 的输出 → get_schedule 的结果（纯函数，单测喂假输出）。

    freq：daily / weekly = 认出了我们管的那个触发器；unknown = 有触发器但没有一个是（只显示，不冒充每天）；
    none = 没有这个任务（或一个触发器都没有时也给 unknown + trigger_count=0，保存会新加一个）。"""
    val = (out or "").strip()
    if val == "none":
        return {"task": TASK, "freq": "none", "enabled": False}
    try:
        data = json.loads(val.splitlines()[-1] if val else "")
    except ValueError:
        return {"task": TASK, "freq": "none", "enabled": False, "error": f"读不懂计划任务的输出：{val[:120]}"}
    trs = data.get("triggers") or []
    if isinstance(trs, dict):  # 只有一个时 ConvertTo-Json 可能不包数组
        trs = [trs]
    trs = [t for t in trs if isinstance(t, dict)]
    ours = [i for i, t in enumerate(trs) if _tagged(t)]
    if ours:
        idx = ours[0]
    else:   # 10-03 以前存的没打标：沿用第 5 批的认法（第一个间隔 1 的每日 / 每周，启用的优先），它就是「我们的」
        idx = next((i for i, t in enumerate(trs) if _managed(t) and t.get("enabled") is not False), None)
        if idx is None:
            idx = next((i for i, t in enumerate(trs) if _managed(t)), None)
        ours = [idx] if idx is not None else []
    mine = trs[idx] if idx is not None else {}
    rules = rules_from_triggers([trs[i] for i in ours])
    freq = {"Daily": "daily", "Weekly": "weekly"}.get(_kind(mine.get("cls")), "unknown")
    if len(rules) > 1 or (rules and rules[0]["kind"] in ("once", "hourly")) \
            or (rules and len(rules[0].get("times") or []) > 1):
        freq = "custom"   # 一次性 / 每 N 小时 / 一天多次 / 几条组合：旧的每天 / 每周下拉表达不了
    days = _days(mine.get("days")) if freq == "weekly" else []
    enabled = str(data.get("state") or "") != "Disabled"
    on = [trs[i] for i in ours if trs[i].get("enabled") is not False]
    out = {"task": TASK, "freq": freq, "enabled": enabled,
           "last_run": data.get("last_run") or "", "last_result": _int(data.get("last_result")),
           "next_run": data.get("next_run") or "",
           "time": _hm(mine.get("start")) if mine else "", "day": ",".join(days),
           "managed_index": idx, "trigger_count": len(trs), "mine": ours,
           "mine_classes": [str(trs[i].get("cls") or "") for i in ours],
           "trigger_enabled": (mine.get("enabled") is not False) if mine else None,
           "rules": rules,
           "others": [describe_trigger(t) for i, t in enumerate(trs) if i not in ours]}
    out["summary"] = summary_text(out if on else {**out, "rules": []}, enabled=enabled)
    return out


# ---------------------------------------------------------------- 10-03：更灵活的定时（规则）
# 规则（插件和 CLI 都用这个形状；一条规则可能对应好几个触发器）：
#   {"kind": "once",   "at": "2026-10-03 17:00"}                         一次性（某月某日某时）
#   {"kind": "daily",  "times": ["04:00", "16:00"]}                       每天，一天可以几次
#   {"kind": "weekly", "days": ["Monday", "Thursday"], "times": ["08:00"]}  每周几（可多选）+ 时刻
#   {"kind": "hourly", "hours": 4, "from": "00:00"}                       每 N 小时（1–6）后台同步（触发器重复间隔）
# 我们写的触发器都打标（Id = LWA-<n>），读写只动打了标的那几个（一个都没打标时按第 5 批规则认一个），其余原样保留。
# 时刻全部写成本机钟点（LOCAL_FIX：New-ScheduledTaskTrigger 记 UTC，夏令时会漂）。

TAG = "LWA"
MAX_RULE_TRIGGERS = 16
HOURLY_MIN, HOURLY_MAX = 1, 6


def _tagged(tr: dict[str, Any]) -> bool:
    return str(tr.get("id") or "").upper().startswith(TAG)


def _rep_hours(rep: Any) -> int | None:
    m = re.fullmatch(r"PT(\d+)H", str(rep or "").strip().upper())
    return int(m.group(1)) if m else None


def rules_from_triggers(trs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """我们的触发器 → 规则（每天的几个时刻并成一条；同一组周几并成一条）。"""
    daily: list[str] = []
    weekly: dict[tuple, list[str]] = {}
    extra: list[dict[str, Any]] = []
    for t in trs:
        kind, hm = _kind(t.get("cls")), _hm(t.get("start"))
        hours = _rep_hours(t.get("rep"))
        if kind == "Time":
            m = re.match(r"(\d{4}-\d{2}-\d{2})", str(t.get("start") or ""))
            extra.append({"kind": "once", "at": f"{m.group(1) if m else ''} {hm}".strip()})
        elif kind == "Daily" and hours:
            extra.append({"kind": "hourly", "hours": hours, "from": hm or "00:00"})
        elif kind == "Daily":
            if hm and hm not in daily:
                daily.append(hm)
        elif kind == "Weekly":
            key = tuple(_days(t.get("days")))
            weekly.setdefault(key, [])
            if hm and hm not in weekly[key]:
                weekly[key].append(hm)
    rules: list[dict[str, Any]] = []
    if daily:
        rules.append({"kind": "daily", "times": sorted(daily)})
    for days, times in weekly.items():
        rules.append({"kind": "weekly", "days": list(days), "times": sorted(times)})
    rules += [r for r in extra if r["kind"] == "hourly"]
    rules += sorted((r for r in extra if r["kind"] == "once"), key=lambda r: r["at"])
    return rules


def _short_dt(text: str) -> str:
    m = re.match(r"\d{4}-(\d{2})-(\d{2})[T ](\d{2}:\d{2})", str(text or ""))
    return f"{m.group(1)}/{m.group(2)} {m.group(3)}" if m else str(text or "")


def describe_rule(r: dict[str, Any]) -> str:
    kind = r.get("kind")
    if kind == "daily":
        return "每天 " + "、".join(r.get("times") or [])
    if kind == "weekly":
        days = "、".join(_DAY_CN.get(d, d) for d in r.get("days") or [])
        return f"每{days} " + "、".join(r.get("times") or [])
    if kind == "hourly":
        start = r.get("from") or "00:00"
        return f"每 {r.get('hours')} 小时一次" + ("" if start == "00:00" else f"（从 {start} 起）")
    if kind == "once":
        return f"{_short_dt(r.get('at'))} 一次"
    return "自定义"


def summary_text(st: dict[str, Any], *, enabled: bool = True) -> str:
    """当前状态一行人话：「每周一 08:00 · 每 4 小时一次 · 下次 10/06 08:00」。"""
    if st.get("freq") == "none":
        return "没有定时同步"
    if not enabled:
        return "已关闭"
    parts = [describe_rule(r) for r in st.get("rules") or []]
    if not parts:
        return "没有定时同步" if not st.get("others") else "自定义触发器（" + "、".join(st["others"]) + "），未改动"
    if st.get("next_run"):
        parts.append("下次 " + _short_dt(st["next_run"]))
    return " · ".join(parts)


def _times(values: Any) -> list[tuple[int, int]] | None:
    vals = values if isinstance(values, list) else [values]
    out: list[tuple[int, int]] = []
    for v in vals:
        hm = _hour_minute(str(v or ""))
        if hm is None:
            return None
        if hm not in out:
            out.append(hm)
    return sorted(out) or None


def normalize_rules(rules: Any, *, now: datetime | None = None) -> tuple[list[dict[str, Any]], str]:
    """校验 + 规整。返回 (规则, 错误)；错误非空 = 不写（格式不对的绝不拼进 PowerShell）。"""
    if not isinstance(rules, list) or not rules:
        return [], "至少要有一条定时（不想定时就选「关闭」）"
    now = now or datetime.now()
    out: list[dict[str, Any]] = []
    n = 0
    for r in rules:
        if not isinstance(r, dict):
            return [], "规则格式不对"
        kind = r.get("kind")
        if kind == "once":
            m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})(?::\d{2})?", str(r.get("at") or "").strip())
            try:
                when = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                                int(m.group(5))) if m else None
            except ValueError:
                when = None
            if when is None:
                return [], f"一次性的时间不对：{r.get('at')}（写成 2026-10-03 17:00）"
            if when <= now:
                return [], f"{when:%m/%d %H:%M} 已经过了"
            out.append({"kind": "once", "at": f"{when:%Y-%m-%d %H:%M}"})
            n += 1
        elif kind in ("daily", "weekly"):
            times = _times(r.get("times") if r.get("times") is not None else r.get("at"))
            if times is None:
                return [], f"时间格式不对：{r.get('times') or r.get('at')}（写成 04:00 或 22:30）"
            rule: dict[str, Any] = {"kind": kind, "times": [f"{h:02d}:{m:02d}" for h, m in times]}
            if kind == "weekly":
                days = r.get("days") if isinstance(r.get("days"), list) else [r.get("days")]
                days = [d for d in DAYS if d in days]
                if not days:
                    return [], "每周要至少选一天"
                rule["days"] = days
            n += len(times)
            out.append(rule)
        elif kind == "hourly":
            try:
                hours = int(r.get("hours"))
            except (TypeError, ValueError):
                hours = 0
            if not HOURLY_MIN <= hours <= HOURLY_MAX:
                return [], f"每几小时只能是 {HOURLY_MIN}–{HOURLY_MAX}"
            start = _hour_minute(str(r.get("from") or "00:00"))
            if start is None:
                return [], f"起始时间格式不对：{r.get('from')}"
            out.append({"kind": "hourly", "hours": hours, "from": f"{start[0]:02d}:{start[1]:02d}"})
            n += 1
        else:
            return [], f"不认识的定时类型：{kind}"
    if n > MAX_RULE_TRIGGERS:
        return [], f"定时太多了（{n} 个），最多 {MAX_RULE_TRIGGERS} 个"
    return out, ""


def _at_ps(hh: int, mm: int) -> str:
    return f"([datetime]::Today.AddHours({int(hh)}).AddMinutes({int(mm)}))"


def rule_triggers_ps(rules: list[dict[str, Any]]) -> list[str]:
    """规整过的规则 → 每个触发器一段给 $new 的 PowerShell（已含 $new=…;）。"""
    out: list[str] = []
    for r in rules:
        kind = r["kind"]
        if kind == "once":
            d = datetime.strptime(r["at"], "%Y-%m-%d %H:%M")
            out.append(f"$new=New-ScheduledTaskTrigger -Once -At ([datetime]::new({d.year},{d.month},{d.day},{d.hour},{d.minute},0));")
        elif kind in ("daily", "weekly"):
            for t in r["times"]:
                hh, mm = map(int, t.split(":"))
                if kind == "daily":
                    out.append(f"$new=New-ScheduledTaskTrigger -Daily -At {_at_ps(hh, mm)};")
                else:
                    out.append(f"$new=New-ScheduledTaskTrigger -Weekly -DaysOfWeek {','.join(r['days'])} -At {_at_ps(hh, mm)};")
        elif kind == "hourly":
            hh, mm = map(int, r["from"].split(":"))
            at = _at_ps(hh, mm)
            # 每天从起点开始、一天之内每 N 小时重复一次 = 全天每 N 小时（重复间隔，不是一堆每日触发器）
            out.append(f"$new=New-ScheduledTaskTrigger -Daily -At {at};"
                       f"$new.Repetition=(New-ScheduledTaskTrigger -Once -At {at} -RepetitionInterval "
                       f"(New-TimeSpan -Hours {int(r['hours'])}) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition;")
    return out


def build_rules_ps(rules: list[dict[str, Any]], mine: list[int], classes: list[str], count: int) -> str:
    """写规则的 PowerShell：读出全部触发器 → 核对个数、我们那几个的类型没变（读和写之间被别处改了就不动）→
    去掉我们那几个、别的原样留着 → 每条规则新建触发器（打标 LWA-n、改成本机钟点）追加 → 整组写回 → 启用任务。
    错误信息只用 ASCII 标记（控制台编码不可靠）。"""
    guard = f"if($list.Count -ne {int(count)}){{throw 'LWA_TRIGGERS_CHANGED'}};"
    for i, cls in zip(mine, classes):
        suffix = re.sub(r"[^A-Za-z]", "", re.sub(r"^MSFT_Task", "", str(cls or ""))) or "Trigger"
        guard += f"if([string]$list[{int(i)}].CimClass.CimClassName -notlike '*{suffix}'){{throw 'LWA_TRIGGERS_CHANGED'}};"
    drop = ",".join(str(int(i)) for i in mine) or "-1"
    keep = f"$keep=@();for($i=0;$i -lt $list.Count;$i++){{if(@({drop}) -notcontains $i){{$keep+=$list[$i]}}}};"
    adds = ""
    for n, expr in enumerate(rule_triggers_ps(rules), 1):
        adds += expr + f"$new.Id='{TAG}-{n}';" + LOCAL_FIX + "$keep+=$new;"
    return (f"$t=Get-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop;$list=@($t.Triggers|Where-Object{{$_}});"
            f"{guard}{keep}{adds}"
            f"Set-ScheduledTask -TaskName '{TASK}' -Trigger $keep -ErrorAction Stop | Out-Null;"
            f"Enable-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop | Out-Null;'ok'")


def set_rules(rules: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """按规则重写我们那几个触发器（其余原样保留），并启用任务。"""
    norm, err = normalize_rules(rules, now=now)
    if err:
        return {"ok": False, "task": TASK, "error": err}
    cur = get_schedule()
    if cur.get("error"):
        return {"ok": False, "task": TASK, "error": "读不到计划任务：" + str(cur["error"])[:200]}
    if cur.get("freq") == "none":
        return {"ok": False, "task": TASK, "error": f"找不到计划任务 {TASK}"}
    ok, out = _ps(build_rules_ps(norm, list(cur.get("mine") or []), list(cur.get("mine_classes") or []),
                                 int(cur.get("trigger_count") or 0)))
    if not ok and "LWA_TRIGGERS_CHANGED" in out:
        out = "计划任务的触发器刚被别处改过，没动它；关掉这个窗口重开再保存"
    if not ok and ("Access is denied" in out or "拒绝访问" in out):
        out += "（改计划任务可能要管理员权限）"
    text = " · ".join(describe_rule(r) for r in norm)
    return {"ok": ok, "task": TASK, "rules": norm, "detail": ("已保存：" + text) if ok else out[:240]}


def get_schedule() -> dict[str, Any]:
    """读当前状态：freq(daily/weekly/unknown/none) + enabled + 其余触发器的描述（others）。"""
    ok, out = _ps(_READ_PS.format(task=TASK))
    if not ok:
        return {"task": TASK, "freq": "none", "enabled": False, "error": out}
    return parse_state(out)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# 触发器起点改成不带时区的本地时间（[datetime] 把 …Z 解析成本地时间，ToString('s') 不带偏移）
LOCAL_FIX = "$new.StartBoundary=([datetime]$new.StartBoundary).ToString('s');"


def build_set_ps(trig: str, index: int | None, count: int) -> str:
    """换触发器的 PowerShell：读出全部触发器 → 核对数量和那一个的类型没变（读和写之间被别处改了就不动）→
    只替换 index 那一个（None = 追加）→ Set-ScheduledTask 整组写回 → 启用任务。错误信息只用 ASCII 标记（控制台编码不可靠）。"""
    guard = f"if($list.Count -ne {int(count)}){{throw 'LWA_TRIGGERS_CHANGED'}};"
    if index is None:
        swap = "$list+=$new;"
    else:
        i = int(index)
        guard += (f"$c=[string]$list[{i}].CimClass.CimClassName;"
                  "if($c -notlike '*DailyTrigger' -and $c -notlike '*WeeklyTrigger'){throw 'LWA_TRIGGERS_CHANGED'};")
        swap = f"$list[{i}]=$new;"
    return (f"$t=Get-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop;$list=@($t.Triggers|Where-Object{{$_}});{guard}"
            # 10-03：New-ScheduledTaskTrigger 记的是 UTC（…Z）=「跨时区同步」，夏令时一到就整点漂一小时；
            # 改写成不带时区的本地时间，触发器按本机钟点走
            f"$new={trig};" + LOCAL_FIX + f"{swap}"
            f"Set-ScheduledTask -TaskName '{TASK}' -Trigger $list -ErrorAction Stop | Out-Null;"
            f"Enable-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop | Out-Null;'ok'")


def set_schedule(freq: str, at: str | None = None, day: str | None = None) -> dict[str, Any]:
    """freq: daily / weekly / off；at: 'HH:mm' 或 '4:00AM'（可选）；day: 周几（weekly，可选）。

    daily / weekly：只替换我们管的那个每日 / 每周触发器（没有就新加一个），其余触发器原样保留，并启用任务。
    off：停用**整个计划任务**（设置页「关闭」= 不再自动同步；任务里别的触发器也跟着停，触发器本身不删，
    改回每天 / 每周时原样恢复）。只停我们那一个而让别的触发器照跑，就不是「关闭」了。"""
    if freq == "off":
        ok, out = _ps(f"Disable-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop")
    elif freq in ("daily", "weekly"):
        at_ok = _norm_time(at)
        if at_ok is None:
            return {"ok": False, "freq": freq, "task": TASK, "error": f"时间格式不对：{at}（写成 04:00 或 22:30）"}
        hm = _hour_minute(at_ok)
        if hm is None:
            return {"ok": False, "freq": freq, "task": TASK, "error": f"时间格式不对：{at}（写成 04:00 或 22:30）"}
        rule: dict[str, Any] = {"kind": freq, "times": [f"{hm[0]:02d}:{hm[1]:02d}"]}
        if freq == "weekly":
            rule["days"] = [d for d in DAYS if d in str(day or "").split(",")] or ["Monday"]
        r = set_rules([rule])   # 10-03：每天 / 每周也走规则（只换我们那几个触发器，其余原样保留）
        r["freq"] = freq
        return r
    else:
        return {"ok": False, "freq": freq, "error": f"未知周期: {freq}（要 daily/weekly/off）"}
    if not ok and ("Access is denied" in out or "拒绝访问" in out):
        out += "（改计划任务可能要管理员权限；可在任务计划程序里手动改 XhsFavSync 的触发器）"
    return {"ok": ok, "freq": freq, "task": TASK, "detail": out[:240]}


def run(args) -> int:
    from .read import EXIT_ERROR, EXIT_OK, dump_json

    if getattr(args, "rules", None):
        try:
            rules = json.loads(args.rules)
        except ValueError:
            rules = None
        result = set_rules(rules) if rules is not None else {"ok": False, "task": TASK, "error": "--rules 不是 JSON"}
        if not result.get("ok"):
            import sys
            print(result.get("error") or result.get("detail") or "没保存上", file=sys.stderr)
        dump_json(result)
        return EXIT_OK if result.get("ok") else EXIT_ERROR
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
        "$t.StartBoundary=([datetime]$t.StartBoundary).ToString('s');"  # 本地钟点，不跟夏令时漂（见 LOCAL_FIX）
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
