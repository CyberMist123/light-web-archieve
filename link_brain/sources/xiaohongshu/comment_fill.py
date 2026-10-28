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
from ...errtext import errtext

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta

from ... import actionlog
from pathlib import Path
from typing import Any, Callable

from ... import domain, storage
from . import adapter as xhs

FLOOR_MIN = 10
FLOOR_ALL = 100_000         # 「全部」= 不设楼数上限（1017：以前 2000，8636 条评论的帖只读到 2007 楼就当读完了）
FILL_BUDGET_S = 480         # 续读一次给读取组件的评论预算（秒）；请求超时比它多 90 秒。插件「立即同步」等号最多 10 分钟，一篇得在这之内放手
FILL_GAP_MIN = 45           # 同一篇两次开页至少隔这么久（0926 实测：同一篇 20 分钟开 5 次会被软限流，评论返回空）；1015 起设置里可调慢（见 fill_gap_min）
# 1016：连续补评论跑满 WORK_MIN 分钟强制歇 REST_MIN 分钟（10-10 连跑 2.5 小时撞过滑块）
WORK_MIN = int(os.environ.get("LWA_WORK_MIN") or 60)
REST_MIN = int(os.environ.get("LWA_REST_MIN") or 30)
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
STALE_MIN = 40              # 状态心跳这么久没动 = 补跑已经停了（pid 可能被复用）；一篇续读最长约 32 分钟不刷心跳（1028 审查 B2）
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
            from ...ai_config import sync_options
            value = sync_options().get("commentFloors", FLOOR_MIN)
        except Exception:  # noqa: BLE001 - 设置坏了也照常补（按默认 10 楼）
            value = FLOOR_MIN
    if value == "all":
        return FLOOR_ALL
    try:
        return max(FLOOR_MIN, min(int(value), 50))
    except (TypeError, ValueError):
        return FLOOR_MIN


def fill_gap_min() -> int:
    """补评论节奏（1015 设置页「定时同步 → 补评论节奏」）：同一篇两次开页至少隔几分钟，只能比 FILL_GAP_MIN 慢。读不到设置按 FILL_GAP_MIN。"""
    try:
        from ...ai_config import sync_options
        return max(FILL_GAP_MIN, int(sync_options().get("commentFillGap") or FILL_GAP_MIN))
    except Exception:  # noqa: BLE001 - 设置坏了按默认节奏
        return FILL_GAP_MIN


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
    from . import adapter as xhs
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


# 1017：续展一趟只管这么宽的一段楼（读取组件从这段的前一楼接着翻，几秒就到；不然从第 1 楼往下找，8 分钟只到 ~500 楼）
EXPAND_WINDOW = 150


def plan_fill(sc: dict[str, Any]) -> tuple[str | None, list[str]]:
    """这一篇这次怎么续：('floors', []) 按楼数重读 / ('expand', [comment_id…]) 只展开缺口楼 / (None, []) 不用续。
    expand 一趟只取从最前一个缺口楼起 EXPAND_WINDOW 楼内的缺口（expand_window 给出从哪楼接着翻）。"""
    if sc["more_floors"]:
        return "floors", []
    if sc["gaps"]:
        first = min(g["floor"] for g in sc["gaps"])
        window = [g for g in sc["gaps"] if g["floor"] < first + EXPAND_WINDOW]
        return "expand", [g["comment_id"] for g in sorted(window, key=lambda g: -g["missing"])]
    return None, []


def expand_window_resume(source: dict[str, Any], targets: list[str]) -> str | None:
    """续展深处的楼（1017）：从目标里最靠前那楼的前一楼接着翻一级评论（"前一楼 id:楼序"），目标楼在前 FLOORS_RESUME_MIN 楼内就不跳。"""
    want = set(str(t) for t in targets)
    comments = source.get("comments") or []
    idx = next((i for i, c in enumerate(comments) if str(c.get("comment_id") or "") in want), None)
    if idx is None or idx < FLOORS_RESUME_MIN:
        return None
    prev = str(comments[idx - 1].get("comment_id") or "")
    return f"{prev}:{idx}" if prev else None


# --------------------------------------------------------------------------
# 1017 断点续展 + 楼中楼额度
# --------------------------------------------------------------------------
# 网页版每次打开，楼中楼都只带第 1 条；以前每次续读都从头点，一小时 30 次额度（约 300 条）永远够不着之后的回复
# （「缺 53 → 53」「缺 213 → 213」原地打转）。现在把每楼存下的最后一条回复当游标交给读取组件，它点之前把页面里
# 这楼的游标改过去，站点就从那里接着往后拉（读取组件 reader-10 起认 expand_resume，老组件忽略即从头展开）。

SUB_PER_HOUR = 30  # 读取组件楼中楼闸：每小时最多点几次「展开回复」（XHS_SUB_PER_HOUR，同 reader 的默认）


def _reply_time(s: dict[str, Any]) -> datetime | None:
    return _parse(s.get("created_at"))


def resume_points(source: dict[str, Any], targets: list[str]) -> list[str]:
    """要续的楼各自从哪接着展开："comment_id:最后一条回复 id:已存条数"。游标取发得最晚的那条
    （站点按时间正序给回复；首屏那条置顶回复可能排在最前、时间却晚，不能拿列表最后一个硬算）。存不到 2 条的不续（从头点就行）。"""
    want = set(str(t) for t in targets)
    out = []
    for c in source.get("comments") or []:
        cid = str(c.get("comment_id") or "")
        subs = [s for s in c.get("sub_comments") or [] if s.get("comment_id")]
        if cid not in want or len(subs) < 2:
            continue
        stamped = [(t, i, s) for i, s in enumerate(subs) if (t := _reply_time(s))]
        last = max(stamped, key=lambda x: (x[0], x[1]))[2] if stamped else subs[-1]
        out.append(f"{cid}:{last['comment_id']}:{len(subs)}")
    return out


FLOORS_RESUME_MIN = 30  # 存下不到这么多楼就从头滚（一趟就能滚完，没必要续）


def floors_resume_point(source: dict[str, Any], state: dict[str, Any] | None = None) -> str | None:
    """一级评论接着翻的断点 "最后一楼游标:已存楼数"（1017）：热门帖一趟 8 分钟只滚得到 ~500 楼，每次从第 1 楼滚起永远到不了底。
    原帖已经读到底、存的楼太少、上次续翻没多拿到（resume_floors_stale）就不续。"""
    cap = source.get("capture") or {}
    # 1017：游标以续读状态里记的「读到最深的那个」为准——每次开页的 capture 游标会被只读前几十楼的续展冲掉
    cursor = str((state or {}).get("floors_cursor") or cap.get("comments_cursor") or "")
    n = len(source.get("comments") or [])
    if not cursor or n < FLOORS_RESUME_MIN or (cap.get("comment_load") or {}).get("has_more") is False:
        return None
    if (state or {}).get("resume_floors_stale"):
        return None
    return f"{cursor}:{n}"


GONE_MIGRATION = "gone-floors-1017"


def forget_unproven_gone() -> int:
    """1017 一次性：以前「没滚到就记成删了」的 gone_floors 全部作废（没法分辨哪些是真删的；真删的下次滚到底会重新认出来）。"""
    marker = storage.link_brain_home() / f"migrated-{GONE_MIGRATION}"
    if marker.exists():
        return 0
    n = 0
    for source_key, source_id in _objects():
        state = load_state(source_key, source_id)
        if state.get("gone_floors"):
            state.pop("gone_floors", None)
            save_state(source_key, source_id, state)
            n += 1
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(n), encoding="utf-8")
    return n


