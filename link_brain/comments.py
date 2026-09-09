"""留言层（Lot 5）：人和 AI 在同一篇笔记上留言、互相戳、标已处理。

规格（docs/TASKBOOK.md Lot 5）：
- 可见 md 的留言层长这样，Obsidian 里看着就是几行「日期 角色」引用，没有协议词：

      > [!link-brain-comment]
      > 「20260909 人」这条留给 Fable 看
      <!-- link-brain: id=cmt2 actor=human target=fable status=open -->

- **只动留言层**：content 层字节一个不碰（读整文件 → 只替换 start/end 之间 → 写回）。
- 解析器要认 Owner 在 Obsidian 里**手写**的行（没有隐藏注释也算一条留言，actor=human/target=none）。
- 每次写同时追加对象级 `comments.jsonl`（可见 md 是给人看的，jsonl 是给机器和将来回放用的）。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import index as index_mod
from . import render as render_mod
from . import storage

EXIT_OK = 0
EXIT_ERROR = 1

# 角色 → 留言里显示的名字。没登记的角色原样显示（`ai:xxx` 去掉前缀）。
DISPLAY = {"human": "人", "owner": "人", "fable": "Fable", "gpt": "GPT", "claude": "Claude"}
TEXT_LINE = re.compile(r"^>\s*「(?P<date>\d{8})\s+(?P<who>[^」]+)」\s*(?P<text>.*)$")
META_LINE = re.compile(
    r"^<!--\s*link-brain:\s*id=(?P<id>\S+)\s+actor=(?P<actor>\S+)\s+"
    r"target=(?P<target>\S+)\s+status=(?P<status>\S+)\s*-->\s*$"
)


def display_name(actor: str) -> str:
    key = actor.lower()
    if key in DISPLAY:
        return DISPLAY[key]
    return actor.split(":", 1)[-1] if ":" in actor else actor


def actor_from_display(who: str) -> str:
    for actor, shown in DISPLAY.items():
        if shown == who and actor in ("human", "fable", "gpt", "claude"):
            return actor
    return "human" if who == "人" else who


@dataclass
class Comment:
    text: str
    date: str
    actor: str = "human"
    target: str = "none"
    status: str = "open"
    comment_id: str | None = None  # 手写的那种没有 id
    line: int = -1
    meta_line: int = -1
    extra: dict[str, Any] = field(default_factory=dict)


def parse_block(block_text: str) -> list[Comment]:
    """解析留言层。带隐藏注释的走注释；裸的手写行也算一条（actor=human/target=none）。"""
    lines = block_text.split("\n")
    out: list[Comment] = []
    for i, line in enumerate(lines):
        m = TEXT_LINE.match(line)
        if not m:
            continue
        c = Comment(
            text=m.group("text").strip(),
            date=m.group("date"),
            actor=actor_from_display(m.group("who").strip()),
            line=i,
        )
        # 隐藏注释就在下一行（渲染时紧跟正文行）
        for j in range(i + 1, min(i + 3, len(lines))):
            mm = META_LINE.match(lines[j].strip())
            if mm:
                c.comment_id = mm.group("id")
                c.actor = mm.group("actor")
                c.target = mm.group("target")
                c.status = mm.group("status")
                c.meta_line = j
                break
            if TEXT_LINE.match(lines[j]):
                break
        out.append(c)
    return out


def _visible_path(meta: dict[str, Any], vault: Path) -> Path | None:
    rel = meta.get("visible_note")
    if not rel:
        return None
    path = vault / rel
    return path if path.is_file() else None


def read_comments(path: Path) -> list[Comment]:
    text = path.read_text(encoding="utf-8")
    block, _ = render_mod.split_layers(text)
    return parse_block(block) if block else []


def _next_id(existing: list[Comment]) -> str:
    used = 0
    for c in existing:
        if c.comment_id and c.comment_id.startswith("cmt"):
            try:
                used = max(used, int(c.comment_id[3:]))
            except ValueError:
                continue
    return f"cmt{used + 1}"


def _replace_block(path: Path, new_block: str) -> None:
    """整文件读进来，只把 start..end 换掉——content 层一个字节都不动。"""
    text = path.read_text(encoding="utf-8")
    start = text.find(render_mod.COMMENTS_START)
    end = text.find(render_mod.COMMENTS_END)
    if start == -1 or end == -1:
        raise ValueError(f"{path.name} 里没有留言层标记，先跑一次 render")
    end += len(render_mod.COMMENTS_END)
    path.write_text(text[:start] + new_block + text[end:], encoding="utf-8")


def _jsonl_append(object_dir: Path, payload: dict[str, Any]) -> None:
    path = object_dir / "comments.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def add_comment(
    item_id: str,
    text: str,
    *,
    actor: str,
    target: str | None = None,
    vault: Path | None = None,
) -> Comment:
    vault = vault or storage.vault_root()
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, item_id)
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"库里没有 {item_id}")
    object_dir = vault / row["object_dir"]
    meta = json.loads((object_dir / "meta.json").read_text(encoding="utf-8"))
    path = _visible_path(meta, vault)
    if path is None:
        raise ValueError(f"{item_id} 没有可见 md（先跑 render）")

    existing = read_comments(path)
    comment = Comment(
        text=text.strip(),
        date=datetime.now().strftime("%Y%m%d"),
        actor=actor,
        target=target or "none",
        status="open",
        comment_id=_next_id(existing),
    )

    file_text = path.read_text(encoding="utf-8")
    block_start = file_text.find(render_mod.COMMENTS_START)
    block_end = file_text.find(render_mod.COMMENTS_END)
    if block_start == -1 or block_end == -1:
        raise ValueError(f"{path.name} 里没有留言层标记，先跑一次 render")
    inner = file_text[block_start + len(render_mod.COMMENTS_START) : block_end].rstrip("\n")

    added = [
        "> [!link-brain-comment]",
        f"> 「{comment.date} {display_name(actor)}」{comment.text}",
        f"<!-- link-brain: id={comment.comment_id} actor={actor} "
        f"target={comment.target} status=open -->",
    ]
    body = ([inner] if inner.strip() else []) + added
    new_block = "\n".join([render_mod.COMMENTS_START, *body, render_mod.COMMENTS_END])
    _replace_block(path, new_block)

    _jsonl_append(
        object_dir,
        {
            "op": "comment",
            "id": comment.comment_id,
            "item_id": item_id,
            "actor": actor,
            "target": comment.target,
            "status": "open",
            "text": comment.text,
            "at": datetime.now().astimezone().isoformat(),
        },
    )
    return comment


def resolve_comment(item_id: str, comment_id: str, *, as_actor: str, vault: Path | None = None) -> None:
    vault = vault or storage.vault_root()
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, item_id)
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"库里没有 {item_id}")
    object_dir = vault / row["object_dir"]
    meta = json.loads((object_dir / "meta.json").read_text(encoding="utf-8"))
    path = _visible_path(meta, vault)
    if path is None:
        raise ValueError(f"{item_id} 没有可见 md")

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(<!--\s*link-brain: id={re.escape(comment_id)}\s[^>]*?)status=open(\s*-->)")
    new_text, n = pattern.subn(r"\1status=resolved\2", text)
    if not n:
        raise ValueError(f"{item_id} 里没有 open 状态的 {comment_id}")
    path.write_text(new_text, encoding="utf-8")
    _jsonl_append(
        object_dir,
        {
            "op": "resolve",
            "id": comment_id,
            "item_id": item_id,
            "by": as_actor,
            "at": datetime.now().astimezone().isoformat(),
        },
    )


def iter_open(for_actor: str, vault: Path | None = None) -> Iterator[tuple[str, str, Comment]]:
    """扫全库，吐出戳给 for_actor 且还 open 的留言。"""
    vault = vault or storage.vault_root()
    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT item_id, title, object_dir FROM objects").fetchall()
    finally:
        conn.close()
    for row in rows:
        meta_path = vault / row["object_dir"] / "meta.json"
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        path = _visible_path(meta, vault)
        if path is None:
            continue
        for c in read_comments(path):
            if c.status == "open" and c.target == for_actor:
                yield row["item_id"], row["title"] or path.stem, c


def run_comment(args) -> int:
    try:
        c = add_comment(
            _resolve_target(args.target),
            args.text,
            actor=args.as_actor,
            target=getattr(args, "target_actor", None),
        )
    except ValueError as exc:
        print(f"留言失败: {exc}", file=sys.stderr)
        return EXIT_ERROR
    poke = f"，戳给 {c.target}" if c.target != "none" else ""
    print(f"{c.comment_id} 已写进留言层（{display_name(c.actor)}{poke}）")
    return EXIT_OK


def run_resolve(args) -> int:
    try:
        resolve_comment(_resolve_target(args.target), args.comment_id, as_actor=args.as_actor)
    except ValueError as exc:
        print(f"标记失败: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"{args.comment_id} 已标 resolved")
    return EXIT_OK


def run_inbox(args) -> int:
    found = list(iter_open(args.for_actor))
    if not found:
        print(f"{args.for_actor} 的收件箱是空的")
        return EXIT_OK
    for item_id, title, c in found:
        print(f"{item_id} | {title} | {c.comment_id or '手写'} 「{c.date} {display_name(c.actor)}」{c.text}")
    return EXIT_OK


def _resolve_target(target: str) -> str:
    conn = index_mod.connect()
    try:
        item_id = index_mod.resolve_item_id(conn, target)
    finally:
        conn.close()
    if not item_id:
        raise SystemExit(f"找不到对象：{target}")
    return item_id
