"""网页版限制的笔记（1011）。

现象：她收藏里有这篇、浏览器里打开要「验证一下」才给看；网页版的收藏列表里也没有它（fav-tokens.json 里查不到）。
读取服务打开详情页，页面上没有这篇——以前评论补齐 / 附件补下各自重试 3 次、「已放弃」、报一句看不懂的错，每晚再来一遍。

现在（读取组件 1011 认出 `NOTE_RESTRICTED` 之后）：
1. 只是这一篇：不停整批、不写熔断、不算这篇评论「连着补不上」的次数。号的事（看得见的验证 / 安全跳转 / 页面上有登录框）
   照旧由读取组件按风控停车写熔断，这里一点不放宽。
2. 兜底一次：用标题搜一次（读取服务 `POST /api/v1/notes/search-token`），按笔记 id 从搜索结果里认出这篇、拿新的打开口令，
   歇一会儿（LWA_FETCH_REST）再用新口令开一次。**每篇每天最多一次**（先记再搜，中途崩了今天也不再搜）；开页前照旧
   accounts.pace；调用方拿着账号锁。绝不连着快速重试。
3. 还是打不开：记在对象级 `derived/restricted.json`（可变状态），问题面板一条（`note.restricted` · `PERMANENT.NOTE_RESTRICTED`，
   一篇一条、不推送、不重复刷次数），卡片角标、笔记页评论区顶上一行「这篇在小红书网页版要验证才能看」+「打开验证」。
   评论补齐 / 附件补下看到它就跳过这篇（不再每晚 3 次）。
4. 她点「打开验证」（`note-verify <item_id> --wait`）：读取服务开有界面的窗口到这篇，她过完验证、看到笔记就关窗。
   窗口里看到过这篇 → 清掉标记、记下窗口里的新口令、把评论续读的「没进展」清零（限制期间的失败不算这篇读不全）、
   附件的下载退避清掉，拉起后台补评论（同一篇照旧隔 45 分钟再开）；附件由今晚 4 点的 `attachments --all` 补。
"""

from __future__ import annotations

import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import storage

SOURCE = "xiaohongshu"
STEP = "note.restricted"
CODE = "PERMANENT.NOTE_RESTRICTED"
TEXT = "这篇在小红书网页版要验证才能看"
STATE_NAME = "restricted.json"
REST_ENV = "LWA_FETCH_REST"       # 搜到新口令后歇多久再开（和补评论篇间同一个变量；本机 cmd 里是 180,420）
REST_DEFAULT = "60,180"
KEYWORD_MAX = 30
NEXT_STEP = "点「打开验证」，在弹出的窗口里过一下验证、看到笔记后关窗；过了会自动补抓评论 / 附件"


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _today() -> str:
    return _now().date().isoformat()


def _sid(item_or_source_id: str) -> str:
    return str(item_or_source_id or "").removeprefix("xhs-")


# --------------------------------------------------------------------------
# 对象级状态 derived/restricted.json
# --------------------------------------------------------------------------


def state_path(source_id: str) -> Path:
    return storage.derived_dir(SOURCE, _sid(source_id)) / STATE_NAME


def load(source_id: str) -> dict[str, Any]:
    try:
        data = storage.read_json(state_path(source_id))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(source_id: str, state: dict[str, Any]) -> None:
    path = state_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(path, state)


# 1017（她：号好着却挂着 10 篇「要验证」，和「号只看一个状态」冲突）：「页面停在 /explore」在号被软限频时也是这样，
# 一次分不出是这篇被限制还是号当时不行。所以撞见一次只算「疑似」：不进问题面板、不出笔记页那行，过 RECHECK_HOURS
# 让后台续读再开一次；在 CONFIRM_DAYS 个不同日子都打不开才算确认（这才要她点「打开验证」）。打开了就 clear，什么都不留。
CONFIRM_DAYS = 2
RECHECK_HOURS = 20


def _days(st: dict[str, Any]) -> list[str]:
    days = [str(d) for d in (st.get("days") or []) if d]
    if not days:  # 1017 前的老标记只有 since / last_at
        days = sorted({str(st.get(k) or "")[:10] for k in ("since", "last_at") if st.get(k)})
    return days


