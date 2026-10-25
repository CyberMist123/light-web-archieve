"""`sync-favorites` 子命令（Lot 6）：把 Owner 主号（momo）的**私密收藏**同步进归档。

小红书没有"列出我的收藏"的公开接口；私密收藏只有**登录态自己看自己**才读得到。
读取服务（`accounts.py`，一个号一个持久浏览器目录）的 `/api/v1/favorites` 负责这一步，
吐出 `{items:[{note_id, xsec_token, url, ...}]}`。

拿到 note_id 列表之后，逐条走**和 `catch` 一样**的 `ingest_url`：命中索引就是 HIT（不联网、
不下载），未命中才经同一个读取服务抓正文 / 图 / 评论。去重只认 `xiaohongshu:<note_id>`（硬约束 7）。

硬约束 8：stdout 只许有一个 JSON，日志一律走 stderr。未登录 / 安全验证时**停车 + 报警**，
由界面给出「扫码登录」或「打开验证」按钮；绝不自动重试。

1001 护号 + 夜跑不被砍（审计 A-1/A-2/A-4/B-1/B-3/B-6）：
- 开工前先看风控熔断（有就一页不开，退出 5），再拿账号锁（被别的任务占着 → 退出 6）；
- 只有「抓取阶段」用号：新收藏抓原文 + 本地渲染（不调模型、不识图），标成待 enrich；
  每次联网抓取后（成功失败都算）随机歇 60–180 秒；连续 3 篇抓取失败就停批（退出 1）并报警；
- 已在库的收藏不再重渲染（只有可见 md 丢了才本地补一份）；
- 每天新抓上限读插件 data.json 的 sync.dailyNewLimit（缺省 50，0 = 不限），插件和夜跑共用；
- `--budget-min N` 到点优雅收尾；`--extract` = 抓完后对本次新收的跑 enrich（不碰号、受剩余预算约束）；
- 收藏读回 0 条或比上次少一半以上：照常处理读到的，但状态标失败并报警。

10-04 F1（读收藏读不全）：
- 把上次正常读到的条数当基准传给读取服务（`?expect=N`，没有基准就不带，旧读取服务不认也没事）；
- 新读取服务回 `partial` / `stop_reason` / `has_more`：partial = 只读到一截。这一截里的新收藏照抓（不浪费），
  同步结果如实标「只读到一截（原因）」，**当晚不再重读收藏列表**（退出码 3：夜跑不重试、也不另登记「步骤出错」——
  10-04 就是一晚读三次撞上滑块）；
- 旧读取服务没这些字段：和以前一样（0 条 / 少一半以上算可疑）。

1011 增量读（作者本机：每晚把 1230 条收藏整份滚一遍，隔一晚撞一次滑块）：
- 平时只读最新那一段：`POST /api/v1/favorites` 带已知 id（上次全量名单 + 已在库的 + 回收站里的），读取服务从最新往下
  连着碰到 `LWA_FAV_STOP_KNOWN`（默认 20）篇已知的就停（stop_reason=known_streak，`incremental=true`）；
- 全量（滚到底）只在：每周一次（`LWA_FAV_FULL_WEEKDAY`，默认周日；-1 = 不按星期）、上次全量超过 7 天、
  没有全量名单、上一晚按名单抓连着失败（口令可能过期了）、或明确要（`--full`）。全量负责：名单（判删除 / 补积压）、
  口令刷新、条数基准；
- 全量名单存在 `_archive/fav-list.json`（最新在前）：增量那晚的待抓清单 = 读到的最新一段 + 名单里其余的（积压从这里接着补，
  用名单里的口令，7 天内有效）；增量读不动基准、不当「只读到一截」、口令只合并读到的那段（attachments.remember_fav_tokens）；
- `--from-snapshot`：不读收藏列表，只按名单补抓（夜里撞验证、冷却后自查恢复之后用：不再去碰刚弹过滑块的收藏页）；
- 老读取服务不认 POST（404 / 405）：退回 GET 读全量（那次没开页、不吃限频）。
"""

from __future__ import annotations
from ...errtext import errtext

import contextlib
import os
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from ... import domain, sync_state, synclog
from ... import ingest as ingest_mod, read as read_mod
from . import adapter as xhs
from . import accounts

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PARTIAL = 3  # 只读到一截 / 条数可疑：读到的已照常入档、原因已登记（sync.favorites）；今晚别再重读列表
EXIT_NEEDS_HUMAN = 5
EXIT_ACCOUNT_BUSY = 6

MAX_CONSECUTIVE_FAILURES = 3
# 已知坏篇（以前抓失败过：已删 / 仅作者可见）排在最后抓，它们再失败不算「服务出事」的信号；
# 但也得有闸：一晚里已知坏篇连着失败 3 篇，余下的已知坏篇今晚不再开（小红书软限流时回的就是「笔记不可用」）。
MAX_KNOWN_BAD_STREAK = 3
FAILED_NOTE_SKIP_AFTER = 3  # 同一篇抓失败 3 晚（已删 / 仅作者可见）就先跳过，免得它每晚把整批卡在同一处
FAILED_NOTE_RETRY_DAYS = 7

# 时间预算（--budget-min）：开一篇新的抓取前，剩下的时间至少要装得下它的最坏耗时
# （开页间隔 ≤40 秒 + 抓详情超时 600 秒 + 登录号补看 150 秒 + 本地渲染），不然这一篇会拖过预算、撞上夜跑外层的限时被整棵杀。
FETCH_RESERVE_SECONDS = 15 * 60
# 新收藏顺手下附件至少要剩这么多；不够就留给 4 点的 attachments --all
GRAB_RESERVE_SECONDS = 20 * 60
# 插件点的同步带 --extract 但不带 --budget-min：补识图 / 概要最多跑这么久，剩下的交给夜里的 enrich --pending
ENRICH_DEFAULT_BUDGET_MIN = 30


# 1008（读取组件 d7）：读收藏「这次先停、下次照常」的两种（503，不写熔断）——登记 TRANSIENT、退出 3（读到一截那一类：
# 夜跑今晚不再重读收藏，但不算要人处理，当晚其它碰号步骤照跑）
SOFT_STOP_CODES = ("HIDDEN_WIDGET", "FAV_TAB_STUCK")
SOFT_STOP_TEXT = {
    "HIDDEN_WIDGET": "页面里有验证组件但没显示滑块，这次先停，下次照常读",
    "FAV_TAB_STUCK": "收藏页签点不动，疑似小红书在限流，今晚先不读收藏",
}


FAV_LIST_NAME = "fav-list.json"
STOP_KNOWN_DEFAULT = 20
FULL_MAX_DAYS = 7
FULL_WEEKDAY_DEFAULT = 6            # 周日（datetime.weekday()：周一 = 0）
SNAPSHOT_FIELDS = ("note_id", "xsec_token", "url", "title", "type", "author", "author_id")


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip())
    except ValueError:
        return default


def stop_after_known() -> int:
    return max(5, min(200, _env_int("LWA_FAV_STOP_KNOWN", STOP_KNOWN_DEFAULT)))


