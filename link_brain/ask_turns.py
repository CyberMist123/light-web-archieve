"""问收藏的轮次登记（1015 第二批 ask 车）：每一答发一个 turn_id，记下这一答的问题、目录 / 来源 id、理解和技能。

「展开」按 turn_id + 那几条 id 走后端（ask.answer(expand=…)），不再拿「上一答」的字面话术再问一遍——
以前前端的「展开重点细节」发固定一句话，被当成新话题重搜（F 节 chat-view.js:893、ask.py:744）。

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
    return row if isinstance(row, dict) else None
