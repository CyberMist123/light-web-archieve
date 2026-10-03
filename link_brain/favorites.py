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
- 每天新抓上限读插件 data.json 的 sync.dailyNewLimit（缺省 50），插件和夜跑共用；
- `--budget-min N` 到点优雅收尾；`--extract` = 抓完后对本次新收的跑 enrich（不碰号、受剩余预算约束）；
- 收藏读回 0 条或比上次少一半以上：照常处理读到的，但状态标失败并报警。
"""

from __future__ import annotations

import contextlib
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from . import sync_state
from . import ingest as ingest_mod, read as read_mod
from .adapters import xiaohongshu as xhs
from . import accounts

EXIT_OK = 0
EXIT_ERROR = 1
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


def fetch_favorites(*, limit: int = 50, verbose: bool = False) -> list[dict[str, Any]]:
    """经读取服务 `/api/v1/favorites` 读当前登录账号的收藏（与评论/附件同一个号、同一个会话）。

    要人处理的（未登录 / 安全验证 / 风控 / 组件未装）→ `AccountBlockedError`，带 `.code`；
    其余（服务不在 / 超时 / 限频）→ `ServiceDownError`。一律停车，不在这里重试——
    重试会撞风控验证码（2026-09-25 实测）。
    """
    global _LAST_TOTAL
    _LAST_TOTAL = None
    try:
        accounts.ensure_reader()
        accounts.pace("读收藏")
        # 读取服务最坏约 480 秒（启动 ≤90 + 读 6 分钟 + 关浏览器 ≤30），客户端要比它长，别把「慢」当成「号出事」
        data = accounts.api("GET", "/api/v1/favorites", timeout=540)
    except accounts.ReaderError as exc:
        msg = accounts.SOLUTIONS.get(exc.code, ("", str(exc), "", ""))
        text = f"{msg[1]}：{msg[2]}" if msg[2] else str(exc)
        err = (xhs.AccountBlockedError if exc.needs_human else xhs.ServiceDownError)(text)
        err.code = exc.code
        raise err from exc
    items = data.get("items") or []
    _LAST_TOTAL = len(items)
    global _CURRENT_ACCOUNT
    cfg = accounts.config()
    _CURRENT_ACCOUNT = {"nickname": data.get("nickname") or cfg.get("nickname") or "",
                        "user_id": cfg.get("user_id") or ""}
    if verbose:
        print(f"[sync-favorites] {data.get('nickname')} 收藏 {len(items)} 条", file=sys.stderr)
    if limit and limit > 0:
        items = items[:limit]
    return items


def _render_local(source_key: str, source_id: str, *, only_if_missing: bool) -> None:
    """本地渲染（不调模型、不识图）：只拼可见 md + agent.md。only_if_missing=True 时可见 md 在就什么都不做。"""
    from . import render as render_mod, storage

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
    from . import enrich as enrich_mod

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
            "error": f"{type(exc).__name__}: {exc}",
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
        from . import attachments as attachments_mod
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


def sync_favorites(
    *,
    limit: int = 50,
    origin: str = "cli",
    actor: str = "human",
    verbose: bool = False,
    extract: bool = False,
    deadline: float | None = None,
) -> dict[str, Any]:
    """读收藏 → 逐条 ingest（去重）→ `{"favorites": N, "synced": M, "items": [...]}`。

    这是**抓取阶段**（用号）。`extract` 在这里不用——识图/概要由 `run` 在放掉账号锁之后交给 enrich。
    `deadline` 是 time.monotonic() 的时刻：到了就不再开新的抓取，剩下的记 deferred。
    """
    global _LAST_TOTAL
    _LAST_TOTAL = None
    try:
        favs = fetch_favorites(limit=limit, verbose=verbose)
    except xhs.NeedsHumanError as exc:
        service = isinstance(exc, xhs.ServiceDownError)
        code = getattr(exc, "code", "")
        # 问题登记在 sync_state.record（_run 拿到这个 payload 就记）：账号类 NEEDS_HUMAN；服务类（含读收藏
        # FAVORITES_FAILED / 超时）TRANSIENT；RATE_LIMITED 只是「刚同步过」，不登记
        return {
            "favorites": 0,
            "synced": 0,
            "login_account": None if service else "xhs",
            "code": code,
            "items": [{"item_id": None, "status": "blocked", "url": None, "error": str(exc), "code": code}],
        }

    # 1001（A-4）：收藏读回 0 条 / 比上次少了一半以上 —— 多半是页面没加载完或被截断，不能当「同步完成」。
    total = _LAST_TOTAL if _LAST_TOTAL is not None else len(favs)
    last = sync_state.load().get("last_favorites") or 0
    suspicious = ""
    if total == 0:
        suspicious = "收藏读回 0 条：多半是收藏页没加载完或被限流，这次不算同步成功"
    elif last and total < last / 2:
        suspicious = f"收藏只读回 {total} 条（上次 {last} 条），少了一半以上：多半只读到一截，这次不算同步成功"
    # 可疑 = 这次不算同步成功：sync_state.record 记 TRANSIENT.FAVORITES_SUSPICIOUS（下次同步自动再读，
    # 连着 3 天才升级推一次；连着 3 晚同一个数就认作新基准）

    # 0927 认号：收藏同步钉在一个号上。登错号（如测试号）时整批不入库、目录页亮「!」，
    # 免得把别的号的收藏悄悄灌进库（0926–0927 测试号登着，夜跑收了它 33 篇）。换号走「更换账号」。
    current = _CURRENT_ACCOUNT.get("nickname") or ""
    pinned = accounts.config().get("sync_account") or ""
    if current and not pinned:
        accounts.save({"sync_account": current})
    elif current and pinned and current != pinned:
        msg = f"现在登录的是「{current}」，不是平时同步的「{pinned}」：没有同步。要换成这个号，请在账号面板点「更换账号」"
        # 登错号 = NEEDS_HUMAN.WRONG_ACCOUNT（sync_state.record 登记在 login，推一次）
        return {"favorites": len(favs), "synced": 0, "login_account": "xhs", "code": "WRONG_ACCOUNT",
                "items": [{"item_id": None, "status": "blocked", "url": None, "error": msg, "code": "WRONG_ACCOUNT"}]}

    failures = _Failures()
    # 抓失败过的（已删 / 仅作者可见）排到最后，别让它们每晚先占掉时间
    favs = sorted(favs, key=lambda f: failures.known(f.get("note_id")))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    quota = _Quota()
    deferred_quota = deferred_budget = skipped_failing = held_known_bad = 0
    consecutive = 0
    known_streak = 0
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
            if quota.exhausted():
                deferred_quota += 1
                continue
            wait = _rest_wait() if fetched_any else 0.0
            if deadline is not None and deadline - _clock() - wait < FETCH_RESERVE_SECONDS:
                deferred_budget += 1  # 剩下的时间装不下这一篇的最坏耗时：不开了，明天继续
                continue
            _rest(wait, verbose=True)
            sync_state.progress(f"第 {i + 1}/{len(favs)} 条收藏是新的（{note_id}），抓取中")
        entry = _sync_one(fav, origin=origin, actor=actor, verbose=verbose, budget_left=budget_left)
        source_id = entry.pop("_source_id", None)
        attachment_block = entry.pop("_blocked_code", "")
        if not in_library:
            fetched_any = True
            status = entry.get("status")
            if status == "new":
                quota.add()
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
            break
    failures.save()
    out: dict[str, Any] = {"favorites": len(favs), "synced": len(items), "items": items}
    if total:
        out["favorites_total"] = total
    if suspicious:
        out["suspicious"] = suspicious
        out["code"] = "FAVORITES_SUSPICIOUS"
    if stop_code:
        out["code"] = stop_code
    if deferred_quota or deferred_budget:
        out["deferred"] = deferred_quota + deferred_budget
        out["deferred_reason"] = "budget" if deferred_budget else "daily_limit"
        out["daily_limit"] = quota.limit
    if skipped_failing or held_known_bad:
        out["skipped_failing"] = skipped_failing + held_known_bad
    if held_known_bad:
        out["held_known_bad"] = held_known_bad
    if fetched_new:
        out["fetched_new"] = fetched_new
    return out


_CURRENT_ACCOUNT: dict[str, str] = {}
_LAST_TOTAL: int | None = None


def tag_account(note_id: str, account: dict[str, str], *, seen_at: str | None = None) -> bool:
    """在对象 meta.json 的 favorited_by 里记下「这篇被哪个号收藏」（去重；失败不影响同步）。"""
    from . import storage
    key = account.get("user_id") or account.get("nickname")
    if not key:
        return False
    path = storage.object_dir(xhs.SOURCE, note_id) / "meta.json"
    try:
        meta = storage.read_json(path)
        tags = [a for a in (meta.get("favorited_by") or []) if isinstance(a, dict)]
        if any((a.get("user_id") or a.get("nickname")) == key for a in tags):
            return False
        tags.append({"nickname": account.get("nickname", ""), "user_id": account.get("user_id", ""),
                     "first_seen": seen_at or datetime.now().astimezone().isoformat(timespec="seconds")})
        meta["favorited_by"] = tags
        storage.write_json(path, meta)
        return True
    except (OSError, ValueError):
        return False


class _Quota:
    """每天最多新抓几篇（插件 data.json 的 sync.dailyNewLimit，缺省 50）。计数存 _archive/sync-quota.json，
    插件白天点的同步和夜跑共用这一个额度。"""

    def __init__(self):
        from datetime import date
        from .ai_config import sync_options
        from . import storage
        self.limit = int(sync_options().get("dailyNewLimit") or 0)
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
        from . import storage
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
        from . import storage
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
        from . import storage
        if not self.dirty:
            return
        try:
            storage.write_json(self.path, self.data)
        except OSError:
            pass


def _already_archived(fav: dict[str, Any]) -> bool:
    """在库里（或在回收站里、已屏蔽同步）= 不用联网。"""
    from . import index as index_mod
    conn = index_mod.connect()
    try:
        if index_mod.get_object(conn, f"xhs-{fav.get('note_id')}") is not None:
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
    if blocked:
        print("sync-favorites: 要人处理（登录态/风控/服务挂了），已停车并报警", file=sys.stderr)
        return EXIT_NEEDS_HUMAN
    if payload.get("code") == "TOO_MANY_FAILURES":
        print("sync-favorites: 连续几篇都没抓到，已停批并报警", file=sys.stderr)
        return EXIT_ERROR
    # 已知坏篇（以前就抓不到：已删 / 仅作者可见）再失败不算出错，不然每晚都报一次「同步出错」
    if any(item.get("status") == "error" and not item.get("known_bad") for item in items):
        print("sync-favorites: 有收藏没归档成功，详见 JSON 里的 error 字段", file=sys.stderr)
        return EXIT_ERROR
    if payload.get("suspicious"):
        print(f"sync-favorites: {payload['suspicious']}", file=sys.stderr)
        return EXIT_ERROR
    if payload.get("deferred_reason") == "budget":
        print(f"sync-favorites: 今天先到这，剩 {payload.get('deferred')} 篇明天继续", file=sys.stderr)
    return EXIT_OK


def _run(args) -> tuple[int, dict[str, Any]]:
    from . import enrich as enrich_mod

    budget = float(getattr(args, "budget_min", 0) or 0)
    deadline = _clock() + budget * 60 if budget > 0 else None
    wait_s = float(getattr(args, "wait_lock_min", 10) or 0) * 60

    # ① 熔断中：一页都不开（B-3）
    try:
        accounts.check_risk_hold()
    except accounts.ReaderError as exc:
        text = f"{accounts.SOLUTIONS['RISK_HOLD'][1]}（{exc.detail}）：{accounts.SOLUTIONS['RISK_HOLD'][2]}"
        payload = {"favorites": 0, "synced": 0, "login_account": "xhs", "code": "RISK_HOLD",
                   "items": [{"item_id": None, "status": "blocked", "url": None, "error": text, "code": "RISK_HOLD"}]}
        if not sync_state.running_elsewhere():
            sync_state.record("finished", payload=payload)  # 顺带登记 NEEDS_HUMAN.RISK_HOLD（login）
        else:
            from . import problems
            problems.report_blocked("sync.favorites", "RISK_HOLD", text)
        return _exit_code(payload), payload

    # ② 账号锁（B-6）：拿不到就退出 6，不碰状态文件（那是正在跑的那一趟的）
    try:
        with accounts.account_session("sync-favorites", wait_s=wait_s):
            sync_state.record("running", message="正在同步收藏")
            try:
                payload = sync_favorites(
                    limit=getattr(args, "limit", 50),
                    origin=getattr(args, "origin", "cli"),
                    actor=getattr(args, "actor", "human"),
                    verbose=getattr(args, "verbose", False),
                    deadline=deadline,
                )
            except Exception:
                sync_state.record("failed", message="同步未完成，请打开账号 / 同步查看详情并重试")
                raise
    except accounts.AccountBusyError as exc:
        print(f"sync-favorites: {exc}", file=sys.stderr)
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
            result = {"error": f"{type(exc).__name__}: {exc}"}
        payload["enrich"] = result
    return _exit_code(payload), payload


def run(args) -> int:
    with contextlib.redirect_stdout(sys.stderr):  # stdout 只留最后那一个 JSON
        code, payload = _run(args)
    read_mod.dump_json(payload)
    return code