def confirmed(st: dict[str, Any]) -> bool:
    """标着、且在不同的日子撞见过 CONFIRM_DAYS 次（或她已经点过「打开验证」没过）。"""
    if not st.get("restricted"):
        return False
    v = st.get("verify") or {}
    return len(_days(st)) >= CONFIRM_DAYS or bool(v.get("result") and v.get("result") != "note_ok")


# 1017（她：我自己的号点原文链接看得到，验证窗口里看不到）：验证窗口和原文链接用的是同一个打开口令，差别在号——
# 读取号看不到、她的号看得到，点验证也救不回来。正文早就存好了的话，缺的只是几条回复：不该叫她。
# 存档已经齐（正文在、设置楼数内楼中楼缺 ≤ COMPLETE_GAP 条、楼数没缺、附件没缺）→ 确认了也不登记，已有的那条收掉。
COMPLETE_GAP = 2


def archive_complete(source_id: str) -> bool:
    """这篇在库里该有的都有了。读不清（没 RAW、算不出来）一律 False——照常登记，宁可多叫一次。"""
    sid = _sid(source_id)
    try:
        from . import comment_fill
        from .attachments import inventory
        meta, source = comment_fill.current_source(SOURCE, sid)
        sc = comment_fill.scope(source, comment_fill.floor_target(), comment_fill.load_state(SOURCE, sid))
        if int(sc.get("missing") or 0) > COMPLETE_GAP or sc.get("more_floors"):
            return False
        report = inventory(storage.object_dir(SOURCE, sid), meta)
        return not report.get("missing")
    except Exception:  # noqa: BLE001
        return False


def is_restricted(source_id: str) -> bool:
    """后台续读 / 附件要不要跳过这篇：确认了的跳过；疑似的过 RECHECK_HOURS 放行再试一次（号不好时读取组件根本不开页）。"""
    st = load(source_id)
    if not st.get("restricted"):
        return False
    if confirmed(st):
        return True
    last = _parse_iso(st.get("last_at"))
    return last is None or (_now() - last).total_seconds() < RECHECK_HOURS * 3600


