"""小红书「专辑」（1019）：她自己给收藏分的组，和标签分开存。

数据：`_archive/albums.json`
    {"schema": 1, "listed_at", "expected", "list_partial",
     "boards": {<专辑id>: {"name", "total", "privacy", "desc", "notes": [笔记id…], "checked_at", "checked_total", "partial"}}}
目录（catalog）给每篇加 `albums`：它所在专辑的名字列表；search / browse / lwa 的 album 过滤按它。

同步（`albums sync`，夜跑一步，碰号）：
  1. 专辑列表：读取服务 GET /api/v1/boards（进一次收藏页签——和读收藏共用 10 分钟限频；自律：距上次读收藏 / 读专辑列表
     不到 LIST_GAP_MIN 分钟就不读，用上次的列表）。一天最多读一次（LIST_EVERY_H）。
  2. 挑要看的专辑：没看过的 → 篇数变了的 → 上次没读全的 → 最久没看的（超过 RECHECK_DAYS 天），每次最多 --max 个；
     一个一个开（GET /api/v1/boards/notes），之间歇 LWA_FETCH_REST（默认 60–180 秒），和补抓笔记一样慢。
     1028：`--board 名字或id`（可多个）= 只看她点名的专辑，不按上面的顺序挑；本地列表里都认得就不读专辑列表。
     每个专辑报一下「还没进库的几篇」（只报不抓：抓帖仍走收藏同步，那边有每日额度和熔断）。
  撞风控 / 掉登录 → 停，退出 5；号被占 → 退出 6。读到的随读随存，中途停下也不丢。
"""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from ... import storage
from . import accounts

LIST_GAP_MIN = 30
LIST_EVERY_H = 20
RECHECK_DAYS = 7
EXIT_OK, EXIT_ERROR, EXIT_NEEDS_HUMAN, EXIT_BUSY = 0, 1, 5, 6


def path():
    return storage.archive_root() / "albums.json"


def load() -> dict[str, Any]:
    try:
        data = storage.read_json(path())
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("boards"), dict):
        data = {"schema": 1, "boards": {}}
    return data


def save(data: dict[str, Any]) -> None:
    storage.write_json(path(), data)
    from ...catalog import mark_dirty  # 1023：专辑进目录（ARCH-AUDIT 第 1 批）
    mark_dirty("专辑")


def _now() -> datetime:
    return datetime.now().astimezone()


