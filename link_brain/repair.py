"""当场自愈（Owner 10-04 定的标准）：非风控的问题当场修，不留到第二天。

「凌晨跑完出 bug 应该当场修复；实际报错都应该显示；期待风控以外的报错是 0。」——所以：
- 各步骤先在**自己那次运行里**换策略重试（识图第二层换参数 → 换模型、概要换模型、向量退避重试、附件转换当场再转、
  转写服务没起当场拉起、附件下载带退避重试；见 docs/ERRORS.md 的对照表）；
- 夜跑收尾再跑一轮「自愈轮」（`run(since=…, auto=True)`）：本次运行新登记、还没解决的非风控问题，各跑一遍对应的修复动作；
  修好的由各模块自己 `problems.resolve`（或这里在退出 0 时代为 resolve），剩下的写清「试过什么、为什么没好、下一步」；
- 面板（problems-ui.js）每条非风控问题一个「现在修」（`run(key=…)`），顶部「全部修一遍」（`run()`）。

绝不碰的：风控 / 登录 / 验证码 / 熔断（NEEDS_HUMAN 账号类）——保持人工入口；自愈轮也绝不重读收藏列表
（10-04 一晚读三次撞了滑块），碰号的动作（补下附件）只在号没出事、离上次开那一篇超过 20 分钟时才跑。

每个修复动作 = 一个 `python -m link_brain …` 子进程（限时，超时整棵结束、放过读取服务，同 enrich.run_limited），
少数几步（检查读取服务）在本进程里做。动作表见 ACTIONS / plan()；新增故障码时在 plan() 里给它一个动作，
并登记到 docs/ERRORS.md（CONVENTIONS §2）。
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from . import problems, storage

# 夜跑几点开始（等待类问题「等到几点」用）；计划任务改了时间可以用环境变量跟上
NIGHTLY_AT = os.environ.get("LINK_BRAIN_NIGHTLY_AT", "04:00")
ROUND_CUTOFF = (6, 50)        # 自愈轮不把夜跑拖过 07:00：06:50 之后不再开新的修复
ROUND_MAX_ROWS = 40           # 一轮最多修这么多组（防一晚几百条把时间全吃掉）
DEFAULT_BUDGET_S = {"key": 20 * 60, "all": 15 * 60, "auto": 30 * 60}
ATTACHMENT_REOPEN_MIN = 20    # 同一篇 20 分钟内重开附件页容易被软限流
LIST_REREAD_MIN = 30          # 读收藏自律间隔（读取服务自己还有 10 分钟限频）
RUNNING_STALE_MIN = 45        # 「正在修」超过这么久还没结论：当它没在修（进程被关了）
SELF_STEP = "nightly.problems-repair"


@dataclass(frozen=True)
class Action:
    name: str
    what: str                                   # 给人看：这个动作做什么
    minutes: int                                # 预计几分钟（面板「正在修 / 预计 N 分钟」）
    argv: Callable[[str | None], list[str]] | None = None   # python -m link_brain 后面的参数；None = 本进程里做
    account: bool = False                       # 碰号（经读取服务开页）
    next_hint: str = "点「复制报错」发给作者"     # 修不好时的下一步
    resolves_self: bool = True                  # 命令自己会 resolve 对应问题；False = 退出 0 由这里代为 resolve


def _item(i: str | None) -> str:
    return str(i or "")


ACTIONS: dict[str, Action] = {a.name: a for a in (
    Action("enrich", "重跑这篇的识图和概要（识图 / 概要会当场换参数、换模型）", 4,
           lambda i: ["enrich", "--item", _item(i)],
           next_hint="到设置里点「测试」看识图 / 归档摘要模型能不能用，好了再点「现在修」"),
    Action("enrich_pending", "补跑所有待补的识图 / 概要", 10, lambda i: ["enrich", "--pending", "--budget-min", "9"],
           next_hint="到设置里点「测试」看识图 / 归档摘要模型能不能用"),
    Action("refine_item", "放弃了的图重新精细识别（换参数 → 换模型）", 4,
           lambda i: ["vision", "--refine-mark", _item(i), "--retry-failed", "--now"],
           next_hint="笔记里用的是第一层识图结果；要更准可以在设置里换精细识别模型后再点「现在修」"),
    Action("refine_run", "补跑待精细识别的图", 8, lambda i: ["vision", "--refine", "--limit", "10"],
           next_hint="到设置里点「测试」看识图接口能不能用"),
    Action("vision_upgrade", "补跑识图第一层", 10, lambda i: ["vision", "--upgrade", "--limit", "10"],
           next_hint="到设置里点「测试」看识图接口能不能用"),
    Action("convert", "重新把附件转成全文", 3, lambda i: ["pdf2md", _item(i), "--force"],
           next_hint="原件已保存：打开原件看看能不能正常打开（有密码 / 损坏的转不了）"),
    Action("attachments", "重新下这篇的附件", 8, lambda i: ["attachments", _item(i), "--budget-min", "7"], account=True,
           next_hint="打开这篇笔记，在小红书里手动下载附件后拖进来（「挂附件」）"),
    Action("attachments_all", "补下缺的附件", 12, lambda i: ["attachments", "--all", "--budget-min", "10"], account=True,
           next_hint="看「附件」那几条各自的原因", resolves_self=False),
    Action("audit", "重数还缺几个附件", 1, lambda i: ["attachments", "--audit"], resolves_self=False),
    Action("transcribe", "拉起转写服务后重转这条视频", 4, lambda i: ["videos", _item(i), "--transcribe"],
           next_hint="确认语音识别能用（设置 → 测试语音识别；CapsWriter 服务端开着）"),
    Action("screen", "重读一次视频画面字幕", 3, lambda i: ["videos", _item(i), "--transcribe", "--rescreen"],
           next_hint="这条视频没有人声、画面上也没认出字，正文和视频本身已存好，不用处理"),
    Action("videos_all", "补转写视频", 10, lambda i: ["videos", "--all", "--transcribe"],
           next_hint="确认语音识别能用（设置 → 测试语音识别）", resolves_self=False),
    Action("embed", "重建语义索引（取向量带退避重试）", 4, lambda i: ["embed"],
           next_hint="到设置里确认千问兼容接口的 key 可用（向量索引跟着它走）"),
    Action("catalog", "重写目录页", 2, lambda i: ["catalog"], resolves_self=False),
    Action("reader", "检查读取服务，没在跑就拉起", 1, None,
           next_hint="打开「账号与同步」看读取组件状态"),
    Action("sync", "重新同步收藏（会读一次收藏列表）", 20,
           lambda i: ["sync-favorites", "--limit", "0", "--budget-min", "18"], account=True,
           next_hint="隔 30 分钟以上再点，或等下次夜跑"),
)}

# nightly.<步骤> 的问题 → 动作（夜跑那一步超时 / 崩了：把那一步的活补跑一小段）
NIGHTLY_STEP_ACTION = {
    "catalog": "catalog", "catalog-final": "catalog", "enrich-pending": "enrich_pending",
    "vision-upgrade": "vision_upgrade", "vision-refine": "refine_run", "videos-transcribe": "videos_all",
    "embed": "embed", "attachments-all": "attachments_all", "attachments-audit": "audit",
    "sync-favorites": "sync",
}


# --------------------------------------------------------------------------
# 时间
# --------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now().astimezone()


def _parse(ts: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts)).astimezone()
    except (TypeError, ValueError):
        return None


def next_nightly(after: datetime) -> datetime:
    """after 之后的下一次夜跑时刻（默认每天 04:00）。"""
    try:
        hh, mm = (int(x) for x in NIGHTLY_AT.split(":", 1))
    except ValueError:
        hh, mm = 4, 0
    at = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return at if at > after else at + timedelta(days=1)


def _hm(dt: datetime | None) -> str:
    return dt.strftime("%m-%d %H:%M") if dt else ""


# --------------------------------------------------------------------------
# 每条问题 → 修复计划
# --------------------------------------------------------------------------

def _run(action: str, *, auto: bool = True) -> dict[str, Any]:
    return {"kind": "run", "action": action, "auto": auto}


def _wait(until: datetime, why: str) -> dict[str, Any]:
    return {"kind": "wait", "action": None, "auto": False, "wait_until": until.isoformat(timespec="seconds"), "why": why}


def _manual(next_step: str) -> dict[str, Any]:
    return {"kind": "manual", "action": None, "auto": False, "next": next_step}


HUMAN = {"kind": "human", "action": None, "auto": False}
NONE = {"kind": "none", "action": None, "auto": False}


def _last_list_read() -> datetime | None:
    """上次读收藏列表结束的时刻（sync-status.json 的 updated_at；正在跑就是现在）。"""
    try:
        from . import sync_state
        st = sync_state.load()
    except Exception:  # noqa: BLE001
        return None
    if st.get("state") == "running":
        return _now()
    return _parse(st.get("updated_at"))


def plan(row: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """这条问题怎么修：kind = run（有动作，auto=夜跑自愈轮会自动跑）/ wait（必须等，带等到几点、为什么）/
    human（风控 / 登录 / key 这类要人处理，走原来的按钮）/ manual（没有自动动作，写下一步）/ none（未开启，不是问题）。"""
    now = now or _now()
    try:
        cls, sub = problems.classify(row.get("code") or ""), problems.subcode(row.get("code") or "")
    except problems.BadCode:
        return _manual("故障码认不出来：点「复制报错」发给作者")
    step = str(row.get("step") or "")
    item = row.get("item_id")
    transient = cls == "TRANSIENT"
    if cls == "SKIPPED":
        return dict(NONE)
    if cls == "NEEDS_HUMAN":
        if sub == "STUCK":  # 连着几天自动重试没好：按那一步的动作修（各篇一起）
            inner = plan({**row, "code": "TRANSIENT.RETRY_EXHAUSTED"}, now)
            return {**inner, "auto": False, "group": True} if inner["kind"] == "run" else inner
        return dict(HUMAN)
    if step == SELF_STEP:
        return _manual("自愈轮自己出了错：点「复制报错」发给作者")
    if sub == "STEP_ARGS":
        return _manual("程序和夜跑脚本版本对不上：更新程序或夜跑脚本后自动恢复")

    if step in ("sync.favorites", "nightly.sync-favorites"):
        if sub == "FAVORITES_SUSPICIOUS":
            until = next_nightly(_parse(row.get("ts")) or now)
            if now < until:
                return _wait(until, "今晚已经读到一截收藏列表，同一晚再读容易撞安全验证；读到的新收藏已入档")
        if sub == "RATE_LIMITED":
            return _wait((_parse(row.get("ts")) or now) + timedelta(minutes=10), "收藏每 10 分钟最多读一次")
        last = _last_list_read()
        if last and now < last + timedelta(minutes=LIST_REREAD_MIN):
            return _wait(last + timedelta(minutes=LIST_REREAD_MIN), "刚读过收藏列表，隔 30 分钟再读，别撞安全验证")
        return _run("sync", auto=False)  # 夜跑已经按规矩重试过一次了：自愈轮不再读列表，只给「现在修」
    if step == "ingest":
        if item:
            return _wait(next_nightly(now), "网页那侧拦了；同一晚再开页容易被限流，夜里的附件补查会再看")
        return _run("reader")
    if step == "attachments.download":
        if not item:
            return _run("attachments_all")
        last = _parse(row.get("ts")) or now
        if now < last + timedelta(minutes=ATTACHMENT_REOPEN_MIN):
            return {**_run("attachments"), "not_before": (last + timedelta(minutes=ATTACHMENT_REOPEN_MIN)).isoformat(timespec="seconds")}
        return _run("attachments")
    if step == "attachments.recheck" or step == "nightly.attachments-recheck":
        return _wait(next_nightly(now), "网页那侧没查清；同一晚再开容易被限流，夜里的附件补查会再看")
    if step == "attachments.convert":
        return _run("convert", auto=transient) if item else _manual("看附件那几条各自的原因")
    if step in ("enrich.summary", "vision.layer1"):
        return _run("enrich", auto=transient) if item else _run("enrich_pending", auto=transient)
    if step == "vision.refine":
        return _run("refine_item", auto=False) if item else _run("refine_run", auto=transient)
    if step == "videos.transcribe":
        if not item:
            return _run("videos_all", auto=transient)
        if sub in ("NO_SPEECH", "NO_AUDIO"):
            return _run("screen", auto=False)
        return _run("transcribe", auto=transient)
    if step == "embed":
        return _run("embed", auto=transient)
    if step == "remote":
        return _manual("到 设置 → 远程阅读 关掉再打开一次")
    if step == "nightly.gemini-keys" or sub == "SECRET_TIMEOUT":
        return _manual("精细识图今晚已退回设置里的模型；检查密码库能不能解锁")
    if step == "nightly.run":
        if sub == "INTERRUPTED":
            return _wait(next_nightly(now), "记的是上一晚夜跑被打断；今晚夜跑走完就自动消")
        return _manual("夜跑自己出错：看夜跑日志，点「复制报错」发给作者")
    if step.startswith("nightly."):
        name = NIGHTLY_STEP_ACTION.get(step[len("nightly."):])
        if name == "sync":
            return plan({**row, "step": "sync.favorites"}, now)
        if name:
            return _run(name, auto=transient)
    return _manual("没有自动修复动作：看原因处理；拿不准就点「复制报错」发给作者")


def describe(row: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """面板要的几项：repairable（给不给「现在修」）、repair_kind、repair_what、repair_minutes、status_text（一句话状态）。"""
    now = now or _now()
    p = plan(row, now)
    act = ACTIONS.get(p.get("action") or "")
    out: dict[str, Any] = {"repairable": p["kind"] == "run", "repair_kind": p["kind"], "repair_auto": bool(p.get("auto")),
                           "repair_what": act.what if act else "", "repair_minutes": act.minutes if act else 0,
                           "status_text": ""}
    at = _parse(row.get("repair_at"))
    if row.get("repair_state") == "running" and at and now < at + timedelta(minutes=RUNNING_STALE_MIN):
        out["status_text"] = f"正在修 / 预计 {int(row.get('repair_eta_min') or (act.minutes if act else 5))} 分钟"
        out["repairing"] = True
    elif p["kind"] == "wait":
        out["status_text"] = f"等到 {_hm(_parse(p['wait_until']))}：{p['why']}"
        out["wait_until"] = p["wait_until"]
    elif p["kind"] == "manual":
        out["status_text"] = "要你看一眼：" + p["next"]
    elif p["kind"] == "run" and act:
        if row.get("repair_state") == "failed":
            out["status_text"] = f"当场修过没好（{_hm(at)}）：可以再点「现在修」"
        else:
            out["status_text"] = f"待修复：点「现在修」当场修（约 {act.minutes} 分钟）"
    return out


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------

def _child_run(argv: list[str], timeout: float) -> tuple[int | None, str, bool]:
    """跑一个修复子进程：python -m link_brain …；超时整棵结束（放过读取服务）。返回 (退出码, stderr 尾巴, 是否超时)。"""
    from . import enrich
    return enrich.run_limited([sys.executable, "-m", "link_brain", *argv], timeout)


def _reader_check(timeout: float) -> tuple[int, str, bool]:
    from . import accounts
    try:
        accounts.ensure_reader(wait=min(40.0, max(5.0, timeout)))
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}", False
    problems.resolve("ingest", None)
    return 0, "", False


def _risk_hold() -> bool:
    try:
        from . import accounts
        return bool(accounts.risk_hold())
    except Exception:  # noqa: BLE001
        return False


def _tail(text: str) -> str:
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    return lines[-1][:120] if lines else ""


def _select(rows: list[dict[str, Any]], *, key: str | None, since: str | None, auto: bool,
            now: datetime) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    picked: list[tuple[dict[str, Any], dict[str, Any]]] = []
    since_dt = _parse(since) if since else None
    target = next((r for r in rows if r["key"] == key), None) if key else None
    for r in rows:
        if r.get("step") == SELF_STEP:
            continue
        p = plan(r, now)
        if key:
            if target is None:
                break
            if r["key"] == key and p["kind"] == "run":
                picked.append((r, p))
            elif target.get("code") == "NEEDS_HUMAN.STUCK" and r.get("step") == target.get("step") \
                    and p["kind"] == "run":
                picked.append((r, p))  # 「连续几天没修好」= 那一步各篇一起修
            continue
        if p["kind"] != "run" or p.get("group"):
            continue
        if auto:
            ts = _parse(r.get("ts"))
            if not p.get("auto") or (since_dt and (ts is None or ts < since_dt)):
                continue
        elif p["action"] == "sync":
            continue  # 「全部修一遍」不顺手读收藏列表：要读就单独点那一条
        picked.append((r, p))
    return picked


def run(*, key: str | None = None, since: str | None = None, auto: bool = False, allow_account: bool = True,
        budget_seconds: float | None = None, execute: Callable[[list[str], float], tuple] | None = None,
        clock: Callable[[], float] = time.monotonic, now_fn: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """跑一轮修复。key = 只修这一条（面板「现在修」）；auto = 夜跑自愈轮（只跑能自动跑的、since 之后登记的）；
    都不给 = 面板「全部修一遍」。返回 {ok, ran, fixed, left, message, results:[{key, status, message}]}。"""
    now_fn = now_fn or _now
    execute = execute or _child_run
    mode = "key" if key else "auto" if auto else "all"
    budget = DEFAULT_BUDGET_S[mode] if budget_seconds is None else max(0.0, float(budget_seconds))
    deadline = clock() + budget
    start = now_fn()
    if auto and start.hour < 7:
        cutoff = start.replace(hour=ROUND_CUTOFF[0], minute=ROUND_CUTOFF[1], second=0, microsecond=0)
        deadline = min(deadline, clock() + max(0.0, (cutoff - start).total_seconds()))
    results: list[dict[str, Any]] = []
    lock = storage.file_lock("problem-repair", wait_s=0, owner="repair")
    try:
        lock.__enter__()
    except storage.LockBusy:
        return {"ok": False, "ran": True, "fixed": 0, "left": 0, "results": [],
                "message": "另一轮修复正在跑（夜跑自愈轮或面板），等它跑完再点"}
    try:
        rows = problems.load()
        picked = _select(rows, key=key, since=since, auto=auto, now=start)
        if key and not picked:
            row = next((r for r in rows if r["key"] == key), None)
            msg = "这条已经好了" if row is None else _not_runnable(row, plan(row, start))
            return {"ok": row is None, "ran": True, "fixed": 0, "left": 0 if row is None else 1, "message": msg,
                    "results": [] if row is None else [{"key": key, "status": "not_runnable", "message": msg}]}
        groups: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for r, p in picked:
            groups.setdefault((p["action"], str(r.get("item_id") or "")), []).append((r, p))
        for n, ((name, item), members) in enumerate(groups.items()):
            act = ACTIONS[name]
            if n >= ROUND_MAX_ROWS:
                results += [_res(r, "deferred", "这一轮修的条数到上限了，可以再点一次「全部修一遍」") for r, _ in members]
                continue
            remaining = deadline - clock()
            if remaining < 30:
                results += [_res(r, "deferred", "这一轮的时间用完了（夜跑不拖过 07:00），可以点「现在修」") for r, _ in members]
                continue
            if act.account and (not allow_account or _risk_hold()):
                why = "号要人处理（风控 / 掉登录），碰号的修复先不跑；处理好账号后点「现在修」"
                for r, _ in members:
                    problems.annotate(r, repair_state="failed", repair_at=_iso(now_fn()), repair_note=why)
                    results.append(_res(r, "skipped", why))
                continue
            not_before = max((_parse(p.get("not_before")) for _, p in members if p.get("not_before")),
                             default=None)
            if not_before and now_fn() < not_before:
                why = f"离上次开这一篇不到 {ATTACHMENT_REOPEN_MIN} 分钟，{_hm(not_before)} 之后再开（别被限流）"
                results += [_res(r, "waiting", why) for r, _ in members]
                continue
            for r, _ in members:
                problems.annotate(r, repair_state="running", repair_at=_iso(now_fn()), repair_eta_min=act.minutes)
            timeout = min(remaining, max(120.0, act.minutes * 60 * 2 + 60))
            try:
                if act.argv is None:
                    code, err, timed_out = _reader_check(timeout)
                else:
                    code, err, timed_out = execute(act.argv(item or None), timeout)
            except Exception as exc:  # noqa: BLE001 - 一个动作炸了不带走这一轮
                code, err, timed_out = 1, f"{type(exc).__name__}: {exc}", False
            folded = problems._fold(problems._read_rows())
            for r, _ in members:
                fresh = folded.get(r["key"])
                if fresh and not fresh.get("resolved_at") and code == 0 and not act.resolves_self:
                    problems.resolve(r["step"], r.get("item_id"), r["code"])
                    fresh = None
                if not fresh or fresh.get("resolved_at"):
                    results.append(_res(r, "resolved", f"已修好：{act.what}"))
                    continue
                if fresh.get("ts") != r.get("ts"):
                    why = str(fresh.get("reason") or "")[:100]  # 这次又登记了一回：用新原因
                else:
                    why = ("到了这一轮的时限还没跑完" if timed_out else _tail(err)
                           or ("跑完了但问题还在" if code == 0 else f"退出码 {code}"))
                note = f"已试：{act.what}（{now_fn():%H:%M}）；没好：{why}；下一步：{act.next_hint}"
                problems.annotate(r, repair_state="failed", repair_at=_iso(now_fn()), repair_note=note)
                results.append(_res(r, "unresolved", note))
    finally:
        lock.__exit__(None, None, None)
    fixed = sum(1 for x in results if x["status"] == "resolved")
    left = len(results) - fixed
    if not results:
        msg = "没有要当场修的问题" if not key else "这条现在不用修"
    else:
        msg = f"自愈：修好 {fixed} 条" + (f"，还剩 {left} 条（每条都写了试过什么、为什么没好、下一步）" if left else "")
    return {"ok": left == 0, "ran": True, "fixed": fixed, "left": left, "message": msg, "results": results}


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _res(row: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    return {"key": row["key"], "step": row.get("step"), "item_id": row.get("item_id"), "status": status,
            "message": message}


def _not_runnable(row: dict[str, Any], p: dict[str, Any]) -> str:
    if p["kind"] == "wait":
        return f"要等到 {_hm(_parse(p['wait_until']))}：{p['why']}"
    if p["kind"] == "human":
        return "这条要你处理（风控 / 登录 / key），用它旁边的按钮"
    if p["kind"] == "manual":
        return "没有自动修复动作：" + p["next"]
    return "这条不是问题（没开 / 没配），不用修"
