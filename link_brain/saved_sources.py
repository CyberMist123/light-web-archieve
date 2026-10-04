"""问收藏的「附加来源」：她在问收藏页「已保存」里存的回答和自己手写的判断。

数据在 vault `_archive/chat-archive.json` 的 `entries`（页面 chat-view.js 写，`{id, ts, kind: report|note, title, content, sources?}`），
不进 catalog-data、不进向量库。问答召回时由 `merge()` 这一个接入点按词法并进候选（不碰召回核心），
来源 id 统一带 `saved:` 前缀，证据字段身份是 `saved`（页面显示「我保存的」）。

短文本也要能中（10-04：手写「做梦是1」，问「做梦」「做梦是」都要找得到）：整句互相包含、或问题的词在里面出现就算中，
不走 BM25（几个字的条目在 BM25 里会被字段长度归一和 idf 压没）。任何读不到 / 坏数据 = 没有附加来源（fail-open）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import storage

PREFIX = "saved:"
FIELD = "saved"
FRONT_MAX = 3   # 强命中（整句包含 / 问题的词基本都在）最多几条排到候选最前面
WEAK_MAX = 5    # 弱命中（只中了一部分词）最多几条，插在 WEAK_SLOT 之后（一般落进「其他相关」）
WEAK_SLOT = 8
_GENERIC = {"ai", "系统", "项目", "功能", "内容", "相关"}
_CACHE: dict[str, Any] = {"stamp": None, "items": []}


def archive_path():
    return storage.vault_root() / "_archive" / "chat-archive.json"


def is_saved(item: dict[str, Any] | None) -> bool:
    return bool(item) and item.get("source_kind") == "saved"


def _item(entry: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    key, content = entry.get("id"), entry.get("content")
    if not key or not isinstance(content, str) or not content.strip():
        return None
    title = str(entry.get("title") or "").strip() or content.strip().split("\n", 1)[0][:80] or "我保存的"
    return {"id": PREFIX + str(key), "title": title, "author": "", "source_kind": "saved",
            "saved_id": str(key), "saved_kind": "note" if entry.get("kind") == "note" else "report",
            "saved_content": content, "ts": entry.get("ts"),
            "search_fields": {FIELD: content}, "search_text": content, "tags": [], "cats": [], "summary": ""}


def load() -> list[dict[str, Any]]:
    """已保存的条目 → 来源 item（按文件修改时间缓存）。"""
    path = archive_path()
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
        if _CACHE["stamp"] == stamp:
            return _CACHE["items"]
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    items = [it for it in (_item(e) for e in (entries if isinstance(entries, list) else [])) if it]
    _CACHE.update(stamp=stamp, items=items)
    return items


def _flat(text: str) -> str:
    from .retrieval import norm
    return re.sub(r"[\W_]+", "", norm(text))


def strength(question: str, item: dict[str, Any], terms) -> int:
    """2 = 强命中，1 = 弱命中，0 = 不中。"""
    from .retrieval import has, norm, variants
    q = _flat(question)
    hay_raw = norm(item.get("title", "") + "\n" + item.get("saved_content", ""))
    hay = _flat(hay_raw)
    if not q or not hay:
        return 0
    if (len(q) >= 2 and q in hay) or (len(hay) >= 2 and hay in q):
        return 2
    focused = [t for t in dict.fromkeys(norm(t) for t in terms or ()) if t and t not in _GENERIC]
    if not focused:
        return 0
    covered = sum(any(has(hay_raw, v) for v in variants(t)) for t in focused)
    if not covered:
        return 0
    return 2 if covered * 3 >= len(focused) * 2 else 1


def matching(question: str, saved: list[dict[str, Any]], terms) -> list[tuple[int, dict[str, Any]]]:
    hits = [(strength(question, it, terms), i, it) for i, it in enumerate(saved or [])]
    hits = [h for h in hits if h[0]]
    hits.sort(key=lambda h: (-h[0], h[1]))   # 同档按「已保存」里的顺序（新的在前）
    return [(s, it) for s, _, it in hits]


def merge(question: str, matches: list[dict[str, Any]], saved: list[dict[str, Any]], terms, *,
          excluded=(), after: int = 0) -> list[dict[str, Any]]:
    """把命中的「我保存的」并进候选：强命中插在第 after 位（保留的来源之后）、弱命中插在 WEAK_SLOT 之后；
    已经在候选里的（她保留 / 带上的）不重复，排除的不要。没命中 = 原样返回。"""
    try:
        excluded = set(excluded or ())
        have = {it.get("id") for it in matches}
        hits = [(s, it) for s, it in matching(question, saved, terms) if it["id"] not in excluded and it["id"] not in have]
        strong = [it for s, it in hits if s == 2][:FRONT_MAX]
        weak = [it for s, it in hits if s == 1][:WEAK_MAX]
        if not strong and not weak:
            return matches
        out = list(matches[:after]) + strong + list(matches[after:])
        slot = max(after + len(strong), min(len(out), WEAK_SLOT))
        return out[:slot] + weak + out[slot:]
    except Exception:  # noqa: BLE001 - 附加来源只是锦上添花，坏了照常回答
        return matches
