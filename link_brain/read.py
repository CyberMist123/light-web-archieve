"""`read` / `search` 子命令。

`read`：默认打印 `meta.json`；`--brief` 打印标题+概要（≤5 行；有小模型 summary 就用它，
没有则退回正文前 120 字）；
`--full` 打印整个 `derived/agent.md`（Lot 3）。
`search`：按标题/正文 LIKE 查询，每条一行 `item_id | title | 1行概要 | tags | 日期`。
"""

from __future__ import annotations

import json
import sys

from . import index as index_mod, llm as llm_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_OK = 0
EXIT_ERROR = 1


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


def run(args) -> int:
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
            print(agent_md_path.read_text(encoding="utf-8"))
            return EXIT_OK

        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return EXIT_OK
    finally:
        conn.close()


def run_search(args) -> int:
    conn = index_mod.connect()
    try:
        rows = index_mod.search(conn, args.query, limit=args.limit)
        for row in rows:
            tags = json.loads(row["tags"] or "[]")
            tags_str = ",".join(tags) if tags else "(无)"
            summary = _one_line(row["body"], 60)
            date = (row["first_archived_at"] or "")[:10]
            print(f"{row['item_id']} | {row['title'] or '(无标题)'} | {summary or '(无概要)'} | {tags_str} | {date}")
        return EXIT_OK
    finally:
        conn.close()
