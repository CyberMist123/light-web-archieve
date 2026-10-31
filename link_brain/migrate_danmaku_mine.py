r"""一次性迁移（1031 作者「弹幕直接复用批注」）：`_archive/bilibili/<BV>/danmaku-mine.json` → 这篇 `notes.json` 里的批注。

以前笔记页视频下面那条「发弹幕」存在 danmaku-mine.json；现在用户自己的弹幕 = 带视频时间 `video_t` 的批注（FORMAT.md「B 站弹幕」），
那套存储去掉了。这里把已有的条目一条不丢地转成批注：

- 每条 → `{id: "adm-<原 id>", ts: <原 created_at>, text, to_fable: false, video_t: <原 time，3 位小数>, migrated_from: "danmaku-mine"}`；
  颜色 / 字号 / 模式不带（以前只发过白色 25 号滚动，批注弹幕一律这样画）。
- 写 notes.json 走批注现有的写法（`note.load_notes` / `note.save_notes`：读坏了报错不碰、原子写），只往 `annotations` 末尾追加，
  别的键（⭐、草稿、墓碑）原样。同一个 id 已经在（迁过一次）或在删除墓碑里（用户删了）就不再加——可以重跑。
- 写成功后原文件改名 `danmaku-mine.json.migrated`（已有同名就加时间戳），不删。主文件不在、只剩上次换名换到一半的 `.bak` 时迁 `.bak`。
- 原文件读不懂、notes.json 读坏了：这一篇跳过并报出来，什么都不改。

用法（部署时跑一次，先 `--dry-run` 看看）：
    python -m link_brain.migrate_danmaku_mine --dry-run
    python -m link_brain.migrate_danmaku_mine [--vault <收藏库路径>]
输出一行 JSON：{moved, skipped, errors, files:[{source_id, path, status, added, kept_existing, renamed_to|error}]}；有错误退出码 1。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import note, storage
from .errtext import errtext

MINE_FILE = "danmaku-mine.json"
SOURCE = "bilibili"
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


def find_files(archive: Path | None = None) -> list[Path]:
    """每篇一个：主文件优先，主文件不在才认 `.bak`。"""
    base = (archive or storage.archive_root()) / SOURCE
    if not base.is_dir():
        return []
    out = []
    for obj in sorted(p for p in base.iterdir() if p.is_dir() and _SID_RE.match(p.name)):
        main, bak = obj / MINE_FILE, obj / (MINE_FILE + ".bak")
        if main.is_file():
            out.append(main)
        elif bak.is_file():
            out.append(bak)
    return out


def _clean_text(s: Any) -> str:
    return re.sub(r"\s{2,}", " ", re.sub(r"[\r\n\t]+", " ", str(s or ""))).strip()


def read_mine(path: Path) -> list[dict[str, Any]]:
    """读不懂抛 ValueError（不许当空的迁、更不许改名）。不合格的条目（没时间 / 没字）跳过。"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path.name} 读不懂：{errtext(exc)}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise ValueError(f"{path.name} 没有 items 数组")
    out = []
    for r in doc["items"]:
        if not isinstance(r, dict):
            continue
        try:
            t = float(r.get("time"))
        except (TypeError, ValueError):
            continue
        text = _clean_text(r.get("text"))
        if t < 0 or t != t or not text:
            continue
        out.append({**r, "time": t, "text": text})
    return out


def to_annotation(rec: dict[str, Any], index: int) -> dict[str, Any]:
    raw_id = _ID_RE.sub("", str(rec.get("id") or ""))[:40] or f"n{index}"
    ts = rec.get("created_at") if isinstance(rec.get("created_at"), str) and rec.get("created_at") else None
    return {
        "id": "adm-" + raw_id,
        "ts": ts or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "text": rec["text"],
        "to_fable": False,
        "video_t": round(rec["time"], 3),
        "migrated_from": "danmaku-mine",
    }


def _renamed_target(path: Path) -> Path:
    target = path.parent / (MINE_FILE + ".migrated")
    if target.exists():
        target = path.parent / (MINE_FILE + ".migrated-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    return target


def migrate_one(path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    source_id = path.parent.name
    row: dict[str, Any] = {"source_id": source_id, "path": str(path), "added": 0, "kept_existing": 0}
    try:
        items = read_mine(path)
        data = note.load_notes(SOURCE, source_id)
    except (ValueError, note.NotesCorrupt) as exc:
        return {**row, "status": "error", "error": errtext(exc)}
    tomb = set(data.get("deleted") or []) if isinstance(data.get("deleted"), list) else set()
    have = {a.get("id") for a in data["annotations"] if isinstance(a, dict) and a.get("id")}
    new = []
    for i, rec in enumerate(items):
        a = to_annotation(rec, i)
        if a["id"] in have or a["id"] in tomb:
            row["kept_existing"] += 1
            continue
        have.add(a["id"])
        new.append(a)
    row["added"] = len(new)
    target = _renamed_target(path)
    if dry_run:
        return {**row, "status": "dry_run", "renamed_to": str(target)}
    try:
        if new:
            data["annotations"].extend(new)
            note.save_notes(SOURCE, source_id, data)
        os.replace(path, target)
    except OSError as exc:
        return {**row, "status": "error", "error": errtext(exc)}
    return {**row, "status": "migrated", "renamed_to": str(target)}


def run(*, dry_run: bool = False, archive: Path | None = None) -> dict[str, Any]:
    files = [migrate_one(p, dry_run=dry_run) for p in find_files(archive)]
    return {
        "dry_run": dry_run,
        "moved": sum(1 for f in files if f["status"] == "migrated"),
        "skipped": sum(1 for f in files if f["status"] == "dry_run"),
        "errors": sum(1 for f in files if f["status"] == "error"),
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m link_brain.migrate_danmaku_mine", description="把 B 站 danmaku-mine.json 迁成带 video_t 的批注（一次性）")
    ap.add_argument("--dry-run", action="store_true", help="只列出要迁什么，不写不改名")
    ap.add_argument("--vault", help="收藏库路径（不填按 LINK_BRAIN_VAULT / ~/.link-brain/config.json / 程序目录/vault）")
    args = ap.parse_args(argv)
    if args.vault:
        os.environ[storage.ENV_VAULT] = str(Path(args.vault).expanduser().resolve())
    result = run(dry_run=args.dry_run)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
