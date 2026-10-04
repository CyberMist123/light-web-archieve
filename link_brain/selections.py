"""选集（10-04）：目录页把选中的几篇存成一个有名字的「选集」，给 AI（本地 MCP / 远程阅读）按名字取。

使用场景：她在目录页多选 → 右键「给 AI（存成选集）」→ 起名（默认「主题+日期」，可改，这个名字就是「暗号」）→
对 AI 说「看一下选集 xxx」，AI 用 list / get 这两个只读函数拿到这几篇的标题、链接、机读版路径和正文。

存储：vault `_archive/selections.json` = {"selections": [{"name", "ids": [item id…], "created_at"}]}，由目录页（JS）写；
这里只读。文件缺 / 坏 = 没有选集（fail-open，不报错）。篇目按 catalog-data 对（删掉的篇目跳过并记 missing）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from . import storage

FILE = "selections.json"
TEXT_PER_ITEM = 8000      # 每篇机读版正文最多带多少字；更多的用 read / 打开 agent_md 读
TEXT_TOTAL = 40000        # 一次取选集所有篇加起来最多带多少字


def path(vault: Path | None = None) -> Path:
    return (vault or storage.vault_root()) / "_archive" / FILE


def load(vault: Path | None = None) -> list[dict[str, Any]]:
    """[{name, ids, created_at}]，新的在前；格式不对的条目丢掉。"""
    try:
        doc = json.loads(path(vault).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = doc.get("selections") if isinstance(doc, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        ids = [i for i in (row.get("ids") or []) if isinstance(i, str) and i] if isinstance(row.get("ids"), list) else []
        if name and ids:
            out.append({"name": name, "ids": list(dict.fromkeys(ids)), "created_at": str(row.get("created_at") or "")})
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out


def _key(s: str) -> str:
    return re.sub(r"[\s「」『』\"'“”‘’《》<>·・_\-]+", "", str(s or "")).casefold()


def find(name: str, rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
    """按名字找：先原样，再忽略空格 / 引号 / 大小写，再唯一包含；返回 (选集, 候选名)。"""
    want = str(name or "").strip()
    for r in rows:
        if r["name"] == want:
            return r, []
    k = _key(want)
    if not k:
        return None, []
    exact = [r for r in rows if _key(r["name"]) == k]
    if exact:
        return exact[0], []
    part = [r for r in rows if k in _key(r["name"]) or _key(r["name"]) in k]
    if len(part) == 1:
        return part[0], []
    return None, [r["name"] for r in part]


def _items() -> dict[str, dict[str, Any]]:
    try:
        from .ask import load_items
        return {str(it.get("id")): it for it in load_items()}
    except Exception:  # noqa: BLE001 - 目录数据坏了 = 对不上标题，不拖垮
        return {}


def list_selections(vault: Path | None = None) -> dict[str, Any]:
    """所有选集：名字、创建时间、篇数、每篇标题（AI 可以主动说「你之前存了选集 xxx」）。"""
    rows = load(vault)
    items = _items()
    out = [{"name": r["name"], "created_at": r["created_at"], "count": len(r["ids"]),
            "titles": [str(items[i].get("title") or i) if i in items else f"（已不在库里：{i}）" for i in r["ids"]]}
           for r in rows]
    return {"status": "ok", "count": len(out), "selections": out,
            "hint": "她说「看一下选集 xxx」时，用选集名取这几篇（取选集的那个工具）"}


def get_selection(name: str, *, paths: Callable[[dict[str, Any]], dict[str, Any]],
                  read_text: Callable[[dict[str, Any]], str | None], vault: Path | None = None) -> dict[str, Any]:
    """按名字取一个选集。paths(item) 给这一篇对外的路径字段（本地 = 绝对路径；远程 = 过了白名单的相对路径，
    读不到的给 None）；read_text(item) 给机读版正文（不让读 = None）。正文按 TEXT_PER_ITEM / TEXT_TOTAL 截断。"""
    if not isinstance(name, str) or not name.strip():
        return {"status": "error", "error": "name 不能为空（选集名字，比如她说的「选集 xxx」里的 xxx）"}
    rows = load(vault)
    hit, maybe = find(name, rows)
    if not hit:
        return {"status": "error", "error": f"没有叫「{name.strip()}」的选集",
                "did_you_mean": maybe, "available": [r["name"] for r in rows][:30]}
    items = _items()
    budget = TEXT_TOTAL
    out, missing = [], []
    for i in hit["ids"]:
        it = items.get(i)
        if not it:
            missing.append(i)
            continue
        row: dict[str, Any] = {"item_id": i, "title": it.get("title"), "source_url": it.get("url"),
                               "tags": it.get("tags") or [], "summary": it.get("summary") or "", **paths(it)}
        text = read_text(it) if budget > 0 else None
        if isinstance(text, str):
            cap = min(TEXT_PER_ITEM, budget)
            row["text"] = text[:cap]
            row["text_total_chars"] = len(text)
            row["truncated"] = len(text) > cap
            budget -= len(row["text"])
        out.append(row)
    return {"status": "ok", "name": hit["name"], "created_at": hit["created_at"], "count": len(out),
            "items": out, "missing": missing,
            "note": "text 是机读版正文（agent.md）的开头；truncated=true 的按 agent_md 路径读全文"}


def read_agent(item: dict[str, Any], vault: Path | None = None) -> str | None:
    rel = item.get("agent_md")
    if not isinstance(rel, str) or not rel:
        return None
    try:
        return ((vault or storage.vault_root()) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
