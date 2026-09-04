"""`read` / `search` 子命令。

`read`：默认打印 `meta.json`；`--brief` 打印标题+概要（≤5 行；有小模型 summary 就用它，
没有则退回正文前 120 字）；
`--full` 打印整个 `derived/agent.md`（Lot 3）。
`search`：按标题/正文 LIKE 查询，每条一行 `item_id | title | 1行概要 | tags | 日期`。

`--json`：给主模型用的机器可读版（`catch` 也复用同一份 `item_payload`），
结构见 `docs/FORMAT.md` §10。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import index as index_mod, llm as llm_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_OK = 0
EXIT_ERROR = 1


def dump_json(payload: Any) -> None:
    """机器可读输出统一走 stdout 的**原始字节**，按 UTF-8 编。

    Windows 控制台默认 GBK：`print()` 一碰到 emoji / ‼ 这种字（小红书标题里到处是）
    就 UnicodeEncodeError，调用方拿到的是崩溃而不是 JSON。写 buffer 绕开 locale。
    """
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # pytest 的 capsys 之类没有 buffer
        sys.stdout.write(line)
        return
    sys.stdout.flush()
    buffer.write(line.encode("utf-8"))
    buffer.flush()


def _one_line(text: str | None, limit: int = 120) -> str:
    text = (text or "").strip()
    text = " ".join(text.split())  # 折叠换行/空白成一行
    return text[:limit]


def _resolve_source_id(conn, target: str) -> tuple[str, str] | None:
    """target 是 item_id（`xhs-<id>`）或 URL/短链/分享文本 → `(source, source_id)`。"""
    if target.startswith("xhs-"):
        row = index_mod.get_object(conn, target)
        if row:
            return row["source"], row["source_id"]
        return xhs.SOURCE, target[len("xhs-") :]
    try:
        parsed = xhs.parse_input(target)
        return xhs.SOURCE, parsed["note_id"]
    except Exception:  # noqa: BLE001 - 不是能解析的链接，就当作原始 item_id 再试一次
        return None


# --------------------------------------------------------------------------
# 机器可读的对象摘要（catch / read --brief --json 共用）
# --------------------------------------------------------------------------


def _attachments_payload(
    note: dict[str, Any], meta: dict[str, Any], source_key: str, source_id: str
) -> dict[str, Any]:
    """附件：一个总状态 + 每个附件一条（下过字节的给绝对路径）。"""
    from . import attachments as attachments_mod

    object_dir = storage.object_dir(source_key, source_id)
    downloaded = attachments_mod.load_downloaded(source_key, source_id)
    items = []
    for att in note.get("attachments") or []:
        got = downloaded.get(att.get("doc_id"))
        local = object_dir / "attachments" / got["file"] if got and got.get("file") else None
        if local is not None and not local.exists():
            local = None
        items.append(
            {
                "name": att.get("name") or att.get("hint"),
                "doc_id": att.get("doc_id"),
                "status": "downloaded" if local else att.get("status"),
                "pages": att.get("page_num"),
                "url": att.get("url"),
                "file": str(local) if local else None,
            }
        )
    status = meta.get("attachments_status")
    if items and any(x["status"] == "downloaded" for x in items):
        status = "downloaded"
    return {"status": status, "items": items}


def item_payload(source_key: str, source_id: str, *, status: str | None = None) -> dict[str, Any]:
    """一个已归档对象 → 给主模型看的 dict。路径一律绝对路径（调用方 cwd 不确定）。

    `status` 是 `catch` 用来区分 new / hit 的；`read --json` 不传就没有这个键。
    """
    object_dir = storage.object_dir(source_key, source_id)
    meta = storage.read_json(object_dir / "meta.json")

    source_path = storage.raw_dir(source_key, source_id, meta["current_version"]) / "source.json"
    note = (storage.read_json(source_path).get("note") or {}) if source_path.exists() else {}

    extracted = llm_mod.extracted_data(llm_mod.load_extracted(source_key, source_id)) or {}
    summary = _one_line(extracted.get("summary") or note.get("body") or "", 120)

    visible_rel = meta.get("visible_note")
    visible_path: Path | None = storage.vault_root() / visible_rel if visible_rel else None
    if visible_path is not None and not visible_path.exists():
        visible_path = None

    tags: list[str] = []
    if visible_path is not None:
        # 可见 md 的 frontmatter 才是权威：原帖 hashtag + 小模型建议 + Owner 手写都在里面
        from .render import existing_tags

        tags = existing_tags(visible_path.read_text(encoding="utf-8"))
    if not tags:
        for tag in [*(note.get("hashtags") or []), *(extracted.get("tags") or [])]:
            if tag and tag not in tags:
                tags.append(tag)

    agent_md = object_dir / "derived" / "agent.md"

    payload: dict[str, Any] = {"item_id": meta["item_id"]}
    if status is not None:
        payload["status"] = status
    payload.update(
        title=meta.get("title"),
        summary=summary,
        tags=tags,
        kind=meta.get("kind"),
        visible_note=str(visible_path) if visible_path else None,
        agent_md=str(agent_md) if agent_md.exists() else None,
        attachments=_attachments_payload(note, meta, source_key, source_id),
        url=meta.get("canonical_url"),
    )
    return payload


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------


def run(args) -> int:
    as_json = getattr(args, "json", False)
    conn = index_mod.connect()
    try:
        resolved = _resolve_source_id(conn, args.target)
        if resolved is None:
            print(f"解析不出对象: {args.target}", file=sys.stderr)
            return EXIT_ERROR
        source, source_id = resolved
        object_dir = storage.object_dir(source, source_id)
        meta_path = object_dir / "meta.json"
        if not meta_path.exists():
            print(f"没有归档过: {args.target}", file=sys.stderr)
            return EXIT_ERROR
        meta = storage.read_json(meta_path)

        if getattr(args, "brief", False):
            if as_json:
                dump_json(item_payload(source, source_id))
                return EXIT_OK
            raw_dir = storage.raw_dir(source, source_id, meta["current_version"])
            source_path = raw_dir / "source.json"
            body = ""
            if source_path.exists():
                body = (storage.read_json(source_path).get("note") or {}).get("body") or ""
            extracted = llm_mod.extracted_data(llm_mod.load_extracted(source, source_id))
            summary = _one_line((extracted or {}).get("summary") or body, 120)
            title = meta.get("title") or "（无标题）"
            print(f"# {title}")
            print(summary or "（无概要）")
            return EXIT_OK

        if getattr(args, "full", False):
            agent_md_path = object_dir / "derived" / "agent.md"
            if not agent_md_path.exists():
                print(f"还没渲染过 agent.md（先跑 render {meta['item_id']}）", file=sys.stderr)
                return EXIT_ERROR
            text = agent_md_path.read_text(encoding="utf-8")
            if as_json:
                dump_json(
                    {
                        "item_id": meta["item_id"],
                        "agent_md": str(agent_md_path),
                        "markdown": text,
                    }
                )
                return EXIT_OK
            print(text)
            return EXIT_OK

        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return EXIT_OK
    finally:
        conn.close()


def run_search(args) -> int:
    as_json = getattr(args, "json", False)
    conn = index_mod.connect()
    try:
        rows = index_mod.search(conn, args.query, limit=args.limit)
        if as_json:
            items = [
                {
                    "item_id": row["item_id"],
                    "title": row["title"],
                    "summary": _one_line(row["body"], 120),
                    "tags": json.loads(row["tags"] or "[]"),
                    "kind": row["kind"],
                    "url": row["canonical_url"],
                    "first_archived": (row["first_archived_at"] or "")[:10],
                }
                for row in rows
            ]
            dump_json({"found": len(items), "items": items})
            return EXIT_OK
        for row in rows:
            tags = json.loads(row["tags"] or "[]")
            tags_str = ",".join(tags) if tags else "(无)"
            summary = _one_line(row["body"], 60)
            date = (row["first_archived_at"] or "")[:10]
            print(f"{row['item_id']} | {row['title'] or '(无标题)'} | {summary or '(无概要)'} | {tags_str} | {date}")
        return EXIT_OK
    finally:
        conn.close()
