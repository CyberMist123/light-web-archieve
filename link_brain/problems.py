"""唯一问题记录（CONVENTIONS §2 / §3）：`vault/_archive/problems.jsonl` + 故障码分类 + 显示登记表。

一行一条，append-only：
    {"ts", "key", "step", "item_id", "title", "code", "reason", "action", "next_at", "count", "resolved_at", "notified"}
- key = `step|item_id|细分码`（item_id 为空 = 步骤级问题），`load()` 按 key 折叠：最新一行为准、count 累加；
  「已解决」= 再追加一行同 key 带 resolved_at；之后同 key 再出现就是新的一轮（count 从头算）。
- 超过 500 行时在锁里压实为最近 500 个 key（每个 key 一行折叠后的结果：count / days / notified 都保留）。

故障码 = `类.细分`，四类：TRANSIENT（自动退避重试）· PERMANENT（记原因、不再重试、不推送）·
NEEDS_HUMAN（只报一次）· SKIPPED（未配置 / 已关闭 / 预算到了：进记录、不算失败、角标不计数）。
现有的裸码（ReaderError.code、sync-status.json.code，如 `NOT_LOGGED_IN`）格式不变，由 `classify` 推出类。

推送只有一个出口：`report()` 内部判定——NEEDS_HUMAN 同 key 未解决只推一次；TRANSIENT 同 key 在连续 3 个
日历日都出现 → 追加一条 NEEDS_HUMAN.STUCK 并推一次。推送走 alert.alert（第 4 批之后它就是模块私有）。

第 0 批只建骨架：没有任何调用点接进来（17 处 alert 的迁移在第 4 批）。
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import storage

FILE_NAME = "problems.jsonl"
MAX_KEYS = 500
REASON_MAX = 200
TITLE_MAX = 120
STUCK_DAYS = 3
DAYS_KEPT = 7  # 每个 key 记住最近几个出现过的日历日（压实后也不丢）

CLASSES = ("TRANSIENT", "PERMANENT", "NEEDS_HUMAN", "SKIPPED")
ACTIONS = ("gave_up", "retry_later", "retrying", "needs_human", "skipped")
DEFAULT_ACTION = {"TRANSIENT": "retry_later", "PERMANENT": "gave_up", "NEEDS_HUMAN": "needs_human",
                  "SKIPPED": "skipped"}
STEPS = ("sync.favorites", "ingest", "attachments.download", "attachments.convert", "attachments.recheck",
         "enrich.summary", "vision.layer1", "vision.refine", "videos.transcribe", "embed", "ask", "login", "config", "remote")
STEP_PREFIXES = ("nightly.",)

# 现有裸码 → 类（§2.2：复用现有码、不改拼写）
BARE_CLASS = {
    "NOT_LOGGED_IN": "NEEDS_HUMAN", "CAPTCHA_REQUIRED": "NEEDS_HUMAN", "ACCOUNT_RISK": "NEEDS_HUMAN",
    "RISK_HOLD": "NEEDS_HUMAN", "NOT_INSTALLED": "NEEDS_HUMAN", "WRONG_ACCOUNT": "NEEDS_HUMAN",
    "FAVORITES_SUSPICIOUS": "NEEDS_HUMAN",
    "RATE_LIMITED": "TRANSIENT", "DISCONNECTED": "TRANSIENT", "TIMEOUT": "TRANSIENT", "BUSY": "TRANSIENT",
    "INTERRUPTED": "TRANSIENT", "TOO_MANY_FAILURES": "TRANSIENT", "ACCOUNT_BUSY": "TRANSIENT",
}

# 显示登记表（§3.1）：code（或 `类.*` 兜底）→ 显示位置 / 标签 / 悬停 / 分组。Python 是唯一文案源，
# 以后写进 catalog-data.json 的 "state_registry" 给页面读；JS 不许自己写状态文案。
# where：top+card（顶部计数 + 卡片角标）· card · list（只在问题列表）· none（列表灰色「未开启」组）
# group：needs_you（等你处理）· auto（正在自动处理）· gave_up（已放弃）· off（未开启）
STATE_REGISTRY: dict[str, dict[str, str]] = {
    # —— 要人处理 ——
    "NEEDS_HUMAN.NOT_LOGGED_IN": dict(where="top+card", label="需要登录", hover="小红书掉登录：点「!」扫码", group="needs_you"),
    "NEEDS_HUMAN.CAPTCHA_REQUIRED": dict(where="top+card", label="需要验证", hover="小红书要安全验证：点「!」打开验证窗口", group="needs_you"),
    "NEEDS_HUMAN.ACCOUNT_RISK": dict(where="top+card", label="账号风控", hover="小红书把读取号跳到了登录/安全页：同步已全部暂停，点「!」处理", group="needs_you"),
    "NEEDS_HUMAN.RISK_HOLD": dict(where="top+card", label="风控暂停中", hover="所有用号的同步都停了，点「!」处理后自动恢复", group="needs_you"),
    "NEEDS_HUMAN.NOT_INSTALLED": dict(where="top+card", label="未安装读取组件", hover="按 README「读取组件」安装后刷新", group="needs_you"),
    "NEEDS_HUMAN.WRONG_ACCOUNT": dict(where="top+card", label="登错号", hover="登录的不是收藏所在的号：换号重新扫码", group="needs_you"),
    "NEEDS_HUMAN.FAVORITES_SUSPICIOUS": dict(where="top+card", label="收藏数异常", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.AUTH_FAILED": dict(where="top+card", label="AI key 失效", hover="接口拒绝了 key（401/403）：到设置里换一个", group="needs_you"),
    "NEEDS_HUMAN.QUOTA_EXCEEDED": dict(where="top+card", label="AI 余额不足", hover="接口提示欠费或额度用完：充值或换 key", group="needs_you"),
    "NEEDS_HUMAN.BACKUP_DISK_MISSING": dict(where="top+card", label="备份盘没挂", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.STUCK": dict(where="top+card", label="连续几天没修好", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.PORT_IN_USE": dict(where="top+card", label="远程阅读端口被占用", hover="{reason}", group="needs_you"),
    # —— 自动重试 ——
    "TRANSIENT.HTTP_5XX": dict(where="list", label="接口暂时出错", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.HTTP_429": dict(where="list", label="接口限流", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.NETWORK": dict(where="list", label="网络不通", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.SERVICE_BUSY": dict(where="list", label="服务正忙", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.STEP_TIMEOUT": dict(where="list", label="步骤超时", hover="{reason}（下次自动再跑）", group="auto"),
    "TRANSIENT.RATE_LIMITED": dict(where="list", label="刚刚同步过", hover="收藏每 10 分钟最多读一次，稍后自动再试", group="auto"),
    "TRANSIENT.DISCONNECTED": dict(where="list", label="读取服务没在运行", hover="{reason}（下次自动拉起）", group="auto"),
    "TRANSIENT.TIMEOUT": dict(where="list", label="读取服务响应超时", hover="{reason}（稍后自动再试）", group="auto"),
    "TRANSIENT.BUSY": dict(where="list", label="读取服务正忙", hover="正在抓别的笔记，做完自然恢复", group="auto"),
    "TRANSIENT.INTERRUPTED": dict(where="list", label="被打断", hover="上次中途被打断，已抓的都在；下次接着来", group="auto"),
    "TRANSIENT.TOO_MANY_FAILURES": dict(where="list", label="连续失败已暂停", hover="{reason}（下次同步再试）", group="auto"),
    "TRANSIENT.ACCOUNT_BUSY": dict(where="list", label="号正被占用", hover="另一个任务在用号，做完再试", group="auto"),
    "TRANSIENT.*": dict(where="list", label="稍后自动重试", hover="{reason}（{next_at} 再试）", group="auto"),
    # —— 已放弃（记原因，不再自动重试）——
    "PERMANENT.PDF_ENCRYPTED": dict(where="card", label="全文没转出来", hover="PDF 有打开密码，字节已保存", group="gave_up"),
    "PERMANENT.PDF_DAMAGED": dict(where="card", label="全文没转出来", hover="PDF 文件损坏，字节已保存", group="gave_up"),
    "PERMANENT.DOC_UNSUPPORTED": dict(where="card", label="全文没转出来", hover="这种文档格式还转不了，原件已保存", group="gave_up"),
    "PERMANENT.NO_AUDIO": dict(where="list", label="视频没有音轨", hover="没有可转写的声音", group="gave_up"),
    "PERMANENT.NO_SPEECH": dict(where="list", label="视频里没人说话", hover="只有背景音乐或环境声", group="gave_up"),
    "PERMANENT.NOTE_GONE": dict(where="card", label="原帖已删除", hover="原帖已删除或不可见，本地存档还在", group="gave_up"),
    "PERMANENT.MODEL_OUTPUT_INVALID": dict(where="card", label="AI 结果不可用", hover="{reason}", group="gave_up"),
    "PERMANENT.REMOTE_TASK_FAILED": dict(where="list", label="远程阅读的计划任务没弄好", hover="{reason}", group="gave_up"),
    "PERMANENT.*": dict(where="card", label="已放弃", hover="{reason}", group="gave_up"),
    # —— 未开启（不算失败）——
    "SKIPPED.NOT_CONFIGURED": dict(where="none", label="未配置", hover="{reason}", group="off"),
    "SKIPPED.DISABLED": dict(where="none", label="已关闭", hover="{reason}", group="off"),
    "SKIPPED.BUDGET": dict(where="none", label="今天的额度到了", hover="{reason}（明天接着来）", group="off"),
    "SKIPPED.FALLBACK": dict(where="none", label="已退回普通方式", hover="{reason}", group="off"),
    "SKIPPED.LEGACY_CONFIG": dict(where="none", label="旧设置已自动换算", hover="{reason}", group="off"),
    "SKIPPED.*": dict(where="none", label="未开启", hover="{reason}", group="off"),
}

# §2.3 首批新增码 + 现有裸码：登记表里精确登记的码必须出自这里或代码里的 problems.report( 字面码
# （tests/test_problems_registry.py 双向核对）。第 4 批接上调用点时这些码会出现在代码里。
PLANNED_CODES = (
    "TRANSIENT.HTTP_5XX", "TRANSIENT.HTTP_429", "TRANSIENT.NETWORK", "TRANSIENT.SERVICE_BUSY",
    "TRANSIENT.STEP_TIMEOUT",
    "PERMANENT.PDF_ENCRYPTED", "PERMANENT.PDF_DAMAGED", "PERMANENT.DOC_UNSUPPORTED", "PERMANENT.NO_AUDIO",
    "PERMANENT.NO_SPEECH", "PERMANENT.NOTE_GONE", "PERMANENT.MODEL_OUTPUT_INVALID",
    "NEEDS_HUMAN.AUTH_FAILED", "NEEDS_HUMAN.QUOTA_EXCEEDED", "NEEDS_HUMAN.BACKUP_DISK_MISSING",
    "NEEDS_HUMAN.STUCK",
    "SKIPPED.NOT_CONFIGURED", "SKIPPED.DISABLED", "SKIPPED.BUDGET", "SKIPPED.FALLBACK",
)

GROUP_OF_CLASS = {"NEEDS_HUMAN": "needs_you", "TRANSIENT": "auto", "PERMANENT": "gave_up", "SKIPPED": "off"}
SUMMARY_KEY = {"NEEDS_HUMAN": "needs_human", "TRANSIENT": "auto", "PERMANENT": "gave_up", "SKIPPED": "skipped"}


class BadCode(ValueError):
    pass


# --------------------------------------------------------------------------
# 码
# --------------------------------------------------------------------------

_SUB_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def normalize(code: str) -> str:
    """`NOT_LOGGED_IN` → `NEEDS_HUMAN.NOT_LOGGED_IN`；已带类的原样返回。格式不对 → BadCode。

    裸码不在 BARE_CLASS 里：`HTTP_429` / `HTTP_5xx` 按 §4.6 翻；其余未知裸码归 TRANSIENT
    （自动重试，连续 3 天还在就升级 STUCK 报给人——不会悄悄藏起来）。"""
    code = str(code or "").strip()
    if "." in code:
        cls, sub = code.split(".", 1)
        if cls not in CLASSES or not _SUB_RE.match(sub):
            raise BadCode(f"故障码格式不对：{code!r}（要 TRANSIENT|PERMANENT|NEEDS_HUMAN|SKIPPED.<大写下划线>）")
        return code
    if not _SUB_RE.match(code):
        raise BadCode(f"故障码格式不对：{code!r}")
    if code in BARE_CLASS:
        return f"{BARE_CLASS[code]}.{code}"
    m = re.match(r"^HTTP_(\d{3})$", code)
    if m:
        status = int(m.group(1))
        if status == 429:
            return "TRANSIENT.HTTP_429"
        if status in (401, 403):
            return "NEEDS_HUMAN.AUTH_FAILED"
        if status == 402:
            return "NEEDS_HUMAN.QUOTA_EXCEEDED"
        if status >= 500:
            return "TRANSIENT.HTTP_5XX"
        return "PERMANENT.MODEL_OUTPUT_INVALID"
    return f"TRANSIENT.{code}"


def classify(code: str) -> str:
    """'TRANSIENT' | 'PERMANENT' | 'NEEDS_HUMAN' | 'SKIPPED'。"""
    return normalize(code).split(".", 1)[0]


def subcode(code: str) -> str:
    return normalize(code).split(".", 1)[1]


def lookup(code: str) -> dict[str, str]:
    """登记表里的显示行：先精确，再 `类.*` 兜底。"""
    full = normalize(code)
    entry = STATE_REGISTRY.get(full) or STATE_REGISTRY[full.split(".", 1)[0] + ".*"]
    return {"code": full, **entry}


def registry_for_js() -> dict[str, dict[str, str]]:
    """给页面用的那份（以后写进 catalog-data.json 的 state_registry）。"""
    return {k: dict(v) for k, v in STATE_REGISTRY.items()}


# --------------------------------------------------------------------------
# 文件
# --------------------------------------------------------------------------


def path() -> Path:
    return storage.archive_root() / FILE_NAME


def _now() -> datetime:
    return datetime.now().astimezone()


def _day(ts: str | None) -> str | None:
    try:
        return datetime.fromisoformat(str(ts)).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return None


def make_key(step: str, item_id: str | None, code: str) -> str:
    return f"{step}|{item_id or ''}|{subcode(code)}"


def _read_rows() -> list[dict[str, Any]]:
    try:
        text = path().read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # 半行 / 坏行：跳过，不让一行坏掉整个列表
        if isinstance(row, dict) and row.get("key"):
            rows.append(row)
    return rows


def _fold(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 key 折叠：最新一行为准；count 累加（解决之后从头算）；days 记最近出现的日历日；notified 本轮推过没有。"""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["key"]
        prev = out.get(key)
        if row.get("resolved_at"):
            if prev is not None:
                out[key] = {**prev, "resolved_at": row["resolved_at"], "notified": False}
            else:
                out[key] = {**row, "count": 0, "days": [], "notified": False}
            continue
        fresh = prev is None or bool(prev.get("resolved_at"))
        base_count = 0 if fresh else int(prev.get("count") or 0)
        days = [] if fresh else list(prev.get("days") or [])
        for d in (row.get("days") or [_day(row.get("ts"))]):
            if d and d not in days:
                days.append(d)
        days = sorted(days)[-DAYS_KEPT:]
        notified = bool(row.get("notified")) or (not fresh and bool(prev.get("notified")))
        out[key] = {**row, "count": base_count + int(row.get("count") or 1), "days": days,
                    "notified": notified, "resolved_at": None}
    return out


