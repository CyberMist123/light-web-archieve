"""同步记录（10-03 她定）：`vault/_archive/sync-log.jsonl`，每次同步一行——目录页「同步记录」窗口的数据。

一行 = 一次同步（插件「立即同步」/ 包内夜跑 / 仓外夜跑脚本 / 定时）：开始 · 结束 · 触发来源 · 新收几篇 ·
正文 / 附件 / 视频 / 识图 / 概要 各几篇成功几篇失败（失败带标题和原因）· 步骤级报错。
数据来自这次实际处理的对象：各步骤在自己完成处调 `note()`（这一进程里先攒着），命令结束时 `flush()` 合进这一行；
不重扫全库。

一次同步由好几个进程拼成（夜跑每步一个子进程），靠「这一次」的编号对上：
- 环境变量 `LINK_BRAIN_SYNC_RUN`（包内夜跑给每一步子进程带上；仓外脚本可以 `synclog begin` 拿编号自己设）；
- 没有编号：`sync-favorites` 开一行（`begin`）；之后不带编号的步骤（仓外脚本的附件 / 补概要 / 转写…）
  并进「最近一条还没收尾、8 小时内动过」的那行；`attachments --audit`（夜跑最后一步）或下一次 `begin` 给它收尾。
- 触发来源：`LINK_BRAIN_SYNC_TRIGGER`（插件「立即同步」= manual，重试 = retry）→ 交互终端 = cli →
  0–7 点 = nightly（夜跑），其余 = schedule（定时）。

写法：整份读 → 改这一行 → 原子写回（在 storage 锁 `sync-log` 里），只留最近 MAX_RUNS 行。手机同步看得到（在库里）。
任何一步出错都不影响同步本身（fail-open，原因进 stderr）。

CLI：`python -m link_brain synclog list|begin|end|record|retry`（stdout 只有一行 JSON）。

1011（她：「14:57 命令行 · 没有新内容」其实那趟收了 43 篇才被停掉；「夜跑在同步」其实是命令行；04:02 那条红的后来早好了）：
- 收藏同步每存好 / 没抓到一篇就把攒着的写进去（`flush_progress`；以前只在命令结束时写，进程被结束那趟一条都留不下）；
  这一行记下抓取进程 `fetch_pid`，正常收尾标 `fetch_done`。读的时候抓取进程已经没了、又没正常收尾 = 「被中断」，
  照已经写进去的篇数说「被中断 · 已收 N 篇」。老记录（没有 fetch_pid、一条没写进去）按库里 first_archived_at
  落在这一趟时间窗里的收藏篇数补回来（`recovered`）。
- 触发来源：没人看着（LINK_BRAIN_UNATTENDED，夜跑脚本 / 包内 nightly 设）优先于「交互终端 = 命令行」——夜跑脚本由
  计划任务起在控制台里，以前被当成命令行。
- 步骤级报错后来好了（同一步在问题记录里已解决；之后同一个命令成功跑过一次也算：cli 结束时 `heal_after_success`）：
  读的时候那条标 `resolved`，不算这次「出错」、不再红着挂在那（docs/ERRORS.md：自愈的不显示）。
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import storage

FILE_NAME = "sync-log.jsonl"
MAX_RUNS = 200
MAX_ITEMS = 200          # 一次同步最多记几条标题（够看；防一行无限长）
OPEN_STALE_HOURS = 8     # 没收尾、这么久没动 = 当它结束了（被强停 / 仓外脚本没调收尾）
ENV_RUN = "LINK_BRAIN_SYNC_RUN"
ENV_TRIGGER = "LINK_BRAIN_SYNC_TRIGGER"
KINDS = ("note", "attachment", "video", "vision", "summary", "comments")
KIND_CN = {"note": "正文", "attachment": "附件", "video": "视频", "vision": "识图", "summary": "概要", "comments": "评论"}
TRIGGER_CN = {"manual": "手动", "nightly": "夜跑", "schedule": "定时", "cli": "命令行", "retry": "重试",
              # 10-04：「导入网址」和问题面板 / 夜跑收尾的自愈轮以前不进同步记录
              "import": "手动导入", "repair": "自愈"}

# 这一进程攒着的（命令结束时 flush）
_pending: list[dict[str, Any]] = []
_errors: list[dict[str, Any]] = []
_new = 0
_run: dict[str, Any] = {}   # 本进程自己 begin 的那一次：{"id", "own"}（own = 命令结束就收尾）


def path() -> Path:
    return storage.archive_root() / FILE_NAME


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _stamp() -> str:
    """条目的时间（到微秒：重试时靠它分辨子进程这回记过没有）。"""
    return _now().isoformat(timespec="microseconds")


def _parse(ts: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.astimezone()


def default_trigger(now: datetime | None = None) -> str:
    env = (os.environ.get(ENV_TRIGGER) or "").strip()
    if env in TRIGGER_CN:
        return env
    if (os.environ.get("LINK_BRAIN_UNATTENDED") or "").strip():
        # 1011：夜跑脚本由计划任务起在控制台里（isatty 为真），以前被记成「命令行」；没人看着的一律按时段算夜跑 / 定时
        hour = (now or _now()).hour
        return "nightly" if 0 <= hour < 7 else "schedule"
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return "cli"
    except (AttributeError, ValueError, OSError):
        pass
    hour = (now or _now()).hour
    return "nightly" if 0 <= hour < 7 else "schedule"


# --------------------------------------------------------------------------- 文件

def _read() -> list[dict[str, Any]]:
    try:
        rows, _bad = storage.read_jsonl(path())  # 半行 / 坏行（含截在汉字中间）跳过
    except OSError:
        return []
    return [r for r in rows if r.get("run_id")]


def _write(rows: list[dict[str, Any]]) -> None:
    rows = rows[-MAX_RUNS:]
    path().parent.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_text(path(), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _edit(fn: Callable[[list[dict[str, Any]]], Any], wait_s: float = 15) -> Any:
    """锁里读改写；锁拿不到如实报错（调用方 fail-open）。"""
    with storage.file_lock("sync-log", wait_s=wait_s):
        rows = _read()
        result = fn(rows)
        _write(rows)
        return result


def _is_open(row: dict[str, Any], now: datetime | None = None) -> bool:
    if row.get("finished_at"):
        return False
    last = _parse(row.get("updated_at") or row.get("started_at"))
    return bool(last) and (now or _now()) - last < timedelta(hours=OPEN_STALE_HOURS)


def _new_row(run_id: str, trigger: str, attach: str) -> dict[str, Any]:
    now = _iso()
    return {"run_id": run_id, "trigger": trigger, "attach": attach, "started_at": now, "finished_at": None,
            "updated_at": now, "new": 0, "counts": {}, "items": [], "errors": [], "error": False, "exit": None,
            "pid": os.getpid()}


def _alive(pid: Any) -> bool:
    try:
        from .sync_state import _alive as alive
        return bool(pid) and alive(int(pid))
    except Exception:  # noqa: BLE001 - 查不了就当还活着（不误判成被中断）
        return True


def new_run_id() -> str:
    return f"{_now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def _close(row: dict[str, Any], *, exit_code: int | None = None, at: str | None = None) -> None:
    row["finished_at"] = at or _iso()
    row["updated_at"] = row["finished_at"]
    if exit_code is not None:
        row["exit"] = int(exit_code)


# --------------------------------------------------------------------------- 开 / 收

def begin(trigger: str | None = None, *, run_id: str | None = None, own: bool = True) -> str | None:
    """开一次同步，返回编号（本进程记住它）。own=True：本命令结束就收尾；False（仓外脚本那条路）：等夜跑最后一步收尾。
    先给「没收尾的自动行」收尾（新的一次开始了，上一次肯定结束了）。出错返回 None（不挡同步）。"""
    trigger = trigger or default_trigger()
    run_id = run_id or new_run_id()

    def go(rows):
        for r in rows:
            if not r.get("finished_at") and r.get("attach") == "auto" and r["run_id"] != run_id:
                _close(r, at=r.get("updated_at"))
        if not any(r["run_id"] == run_id for r in rows):
            rows.append(_new_row(run_id, trigger, "own" if own else "auto"))
    try:
        _edit(go)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] 同步记录没开上：{type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    _run.clear()
    _run.update(id=run_id, own=own)
    return run_id


def end(run_id: str | None = None, *, exit_code: int | None = None, auto_only: bool = False) -> bool:
    """收尾。run_id 不给 = 最近一条没收尾的（auto_only：只收「自动并进来」的那种，仓外脚本那条路）。"""
    flush()

    def go(rows):
        target = None
        if run_id:
            target = next((r for r in reversed(rows) if r["run_id"] == run_id), None)
        else:
            target = next((r for r in reversed(rows) if not r.get("finished_at")
                           and (not auto_only or r.get("attach") == "auto")), None)
        if target is None or target.get("finished_at"):
            return False
        _close(target, exit_code=exit_code)
        return True
    try:
        return bool(_edit(go))
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] 同步记录没收上尾：{type(exc).__name__}: {exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- 记

def _clip(text: Any, n: int = 200) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def note(kind: str, item_id: str | None, ok: bool, *, title: str | None = None, note_path: str | None = None,
         reason: str = "", code: str = "", url: str | None = None, retry: list[str] | None = None) -> None:
    """记一条「这次处理了这一篇的这一项」。kind ∈ KINDS。不落盘（命令结束时 flush）。"""
    if kind not in KINDS:
        return
    new = {"kind": kind, "id": item_id or None, "title": _clip(title, 120) or None, "note": note_path or None,
           "ok": bool(ok), "reason": "" if ok else _clip(reason), "code": "" if ok else str(code or ""),
           "url": url or None, "retry": retry or None, "at": _stamp()}
    # 同一进程里同一篇同一项记了好几次（一篇两个附件：一个下好、一个没下好；下好了但没转成文字）：有一次没成就算没成
    old = next((p for p in _pending if item_id and p["kind"] == kind and p["id"] == item_id), None)
    if old is None:
        _pending.append(new)
        return
    if not new["ok"]:
        if old["ok"]:
            old.update(ok=False, reason=new["reason"], code=new["code"], retry=new["retry"])
        else:
            old["reason"] = _clip(f"{old['reason']}；{new['reason']}") if new["reason"] not in old["reason"] else old["reason"]
            if old.get("retry") != new["retry"]:
                old["retry"] = None   # 两种失败要不同的命令补：退回这一项的默认补处理命令
    old["title"] = old["title"] or new["title"]
    old["note"] = old["note"] or new["note"]
    old["at"] = new["at"]


def count_new(n: int = 1) -> None:
    global _new
    _new += int(n)


def fetch_started() -> None:
    """收藏同步开抓：这一行记下抓取进程（被结束了，读的时候才认得出「被中断」）。fail-open。"""
    pid = os.getpid()

    def go(rows):
        rid = _target_id(rows, True)
        row = next(r for r in rows if r["run_id"] == rid)
        row.update(fetch_pid=pid, fetch_done=False, updated_at=_iso())
        return rid
    try:
        _edit(go)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] 同步记录没记上抓取进程：{type(exc).__name__}: {exc}", file=sys.stderr)


def _fetch_done(exit_code: int | None) -> None:
    pid = os.getpid()

    def go(rows):
        for r in reversed(rows):
            if r.get("fetch_pid") == pid and not r.get("fetch_done"):
                r.update(fetch_done=True, fetch_exit=exit_code, updated_at=_iso())
                return True
        return False
    try:
        _edit(go)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] 同步记录没标上抓取收尾：{type(exc).__name__}: {exc}", file=sys.stderr)


def flush_progress() -> None:
    """收藏同步每处理完一篇（新收 / 没抓到）就写进去：进程中途被结束，已经收的照样记得（1011）。"""
    if has_pending():
        flush(create=True)


def error(step: str, reason: str, code: str = "") -> None:
    """步骤级报错（号要处理、步骤超时、整步没跑…）：不对应某一篇。"""
    _errors.append({"step": str(step), "reason": _clip(reason), "code": str(code or ""), "at": _iso()})


def has_pending() -> bool:
    return bool(_pending or _errors or _new)


def _fill_meta(item: dict[str, Any]) -> None:
    """标题 / 笔记路径没给的，从 meta.json 补（只读这一篇）。"""
    if (item.get("title") and item.get("note")) or not item.get("id"):
        return
    sid = str(item["id"]).split("-", 1)[-1]
    try:
        for meta_path in storage.archive_root().glob(f"*/{sid}/meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            item["title"] = item.get("title") or _clip(meta.get("title"), 120) or None
            item["note"] = item.get("note") or meta.get("visible_note") or None
            return
    except (OSError, ValueError):
        return


def recount(row: dict[str, Any]) -> None:
    counts: dict[str, dict[str, int]] = {}
    for it in row.get("items") or []:
        c = counts.setdefault(it.get("kind") or "?", {"ok": 0, "failed": 0})
        c["ok" if it.get("ok") else "failed"] += 1
    row["counts"] = {k: counts[k] for k in KINDS if k in counts}
    row["error"] = any(not e.get("resolved") for e in row.get("errors") or []) or any(not it.get("ok") for it in row.get("items") or [])


def _merge(row: dict[str, Any], items: list[dict[str, Any]], errors: list[dict[str, Any]], new: int) -> None:
    by_key = {(it.get("kind"), it.get("id") or it.get("url") or it.get("title")): i for i, it in enumerate(row["items"])}
    for it in items:
        key = (it.get("kind"), it.get("id") or it.get("url") or it.get("title"))
        if key in by_key:   # 同一篇同一项：以后来的为准（重试 / 同一晚补了第二次）
            old = row["items"][by_key[key]]
            row["items"][by_key[key]] = {**old, **{k: v for k, v in it.items() if v is not None or k in ("reason",)},
                                         "title": it.get("title") or old.get("title"),
                                         "note": it.get("note") or old.get("note")}
        elif len(row["items"]) < MAX_ITEMS:
            by_key[key] = len(row["items"])
            row["items"].append(it)
        else:
            row["items_dropped"] = int(row.get("items_dropped") or 0) + 1
    seen = {(e.get("step"), e.get("reason")) for e in row["errors"]}
    for e in errors:
        if (e.get("step"), e.get("reason")) not in seen:
            row["errors"].append(e)
            seen.add((e.get("step"), e.get("reason")))
    row["errors"] = row["errors"][-30:]
    row["new"] = int(row.get("new") or 0) + int(new)
    row["updated_at"] = _iso()
    recount(row)


def _target_id(rows: list[dict[str, Any]], create: bool) -> str | None:
    env = (os.environ.get(ENV_RUN) or "").strip()
    if env:
        if not any(r["run_id"] == env for r in rows):
            rows.append(_new_row(env, default_trigger(), "own"))
        return env
    if _run.get("id") and any(r["run_id"] == _run["id"] for r in rows):
        return _run["id"]
    now = _now()
    open_auto = next((r for r in reversed(rows) if r.get("attach") == "auto" and _is_open(r, now)), None)
    if open_auto:
        return open_auto["run_id"]
    if create:
        rid = new_run_id()
        rows.append(_new_row(rid, default_trigger(), "auto"))
        return rid
    return None


def flush(*, create: bool = False) -> str | None:
    """把这一进程攒着的并进这一次同步那行。create：找不到可并的那次就开一行（sync-favorites）。返回编号。"""
    global _new
    if not has_pending():
        return _run.get("id")
    items, errors, new = list(_pending), list(_errors), _new
    for it in items:
        _fill_meta(it)

    def go(rows):
        rid = _target_id(rows, create)
        if not rid:
            return None
        row = next(r for r in rows if r["run_id"] == rid)
        _merge(row, items, errors, new)
        return rid
    try:
        rid = _edit(go)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] 同步记录没写上：{type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    _pending.clear()
    _errors.clear()
    _new = 0
    return rid


def finish_command(command: str, args: Any = None, exit_code: int | None = None) -> None:
    """cli.main 每个命令结束时调：攒着的写进去；自己开的那次（插件「立即同步」）收尾；仓外夜跑最后一步给自动行收尾。"""
    try:
        if has_pending():
            flush(create=(command == "sync-favorites"))
        if command == "sync-favorites":
            _fetch_done(exit_code)
        if exit_code == 0:
            heal_after_success(command, args)
        if _run.get("own") and _run.get("id") and not os.environ.get(ENV_RUN):
            end(_run["id"], exit_code=exit_code)
            _run.clear()
        elif command == "attachments" and getattr(args, "audit", False) and not os.environ.get(ENV_RUN):
            end(None, auto_only=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] {type(exc).__name__}: {exc}", file=sys.stderr)


def reset() -> None:
    """测试用：清掉这一进程攒着的。"""
    global _new
    _pending.clear()
    _errors.clear()
    _new = 0
    _run.clear()


# --------------------------------------------------------------------------- 读

def load(limit: int = 50) -> list[dict[str, Any]]:
    """新的在前。没收尾又很久没动的当它结束了（stale=True，结束时间 = 最后一次更新）；还在跑的 running=True。

    1011：抓取进程没了又没正常收尾 → interrupted=True（开这一行的进程也没了就当它结束了，不再挂 8 小时「进行中」）；
    老记录一条没写进去、时间窗里库里却多了收藏 → 按库补回 new / items（recovered=True，也算被中断）；
    步骤级报错后来好了 → 那条 resolved=True，error 只看没好的。"""
    now = _now()
    raw = _read()
    out = []
    for i in range(len(raw) - 1, -1, -1):
        r = dict(raw[i])
        fetch_dead = bool(r.get("fetch_pid")) and not r.get("fetch_done") and not _alive(r.get("fetch_pid"))
        if fetch_dead:
            r["interrupted"] = True
        if not r.get("finished_at"):
            if _is_open(r, now) and not (fetch_dead and not _alive(r.get("pid") or r.get("fetch_pid"))):
                r["running"] = True
            else:
                r["finished_at"] = r.get("updated_at") or r.get("started_at")
                r["stale"] = True
        out.append(r)
        if limit and len(out) >= limit:
            break
    try:
        _recover_lost(out, raw)
    except Exception as exc:  # noqa: BLE001 - 补不回来就照原样显示
        print(f"[synclog] 被中断那趟的篇数没补回来：{type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        _mark_healed(out)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] 报错后来好没好没核上：{type(exc).__name__}: {exc}", file=sys.stderr)
    return out


# 收藏同步类的一趟（被中断时值得按库补回篇数）；导入 / 重试 / 自愈不算
_FETCH_TRIGGERS = ("cli", "nightly", "schedule", "manual")


def _recover_lost(rows: list[dict[str, Any]], raw: list[dict[str, Any]]) -> None:
    """一条没写进去的那趟（进程在攒着的结果写进去之前就被结束了）：按库里 first_archived_at 落在这一趟时间窗
    [开始, 下一趟开始) 里、从收藏进来的对象补回篇数和标题。只补「没在跑、没记新收、没有正文条目」的收藏同步行。"""
    cands = [r for r in rows if not r.get("running") and not int(r.get("new") or 0) and r.get("trigger") in _FETCH_TRIGGERS
             and not any(it.get("kind") == "note" for it in r.get("items") or [])]
    if not cands:
        return
    starts = sorted((t, x["run_id"]) for x in raw for t in [_parse(x.get("started_at"))] if t)
    nxt = {rid: (starts[i + 1][0] if i + 1 < len(starts) else None) for i, (_, rid) in enumerate(starts)}
    from . import index as index_mod
    conn = index_mod.connect()
    try:
        objs = conn.execute(
            "SELECT o.item_id, o.title, o.first_archived_at, o.visible_note FROM objects o WHERE EXISTS "
            "(SELECT 1 FROM relations r WHERE r.item_id = o.item_id AND r.ingest_kind = 'favorite')").fetchall()
    finally:
        conn.close()
    arch = [(row[0], row[1], _parse(row[2]), row[3]) for row in objs]
    for r in cands:
        a, b = _parse(r.get("started_at")), nxt.get(r["run_id"])
        if a is None:
            continue
        got = sorted(((t, iid, title, note) for iid, title, t, note in arch if t and t >= a and (b is None or t < b)),
                     key=lambda x: x[0])
        if not got:
            continue
        r["new"] = len(got)
        r["recovered"] = True
        r["interrupted"] = True
        items = []
        for t, iid, title, note in got[:MAX_ITEMS]:
            it = {"kind": "note", "id": iid, "title": _clip(title, 120) or None, "note": note or None, "ok": True, "reason": "",
                  "code": "", "url": None, "retry": None, "at": t.isoformat()}
            _fill_meta(it)
            items.append(it)
        r["items"] = items + list(r.get("items") or [])
        if len(got) > MAX_ITEMS:
            r["items_dropped"] = len(got) - MAX_ITEMS
        last = got[-1][0]
        end = _parse(r.get("finished_at"))
        if end is None or end < last:
            r["finished_at"] = last.isoformat(timespec="seconds")
        recount(r)


# 夜跑离线步骤的 slug → 给人看的名字（同步记录里「后来好了：…」）
STEP_CN = {"catalog": "重写目录页", "catalog-final": "重写目录页（收尾）", "embed": "语义索引", "enrich-pending": "补识图 / 概要",
           "vision-upgrade": "识图补跑", "vision-refine": "精细识图", "videos-transcribe": "补转写视频"}


def _problem_step(step: Any) -> str | None:
    """同步记录里的步骤名 → 问题记录里的 step：repair.nightly.catalog / nightly.catalog / catalog → nightly.catalog。
    碰号的（收藏同步 / 登录 / 附件）不在这里认——那些照实挂着，等她处理或下次同步（docs/ERRORS.md：风控以外 0）。"""
    s = str(step or "")
    if s.startswith("repair."):
        s = s[len("repair."):]
    slug = s[len("nightly."):] if s.startswith("nightly.") else s
    return "nightly." + slug if slug in STEP_CN else None


def _mark_healed(rows: list[dict[str, Any]]) -> None:
    errs = [(r, e) for r in rows for e in r.get("errors") or [] if _problem_step(e.get("step"))]
    if not errs:
        return
    from . import problems
    state: dict[str, dict[str, Any]] = {}
    for row in problems._fold(problems._read_rows()).values():
        st = row.get("step")
        if not st:
            continue
        cur = state.setdefault(st, {"open": False, "resolved_at": ""})
        if row.get("resolved_at"):
            cur["resolved_at"] = max(cur["resolved_at"], str(row["resolved_at"]))
        else:
            cur["open"] = True
    for r, e in errs:
        pstep = _problem_step(e.get("step")) or ""
        st = state.get(pstep)
        if not st or st["open"] or not st["resolved_at"]:
            continue
        at = _parse(e.get("at")) or _parse(r.get("started_at"))
        done = _parse(st["resolved_at"])
        if at and done and done >= at:
            e["resolved"] = True
            e["resolved_at"] = st["resolved_at"]
            e["label"] = STEP_CN.get(pstep[len("nightly."):], "")
    for r in rows:
        if any(e.get("resolved") for e in r.get("errors") or []):
            recount(r)


def heal_after_success(command: str, args: Any = None) -> int:
    """一个离线步骤的命令成功跑完（不管是夜跑、插件「刷新目录」还是命令行）：夜跑里同一步挂着的报错（崩溃 / 超时）
    就是好了——在问题记录里标已解决。以前只有夜跑自己那一步成功才解决，白天跑好了的照样红着挂到第二晚。"""
    def flag(name: str) -> bool:
        return bool(getattr(args, name, False))
    slugs: tuple[str, ...] = ()
    if command == "catalog":
        slugs = ("catalog", "catalog-final")
    elif command == "embed":
        slugs = ("embed",)
    elif command == "enrich" and flag("pending"):
        slugs = ("enrich-pending",)
    elif command == "vision" and flag("upgrade"):
        slugs = ("vision-upgrade",)
    elif command == "vision" and flag("refine"):
        slugs = ("vision-refine",)
    elif command == "videos" and flag("transcribe") and flag("all"):
        slugs = ("videos-transcribe",)
    if not slugs:
        return 0
    try:
        from . import problems
        n = sum(problems.resolve("nightly." + s) for s in slugs)
        if n:
            problems.write_summary()
        return n
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] 夜跑那一步的报错没标成已好：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 0


def summary_line(row: dict[str, Any]) -> str:
    """`10/03 04:00 夜跑 · 新收 3 · 正文 3 ✅ · 附件 2 ✅ 1 ❌`（给 CLI / 日志看；界面自己拼同样的格式）。"""
    st = _parse(row.get("started_at"))
    head = f"{st:%m/%d %H:%M}" if st else "?"
    parts = [f"{head} {TRIGGER_CN.get(row.get('trigger'), row.get('trigger') or '')}".strip()]
    if row.get("interrupted"):
        parts.append(f"被中断 · 已收 {row.get('new') or 0} 篇")
    elif row.get("new"):
        parts.append(f"新收 {row['new']}")
    for k in KINDS:
        c = (row.get("counts") or {}).get(k)
        if not c:
            continue
        bits = [f"{KIND_CN[k]}"]
        if c.get("ok"):
            bits.append(f"{c['ok']} ✅")
        if c.get("failed"):
            bits.append(f"{c['failed']} ❌")
        parts.append(" ".join(bits))
    if len(parts) == 1:
        open_errors = [e for e in row.get("errors") or [] if not e.get("resolved")]
        parts.append("没有新内容" if not open_errors else "没做完")
    return " · ".join(parts)


def backlog() -> dict[str, Any] | None:
    """第一排「收藏 T 篇，已入库 A 篇，还差 R 篇，预计还要 D 天同步完」：数全走 fav_counts（和进度条「收藏已入库 A/T」同一份）。
    积压清零 / 读不到 = None。"""
    try:
        from .setup.backfill import backfill
        b = backfill()
    except Exception:  # noqa: BLE001
        return None
    if not b.get("favorites_total") or not b.get("deferred"):
        return None
    return {"favorites_total": b.get("favorites_total"), "archived": b.get("archived"), "deferred": b.get("deferred"),
            "remaining": b.get("deferred"), "days_left": b.get("days_left"), "daily_limit": b.get("daily_limit"),
            "message": f"收藏 {b['favorites_total']} 篇，已入库 {b.get('archived') or 0} 篇，还差 {b['deferred']} 篇"
                       + (f"，预计还要 {b['days_left']} 天同步完" if b.get("days_left") is not None else "")}


# --------------------------------------------------------------------------- 重试

# 步骤级报错能在这里重跑的（不碰号的离线步骤）；碰号的（收藏同步 / 附件补下 / 补查）只说怎么办
STEP_RETRY = {
    "catalog": ["catalog"], "catalog-final": ["catalog"], "embed": ["embed"],
    "enrich-pending": ["enrich", "--pending", "--budget-min", "60"],
    "vision-upgrade": ["vision", "--upgrade", "--limit", "30"],
    "vision-refine": ["vision", "--refine", "--limit", "0"],
    "videos-transcribe": ["videos", "--all", "--transcribe"],
}
TIMEOUT_SEC = {"ingest": 900, "attachments": 1200, "videos": 1800, "enrich": 1500, "catalog": 600, "embed": 1500,
               "vision": 2700}


def retry_plan(row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """失败项 → 现有补处理命令（同一篇同一命令只跑一次）；返回 (要跑的, 不在这里重跑的说明)。"""
    jobs: dict[tuple, dict[str, Any]] = {}
    notes: list[str] = []
    for it in row.get("items") or []:
        if it.get("ok"):
            continue
        kind, iid = it.get("kind"), it.get("id")
        if it.get("retry"):
            cmd = list(it["retry"])
        elif kind == "note" and it.get("url") and not it.get("note"):
            cmd = ["ingest", it["url"], "--origin", "cli"]
        elif kind in ("note", "vision", "summary") and iid:
            cmd = ["enrich", "--item", iid]
        elif kind == "attachment" and iid:
            cmd = ["attachments", iid]
        elif kind == "video" and iid:
            cmd = ["videos", iid, "--transcribe"]
        else:
            notes.append(f"{it.get('title') or iid or '一项'}：不知道怎么单独重跑")
            continue
        job = jobs.setdefault(tuple(cmd), {"cmd": cmd, "items": []})
        job["items"].append(it)
    for e in row.get("errors") or []:
        step = str(e.get("step") or "")
        slug = step.split(".", 1)[1] if step.startswith("nightly.") else step
        if slug in STEP_RETRY:
            jobs.setdefault(tuple(STEP_RETRY[slug]), {"cmd": STEP_RETRY[slug], "items": [], "step": step})
        elif slug.startswith("sync-favorites") or slug in ("sync.favorites", "login") or slug.startswith("attachments"):
            msg = "收藏同步 / 附件补下要用小红书号：不在这里重跑，处理好账号后点「立即同步」，或等下次同步"
            if msg not in notes:
                notes.append(msg)
    return list(jobs.values()), notes


def _run_cmd(cmd: list[str], run_id: str, timeout: float) -> tuple[int | None, str, bool]:
    """跑一条 `python -m link_brain …`（带这次同步的编号，结果并回同一行）；超时整棵杀（放过读取服务）。"""
    env = dict(os.environ)
    env[ENV_RUN] = run_id
    env[ENV_TRIGGER] = "retry"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env[storage.ENV_VAULT] = str(storage.vault_root())
    repo = str(storage.repo_root())
    env["PYTHONPATH"] = repo + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen([sys.executable, "-m", "link_brain", *cmd], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", **kw)
    try:
        _, err = proc.communicate(timeout=timeout)
        return proc.returncode, (err or "").strip(), False
    except subprocess.TimeoutExpired:
        from . import procs
        procs.kill_tree(proc.pid)
        try:
            _, err = proc.communicate(timeout=30)
        except (subprocess.TimeoutExpired, ValueError):
            err = ""
        return None, (err or "").strip(), True


def retry(run_id: str, *, runner: Callable[[list[str], str, float], tuple[int | None, str, bool]] | None = None) -> dict[str, Any]:
    """只重跑这一次失败的那几篇 / 那一步（现有补处理命令），结果并回同一行；如实返回每条怎样。"""
    runner = runner or _run_cmd
    row = next((r for r in _read() if r["run_id"] == run_id), None)
    if row is None:
        return {"ok": False, "code": "", "message": f"没有这次同步的记录：{run_id}", "results": []}
    jobs, notes = retry_plan(row)
    if not jobs:
        msg = "；".join(notes) if notes else "这次没有失败项要重试"
        return {"ok": not notes, "code": "", "message": msg, "results": [], "notes": notes, "run": row}
    started = _stamp()
    results = []
    for job in jobs:
        cmd = job["cmd"]
        code, err, timed_out = runner(cmd, run_id, TIMEOUT_SEC.get(cmd[0], 1200))
        tail = (err.splitlines() or [""])[-1][:200]
        ok = code in (0,) and not timed_out
        why = "" if ok else (f"超过 {TIMEOUT_SEC.get(cmd[0], 1200) // 60} 分钟没跑完，已停止" if timed_out
                             else tail or f"退出码 {code}")
        results.append({"cmd": cmd, "ok": ok, "error": why, "items": [it.get("id") for it in job["items"]],
                        "step": job.get("step")})
    # 子进程自己记过的项（这次重试里更新过）以它为准；没记的按退出码补一条
    fresh = next((r for r in _read() if r["run_id"] == run_id), row)
    touched = {(it.get("kind"), it.get("id")) for it in fresh.get("items") or [] if str(it.get("at") or "") >= started}
    for res, job in zip(results, jobs):
        for it in job["items"]:
            if (it.get("kind"), it.get("id")) in touched:
                continue
            _pending.append({**it, "ok": res["ok"], "reason": "" if res["ok"] else res["error"],
                             "code": "" if res["ok"] else (it.get("code") or ""), "at": _stamp()})

    def go(rows):
        r = next((x for x in rows if x["run_id"] == run_id), None)
        if r is None:
            return None
        items = list(_pending)
        _merge(r, items, [], 0)
        fixed_steps = {res.get("step") for res in results if res.get("ok") and res.get("step")}
        if fixed_steps:
            r["errors"] = [e for e in r["errors"] if e.get("step") not in fixed_steps]
        r["retried_at"] = _iso()
        recount(r)
        return r
    try:
        final = _edit(go)
    except Exception as exc:  # noqa: BLE001
        final = None
        notes.append(f"重试结果没写进同步记录：{type(exc).__name__}: {exc}")
    _pending.clear()
    final = final or fresh
    still = [it for it in final.get("items") or [] if not it.get("ok")]
    done = sum(1 for r in results if r["ok"])
    msg = f"重跑了 {len(results)} 项，成了 {done} 项"
    if still:
        msg += f"；还有 {len(still)} 篇没好：" + "；".join(f"{it.get('title') or it.get('id')}（{it.get('reason') or '原因未知'}）"
                                                for it in still[:3])
    if notes:
        msg += "。" + "；".join(notes)
    return {"ok": done == len(results) and not still, "code": "", "message": msg, "results": results,
            "notes": notes, "run": final}


# --------------------------------------------------------------------------- CLI

def add_parser(sub) -> None:
    p = sub.add_parser("synclog", help="同步记录（目录页「同步记录」窗口）：list / begin / end / record / retry")
    ss = p.add_subparsers(dest="synclog_command")
    q = ss.add_parser('stop', help='插件停止自己启动的同步后收尾')
    q.add_argument('--by-user', action='store_true')
    q = ss.add_parser("list", help="最近几次同步（新的在前）+ 第一排的积压")
    q.add_argument("--limit", type=int, default=50)
    q = ss.add_parser("begin", help="开一次同步，输出 run_id（仓外夜跑脚本开头用：设成环境变量 LINK_BRAIN_SYNC_RUN）")
    q.add_argument("--trigger", choices=sorted(TRIGGER_CN), default=None)
    q = ss.add_parser("end", help="给这一次收尾（不给 --run = 最近一条没收尾的）")
    q.add_argument("--run", default=None)
    q.add_argument("--exit", dest="exit_code", type=int, default=None, help="夜跑的退出码（记下来）")
    q = ss.add_parser("record", help="记一条步骤级报错（仓外脚本：某步超时 / 被杀，Python 自己记不上的）")
    q.add_argument("--step", required=True)
    q.add_argument("--error", required=True, help="一句原因")
    q.add_argument("--code", default="")
    q.add_argument("--run", default=None)
    q = ss.add_parser("retry", help="只重跑这一次失败的那几篇 / 那一步")
    q.add_argument("--run", required=True)


def run(args) -> int:
    import contextlib
    from .read import EXIT_ERROR, EXIT_OK, dump_json

    cmd = getattr(args, "synclog_command", None)
    with contextlib.redirect_stdout(sys.stderr):
        if cmd == 'stop':
            from . import sync_state
            stopped = bool(args.by_user and sync_state.stopped_by_user())
            if stopped:
                end()
            out = {'ok': stopped, 'code': '', 'message': '已手动停止' if stopped else '没有已停止的同步可收尾'}
        elif cmd == "begin":
            rid = begin(args.trigger, own=False)
            out = {"ok": bool(rid), "code": "", "message": "已开一次同步记录" if rid else "同步记录没开上", "run_id": rid}
        elif cmd == "end":
            done = end(args.run, exit_code=args.exit_code)
            out = {"ok": True, "code": "", "message": "已收尾" if done else "没有要收尾的", "closed": done}
        elif cmd == "record":
            if args.run:
                os.environ[ENV_RUN] = args.run
            error(args.step, args.error, args.code)
            rid = flush(create=False)
            out = {"ok": bool(rid), "code": "", "message": "已记下" if rid else "没有进行中的同步，没记", "run_id": rid}
        elif cmd == "retry":
            out = retry(args.run)
        else:
            rows = load(getattr(args, "limit", 50) or 50)
            out = {"ok": True, "code": "", "message": f"最近 {len(rows)} 次同步", "runs": rows, "backlog": backlog(),
                   "triggers": TRIGGER_CN, "kinds": KIND_CN}
    dump_json(out)
    return EXIT_OK if out.get("ok") else EXIT_ERROR
