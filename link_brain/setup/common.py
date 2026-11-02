"""「开始」页向导后端的共用小件：结果形状、进度事件、安装错误、插件设置补丁。"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable

from ..errtext import errtext

Emit = Callable[[dict[str, Any]], None]


class SetupError(Exception):
    """装的过程中能说清原因的失败：code 是 CONVENTIONS §2 的故障码，message 是给人看的一句话。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


FALLBACK_LOG = "setup-run.log"
_fallback: dict[str, Any] = {"path": None}   # stdout 断了之后写哪；None = stdout 还通着


def fallback_log_path() -> Path:
    """stdout 管道断了（Obsidian 关掉）之后进度事件写到这里：`~/.link-brain/logs/setup-run.log`（跟 LINK_BRAIN_HOME 走）。"""
    from .. import storage
    return storage.link_brain_home() / "logs" / FALLBACK_LOG


def _is_broken_pipe(exc: BaseException) -> bool:
    import errno
    return isinstance(exc, BrokenPipeError) or (isinstance(exc, OSError) and exc.errno in (errno.EPIPE, errno.EINVAL))


def _switch_to_log(path: Path) -> None:
    """stdout 断了：以后的事件写日志；并把 fd 1 指到 /dev/null——不然解释器退出时 flush 又撞一次 BrokenPipe、退出码 120。"""
    import os
    _fallback["path"] = path
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
    except (OSError, ValueError, AttributeError):
        pass


def _append_log(path: Path, line: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass   # 日志也写不了就算了：进度照样在 _archive/setup-run.json 里（pipeline 每步都落盘）


def stdout_emit(event: dict[str, Any]) -> None:
    """install / run 的进度事件：一行一个 JSON，写 UTF-8 字节，立刻 flush（插件边读边画进度条）。

    1102：Obsidian 关掉后 stdout 管道断掉（BrokenPipeError / EPIPE / Windows 上的 EINVAL）——不再抛着把整轮炸掉，
    切到 `~/.link-brain/logs/setup-run.log` 接着写（带时间戳），子进程接着跑完。"""
    line = json.dumps(event, ensure_ascii=False) + "\n"
    if _fallback["path"] is not None:
        _append_log(_fallback["path"], _stamp() + line)
        return
    try:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:
            sys.stdout.write(line)
            sys.stdout.flush()
            return
        sys.stdout.flush()
        buffer.write(line.encode("utf-8"))
        buffer.flush()
    except (OSError, ValueError) as exc:   # ValueError：stdout 已经被关掉（I/O operation on closed file）
        if not _is_broken_pipe(exc) and not isinstance(exc, ValueError):
            raise
        path = fallback_log_path()
        _switch_to_log(path)
        _append_log(path, _stamp() + json.dumps({"type": "note", "text": "stdout 断了（Obsidian 关了？），进度改写到这里，安装在后台继续"},
                                                 ensure_ascii=False) + "\n")
        _append_log(path, _stamp() + line)


def _stamp() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S ")


def reset_fallback() -> None:
    """只给测试用：忘掉「stdout 已断」。"""
    _fallback["path"] = None


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
        return {"written": False, "path": str(path), "reason": f"插件设置写不进去：{errtext(exc)}"}
    return {"written": True, "path": str(path), "reason": ""}