def _append(rows: list[dict[str, Any]]) -> None:
    """追加行（每行 ≤ 4 KB）；超过 MAX_KEYS 行就压实。锁拿不到也照写（只追加，丢不了别人的行；压实留给下一次）。"""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    try:
        with storage.file_lock("problems", wait_s=5):
            with p.open("a", encoding="utf-8") as fh:
                fh.write(blob)
            _compact_locked()
    except storage.LockBusy:
        with p.open("a", encoding="utf-8") as fh:
            fh.write(blob)


def _compact_locked() -> bool:
    rows = _read_rows()
    if len(rows) <= MAX_KEYS:
        return False
    folded = _fold(rows)
    keep = sorted(folded.values(), key=lambda r: str(r.get("ts") or ""))[-MAX_KEYS:]
    storage.atomic_write_text(path(), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep))
    return True


def compact() -> bool:
    """压实为最近 MAX_KEYS 个 key（每个 key 一行折叠结果）。在 problems 锁里做。"""
    with storage.file_lock("problems", wait_s=30):
        return _compact_locked()


# --------------------------------------------------------------------------
# 推送（唯一出口）
# --------------------------------------------------------------------------


def _push(row: dict[str, Any]) -> None:
    """报给人。alert 永不抛异常；这里再兜一层，推送失败绝不影响记录。"""
    try:
        from . import alert as alert_mod

        entry = lookup(row["code"])
        title = f"{entry['label']}：{row.get('title') or row.get('item_id') or row.get('step')}"
        alert_mod.alert("problem", title, row.get("reason") or entry["hover"],
                        code=row["code"], step=row.get("step"), item_id=row.get("item_id"))
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 推送失败（{type(exc).__name__}: {exc}）", file=sys.stderr)


