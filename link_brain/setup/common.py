"""「开始」页向导后端的共用小件：结果形状、进度事件、安装错误、插件设置补丁。"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable

Emit = Callable[[dict[str, Any]], None]


class SetupError(Exception):
    """装的过程中能说清原因的失败：code 是 CONVENTIONS §2 的故障码，message 是给人看的一句话。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def stdout_emit(event: dict[str, Any]) -> None:
    """install 的进度事件：一行一个 JSON，写 UTF-8 字节，立刻 flush（插件边读边画进度条）。"""
    line = json.dumps(event, ensure_ascii=False) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(line)
        sys.stdout.flush()
        return
    sys.stdout.flush()
    buffer.write(line.encode("utf-8"))
    buffer.flush()


def progress(emit: Emit | None, component: str, phase: str, done: int | None = None, total: int | None = None,
             text: str = "") -> None:
    if emit is None:
        return
    emit({"type": "progress", "component": component, "phase": phase,
          "done": int(done) if done is not None else None, "total": int(total) if total is not None else None,
          "text": text})


def mb(n_bytes: int | float | None) -> int | None:
    return None if n_bytes is None else int(round(float(n_bytes) / (1 << 20)))


# --------------------------------------------------------------------------
# 插件设置（vault/.obsidian/plugins/link-brain-actions/data.json）补丁
# --------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def apply_settings_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """把装好后要改的设置（只改给出的键）合进插件 data.json，原子写。

    插件开着时它内存里还有一份设置，下次保存会盖掉这里写的——所以 install 的 result 里同时带
    `settings_patch`，插件拿到后自己 merge 再保存（两边都写，谁先谁后结果一样）。
    插件目录不存在（没在 Obsidian 里用）就不建文件，只在 result 里带补丁。"""
    from .. import ai_config, storage
    path: Path = ai_config.data_json_path()
    if not patch:
        return {"written": False, "path": str(path), "reason": "没有要改的设置"}
    if not path.parent.is_dir():
        return {"written": False, "path": str(path), "reason": "插件目录不在（没在 Obsidian 里装插件），只在结果里带补丁"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError) as exc:
        return {"written": False, "path": str(path), "reason": f"插件设置读不了，没改：{type(exc).__name__}"}
    if not isinstance(raw, dict):
        return {"written": False, "path": str(path), "reason": "插件设置不是对象，没改"}
    try:
        storage.write_json(path, _deep_merge(raw, patch))
    except OSError as exc:
        return {"written": False, "path": str(path), "reason": f"插件设置写不进去：{type(exc).__name__}: {exc}"}
    return {"written": True, "path": str(path), "reason": ""}
