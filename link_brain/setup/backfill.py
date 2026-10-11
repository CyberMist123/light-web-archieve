"""`setup backfill`：补历史收藏的进度——收藏总数 / 已入库 / 还差 / 每天上限 / 预计天数。只读本地，不联网。

1011 起三个数全走 `link_brain.fav_counts.counts()`（进度条、同步记录第一排同一份口径，见那个文件头）：
- 收藏总数 = 收藏名单（fav-list.json）条数；没有名单退到 sync-status.json 的 last_favorites / favorites。
- 已入库 = 名单里在库里或回收站里的篇数（没有名单时退到「从收藏进来的对象数」）；archived_all = 库里对象总数。
- 还差（deferred，旧键名照留；另给 remaining 同值）= 总数 − 已入库。上次同步自己记的 deferred（那一趟没抓、留到以后的）
  只作参考放在 last_sync_deferred，不再拿它当「还剩」（它不含中途被停那次没来得及数的）。
- 每天上限：设置 sync.dailyNewLimit（0 = 不限）。预计天数 = 还差 ÷ 每天上限 向上取整；不限时一晚（可能被夜跑时间预算截断）。
缺数据的项给 null。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def backfill() -> dict[str, Any]:
    from .. import ai_config, fav_counts, sync_state
    try:
        status = sync_state.load()
    except Exception:  # noqa: BLE001
        status = {}
    c = fav_counts.counts()
    total, archived, remaining = c["favorites_total"], c["archived"], c["remaining"]
    limit = ai_config.sync_options().get("dailyNewLimit")
    days = fav_counts.days_left(remaining, limit)
    if total is None:
        message = "还没同步过收藏，收藏总数不知道"
    elif remaining:
        message = f"还差 {remaining} 篇，每天最多 {limit or '不限'} 篇，约 {days} 天补完"
    else:
        message = "历史收藏都补完了"
    return {"ok": True, "code": "", "message": message, "favorites_total": total,
            "archived": archived if archived is not None else 0, "archived_all": c["library_total"] or 0,
            "deferred": remaining, "remaining": remaining,
            "deferred_from": {"list": "favorites_list", "baseline": "total_minus_archived"}.get(c["basis"]),
            "last_sync_deferred": _int(status.get("deferred")),
            "daily_limit": limit, "days_left": days,
            "last_sync": status.get("last_success") or status.get("updated_at"),
            "as_of": datetime.now().astimezone().isoformat(timespec="seconds")}