def fav_list_path():
    from ... import storage
    return storage.archive_root() / FAV_LIST_NAME


def load_snapshot() -> dict[str, Any]:
    """全量名单 {full_at, at, items:[{note_id, xsec_token, url, title…}], full_next?}；没有 / 坏了 = {}。"""
    from ... import storage
    try:
        data = storage.read_json(fav_list_path())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else {}


def _save_snapshot(data: dict[str, Any]) -> None:
    from ... import storage
    try:
        storage.write_json(fav_list_path(), data)
    except OSError as exc:
        print(f"[sync-favorites] 收藏名单没存上（不影响同步）：{exc}", file=sys.stderr)


def _slim(item: dict[str, Any]) -> dict[str, Any]:
    return {k: item[k] for k in SNAPSHOT_FIELDS if item.get(k) not in (None, "")}


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)).astimezone()
    except (TypeError, ValueError):
        return None


def read_mode(*, force_full: bool = False, now: datetime | None = None) -> tuple[str, str]:
    """这次读收藏读全量还是增量：('full' | 'incremental', 为什么)。"""
    now = now or datetime.now().astimezone()
    if force_full:
        return "full", "明确要读全量"
    snap = load_snapshot()
    if not snap.get("items"):
        return "full", "还没有全量名单"
    if snap.get("full_next"):
        return "full", "上一晚按名单抓连着失败，口令可能过期了"
    full_at = _parse_ts(snap.get("full_at"))
    if full_at is None or now - full_at >= timedelta(days=FULL_MAX_DAYS):
        return "full", f"上次全量超过 {FULL_MAX_DAYS} 天"
    weekday = _env_int("LWA_FAV_FULL_WEEKDAY", FULL_WEEKDAY_DEFAULT)
    if 0 <= weekday <= 6 and now.weekday() == weekday and full_at.date() != now.date():
        return "full", "每周一次的全量"
    return "incremental", ""