def _consecutive_days(days: list[str], n: int, today: date) -> bool:
    want = {(today - timedelta(days=i)).isoformat() for i in range(n)}
    return want.issubset(set(days))


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------


def report(step: str, code: str, reason: str, *, item_id: str | None = None, title: str | None = None,
           action: str | None = None, next_at: str | None = None, _now_fn=None) -> dict[str, Any]:
    """登记一条问题，返回写进文件的那一行。推送判定在这里（见模块说明）。

    码格式不对抛 BadCode（调用方写错码是 bug，要在测试里炸出来）；写盘失败不抛，返回的行带 written=False。"""
    full = normalize(code)
    cls = full.split(".", 1)[0]
    if action is not None and action not in ACTIONS:
        raise ValueError(f"action 只能是 {ACTIONS}：{action!r}")
    now = (_now_fn or _now)()
    key = make_key(step, item_id, full)
    row: dict[str, Any] = {
        "ts": now.isoformat(timespec="seconds"), "key": key, "step": step, "item_id": item_id or None,
        "title": (title or "")[:TITLE_MAX] or None, "code": full, "reason": str(reason or "")[:REASON_MAX],
        "action": action or DEFAULT_ACTION[cls], "next_at": next_at, "count": 1, "resolved_at": None,
    }
    try:
        prev = _fold(_read_rows()).get(key)
    except Exception:  # noqa: BLE001
        prev = None
    unresolved_prev = prev is not None and not prev.get("resolved_at")
    push = cls == "NEEDS_HUMAN" and not (unresolved_prev and prev.get("notified"))
    if push:
        row["notified"] = True
    out_rows = [row]
    stuck = None
    if cls == "TRANSIENT":
        seen = (prev.get("days") or []) if unresolved_prev else []
        days = sorted({*seen, now.date().isoformat()})
        if _consecutive_days(days, STUCK_DAYS, now.date()):
            stuck_key = make_key(step, item_id, "NEEDS_HUMAN.STUCK")
            try:
                stuck_prev = _fold(_read_rows()).get(stuck_key)
            except Exception:  # noqa: BLE001
                stuck_prev = None
            if not (stuck_prev and not stuck_prev.get("resolved_at")):
                stuck = {**row, "key": stuck_key, "code": "NEEDS_HUMAN.STUCK", "action": "needs_human",
                         "reason": f"连续 {STUCK_DAYS} 天自动重试都没成功：{row['reason']}"[:REASON_MAX],
                         "next_at": None, "notified": True}
                out_rows.append(stuck)
    try:
        _append(out_rows)
        row["written"] = True
    except OSError as exc:
        print(f"[problems] 问题记录写不进去（{exc}）", file=sys.stderr)
        row["written"] = False
    if push:
        _push(row)
    if stuck:
        _push(stuck)
    return row


