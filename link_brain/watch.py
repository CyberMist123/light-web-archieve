"""实时进度终端（1016）：一个黑框，每 2 秒刷新一次，看号的状态、正在抓什么、最近每一次用号的结果。

    python -m link_brain watch          # 在当前终端里刷新
    tools\\lwa-watch.cmd                 # 双击：另开一个黑框跑上面这条

只读本机文件（熔断文件、楼中楼计数、各任务状态文件、用号行为日志），不连读取服务、不碰号，开着不影响任何任务。
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import actionlog

RED, YEL, GRN, DIM, BOLD, RST = "\x1b[31m", "\x1b[33m", "\x1b[32m", "\x1b[2m", "\x1b[1m", "\x1b[0m"


def _json(p: Path) -> dict[str, Any]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def snapshot() -> dict[str, Any]:
    """收集一次要显示的东西（全是本地文件）。"""
    from . import accounts, crawl, storage
    prof = accounts.profile_dir()
    arch = storage.archive_root()
    now = datetime.now().astimezone()
    return {
        "now": now,
        "hold": _json(prof / "risk-hold.json"),
        "sub": _json(prof / "sub-expand.json"),
        "strikes": _json(prof / "rate-limit-strikes.json"),
        "crawl": crawl.read_status(),
        "fill": _json(arch / "comments-fill-status.json") if arch else {},
        "sync": _json(arch / "sync-status.json") if arch else {},
        "rows": actionlog.read(since=now - timedelta(hours=24)),
    }


def _age(ts: str, now: datetime) -> str:
    try:
        t = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return ""
    s = int((now - (t if t.tzinfo else t.astimezone())).total_seconds())
    return f"{s}s 前" if s < 120 else f"{s // 60} 分钟前" if s < 3600 else f"{s // 3600} 小时前"


def render(snap: dict[str, Any], *, width: int = 100, color: bool = True) -> str:
    """一屏的文字（纯函数，测试直接调）。"""
    c = (lambda code, s: f"{code}{s}{RST}") if color else (lambda code, s: s)
    now = snap["now"]
    out = [c(BOLD, f"LWA 实时进度  {now:%m-%d %H:%M:%S}") + c(DIM, "  （只读本机文件，不碰号；Ctrl+C 退出）"), ""]

    hold = snap.get("hold") or {}
    if hold.get("code") == "XHS_RATE_LIMITED":
        out.append(c(YEL, f"号：限频冷却中（第 {hold.get('strikes')} 次），冷却到 {str(hold.get('until'))[5:16].replace('T', ' ')}，到点自己试，不用管"))
    elif hold.get("code"):
        out.append(c(RED, f"号：熔断中 {hold.get('code')}（自 {str(hold.get('since'))[5:16].replace('T', ' ')}）——要你处理：{str(hold.get('detail'))[:80]}"))
    else:
        out.append(c(GRN, "号：正常"))
    used = 0
    for ts in (snap.get("sub") or {}).get("clicks") or []:
        try:
            if now - datetime.fromisoformat(ts) < timedelta(hours=1):
                used += 1
        except ValueError:
            pass
    st = snap.get("strikes") or {}
    extra = f" · 24h 内限频 {st.get('strikes')} 次（最后 {str(st.get('last'))[5:16].replace('T', ' ')}）" if st.get("strikes") else ""
    out.append(f"楼中楼：这一小时已展开 {used} 次{extra}")
    out.append("")

    cr = snap.get("crawl") or {}
    if cr:
        out.append(c(BOLD, "交替抓取") + f"  {cr.get('state', '')} · {cr.get('message', '')}  " + c(DIM, _age(cr.get("updated_at", ""), now)))
        hist = [h for h in cr.get("history") or [] if h.get("block")][-6:]
        if hist:
            out.append(c(DIM, "  最近：" + " → ".join(
                f"{h['block']}({'跳过' if h.get('skipped') else str(h.get('minutes', '')) + '分'})" for h in hist)))
    fill = snap.get("fill") or {}
    if fill:
        out.append(c(BOLD, "补评论") + f"  {fill.get('state', '')} · {str(fill.get('message', ''))[:70]}  "
                   + c(DIM, f"已补齐 {fill.get('done', 0)} · " + _age(fill.get("updated_at", ""), now)))
    sync = snap.get("sync") or {}
    if sync:
        live = sync.get("live") or {}
        prog = f"{live.get('done')}/{live.get('total')}" if live.get("total") else ""
        out.append(c(BOLD, "收藏同步") + f"  {sync.get('label') or sync.get('state', '')} {prog} · {str(sync.get('message', ''))[:60]}")
    out.append("")

    rows = snap.get("rows") or []
    cnt: dict[str, Counter] = {}
    for r in rows:
        k = cnt.setdefault(str(r.get("action")), Counter())
        k["拦" if actionlog.is_risk(r) else "ok" if r.get("ok") else "错"] += 1
    if cnt:
        out.append(c(BOLD, "24 小时用号") + "  " + "  ".join(
            f"{actionlog.ACTION_CN.get(a, a)} ok{v['ok']}" + (c(RED, f" 拦{v['拦']}") if v["拦"] else "")
            + (c(YEL, f" 错{v['错']}") if v["错"] else "") for a, v in sorted(cnt.items())))
    for a in sorted(cnt):
        why, _ = actionlog.repeat_pause(a, rows, now)
        if why:
            out.append(c(RED, "  暂停：" + why))
    out.append("")
    out.append(c(BOLD, "最近用号（新的在下）"))
    for r in rows[-15:]:
        t = str(r.get("ts", ""))[11:19]
        what = f"{actionlog.ACTION_CN.get(r.get('action'), r.get('action'))} {str(r.get('item') or '')[-8:]}"
        trig = c(DIM, f"[{str(r.get('trigger', ''))[:18]}]")
        if r.get("ok"):
            more = f" 楼中楼点 {r['sub_clicks']}" if r.get("sub_clicks") else ""
            res = c(GRN, "ok") + f" {r.get('secs', '')}s{more}"
        else:
            tag = r.get("code") or "错"
            if r.get("error_code"):
                tag += f" {r['error_code']}"
            if r.get("reject"):
                tag += f" @{r['reject']}"
            res = c(RED if actionlog.is_risk(r) else YEL, tag)
        out.append(f"  {t} {trig} {what:<24} {res}"[: width + 40])
    if not rows:
        out.append(c(DIM, "  （24 小时内没有用号记录）"))
    return "\n".join(out)


def run(args) -> int:
    if os.name == "nt":
        os.system("")  # 打开 Windows 终端的 ANSI 颜色
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    interval = float(getattr(args, "interval", 2) or 2)
    try:
        while True:
            text = render(snapshot())
            sys.stdout.write("\x1b[2J\x1b[H" + text + "\n")
            sys.stdout.flush()
            if getattr(args, "once", False):
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
