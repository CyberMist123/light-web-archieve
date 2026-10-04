import json

from . import storage


def additional_sources():
    path = storage.vault_root() / "_archive" / "chat-archive.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        return []
    return [{"id": "saved:" + str(entry["id"]),
             "title": entry.get("title") or entry.get("content", "")[:80] or "我保存的",
             "author": "我", "source_kind": "saved", "saved_id": entry["id"],
             "saved_content": entry.get("content", ""),
             "search_fields": {"saved": entry.get("content", "")},
             "search_text": entry.get("content", ""), "tags": [], "cats": []}
            for entry in entries if isinstance(entry, dict) and entry.get("id") and entry.get("content")]


def matching_sources(question, items):
    from .retrieval import norm
    query = norm(question)
    return [item for item in items if item.get("source_kind") == "saved" and query
            and query in norm(item.get("title", "") + " " + item.get("saved_content", ""))]