def is_open(step: str, item_id: str | None, code: str) -> bool:
    """这个 step + item_id + 码现在有没有一条还没解决的记录（只记一次的说明类用它去重）。读不动就当没有。"""
    try:
        row = _fold(_read_rows()).get(make_key(step, item_id, normalize(code)))
    except Exception:  # noqa: BLE001
        return False
    return bool(row) and not row.get("resolved_at")


def resolve(step: str, item_id: str | None = None, code: str | None = None, *, _now_fn=None) -> int:
    """把 step（+ item_id；None = 步骤级那几条）下未解决的问题标成已解决。code 给了就只解决那一个码。
    返回解决了几条。永不抛异常（解决失败最多是列表里多挂一条）。"""
    try:
        folded = _fold(_read_rows())
        want_sub = subcode(code) if code else None
        targets = [r for r in folded.values()
                   if r.get("step") == step and (r.get("item_id") or None) == (item_id or None)
                   and not r.get("resolved_at")
                   and (want_sub is None or str(r.get("key", "")).rsplit("|", 1)[-1] == want_sub)]
        if not targets:
            return 0
        now = (_now_fn or _now)().isoformat(timespec="seconds")
        _append([{"ts": now, "key": r["key"], "step": step, "item_id": item_id or None, "code": r["code"],
                  "resolved_at": now, "count": 0} for r in targets])
        return len(targets)
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 标记已解决失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 0


