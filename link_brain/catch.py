"""`catch` 子命令：主模型的入口。

给它一整条聊天消息原文，它自己找里面的小红书链接、归档（命中索引就是 HIT，不联网）、
**只往 stdout 打一个 JSON**，让调用方一眼判断要不要展开：

    {"found": 1, "items": [{"item_id": "...", "status": "new", ...}]}

消息里没有小红书链接就是 `{"found": 0, "items": []}`，零成本。
JSON 结构见 `docs/FORMAT.md` §10。

硬约束 8：这里**不起 HTTP 服务、不起 MCP 服务**。TG / CMX 端就是 Bash 直调这个 CLI。
所以 stdout 只许有那一个 JSON —— 日志一律走 stderr，渲染也不开 verbose。
"""

from __future__ import annotations

import sys
from typing import Any
from urllib.parse import urlsplit

from . import ingest as ingest_mod, read as read_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_OK = 0
EXIT_ERROR = 1

# 只认小红书；消息里的其它链接一律不碰（V1 没有别的 adapter）
XHS_HOSTS = ("xiaohongshu.com", "xhslink.cn", "xhslink.com")
# URL_RE 已经排掉了大部分中文标点，这里再收一遍粘在链接尾巴上的收尾符号
TRAILING = "，。、；：！？）)]】》>\"'“”‘’"


def _is_xhs(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in XHS_HOSTS)


def find_xhs_urls(message: str) -> list[str]:
    """从任意消息全文里抠出小红书链接，按出现顺序去重。"""
    found: list[str] = []
    for match in xhs.URL_RE.finditer(message or ""):
        url = match.group(0).rstrip(TRAILING)
        if _is_xhs(url) and url not in found:
            found.append(url)
    return found


def _ensure_rendered(
    source_key: str, source_id: str, *, force: bool, extract: bool
) -> None:
    """保证可见 md / agent.md 在盘上。

    HIT 且文件都在 → 什么都不做（vision 会 spawn 子进程，白花钱）。
    新归档、或者可见 md 不见了（被删/改名）→ 补渲染一次。
    `verbose` 永远传 False：`render_item` 的 verbose 打的是 stdout，会污染 JSON。
    """
    meta_path = storage.object_dir(source_key, source_id) / "meta.json"
    rel = storage.read_json(meta_path).get("visible_note") if meta_path.exists() else None
    have = bool(rel) and (storage.vault_root() / rel).exists()
    if not (force or extract or not have):
        return
    from . import render as render_mod

    render_mod.render_item(source_key, source_id, verbose=False, llm=extract)


def _catch_one(
    url: str, *, message: str, origin: str, actor: str, verbose: bool, extract: bool
) -> dict[str, Any]:
    try:
        summary = ingest_mod.ingest_url(
            url,
            origin=origin,
            actor=actor,
            ingest_kind="shared",
            note=message,
            verbose=verbose,
        )
    except Exception as exc:  # noqa: BLE001 - 一条链接抓挂了不该带走整条消息
        return {
            "item_id": None,
            "status": "error",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }

    status = "hit" if summary.get("hit") else "new"
    source_key, source_id = xhs.SOURCE, summary["note_id"]

    render_error = None
    try:
        _ensure_rendered(source_key, source_id, force=(status == "new"), extract=extract)
    except Exception as exc:  # noqa: BLE001 - 渲染失败不该吞掉已经落盘的归档
        render_error = f"渲染失败: {type(exc).__name__}: {exc}"

    try:
        payload = read_mod.item_payload(source_key, source_id, status=status)
    except Exception as exc:  # noqa: BLE001
        return {
            "item_id": summary.get("item_id"),
            "status": "error",
            "url": url,
            "error": f"读归档失败: {type(exc).__name__}: {exc}",
        }
    if render_error:
        payload["error"] = render_error
    return payload


def catch_message(
    message: str,
    *,
    origin: str = "cli",
    actor: str = "human",
    verbose: bool = False,
    extract: bool = False,
) -> dict[str, Any]:
    """一条消息 → `{"found": N, "items": [...]}`（同一篇笔记出现两次只算一条）。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in find_xhs_urls(message):
        entry = _catch_one(
            url, message=message, origin=origin, actor=actor, verbose=verbose, extract=extract
        )
        item_id = entry.get("item_id")
        if item_id:
            if item_id in seen:
                continue
            seen.add(item_id)
        items.append(entry)
    return {"found": len(items), "items": items}


def run(args) -> int:
    payload = catch_message(
        args.message,
        origin=args.origin,
        actor=args.actor,
        verbose=getattr(args, "verbose", False),
        extract=getattr(args, "extract", False),
    )
    read_mod.dump_json(payload)
    if any(item.get("status") == "error" for item in payload["items"]):
        print("catch: 有链接没归档成功，详见 JSON 里的 error 字段", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK
