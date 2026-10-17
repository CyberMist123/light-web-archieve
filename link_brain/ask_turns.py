"""问收藏的轮次登记（1015 第二批 ask 车；1018 v2.1 扩成会话状态）：每一答发一个 turn_id，记下这一答的问题、目录 / 来源 id、理解和技能。

「展开」按 turn_id + 那几条 id 走后端（ask.answer(expand=…)），不再拿「上一答」的字面话术再问一遍——
以前前端的「展开重点细节」发固定一句话，被当成新话题重搜（F 节 chat-view.js:893、ask.py:744）。

1018 v2.1（设计 §5.2）：每轮另记 thread_id（第一问生成、追问沿用）、parent_turn_id、who（哪个凭据问的）、
ordered_sources（顺序 = 来源导读的顺序）、objects（答案里出现的对象）、scope（话题 / 任务 / 硬条件 / 排除 / 保留）、head（回答开头）。
查法：get(turn_id) / latest_in_thread(thread_id) / latest_for_who(who, 15 分钟)。按问题原文找的 latest_for 只留给旧测试，生产不再用
（同一句话问两次会串，本地 / 远程共用一张表）。

文件 `_archive/ask-turns.json`（环境变量 LINK_BRAIN_ASK_TURNS 可改位置，评测用）：{"turns": {turn_id: {...}}}，只留最近 KEEP 轮。
写失败不影响作答（fail-open）：拿不到登记时，展开请求带上的 question + ids 照样能答，只是不能核对 id 是不是那一答的。
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage

KEEP = 200
_LOCK = threading.Lock()


def path() -> Path:
    env = os.environ.get("LINK_BRAIN_ASK_TURNS")
    return Path(env) if env else storage.archive_root() / "ask-turns.json"


def _read() -> dict[str, Any]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        turns = data.get("turns") if isinstance(data, dict) else None
        return turns if isinstance(turns, dict) else {}
    except (OSError, ValueError):
        return {}


def new_id() -> str:
    return "t" + datetime.now().strftime("%m%d%H%M%S") + secrets.token_hex(3)


def new_thread_id() -> str:
    return "th" + datetime.now().strftime("%m%d%H%M") + secrets.token_hex(4)


def record(turn_id: str, entry: dict[str, Any]) -> bool:
    """登记一轮；写不进去返回 False（不抛）。"""
    row = {**entry, "ts": datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        with _LOCK, storage.file_lock("ask-turns", wait_s=5, owner="ask"):
            turns = _read()
            turns[turn_id] = row
            if len(turns) > KEEP:
                turns = dict(sorted(turns.items(), key=lambda kv: str((kv[1] or {}).get("ts", "")))[-KEEP:])
            storage.atomic_write_text(path(), json.dumps({"turns": turns}, ensure_ascii=False))
        return True
    except Exception:  # noqa: BLE001 - 登记只是给展开核对用
        return False


def get(turn_id: Any) -> dict[str, Any] | None:
    if not isinstance(turn_id, str) or not turn_id:
        return None
    row = _read().get(turn_id)
    if isinstance(row, dict):
        return {**row, "turn_id": turn_id}
    return None


def _rows() -> list[dict[str, Any]]:
    return [{**r, "turn_id": tid} for tid, r in _read().items() if isinstance(r, dict)]


def latest_in_thread(thread_id: Any) -> dict[str, Any] | None:
    """这条会话线里最近的一轮。"""
    if not isinstance(thread_id, str) or not thread_id:
        return None
    rows = [r for r in _rows() if r.get("thread_id") == thread_id]
    return max(rows, key=lambda r: str(r.get("ts") or "")) if rows else None


def _parse_ts(value):
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.astimezone()


def latest_for_who(who: Any, *, within_s: int = 900, now: datetime | None = None) -> dict[str, Any] | None:
    """同一凭据（ctx.who）within_s 秒内的最后一轮；没有 = None。绝不跨凭据、绝不取全局最近一问。"""
    if not isinstance(who, str) or not who:
        return None
    now = now or datetime.now().astimezone()
    best = None
    for r in _rows():
        if r.get("who") != who:
            continue
        ts = _parse_ts(r.get("ts"))
        if ts is None or (now - ts).total_seconds() > within_s or (now - ts).total_seconds() < -60:
            continue
        if best is None or str(r.get("ts") or "") > str(best.get("ts") or ""):
            best = r
    return best


def latest_for(question: Any) -> dict[str, Any] | None:
    """按提问原文找最近一轮（1015 第三批 R1 的老路；1018 起生产不再用它——追问带 parent_turn_id / thread_id）。"""
    q = " ".join(str(question or "").split())[:1000]
    if not q:
        return None
    rows = [r for r in _rows() if " ".join(str(r.get("q") or "").split()) == q]
    return max(rows, key=lambda r: str(r.get("ts") or "")) if rows else None
