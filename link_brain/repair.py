"""Bounded same-run repairs; account and list-reading failures never auto-retry."""
from __future__ import annotations

import sys
import time
from datetime import datetime

from . import enrich, problems, storage


def command(row):
    step, item = row.get("step"), row.get("item_id")
    if problems.classify(row["code"]) == "NEEDS_HUMAN":
        return None
    if step in ("sync.favorites", "login", "ingest", "attachments.recheck"):
        return None
    if step in ("enrich.summary", "vision.layer1") and item:
        return ["enrich", "--item", item, "--budget-min", "4"]
    if step == "vision.refine" and item:
        return ["vision", "--refine-mark", item, "--now"]
    if step == "attachments.convert" and item:
        return ["pdf2md", item, "--force"]
    if step == "attachments.download" and item:
        return ["attachments", item, "--budget-min", "4"]
    if step == "videos.transcribe" and item:
        return ["videos", item, "--transcribe"]
    if step == "embed" or step == "nightly.embed":
        return ["embed"]
    if step == "config":
        return ["problems", "summary"]
    if step in ("nightly.catalog", "nightly.catalog-final"):
        return ["catalog"]
    return None


def describe(row):
    manual = problems.classify(row["code"]) == "NEEDS_HUMAN"
    args = command(row)
    return {"repairable": not manual, "repair_minutes": 5,
            "repair_note": "本晚不重读收藏或原网页；保留已入档内容" if row.get("step") in ("sync.favorites", "ingest", "attachments.recheck")
            else "重跑对应步骤并核对问题记录" if args else "检查当前条件；无法自动修复时给出下一步"}


def run(*, key=None, since=None, budget_seconds=600, execute=None, clock=time.monotonic):
    execute = execute or enrich.run_limited
    deadline = clock() + min(600, max(0, budget_seconds))
    now = datetime.now().astimezone()
    if since and now.hour < 7:
        deadline = min(deadline, clock() + (now.replace(hour=7, minute=0, second=0, microsecond=0) - now).total_seconds())
    results = []
    with storage.file_lock("problem-repair", wait_s=0, owner="repair"):
        rows = problems.load()
        for row in rows:
            if key and row["key"] != key:
                continue
            if since and row["ts"] < since:
                continue
            if problems.classify(row["code"]) == "NEEDS_HUMAN":
                continue
            if not problems.is_open(row["step"], row.get("item_id"), row["code"]):
                continue
            args = command(row)
            remaining = deadline - clock()
            if remaining <= 0:
                results.append({"key": row["key"], "status": "deferred", "message": "本轮自愈时限已到；可点现在修"})
                continue
            if not args:
                reason = ("已检查：不自动重读收藏 / 原网页" if row["step"] in ("sync.favorites", "ingest", "attachments.recheck")
                          else "已检查：当前没有可执行的自动修复动作")
                message = reason + "；原因：" + row["reason"][:80] + "；下一步：" + (
                    "下次计划同步再读" if row["step"] == "sync.favorites" else "检查配置或原文件后再点现在修")
                problems.report(row["step"], row["code"], message, item_id=row.get("item_id"), title=row.get("title"), action="gave_up")
                results.append({"key": row["key"], "status": "unresolved", "message": message})
                continue
            problems.report(row["step"], row["code"], "正在修 / 预计 5 分钟", item_id=row.get("item_id"), title=row.get("title"), action="retrying")
            try:
                code, error, timed_out = execute([sys.executable, "-m", "link_brain", *args], min(300, remaining))
            except Exception as exc:
                code, error, timed_out = 1, str(exc), False
            if code == 0 and row["step"] in ("nightly.embed", "nightly.catalog", "nightly.catalog-final"):
                problems.resolve(row["step"], row.get("item_id"), row["code"])
            open_now = problems.is_open(row["step"], row.get("item_id"), row["code"])
            if not open_now:
                results.append({"key": row["key"], "status": "resolved", "message": "已修好"})
            else:
                message = "已试：" + " ".join(args[:2]) + "；未修好：" + ("到达本轮时限" if timed_out else error[-80:] or "步骤结束但问题仍未解决") + "；下一步：检查配置 / 原文件后点现在修"
                problems.report(row["step"], row["code"], message, item_id=row.get("item_id"), title=row.get("title"), action="gave_up")
                results.append({"key": row["key"], "status": "unresolved", "message": message})
    return {"ok": all(row["status"] == "resolved" for row in results), "results": results,
            "message": f"自愈结束：修好 {sum(row['status'] == 'resolved' for row in results)} / {len(results)} 条"}

