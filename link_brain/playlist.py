"""按标签连播（批次 D · F6-a）：纯读 catalog-data + 对象 manifest，不写库、不加锁、不联网。

`playlist --tag X [--order newest|oldest|shuffle] [--seed N] [--start ITEM]` / `playlist --tags`。
stdout 只有最后一行 JSON；路径都是收藏库相对（插件 lbPath + getResourcePath 转成可播放地址）。
退出码：0 有结果；1 目录还没建好；2 没命中。
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from . import storage

ORDERS = ("newest", "oldest", "shuffle")


class PlaylistError(Exception):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def _norm(tag: Any) -> str:
    return str(tag or "").strip().lstrip("#").strip().casefold()


def tag_match(item_tags: list[Any], q: str) -> bool:
    q = _norm(q)
    if not q:
        return False
    for t in item_tags or []:
        n = _norm(t)
        if n == q or n.startswith(q + "/"):
            return True
    return False


def _catalog() -> dict[str, Any]:
    path = storage.archive_root() / "catalog-data.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PlaylistError("目录还没建好：先刷新目录", 1) from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise PlaylistError("目录还没建好：先刷新目录", 1)
    return data


def _rel(p: Path) -> str:
    return str(p.relative_to(storage.vault_root())).replace("\\", "/")


def video_of(item: dict[str, Any]) -> dict[str, Any]:
    """→ {status: ok|missing|not_downloaded|none, video, poster, duration_sec, width, height, bytes}"""
    item_id = str(item.get("id") or "")
    source, _, source_id = item_id.partition("-")
    obj = None
    if item.get("agent_md"):
        obj = (storage.vault_root() / item["agent_md"]).parent.parent
    if obj is None or not (obj / "meta.json").is_file():
        src = item.get("source") or source
        sid = item.get("source_id") or source_id
        obj = storage.object_dir(src, sid) if src and sid else None
    if obj is None or not (obj / "meta.json").is_file():
        return {"status": "none"}
    try:
        meta = json.loads((obj / "meta.json").read_text(encoding="utf-8"))
        raw = obj / "raw" / storage.version_name(int(meta["current_version"]))
        manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "none"}

    def resolve(file: str | None) -> Path | None:
        if not file:
            return None
        return obj / file if file.startswith("raw/") else raw / file

    media = manifest.get("media") or []
    vids = [m for m in media if m.get("role") == "video"]
    if not vids:
        return {"status": "none"}
    ok = next((m for m in vids if m.get("download_status") == "ok"), None)
    if ok is None:
        return {"status": "not_downloaded"}
    path = resolve(ok.get("file"))
    if path is None or not path.is_file():
        return {"status": "missing"}
    cover = next((m for m in media if m.get("role") == "video_cover" and m.get("file")), None)
    cpath = resolve(cover.get("file")) if cover else None
    info: dict[str, Any] = {}
    try:
        src = json.loads((raw / "source.json").read_text(encoding="utf-8"))
        info = ((src.get("note") or {}).get("video") or {}) if isinstance(src, dict) else {}
    except (OSError, ValueError):
        info = {}
    return {"status": "ok", "video": _rel(path), "poster": _rel(cpath) if cpath and cpath.is_file() else "",
            "duration_sec": info.get("duration_sec"), "width": info.get("width"), "height": info.get("height"),
            "bytes": path.stat().st_size}


def _is_video(item: dict[str, Any]) -> bool:
    return item.get("kind") == "video"


def tags_summary() -> dict[str, Any]:
    data = _catalog()
    counts: dict[str, dict[str, Any]] = {}
    for it in data["items"]:
        if not _is_video(it):
            continue
        v = video_of(it)
        if v["status"] == "none":
            continue
        for t in it.get("tags") or []:
            key = str(t).strip().lstrip("#").strip()
            if not key:
                continue
            row = counts.setdefault(key.casefold(), {"tag": key, "count": 0, "playable": 0})
            row["count"] += 1
            row["playable"] += 1 if v["status"] == "ok" else 0
    tags = sorted((r for r in counts.values() if r["count"] >= 1), key=lambda r: (-r["playable"], -r["count"], r["tag"]))
    return {"ok": True, "code": "", "message": f"{len(tags)} 个标签下有视频", "tags": tags}


def build(tag: str, order: str = "newest", seed: int | None = None, start: str | None = None) -> dict[str, Any]:
    if order not in ORDERS:
        raise PlaylistError(f"顺序不认得：{order}", 2)
    data = _catalog()
    label = str(tag or "").strip().lstrip("#")
    hits = [it for it in data["items"] if _is_video(it) and tag_match(it.get("tags") or [], label)]
    items, skipped = [], []
    for it in hits:
        v = video_of(it)
        if v["status"] == "ok":
            items.append({"item_id": it.get("id"), "title": it.get("title") or "", "author": it.get("author") or "",
                          "note": it.get("note") or "", "video": v["video"], "poster": v["poster"],
                          "duration_sec": v["duration_sec"], "width": v["width"], "height": v["height"],
                          "bytes": v["bytes"], "date": it.get("date") or "", "_ts": str(it.get("ts") or "")})
        elif v["status"] in ("not_downloaded", "missing"):
            skipped.append({"item_id": it.get("id"), "title": it.get("title") or "",
                            "reason": "视频没下载" if v["status"] == "not_downloaded" else "视频文件不在了"})
    if not items:
        sugg: dict[str, int] = {}
        q = _norm(label)
        for it in data["items"]:
            if not _is_video(it):
                continue
            for t in it.get("tags") or []:
                k = str(t).strip().lstrip("#")
                if q and q in k.casefold() and k.casefold() != q:
                    sugg[k] = sugg.get(k, 0) + 1
        suggestions = [k for k, _ in sorted(sugg.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
        msg = f"没有带 #{label} 的视频" + (f"（{len(skipped)} 条没下载）" if skipped else "")
        if suggestions:
            msg += "，是不是要找：" + "、".join("#" + s for s in suggestions)
        return {"ok": False, "code": "", "message": msg, "tag": label, "order": order, "seed": seed,
                "start_index": 0, "items": [], "skipped": skipped, "suggestions": suggestions, "_exit": 2}
    items.sort(key=lambda x: x["_ts"], reverse=True)
    if order == "oldest":
        items.reverse()
    elif order == "shuffle":
        if seed is None:
            seed = int(time.time() * 1000)
        items.sort(key=lambda x: str(x["item_id"]))
        random.Random(seed).shuffle(items)
    start_index = 0
    if start:
        idx = next((i for i, x in enumerate(items) if x["item_id"] == start), -1)
        if idx >= 0:
            if order == "shuffle":
                items.insert(0, items.pop(idx))
            else:
                start_index = idx
    for x in items:
        x.pop("_ts", None)
    msg = f"#{label} 有 {len(items)} 条视频" + (f"（{len(skipped)} 条没下载，跳过了）" if skipped else "")
    return {"ok": True, "code": "", "message": msg, "tag": label, "order": order, "seed": seed,
            "start_index": start_index, "items": items, "skipped": skipped, "suggestions": []}


def add_parser(sub) -> None:
    p = sub.add_parser("playlist", help="按标签列出能播的视频（连播用；纯读）")
    p.add_argument("--tag", help="标签（带不带 # 都行，子标签也算）")
    p.add_argument("--tags", action="store_true", help="列出有视频的标签")
    p.add_argument("--order", default="newest", choices=ORDERS)
    p.add_argument("--seed", type=int)
    p.add_argument("--start", help="从这一条开始（item_id）")
    p.add_argument("--json", action="store_true")


def run(args) -> int:
    from .read import dump_json
    try:
        if args.tags:
            out, code = tags_summary(), 0
        elif args.tag:
            out = build(args.tag, args.order, args.seed, args.start)
            code = out.pop("_exit", 0)
        else:
            raise PlaylistError("要给 --tag 或 --tags", 2)
    except PlaylistError as exc:
        out, code = {"ok": False, "code": "", "message": str(exc), "items": [], "skipped": [], "suggestions": []}, exc.exit_code
    print(out.get("message") or "", file=sys.stderr)
    dump_json(out)
    return code
