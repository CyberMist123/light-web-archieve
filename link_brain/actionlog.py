"""用号行为日志（1016）：每一次经读取服务碰小红书的动作记一行，撞了什么、在哪个接口撞的，一眼看得出。

为什么要它：同一种行为反复撞几次，小红书会升级处罚（10-12 起 6 次 300013 访问频繁都在展开楼中楼，第 7 次升成 300011
账号异常、要重新登录）。熔断只记「最近一次」，看不出是哪种行为在反复撞；这份日志按行为种类数，给退避用，也给实时终端看。

落在 `~/.link-brain/account-actions.jsonl`（本机，不进 vault、不进 git），一行一条：
  {"ts", "action", "trigger", "item", "ok", "code", "error_code", "reject", "secs", "detail", ...}
- action：favorites（读收藏列表）· note（只开笔记正文）· comments（滚评论 / 展开楼中楼）· attachments · search_token · login_check · 其他按接口名
- trigger：谁让做的——环境变量 LWA_TRIGGER（夜跑 / 补评论 / 交替抓取 / 她点的）> 账号锁的持有者 > 进程命令行
- error_code / reject：从读取服务报错里取的小红书 error_code（300011 / 300013 …）与被拒接口种类（sub_comments …）

写不进去绝不影响主流程。超过 5 MB 轮转成 .1（只留一份）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import sources, storage

FILE = "account-actions.jsonl"
MAX_BYTES = 5 * 1024 * 1024

# 读取服务报错里算「号被小红书拦了」的码（不含刚同步过 RATE_LIMITED / 服务忙 BUSY 这类本地码）
RISK_CODES = {"ACCOUNT_RISK", "XHS_RATE_LIMITED", "CAPTCHA_REQUIRED", "NOT_LOGGED_IN"}

_ERR_CODE = re.compile(r"error_code[=:]\s*(\d{4,8})")
_REJECT = re.compile(r"触发接口=([a-z_]+)")
_BRACKET = re.compile(r"\[([A-Z][A-Z_]{3,})\]")

# 同一种行为在窗口内被拦几次后暂停多久（第 2 次起才由这里管；第 1 次由读取服务的熔断 / 冷却管）
REPEAT_WINDOW = timedelta(hours=72)
REPEAT_PAUSE = timedelta(hours=24)


def path() -> Path:
    return sources.get(sources.names()[0]).action_home() / FILE


def _now() -> datetime:
    return datetime.now().astimezone()


def trigger() -> str:
    t = os.environ.get("LWA_TRIGGER", "").strip()
    if t:
        return t
    try:
        h = sources.get(sources.names()[0]).action_lock_holder() or {}
        if h.get("owner"):
            return str(h["owner"])
    except Exception:  # noqa: BLE001 - 只是标注
        pass
    args = [a for a in sys.argv[1:] if not a.startswith("-")][:2]
    return " ".join(args) or "manual"


def parse(text: str) -> dict[str, str]:
    """从报错文本里取 code / error_code / reject（取不到为空）。"""
    text = text or ""
    out = {"code": "", "error_code": "", "reject": ""}
    m = _BRACKET.search(text)
    if m:
        out["code"] = m.group(1)
    m = _ERR_CODE.search(text)
    if m:
        out["error_code"] = m.group(1)
    m = _REJECT.search(text)
    if m:
        out["reject"] = m.group(1)
    elif "comment/sub/page" in text:
        out["reject"] = "sub_comments"
    return out


def record(action: str, *, ok: bool, item: str = "", code: str = "", detail: str = "", secs: float | None = None,
           **extra: Any) -> dict[str, Any] | None:
    """记一行。code 没给就从 detail 里的 [CODE] 取。返回写下的那行（写失败返回 None）。"""
    try:
        got = parse(detail)
        row: dict[str, Any] = {"ts": _now().isoformat(timespec="seconds"), "action": action, "trigger": trigger(),
                               "item": item or "", "ok": bool(ok), "code": code or got["code"],
                               "error_code": got["error_code"], "reject": got["reject"]}
        if secs is not None:
            row["secs"] = round(float(secs), 1)
        if detail and not ok:
            row["detail"] = str(detail)[:300]
        row.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if p.stat().st_size > MAX_BYTES:
                os.replace(p, p.with_name(FILE + ".1"))
        except FileNotFoundError:
            pass
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with p.open("a+b") as f:
            # 上次写到行尾前被打断：先补个换行，别让新行粘在半行后面一起坏掉
            if f.seek(0, os.SEEK_END) > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    line = "\n" + line
            f.write(line.encode("utf-8"))
        return row
    except Exception:  # noqa: BLE001 - 日志写不进去不影响主流程
        return None


def read(*, since: datetime | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """读日志（旧在前）。limit = 只要最后几行。读不到返回 []。"""
    rows: list[dict[str, Any]] = []
    try:
        lines, _bad = storage.read_jsonl(path())
    except OSError:
        return rows
    if limit:
        lines = lines[-max(limit * 4, limit):] if since else lines[-limit:]
    for r in lines:
        if since is not None:
            t = _ts(r)
            if t is None or t < since:
                continue
        rows.append(r)
    return rows[-limit:] if limit else rows


def _ts(r: dict[str, Any]) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(r.get("ts")))
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def is_risk(r: dict[str, Any]) -> bool:
    return not r.get("ok") and str(r.get("code") or "") in RISK_CODES


def repeat_pause(action: str, rows: Iterable[dict[str, Any]] | None = None,
                 now: datetime | None = None) -> tuple[str, datetime | None]:
    """同一种行为反复被拦：72 小时内第 n 次（n ≥ 2）→ 从最后一次起暂停 24 小时 ×(n−1)。
    返回 (原因, 到几点)；不用停返回 ("", None)。纯逻辑（rows 可传进来测）。"""
    now = now or _now()
    if rows is None:
        rows = read(since=now - REPEAT_WINDOW)
    hits = [r for r in rows if r.get("action") == action and is_risk(r) and (_ts(r) or now) >= now - REPEAT_WINDOW]
    if len(hits) < 2:
        return "", None
    last = max(_ts(r) or now for r in hits)
    until = last + REPEAT_PAUSE * (len(hits) - 1)
    if now >= until:
        return "", None
    codes = "、".join(sorted({str(r.get("error_code") or r.get("code")) for r in hits}))
    return (f"「{ACTION_CN.get(action, action)}」72 小时内被小红书拦了 {len(hits)} 次（{codes}），"
            f"暂停到 {until.strftime('%m-%d %H:%M')}，免得同一种行为越撞越重"), until


ACTION_CN = {"favorites": "读收藏列表", "note": "开笔记", "comments": "读评论 / 楼中楼", "attachments": "下附件",
             "search_token": "搜标题找口令", "login_check": "查登录", "probe": "冷却后自查"}


def action_for_tool(tool: str, arguments: dict[str, Any]) -> str:
    if tool == "get_feed_detail":
        return "comments" if arguments.get("load_all_comments") or arguments.get("expand_floors") else "note"
    if tool == "check_login_status":
        return "login_check"
    return tool


def action_for_route(route: str) -> str:
    for name in sources.names():
        action = sources.get(name).action_for_route(route)
        if action:
            return action
    return ""
