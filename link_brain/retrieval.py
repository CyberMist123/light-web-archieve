"""Local field-weighted retrieval. No model or network needed for search."""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ALIASES = json.loads((Path(__file__).parent / "assets/search-aliases.json").read_text(encoding="utf-8"))
WEIGHTS = {"title": 12, "tags": 10, "body": 7, "attachments": 6, "transcript": 6, "ocr": 5, "comments": 3, "summary": 2, "author": 1}


def norm(text):
    return unicodedata.normalize("NFKC", str(text or "")).casefold().strip()


def variants(term):
    term = norm(term)
    expanded = [term]
    for group in ALIASES:
        if term in group or (term == "音" and "音乐" in group):
            expanded.extend(group)
    return list(dict.fromkeys(expanded))


def fields(item):
    return {"title": item.get("title", ""), "tags": " ".join(item.get("tags") or []),
            "summary": item.get("summary", ""), "author": item.get("author", ""),
            **(item.get("search_fields") or {"body": item.get("search_text", "")})}


def score(item, terms, *, require_all=False):
    fs = {key: norm(value) for key, value in fields(item).items()}
    total = 0.0
    for term in terms:
        term = norm(term)
        if not term:
            continue
        best = max((WEIGHTS.get(key, 1) * (1 if v == term else .75)
                    for v in variants(term) for key, text in fs.items() if v in text), default=0)
        if not best and re.fullmatch(r"[a-z]{4,}", term):
            if any(SequenceMatcher(None, term, word).ratio() >= .8
                   for word in re.findall(r"[a-z]+", fs["title"] + " " + fs["tags"])):
                best = 2
        if not best and require_all:
            return 0
        total += best
    return total


def excerpts(item, terms, limit=800):
    """Return source-labelled verbatim windows; prefer matching original fields."""
    ranked = []
    for key, value in fields(item).items():
        if key in {"title", "tags", "author", "summary"} or not value:
            continue
        text = str(value)
        positions = [norm(text).find(v) for t in terms for v in variants(t) if v in norm(text)]
        if positions:
            pos = min(positions)
            start = max(0, pos - 100)
            ranked.append((WEIGHTS.get(key, 1), key, text[start:]))
    if not ranked:
        ranked = [(1, "body", str(item.get("search_text") or item.get("summary") or ""))]
    ranked.sort(reverse=True)
    budget = max(1, limit // len(ranked))
    return [{"field": key, "text": text[:budget]} for _, key, text in ranked]


def search(query, limit=20):
    from .ask import load_items, query_terms
    from . import storage
    items = load_items()
    terms = [norm(x) for x in query.split() if x.strip()]
    tag_query = query.startswith("#")
    hits = []
    for item in items:
        s = 1 if not terms else (10 if any(norm(t).lstrip("#") in query.lower().split("#")[1:] for t in item.get("tags", [])) else 0) if tag_query else score(item, terms, require_all=True)
        if s:
            hits.append((s, item))
    if not hits and not tag_query:
        hits = [(score(it, query_terms(query)), it) for it in items]
        hits = [(s, it) for s, it in hits if s > 0]
    hits.sort(key=lambda x: (x[0], x[1].get("ts", "")), reverse=True)
    results = []
    for s, it in hits[:limit]:
        results.append({"item_id": it["id"], "title": it["title"], "score": s,
                        "excerpts": excerpts(it, terms, 700), "url": it.get("url"),
                        "visible_note": str(storage.vault_root() / it["note"]) if it.get("note") else None,
                        "agent_md": str(storage.vault_root() / it["agent_md"]) if it.get("agent_md") else None,
                        "attachments": it.get("attachment_files", []), "tags": it.get("tags", []),
                        "summary": it.get("summary", ""), "first_archived": it.get("date", "")})
    return {"status": "ok", "query": query, "total": len(hits), "results": results, "found": len(results), "items": [{k: row[k] for k in ("item_id", "title", "summary", "tags", "url", "first_archived")} for row in results]}
