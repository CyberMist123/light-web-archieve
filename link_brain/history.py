"""可见笔记的快照（批次 D · F1）：整篇重写可见 md 之前先存一份，可列出、可找回。

住 `<对象目录>/history/visible-YYYYMMDD-HHMMSS[-n]-<reason>.txt`。用 .txt 不用 .md：
.md 会进 Obsidian 搜索和图谱，里面的 dataviewjs 打开就跑，frontmatter 的 item_id 还会被当成同一篇。
reason 词表：restore / undo / render / heal。每篇只留最新 KEEP 份。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage

KEEP = 20
REASONS = ("restore", "undo", "render", "heal")
NAME_RE = re.compile(r"^visible-(\d{8})-(\d{6})(?:-(\d+))?-([a-z]+)\.txt$")


def history_dir(object_dir: Path) -> Path:
    return Path(object_dir) / "history"


def _sort_key(name: str) -> tuple:
    m = NAME_RE.match(name)
    if not m:
        return ("", "", 0)
    return (m.group(1), m.group(2), int(m.group(3) or 0))


def snapshot(object_dir: Path, text: str, reason: str) -> str:
    if reason not in REASONS:
        raise ValueError(f"快照原因不在词表里：{reason}")
    folder = history_dir(object_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 同一秒里的第 n 份（不管 reason）带 -n，取已有最大的 n + 1：保证排序就是写入顺序（旧的被修剪掉也不回头复用）
    d, t = stamp.split("-")
    same = [_sort_key(p.name)[2] or 1 for p in folder.iterdir() if _sort_key(p.name)[:2] == (d, t)]
    n = max(same) + 1 if same else 1
    name = f"visible-{stamp}{'' if n == 1 else f'-{n}'}-{reason}.txt"
    storage.atomic_write_text(folder / name, text)
    _prune(folder)
    return name


def _all(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.is_file() and NAME_RE.match(p.name)),
                  key=lambda p: _sort_key(p.name), reverse=True)


def _prune(folder: Path) -> None:
    for p in _all(folder)[KEEP:]:
        try:
            p.unlink()
        except OSError:
            pass


def list_snapshots(object_dir: Path) -> list[dict[str, Any]]:
    out = []
    for p in _all(history_dir(object_dir)):
        m = NAME_RE.match(p.name)
        d, t = m.group(1), m.group(2)
        ts = f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:4]}:{t[4:]}"
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({"name": p.name, "ts": ts, "reason": m.group(4), "bytes": size})
    return out


def read_snapshot(object_dir: Path, name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError(f"快照名不对：{name}")
    p = history_dir(object_dir) / name
    if not p.is_file():
        raise FileNotFoundError(f"快照不在了：{name}")
    return p.read_text(encoding="utf-8")


def latest(object_dir: Path, reason: str | None = None) -> str | None:
    for s in list_snapshots(object_dir):
        if reason is None or s["reason"] == reason:
            return s["name"]
    return None