def _parse(ts: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def note_albums(data: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """笔记 id（不带 xhs-）→ 它所在专辑的名字（按专辑名排）。"""
    data = data if data is not None else load()
    out: dict[str, list[str]] = {}
    for b in sorted((data.get("boards") or {}).values(), key=lambda b: str(b.get("name") or "")):
        name = str(b.get("name") or "").strip()
        if not name:
            continue
        for nid in b.get("notes") or []:
            names = out.setdefault(str(nid), [])
            if name not in names:
                names.append(name)
    return out


# ---------------------------------------------------------------- 列表

def merge_list(data: dict[str, Any], result: dict[str, Any], now: datetime) -> dict[str, int]:
    """读取服务的列表并进本地：新的加上、名字 / 篇数 / 私密照新的改；列表读全了才删掉已经不在的专辑。"""
    boards = data.setdefault("boards", {})
    seen, added = set(), 0
    for b in result.get("boards") or []:
        bid = str(b.get("id") or "")
        if not bid:
            continue
        seen.add(bid)
        row = boards.get(bid)
        if row is None:
            row = boards[bid] = {"notes": []}
            added += 1
        row.update(name=str(b.get("name") or ""), total=int(b.get("total") or 0), privacy=int(b.get("privacy") or 0),
                   desc=str(b.get("desc") or ""))
    removed = 0
    if seen and not result.get("partial"):
        for bid in [k for k in boards if k not in seen]:
            del boards[bid]
            removed += 1
    data.update(listed_at=now.isoformat(timespec="seconds"), expected=int(result.get("expected") or 0),
                list_partial=bool(result.get("partial")))
    return {"listed": len(seen), "added": added, "removed": removed}


def list_due(data: dict[str, Any], now: datetime) -> tuple[bool, str]:
    """这次要不要读专辑列表：(要不要, 为什么不)。"""
    last = _parse(data.get("listed_at"))
    if last and now - last < timedelta(hours=LIST_EVERY_H) and not data.get("list_partial"):
        return False, "今天读过专辑列表了"
    try:
        from ... import actionlog
        for row in reversed(actionlog.read(limit=200)):
            if row.get("action") in ("favorites", "boards"):
                at = _parse(row.get("ts"))
                if at and now - at < timedelta(minutes=LIST_GAP_MIN):
                    return False, f"{LIST_GAP_MIN} 分钟内刚进过收藏页签，这次用上次的专辑列表"
                break
    except Exception:  # noqa: BLE001 - 日志读不到就按「没读过」
        pass
    return True, ""


# ---------------------------------------------------------------- 挑专辑

def due_boards(data: dict[str, Any], now: datetime, limit: int) -> list[tuple[str, str]]:
    """[(专辑 id, 为什么要看)]，最该看的在前。空专辑不看。"""
    rows = []
    for bid, b in (data.get("boards") or {}).items():
        if int(b.get("total") or 0) <= 0:
            continue
        checked = _parse(b.get("checked_at"))
        if checked is None:
            rows.append((0, "", bid, "没看过"))
        elif int(b.get("checked_total") or -1) != int(b.get("total") or 0):
            rows.append((1, b.get("checked_at"), bid, "篇数变了"))
        elif b.get("partial"):
            rows.append((2, b.get("checked_at"), bid, "上次没读全"))
        elif now - checked > timedelta(days=RECHECK_DAYS):
            rows.append((3, b.get("checked_at"), bid, f"超过 {RECHECK_DAYS} 天没看"))
    rows.sort(key=lambda r: (r[0], str(r[1])))
    return [(bid, why) for _, _, bid, why in rows[:max(limit, 0)]]


def pick_boards(data: dict[str, Any], wanted: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """她点名的专辑 → ([(专辑 id, "点名")], [认不出的])。按 id → 整名 → 包含（和 album 过滤同一口径）；包含撞上多个算认不出。"""
    boards = data.get("boards") or {}
    picked: list[tuple[str, str]] = []
    unknown: list[str] = []
    for w in wanted:
        w = str(w or "").strip()
        if not w:
            continue
        if w in boards:
            hits = [w]
        else:
            hits = [bid for bid, b in boards.items() if str(b.get("name") or "").strip() == w]
            if not hits:
                hits = [bid for bid, b in boards.items() if w in str(b.get("name") or "")]
        if len(hits) != 1:
            unknown.append(w)
        elif (hits[0], "点名") not in picked:
            picked.append((hits[0], "点名"))
    return picked, unknown


def _library_ids() -> set[str]:
    from . import fav_counts
    return fav_counts.library_ids()


def merge_notes(data: dict[str, Any], bid: str, result: dict[str, Any], now: datetime) -> int:
    row = data.setdefault("boards", {}).setdefault(bid, {"notes": []})
    board = result.get("board") or {}
    if board.get("name"):
        row["name"] = str(board["name"])
    if board.get("total"):
        row["total"] = int(board["total"])
    ids = []
    for n in result.get("notes") or []:
        nid = str(n.get("note_id") or "")
        if nid and nid not in ids:
            ids.append(nid)
    row.update(notes=ids, checked_at=now.isoformat(timespec="seconds"), checked_total=int(row.get("total") or 0),
               partial=bool(result.get("partial")))
    return len(ids)


# ---------------------------------------------------------------- 同步

def _rest() -> float:
    lo, hi = accounts._gap_range("LWA_FETCH_REST", "60,180")
    return random.uniform(lo, hi)


def sync(*, max_boards: int = 6, budget_min: float = 25, list_boards: bool = True, verbose: bool = True,
         boards: list[str] | None = None, sleep=time.sleep, clock=time.monotonic) -> tuple[int, dict[str, Any]]:
    """返回 (退出码, 摘要)。随读随存。boards = 她点名的专辑（名字或 id），给了就只看这些。"""
    def say(msg: str) -> None:
        if verbose:
            print(msg, file=sys.stderr)

    data = load()
    now = _now()
    out: dict[str, Any] = {"listed": None, "boards": [], "stopped": ""}
    end = clock() + budget_min * 60
    if boards:
        _, unknown = pick_boards(data, boards)
        list_boards = list_boards and bool(unknown)   # 点名的本地都认得：不必进收藏页签读列表
    library: set[str] | None = None
    try:
        with accounts.account_session("albums", wait_s=60):
            accounts.check_risk_hold()
            if list_boards:
                due, why = list_due(data, now)
                if due:
                    accounts.pace("读专辑列表")
                    try:
                        res = accounts.api("GET", "/api/v1/boards", timeout=360)
                    except accounts.ReaderError as exc:
                        if exc.code != "RATE_LIMITED":
                            raise
                        res, why = None, "读取服务说收藏刚读过（限频），这次用上次的专辑列表"
                    if res is not None:
                        out["listed"] = merge_list(data, res, _now())
                        save(data)
                        say(f"[albums] 专辑列表：{out['listed']}（页签写 {data.get('expected')} 个）")
                if why:
                    say(f"[albums] {why}")
            if boards:
                todo, unknown = pick_boards(data, boards)
                if unknown:
                    out["unknown"] = unknown
                    say(f"[albums] 认不出这些专辑（名字对不上或撞了多个）：{'、'.join(unknown)}")
            else:
                todo = due_boards(data, now, max_boards)
            for i, (bid, why) in enumerate(todo):
                if clock() > end:
                    out["stopped"] = "budget"
                    break
                if i:
                    wait = _rest()
                    if clock() + wait > end:
                        out["stopped"] = "budget"
                        break
                    say(f"[albums] 歇 {wait:.0f} 秒再开下一个专辑")
                    sleep(wait)
                accounts.pace("开专辑")
                name = (data["boards"].get(bid) or {}).get("name") or bid
                res = accounts.api("GET", f"/api/v1/boards/notes?board_id={bid}", timeout=540)
                n = merge_notes(data, bid, res, _now())
                save(data)
                if library is None:
                    library = _library_ids()
                missing = [nid for nid in data["boards"][bid]["notes"] if nid not in library]
                row = {"id": bid, "name": name, "why": why, "notes": n, "partial": bool(res.get("partial")),
                       "missing": len(missing)}
                if boards:
                    row["missing_ids"] = missing
                out["boards"].append(row)
                say(f"[albums] 「{name}」（{why}）：{n} 篇" + ("，没读全" if res.get("partial") else "")
                    + (f"，{len(missing)} 篇还没进库" if missing else ""))
    except accounts.AccountBusyError as exc:
        out["stopped"] = f"号被占着：{exc}"
        return EXIT_BUSY, out
    except accounts.ReaderError as exc:
        out["stopped"] = f"{exc.code}: {exc}"
        if exc.code in accounts.NEEDS_HUMAN_CODES:
            return EXIT_NEEDS_HUMAN, out
        if exc.code == accounts.RATE_LIMIT_CODE:
            return EXIT_OK, out   # 限频冷却：读取服务自己会冷却、自探，不另报错；已读到的已存
        return EXIT_ERROR, out
    return EXIT_OK, out


def run(args) -> int:
    if args.action == "list":
        data = load()
        boards = sorted((data.get("boards") or {}).values(), key=lambda b: -int(b.get("total") or 0))
        if args.json:
            print(json.dumps({"listed_at": data.get("listed_at"), "expected": data.get("expected"),
                              "albums": [{k: b.get(k) for k in ("name", "total", "privacy", "checked_at", "partial")}
                                         | {"in_library": len(b.get("notes") or [])} for b in boards]}, ensure_ascii=False))
            return 0
        if not boards:
            print("还没同步过专辑（albums sync 还没跑过）")
            return 0
        for b in boards:
            seen = "没看过" if not b.get("checked_at") else f"读到 {len(b.get('notes') or [])} 篇"
            print(f"{b.get('name')}｜{b.get('total')} 篇｜{seen}" + ("｜私密" if b.get("privacy") else ""))
        print(f"共 {len(boards)} 个专辑（列表读于 {str(data.get('listed_at') or '')[:16]}）")
        return 0
    code, out = sync(max_boards=args.max, budget_min=args.budget_min, list_boards=not args.no_list,
                     boards=getattr(args, "board", None))
    print(json.dumps(out, ensure_ascii=False))
    return code
