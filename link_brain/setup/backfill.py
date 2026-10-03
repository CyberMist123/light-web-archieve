"""`setup backfill`：补历史收藏的进度——收藏总数 / 已入库 / 还剩 / 每天上限 / 预计天数。只读本地，不联网。

- 收藏总数：sync-status.json 的 last_favorites（正常读到的基准；读到一截的那次不算）→ 退到 favorites。
- 已入库：_archive/xiaohongshu/*/meta.json 里 favorited_by 不空的篇数（从收藏进来的；分享单篇进来的另记 archived_all）。
- 还剩：上次同步记的 deferred（那次没抓、留到以后的）→ 没有就「总数 − 已入库」（不小于 0）。
- 每天上限：设置 sync.dailyNewLimit（0 = 不限）。预计天数 = 还剩 ÷ 每天上限 向上取整；不限时剩的一晚做完（可能被夜跑时间预算截断）。
缺数据的项给 null。
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any


def _archived() -> tuple[int, int]:
    from .. import storage
    root = storage.archive_root() / "xiaohongshu"
    fav = total = 0
    try:
        dirs = list(root.iterdir())
    except OSError:
        return 0, 0
    for d in dirs:
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        total += 1
        if meta.get("favorited_by") or meta.get("ingest_kind") == "favorite":
            fav += 1
    return fav, total


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def backfill() -> dict[str, Any]:
    from .. import ai_config, sync_state
    try:
        status = sync_state.load()
    except Exception:  # noqa: BLE001
        status = {}
    total = _int(status.get("last_favorites")) or _int(status.get("favorites"))
    archived, archived_all = _archived()
    deferred = _int(status.get("deferred"))
    deferred_from = "last_sync" if deferred is not None else None
    if deferred is None and total is not None:
        deferred, deferred_from = max(total - archived, 0), "total_minus_archived"
    limit = ai_config.sync_options().get("dailyNewLimit")
    if deferred is None:
        days = None
    elif deferred == 0:
        days = 0
    elif not limit:
        days = 1
    else:
        days = math.ceil(deferred / int(limit))
    if total is None:
        message = "还没同步过收藏，收藏总数不知道"
    elif deferred:
        message = f"还剩 {deferred} 篇，每天最多 {limit or '不限'} 篇，约 {days} 天补完"
    else:
        message = "历史收藏都补完了"
    return {"ok": True, "code": "", "message": message, "favorites_total": total, "archived": archived,
            "archived_all": archived_all, "deferred": deferred, "deferred_from": deferred_from,
            "daily_limit": limit, "days_left": days,
            "last_sync": status.get("last_success") or status.get("updated_at"),
            "as_of": datetime.now().astimezone().isoformat(timespec="seconds")}
