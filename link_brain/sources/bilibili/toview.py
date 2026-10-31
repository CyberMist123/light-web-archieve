"""B 站「稍后再看」：和收藏夹一起同步，当成一个叫「稍后再看」的专辑（1031 作者：「稍后再看也一起同步」）。

接口（bilibili-API-collect 的 history&toview/toview.md，要登录态 Cookie）：`GET x/v2/history/toview`
→ `data = {count, list: [{aid, bvid, title, videos（分 P 数）, duration, owner{mid,name}, add_at（加入时间）, state, cid, pubdate…}]}`，
一次回全部（没有分页）。没加过任何视频时 `list` 可能是 null / 空。`state < 0` = 稿件已失效（删了 / 锁了 / 审核中）。

快照写成和收藏夹**同形状**（`favorites.snapshot_path(mid, "toview")` = `_archive/bilibili-sync/folders/<mid>-toview.json`），
于是 `sync.plan` / 下载 / 断点续跑 / 挑选页（`sync.picker`）都不用分支；收藏夹 id 一律是字符串 `"toview"`。

从稍后再看里移除的：**不删本地、不解除专辑**（`update_relations(deactivate_missing=False)`）——看完就移出是常态，
本地那条照旧归「稍后再看」专辑。读失败（限流 / 断网）时退回上次的快照接着用，并在结果里记 error。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from link_brain import storage

from . import favorites

TOVIEW_URL = favorites.API + "/x/v2/history/toview"
TOVIEW_ID = "toview"          # 挑选页 / --skip-folder 用的「收藏夹 id」
TITLE = "稍后再看"            # 专辑名


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def item_row(raw: dict[str, Any]) -> dict[str, Any]:
    """稍后再看的一条 → 和 favorites._item_row 同字段（fav_time 用加入稍后再看的时间）。"""
    owner = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
    try:
        state = int(raw.get("state") or 0)
    except (TypeError, ValueError):
        state = 0
    bvid = str(raw.get("bvid") or "")
    invalid = state < 0
    pages = raw.get("pages") if isinstance(raw.get("pages"), list) else []
    return {
        "bvid": bvid,
        "id": int(raw.get("aid") or 0),
        "kind": "video" if bvid else "other",
        "type": 2,
        "title": str(raw.get("title") or ""),
        "fav_time": int(raw.get("add_at") or 0) or None,
        "attr": 9 if invalid else 0,
        "invalid": invalid,
        "invalid_reason": "invalid" if invalid else None,
        "page_count": int(raw.get("videos") or len(pages) or 1),
        "first_cid": int(raw.get("cid") or 0) or None,
        "upper_mid": int(owner.get("mid") or 0) or None,
        "upper_name": str(owner.get("name") or ""),
        "pubtime": int(raw.get("pubdate") or 0) or None,
        "duration": int(raw.get("duration") or 0) or None,
        "cover": favorites._https(raw.get("pic")),   # 1101：待下载页卡片的封面网址（稍后再看的接口叫 pic）
        "listed": True,
    }


def snapshot_from(data: Any, owner_mid: Any, *, now: str | None = None) -> dict[str, Any]:
    stamp = now or _now()
    data = data if isinstance(data, dict) else {}
    rows = [item_row(x) for x in (data.get("list") or []) if isinstance(x, dict)]
    seen: set[str] = set()
    items = []
    for it in rows:   # 同一个 BV 只留一条（接口偶尔重复）
        k = favorites.item_key(it)
        if k not in seen:
            seen.add(k)
            items.append(it)
    count = int(data.get("count") or len(items))
    complete = len(items) >= count
    return {"schema_version": favorites.SCHEMA_VERSION, "kind": "toview", "owner_mid": int(owner_mid) if owner_mid else None,
            "media_id": TOVIEW_ID, "fid": None, "title": TITLE, "private": True, "fetched_at": stamp, "started_at": stamp,
            "complete": complete, "status": ("empty" if not items else "complete") if complete else "partial",
            "media_count": count, "item_count": len(items), "pages_read": [1], "missing_pages": [], "reached_end": True,
            "raw_count": len(rows), "error": None if complete else favorites._err("count_mismatch", f"稍后再看说有 {count} 条，只给了 {len(items)} 条"),
            "items": items}


def sync_toview(client, owner_mid: Any, *, log: Callable[[str], None] | None = None,
                now: str | None = None) -> dict[str, Any]:
    """读一次稍后再看 → 写快照 + 关系表（不解除）。回 {snapshot, error, stale}。

    读失败：有上次的快照就接着用（stale=True，不覆盖文件），没有就回一个 items=[] 的 error 快照（不写盘）。"""
    say = log or (lambda _m: None)
    path = favorites.snapshot_path(owner_mid, TOVIEW_ID)
    data, err = favorites._get(client, TOVIEW_URL, {})
    if err:
        prev = favorites._read(path)
        say(f"稍后再看没读到（{err.get('message')}）" + ("，用上次的快照" if prev else ""))
        if prev:
            return {"snapshot": prev, "error": err, "stale": True}
        snap = snapshot_from({}, owner_mid, now=now)
        snap.update(complete=False, status=err.get("reason") or "error", error=err, media_count=None)
        return {"snapshot": snap, "error": err, "stale": False}
    snap = snapshot_from(data, owner_mid, now=now)
    storage.write_json(path, snap)
    if snap["owner_mid"]:
        favorites.update_relations(snap, None, deactivate_missing=False)
    say(f"稍后再看：{snap['item_count']} 条")
    return {"snapshot": snap, "error": None, "stale": False}
