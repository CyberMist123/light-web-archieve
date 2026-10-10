"""评论补齐（1009 Owner）：设置里「评论楼层」选 N = 前 N 楼的评论、每楼全部楼中楼都要抓全。

她的规则（10-09 晚）：
- 楼数 = 至少抓到这么多。调小不删已抓的（续读一律并集合并，删掉的评论也留着）；调大 = 旧笔记自动排进后台续读，补到新楼数。
- 同步读不完的自动续读直到补齐，不靠她手点；缺口 > 0 的每晚都续；连着几次补不上才进问题面板，照实说原因。
- 碰号照旧：读取服务的熔断 / 开页间隔 / 账号锁一样不少。撞验证就停，等她过完验证自动接着跑；夜跑在跑时让路。

缺口按**存下来的评论**现算（不靠读取组件当时报的 comment_load）：前 N 楼里「原站显示的回复数 > 存下的回复数」就是缺口。
10-08 以前入库的笔记没有 comment_load，以前的续读只认 comment_load 里的缺口，这批（10-09 实查 195 篇、5863 条）永远排不上——这就是漏的根因。

两种续读：
- expand：只展开前 N 楼里有缺口的那几楼（读取组件 expand_floors），其它楼不点；
- floors：存下的楼不到 N、原帖可能还有 → 按 N 楼重读一次（逐楼展开），再和旧的并集合并。

每篇的续读进度记在对象级 `derived/comments-fill.json`（可变状态；RAW 版本照旧不可变）。
后台补跑 = `comments --fill-pending --until-done`（单实例，状态写 `_archive/comments-fill-status.json`，插件状态栏读它）。
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import storage

FLOOR_MIN = 10
FLOOR_ALL = 2000            # 「全部」= 读取组件一次最多列这么多楼
FILL_BUDGET_S = 480         # 续读一次给读取组件的评论预算（秒）；请求超时比它多 90 秒。插件「立即同步」等号最多 10 分钟，一篇得在这之内放手
FILL_GAP_MIN = 45           # 同一篇两次开页至少隔这么久（0926 实测：同一篇 20 分钟开 5 次会被软限流，评论返回空）
NO_PROGRESS_LIMIT = 3       # 连着这么多次续读都没多拿到 → 不再自动续，进问题面板（照实说原因）
SETTLED_REASONS = ("count_mismatch",)   # 读取组件说「展开到底了，原站显示的数比能看到的多（删除 / 折叠）」：读多少次都一样，不算缺口
STATE_NAME = "comments-fill.json"
STATUS_NAME = "comments-fill-status.json"
LOCK_NAME = "comments-fill"
STEP = "comments.fill"
CODE_INCOMPLETE = "PERMANENT.COMMENTS_INCOMPLETE"
NIGHTLY_LEAD_MIN = 20       # 夜跑开始前这么多分钟就让路（号让给夜跑）
TASK_CACHE_S = 300
WAIT_HUMAN_S = 180          # 号要人处理（验证 / 掉登录）时多久看一眼（只读内存状态，不开页）
WAIT_BUSY_S = 60
HEARTBEAT_S = 60
MAX_WAIT_S = 12 * 3600      # 号要人处理时最多等这么久（只看内存状态）；再久就先退出，下次同步 / 夜跑 / 打开 Obsidian 再拉起
CATALOG_EVERY = 25          # 每补齐这么多篇重建一次目录（卡片上的评论数跟上）

# 缺口原因 → 人话（可见页 / 状态 / 问题面板）
REASON_CN = {
    "old_reader": "以前只存了每楼前几条回复",
    "not_expanded": "这楼当时没展开",
    "gone": "这楼在原帖里已经找不到了（删了或被折叠）",
}


# --------------------------------------------------------------------------
# 楼数设置
# --------------------------------------------------------------------------


def floor_target(value: Any = None) -> int:
    """设置里的「评论楼层」→ 要补齐的楼数：10–50；「全部」= FLOOR_ALL。读不到设置按 10。"""
    if value is None:
        try:
            from .ai_config import sync_options
            value = sync_options().get("commentFloors", FLOOR_MIN)
        except Exception:  # noqa: BLE001 - 设置坏了也照常补（按默认 10 楼）
            value = FLOOR_MIN
    if value == "all":
        return FLOOR_ALL
    try:
        return max(FLOOR_MIN, min(int(value), 50))
    except (TypeError, ValueError):
        return FLOOR_MIN


def floors_label(floors: int) -> str:
    return "全部楼层" if floors >= FLOOR_ALL else f"前 {floors} 楼"


# --------------------------------------------------------------------------
# 缺口模型（纯函数）
# --------------------------------------------------------------------------


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def reason_text(reason: str) -> str:
    from .adapters import xiaohongshu as xhs
    return REASON_CN.get(reason) or xhs.REPLY_GAP_CN.get(reason) or "没读全"


def may_have_more_floors(source: dict[str, Any]) -> bool:
    """原帖还可能有没存下来的一级评论（楼）吗：读取组件 / MCP 明说读到底了、或评论总数对得上，就没有。"""
    cap = source.get("capture") or {}
    cl = cap.get("comment_load") or {}
    if cl.get("has_more") is False or cap.get("comments_complete") is True:
        return False
    comments = source.get("comments") or []
    cc = ((source.get("note") or {}).get("engagement") or {}).get("comment_count")
    declared = len(comments) + sum(_int(c.get("sub_comment_count")) for c in comments)
    if isinstance(cc, int) and cc <= declared:
        return False
    return True


def scope(source: dict[str, Any], floors: int, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """前 floors 楼的缺口：gaps（要续读的楼）、settled（读多少次都一样的：原站多显示 / 楼已删）、missing（gaps 合计）、
    more_floors（存下的楼不到 floors、原帖可能还有）。"""
    state = state or {}
    comments = source.get("comments") or []
    cl = (source.get("capture") or {}).get("comment_load") or {}
    reasons = {str(g.get("comment_id")): str(g.get("reason") or "") for g in cl.get("gaps") or [] if g.get("comment_id")}
    gone = set(str(x) for x in state.get("gone_floors") or [])
    gaps, settled = [], []
    for idx, c in enumerate(comments[:floors], start=1):
        shown, have = _int(c.get("sub_comment_count")), len(c.get("sub_comments") or [])
        if shown <= have:
            continue
        cid = str(c.get("comment_id") or "")
        reason = "gone" if cid in gone else (reasons.get(cid) or ("old_reader" if not cl else "not_expanded"))
        g = {"comment_id": cid, "floor": idx, "shown": shown, "loaded": have, "missing": shown - have, "reason": reason}
        (settled if reason in SETTLED_REASONS or reason == "gone" or not cid else gaps).append(g)
    more = (len(comments) < floors and may_have_more_floors(source)
            and _int(state.get("floors_done")) < floors)
    return {"floors": floors, "stored": len(comments), "gaps": gaps, "settled": settled,
            "missing": sum(g["missing"] for g in gaps), "more_floors": bool(more)}


def plan_fill(sc: dict[str, Any]) -> tuple[str | None, list[str]]:
    """这一篇这次怎么续：('floors', []) 按楼数重读 / ('expand', [comment_id…]) 只展开缺口楼 / (None, []) 不用续。"""
    if sc["more_floors"]:
        return "floors", []
    if sc["gaps"]:
        return "expand", [g["comment_id"] for g in sorted(sc["gaps"], key=lambda g: -g["missing"])]
    return None, []


# --------------------------------------------------------------------------
# 每篇的续读状态（derived/comments-fill.json）
# --------------------------------------------------------------------------


def state_path(source_key: str, source_id: str) -> Path:
    return storage.derived_dir(source_key, source_id) / STATE_NAME


def load_state(source_key: str, source_id: str) -> dict[str, Any]:
    try:
        data = storage.read_json(state_path(source_key, source_id))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(source_key: str, source_id: str, state: dict[str, Any]) -> None:
    path = state_path(source_key, source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(path, state)


def _parse(ts: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.astimezone()


def _now() -> datetime:
    return datetime.now().astimezone()


def last_open(source: dict[str, Any], state: dict[str, Any]) -> datetime | None:
    """上次开这一篇的时刻：续读记录和这一版抓取时刻取较晚的（老 comment_load 里的 fill_last_at 也算）。"""
    cap = source.get("capture") or {}
    stamps = [_parse(state.get("last_at")), _parse(cap.get("captured_at")),
              _parse((cap.get("comment_load") or {}).get("fill_last_at"))]
    sid = source.get("source_id")
    if sid:
        # 1011：她在验证窗口里刚开过这篇——同一篇照旧隔 45 分钟再开（别让补抓紧跟着验证窗口）
        from . import restricted
        stamps.append(_parse(restricted.load(sid).get("verified_at")))
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def is_stuck(state: dict[str, Any], floors: int) -> bool:
    """连着几次补不上、已进问题面板：同一个楼数下不再自动续（楼数调大了照样再试）。"""
    return bool(state.get("stuck")) and _int(state.get("stuck_floors") or floors) >= floors


# --------------------------------------------------------------------------
# 全库扫描
# --------------------------------------------------------------------------


def _objects() -> list[tuple[str, str]]:
    from . import index as index_mod
    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT source, source_id FROM objects ORDER BY item_id").fetchall()
    finally:
        conn.close()
    return [(r["source"], r["source_id"]) for r in rows]


def current_source(source_key: str, source_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    meta = storage.read_json(storage.object_dir(source_key, source_id) / "meta.json")
    source = storage.read_json(storage.raw_dir(source_key, source_id, meta["current_version"]) / "source.json")
    return meta, source


def survey(floors: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    """全库还有哪些篇要续：ready（现在就能续，缺得少的在前）/ cooling（同一篇 45 分钟内刚开过）/ stuck（进了问题面板）/
    restricted（1011：网页版要验证才能看，等她点「打开验证」，不再自动开页）。"""
    from . import restricted as restricted_mod
    floors = floors or floor_target()
    now = now or _now()
    ready, cooling, stuck, restricted = [], [], [], []
    missing = 0
    for source_key, source_id in _objects():
        if source_key != "xiaohongshu":
            continue
        try:
            meta, source = current_source(source_key, source_id)
        except (OSError, ValueError, KeyError):
            continue
        state = load_state(source_key, source_id)
        sc = scope(source, floors, state)
        mode, targets = plan_fill(sc)
        if mode is None:
            continue
        entry = {"source": source_key, "source_id": source_id, "item_id": f"xhs-{source_id}",
                 "title": (source.get("note") or {}).get("title") or meta.get("title") or "",
                 "mode": mode, "targets": targets, "missing": sc["missing"], "more_floors": sc["more_floors"],
                 "attempts": _int(state.get("attempts"))}
        if is_stuck(state, floors):
            stuck.append(entry)
            continue
        if restricted_mod.is_restricted(source_id):
            restricted.append(entry)
            continue
        missing += sc["missing"]
        last = last_open(source, state)
        if last and now - last < timedelta(minutes=FILL_GAP_MIN):
            entry["eligible_at"] = (last + timedelta(minutes=FILL_GAP_MIN)).isoformat(timespec="seconds")
            cooling.append(entry)
        else:
            ready.append(entry)
    # 缺得少的先补（大多数笔记只缺几条，补完一篇算一篇）；同样多的按续过的次数少的在前
    ready.sort(key=lambda e: (e["attempts"] > 0, e["missing"] if e["missing"] else 1_000_000, e["item_id"]))
    cooling.sort(key=lambda e: e["eligible_at"])
    return {"floors": floors, "ready": ready, "cooling": cooling, "stuck": stuck, "restricted": restricted,
            "missing": missing, "pending": len(ready) + len(cooling)}


# --------------------------------------------------------------------------
# 续读一篇
# --------------------------------------------------------------------------


def _note_url(source_id: str, source: dict[str, Any], token: str | None = None) -> str:
    if token is None:
        from . import restricted
        # 1011：用标题搜到 / 验证窗口里拿到的新口令优先（网页版限制过的笔记，旧口令多半就是打不开的那个）
        token = restricted.best_token(source_id, (source.get("note") or {}).get("xsec_token") or "")
    return f"https://www.xiaohongshu.com/explore/{source_id}?xsec_token={token}"


def fill_one(item_id: str, *, floors: int | None = None, verbose: bool = False, budget_s: int = FILL_BUDGET_S,
             manual: bool = False) -> dict[str, Any]:
    """续读一篇：按 plan_fill 选 expand / floors，抓完和旧的并集合并（新 RAW 版本只在真多拿到东西时才写），
    记续读状态，补齐了消问题、连着补不上进问题面板，最后重渲染可见页。碰号：调用方要拿着账号锁。

    manual=True（她点的「再试一次 / 现在抓全部评论」）：不看 45 分钟间隔、不看「已放弃」，照跑一次。"""
    from . import catch as catch_mod, ingest as ingest_mod, index as index_mod, problems
    floors = floors or floor_target()
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, item_id)
    finally:
        conn.close()
    if not row:
        raise FileNotFoundError(f"没有归档过: {item_id}")
    source_key, source_id = row["source"], row["source_id"]
    meta, source = current_source(source_key, source_id)
    state = load_state(source_key, source_id)
    sc = scope(source, floors, state)
    mode, targets = plan_fill(sc)
    title = (source.get("note") or {}).get("title") or meta.get("title") or ""
    base = {"item_id": item_id, "note_id": source_id, "title": title, "floors": floors, "mode": mode,
            "missing_before": sc["missing"], "version": meta["current_version"]}
    if mode is None:
        if state.get("stuck"):
            _settle(source_key, source_id, state, item_id, problems)
        return {**base, "filled": False, "missing_after": 0, "reason": "没有缺口", "refreshed_unchanged": True}
    if not manual and is_stuck(state, floors):
        return {**base, "filled": False, "missing_after": sc["missing"], "reason": "连着几次补不上，已记进问题面板"}

    before_missing, before_floors = sc["missing"], sc["stored"]
    from . import restricted
    from .adapters import xiaohongshu as xhs
    if not manual and restricted.is_restricted(source_id):
        # 1011：网页版要验证才能看的，等她点「打开验证」，后台不再自动开页
        return {**base, "filled": False, "missing_after": sc["missing"], "restricted": True, "reason": restricted.TEXT}

    def attempt(url: str) -> dict[str, Any]:
        return ingest_mod.ingest_url(url, refresh=True, comment_floors=floors, verbose=verbose,
                                     expand_floors=targets if mode == "expand" else None, fill=True,
                                     fill_budget_s=budget_s)

    old_token = (source.get("note") or {}).get("xsec_token") or ""
    try:
        summary = attempt(_note_url(source_id, source))
    except xhs.NoteRestrictedError as exc:
        # 1011：只是这一篇（网页版要验证）：今天没搜过就用标题搜一次新口令、歇一会儿再开一次；还不行就记一条、跳过这篇。
        # 不算「没进展」（这不是评论读不全），也不报 COMMENTS_INCOMPLETE
        opened, summary = restricted.retry_with_fresh_token(
            source_id, title=title, old_token=restricted.best_token(source_id, old_token),
            attempt=lambda tok: attempt(_note_url(source_id, source, tok)), restricted_exc=(xhs.NoteRestrictedError,),
            item_id=item_id, via="comments.fill", detail=str(exc)[:200])
        if not opened:
            try:
                catch_mod._ensure_rendered(source_key, source_id, force=True, extract=False)
            except Exception as rexc:  # noqa: BLE001 - 笔记页那一行下次渲染会跟上
                print(f"[comments] 重渲染没成：{type(rexc).__name__}: {rexc}", file=sys.stderr)
            return {**base, "filled": False, "missing_after": sc["missing"], "restricted": True, "reason": restricted.TEXT}
    else:
        restricted.clear(source_id, item_id=item_id, why="评论续读打开了这篇")
    meta2, source2 = current_source(source_key, source_id)
    now = _now().isoformat(timespec="seconds")
    cl2 = (source2.get("capture") or {}).get("comment_load") or {}
    if mode == "expand":
        not_found = set(str(x) for x in (summary.get("floors_not_found") or []))
        if not_found:
            state["gone_floors"] = sorted(set(str(x) for x in state.get("gone_floors") or []) | not_found)
    sc2 = scope(source2, floors, state)
    progressed = sc2["missing"] < before_missing or sc2["stored"] > before_floors or bool(summary.get("floors_not_found"))
    if mode == "floors" and sc2["stored"] <= before_floors:
        state["floors_done"] = floors  # 按楼数重读过一次、楼没变多：原帖就这么多楼，这个楼数下不再重读
        progressed = progressed or sc2["missing"] < before_missing
    state["attempts"] = _int(state.get("attempts")) + 1
    state["last_at"] = now
    state["last_mode"] = mode
    state["last_missing"] = sc2["missing"]
    state["no_progress"] = 0 if progressed else _int(state.get("no_progress")) + 1
    state.pop("last_error", None)
    hist = list(state.get("history") or [])[-7:]
    hist.append({"at": now, "mode": mode, "before": before_missing, "after": sc2["missing"],
                 "floors_before": before_floors, "floors_after": sc2["stored"],
                 "stop": str(cl2.get("stop_reason") or "")})
    state["history"] = hist
    mode2, _ = plan_fill(sc2)
    if mode2 is None:
        _settle(source_key, source_id, state, item_id, problems)
    elif state["no_progress"] >= NO_PROGRESS_LIMIT:
        main = max(sc2["gaps"], key=lambda g: g["missing"])["reason"] if sc2["gaps"] else str(cl2.get("stop_reason") or "")
        why = reason_text(main)
        state.update(stuck=True, stuck_floors=floors, stuck_at=now, stuck_reason=why)
        save_state(source_key, source_id, state)
        problems.report(STEP, CODE_INCOMPLETE,
                        f"{floors_label(floors)}的楼中楼还缺 {sc2['missing']} 条：{why}；连着 {state['no_progress']} 次续读都没多拿到，先不自动读了",
                        item_id=item_id, title=title, action="gave_up")
    else:
        save_state(source_key, source_id, state)
    try:
        catch_mod._ensure_rendered(source_key, source_id, force=True, extract=False)
    except Exception as exc:  # noqa: BLE001 - 渲染出意外不影响已经落盘的评论
        print(f"[comments] 重渲染没成（评论已存好）：{type(exc).__name__}: {exc}", file=sys.stderr)
    return {**base, "filled": not summary.get("refreshed_unchanged"), "missing_after": sc2["missing"],
            "more_floors": sc2["more_floors"], "done": mode2 is None, "stuck": bool(state.get("stuck")),
            "version": meta2["current_version"], "comments": summary.get("comments"),
            "sub_comments": summary.get("sub_comments"), "refreshed_unchanged": summary.get("refreshed_unchanged")}


def _settle(source_key: str, source_id: str, state: dict[str, Any], item_id: str, problems) -> None:
    """补齐了：清掉「补不上」标记，问题面板那条标已解决。"""
    state["no_progress"] = 0
    state["done_at"] = _now().isoformat(timespec="seconds")
    for k in ("stuck", "stuck_floors", "stuck_at", "stuck_reason"):
        state.pop(k, None)
    save_state(source_key, source_id, state)
    problems.resolve(STEP, item_id)


def note_failure(item_id: str, error: str) -> None:
    """这一篇这次没读成（不是号的事，比如这篇打不开）：算一次没进展，记一句原因。"""
    from . import index as index_mod, problems
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, item_id)
    finally:
        conn.close()
    if not row:
        return
    state = load_state(row["source"], row["source_id"])
    now = _now().isoformat(timespec="seconds")
    state["attempts"] = _int(state.get("attempts")) + 1
    state["last_at"] = now
    state["no_progress"] = _int(state.get("no_progress")) + 1
    state["last_error"] = str(error)[:200]
    if state["no_progress"] >= NO_PROGRESS_LIMIT and not state.get("stuck"):
        floors = floor_target()
        state.update(stuck=True, stuck_floors=floors, stuck_at=now, stuck_reason=f"这篇读不出来：{error}"[:200])
        problems.report(STEP, CODE_INCOMPLETE, f"评论续读连着 {state['no_progress']} 次没成：{error}"[:300],
                        item_id=item_id, action="gave_up")
    save_state(row["source"], row["source_id"], state)


def view_for_render(source: dict[str, Any], state: dict[str, Any] | None, floors: int | None = None) -> dict[str, Any]:
    """可见页顶上那一行要的东西：楼数、缺口、原因、是不是在后台补 / 已放弃。"""
    floors = floors or floor_target()
    state = state or {}
    sc = scope(source, floors, state)
    stuck = is_stuck(state, floors)
    main = max(sc["gaps"], key=lambda g: g["missing"])["reason"] if sc["gaps"] else ""
    restricted_view = None
    if source.get("source_id"):
        from . import restricted
        restricted_view = restricted.view(source["source_id"])   # 1011：网页版要验证才能看（笔记页给「打开验证」）
    return {**sc, "stuck": stuck, "attempts": _int(state.get("attempts")), "why": reason_text(main) if main else "",
            "gap_reasons": {g["comment_id"]: g["reason"] for g in sc["gaps"] + sc["settled"]},
            "restricted": restricted_view}


# --------------------------------------------------------------------------
# 后台补跑：状态文件
# --------------------------------------------------------------------------


def status_path() -> Path:
    return storage.archive_root() / STATUS_NAME


def read_status() -> dict[str, Any]:
    """状态文件 + 进程还在不在（只在 Python 判：running/waiting/paused 但 pid 没了 → stopped）。"""
    try:
        st = storage.read_json(status_path())
    except (OSError, ValueError):
        return {}
    if not isinstance(st, dict):
        return {}
    if st.get("state") in ("running", "waiting", "paused") and st.get("pid"):
        if storage.pid_state(st.get("pid")) == "dead":
            st = {**st, "state": "stopped", "message": "后台补评论中途停了（进程不在了），下次同步 / 夜跑接着补"}
    return st


class Status:
    """后台补跑的状态文件：每次变化、等待时每分钟写一次（插件状态栏按 updated_at 判新旧）。"""

    def __init__(self, floors: int, *, background: bool):
        self.data: dict[str, Any] = {"state": "running", "pid": os.getpid(), "background": background,
                                     "started_at": _now().isoformat(timespec="seconds"), "floors": floors,
                                     "total": 0, "done": 0, "left": 0, "missing": 0, "stuck": 0,
                                     "current": None, "wait_code": "", "message": "正在补评论…"}
        self.done_ids: set[str] = set()
        self.seen_ids: set[str] = set()

    def update(self, **fields: Any) -> None:
        self.data.update(fields)
        self.data["updated_at"] = _now().isoformat(timespec="seconds")
        try:
            storage.write_json(status_path(), self.data)
        except OSError as exc:
            print(f"[comments] 状态没写上：{exc}", file=sys.stderr)

    def counts(self, sv: dict[str, Any]) -> None:
        ids = {e["item_id"] for e in sv["ready"] + sv["cooling"]}
        self.seen_ids |= ids
        self.done_ids -= ids
        self.data.update(total=len(self.seen_ids), done=len(self.done_ids), left=len(ids), missing=sv["missing"],
                         stuck=len(sv["stuck"]), restricted=len(sv.get("restricted") or []), floors=sv["floors"])

    def text(self, head: str = "") -> str:
        d = self.data
        bits = [head or "补评论"]
        if d.get("total"):
            bits.append(f"已补齐 {d['done']}/{d['total']} 篇")
        if d.get("missing"):
            bits.append(f"还缺 {d['missing']} 条回复")
        return " · ".join(bits)


# --------------------------------------------------------------------------
# 让路：夜跑 / 别的任务 / 号要人处理
# --------------------------------------------------------------------------

_TASK_CACHE: dict[str, Any] = {"at": 0.0, "rows": []}
_TASK_PS = (
    "$o=@();foreach($n in @({names})){{$t=Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue;"
    "if($t){{$i=Get-ScheduledTaskInfo -TaskName $n -ErrorAction SilentlyContinue;"
    "$o+=[pscustomobject]@{{name=$n;state=[string]$t.State;"
    "next=$(if($i -and $i.NextRunTime){{$i.NextRunTime.ToString('s')}}else{{''}})}}}}}};"
    "ConvertTo-Json -Compress -InputObject @($o)"
)


def _nightly_tasks() -> list[str]:
    from . import sync_schedule
    names = [sync_schedule.TASK, sync_schedule.nightly_task_name()]
    return list(dict.fromkeys(n for n in names if n))


def task_rows(force: bool = False) -> list[dict[str, Any]]:
    """夜跑计划任务现在的状态和下次运行时间（Windows；别的系统返回空）。5 分钟缓存。"""
    if os.name != "nt":
        return []
    if not force and time.monotonic() - _TASK_CACHE["at"] < TASK_CACHE_S:
        return _TASK_CACHE["rows"]
    names = ",".join("'" + n.replace("'", "''") + "'" for n in _nightly_tasks())
    rows: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _TASK_PS.format(names=names)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads((proc.stdout or "").strip().splitlines()[-1]) if (proc.stdout or "").strip() else []
        rows = [r for r in (data if isinstance(data, list) else [data]) if isinstance(r, dict)]
    except Exception as exc:  # noqa: BLE001 - 查不到就当没有夜跑（账号锁照样兜底）
        print(f"[comments] 查不到夜跑计划任务：{type(exc).__name__}: {exc}", file=sys.stderr)
    _TASK_CACHE.update(at=time.monotonic(), rows=rows)
    return rows


def nightly_busy(now: datetime | None = None, rows: list[dict[str, Any]] | None = None) -> str:
    """夜跑在跑 / 快开始了 → 一句原因；否则 ''。"""
    now = now or _now()
    rows = task_rows() if rows is None else rows
    for r in rows:
        if str(r.get("state") or "") == "Running":
            return "夜跑在跑，号让给它，做完接着补"
    for r in rows:
        nxt = _parse(r.get("next")) if r.get("next") else None
        if nxt and timedelta(0) <= nxt - now <= timedelta(minutes=NIGHTLY_LEAD_MIN):
            return f"夜跑 {nxt:%H:%M} 开始，号先让给它，做完接着补"
    return ""


def account_wait_reason() -> tuple[str, str]:
    """号现在能不能用（只问读取服务内存里的状态，不开页）：('', '') 能用；否则 (码, 一句原因)。"""
    from . import accounts
    try:
        session = accounts.ensure_reader()
    except accounts.ReaderError as exc:
        if exc.code == "DEV_COPY_BLOCKED":
            raise
        return exc.code or "DISCONNECTED", f"读取服务没连上（{exc.code}），稍后自动再试"
    hold = accounts.hold_from_session(session)
    if hold:
        code = str(hold.get("code") or "RISK_HOLD")
        what = "掉登录了：在设置 / 问题入口扫码登录" if code == "NOT_LOGGED_IN" else "要安全验证：点问题入口「打开验证」"
        return code, f"小红书{what}，处理好自动接着补（{accounts.hold_text(hold) or '暂停中'}）"
    if isinstance(session, dict):
        if session.get("logged_in") is False:
            return "NOT_LOGGED_IN", "小红书掉登录了：在设置 / 问题入口扫码登录，登好自动接着补"
        if session.get("verifying") or str(session.get("state") or "idle") not in ("idle", ""):
            return "BUSY", "正在扫码 / 验证，等它完了再接着补"
    return "", ""


def spawn_worker() -> dict[str, Any]:
    """拉起后台补跑（脱离调用方，单实例：已经在跑就不再起）。"""
    st = read_status()
    if st.get("state") in ("running", "waiting", "paused"):
        return {"ok": True, "started": False, "already": True, "pid": st.get("pid"), "message": "后台补评论已经在跑"}
    from . import procs
    argv = [sys.executable, "-m", "link_brain", "comments", "--fill-pending", "--until-done"]
    env = dict(os.environ)
    env[storage.ENV_VAULT] = str(storage.vault_root())
    env["PYTHONIOENCODING"] = "utf-8"
    log = storage.link_brain_home() / "comments-fill.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    pid = procs.spawn_detached(argv, cwd=str(Path(__file__).resolve().parent.parent), env=env, log_path=log)
    return {"ok": True, "started": True, "pid": pid, "message": "后台开始补评论"}


# --------------------------------------------------------------------------
# 补跑循环（夜跑一步 / 后台一直跑到补完）
# --------------------------------------------------------------------------


def run(args, *, sleep: Callable[[float], None] = time.sleep) -> int:
    """`comments --fill-pending [--until-done] [--budget-min M] [--limit N] [--then-background]`。

    夜跑这一步（不带 --until-done）：预算内能续的各续一次；号要人处理退出 5、号被占退出 6；没补完、带 --then-background
    就拉起后台补跑接着补（它会等夜跑做完再开始碰号）。
    后台（--until-done）：一直补到全库没有能续的缺口；撞验证 / 掉登录就停下等（只看内存状态，不开页），她处理好自动接着；
    夜跑在跑、或别的任务要用号就让路。单实例：已经有一个在跑就直接退出 0。"""
    from . import accounts
    from .adapters import xiaohongshu as xhs
    from .read import dump_json, outcome
    until_done = bool(getattr(args, "until_done", False))
    budget = float(getattr(args, "budget_min", 0) or 0)
    limit = int(getattr(args, "limit", 0) or 0)
    verbose = bool(getattr(args, "verbose", False))
    deadline = time.monotonic() + budget * 60 if budget > 0 else None
    try:
        lock = storage.file_lock(LOCK_NAME, wait_s=0, owner="comments-fill", stale_s=10 * 60)
        lock.__enter__()
    except storage.LockBusy:
        msg = "后台补评论已经在跑，这次不重复开"
        dump_json(outcome({"candidates": None, "done": [], "failed": [], "already_running": True}, ok=True, message=msg))
        return 0
    floors = floor_target()
    status = Status(floors, background=until_done)
    done: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    deferred = 0
    exit_code = 0
    stop_msg = ""
    since_catalog = 0
    waited_s = 0
    attempts_this_run: dict[str, int] = {}

    def nap(seconds: float, **fields: Any) -> None:
        """等一会儿（每分钟刷一次状态文件的 updated_at，插件据此知道它还活着）。"""
        status.update(**fields)
        left = max(0.0, float(seconds))
        while left > 0:
            step = min(float(HEARTBEAT_S), left)
            sleep(step)
            left -= step
            status.update()

    try:
        while True:
            floors = floor_target()
            sv = survey(floors)
            status.counts(sv)
            ready = sv["ready"]
            if not until_done:
                ready = [e for e in ready if attempts_this_run.get(e["item_id"], 0) == 0]
            if limit and len(done) + len(failed) >= limit:
                deferred = len(ready)
                break
            if not ready:
                if until_done and sv["cooling"]:
                    first = _parse(sv["cooling"][0]["eligible_at"]) or _now()
                    wait = max(30.0, min(900.0, (first - _now()).total_seconds() + 5))
                    nap(wait, state="waiting", current=None, wait_code="COOLING",
                        message=status.text("补评论") + f" · 同一篇隔 {FILL_GAP_MIN} 分钟再开，{first:%H:%M} 接着补")
                    continue
                break
            entry = ready[0]
            if deadline is not None and deadline - time.monotonic() < FILL_BUDGET_S + 150:
                deferred = len(ready)
                break
            if until_done:
                why = nightly_busy()
                if why:
                    nap(300, state="paused", current=None, wait_code="NIGHTLY", message=status.text("补评论暂停") + " · " + why)
                    continue
                if accounts.lock_wanted():
                    nap(20, state="paused", current=None, wait_code="YIELD",
                        message=status.text("补评论暂停") + " · 别的任务要用号，先让它")
                    continue
            code, why = account_wait_reason()
            if code:
                if not until_done or code == "NOT_INSTALLED":
                    stop_msg = why if code != "NOT_INSTALLED" else "没装读取组件，补不了评论（装好后同步时会接着补）"
                    exit_code = 5 if code in accounts.NEEDS_HUMAN_CODES or code in ("RISK_HOLD",) else 0
                    deferred = len(ready)
                    break
                waited_s += WAIT_HUMAN_S if code in accounts.NEEDS_HUMAN_CODES else WAIT_BUSY_S
                if waited_s > MAX_WAIT_S:
                    stop_msg = f"等了 {MAX_WAIT_S // 3600} 小时还没好（{why}），先停；处理好后下次同步 / 夜跑 / 打开 Obsidian 会接着补"
                    deferred = len(ready)
                    break
                nap(WAIT_HUMAN_S if code in accounts.NEEDS_HUMAN_CODES else WAIT_BUSY_S, state="waiting", current=None,
                    wait_code=code, message=status.text("补评论暂停") + " · " + why)
                continue
            waited_s = 0
            item_id = entry["item_id"]
            status.update(state="running", current={"item_id": item_id, "title": entry["title"][:60]}, wait_code="",
                          message=status.text("正在补评论") + f" · {entry['title'][:24]}")
            attempts_this_run[item_id] = attempts_this_run.get(item_id, 0) + 1
            lock_wait = 300.0 if until_done else float(getattr(args, "wait_lock_min", 2) or 2) * 60
            try:
                with accounts.account_session("comments-fill", wait_s=lock_wait, polite=until_done):
                    out = fill_one(item_id, floors=floors, verbose=verbose)
            except accounts.AccountBusyError as exc:
                attempts_this_run[item_id] -= 1
                holder = str((exc.holder or {}).get("owner") or "")
                if not until_done:
                    stop_msg = f"号正被「{holder or '别的任务'}」占着"
                    exit_code = 6
                    deferred = len(ready)
                    break
                nap(WAIT_BUSY_S, state="waiting", current=None, wait_code="ACCOUNT_BUSY",
                    message=status.text("补评论暂停") + f" · 号正被「{holder or '别的任务'}」用着，等它做完")
                continue
            except xhs.NeedsHumanError as exc:
                from . import problems
                service = isinstance(exc, xhs.ServiceDownError)
                problems.report_blocked(STEP, getattr(exc, "code", "") or "", f"补评论停了：{exc}", service=service)
                if not until_done:
                    stop_msg = f"补评论停了：{exc}"
                    exit_code = 0 if service else 5
                    deferred = len(ready)
                    break
                nap(WAIT_BUSY_S if service else WAIT_HUMAN_S, state="waiting", current=None,
                    wait_code=getattr(exc, "code", "") or ("DISCONNECTED" if service else "ACCOUNT_BLOCKED"),
                    message=status.text("补评论暂停") + " · " + ("读取服务没连上，稍后自动再试" if service else
                                                             "小红书要你处理（验证 / 登录），处理好自动接着补"))
                continue
            except (xhs.AdapterError, FileNotFoundError, OSError, ValueError, KeyError) as exc:
                note_failure(item_id, f"{type(exc).__name__}: {exc}")
                failed.append({"item_id": item_id, "error": str(exc)[:200]})
                continue
            done.append({"item_id": item_id, "filled": out.get("filled"), "missing_after": out.get("missing_after"),
                         "done": out.get("done"), "stuck": out.get("stuck"), "restricted": bool(out.get("restricted"))})
            print(f"[comments] {datetime.now():%H:%M:%S} {item_id}《{entry['title'][:30]}》{out.get('mode')}："
                  f"缺 {out.get('missing_before')} → {out.get('missing_after')}"
                  + ("，补齐了" if out.get("done") else "，连着补不上，进问题面板" if out.get("stuck") else
                     "，网页版要验证才能看：记进问题面板，等她点「打开验证」" if out.get("restricted") else "，下次接着补"),
                  file=sys.stderr)
            if out.get("done"):
                status.done_ids.add(item_id)
                status.data["done"] = len(status.done_ids)
                since_catalog += 1
            if since_catalog >= CATALOG_EVERY:
                since_catalog = 0
                _rebuild_catalog()
            # 和同步收藏一样，每篇之后随机歇 60–180 秒（LWA_FETCH_REST）——像人一样看完一篇再点下一篇；歇的时候不攥着号，
            # 等着用号的任务（5 秒一看）先拿到锁
            lo, hi = accounts._gap_range("LWA_FETCH_REST", "60,180")
            nap(max(8.0, random.uniform(lo, hi)) if hi > 0 else 0, state="running", current=None,
                message=status.text("补评论") + " · 歇一会儿再开下一篇")
    except accounts.ReaderError as exc:  # DEV_COPY_BLOCKED：这份代码不许用号
        stop_msg = str(exc)
        exit_code = 5
    finally:
        try:
            sv = survey(floor_target())
            status.counts(sv)
            if since_catalog or any(d.get("filled") for d in done):
                _rebuild_catalog()
            left = sv["pending"]
            if left and not stop_msg and not until_done and getattr(args, "then_background", False):
                spawned = spawn_worker()
                stop_msg = f"还有 {left} 篇没补完，转到后台接着补" if spawned.get("ok") else ""
            final_state = "done" if not left else ("stopped" if stop_msg else "deferred")
            msg = (f"评论都补齐了（{floors_label(sv['floors'])}）" if not left else
                   status.text("补评论") + (f" · {stop_msg}" if stop_msg else " · 剩下的下次接着补"))
            if sv["stuck"]:
                msg += f" · {len(sv['stuck'])} 篇连着补不上（见问题面板）"
            if sv.get("restricted"):
                msg += f" · {len(sv['restricted'])} 篇在网页版要验证才能看（见问题面板，点「打开验证」）"
            status.update(state=final_state, current=None, message=msg, finished_at=_now().isoformat(timespec="seconds"))
        finally:
            lock.__exit__(None, None, None)
    message = status.data.get("message") or ""
    dump_json(outcome({"candidates": status.data.get("total"), "done": done, "failed": failed, "deferred": deferred,
                       "left": status.data.get("left"), "missing": status.data.get("missing")},
                      ok=exit_code in (0,) and not (failed and not done), message=message,
                      code="" if exit_code == 0 else ("NEEDS_HUMAN" if exit_code == 5 else "ACCOUNT_BUSY")))
    if exit_code:
        return exit_code
    return 1 if failed and not done else 0


def _rebuild_catalog() -> None:
    try:
        from . import catalog
        catalog.build()
    except Exception as exc:  # noqa: BLE001 - 目录下次重建会跟上
        print(f"[comments] 目录没重建上：{type(exc).__name__}: {exc}", file=sys.stderr)


def status_payload() -> dict[str, Any]:
    """`comments --fill-status`：插件设置页 / 状态栏用。本地读，不碰号。"""
    from .read import outcome
    sv = survey()
    st = read_status()
    running = st.get("state") in ("running", "waiting", "paused")
    msg = (st.get("message") if running else
           (f"评论都补齐了（{floors_label(sv['floors'])}）" if not sv["pending"] else
            f"{sv['pending']} 篇的评论还没补齐（共缺 {sv['missing']} 条回复）"))
    return outcome({"floors": sv["floors"], "pending": sv["pending"], "ready": len(sv["ready"]),
                    "cooling": len(sv["cooling"]), "stuck": len(sv["stuck"]),
                    "restricted": len(sv.get("restricted") or []), "missing": sv["missing"],
                    "running": running, "status": st}, ok=True, message=msg or "")