def deepest_cursor(comments: list[dict[str, Any]], *cursors: Any) -> str:
    """几个一级评论游标里，在存档楼序里最靠后的那个（游标 = 那一页最后一楼的 id；认不出的排最前）。"""
    pos = {str(c.get("comment_id") or ""): i for i, c in enumerate(comments)}
    cands = [str(c) for c in cursors if c]
    return max(cands, key=lambda c: pos.get(c, -1)) if cands else ""


REPLIES_PER_CLICK = 5  # 站点每点一次「展开回复」大约给几条（num=10，实测多半 5 条）


def fill_plan(source: dict[str, Any], state: dict[str, Any] | None = None, floors: int | None = None) -> dict[str, Any]:
    """1018 她：一级评论拉完之后，把要展开的楼列成计划——哪些楼、各缺多少、预计点几次、要多久。读全了的楼不在里面（不碰）。"""
    floors = floors or FLOOR_ALL
    sc = scope(source, floors, state or {})
    comments = (source.get("comments") or [])[:floors]
    gaps = sorted(sc["gaps"], key=lambda g: g["floor"])
    clicks = sum(-(-g["missing"] // REPLIES_PER_CLICK) for g in gaps)
    per_hour = _per_hour()
    return {"floors": len(comments), "floors_more": sc["more_floors"],
            "complete": len(comments) - len(gaps) - len(sc["settled"]), "settled": len(sc["settled"]),
            "need_expand": len(gaps), "missing": sc["missing"], "clicks": clicks,
            "hours": round(clicks / per_hour, 1), "per_hour": per_hour,
            "next": [{"floor": g["floor"], "missing": g["missing"], "shown": g["shown"]} for g in gaps[:10]]}


def _per_hour() -> int:
    """楼中楼每小时额度（和 sub_quota 同一套来源）。"""
    try:
        per_hour = max(1, int(os.environ.get("XHS_SUB_PER_HOUR") or SUB_PER_HOUR))
    except ValueError:
        per_hour = SUB_PER_HOUR
    try:
        from . import accounts
        v = int(json.loads((accounts.profile_dir() / "sub-per-hour.json").read_text(encoding="utf-8")).get("per_hour") or 0)
        if v > 0:
            per_hour = min(v, 120)
    except Exception:  # noqa: BLE001
        pass
    return per_hour


SUB_PAUSE_PER_STRIKE = timedelta(hours=24)   # 读取组件 sub_budget.subPauseAfterStrike：每次限频楼中楼暂停 24 小时 × 次数
RATE_STRIKE_WINDOW = timedelta(hours=24)     # 读取组件 rateLimitStrikeWindow：两次限频隔这么久以内算连续


def _profile_json(name: str) -> dict[str, Any]:
    try:
        from . import accounts
        data = json.loads((accounts.profile_dir() / name).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 文件没有 / 坏了 = 没有这条
        return {}


def sub_gate_closed(now: datetime | None = None) -> tuple[str, datetime | None]:
    """读取组件的楼中楼闸现在是不是因为「熔断 / 冷却自查」或「限频后暂停」关着（Go sub_budget.subGateWhy 的前两条，
    1028 审查 A6：以前 Python 只看每小时点击数，限频后 24–72 小时里把只展开楼中楼的篇一篇篇白开）。
    返回 (原因, 大概几点会开)；('', None) = 不因这两条关。只读 profile 目录里的文件，不碰号。"""
    now = now or _now()
    hold = _profile_json("risk-hold.json")
    if hold.get("code"):
        from . import accounts
        if accounts.is_rate_limited(hold):
            until = accounts.rate_limit_until(hold)
            return ("读取服务在限频冷却 / 到点自探中，楼中楼不点", until if until and until > now else None)
        return (f"读取服务在熔断 / 冷却自查中（{hold.get('code')}），楼中楼不点", None)
    strikes = _profile_json("rate-limit-strikes.json")
    n = _int(strikes.get("strikes"))
    last = _parse(strikes.get("last"))
    if n > 0 and last and now - last <= RATE_STRIKE_WINDOW:
        until = last + n * SUB_PAUSE_PER_STRIKE
        if now < until:
            return (f"24 小时内被限频 {n} 次，楼中楼暂停到 {until:%m-%d %H:%M}", until)
    return "", None


def sub_quota(now: datetime | None = None) -> tuple[int, datetime | None]:
    """楼中楼这一小时还能点几次 + 最早哪一刻空出一次（读读取组件落盘的 sub-expand.json，只读；读不到按满额）。
    1028（A6）：闸因熔断 / 限频后暂停关着时直接 0（和读取组件 subGateWhy 同一口径）。"""
    per_hour = _per_hour()
    why, until = sub_gate_closed(now)
    if why:
        return 0, until
    try:
        from . import accounts
        data = json.loads((accounts.profile_dir() / "sub-expand.json").read_text(encoding="utf-8"))
        clicks = sorted(t for t in (_parse(x) for x in data.get("clicks") or []) if t)
    except Exception:  # noqa: BLE001 - 文件没有 / 坏了：按满额（真闸在读取组件里）
        return per_hour, None
    now = now or _now()
    recent = [t for t in clicks if now - t < timedelta(hours=1)]
    left = max(0, per_hour - len(recent))
    return left, (recent[0] + timedelta(hours=1) if recent and not left else None)


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


# 1016（她：已放弃的不要放弃）：补不上的不再永久停，按 3 / 7 / 14 天慢慢再试一次（之后每 14 天一次）。
STUCK_RETRY_DAYS = (3, 7, 14)

# 1016：这些停因说明这次根本没真去点（楼中楼闸关着 / 预算 / 限频 / 风控停下），不算「续读没多拿到」。
# 1017：not_expanded = 这楼这次没点（楼中楼闸关在它滚出来之前，没来得及标 sub_paused），也不算
NOT_A_REAL_TRY = {"sub_paused", "not_reached", "budget", "throttled", "risk", "cancelled", "not_expanded"}


def stuck_retry_due(state: dict[str, Any], now: datetime | None = None) -> bool:
    """补不上的那篇到没到下一次慢速重试的时候。"""
    at = _parse(state.get("stuck_at"))
    if at is None:
        return False  # 不知道哪天停的：按刚停算（不至于每轮都开）
    rounds = _int(state.get("stuck_rounds"))
    days = STUCK_RETRY_DAYS[min(rounds, len(STUCK_RETRY_DAYS) - 1)]
    return (now or _now()) - at >= timedelta(days=days)


def is_stuck(state: dict[str, Any], floors: int) -> bool:
    """连着几次补不上、已进问题面板：同一个楼数下先不自动续，到了慢速重试的日子（stuck_retry_due）再试一次。"""
    return (bool(state.get("stuck")) and _int(state.get("stuck_floors") or floors) >= floors
            and not stuck_retry_due(state))


# --------------------------------------------------------------------------
# 全库扫描
# --------------------------------------------------------------------------


def _objects() -> list[tuple[str, str]]:
    from ... import index as index_mod
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


# 1018 她：指定帖子（--only）的开页节奏「20 分钟最多 2 次」——上一趟结束隔 ONLY_GAP_MIN 分钟再开，且 20 分钟内已开过 2 次就等
ONLY_GAP_MIN = 10
ONLY_WINDOW_MIN, ONLY_MAX_OPENS = 20, 2


def opens_within(state: dict[str, Any], minutes: int, now: datetime | None = None) -> list[datetime]:
    """这一篇最近 minutes 分钟内开过页的时刻（按续读历史，从早到晚）。"""
    now = now or _now()
    ats = [t for t in (_parse(h.get("at")) for h in state.get("history") or []) if t]
    return sorted(t for t in ats if now - t < timedelta(minutes=minutes))


def survey(floors: int | None = None, now: datetime | None = None, gap_min: int | None = None,
           window: tuple[int, int] | None = None) -> dict[str, Any]:
    """全库还有哪些篇要续：ready（现在就能续，缺得少的在前）/ cooling（同一篇 45 分钟内刚开过）/ stuck（进了问题面板）/
    restricted（1011：网页版要验证才能看，等她点「打开验证」，不再自动开页）。
    gap_min / window（1018，--only 用）：同一篇隔几分钟再开、(分钟, 最多几次) 窗口内开页次数上限。"""
    from . import restricted as restricted_mod
    floors = floors or floor_target()
    now = now or _now()
    gap = gap_min or fill_gap_min()
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
        entry = {"source": source_key, "source_id": source_id, "item_id": domain.item_id(source_key, source_id),
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
        recent = opens_within(state, window[0], now) if window else []
        if last and now - last < timedelta(minutes=gap):
            entry["eligible_at"] = (last + timedelta(minutes=gap)).isoformat(timespec="seconds")
            cooling.append(entry)
        elif window and len(recent) >= window[1]:
            entry["eligible_at"] = (recent[-window[1]] + timedelta(minutes=window[0])).isoformat(timespec="seconds")
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
             manual: bool = False, progress=None) -> dict[str, Any]:
    """续读一篇：按 plan_fill 选 expand / floors，抓完和旧的并集合并（新 RAW 版本只在真多拿到东西时才写），
    记续读状态，补齐了消问题、连着补不上进问题面板，最后重渲染可见页。碰号：调用方要拿着账号锁。

    manual=True（她点的「再试一次 / 现在抓全部评论」）：不看 45 分钟间隔、不看「已放弃」，照跑一次。"""
    from ... import catch as catch_mod, ingest as ingest_mod, index as index_mod, problems
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
    from . import adapter as xhs
    if not manual and restricted.is_restricted(source_id):
        # 1011：网页版要验证才能看的，等她点「打开验证」，后台不再自动开页
        return {**base, "filled": False, "missing_after": sc["missing"], "restricted": True, "reason": restricted.TEXT}

    # 1017 断点续展：上次带游标续了却一条没多拿到（游标那条被删了之类），这次从头展开一次
    resume = resume_points(source, targets) if mode == "expand" and not state.get("resume_stale") else []
    top_resume = floors_resume_point(source, state) if mode == "floors" else (
        expand_window_resume(source, targets) if mode == "expand" else None)
    gone_before = set(state.get("gone_floors") or [])

    def attempt(url: str) -> dict[str, Any]:
        return ingest_mod.ingest_url(url, refresh=True, comment_floors=floors, verbose=verbose,
                                     expand_floors=targets if mode == "expand" else None, fill=True,
                                     fill_budget_s=budget_s, expand_resume=resume or None, floors_resume=top_resume,
                                     progress=progress)

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
    if summary.get("status") == "trashed":
        # 1025 第二波 PR⑤a：续读的时候她把这篇删了——没发布新版本，别再读状态 / 重渲染一篇已进回收站的
        return {**base, "filled": False, "trashed": True, "missing_after": sc["missing"]}
    meta2, source2 = current_source(source_key, source_id)
    now = _now().isoformat(timespec="seconds")
    cl2 = (source2.get("capture") or {}).get("comment_load") or {}
    deep = deepest_cursor(source2.get("comments") or [], state.get("floors_cursor"),
                          (source.get("capture") or {}).get("comments_cursor"),
                          (source2.get("capture") or {}).get("comments_cursor"))
    if deep:
        state["floors_cursor"] = deep
    if mode == "expand":
        not_found = set(str(x) for x in (summary.get("floors_not_found") or []))
        # 1017：只有一级评论真滚到底（stop=end / has_more=false）还找不到，才算这楼删了；预算到点没滚到不算
        # （以前没滚到就记成删了：一篇热门帖 448 楼被当成删掉，1937 条缺口被悄悄划掉）
        hit_end = str(cl2.get("stop_reason") or "") == "end" or cl2.get("has_more") is False
        if not_found and hit_end:
            state["gone_floors"] = sorted(set(str(x) for x in state.get("gone_floors") or []) | not_found)
    sc2 = scope(source2, floors, state)
    progressed = (sc2["missing"] < before_missing or sc2["stored"] > before_floors
                  or (mode == "expand" and bool(set(state.get("gone_floors") or []) - gone_before)))
    if mode == "floors" and (str(cl2.get("stop_reason") or "") == "end" or cl2.get("has_more") is False):
        # 1017：一级评论真翻到底了——记下来，这个楼数下不再翻（之后的续展只读一页、会把 has_more 写回 true）
        # 1026：翻到底 = 原帖就这么多楼，哪个楼数下都不用再翻（记 FLOOR_ALL，之后的浅续读也不会把「到底了」冲掉）
        state["floors_done"] = FLOOR_ALL if cl2.get("has_more") is False or reached_end(source2.get("capture")) else floors
        state.setdefault("end_at", now)
        state.pop("resume_floors_stale", None)
    elif mode == "floors" and top_resume and sc2["stored"] <= before_floors:
        state["resume_floors_stale"] = True  # 1017：续翻没多拿到（游标那楼被删之类）：下次从第 1 楼滚一次再定
    elif mode == "floors" and sc2["stored"] <= before_floors:
        state["floors_done"] = floors  # 按楼数重读过一次、楼没变多：原帖就这么多楼，这个楼数下不再重读
    elif mode == "floors":
        state.pop("resume_floors_stale", None)
        progressed = progressed or sc2["missing"] < before_missing
    state["attempts"] = _int(state.get("attempts")) + 1
    state["last_at"] = now
    state["last_mode"] = mode
    state["last_missing"] = sc2["missing"]
    gap_reasons = {str(g.get("reason") or "") for g in sc2["gaps"]}
    real_try = not (gap_reasons and gap_reasons <= NOT_A_REAL_TRY) and str(cl2.get("stop_reason") or "") not in NOT_A_REAL_TRY
    if resume and progressed:
        state.pop("resume_stale", None)
    elif resume and real_try:
        state["resume_stale"] = True
    elif not resume:
        state.pop("resume_stale", None)
    if progressed:
        state["no_progress"] = 0
    elif real_try:
        state["no_progress"] = _int(state.get("no_progress")) + 1
    else:
        state["no_progress"] = _int(state.get("no_progress"))  # 这次没真去点（闸关着 / 预算）：不加也不清
    if state.get("stuck") and progressed:
        for k in ("stuck", "stuck_floors", "stuck_at", "stuck_reason", "stuck_rounds"):
            state.pop(k, None)
    state.pop("last_error", None)
    hist = list(state.get("history") or [])[-7:]
    hist.append({"at": now, "mode": mode, "before": before_missing, "after": sc2["missing"], "resumed": len(resume),
                 "floors_resumed_from": int(top_resume.rsplit(":", 1)[1]) if top_resume else 0,
                 "floors_before": before_floors, "floors_after": sc2["stored"],
                 "stop": str(cl2.get("stop_reason") or "")})
    state["history"] = hist
    mode2, _ = plan_fill(sc2)
    if mode2 is None:
        _settle(source_key, source_id, state, item_id, problems)
    elif state["no_progress"] >= NO_PROGRESS_LIMIT:
        main = max(sc2["gaps"], key=lambda g: g["missing"])["reason"] if sc2["gaps"] else str(cl2.get("stop_reason") or "")
        why = reason_text(main)
        rounds = _int(state.get("stuck_rounds")) + (1 if state.get("stuck") else 0)
        state.update(stuck=True, stuck_floors=floors, stuck_at=now, stuck_reason=why, stuck_rounds=rounds)
        save_state(source_key, source_id, state)
        days = STUCK_RETRY_DAYS[min(rounds, len(STUCK_RETRY_DAYS) - 1)]
        problems.report(STEP, CODE_INCOMPLETE,
                        f"{floors_label(floors)}的楼中楼还缺 {sc2['missing']} 条：{why}；连着 {state['no_progress']} 次续读都没多拿到，"
                        f"{days} 天后自动再试（不放弃）",
                        item_id=item_id, title=title, action="retry_later", missing=sc2["missing"])
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
    from ... import index as index_mod, problems
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, item_id)
    finally:
        conn.close()
    if not row:
        return
    from . import restricted
    if restricted.MARKER in str(error):
        # 1016：报错里是 [NOTE_RESTRICTED]（只是这篇网页版要验证）却以普通 AdapterError 到这儿：照「网页版要验证」记，
        # 不算没进展、不报 COMMENTS_INCOMPLETE（和 fill_one 里 NoteRestrictedError 那条路一致）
        restricted.mark(row["source_id"], item_id=item_id, via="comments.fill", detail=str(error)[:200])
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
    # 1026：她手动「抓全部评论」过的这篇，评论区顶上照实写抓到哪了（已抓楼数 / 翻没翻到最后一页 / 还缺什么、为什么），能接着补抓
    full = fetch_report(source, state) if state.get("full_at") else None
    return {**sc, "stuck": stuck, "attempts": _int(state.get("attempts")), "why": reason_text(main) if main else "",
            "gap_reasons": {g["comment_id"]: g["reason"] for g in sc["gaps"] + sc["settled"]},
            "restricted": restricted_view, "full": full}


# --------------------------------------------------------------------------
# 1026 手动「抓全部评论」：抓到哪了、能不能接着补（她：「抓全部评论这里有 bug……有一些它会不齐」）
# --------------------------------------------------------------------------
# 根因（真库只读实查 10-26）：①一篇翻到底的（306 楼、has_more=false）之后被按设置楼数（10 楼）的续展冲掉——
# comments_complete 退回 false、游标退回第 20 楼，页面又说没读全（全库 22 篇）；②抓完只说「评论已更新：N 条」，
# 楼中楼因为每小时额度（sub_paused）停下的 19 楼缺 25 条没人告诉她；③再点一次是从第 1 楼整篇重抓，
# 而不是接着补缺的那几楼 / 从停下的那一页往后翻。


def reached_end(capture: dict[str, Any] | None) -> bool:
    """这一版的一级评论翻到最后一页了吗（读取组件 / MCP 明说没有下一页）。"""
    cap = capture or {}
    cl = cap.get("comment_load") or {}
    return cap.get("comments_complete") is True or cl.get("has_more") is False or str(cl.get("stop_reason") or "") == "end"


def _declared_total(source: dict[str, Any]) -> int | None:
    v = ((source.get("note") or {}).get("engagement") or {}).get("comment_count")
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def fetch_report(source: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    """全部楼层口径（不看设置里的楼数）的抓取结果：已抓楼数 / 回复数、原帖显示的总数（含回复，站点只给这个）、
    翻没翻到最后一页（没到：停在哪、为什么、下次从第几楼接着翻）、哪几楼的楼中楼还缺、为什么、上次失败的原因，
    以及还能不能接着补（resumable）。text 是给她看的一句话。"""
    from . import adapter as xhs
    state = state or {}
    comments = source.get("comments") or []
    cap = source.get("capture") or {}
    cl = cap.get("comment_load") or {}
    sc = scope(source, FLOOR_ALL, state)
    floors = len(comments)
    replies = sum(len(c.get("sub_comments") or []) for c in comments)
    declared = _declared_total(source)
    end = reached_end(cap) or _int(state.get("floors_done")) >= FLOOR_ALL
    stop = str(cl.get("stop_reason") or "")
    mode, _ = plan_fill(sc)
    main = max(sc["gaps"], key=lambda g: g["missing"])["reason"] if sc["gaps"] else ""
    settled_missing = sum(g["missing"] for g in sc["settled"])
    error = str(state.get("last_error") or "")
    if end:
        paging, paging_why = "end", ""
    else:
        paging = "more"
        paging_why = ("按楼数上限只读了前几楼" if stop == "floor_limit" else xhs.REPLY_GAP_CN.get(stop) or
                      ("还没整篇抓过" if not stop else "这次停在这"))
    bits = [f"已抓 {floors} 楼、{replies} 条回复" + (f"（原帖显示共 {declared} 条评论，含回复）" if declared is not None else "")]
    if end:
        bits.append("已翻到最后一页")
    else:
        bits.append(f"还没翻到最后一页（{paging_why}），接着补抓会从第 {floors + 1} 楼往后翻")
    if sc["missing"]:
        bits.append(f"{len(sc['gaps'])} 楼的楼中楼还缺 {sc['missing']} 条（{reason_text(main)}）")
    if settled_missing:
        bits.append(f"另有 {settled_missing} 条原站显示但看不到（删了或被折叠，抓多少次都一样）")
    if error:
        bits.append(f"上次没成：{error}")
    complete = end and not sc["gaps"]
    text = ("评论全部抓齐了：" if complete else "") + "，".join(bits)
    return {"floors": floors, "replies": replies, "declared_total": declared, "stored_total": floors + replies,
            "reached_end": end, "paging": paging, "paging_why": paging_why, "next_floor": None if end else floors + 1,
            "missing": sc["missing"], "gap_floors": len(sc["gaps"]), "why": reason_text(main) if main else "",
            "settled_missing": settled_missing, "error": error, "complete": complete,
            "resumable": mode is not None, "resume_mode": mode, "text": text}


def manual_plan(source: dict[str, Any], state: dict[str, Any] | None) -> str:
    """她点「抓全部评论」这一下做什么：'resume'（整篇抓过、还有没齐的 → 接着补：没翻到底就从停下那页往后翻，翻到底了就只展开缺的楼）
    / 'full'（没整篇抓过，或者全齐了想刷新 → 整篇读一遍，和存下的并集合并）。"""
    state = state or {}
    if not (state.get("full_at") or reached_end(source.get("capture")) or _int(state.get("floors_done")) >= FLOOR_ALL):
        return "full"
    mode, _ = plan_fill(scope(source, FLOOR_ALL, state))
    return "resume" if mode else "full"


def record_full(source_key: str, source_id: str, *, error: str = "") -> dict[str, Any]:
    """手动抓完（或没成）记一笔：full_at / 这次的结果；翻到底了就记 floors_done=FLOOR_ALL（之后的浅续读不会再把它记回没读全）。"""
    _, source = current_source(source_key, source_id)
    state = load_state(source_key, source_id)
    now = _now().isoformat(timespec="seconds")
    state["full_at"] = now
    if error:
        state["last_error"] = str(error)[:200]
    if reached_end(source.get("capture")):
        state["floors_done"] = FLOOR_ALL
        state.setdefault("end_at", now)
    rep = fetch_report(source, state)
    state["full"] = {k: rep[k] for k in ("floors", "replies", "declared_total", "reached_end", "missing", "gap_floors")}
    save_state(source_key, source_id, state)
    return rep


END_MIGRATION = "reached-end-1026"


def remember_reached_end(objects: list[tuple[str, str]] | None = None) -> int:
    """1026 一次性（本地，不开页）：以前某一版翻到底、后来被浅的续读把「到底了」冲掉的篇，在续读状态里补记 floors_done=FLOOR_ALL。
    只认「那一版的楼现在一楼不少都在」的（并集合并保证这一点，再核一遍）。"""
    marker = storage.link_brain_home() / f"migrated-{END_MIGRATION}"
    if objects is None and marker.exists():
        return 0
    n = 0
    for source_key, source_id in (objects if objects is not None else _objects()):
        if source_key != "xiaohongshu":
            continue
        try:
            meta, source = current_source(source_key, source_id)
        except (OSError, ValueError, KeyError):
            continue
        if reached_end(source.get("capture")):
            continue
        state = load_state(source_key, source_id)
        if _int(state.get("floors_done")) >= FLOOR_ALL:
            continue
        have = {xhs.floor_key(c) for c in source.get("comments") or []}
        for v in range(int(meta.get("current_version") or 1) - 1, 0, -1):
            try:
                old = storage.read_json(storage.raw_dir(source_key, source_id, v) / "source.json")
            except (OSError, ValueError):
                continue
            if reached_end(old.get("capture")) and {xhs.floor_key(c) for c in old.get("comments") or []} <= have:
                state["floors_done"] = FLOOR_ALL
                state.setdefault("end_at", (old.get("capture") or {}).get("captured_at") or _now().isoformat(timespec="seconds"))
                save_state(source_key, source_id, state)
                n += 1
                break
    if objects is None:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(n), encoding="utf-8")
    return n


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
        # 1028：pid 会被系统复用（10-28 13:33 停掉的补跑，pid 后来成了 svchost，「已经在跑」挡了 7 小时）——
        # 心跳 STALE_MIN 分钟没动也算停了（一篇最长 FILL_BUDGET_S + 90 秒，等待时每 HEARTBEAT_S 秒写一次）
        updated = _parse(st.get("updated_at"))
        stale = updated is not None and _now() - updated > timedelta(minutes=STALE_MIN)
        if stale or storage.pid_state(st.get("pid")) == "dead":
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
    from ... import sync_schedule
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


# 1018：夜跑停在不碰号的步骤上时补评论不用让路——以前整个夜跑任务没结束就一直等，收藏同步 10:25 做完、后面识图 /
# 概要 / 向量 / 目录跑到 11:32，补评论白等 67 分钟。
# 1028（审查 A7）：碰不碰号以 nightly.STEPS 里 Step.account 为准，不再自己抄一份前缀名单（名单漏了「attachments --recheck
# --guest-only」150 分钟和「index catch-up」，每晚白等最多 3 小时）。认不出的步骤照旧让路（宁可多等）。


def step_touches_account(name: str) -> bool | None:
    """夜跑这一步碰不碰号：True / False；nightly.STEPS 里没有这个名字 → None（认不出）。"""
    name = (name or "").strip()
    if not name:
        return None
    try:
        from ... import nightly
        steps = nightly.STEPS
    except Exception:  # noqa: BLE001 - 夜跑模块读不动：当认不出
        return None
    for st in steps:
        if st.name == name:
            return bool(st.account)
    return None


def nightly_step(log_paths: list[Path] | None = None) -> str:
    """夜跑日志里正在跑的那一步（最后一个「=== X 开始」且后面还没有它的「结束」）；读不出来返回 ''。"""
    import re
    if log_paths is None:
        from ... import nightly
        from . import accounts
        log_paths = [Path(nightly.default_log_path()), accounts.tool_dir() / "fav-sync.log"]
    best: tuple[float, str] = (0.0, "")
    for p in log_paths:
        try:
            mtime = p.stat().st_mtime
            with open(p, "rb") as fh:
                fh.seek(max(0, p.stat().st_size - 64_000))
                tail = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        cur = ""
        for line in tail.splitlines():
            m = re.search(r"=== (.+?) (开始|结束)", line)
            if not m:
                continue
            cur = m.group(1).strip() if m.group(2) == "开始" else ("" if m.group(1).strip() == cur else cur)
        if mtime > best[0]:
            best = (mtime, cur)
    return best[1]


def nightly_busy(now: datetime | None = None, rows: list[dict[str, Any]] | None = None,
                 step: str | None = None) -> str:
    """夜跑在跑（且正在碰号的那几步）/ 快开始了 → 一句原因；否则 ''。"""
    now = now or _now()
    rows = task_rows() if rows is None else rows
    for r in rows:
        if str(r.get("state") or "") == "Running":
            cur = nightly_step() if step is None else step
            if step_touches_account(cur) is False:
                continue  # 这一步只在本机算、不用号：不用让
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
    if hold and accounts.is_rate_limited(hold):
        return accounts.RATE_LIMIT_CODE, accounts.rate_limit_text(hold)  # 1015：限频冷却，到点自己接着补
    if hold:
        code = str(hold.get("code") or "RISK_HOLD")
        what = "掉登录了：在设置 / 问题入口扫码登录" if code == "NOT_LOGGED_IN" else "弹了验证（不是掉登录）：点问题入口「打开验证」"
        return code, f"小红书{what}，处理好自动接着补（{accounts.hold_text(hold) or '暂停中'}）"
    if isinstance(session, dict):
        if session.get("logged_in") is False:
            return "NOT_LOGGED_IN", "小红书掉登录了：在设置 / 问题入口扫码登录，登好自动接着补"
        # 1028：只认「正在扫码」（state=waiting）和验证窗口开着；登录完留下的 success / failed 不算忙
        #（以前「不是 idle 就当忙」：登录成功后 state 一直是 success，补跑干等了 48 分钟）
        if session.get("verifying") or str(session.get("state") or "") == "waiting":
            return "BUSY", "正在扫码 / 验证，等它完了再接着补"
    return "", ""


def spawn_worker() -> dict[str, Any]:
    """拉起后台补跑（脱离调用方，单实例：已经在跑就不再起）。"""
    st = read_status()
    if st.get("state") in ("running", "waiting", "paused"):
        return {"ok": True, "started": False, "already": True, "pid": st.get("pid"), "message": "后台补评论已经在跑"}
    from ... import deps, procs
    argv = [deps.python_exe(), "-m", "link_brain", "comments", "--fill-pending", "--until-done"]   # P0 1024：和插件同一个解释器
    env = dict(os.environ)
    env[storage.ENV_VAULT] = str(storage.vault_root())
    env["PYTHONIOENCODING"] = "utf-8"
    log = storage.link_brain_home() / "comments-fill.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    pid = procs.spawn_detached(argv, cwd=str(storage.repo_root()), env=env, log_path=log)
    return {"ok": True, "started": True, "pid": pid, "message": "后台开始补评论"}


# --------------------------------------------------------------------------
# 补跑循环（夜跑一步 / 后台一直跑到补完）
# --------------------------------------------------------------------------


def run(args, *, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> int:
    """`comments --fill-pending [--until-done] [--budget-min M] [--limit N] [--then-background]`。

    夜跑这一步（不带 --until-done）：预算内能续的各续一次；号要人处理退出 5、号被占退出 6；没补完、带 --then-background
    就拉起后台补跑接着补（它会等夜跑做完再开始碰号）。
    后台（--until-done）：一直补到全库没有能续的缺口；撞验证 / 掉登录就停下等（只看内存状态，不开页），她处理好自动接着；
    夜跑在跑、或别的任务要用号就让路。单实例：已经有一个在跑就直接退出 0。"""
    from . import accounts
    from . import adapter as xhs
    from ...read import dump_json, outcome
    from . import night_captcha
    until_done = bool(getattr(args, "until_done", False))
    if until_done:
        night_captcha.set_unattended("comments-fill")  # 1011：后台补跑没人看着——撞验证先冷却自查，不当场推
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
    try:
        # 1011：以前因「页面上没有这篇」放弃了的续读解开一次（本地，零开页），让新办法认它、给它搜一次新口令
        from . import restricted
        restricted.release_legacy_fill_stuck()
        restricted.reclassify_fill_failures()
        forget_unproven_gone()
        remember_reached_end()
    except Exception as exc:  # noqa: BLE001 - 迁移没成不挡补评论
        print(f"[comments] 旧的「已放弃」没解开：{type(exc).__name__}: {exc}", file=sys.stderr)
    # 1017 她：「对特定帖子能跑完楼层」——--only 只补这几篇、按 --floors 的楼数（不改全局设置），stuck 的也照补
    only = [x if domain.parse_item_id(x) else domain.item_id(xhs.SOURCE, x) for x in
            (s.strip() for s in ",".join(getattr(args, "only", None) or []).split(",")) if x]
    only_floors = None
    if only:
        fl = str(getattr(args, "floors", "") or "")
        only_floors = FLOOR_ALL if fl == "all" else floor_target(fl or 50)

    def target_floors() -> int:
        return only_floors or floor_target()

    floors = target_floors()
    status = Status(floors, background=until_done)
    done: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    deferred = 0
    exit_code = 0
    stop_msg = ""
    since_catalog = 0
    wait_since: float | None = None   # 1028（A5）：号不能用从几时等起——按墙钟算，不只算歇的那段（拉起服务的 40 秒、深查都算）
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
        work_since: list[float] = []  # 1016：这一段连续干活从几时起（跑满 WORK_MIN 分钟强制歇 REST_MIN 分钟）
        last_work_end = [0.0]  # 1018：上一篇做完的时刻——中间让路 / 等额度歇够了 REST_MIN，就算歇过了，别再强制歇
        while True:
            floors = target_floors()
            sv = survey(floors, gap_min=ONLY_GAP_MIN, window=(ONLY_WINDOW_MIN, ONLY_MAX_OPENS)) if only else survey(floors)
            if only:
                pick = lambda xs: [e for e in xs if e["item_id"] in only]  # noqa: E731
                sv = {**sv, "ready": pick(sv["ready"]) + pick(sv["stuck"]), "cooling": pick(sv["cooling"]),
                      "stuck": [], "restricted": pick(sv["restricted"])}
                sv["missing"] = sum(e["missing"] for e in sv["ready"] + sv["cooling"])
                sv["pending"] = len(sv["ready"]) + len(sv["cooling"])
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
                        message=status.text("补评论") + (f" · 同一篇 20 分钟最多开 2 次，{first:%H:%M} 接着补" if only else
                                                       f" · 同一篇隔 {fill_gap_min()} 分钟再开，{first:%H:%M} 接着补"))
                    continue
                break
            entry = ready[0]
            left_q, free_at = sub_quota()
            if left_q <= 0:
                # 1017：楼中楼这一小时的额度用完了——只展开楼中楼的篇（expand）开了也是白开（sub_paused），先等额度；
                # 要多读楼的（floors）照常
                floors_first = [e for e in ready if e["mode"] == "floors"]
                gate_why = sub_gate_closed()[0] or "楼中楼这一小时的额度用完了"
                if floors_first:
                    entry = floors_first[0]
                elif until_done:
                    wait = max(60.0, min(1800.0, ((free_at or _now()) - _now()).total_seconds() + 30))
                    nap(wait, state="waiting", current=None, wait_code="SUB_QUOTA",
                        message=status.text("补评论歇一会") + f" · {gate_why}，"
                        f"{(free_at or _now() + timedelta(seconds=wait)):%H:%M} 接着补")
                    continue
                else:
                    stop_msg, deferred = f"{gate_why}，下次接着补", len(ready)
                    break
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
            if code == "CAPTCHA_REQUIRED" and until_done and night_captcha.unattended():
                # 1011：后台补评论撞的验证先不叫她——冷却后自查一次（night_captcha），干净就接着补，还在就今天先停（不推）
                r = night_captcha.recover(wait=False)
                res = r.get("result")
                if res in ("cleared", "no_hold"):
                    continue  # 自查干净 / 暂停已经不在了：回头再看一眼号，接着补
                if res in ("cooling", "busy", "error"):
                    left = float(r.get("retry_after_s") or WAIT_BUSY_S)
                    when = f"，{r['ready_at'][11:16]} 自己再看一眼" if r.get("ready_at") else ""
                    nap(max(30.0, min(900.0, left)), state="waiting", current=None, wait_code="CAPTCHA_COOLDOWN",
                        message=status.text("补评论暂停") + f" · {night_captcha.SAY}，先冷却{when}")
                    continue
                if res != "not_captcha":
                    # 今天已经自查过 / 自查验证还在 / 掉登录：今天先停（不推；连着两晚才由 night_captcha 推一次）
                    stop_msg = f"{night_captcha.SAY}：{r.get('message') or '冷却后自查没过'}"
                    deferred = len(ready)
                    break
            if code:
                if not until_done or code == "NOT_INSTALLED":
                    stop_msg = why if code != "NOT_INSTALLED" else "没装读取组件，补不了评论（装好后同步时会接着补）"
                    exit_code = 5 if code in accounts.NEEDS_HUMAN_CODES or code in ("RISK_HOLD",) else 0
                    deferred = len(ready)
                    break
                if wait_since is None:
                    wait_since = clock()
                if clock() - wait_since > MAX_WAIT_S:
                    stop_msg = f"等了 {MAX_WAIT_S // 3600} 小时还没好（{why}），先停；处理好后下次同步 / 夜跑 / 打开 Obsidian 会接着补"
                    deferred = len(ready)
                    break
                nap(WAIT_HUMAN_S if code in accounts.NEEDS_HUMAN_CODES else WAIT_BUSY_S, state="waiting", current=None,
                    wait_code=code, message=status.text("补评论暂停") + " · " + why)
                continue
            rp_why, rp_until = actionlog.repeat_pause("comments")
            if rp_why:  # 1016：同一种行为（读评论 / 楼中楼）反复被拦：这类先停，别越撞越重
                if not until_done:
                    stop_msg, deferred = rp_why, len(ready)
                    break
                left = (rp_until - _now()).total_seconds() if rp_until else WAIT_BUSY_S
                nap(max(60.0, min(1800.0, left)), state="waiting", current=None, wait_code="REPEAT_PAUSE",
                    message=status.text("补评论暂停") + " · " + rp_why)
                continue
            if until_done:
                if work_since and last_work_end[0] and time.monotonic() - last_work_end[0] >= REST_MIN * 60:
                    work_since.clear()  # 1018：让路 / 等额度已经歇了这么久：以前照算「连着干活」，一结束又强制歇 30 分钟
                if not work_since:
                    work_since.append(time.monotonic())
                elif time.monotonic() - work_since[0] >= WORK_MIN * 60:
                    work_since.clear()
                    nap(REST_MIN * 60, state="waiting", current=None, wait_code="REST",
                        message=status.text("补评论歇一会") + f" · 连着补了 {WORK_MIN} 分钟，像人一样歇 {REST_MIN} 分钟")
                    continue
            wait_since = None
            item_id = entry["item_id"]
            status.update(state="running", current={"item_id": item_id, "title": entry["title"][:60]}, wait_code="",
                          message=status.text("正在补评论") + f" · {entry['title'][:24]}")
            attempts_this_run[item_id] = attempts_this_run.get(item_id, 0) + 1
            lock_wait = 300.0 if until_done else float(getattr(args, "wait_lock_min", 2) or 2) * 60
            try:
                with accounts.account_session("comments-fill", wait_s=lock_wait, polite=until_done):
                    out = fill_one(item_id, floors=floors, verbose=verbose, manual=bool(only))
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
                from ... import problems
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
                note_failure(item_id, errtext(exc))
                failed.append({"item_id": item_id, "error": str(exc)[:200]})
                continue
            last_work_end[0] = time.monotonic()
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
        from ... import catalog
        catalog.build()
    except Exception as exc:  # noqa: BLE001 - 目录下次重建会跟上
        print(f"[comments] 目录没重建上：{type(exc).__name__}: {exc}", file=sys.stderr)


def status_payload() -> dict[str, Any]:
    """`comments --fill-status`：插件设置页 / 状态栏用。本地读，不碰号。"""
    from ...read import outcome
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


# ---- 评论续读落盘（1025 第二波 PR⑤b 从 ingest.py 搬来，内容不变）--------------------------------------

def _merge_fill(source: dict[str, Any], old: dict[str, Any], expanded: set[str], captured_at: str, log,
                *, keep_order: bool = False, old_end: bool = False) -> dict[str, Any]:
    """续读（1009）：正文 / 图片 / 附件沿用上一版（这次只为评论开页），评论和上一版并集合并，comment_load 重算缺口。
    keep_order（1017 一级评论续翻）：这次只有首屏 + 接着翻的楼，保持老顺序、新楼接在后面。"""
    keep_order = keep_order or bool(expanded)
    merged = xhs.merge_comments(old.get("comments") or [], source.get("comments") or [], expanded,
                                keep_old_order=keep_order)
    new_cl = source["capture"].get("comment_load")
    if new_cl is not None:
        new_cl = {**new_cl, "fill_last_at": captured_at}
    cl = xhs.merge_comment_load((old.get("capture") or {}).get("comment_load"), new_cl,
                                expanded or {str(c.get("comment_id") or "") for c in source.get("comments") or []}, merged)
    before = sum(len(c.get("sub_comments") or []) for c in old.get("comments") or [])
    after = sum(len(c.get("sub_comments") or []) for c in merged)
    log(f"续读合并：一级 {len(old.get('comments') or [])} → {len(merged)} 楼，楼中楼 {before} → {after} 条")
    old_cap = old.get("capture") or {}
    capture = {**old_cap, **source["capture"], "comment_load": cl}
    if old_cap.get("comments_complete") is True or (new_cl or {}).get("has_more") is False:
        capture["comments_complete"] = True if (new_cl or {}).get("has_more") is not True else capture.get("comments_complete")
    # 1026（她：抓全部评论后「有一些它会不齐」）：上一版已经一页一页翻到底了，这次只是按楼数上限读前几楼 / 只展开几楼的续读——
    # 这次的 has_more=true 只说明「楼数上限外还有」，不说明存档缺楼。以前直接拿这次的盖掉：翻到底的 306 楼被记回「没读全、还有下一页」，
    # 游标退回第 20 楼（真库 22 篇这样）。现在翻到底的结论和最深的游标留着，这次读的样子另记在 last_read。
    if (old_end or reached_end(old_cap)) and not reached_end(source["capture"]):
        last = {k: (new_cl or {}).get(k) for k in ("floor_limit", "floors_loaded", "has_more", "stop_reason")}
        cl = {**(cl or {}), "has_more": False, "stop_reason": "end", "last_read": last,
              "floors_loaded": max(_int((cl or {}).get("floors_loaded")), len(merged))}
        cl["partial"] = False
        capture["comment_load"] = cl
        capture["comments_complete"] = True
    capture["comments_cursor"] = deepest_cursor(merged, old_cap.get("comments_cursor"),
                                                source["capture"].get("comments_cursor")) or capture.get("comments_cursor")
    note = {**(old.get("note") or {})}
    if (source.get("note") or {}).get("xsec_token"):
        note["xsec_token"] = source["note"]["xsec_token"]
    return {**old, "comments": merged, "note": note, "capture": capture}


def _log_comment_load(source: dict[str, Any], log) -> None:
    """评论读到哪一步、缺多少，进同步记录（1008 Owner：缺口要让人看到，不能悄悄少一截）。
    1009：缺口按设置里的楼数现算（comment_fill.scope），读不完的后台自动接着读。"""
    floors = floor_target()
    sc = scope(source, floors)
    cl = (source.get("capture") or {}).get("comment_load") or {}
    item_id = domain.item_id(xhs.SOURCE, source["source_id"])
    title = (source.get("note") or {}).get("title")
    try:
        from ... import synclog
        if sc["missing"] > 0:
            main = max(sc["gaps"], key=lambda g: g["missing"])["reason"]
            why = reason_text(main)
            synclog.note("comments", item_id, False, title=title,
                         reason=f"{floors_label(floors)}的楼中楼还缺 {sc['missing']} 条（{why}），后台自动接着读",
                         code="COMMENTS_PARTIAL", retry=["comments", item_id, "--fill"])
            log(f"评论：楼中楼还缺 {sc['missing']} 条（{why}）")
        elif int(cl.get("fill_attempts") or 0) > 0:
            synclog.note("comments", item_id, True, title=title)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] {errtext(exc)}", file=sys.stderr)


def _main_gap_reason(cl: dict[str, Any]) -> str:
    gaps = cl.get("gaps") or []
    if not gaps:
        return str(cl.get("stop_reason") or "")
    return max(gaps, key=lambda g: int(g.get("missing") or 0)).get("reason") or str(cl.get("stop_reason") or "")


def _fillable(cl: dict[str, Any]) -> bool:
    """（1008 旧口径，只看读取组件报的缺口；1009 起排程看 comment_fill.survey）这份 comment_load 里有没有能续的缺口。"""
    if int(cl.get("replies_missing") or 0) <= 0:
        return False
    return any(g.get("reason") in xhs.RESUMABLE_GAPS and g.get("comment_id") for g in cl.get("gaps") or [])


def fill_targets(cl: dict[str, Any]) -> list[str]:
    """要续读的楼（comment_id），缺得多的在前。"""
    gaps = [g for g in cl.get("gaps") or [] if g.get("reason") in xhs.RESUMABLE_GAPS and g.get("comment_id")]
    gaps.sort(key=lambda g: -int(g.get("missing") or 0))
    return [str(g["comment_id"]) for g in gaps]


def _reuse_media(source: dict[str, Any], raw_dir: Path, rel_prefix: str, old_manifest: dict[str, Any] | None,
                 object_dir: Path, *, progress=None) -> dict[str, Any]:
    """续读写新版本时：上一版已经下好的图 / 视频 / 语音直接引用旧版本的文件（RAW 不可变，引用安全；识图按资产路径复用，
    不会把整篇图重识一遍），只下这次新冒出来的评论图 / 语音。"""
    old_media = [m for m in (old_manifest or {}).get("media") or [] if m.get("download_status") == "ok" and m.get("file")
                 and (object_dir / m["file"]).is_file()]

    def key(m: dict[str, Any]) -> tuple:
        role = m.get("role")
        if role in ("comment_image",):
            return (role, str(m.get("comment_id") or ""), int(m.get("index") or 0))
        if role == "comment_audio":
            return (role, str(m.get("comment_id") or ""))
        if role in ("note_image", "video_cover"):
            return (role, int(m.get("index") or 0))
        return (role,)

    have = {key(m): m for m in old_media}
    trimmed = json.loads(json.dumps(source))
    reused: list[dict[str, Any]] = []
    note = trimmed["note"]
    keep_images = []
    for image in note.get("images") or []:
        role = "video_cover" if note.get("kind") == "video" else "note_image"
        hit = have.get((role, int(image.get("index") or 0)))
        if hit:
            reused.append(dict(hit))
        else:
            keep_images.append(image)
    note["images"] = keep_images
    video_hit = next((m for m in old_media if m.get("role") == "video"), None)
    if video_hit is not None and (note.get("video") or {}).get("video_url"):
        reused.append(dict(video_hit))
        note["video"] = {**note["video"], "video_url": None}
    for c in trimmed.get("comments") or []:
        for group in [c, *(c.get("sub_comments") or [])]:
            cid = str(group.get("comment_id") or "")
            imgs = group.get("images") or []
            if imgs and all(have.get(("comment_image", cid, i)) for i in range(1, len(imgs) + 1)):
                reused.extend(dict(have[("comment_image", cid, i)]) for i in range(1, len(imgs) + 1))
                group["images"] = []
            audio = group.get("audio")
            if audio and have.get(("comment_audio", cid)):
                reused.append(dict(have[("comment_audio", cid)]))
                group["audio"] = None
    from ... import ingest as ingest_mod  # 下载走 ingest 的通用下载（测试 monkeypatch 打在 ingest 上）
    manifest = ingest_mod.download_media(trimmed, raw_dir, rel_prefix, progress=progress)
    manifest["media"] = reused + manifest["media"]
    counted = [m for m in manifest["media"] if m["role"] in ("note_image", "comment_image", "video_cover")]
    manifest["images_declared"] = len(counted)
    manifest["images_ok"] = sum(1 for m in counted if m["download_status"] == "ok")
    manifest["images_complete"] = manifest["images_declared"] == manifest["images_ok"]
    manifest["reused"] = len(reused)
    return manifest


def ingest_fill(parsed: dict[str, Any], conn, existing: dict[str, Any], *, log, progress=None, comment_floors=None,
                budget_left=None, expand_floors: list[str] | None = None, fill_budget_s: int | None = None,
                expand_resume: list[str] | None = None, floors_resume: str | None = None, origin: str, actor: str,
                ingest_kind: str, note: str | None, created_at: str) -> dict[str, Any]:
    """评论续读（ingest_url fill=True，要求已归档）：这次开页只为评论——不做附件网页探测、不碰登录号补看；
    正文 / 图片沿用上一版，评论和上一版并集合并（调小楼数不删已抓的）；**没多拿到任何评论就不写新版本**；
    写新版本时上一版下好的图 / 视频 / 语音直接引用旧文件（不重下、不重识图）。
    1025 第二波 PR⑤b 从 ingest.ingest_url / _finish_fill 搬来（内容不变），经来源接口的 fill 调进来。"""
    from ... import index as index_mod, ingest as ingest_mod, problems
    sid = parsed["note_id"]
    object_dir = storage.object_dir(xhs.SOURCE, sid)
    old_meta = storage.read_json(object_dir / "meta.json")
    old_dir = storage.raw_dir(xhs.SOURCE, sid, old_meta["current_version"])
    old_source = storage.read_json(old_dir / "source.json")
    old_manifest = storage.read_json(old_dir / "manifest.json") if (old_dir / "manifest.json").exists() else None
    old_web = storage.read_json(old_dir / "web_raw.json") if (old_dir / "web_raw.json").exists() else None
    if not parsed.get("xsec_token"):
        parsed = {**parsed, "xsec_token": (old_source.get("note") or {}).get("xsec_token")}

    log(f"MCP {xhs.MCP_TOOL} @ {xhs.MCP_ENDPOINT}")
    if progress:
        kw = xhs._detail_kwargs(comment_floors, expand_floors, fill_budget_s)
        cap = int(kw.get("timeout") or 600) // 60
        progress("read", f"打开这篇，把评论一楼一楼展开读下来（热门笔记要几分钟到十几分钟，最多 {cap} 分钟）")
    raw = xhs._fetch_with_retry(parsed, log=log, comment_floors=comment_floors, budget_left=budget_left,
                                expand_floors=expand_floors, fill_budget_s=fill_budget_s, progress=progress,
                                expand_resume=expand_resume, floors_resume=floors_resume)
    problems.resolve("ingest", None)  # 抓到了 = 读取服务好着：之前「服务没起来 / 超时」那几条步骤级问题算解决

    expanded = set(expand_floors or [])
    keep_order = bool(floors_resume)
    captured_at = ingest_mod.now_iso()
    if progress:
        progress("merge", "评论读回来了：和存下的合并")
    fresh = xhs.normalize(raw, parsed, captured_at=captured_at, web_probe=None)
    # 1026：续读状态里记着「这篇翻到底过」（老版本被浅的续读盖掉了的那 22 篇由 remember_reached_end 补记）也算
    old_end = _int(load_state(xhs.SOURCE, sid).get("floors_done")) >= FLOOR_ALL
    source = _merge_fill(fresh, old_source, expanded, captured_at, log, keep_order=keep_order, old_end=old_end)
    not_found = list(((raw.get("data") or {}).get("comment_load") or {}).get("floors_not_found") or [])         if isinstance(raw, dict) else []
    meta_path = object_dir / "meta.json"
    subs = sum(len(c.get("sub_comments") or []) for c in source["comments"])
    base = {"hit": False, "item_id": old_meta["item_id"], "note_id": sid, "kind": old_meta.get("kind"),
            "failed": [], "comments": len(source["comments"]), "sub_comments": subs,
            "comments_complete": source["capture"].get("comments_complete"),
            "attachments_status": old_meta.get("attachments_status"), "floors_not_found": not_found,
            "exit_code": ingest_mod.EXIT_OK}
    if xhs.comments_signature(source["comments"]) == xhs.comments_signature(old_source.get("comments") or []):
        log("续读：这次没多拿到评论，不写新 RAW 版本，只更新 last_checked_at")
        meta = ingest_mod._touch_checked(meta_path, old_meta["item_id"], captured_at)
        return {**base, "refreshed_unchanged": True, "version": meta["current_version"],
                "raw_dir": storage.raw_dir(xhs.SOURCE, sid, meta["current_version"]), "manifest": None}
    _log_comment_load(source, log)
    with storage.stage_version(xhs.SOURCE, sid) as stg:
        log(f"续读暂存 → {stg.path.name}")
        storage.write_json(stg.path / "mcp_raw.json", raw)
        # 这次没探测附件：沿用上一版的网页探测结果（附件补查按它判断），并注明出处
        storage.write_json(stg.path / "web_raw.json", old_web if old_web is not None else
                           {"ok": None, "error": "评论续读不探测附件（沿用上一版）"})
        storage.write_json(stg.path / "source.json", source)
        manifest0 = _reuse_media(source, stg.path, f"raw/{stg.path.name}", old_manifest, object_dir, progress=progress)
        try:
            # 和完整重抓同一套保留规则（merge_meta）：抓取产生不了的字段在锁里按当前 meta 原样带上
            version, manifest, meta = ingest_mod._commit_version(
                conn, parsed, stg, manifest0, source=source, sha=index_mod.normalized_source_sha256(source),
                captured_at=captured_at, expect_existing=True, check_sha=True,
                meta_kw=dict(origin=origin, actor=actor, ingest_kind=ingest_kind, note=note), log=log)
        except ingest_mod._Discarded as d:
            return {**base, **ingest_mod._discarded_summary(conn, parsed, d.reason, source, log)}
    raw_dir = storage.raw_dir(xhs.SOURCE, sid, version)
    failed = [m for m in manifest["media"] if m["download_status"] == "failed"]
    return {**base, "refreshed_unchanged": False, "version": version, "raw_dir": raw_dir, "manifest": manifest,
            "failed": failed, "exit_code": ingest_mod.EXIT_MISSING_CONTENT if failed else ingest_mod.EXIT_OK}
