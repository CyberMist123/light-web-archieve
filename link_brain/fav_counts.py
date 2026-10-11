"""收藏同步进度的几个数——全仓只此一份口径（1011 她：同一时刻目录页「43 / 659 篇」、进度条「库里 605/1246（还差 641 篇）」、
同步记录「一共 1233 篇收藏，已入库 649 篇」三处各说各的）。进度条（favorites._Live）、同步记录第一排（synclog.backlog）、
`setup backfill` 都从这里取，界面上统一说「收藏已入库 A/T（还差 R 篇）」。

- favorites_total（T，收藏一共几篇）= 收藏名单 `_archive/fav-list.json` 的条数：全量读时整份换掉、增量读时把最新一段并在最前，
  所以它是「现在的收藏夹」。以前同步记录用 sync-status.json 的 last_favorites（上一次**正常收尾**的全量条数），中途被停的那次
  读到的新总数不进去——1011 那天名单已是 1246，它还停在 1233。
  没有名单（还没读过全量）→ 退到 last_favorites / favorites，basis = "baseline"。
- archived（A，已入库）= 名单里的这些笔记，在库里（`_archive/xiaohongshu/<id>/`）或在回收站（删了 = 不再同步）的篇数。
  basis = "baseline" 时没法逐篇对，退到「从收藏进来的对象数」（meta 的 favorited_by / ingest_kind=favorite）。
  以前同步记录数的就是后者（649）：里面有 47 篇后来取消了收藏、已不在名单里，所以比进度条的 605 多。
- remaining（R，还差）= T − A（含抓不到的：已删 / 仅作者可见的那几篇，照实算在里面）。
- library_total（库里一共）= 库里的对象数（含分享 / 导入单篇进来的、后来取消收藏的；回收站里的不算）。目录页「共 N 篇」数的是
  catalog-data 的 items，同一个东西。所以「已入库 A」≤「库里 N」，差的就是不在收藏夹里的那些。

只读本地，不联网；任何一项数不出来给 None（界面缺哪项不显示哪项，fail-open）。
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable

SOURCE = "xiaohongshu"   # = adapters.xiaohongshu.SOURCE（不为一个常量去加载整个适配器）


def library_ids() -> set[str]:
    """库里已有的（对象目录名 = note_id）+ 回收站里的 note_id。读不到就是空集。"""
    from . import storage
    ids: set[str] = set()
    try:
        root = storage.archive_root() / SOURCE
        if root.is_dir():
            ids.update(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        pass
    ids |= _tombstones()
    return ids


def _tombstones() -> set[str]:
    from . import index as index_mod
    try:
        conn = index_mod.connect()
    except Exception:  # noqa: BLE001
        return set()
    try:
        return {str(r[0]) for r in conn.execute("SELECT source_id FROM tombstones WHERE source = ?", (SOURCE,))}
    except Exception:  # noqa: BLE001
        return set()
    finally:
        conn.close()


def _objects() -> tuple[int, int]:
    """(库里对象数, 其中从收藏进来的)。"""
    from . import storage
    total = fav = 0
    try:
        dirs = [d for d in (storage.archive_root() / SOURCE).iterdir() if d.is_dir()]
    except OSError:
        return 0, 0
    for d in dirs:
        total += 1
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("favorited_by") or meta.get("ingest_kind") == "favorite":
            fav += 1
    return total, fav


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def counts(pool_ids: Iterable[str] | None = None, *, have: set[str] | None = None) -> dict[str, Any]:
    """{favorites_total, archived, remaining, library_total, basis}。

    pool_ids：这一趟同步手上的收藏名单（favorites._Live 用：全量读到的 / 增量 + 名单其余的 / 按名单补抓的）；
    不给 = 读 `_archive/fav-list.json`。have：库里 + 回收站的 note_id（调用方已经数过就传进来，省一次扫目录）。"""
    out: dict[str, Any] = {"favorites_total": None, "archived": None, "remaining": None, "library_total": None, "basis": None}
    try:
        lib_total, fav_objects = _objects()
        out["library_total"] = lib_total
    except Exception:  # noqa: BLE001
        lib_total, fav_objects = None, None
    ids: set[str] | None = None
    try:
        if pool_ids is not None:
            ids = {str(x) for x in pool_ids if x}
        else:
            from .favorites import load_snapshot
            snap = load_snapshot()
            items = snap.get("items") or []
            if items:
                ids = {str(x.get("note_id")) for x in items if isinstance(x, dict) and x.get("note_id")}
    except Exception:  # noqa: BLE001
        ids = None
    if ids:
        have = library_ids() if have is None else have
        total, archived = len(ids), len(ids & have)
        out.update(favorites_total=total, archived=archived, remaining=max(0, total - archived), basis="list")
        return out
    try:
        from . import sync_state
        status = sync_state.load()
    except Exception:  # noqa: BLE001
        status = {}
    total = _int(status.get("last_favorites")) or _int(status.get("favorites"))
    if total:
        archived = fav_objects or 0
        out.update(favorites_total=total, archived=archived, remaining=max(0, total - archived), basis="baseline")
    return out


def days_left(remaining: int | None, daily_limit: int | None) -> int | None:
    """还差 R 篇、每天最多 L 篇 → 约几天（L=0 不限 = 一晚；R=0 = 0）。"""
    if remaining is None:
        return None
    if remaining <= 0:
        return 0
    if not daily_limit:
        return 1
    return math.ceil(remaining / int(daily_limit))


def text(c: dict[str, Any]) -> str:
    """统一说法：「收藏已入库 A/T（还差 R 篇）」；缺数 = ''。"""
    a, t, r = c.get("archived"), c.get("favorites_total"), c.get("remaining")
    if a is None or not t:
        return ""
    return f"收藏已入库 {a}/{t}" + (f"（还差 {r} 篇）" if r else "")
