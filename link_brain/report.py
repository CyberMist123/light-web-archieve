"""`python -m link_brain report week [--days 7]`：目录页「本周同步情况」窗口的数据（第 6 批）。

只读本地，不联网、不调读取服务、不写任何文件：
- 那天新收几篇：按对象 `meta.json` 的 `first_archived_at`（首次入库时间，本机时区的日历日）分天；
  枚举对象优先读 `_archive/index.db`（只读打开），读不了就扫 `_archive/<来源>/*/meta.json`。
- 正文 = meta.visible_note 指的那份可见笔记在不在；机读版 = `derived/agent.md` 在不在。
- 附件 = `attachments.inventory`（attachments.json + source.json 声明）：该有的（有文件编号或已下到的；只是正文
  提到「附件」、找不到文件的「线索」不算该有）下好几个、还缺几个；下好的 PDF / Word 转成文字（derived/attachments/*.md）几个。
- 识图 / 概要还差 = `enrich.needs`（夜跑补处理用的同一个判断）。
- 那天夜跑走完没有：有包内夜跑日志（`~/.link-brain/nightly.log`）就按「=== 夜跑开始 / 结束 ===」判；
  没有（比如还在用仓外脚本）就不判走没走完，只列那天登记过的问题（problems.jsonl）+ sync-status.json 说得上的那天。
- 还剩几篇逐晚处理 = sync-status.json 的 `deferred`。
stdout 只有一行 JSON（CONVENTIONS §1），人话进 stderr。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import storage

TIME_FIELD = "first_archived_at"
TIME_FIELD_NOTE = "按 meta.json 的 first_archived_at（首次入库时间）分天"
WEEKDAYS = "一二三四五六日"
CONVERTIBLE = (".pdf", ".docx")  # 与 docconv.CONVERTIBLE_SUFFIXES 一致：只有这两种会转成文字
NIGHTLY_LOG_TAIL = 2 * 1024 * 1024
# 不算夜跑的问题：设置换算、问收藏、远程阅读
_NOT_NIGHTLY_STEPS = ("config", "ask", "remote")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def _local_day(ts: Any) -> date | None:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return (dt.astimezone() if dt.tzinfo else dt).date()


def _objects(source: str | None = None) -> list[tuple[str, str, str | None]]:
    """[(source, source_id, first_archived_at)]：index.db 只读打开；不行就扫 meta.json。"""
    db = storage.index_db_path()
    if db.is_file():
        try:
            conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
            try:
                rows = conn.execute("SELECT source, source_id, first_archived_at FROM objects").fetchall()
            finally:
                conn.close()
            return [(r[0], r[1], r[2]) for r in rows if not source or r[0] == source]
        except sqlite3.Error:
            pass
    out = []
    root = storage.archive_root()
    for meta_path in sorted(root.glob("*/*/meta.json")):
        meta = _load(meta_path)
        if isinstance(meta, dict) and (not source or meta_path.parent.parent.name == source):
            out.append((meta_path.parent.parent.name, meta_path.parent.name, meta.get(TIME_FIELD)))
    return out


def _item_status(src: str, sid: str) -> dict[str, Any] | None:
    from . import attachments, enrich

    obj = storage.object_dir(src, sid)
    meta = _load(obj / "meta.json")
    if not isinstance(meta, dict):
        return None
    vault = storage.vault_root()
    visible = meta.get("visible_note")
    has_note = bool(visible) and (vault / visible).is_file()
    has_agent = (obj / "derived" / "agent.md").is_file()
    expected = downloaded = convertible = converted = 0
    try:
        inv = attachments.inventory(obj, meta)
    except Exception:  # noqa: BLE001 - 一篇读坏不拖垮整张表
        inv = {"files": []}
    for f in inv.get("files") or []:
        if not f.get("downloaded") and not f.get("doc_id"):
            continue  # 线索：正文提到附件、找不到文件，不算该有
        expected += 1
        if f.get("downloaded"):
            downloaded += 1
            if Path(str(f.get("file") or f.get("name") or "")).suffix.lower() in CONVERTIBLE:
                convertible += 1
                converted += bool(f.get("markdown"))
    try:
        needs = enrich.needs(src, sid)
    except Exception:  # noqa: BLE001
        needs = []
    missing = []
    if not has_note:
        missing.append("正文")
    if not has_agent:
        missing.append("机读版")
    if expected > downloaded:
        missing.append(f"附件缺 {expected - downloaded} 个")
    if convertible > converted:
        missing.append(f"附件转文字差 {convertible - converted} 个")
    if "vision" in needs:
        missing.append("识图")
    if "summary" in needs:
        missing.append("概要")
    return {
        "id": meta.get("item_id") or sid, "title": meta.get("title") or sid,
        "note": visible if has_note else None,
        "has_note": has_note, "has_agent": has_agent,
        "att_expected": expected, "att_downloaded": downloaded,
        "att_convertible": convertible, "att_converted": converted,
        "vision_missing": "vision" in needs, "summary_missing": "summary" in needs,
        "missing": missing,
    }


def _empty_counts() -> dict[str, Any]:
    return {"new": 0,
            "note": {"done": 0, "missing": 0},
            "agent": {"done": 0, "missing": 0},
            "attachments": {"expected": 0, "downloaded": 0, "missing": 0, "convertible": 0, "converted": 0, "unconverted": 0},
            "vision_missing": 0, "summary_missing": 0}


def _add(counts: dict[str, Any], st: dict[str, Any]) -> None:
    counts["new"] += 1
    counts["note"]["done" if st["has_note"] else "missing"] += 1
    counts["agent"]["done" if st["has_agent"] else "missing"] += 1
    a = counts["attachments"]
    a["expected"] += st["att_expected"]
    a["downloaded"] += st["att_downloaded"]
    a["missing"] += st["att_expected"] - st["att_downloaded"]
    a["convertible"] += st["att_convertible"]
    a["converted"] += st["att_converted"]
    a["unconverted"] += st["att_convertible"] - st["att_converted"]
    counts["vision_missing"] += st["vision_missing"]
    counts["summary_missing"] += st["summary_missing"]


# ------------------------------------------------------------------ 夜跑
def _nightly_runs() -> dict[date, dict[str, Any]] | None:
    """包内夜跑日志：{日: {started_at, ended_at|None}}（那天最后一趟）；没有日志 = None。"""
    from . import nightly

    log = nightly.default_log_path()
    try:
        with open(log, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - NIGHTLY_LOG_TAIL))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    runs: dict[date, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if nightly.START_MARK in line or nightly.END_MARK in line:
            try:
                at = datetime.strptime(line.strip()[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if nightly.START_MARK in line:
                current = {"started_at": at.isoformat(timespec="minutes"), "ended_at": None}
                runs[at.date()] = current
            elif current is not None and current["ended_at"] is None:
                current["ended_at"] = at.isoformat(timespec="minutes")
    return runs


def _day_problems() -> dict[date, list[dict[str, Any]]]:
    """problems.jsonl 里每天登记过的问题（同 key 一天只算一条），附「现在还没解决」。"""
    from . import problems

    rows = problems._read_rows()
    still_open = {k for k, r in problems._fold(rows).items() if not r.get("resolved_at")}
    out: dict[date, dict[str, dict[str, Any]]] = {}
    for r in rows:
        if r.get("resolved_at") or str(r.get("step") or "") in _NOT_NIGHTLY_STEPS:
            continue
        d = _local_day(r.get("ts"))
        if d is None:
            continue
        shown = problems.describe(r.get("code", ""), r.get("reason"), r.get("next_at"))
        out.setdefault(d, {})[r["key"]] = {
            "code": shown["code"], "label": shown["label"], "group": shown["group"], "hover": shown["hover"],
            "step": r.get("step"), "step_label": problems.step_label(r.get("step")),
            "item_id": r.get("item_id"), "title": r.get("title"), "open": r["key"] in still_open}
    return {d: list(v.values()) for d, v in out.items()}


def _nightly_for(day: date, runs: dict[date, dict[str, Any]] | None, probs: list[dict[str, Any]],
                 sync: dict[str, Any], today: date) -> dict[str, Any]:
    open_n = sum(p["open"] for p in probs)
    parts: list[str] = []
    finished: bool | None = None
    run = (runs or {}).get(day)
    source = "log" if runs is not None else "problems"
    if runs is not None:
        if run is None:
            parts.append("那天没跑夜跑")
        elif run["ended_at"]:
            finished = True
            parts.append("夜跑走完了")
        else:
            finished = False
            started = run["started_at"][11:16]
            parts.append(f"夜跑可能还在跑（{started} 开始）" if day == today and sync.get("state") == "running"
                         else f"夜跑没走完（{started} 开始，日志里没有结束）")
    else:
        if _local_day(sync.get("last_success")) == day:
            parts.append("收藏同步成功")
        if _local_day(sync.get("updated_at")) == day and sync.get("state") in ("failed", "blocked"):
            why = str(sync.get("detail") or sync.get("message") or "").strip()
            parts.append("收藏同步没成功" + (f"：{why}" if why else ""))
    if probs:
        first = probs[0]
        head = f"{first['step_label']} · {first['label']}" if first.get("step_label") else first["label"]
        more = f" 等 {len(probs)} 个问题" if len(probs) > 1 else ""
        tail = f"（{open_n} 个还没解决）" if open_n else "（都已解决）"
        parts.append(f"有问题：{head}{more}{tail}")
    elif runs is None and not parts:
        parts.append("没有问题记录")
    return {"source": source, "finished": finished,
            "started_at": run["started_at"] if run else None, "ended_at": run["ended_at"] if run else None,
            "problems": probs, "open_problems": open_n, "text": "；".join(parts)}


def week(days: int = 7, *, now: datetime | None = None, source: str | None = None) -> dict[str, Any]:
    from . import sync_state

    days = max(1, min(int(days or 7), 31))
    now = (now or datetime.now().astimezone())
    today = (now.astimezone() if now.tzinfo else now).date()
    start = today - timedelta(days=days - 1)
    per_day: dict[date, list[dict[str, Any]]] = {start + timedelta(days=i): [] for i in range(days)}
    no_time = 0
    for src, sid, ts in _objects(source):
        d = _local_day(ts)
        if d is None:
            meta = _load(storage.object_dir(src, sid) / "meta.json")
            d = _local_day(meta.get(TIME_FIELD)) if isinstance(meta, dict) else None
        if d is None:
            no_time += 1
            continue
        if d in per_day:
            st = _item_status(src, sid)
            if st is not None:
                per_day[d].append(st)
    try:
        sync = sync_state._read_raw() or {}
    except Exception:  # noqa: BLE001
        sync = {}
    runs = _nightly_runs()
    try:
        probs = _day_problems()
    except Exception:  # noqa: BLE001
        probs = {}
    rows, total = [], _empty_counts()
    for d in sorted(per_day, reverse=True):
        counts = _empty_counts()
        for st in per_day[d]:
            _add(counts, st)
            _add(total, st)
        incomplete = [{"id": st["id"], "title": st["title"], "note": st["note"], "missing": st["missing"]}
                      for st in per_day[d] if st["missing"]]
        rows.append({"date": d.isoformat(), "weekday": "周" + WEEKDAYS[d.weekday()], **counts,
                     "incomplete": incomplete,
                     "nightly": _nightly_for(d, runs, probs.get(d, []), sync, today)})
    deferred = sync.get("deferred")
    try:
        deferred = int(deferred) if deferred not in (None, "") else None
    except (TypeError, ValueError):
        deferred = None
    message = f"最近 {days} 天新收 {total['new']} 篇"
    return {"ok": True, "code": "", "message": message, "days": days,
            "from": start.isoformat(), "to": today.isoformat(), "generated_at": now.isoformat(timespec="seconds"),
            "time_field": TIME_FIELD, "time_field_note": TIME_FIELD_NOTE, "no_time": no_time,
            "nightly_source": "log" if runs is not None else "problems",
            "rows": rows, "total": total, "deferred": deferred,
            "sync": {"state": sync.get("state"), "message": sync.get("message"),
                     "last_success": sync.get("last_success"), "updated_at": sync.get("updated_at")}}


def add_parser(sub) -> None:
    p = sub.add_parser("report", help="本周同步情况：最近几天新收几篇、各项生成齐没有、夜跑走完没有（只读本地），输出 JSON")
    rsub = p.add_subparsers(dest="report_cmd", metavar="<week>")
    pw = rsub.add_parser("week", help="最近 N 天（默认 7）按天汇总")
    pw.add_argument("--days", type=int, default=7)


def run(args) -> int:
    from .read import dump_json

    if getattr(args, "report_cmd", None) != "week":
        print("用法：python -m link_brain report week [--days 7]", file=sys.stderr)
        return 1
    try:
        out = week(args.days)
    except Exception as exc:  # noqa: BLE001 - 给页面一句人话
        dump_json({"ok": False, "code": "", "message": f"读不出同步情况：{exc}", "rows": []})
        print(f"读不出同步情况：{exc}", file=sys.stderr)
        return 1
    print(out["message"], file=sys.stderr)
    dump_json(out)
    return 0