def load(limit: int = MAX_KEYS, *, include_resolved: bool = False) -> list[dict[str, Any]]:
    """折叠后的问题：未解决在前（要你处理 → 自动处理 → 已放弃 → 未开启），同组新的在前。"""
    folded = list(_fold(_read_rows()).values())
    if not include_resolved:
        folded = [r for r in folded if not r.get("resolved_at")]
    order = {"needs_you": 0, "auto": 1, "gave_up": 2, "off": 3}

    def sort_key(r):
        try:
            group = GROUP_OF_CLASS[classify(r.get("code", ""))]
        except BadCode:
            group = "auto"
        return (1 if r.get("resolved_at") else 0, order[group], _neg_ts(r.get("ts")))

    folded.sort(key=sort_key)
    out = []
    for r in folded[:limit]:
        try:
            entry = lookup(r["code"])
        except (BadCode, KeyError):
            entry = {"label": r.get("code", ""), "hover": "{reason}", "where": "list", "group": "auto"}
        out.append({**r, "label": entry["label"], "group": entry["group"], "where": entry["where"]})
    return out


def _neg_ts(ts) -> float:
    try:
        return -datetime.fromisoformat(str(ts)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def summary() -> dict[str, Any]:
    """{needs_human, auto, gave_up, skipped, last_runs: {step: {ts, ok}}}——顶部入口的计数。"""
    rows = _read_rows()
    folded = _fold(rows)
    counts = {"needs_human": 0, "auto": 0, "gave_up": 0, "skipped": 0}
    for r in folded.values():
        if r.get("resolved_at"):
            continue
        try:
            counts[SUMMARY_KEY[classify(r.get("code", ""))]] += 1
        except BadCode:
            counts["auto"] += 1
    last: dict[str, dict[str, Any]] = {}
    for r in rows:
        step = r.get("step")
        if step:
            last[step] = {"ts": r.get("ts"), "ok": bool(r.get("resolved_at"))}
    return {**counts, "last_runs": last}


# --------------------------------------------------------------------------
# 「复制报错」（§3.5）
# --------------------------------------------------------------------------

_SECRET_RE = re.compile(
    r'(?i)("?(?:api[_-]?key|apikey|token|cookie|authorization|x-api-key|secret|password)"?\s*[:=]\s*)'
    r'("[^"]*"|\'[^\']*\'|[^\s,;&}]+)')
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_XSEC_RE = re.compile(r"(?i)(xsec_token=)[^&\s\"'<>]+")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")


def redact(text: str, *, vault: Path | None = None, home: Path | None = None) -> str:
    """去掉 apiKey/token/cookie/Authorization/Bearer 后面的值、xsec_token 参数值；vault 绝对路径换 <vault>、家目录换 ~。"""
    text = str(text or "")
    text = _BEARER_RE.sub(r"\1 <redacted>", text)
    text = _SECRET_RE.sub(lambda m: m.group(1) + ('"<redacted>"' if m.group(2).startswith('"') else "<redacted>"), text)
    text = _XSEC_RE.sub(r"\1<redacted>", text)
    text = _SK_RE.sub("sk-<redacted>", text)
    vault = Path(vault) if vault else storage.vault_root()
    home = Path(home) if home else Path.home()
    for raw, token in ((str(vault), "<vault>"), (str(home), "~")):
        if not raw or len(raw) < 3:
            continue
        variants = {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\"), raw.replace("/", "\\")}
        for v in sorted(variants, key=len, reverse=True):
            text = re.sub(re.escape(v), lambda _m, t=token: t, text, flags=re.IGNORECASE)
    return text


def _plugin_version() -> str:
    try:
        manifest = storage.repo_root() / "obsidian-plugins" / "link-brain-actions" / "manifest.json"
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "?")
    except (OSError, ValueError):
        return "?"


def export_redacted(limit: int = 50, *, plugin_version: str | None = None) -> str:
    """「复制报错」的内容：插件版本 · Python 版本 · 各 step 上次运行结果 · 最近 50 条问题，全部脱敏。
    保留 item_id 和标题（用户自己的数据）。"""
    from . import __version__

    s = summary()
    lines = [
        "# Link Brain 诊断信息（已脱敏）",
        f"- 插件版本：{plugin_version or _plugin_version()} · link_brain {__version__}",
        f"- Python：{platform.python_version()} · {platform.system()} {platform.release()}",
        f"- 问题计数：要你处理 {s['needs_human']} · 自动处理中 {s['auto']} · 已放弃 {s['gave_up']} · 未开启 {s['skipped']}",
        "",
        "## 各步骤上次记录",
    ]
    for step, info in sorted(s["last_runs"].items()):
        lines.append(f"- {step}：{info.get('ts') or '?'} · {'已恢复' if info.get('ok') else '有问题'}")
    if not s["last_runs"]:
        lines.append("- （没有记录）")
    lines += ["", f"## 最近 {limit} 条问题"]
    rows = load(MAX_KEYS, include_resolved=True)
    rows.sort(key=lambda r: _neg_ts(r.get("ts")))
    for r in rows[:limit]:
        state = "已解决" if r.get("resolved_at") else r.get("action") or ""
        lines.append(" · ".join(str(x) for x in (r.get("ts"), r.get("step"), r.get("item_id") or "-",
                                                 r.get("title") or "", r.get("code"), state,
                                                 f"×{r.get('count')}", r.get("reason") or "") if x != ""))
    if not rows:
        lines.append("- （没有问题记录）")
    return redact("\n".join(lines))


# --------------------------------------------------------------------------
# CLI：python -m link_brain problems list|report|export
# --------------------------------------------------------------------------


def add_parser(sub) -> None:
    p = sub.add_parser("problems", help="问题记录：list 列出 / report 登记一条（夜跑脚本用）/ export 复制报错（脱敏）")
    psub = p.add_subparsers(dest="problems_cmd", metavar="<list|report|export>")
    pl = psub.add_parser("list", help="列出问题（折叠后，未解决在前），输出 JSON")
    pl.add_argument("--all", action="store_true", help="连已解决的也列")
    pl.add_argument("--limit", type=int, default=MAX_KEYS)
    pr = psub.add_parser("report", help="登记一条问题（夜跑脚本登记步骤超时用），输出 JSON")
    pr.add_argument("--step", required=True)
    pr.add_argument("--code", required=True, help="类.细分，如 TRANSIENT.STEP_TIMEOUT")
    pr.add_argument("--reason", default="")
    pr.add_argument("--item-id", dest="item_id")
    pr.add_argument("--title")
    pr.add_argument("--action", choices=ACTIONS)
    pr.add_argument("--next-at", dest="next_at")
    pe = psub.add_parser("export", help="复制报错：脱敏后的诊断信息，输出 JSON {text}")
    pe.add_argument("--limit", type=int, default=50)
    pe.add_argument("--plugin-version", dest="plugin_version")


def _valid_step(step: str) -> bool:
    return step in STEPS or any(step.startswith(p) and len(step) > len(p) for p in STEP_PREFIXES)


def run(args) -> int:
    from .read import dump_json

    cmd = getattr(args, "problems_cmd", None)
    if cmd == "list":
        dump_json({"ok": True, "code": "", "message": "", "summary": summary(),
                   "problems": load(args.limit, include_resolved=args.all)})
        return 0
    if cmd == "report":
        if not _valid_step(args.step):
            print(f"step 不在词表里：{args.step}（见 CONVENTIONS §2 step 词表，夜跑用 nightly.<名>）", file=sys.stderr)
            return 1
        try:
            row = report(args.step, args.code, args.reason, item_id=args.item_id, title=args.title,
                         action=args.action, next_at=args.next_at)
        except (BadCode, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        ok = bool(row.get("written"))
        dump_json({"ok": ok, "code": "", "message": "已登记" if ok else "问题记录没写进去", "row": row})
        if not ok:
            print("问题记录没写进去（磁盘或权限）", file=sys.stderr)
        return 0 if ok else 1
    if cmd == "export":
        dump_json({"ok": True, "code": "", "message": "已生成诊断信息",
                   "text": export_redacted(args.limit, plugin_version=args.plugin_version)})
        return 0
    print("用法：python -m link_brain problems list|report|export", file=sys.stderr)
    return 1