def known_ids() -> set[str]:
    """读取服务判「读到已知处」用的已知 id：全量名单 + 已在库的 + 回收站里（屏蔽同步）的。"""
    ids = {str(x.get("note_id")) for x in load_snapshot().get("items") or [] if x.get("note_id")}
    try:
        from ... import index as index_mod
        conn = index_mod.connect()
        try:
            ids.update(str(r[0]) for r in conn.execute("SELECT source_id FROM tombstones WHERE source = ?", (xhs.SOURCE,)))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - 读不到回收站只是少几个已知 id
        pass
    try:
        from ... import storage
        root = storage.archive_root() / xhs.SOURCE
        if root.is_dir():
            ids.update(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        pass
    return {i for i in ids if i}


def merge_with_snapshot(items: list[dict[str, Any]], snap: dict[str, Any]) -> list[dict[str, Any]]:
    """增量读到的最新一段 + 名单里其余的（名单顺序，标 _src=snapshot：口令是名单里的）。"""
    seen = {str(x.get("note_id")) for x in items if x.get("note_id")}
    rest = [{**x, "_src": "snapshot"} for x in snap.get("items") or []
            if x.get("note_id") and str(x.get("note_id")) not in seen]
    return [*items, *rest]


def _remember_list(items: list[dict[str, Any]], *, full: bool) -> None:
    """全量读全：名单整份换掉（full_at = 现在）；增量 / 一截：读到的合进名单最前面，其余原样，full_at 不动。"""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    if full:
        _save_snapshot({"schema_version": 1, "full_at": now, "at": now, "items": [_slim(x) for x in items]})
        return
    snap = load_snapshot()
    if not snap.get("items"):
        return  # 没有全量名单时，一截不当名单
    merged = [_slim({k: v for k, v in x.items() if k != "_src"}) for x in merge_with_snapshot(items, snap)]
    _save_snapshot({**snap, "at": now, "items": merged})


def mark_full_next(why: str) -> None:
    snap = load_snapshot()
    if snap.get("items"):
        _save_snapshot({**snap, "full_next": why[:120]})


class FavoritesSoftStop(RuntimeError):
    """读收藏这次先停（不熔断、不要人处理）：带 .code（HIDDEN_WIDGET / FAV_TAB_STUCK）。"""

    code = ""


def _post_incremental(known: set[str]) -> dict[str, Any] | None:
    """1011 增量读：POST 带已知 id。老读取服务不认这个路由（404 / 405）→ None（调用方退回 GET 全量）。"""
    try:
        expect = int(sync_state.load().get("last_favorites") or 0)
    except (TypeError, ValueError):
        expect = 0
    body = {"known_ids": sorted(known), "stop_after_known": stop_after_known()}
    if expect > 0:
        body["expect"] = expect
    try:
        return accounts.api("POST", "/api/v1/favorites", timeout=780, body=body)
    except accounts.ReaderError as exc:
        if exc.code in ("HTTP_404", "HTTP_405"):
            print("[sync-favorites] 读取组件还不认增量读，这次退回读全量", file=sys.stderr)
            return None
        raise


def fetch_favorites(*, limit: int = 50, verbose: bool = False, mode: str = "full") -> list[dict[str, Any]]:
    """经读取服务 `/api/v1/favorites` 读当前登录账号的收藏（与评论/附件同一个号、同一个会话）。

    要人处理的（未登录 / 安全验证 / 风控 / 组件未装）→ `AccountBlockedError`，带 `.code`；
    其余（服务不在 / 超时 / 限频）→ `ServiceDownError`。一律停车，不在这里重试——
    重试会撞风控验证码（2026-09-25 实测）。

    mode='incremental'（1011）：只读最新那一段，返回「读到的 + 全量名单里其余的」（积压照补）；_LAST_READ 带 incremental。
    """
    global _LAST_TOTAL, _LAST_READ
    _LAST_TOTAL = None
    _LAST_READ = {}
    try:
        accounts.ensure_reader()
        accounts.pace("读收藏")
        # 读取服务：滚动预算 420 秒、单次请求上限 10 分钟（含启动浏览器 / 关浏览器）；客户端 780 秒比它长，
        # 别把「慢」当成「号出事」
        data = None
        known = known_ids() if mode == "incremental" else set()
        if mode == "incremental" and known:
            data = _post_incremental(known)
        if data is None:
            data = accounts.api("GET", favorites_route(), timeout=780)
    except accounts.ReaderError as exc:
        if exc.code in SOFT_STOP_CODES:
            # 1008（读取组件 d7）：看不见的验证组件 / 页签点不动——只停这一次读收藏，不熔断、不是要人处理，
            # 不能当 ServiceDownError 走退出码 5（那会挡掉当晚其它碰号步骤）
            err = FavoritesSoftStop(str(exc) or SOFT_STOP_TEXT[exc.code])
            err.code = exc.code
            raise err from exc
        msg = accounts.SOLUTIONS.get(exc.code, ("", str(exc), "", ""))
        text = f"{msg[1]}：{msg[2]}" if msg[2] else str(exc)
        err = (xhs.AccountBlockedError if exc.needs_human else xhs.ServiceDownError)(text)
        err.code = exc.code
        raise err from exc
    items = data.get("items") or []
    _LAST_TOTAL = len(items)
    _LAST_READ = {key: data[key] for key in READ_FIELDS if key in data}
    incremental = bool(data.get("incremental")) or data.get("stop_reason") == "known_streak"
    if incremental:
        _LAST_READ["incremental"] = True
    global _CURRENT_ACCOUNT
    cfg = accounts.config()
    _CURRENT_ACCOUNT = {"nickname": data.get("nickname") or cfg.get("nickname") or "",
                        "user_id": cfg.get("user_id") or ""}
    if verbose:
        print(f"[sync-favorites] {data.get('nickname')} 收藏 {len(items)} 条", file=sys.stderr)
    # 读全时把「笔记 id → 最新口令」存到本地（零开页），附件补查 / 下载优先用它（批次 D · L6 P8）；
    # 1011 增量读只合并读到的那段（没读到的口令原样留着，各自按自己的时刻算新不新）
    from ... import attachments
    partial = bool(data.get("partial"))
    attachments.remember_fav_tokens(items, partial=partial, merge=incremental)
    # 1011 全量名单：读全才整份换；增量 / 一截只把读到的合进去
    try:
        last = int(sync_state.load().get("last_favorites") or 0)
    except (TypeError, ValueError):
        last = 0
    full = not incremental and not partial and bool(items) and not suspicious_reason(len(items), last, _LAST_READ)
    _remember_list(items, full=full)
    if incremental:
        snap = load_snapshot()
        items = merge_with_snapshot(items, snap)
        if verbose:
            print(f"[sync-favorites] 增量读：最新 {_LAST_TOTAL} 条（连着碰到 {stop_after_known()} 篇读过的就停），"
                  f"连同名单共 {len(items)} 条", file=sys.stderr)
    if limit and limit > 0:
        items = items[:limit]
    return items


# 新读取服务（10-04 F1）在响应里多带的读法结论；旧读取服务没有这些键
READ_FIELDS = ("partial", "stop_reason", "has_more", "expect", "scroll", "incremental")
STOP_REASON_TEXT = {
    "budget": "滚动时间用完了还在加载",
    "below_expect": "条数停在上次基准以下、页面又没说到底",
    # 1008（读取组件 d7）：stalled 取代 stuck_has_more（卡住只换第 1 级滚法，还不动就停）
    "stalled": "列表停住了、页面又说还有更多，换了一种滚法还是不动，就先停了（不再硬滚）",
    "hidden_widget": "滚动途中页面里出现了看不见的验证组件，先停了（不熔断，下次照常读）",
    "api_refused": "收藏接口回了拒绝，先停了（不再接着打接口）",
    "cancelled": "读的时候请求超时被取消",
    "tab_lost": "滚动途中页签跳走了",
    "not_scrolled": "读取服务没给出滚动结论",
    "risk": "撞到风控",
    "known_streak": "读到上次读过的地方就停了（增量读）",
}


def favorites_route() -> str:
    """读收藏的请求路径：有上次正常读到的条数就当基准带上（`?expect=N`），没有就不带（和以前一模一样）。"""
    try:
        expect = int(sync_state.load().get("last_favorites") or 0)
    except (TypeError, ValueError):
        expect = 0
    return f"/api/v1/favorites?expect={expect}" if expect > 0 else "/api/v1/favorites"


def suspicious_reason(total: int, last: int, read: dict[str, Any]) -> str:
    """这次读回的条数靠不靠得住；靠不住就返回一句给人看的原因（空串 = 可以当全量）。

    - 读取服务明说 partial（只读到一截）→ 可疑，带上判停原因；
    - 0 条永远可疑（哪怕说读到底了）；
    - 读取服务明说读到底了（stop_reason=has_more_false）→ 可信，哪怕比上次少很多（她真删了收藏）；
    - 其余（旧读取服务没这些字段 / stable）→ 老规矩：比上次少一半以上算可疑。
    - 1011 增量读（incremental / stop_reason=known_streak）：本来就只读最新一段，条数少不算可疑（0 条照样可疑）。"""
    if read.get("incremental") or read.get("stop_reason") == "known_streak":
        return "" if total > 0 else "收藏读回 0 条：多半是收藏页没加载完或被限流，这次不算同步成功；今晚不再重读收藏列表"
    if read.get("partial"):
        why = STOP_REASON_TEXT.get(str(read.get("stop_reason") or ""), str(read.get("stop_reason") or "原因没报"))
        base = f"（上次 {last} 条）" if last else ""
        return (f"收藏只读到一截：读回 {total} 条{base}，{why}。这一截里的新收藏已照常入档；"
                "今晚不再重读收藏列表（同一晚多读容易撞安全验证）")
    if total == 0:
        return "收藏读回 0 条：多半是收藏页没加载完或被限流，这次不算同步成功；今晚不再重读收藏列表"
    if read.get("stop_reason") == "has_more_false":
        return ""
    if last and total < last / 2:
        return (f"收藏只读回 {total} 条（上次 {last} 条），少了一半以上：多半只读到一截，这次不算同步成功；"
                "读到的新收藏已照常入档，今晚不再重读收藏列表")
    return ""


def _render_local(source_key: str, source_id: str, *, only_if_missing: bool) -> None:
    """本地渲染（不调模型、不识图）：只拼可见 md + agent.md。only_if_missing=True 时可见 md 在就什么都不做。"""
    from ... import render as render_mod, storage

    if only_if_missing:
        meta_path = storage.object_dir(source_key, source_id) / "meta.json"
        rel = storage.read_json(meta_path).get("visible_note") if meta_path.exists() else None
        if rel and (storage.vault_root() / rel).exists():
            return
    render_mod.render_object(source_key, source_id, verbose=False, llm=False)


def _sync_one(fav: dict[str, Any], *, origin: str, actor: str, verbose: bool, budget_left=None) -> dict[str, Any]:
    """一条收藏 → 归档条目 dict（抓取阶段：新的抓原文 + 本地渲染 + 标待 enrich；已在库的基本不动）。

    budget_left：返回「这一批还剩几秒」的函数（没有预算时 None）。剩的不多就不顺手下附件、抓详情也不再重试。
    """
    from ... import enrich as enrich_mod

    url = fav.get("url") or ""
    try:
        summary = ingest_mod.ingest_url(
            url,
            origin=origin,
            actor=actor,
            ingest_kind="favorite",
            note=None,
            verbose=verbose,
            budget_left=budget_left,
        )
    except accounts.AccountBusyError:
        raise  # 本进程的账号锁被接管了：整批停（退出 6），不当成这一篇的错
    except xhs.NeedsHumanError as exc:
        # 第 4 批：不在这里报警。整批停车后 sync_state.record 按码登记问题（账号类 NEEDS_HUMAN 推一次，
        # 服务类 TRANSIENT 下次再试），推不推由 problems.report 唯一出口判定。
        service = isinstance(exc, xhs.ServiceDownError)
        return {"item_id": None, "status": "blocked", "url": url, "error": str(exc),
                "login_account": None if service else 'xhs', "code": getattr(exc, "code", "")}
    except Exception as exc:  # noqa: BLE001 - 一条收藏挂了不该带走整批
        return {
            "item_id": None,
            "status": "error",
            "url": url,
            "error": errtext(exc),
        }

    if summary.get("note_id") and _CURRENT_ACCOUNT.get("nickname"):
        tag_account(summary["note_id"], _CURRENT_ACCOUNT)
    if summary.get('status') == 'trashed':
        print(f"[sync-favorites] {summary['item_id']} 已删除，跳过", file=sys.stderr)
        return {**summary, 'url': url}
    status = "hit" if summary.get("hit") else "new"
    source_key, source_id = xhs.SOURCE, summary["note_id"]

    render_error = None
    try:
        if status == "new":
            enrich_mod.mark_pending(source_key, source_id)
            sync_state.progress(f"《{summary.get('title') or source_id}》已存好（识图和概要之后补）")
        # 1001（A-2）：已在库的不再重渲染——以前每次同步都把全库重写一遍、还在主进程里不限时补识图
        _render_local(source_key, source_id, only_if_missing=(status == "hit"))
    except Exception as exc:  # noqa: BLE001 - 渲染失败不该吞掉已经落盘的归档
        render_error = f"渲染失败: {type(exc).__name__}: {exc}"

    blocked_code = ""
    if status == "new":  # 0927：新收藏入库就下附件（一个一个、隔几分钟）；老的缺附件交给每晚 4 点
        from ... import attachments as attachments_mod
        if budget_left is not None and budget_left() < GRAB_RESERVE_SECONDS:
            # 1001：时间不多了，下附件（每个 1.5–4 分钟间隔、最长 4 分钟下载、最多 3 次）会拖过预算
            sync_state.progress(f"《{summary.get('title') or source_id}》时间不多了，附件留给 4 点补下")
        else:
            sync_state.progress(f"《{summary.get('title') or source_id}》查附件 / 下附件中")
            blocked_code = attachments_mod.grab_after_ingest(source_key, source_id, budget_left=budget_left) or ""

    try:
        payload = read_mod.item_payload(source_key, source_id, status=status)
    except Exception as exc:  # noqa: BLE001
        return {
            "item_id": summary.get("item_id"),
            "status": "error",
            "url": url,
            "error": f"读归档失败: {type(exc).__name__}: {exc}",
        }
    payload["_source_id"] = source_id
    if blocked_code:
        payload["_blocked_code"] = blocked_code  # 这篇存好了，但下附件时号出事：整批停车
    if render_error:
        payload["error"] = render_error
    return payload


def _clock() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _rest_wait() -> float:
    """每次联网抓取后要歇多久（成功失败都算），像人一样慢慢看。"""
    lo, hi = accounts._gap_range("LWA_FETCH_REST", "60,180")
    return random.uniform(lo, hi)


def _rest(wait: float, verbose: bool = True) -> None:
    if wait > 0:
        if verbose:
            print(f"[sync-favorites] 歇 {wait:.0f} 秒再看下一篇", file=sys.stderr)
        _sleep(wait)


def _library_ids() -> set[str]:
    """库里已有的（对象目录）+ 回收站里的 note_id（口径在 fav_counts，进度条 / 同步记录同一份）。"""
    from . import fav_counts
    return fav_counts.library_ids()


class _Live:
    """1011：同步的结构化进度 → sync-status.json 的 `live`（插件状态栏 / 目录页画细进度条，文件监听实时刷新）。

    以前进度句是「第 594/1246 条收藏是新的」：594 是在收藏列表里的位置，看着像进度其实不是。现在分开记：
    今天新抓了几篇 / 每天上限（sync-quota + dailyNewLimit）、这一趟新抓几篇、库里有几篇 / 收藏一共几篇（还差几篇）、
    正在抓哪篇、在歇（几秒后抓下一篇）、按眼下的速度今天的额度大约几点抓完。
    写入节流：只在换阶段时写（读列表 / 开抓一篇 / 存好一篇 / 开始歇 / 收尾），歇着的倒计时由页面按 next_at 自己走，
    已在库的那些不写。写失败不影响同步（sync_state.progress 自己吞错）。"""

    PHASE_TEXT = {"listing": "读收藏列表", "fetching": "抓取中", "resting": "歇着", "finishing": "收尾"}

    def __init__(self, quota: "_Quota", deadline: float | None = None):
        self.quota = quota
        self.deadline = deadline
        self.total = None          # 收藏一共几篇（全量名单口径）
        self.archived = None       # 其中库里已有（含回收站）几篇
        self.remaining = None      # 还差几篇（待抓积压）
        self.run_new = 0
        self.started = None        # 这一趟第一篇开抓的时刻（monotonic），估速度用
        self.title = ""

    def count(self, pool: list[dict[str, Any]]) -> None:
        # 1011：口径只在 fav_counts 一处（同步记录第一排 / setup backfill 用同一个函数），界面统一说「收藏已入库 A/T」
        try:
            from . import fav_counts
            c = fav_counts.counts([f.get("note_id") for f in pool if f.get("note_id")], have=_library_ids())
            self.total, self.archived, self.remaining = c["favorites_total"], c["archived"], c["remaining"]
        except Exception:  # noqa: BLE001 - 数不出来就不显示库里那一行
            self.total = self.archived = self.remaining = None

    def stored(self) -> None:
        self.run_new += 1
        if self.archived is not None:
            self.archived += 1
            self.remaining = max(0, (self.remaining or 0) - 1)

    def today_label(self, n: int) -> str:
        lim = self.quota.limit
        return f"今天第 {n}/{lim} 篇" if lim > 0 else f"今天第 {n} 篇"

    def _per_item(self) -> float:
        if self.run_new and self.started is not None:
            return max(30.0, (_clock() - self.started) / self.run_new)
        lo, hi = accounts._gap_range("LWA_FETCH_REST", "60,180")
        return (lo + hi) / 2 + 60   # 还没抓完一篇：歇的平均 + 抓一篇的大概耗时

    def _eta(self) -> str | None:
        lim = self.quota.limit
        left = self.remaining
        if lim > 0:
            room = max(0, lim - self.quota.count)
            left = room if left is None else min(left, room)
        if not left:
            return None
        secs = left * self._per_item()
        if self.deadline is not None:
            secs = min(secs, max(0.0, self.deadline - _clock()))
        return (datetime.now().astimezone() + timedelta(seconds=secs)).isoformat(timespec="seconds")

    def push(self, phase: str, text: str, *, rest_s: float | None = None) -> None:
        live: dict[str, Any] = {
            "phase": phase, "phase_text": self.PHASE_TEXT.get(phase, phase),
            "today_new": self.quota.count, "daily_limit": self.quota.limit, "this_run_new": self.run_new,
            "archived": self.archived, "favorites_total": self.total, "remaining": self.remaining,
            "title": self.title, "eta_at": self._eta(),
        }
        if phase == "resting" and rest_s:
            live["phase_text"] = f"歇 {rest_s:.0f} 秒"
            live["rest_s"] = round(rest_s)
            live["next_at"] = (datetime.now().astimezone() + timedelta(seconds=rest_s)).isoformat(timespec="seconds")
        sync_state.progress(text, live=live)


def _log_entry(entry: dict[str, Any], fav: dict[str, Any], in_library: bool, known_bad: bool) -> None:
    """10-03 同步记录：这一篇这次怎样（新收 = 正文 ✅；抓不到 / 渲染失败 = 正文 ❌；号出事 = 步骤级报错）。"""
    status = entry.get("status")
    try:
        if status == "new":
            synclog.count_new(1)
            synclog.note("note", entry.get("item_id"), not entry.get("error"), title=entry.get("title"),
                         reason=entry.get("error") or "")
        elif status == "error" and not in_library and not known_bad:
            nid = fav.get("note_id")
            synclog.note("note", entry.get("item_id") or (domain.item_id(xhs.SOURCE, nid) if nid else None), False,
                         title=fav.get("title") or entry.get("title"), reason=entry.get("error") or "没抓到",
                         url=entry.get("url") or fav.get("url"))
        elif status == "blocked":
            synclog.error("sync-favorites", entry.get("error") or "号要处理，已停车", entry.get("code") or "")
        # 1011：每篇当场写进同步记录（以前攒到命令结束：进程被结束那趟记成「没有新内容」）
        synclog.flush_progress()
    except Exception as exc:  # noqa: BLE001 - 记录出错不挡同步
        print(f"[synclog] {type(exc).__name__}: {exc}", file=sys.stderr)


def sync_favorites(
    *,
    limit: int = 50,
    origin: str = "cli",
    actor: str = "human",
    verbose: bool = False,
    extract: bool = False,
    deadline: float | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    """读收藏 → 逐条 ingest（去重）→ `{"favorites": N, "synced": M, "items": [...]}`。

    这是**抓取阶段**（用号）。`extract` 在这里不用——识图/概要由 `run` 在放掉账号锁之后交给 enrich。
    `deadline` 是 time.monotonic() 的时刻：到了就不再开新的抓取，剩下的记 deferred。
    mode（1011）：auto = 平时增量、每周 / 该全量时全量（read_mode）；full = 读全量；snapshot = 不读列表，只按全量名单补抓。
    """
    global _LAST_TOTAL, _LAST_READ, _CURRENT_ACCOUNT
    _LAST_TOTAL = None
    _LAST_READ = {}
    read_label = ""
    if mode == "snapshot":
        snap = load_snapshot()
        full_at = _parse_ts(snap.get("full_at"))
        if not snap.get("items") or full_at is None or \
                datetime.now().astimezone() - full_at >= timedelta(days=FULL_MAX_DAYS):
            note = "还没有新近的收藏名单（7 天内读过全量才有），这次不按名单补抓"
            print(f"[sync-favorites] {note}", file=sys.stderr)
            return {"favorites": 0, "synced": 0, "items": [], "read_mode": "snapshot", "note": note}
        cfg = accounts.config()
        _CURRENT_ACCOUNT = {"nickname": "", "user_id": cfg.get("user_id") or ""}
        _CURRENT_ACCOUNT["nickname"] = cfg.get("sync_account") or cfg.get("nickname") or ""
        favs = [{**x, "_src": "snapshot"} for x in snap["items"] if x.get("note_id")]
        if limit and limit > 0:
            favs = favs[:limit]
        read_label = "snapshot"
        print(f"[sync-favorites] 不读收藏列表，按名单（{full_at:%m-%d} 全量）补抓：共 {len(favs)} 条", file=sys.stderr)
    else:
        rmode, why = read_mode(force_full=(mode == "full"))
        read_label = rmode
        print(f"[sync-favorites] 这次读收藏：{'全量' if rmode == 'full' else '增量（只读最新一段）'}"
              + (f"（{why}）" if why else ""), file=sys.stderr)
    quota = _Quota()
    # 1015 设置页「定时同步 → 每次同步最多收几篇」：0 = 不限（只受每天上限管）
    from ...ai_config import per_run_limit, sync_options as _sync_opts
    per_run = per_run_limit(_sync_opts().get("perRunLimit"))
    run_new = 0
    live = _Live(quota, deadline)
    if read_label != "snapshot":
        live.push("listing", "读收藏列表")
    try:
        if read_label == "full":
            favs = fetch_favorites(limit=limit, verbose=verbose)
        elif read_label == "incremental":
            favs = fetch_favorites(limit=limit, verbose=verbose, mode="incremental")
    except FavoritesSoftStop as exc:
        code = getattr(exc, "code", "") or "HIDDEN_WIDGET"
        text = f"{SOFT_STOP_TEXT.get(code, '')}（读取服务：{exc}）" if str(exc) and str(exc) != SOFT_STOP_TEXT.get(code) \
            else SOFT_STOP_TEXT.get(code, str(exc))
        synclog.error("sync-favorites", f"读收藏这次先停了：{text}", code)
        # 不进 items（不是 blocked → 不走退出码 5）；suspicious 让它退出 3、不顶基准，suspicious_code 让问题记录登记成这个码
        return {"favorites": 0, "synced": 0, "code": code, "suspicious": text, "suspicious_code": code, "items": []}
    except xhs.NeedsHumanError as exc:
        service = isinstance(exc, xhs.ServiceDownError)
        code = getattr(exc, "code", "")
        synclog.error("sync-favorites", ("刚同步过（收藏每 10 分钟最多读一次），这次跳过" if code == "RATE_LIMITED"
                                         else f"读收藏没成：{exc}"), code)
        # 问题登记在 sync_state.record（_run 拿到这个 payload 就记）：账号类 NEEDS_HUMAN；服务类（含读收藏
        # FAVORITES_FAILED / 超时）TRANSIENT；RATE_LIMITED 只是「刚同步过」，不登记
        return {
            "favorites": 0,
            "synced": 0,
            "login_account": None if service else "xhs",
            "code": code,
            "items": [{"item_id": None, "status": "blocked", "url": None, "error": str(exc), "code": code}],
        }

    # 1001（A-4）/ 10-04 F1：只读到一截 / 0 条 / 比上次少一半以上 —— 不能当「同步完成」，但读到的照常处理。
    total = _LAST_TOTAL if _LAST_TOTAL is not None else len(favs)
    last = int(sync_state.load().get("last_favorites") or 0)
    read = dict(_LAST_READ)
    suspicious = "" if mode == "snapshot" else suspicious_reason(total, last, read)
    # 可疑 = 这次不算同步成功：sync_state.record 记 TRANSIENT.FAVORITES_SUSPICIOUS（一条，原因一句），
    # 基准不被这次顶掉（sync_state._update_baseline）；退出码 3 让夜跑今晚不再重读

    # 0927 认号：收藏同步钉在一个号上。登错号（如测试号）时整批不入库、目录页亮「!」，
    # 免得把别的号的收藏悄悄灌进库（0926–0927 测试号登着，夜跑收了它 33 篇）。换号走「更换账号」。
    current = _CURRENT_ACCOUNT.get("nickname") or ""
    pinned = accounts.config().get("sync_account") or ""
    if current and not pinned:
        accounts.save({"sync_account": current})
    elif current and pinned and current != pinned:
        msg = f"现在登录的是「{current}」，不是平时同步的「{pinned}」：没有同步。要换成这个号，请在账号面板点「更换账号」"
        synclog.error("sync-favorites", msg, "WRONG_ACCOUNT")
        # 登错号 = NEEDS_HUMAN.WRONG_ACCOUNT（sync_state.record 登记在 login，推一次）
        return {"favorites": len(favs), "synced": 0, "login_account": "xhs", "code": "WRONG_ACCOUNT",
                "items": [{"item_id": None, "status": "blocked", "url": None, "error": msg, "code": "WRONG_ACCOUNT"}]}

    failures = _Failures()
    # 抓失败过的（已删 / 仅作者可见）排到最后，别让它们每晚先占掉时间
    favs = sorted(favs, key=lambda f: failures.known(f.get("note_id")))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    # 进度条「库里 650/1246」：增量那晚读到的只是最新一段，总数按「这段 + 全量名单其余的」数
    live.count(favs if read_label != "incremental" else merge_with_snapshot(favs, load_snapshot()))
    deferred_quota = deferred_budget = skipped_failing = held_known_bad = 0
    consecutive = 0
    known_streak = 0
    fail_srcs: list[str] = []   # 1011：连着失败的那几篇是不是按名单（旧口令）抓的
    fetched_any = False
    fetched_new: list[str] = []
    stop_code = ""
    budget_left = (lambda: deadline - _clock()) if deadline is not None else None
    for i, fav in enumerate(favs):
        in_library = _already_archived(fav)
        if deadline is not None and _clock() >= deadline:
            if not in_library:
                deferred_budget += 1
            continue
        note_id = fav.get("note_id")
        known_bad = False
        if not in_library:
            if failures.skip(note_id):
                skipped_failing += 1
                continue
            known_bad = failures.known(note_id)
            if known_bad and known_streak >= MAX_KNOWN_BAD_STREAK:
                held_known_bad += 1  # 已知坏篇今晚已经连着失败 3 篇了：余下的不再开页
                continue
            if quota.exhausted() or (per_run and run_new >= per_run):
                deferred_quota += 1   # 1015：每次同步篇数到了也算「额度到了」，下次接着收
                continue
            wait = _rest_wait() if fetched_any else 0.0
            if deadline is not None and deadline - _clock() - wait < FETCH_RESERVE_SECONDS:
                deferred_budget += 1  # 剩下的时间装不下这一篇的最坏耗时：不开了，明天继续
                continue
            nth = live.today_label(quota.count + 1)
            if wait > 0:
                live.push("resting", f"歇 {wait:.0f} 秒，接着抓{nth}", rest_s=wait)
            _rest(wait, verbose=True)
            live.title = str(fav.get("title") or "").strip() or "（没标题的一篇）"
            if live.started is None:
                live.started = _clock()
            live.push("fetching", f"{nth} · 《{live.title}》")
        entry = _sync_one(fav, origin=origin, actor=actor, verbose=verbose, budget_left=budget_left)
        source_id = entry.pop("_source_id", None)
        attachment_block = entry.pop("_blocked_code", "")
        _log_entry(entry, fav, in_library, known_bad)
        if not in_library:
            fetched_any = True
            status = entry.get("status")
            if status == "new":
                quota.add()
                run_new += 1
                live.title = str(entry.get("title") or live.title)
                live.stored()
                live.push("fetching", f"{live.today_label(quota.count)}已存好 · 《{live.title}》")
                failures.clear(note_id)
                consecutive = 0
                known_streak = 0
                if source_id:
                    fetched_new.append(source_id)
            elif status == "error":
                failures.add(note_id, entry.get("error") or "")
                if known_bad:
                    entry["known_bad"] = True  # 以前就抓不到的：照实列出，但不算这次同步「出错」
                    # 已知坏篇（删了/私密）再失败不算「服务出事」的信号，不报警；但连着 3 篇就收手
                    known_streak += 1
                    if known_streak == MAX_KNOWN_BAD_STREAK:
                        print(f"[sync-favorites] 以前抓失败过的收藏连着 {known_streak} 篇还是抓不到，"
                              "余下的今晚不再试", file=sys.stderr)
                else:
                    consecutive += 1
                    fail_srcs.append(fav.get("_src") or "")
            elif status != "blocked":
                consecutive = 0
                known_streak = 0
        item_id = entry.get("item_id")
        if item_id:
            if item_id in seen:
                continue
            seen.add(item_id)
        items.append(entry)
        if attachment_block:
            items.append({"item_id": None, "status": "blocked", "url": entry.get("url"), "code": attachment_block,
                          "login_account": "xhs", "error": f"下附件时账号要处理（{attachment_block}），已停车"})
        if entry.get("status") == "blocked" or attachment_block:
            break  # 号/服务出事，后面照抓也只是接着失败
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            stop_code = "TOO_MANY_FAILURES"
            recent = [x.get("error") or "" for x in items if x.get("status") == "error"][-MAX_CONSECUTIVE_FAILURES:]
            # 连着几篇抓不到但没撞风控 / 掉登录（那些是 blocked，上面已经停车）：TRANSIENT.TOO_MANY_FAILURES，
            # 只记不推，下次同步再来；连续 3 天都这样才升级推一次（sync_state.record 登记）
            print(f"[sync-favorites] 连续 {consecutive} 篇没抓到，先停下。最近的原因：\n"
                  + "\n".join(e[:160] for e in recent), file=sys.stderr)
            if fail_srcs[-MAX_CONSECUTIVE_FAILURES:] == ["snapshot"] * MAX_CONSECUTIVE_FAILURES:
                # 1011：连着失败的都是按名单里的旧口令抓的——口令可能过期了：下一次读收藏读全量（顺带刷新口令）
                mark_full_next(f"按名单抓连着 {consecutive} 篇失败，口令可能过期了")
            break
    failures.save()
    if fetched_any:
        live.title = ""
        live.push("finishing", "收尾")
    if suspicious:
        synclog.error("sync-favorites", suspicious, "FAVORITES_SUSPICIOUS")
    if stop_code:
        synclog.error("sync-favorites", f"连着 {consecutive} 篇没抓到，先停下（下次同步再来）", stop_code)
    out: dict[str, Any] = {"favorites": len(favs), "synced": len(items), "items": items, "read_mode": read_label}
    if total and mode != "snapshot" and not read.get("incremental"):
        out["favorites_total"] = total   # 只有读全量才拿条数当总数 / 基准（增量、按名单补抓都不是总数）
    elif total and mode != "snapshot":
        out["favorites_read"] = total
    out.update(read)  # partial / stop_reason / has_more / expect / scroll：如实带上，旧读取服务没有就不带
    if suspicious:
        out["suspicious"] = suspicious
        out["code"] = "FAVORITES_SUSPICIOUS"
        out["no_reread"] = True
    if stop_code:
        out["code"] = stop_code
    if deferred_quota or deferred_budget:
        out["deferred"] = deferred_quota + deferred_budget
        out["deferred_reason"] = ("budget" if deferred_budget
                                  else "run_limit" if per_run and run_new >= per_run and not quota.exhausted() else "daily_limit")
        out["daily_limit"] = quota.limit
        if per_run:
            out["run_limit"] = per_run
    if skipped_failing or held_known_bad:
        out["skipped_failing"] = skipped_failing + held_known_bad
    if held_known_bad:
        out["held_known_bad"] = held_known_bad
    if fetched_new:
        out["fetched_new"] = fetched_new
    return out


_CURRENT_ACCOUNT: dict[str, str] = {}
_LAST_TOTAL: int | None = None
_LAST_READ: dict[str, Any] = {}


def tag_account(note_id: str, account: dict[str, str], *, seen_at: str | None = None) -> bool:
    """在对象 meta.json 的 favorited_by 里记下「这篇被哪个号收藏」（去重；失败不影响同步）。"""
    from ... import storage
    key = domain.account_key(account)
    if not key:
        return False
    path = storage.object_dir(xhs.SOURCE, note_id) / "meta.json"
    item_id = domain.item_id(xhs.SOURCE, note_id)
    added = []

    def add(meta):
        tags = [a for a in (meta.get("favorited_by") or []) if isinstance(a, dict)]
        if any(domain.account_key(a) == key for a in tags):
            return
        tags.append({"nickname": account.get("nickname", ""), "user_id": account.get("user_id", ""),
                     "first_seen": seen_at or datetime.now().astimezone().isoformat(timespec="seconds")})
        meta["favorited_by"] = tags
        added.append(True)

    try:
        # 1024：只改 favorited_by，单篇锁里重读再写
        storage.update_json(path, add, lock_name=storage.obj_lock_name(item_id))
    except FileNotFoundError:
        return False
    except (OSError, ValueError, storage.LockBusy) as exc:
        # 1024 返修（复审 meta 低）：这篇被 render / 重抓占着超过 60 秒等情况——这次漏记收藏账号，照实打一行
        print(f"[收藏账号] {item_id} 这次没记上（{errtext(exc)}），下次同步再记", file=sys.stderr)
        return False
    if not added:
        return False
    from ...catalog import mark_dirty  # 1023：收藏账号决定「来源」（ARCH-AUDIT 第 1 批）
    mark_dirty("收藏账号")
    return True


class _Quota:
    """每天最多新抓几篇（插件 data.json 的 sync.dailyNewLimit，缺省 50）。计数存 _archive/sync-quota.json，
    插件白天点的同步和夜跑共用这一个额度。"""

    def __init__(self):
        from datetime import date
        from ...ai_config import sync_options
        from ... import storage
        # 第 5 批 4.1：sync_options 已规整——0 = 不限，空 / 乱填 = 默认 50（以前 `or 0` 让空值变成不限）
        self.limit = int(sync_options()["dailyNewLimit"])
        self.path = storage.archive_root() / "sync-quota.json"
        self.today = date.today().isoformat()
        try:
            data = storage.read_json(self.path)
        except (OSError, ValueError):
            data = {}
        self.count = int(data.get("new", 0)) if data.get("date") == self.today else 0

    def exhausted(self) -> bool:
        return self.limit > 0 and self.count >= self.limit

    def add(self) -> None:
        from ... import storage
        self.count += 1
        try:
            # CONVENTIONS §6.4：插件白天的同步和夜跑共用这一个计数，读改写在锁里（以文件里的数为准再 +1）
            with storage.file_lock("sync-quota", wait_s=10):
                try:
                    data = storage.read_json(self.path)
                except (OSError, ValueError):
                    data = {}
                if isinstance(data, dict) and data.get("date") == self.today:
                    self.count = max(self.count, int(data.get("new", 0)) + 1)
                storage.write_json(self.path, {"date": self.today, "new": self.count})
        except (OSError, ValueError, storage.LockBusy):
            pass


class _Failures:
    """抓失败过的收藏：`_archive/sync-failures.json` = {note_id: {count, last, error}}。"""

    def __init__(self):
        from ... import storage
        self.path = storage.archive_root() / "sync-failures.json"
        try:
            data = storage.read_json(self.path)
        except (OSError, ValueError):
            data = {}
        self.data: dict[str, dict[str, Any]] = data if isinstance(data, dict) else {}
        self.dirty = False

    def known(self, note_id) -> bool:
        return bool(note_id) and note_id in self.data

    def skip(self, note_id) -> bool:
        rec = self.data.get(note_id or "")
        if not rec or int(rec.get("count") or 0) < FAILED_NOTE_SKIP_AFTER:
            return False
        try:
            last = datetime.fromisoformat(str(rec.get("last")))
        except ValueError:
            return False
        return datetime.now().astimezone() - last < timedelta(days=FAILED_NOTE_RETRY_DAYS)

    def add(self, note_id, error: str) -> None:
        if not note_id:
            return
        rec = self.data.get(note_id) or {}
        self.data[note_id] = {"count": int(rec.get("count") or 0) + 1, "error": error[:200],
                              "last": datetime.now().astimezone().isoformat(timespec="seconds")}
        self.dirty = True

    def clear(self, note_id) -> None:
        if note_id and self.data.pop(note_id, None) is not None:
            self.dirty = True

    def save(self) -> None:
        from ... import storage
        if not self.dirty:
            return
        try:
            storage.write_json(self.path, self.data)
        except OSError:
            pass


def _already_archived(fav: dict[str, Any]) -> bool:
    """在库里（或在回收站里、已屏蔽同步）= 不用联网。名单来自读取组件，没有 note_id 的条目当「不在库」交给后面报错。"""
    from ... import index as index_mod
    nid = fav.get("note_id")
    if not nid:
        return False
    conn = index_mod.connect()
    try:
        if index_mod.get_object(conn, domain.item_id(xhs.SOURCE, nid)) is not None:
            return True
        return conn.execute("SELECT 1 FROM tombstones WHERE source = ? AND source_id = ?",
                            (xhs.SOURCE, fav.get("note_id"))).fetchone() is not None
    finally:
        conn.close()


def _exit_code(payload: dict[str, Any]) -> int:
    items = payload.get("items") or []
    blocked = [x for x in items if x.get("status") == "blocked"]
    if blocked and all(x.get("code") == "RATE_LIMITED" for x in blocked):
        print("sync-favorites: 刚同步过（收藏每 10 分钟最多读一次），这次跳过，稍后再试", file=sys.stderr)
        return EXIT_OK
    if blocked and all(x.get("code") == "XHS_RATE_LIMITED" for x in blocked):
        # 1015：限频冷却中——照旧退出 5（夜跑据此今晚不再开页、交给 captcha-recover 等冷却到点），但不是要人处理
        print("sync-favorites: 小红书限频冷却中（不是封号，不用处理），这次没开页；冷却到点自动再试", file=sys.stderr)
        return EXIT_NEEDS_HUMAN
    if blocked:
        print("sync-favorites: 要人处理（登录态/风控/服务挂了），已停车并报警", file=sys.stderr)
        return EXIT_NEEDS_HUMAN
    if payload.get("suspicious"):
        # 10-04 F1：只读到一截 / 条数可疑 = 退出 3（不是 1）：夜跑「exit 1 等 25 分钟再读一次」不会触发，
        # 也不另登记「sync-favorites 步骤出错」——原因已经在 sync.favorites 那一条里（同一件事只报一条）
        print(f"sync-favorites: {payload['suspicious']}", file=sys.stderr)
        return EXIT_PARTIAL
    if payload.get("code") == "TOO_MANY_FAILURES":
        print("sync-favorites: 连续几篇都没抓到，已停批并报警", file=sys.stderr)
        return EXIT_ERROR
    # 已知坏篇（以前就抓不到：已删 / 仅作者可见）再失败不算出错，不然每晚都报一次「同步出错」
    if any(item.get("status") == "error" and not item.get("known_bad") for item in items):
        print("sync-favorites: 有收藏没归档成功，详见 JSON 里的 error 字段", file=sys.stderr)
        return EXIT_ERROR
    if payload.get("deferred_reason") == "budget":
        print(f"sync-favorites: 今天先到这，剩 {payload.get('deferred')} 篇明天继续", file=sys.stderr)
    return EXIT_OK


def _run(args) -> tuple[int, dict[str, Any]]:
    from ... import enrich as enrich_mod

    budget = float(getattr(args, "budget_min", 0) or 0)
    deadline = _clock() + budget * 60 if budget > 0 else None
    wait_s = float(getattr(args, "wait_lock_min", 10) or 0) * 60
    # 10-03 同步记录：这次同步开一行（夜跑子进程带着 LINK_BRAIN_SYNC_RUN 就并进夜跑那行；插件「立即同步」带
    # LINK_BRAIN_SYNC_TRIGGER=manual → 命令结束就收尾；仓外夜跑脚本什么都不带 → 等夜跑最后一步收尾）
    if not os.environ.get(synclog.ENV_RUN):
        synclog.begin(own=bool(os.environ.get(synclog.ENV_TRIGGER)))

    # ① 熔断中：一页都不开（B-3）
    try:
        accounts.check_risk_hold()
    except accounts.ReaderError as exc:
        hcode = accounts.RATE_LIMIT_CODE if exc.code == accounts.RATE_LIMIT_CODE else "RISK_HOLD"
        if hcode == accounts.RATE_LIMIT_CODE:
            text = exc.detail or accounts.SOLUTIONS[hcode][1]  # 1015：限频冷却中，一页不开，不要人处理
        else:
            text = f"{accounts.SOLUTIONS['RISK_HOLD'][1]}（{exc.detail}）：{accounts.SOLUTIONS['RISK_HOLD'][2]}"
        payload = {"favorites": 0, "synced": 0, "login_account": "xhs", "code": hcode,
                   "items": [{"item_id": None, "status": "blocked", "url": None, "error": text, "code": hcode}]}
        synclog.error("sync-favorites", text, hcode)
        if not sync_state.running_elsewhere():
            sync_state.record("finished", payload=payload)  # 顺带登记 NEEDS_HUMAN.RISK_HOLD（login）
        else:
            from ... import problems
            problems.report_blocked("sync.favorites", hcode, text)
        return _exit_code(payload), payload

    # ② 账号锁（B-6）：拿不到就退出 6，不碰状态文件（那是正在跑的那一趟的）
    try:
        with accounts.account_session("sync-favorites", wait_s=wait_s):
            sync_state.record("running", message="正在同步收藏")
            synclog.fetch_started()   # 1011：记下抓取进程，被结束了同步记录认得出「被中断」
            try:
                payload = sync_favorites(
                    limit=getattr(args, "limit", 50),
                    origin=getattr(args, "origin", "cli"),
                    actor=getattr(args, "actor", "human"),
                    verbose=getattr(args, "verbose", False),
                    deadline=deadline,
                    mode=("snapshot" if getattr(args, "from_snapshot", False)
                          else "full" if getattr(args, "full", False) else "auto"),
                )
            except Exception:
                sync_state.record("failed", message="同步未完成，请打开账号 / 同步查看详情并重试")
                raise
    except accounts.AccountBusyError as exc:
        print(f"sync-favorites: {exc}", file=sys.stderr)
        synclog.error("sync-favorites", f"号被别的任务占着，这次没同步：{exc}", "ACCOUNT_BUSY")
        return EXIT_ACCOUNT_BUSY, {"favorites": 0, "synced": 0, "items": [], "code": "ACCOUNT_BUSY",
                                   "error": str(exc)}

    # ③ 抓取阶段的结果先落状态：号已放掉，同步就算结束了（不然补概要期间状态一直是 running + 活 pid，
    #    跨过 04:00 时夜跑开头会当成「上一趟还在跑」整晚跳过，连不碰号的步骤都不做）
    sync_state.record("finished", payload=payload)

    # ④ --extract：对本次新收的补识图 + 概要（不碰号，受剩余预算约束；没给预算时最多 30 分钟，剩下的夜里补）
    new = payload.get("fetched_new") or []
    if getattr(args, "extract", False) and new:
        left = (deadline - _clock()) if deadline is not None else ENRICH_DEFAULT_BUDGET_MIN * 60
        sync_state.progress(f"抓取完成，给本次新收的 {len(new)} 篇补识图和概要")
        try:
            result = enrich_mod.enrich_items([(xhs.SOURCE, sid) for sid in new], llm=True,
                                             deadline=time.monotonic() + max(0.0, left))
        except Exception as exc:  # noqa: BLE001 - 补概要出错不该把整次同步记成失败
            result = {"error": errtext(exc)}
        payload["enrich"] = result
    return _exit_code(payload), payload


def run(args) -> int:
    with contextlib.redirect_stdout(sys.stderr):  # stdout 只留最后那一个 JSON
        try:
            code, payload = _run(args)
        finally:
            # 1023：同步完成、失败、中途抛错都让目录跟上（以前只有夜跑 / 手动刷新才重建 → 「今日新增」筛不到）
            from ...catalog import ensure_fresh
            ensure_fresh(wait_s=60)
    items = payload.get('items') or []
    new = len(payload.get('fetched_new') or [])
    blocked = [item for item in items if item.get('status') == 'blocked']
    if blocked and all(item.get('code') == 'RATE_LIMITED' for item in blocked):
        message = '刚同步过（收藏每 10 分钟最多读一次），这次跳过'
    elif code == EXIT_PARTIAL:
        message = f'这次只读到一部分收藏：读到的已入库（新收 {new} 篇），原因见同步记录'
    elif code == EXIT_NEEDS_HUMAN:
        message = (blocked[0].get('error') if blocked else payload.get('error')) or '账号需要处理，见问题列表'
    elif code == EXIT_ACCOUNT_BUSY:
        message = '正在执行其他账号任务，完成后再点，或在底部状态栏停止'
    elif code == EXIT_ERROR:
        failed = sum(item.get('status') == 'error' for item in items)
        message = f'{failed} 篇没归档成功，其余已入库（原因见同步记录）'
    else:
        message = f'同步完成：新收 {new} 篇' if new else '同步完成：没有新收藏'
        if payload.get('deferred'):
            message += f'，还剩 {payload["deferred"]} 篇明天继续'
    payload.update(ok=code in (EXIT_OK, EXIT_PARTIAL), message=message)
    payload.setdefault('code', '')
    read_mod.dump_json(payload)
    return code