def _parse_iso(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def best_token(source_id: str, fallback: str | None = None) -> str:
    """这篇眼下最好用的打开口令：搜到的 / 验证窗口里拿到的新口令，没有就用调用方给的。"""
    return str(load(source_id).get("token") or fallback or "")


def keyword(title: str | None) -> str:
    """标题 → 搜索词（压空白、去话题尾巴、截前 KEYWORD_MAX 字）。"""
    s = " ".join(str(title or "").replace("#", " ").split())
    return s[:KEYWORD_MAX]


def search_due(state: dict[str, Any]) -> bool:
    """今天还没为这篇搜过。"""
    return str((state.get("search") or {}).get("on") or "") != _today()


def reason_text(state: dict[str, Any]) -> str:
    """问题面板 / 卡片悬停那一句（≤320 字）。"""
    bits = [TEXT + "：读取服务打开这篇时页面上没有它（不是号的问题，只是这一篇）"]
    s = state.get("search") or {}
    res = s.get("result")
    if res == "not_found":
        bits.append(f"{str(s.get('on') or '')[5:]} 用标题搜过一次，搜索结果里没有这篇")
    elif res == "found":
        bits.append(f"{str(s.get('on') or '')[5:]} 用标题搜到了新的打开口令，用它开也还是要验证")
    elif res == "no_title":
        bits.append("这篇没有标题，没法搜新的打开口令")
    v = state.get("verify") or {}
    if v.get("result") and v.get("result") != "note_ok":
        bits.append(f"上次打开验证：{v.get('text') or v.get('result')}")
    return "；".join(bits) + "。" + NEXT_STEP


# --------------------------------------------------------------------------
# 标记 / 清除
# --------------------------------------------------------------------------


def mark(source_id: str, *, item_id: str | None = None, title: str | None = None, via: str = "",
         detail: str = "") -> dict[str, Any]:
    """记成「网页版要验证」：对象级状态 + 问题面板一条（一篇一条；已经开着就不再登记，不刷次数）。永不抛异常。"""
    sid = _sid(source_id)
    item_id = item_id or f"xhs-{sid}"
    st = load(sid)
    was = bool(st.get("restricted"))
    now = _iso()
    days = _days(st) if was else []
    st.update(restricted=True, last_at=now, count=int(st.get("count") or 0) + 1,
              via=sorted({*(st.get("via") or []), *([via] if via else [])}), detail=str(detail or "")[:200],
              days=sorted({*days, now[:10]})[-7:])
    if not was:
        st["since"] = now
        st.pop("cleared_at", None)
        st.pop("cleared_why", None)
    if title:
        st["title"] = str(title)[:120]
    try:
        save(sid, st)
    except OSError as exc:
        print(f"[restricted] 状态没写上：{exc}", file=sys.stderr)
    try:
        from . import problems
        if not confirmed(st) or archive_complete(sid):
            pass  # 1017：疑似的不登记（等隔天再开一次）；存档已经齐了的也不叫她
        elif not was or not problems.is_open(STEP, item_id, CODE):
            problems.report(STEP, "PERMANENT.NOTE_RESTRICTED", reason_text(st), item_id=item_id, title=title or st.get("title"),
                            action="gave_up")
    except Exception as exc:  # noqa: BLE001 - 登记失败不影响别的
        print(f"[restricted] 问题记录没写上：{exc}", file=sys.stderr)
    return st


def clear(source_id: str, *, item_id: str | None = None, why: str = "", token: str | None = None) -> bool:
    """这篇打开了：清掉标记、问题面板那条标已解决；新口令记下来。返回原来是不是标着。永不抛异常。"""
    sid = _sid(source_id)
    st = load(sid)
    was = bool(st.get("restricted"))
    if not was and not token:
        return False
    now = _iso()
    if token:
        st.update(token=str(token), token_at=now)
    if was:
        st.update(restricted=False, cleared_at=now, cleared_why=why[:120])
    try:
        save(sid, st)
    except OSError as exc:
        print(f"[restricted] 状态没写上：{exc}", file=sys.stderr)
    if was:
        try:
            from . import problems
            problems.resolve(STEP, item_id or f"xhs-{sid}")
        except Exception:  # noqa: BLE001
            pass
    return was


def view(source_id: str) -> dict[str, Any] | None:
    """笔记页评论区顶上那一行要的：{text, since, item_id}；没标着返回 None。"""
    st = load(source_id)
    if not confirmed(st):
        return None
    return {"text": TEXT, "since": st.get("since"), "item_id": f"xhs-{_sid(source_id)}",
            "searched": (st.get("search") or {}).get("result") or ""}


# --------------------------------------------------------------------------
# 兜底：用标题搜一次，拿新的打开口令
# --------------------------------------------------------------------------


def _rest_seconds() -> float:
    from . import accounts
    lo, hi = accounts._gap_range(REST_ENV, REST_DEFAULT)
    return max(0.0, random.uniform(lo, hi))


def find_fresh_token(source_id: str, title: str | None, old_token: str | None = None, *,
                     sleep: Callable[[float], None] | None = None, progress=None) -> str | None:
    """每篇每天最多一次：用标题搜，按笔记 id 认出这篇、拿新的打开口令；拿到了先歇一会儿（LWA_FETCH_REST）再交回，
    调用方紧接着用它开一次。调用方必须拿着账号锁。

    号要人处理（熔断 / 验证 / 掉登录）→ 抛 xhs.AccountBlockedError（带码），调用方照原来的规矩停车；
    其余没搜成（服务忙、页面里有看不见的验证组件、搜索页没出来、搜不到、搜到的口令和原来一样）→ None。"""
    from . import accounts
    from .adapters import xiaohongshu as xhs
    sid = _sid(source_id)
    st = load(sid)
    if not search_due(st):
        return None
    kw = keyword(title)
    rec: dict[str, Any] = {"on": _today(), "at": _iso()}
    if not kw:
        st["search"] = {**rec, "result": "no_title"}
        save(sid, st)
        return None
    st["search"] = {**rec, "result": "running"}   # 先记再搜：中途崩了 / 被杀，今天也不再搜第二次
    save(sid, st)
    if progress:
        progress("search", "这篇打不开：用标题搜一次，看能不能拿到新的打开口令")
    try:
        accounts.pace("搜这篇的标题")
        data = accounts.search_note_token(sid, kw)
    except accounts.ReaderError as exc:
        st["search"] = {**rec, "result": "error", "error": f"{exc.code} {exc}"[:200]}
        save(sid, st)
        if exc.needs_human:
            err = xhs.AccountBlockedError(f"用标题搜这篇时号要处理：{exc}")
            err.code = exc.code
            raise err from exc
        print(f"[restricted] 用标题搜这篇没成（{exc.code}）：{exc}", file=sys.stderr)
        return None
    token = str((data or {}).get("xsec_token") or "") if (data or {}).get("found") else ""
    if not token:
        st["search"] = {**rec, "result": "not_found", "count": (data or {}).get("count")}
        save(sid, st)
        return None
    if old_token and token == old_token:
        st["search"] = {**rec, "result": "same_token"}
        save(sid, st)
        return None
    st["search"] = {**rec, "result": "found"}
    st.update(token=token, token_at=_iso())
    save(sid, st)
    wait = _rest_seconds()
    print(f"[restricted] 搜到这篇的新口令，歇 {wait:.0f} 秒再开（不连着开）", file=sys.stderr)
    if progress:
        progress("search", f"搜到了新的打开口令，歇 {wait:.0f} 秒再用它打开（不连着开页）")
    (sleep or time.sleep)(wait)
    return token


def retry_with_fresh_token(source_id: str, *, title: str | None, old_token: str | None, attempt: Callable[[str], Any],
                           restricted_exc: tuple[type[BaseException], ...], item_id: str | None = None, via: str = "",
                           detail: str = "", sleep: Callable[[float], None] | None = None, progress=None) -> tuple[bool, Any]:
    """第一次已经撞了「网页版限制」之后：今天还没搜过就搜一次新口令、再开一次（attempt(token)）。
    返回 (打开了没, attempt 的结果)。还是打不开 → mark()，返回 (False, None)。号要人处理的异常原样往上抛。"""
    sid = _sid(source_id)
    token = find_fresh_token(sid, title, old_token, sleep=sleep, progress=progress)
    if token:
        try:
            result = attempt(token)
        except restricted_exc as exc:
            mark(sid, item_id=item_id, title=title, via=via, detail=f"用搜到的新口令开也还是要验证：{exc}")
            return False, None
        clear(sid, item_id=item_id, why="用标题搜到的新口令打开了", token=token)
        return True, result
    mark(sid, item_id=item_id, title=title, via=via, detail=detail)
    return False, None


LEGACY_HINT = "not found in noteDetailMap"   # 1011 以前读取组件对这类笔记的报错（当普通失败记进了续读状态）


def quiet_unconfirmed() -> list[str]:
    """1017 迁移（幂等、零开页）：问题面板里还开着、但只撞见过一天的「网页版要验证」——收掉，等后台隔天再开一次。"""
    from . import problems
    out = []
    for r in problems.load():
        if r.get("step") != STEP or r.get("resolved_at") or not r.get("item_id"):
            continue
        if not confirmed(load(r["item_id"])) or archive_complete(r["item_id"]):
            problems.resolve(STEP, r["item_id"])
            out.append(r["item_id"])
    return out


def release_legacy_fill_stuck() -> list[str]:
    """一次性（幂等）的本地迁移，零开页：1011 以前，这类笔记的评论续读连着 3 次「not found in noteDetailMap」后被记成
    「连着补不上」（COMMENTS_INCOMPLETE，已放弃），之后再也不会自动开它——新逻辑就永远轮不到认它、给它搜一次新口令。
    这里把这种「已放弃」解开（没进展清零、问题标已解决），让后台补评论按原来的节奏再试**一次**：新读取组件会认出 NOTE_RESTRICTED，
    走兜底（每天最多搜一次）、还不行就记成「网页版要验证」。只认续读状态里记着这句报错的，别的「已放弃」一概不动。返回解开了哪几篇。"""
    from . import comment_fill, problems
    out: list[str] = []
    base = storage.archive_root() / SOURCE
    for path in base.glob(f"*/derived/{comment_fill.STATE_NAME}"):
        sid = path.parents[1].name
        try:
            st = storage.read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(st, dict) or not st.get("stuck") or st.get("legacy_released"):
            continue
        if LEGACY_HINT not in f"{st.get('stuck_reason') or ''} {st.get('last_error') or ''}":
            continue
        for k in ("stuck", "stuck_floors", "stuck_at", "stuck_reason"):
            st.pop(k, None)
        st["no_progress"] = 0
        st["legacy_released"] = _iso()
        try:
            comment_fill.save_state(SOURCE, sid, st)
        except OSError:
            continue
        problems.resolve(comment_fill.STEP, f"xhs-{sid}")
        out.append(f"xhs-{sid}")
    if out:
        print(f"[restricted] {len(out)} 篇以前因「页面上没有这篇」放弃了的评论续读，按新办法再试一次", file=sys.stderr)
    return out


MARKER = "[NOTE_RESTRICTED]"  # 读取组件的报错标记（adapters.xiaohongshu.RESTRICTED_MARKER）


def reclassify_fill_failures() -> list[str]:
    """一次性（幂等）的本地迁移，零开页（1016）：续读报错里明明是 `[NOTE_RESTRICTED]`（页面停在 /explore），
    却被当普通失败连记 3 次、登成了 COMMENTS_INCOMPLETE（1011 前起的后台进程还在跑旧代码时写的）。
    这里改记成「网页版要验证」（note.restricted，一篇一条，同篇已有就并进那条），续读的「已放弃」解开、那条标已解决。"""
    from . import comment_fill, problems
    out: list[str] = []
    base = storage.archive_root() / SOURCE
    for path in base.glob(f"*/derived/{comment_fill.STATE_NAME}"):
        sid = path.parents[1].name
        try:
            st = storage.read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(st, dict):
            continue
        text = f"{st.get('stuck_reason') or ''} {st.get('last_error') or ''}"
        item_id = f"xhs-{sid}"
        if MARKER not in text or st.get("restricted_moved"):
            continue
        mark(sid, item_id=item_id, via="comments.fill", detail=(st.get("last_error") or st.get("stuck_reason") or "")[:200])
        for k in ("stuck", "stuck_floors", "stuck_at", "stuck_reason"):
            st.pop(k, None)
        st["no_progress"] = 0
        st["restricted_moved"] = _iso()
        try:
            comment_fill.save_state(SOURCE, sid, st)
        except OSError:
            continue
        problems.resolve(comment_fill.STEP, item_id, comment_fill.CODE_INCOMPLETE)
        out.append(item_id)
    if out:
        print(f"[restricted] {len(out)} 篇评论续读的「补不上」其实是网页版要验证，已改记到 note.restricted", file=sys.stderr)
    return out


# --------------------------------------------------------------------------
# 她点「打开验证」之后
# --------------------------------------------------------------------------


def _requeue_comments(source_id: str, item_id: str) -> None:
    """限制期间的续读失败不算这篇评论「读不全」：清掉没进展计数 / 已放弃，问题面板那条（若有）标已解决。"""
    from . import comment_fill, problems
    st = comment_fill.load_state(SOURCE, source_id)
    if not st:
        return
    changed = False
    for k in ("stuck", "stuck_floors", "stuck_at", "stuck_reason", "last_error"):
        if k in st:
            st.pop(k)
            changed = True
    if int(st.get("no_progress") or 0):
        st["no_progress"] = 0
        changed = True
    if changed:
        comment_fill.save_state(SOURCE, source_id, st)
        problems.resolve(comment_fill.STEP, item_id)


def _requeue_attachments(source_id: str) -> None:
    """附件的跨夜下载退避清掉：今晚 4 点的 attachments --all 直接补这篇。"""
    path = storage.object_dir(SOURCE, source_id) / "attachment-state.json"
    try:
        st = storage.read_json(path)
    except (OSError, ValueError):
        return
    if isinstance(st, dict) and st.get("download_backoff"):
        st.pop("download_backoff", None)
        storage.write_json(path, st)


def after_verify(source_id: str, outcome: dict[str, Any], *, spawn: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    """笔记验证窗口关了之后：过了 → 清标记、记新口令、排回补抓（评论后台补、附件今晚补）；没过 → 记下结论（面板那句跟着改）。"""
    sid = _sid(source_id)
    item_id = f"xhs-{sid}"
    st = load(sid)
    st["verify"] = {"at": _iso(), "result": outcome.get("result"), "text": outcome.get("message")}
    if not outcome.get("ok"):
        save(sid, st)
        if st.get("restricted"):
            try:
                from . import problems
                for r in problems.load():
                    if r.get("step") == STEP and r.get("item_id") == item_id:
                        problems.annotate(r, verify_result=str(outcome.get("result") or ""), verify_at=_iso())
            except Exception:  # noqa: BLE001
                pass
        return {**outcome, "requeued": False}
    st["verified_at"] = _iso()
    st["recapture"] = {"queued_at": _iso(), "comments": "后台补评论（同一篇隔 45 分钟再开）", "attachments": "今晚 4 点补附件"}
    save(sid, st)
    clear(sid, item_id=item_id, why="她在验证窗口里过了验证", token=outcome.get("token") or None)
    errors = []
    for fn in (_requeue_comments, _requeue_attachments):
        try:
            fn(sid, item_id) if fn is _requeue_comments else fn(sid)
        except Exception as exc:  # noqa: BLE001 - 排回补抓失败不影响「已经过了」
            errors.append(f"{fn.__name__}: {exc}")
    spawned: dict[str, Any] = {}
    try:
        from . import comment_fill
        spawned = (spawn or comment_fill.spawn_worker)()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"spawn: {exc}")
    try:
        from . import catch as catch_mod
        catch_mod._ensure_rendered(SOURCE, sid, force=True, extract=False)
    except Exception as exc:  # noqa: BLE001 - 笔记页那一行下次渲染会跟上
        errors.append(f"render: {exc}")
    for e in errors:
        print(f"[restricted] {e}", file=sys.stderr)
    return {**outcome, "requeued": True, "spawned": bool(spawned.get("started") or spawned.get("already")),
            "message": "过了，这篇能打开了：评论在后台补（同一篇隔 45 分钟再开），附件今晚 4 点补"}


def run_verify(args) -> int:
    """`note-verify <item_id> [--wait]`：插件笔记页 / 问题面板的「打开验证」。stdout 最后一行 {ok, code, message, …}。"""
    from . import accounts, index as index_mod
    from .read import dump_json, outcome
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, args.target)
    finally:
        conn.close()
    if not row or row["source"] != SOURCE:
        dump_json(outcome({"item_id": args.target}, ok=False, message="库里没有这一篇", code="NOT_FOUND"))
        return 1
    sid = row["source_id"]
    try:
        meta = storage.read_json(storage.object_dir(SOURCE, sid) / "meta.json")
        source = storage.read_json(storage.raw_dir(SOURCE, sid, meta["current_version"]) / "source.json")
        old = (source.get("note") or {}).get("xsec_token") or ""
    except (OSError, ValueError, KeyError):
        old = ""
    try:
        out = accounts.open_note_verify(sid, best_token(sid, old), wait=bool(getattr(args, "wait", False)))
    except accounts.ReaderError as exc:
        _, reason, step, _ = accounts.SOLUTIONS.get(exc.code, ("", str(exc), "", ""))
        dump_json(outcome({"item_id": row["item_id"]}, ok=False, message=f"验证窗口没打开：{reason}" + (f"（{step}）" if step else ""),
                          code=exc.code))
        return 5 if exc.needs_human else 1
    if out.get("mode") == "note" and out.get("result") not in ("opened",):
        out = after_verify(sid, out)
    payload = {"item_id": row["item_id"], **{k: v for k, v in out.items() if k not in ("token", "row")}}
    dump_json(outcome(payload, ok=bool(out.get("ok")) or out.get("result") == "opened", message=str(out.get("message") or ""),
                      code="" if out.get("ok") else ("NOTE_RESTRICTED" if out.get("mode") == "note" else str(out.get("mode") or ""))))
    return 0
