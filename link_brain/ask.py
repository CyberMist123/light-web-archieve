"""Grounded archive answers for the Obsidian UI, Claude Code and Codex.

Local retrieval uses field weights and bilingual aliases. Questions call the configured
text model once by default; optional query expansion is off. Source windows remain
verbatim and citations carry paths to the complete machine-readable Markdown.
Conversation history resolves follow-ups but is not treated as source evidence.
"""

from __future__ import annotations

import json
import mimetypes
import re
import sys
from pathlib import Path
from typing import Any

from . import ai_config, llm, storage
from .read import EXIT_ERROR, EXIT_OK, dump_json

GITHUB_RE = re.compile(r"https?://github\.com/[^\s)]+", re.I)
_URL_RE = re.compile(r"https?://[^\s)]+", re.I)
_TERM_SPLIT = re.compile(r"[\s,，、;；/|]+")
# 中文按 2-gram 也切一份，好让「做梦」命中「做梦/梦境」这类
_STOP = {"的", "了", "我", "有", "和", "与", "给", "所有", "全部", "关于", "一下",
         "请", "帮", "找", "查", "列", "列出", "提取", "地址", "链接", "分析", "简单",
         "从收藏", "收藏里", "从收藏里", "给我", "一份", "重点", "重点是", "材料", "步骤", "怎么", "如何", "什么", "有没有", "这些", "相关", "这些", "那些", "哪些", "是", "在", "吗", "呢", "把", "对", "里"}


# --------------------------------------------------------------------------
# 本地索引
# --------------------------------------------------------------------------

def load_items() -> list[dict[str, Any]]:
    """读 catalog-data.json 的 items；没有就空列表（fail-open）。"""
    path = storage.vault_root() / "_archive" / "catalog-data.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        from .catalog import collect
        return collect(storage.vault_root())
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def query_terms(question: str) -> list[str]:
    """Tokenize natural-language requests without matching instruction fragments."""
    import jieba
    import logging
    from .retrieval import norm
    jieba.setLogLevel(logging.ERROR)
    ignored = _STOP | {"收藏", "归档", "库里", "原文", "相关", "一份", "怎么回事", "重点", "需要", "想要", "内容", "告诉", "里面"}
    words = [norm(w) for w in jieba.lcut(question or "")]
    terms = [w for w in words if w not in ignored and re.search(r"[a-z0-9一-鿿]", w) and len(w) >= 2]
    return list(dict.fromkeys(terms))


def score(it: dict[str, Any], terms: list[str]) -> int:
    from .retrieval import score as weighted_score
    return weighted_score(it, terms)


def retrieve(items: list[dict[str, Any]], terms: list[str]) -> list[dict[str, Any]]:
    scored = [(score(it, terms), it) for it in items]
    hits = [(s, it) for s, it in scored if s > 0]
    hits.sort(key=lambda x: (x[0], x[1].get("ts") or ""), reverse=True)
    return [it for _, it in hits]


# --------------------------------------------------------------------------
# 意图
# --------------------------------------------------------------------------

def detect_intent(question: str) -> str:
    q = question or ""
    if re.search(r"github|仓库|repo", q, re.I) and re.search(r"提取|地址|链接|有哪些|列|url", q, re.I):
        return "github"
    if re.search(r"链接|url|网址|原文", q, re.I) and re.search(r"提取|给我|列|所有|哪些", q, re.I):
        return "links"
    return "qa"


# --------------------------------------------------------------------------
# 模型调用（media.py 复用 / 自定义 HTTP）
# --------------------------------------------------------------------------

def call_text(instruction: str, input_text: str, settings: dict[str, Any]) -> dict[str, Any]:
    """按 data.json 的 textAI 配置发一次文本请求。返回 {status, text, usage, error}。"""
    text_cfg = settings.get("textAI") or {}
    if (text_cfg.get("mode") or "media") == "http" and (text_cfg.get("endpoint") or "").strip():
        return _call_http(instruction, input_text, text_cfg)
    cfg = llm.load_config()
    model = (text_cfg.get("model") or "").strip() or cfg.get("model")
    res = llm.call_media_text(instruction, input_text, model=model, timeout=int(cfg["timeout_sec"]))
    return {"status": res["status"], "text": res.get("text"), "usage": None, "error": res.get("error")}


def _call_http(instruction: str, input_text: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """OpenAI 兼容 /chat/completions。key 只在内存里用，绝不打印。"""
    import httpx

    endpoint = (cfg.get("endpoint") or "").strip()
    headers = {"Content-Type": "application/json"}
    if (cfg.get("apiKey") or "").strip():
        headers["Authorization"] = f"Bearer {cfg['apiKey'].strip()}"
    body = {
        "model": (cfg.get("model") or "").strip() or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": input_text},
        ],
        "max_tokens": int(cfg.get("maxTokens") or 800),
        "temperature": 0.3,
        "stream": False,
    }
    try:
        resp = httpx.post(endpoint, headers=headers, json=body, timeout=180)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - 失败当数据回，不炸
        return {"status": "failed", "text": None, "usage": None,
                "error": f"HTTP 调用失败: {type(exc).__name__}: {exc}"}
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"status": "failed", "text": None, "usage": None, "error": "响应结构不认识（非 OpenAI /chat/completions）"}
    return {"status": "ok", "text": text, "usage": payload.get("usage"), "error": None}


# --------------------------------------------------------------------------
# 三种答法
# --------------------------------------------------------------------------

def _note_link(it: dict[str, Any]) -> str:
    note = it.get("note")
    title = it.get("title") or "未命名"
    if note:
        stem = re.sub(r"\.md$", "", str(note))
        return f"[[{stem}|{title}]]"
    return title


def _answer_github(question: str, items: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    terms = [t for t in query_terms(question) if t not in {"github", "repo", "仓库"}]
    pool = retrieve(items, terms) if terms else items
    rows: list[str] = []
    seen: set[str] = set()
    for it in pool:
        for url in it.get("github_urls") or []:
            url = str(url).rstrip("。，、；：！？)]}")
            if url and url not in seen:
                seen.add(url)
                rows.append(f"- {url} — {_note_link(it)}")
    lines = [f"**在库里找到 {len(seen)} 个 GitHub 地址**（来自 {len(items)} 篇归档，均为原文/评论中实际出现的链接）：", ""]
    lines += rows or ["（本次检索范围内没有出现 github.com 地址。）"]
    sources = [{**_card(it, ""), "citation": i+1} for i, it in enumerate(pool) if it.get("github_urls")]
    return {"markdown": "\n".join(lines), "matches": len(seen), "materials": len(rows),
            "sources": sources, "usage": None, "model_called": False}


def _answer_links(question: str, items: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    terms = query_terms(question)
    from .retrieval import score as weighted_score
    matches = [it for it in retrieve(items, terms) if weighted_score(it, terms, require_all=True)] if terms else items
    lines = [f"**匹配到 {len(matches)} 篇**（下面给完整链接列表，可继续查看）：", ""]
    for it in matches:
        url = it.get("url")
        link = f" · [原文]({url})" if url and _URL_RE.match(str(url)) else ""
        lines.append(f"- {_note_link(it)}{link}")
    if not matches:
        lines.append("（没有命中的笔记。）")
    return {"markdown": "\n".join(lines), "matches": len(matches), "materials": len(matches),
            "sources": [{**_card(it, ""), "citation": i+1} for i, it in enumerate(matches)],
            "usage": None, "model_called": False}


def _expand_terms(question: str, base: list[str], settings: dict[str, Any]) -> list[str]:
    """普通问题：可选一次小模型把问句扩成 3-6 个检索词/同义词。失败就用 base。"""
    if not (settings.get("retrieval") or {}).get("expandTerms", False):
        return base
    instr = ("把下面这个中文检索需求扩写成 3 到 6 个用于本地全文检索的关键词或同义词，"
             "只输出一个 JSON 数组（如 [\"做梦\",\"梦境\",\"dream\"]），不要解释。")
    res = call_text(instr, question, settings)
    if res.get("status") != "ok":
        return base
    text = res.get("text") or ""
    try:
        m = re.search(r"\[.*\]", text, re.S)
        arr = json.loads(m.group(0)) if m else []
    except (ValueError, AttributeError):
        return base
    extra = [str(x).strip().casefold() for x in arr if isinstance(x, (str, int)) and str(x).strip()]
    merged = list(dict.fromkeys(base + extra))
    return merged or base


def _card(item: dict[str, Any], excerpt: str) -> dict[str, Any]:
    url = item.get("url")
    return {
        "id": item.get("id"),
        "title": item.get("title") or "未命名",
        "cover": item.get("cover"),
        "note": item.get("note"),
        "url": url if _URL_RE.match(str(url or "")) else "",
        "excerpt": excerpt,
        "agent_md": str(storage.vault_root() / item["agent_md"]) if item.get("agent_md") else None,
        "attachments": item.get("attachment_files", []),
    }


def _answer_qa(question, items, settings, history=None):
    from .retrieval import excerpts
    history = [m for m in (history or [])[-8:] if m.get("role") in {"user", "assistant"}]
    # Prior user requests resolve follow-ups; previous model text is never retrieval evidence.
    prior = " ".join(str(m.get("content", ""))[:1000] for m in history if m["role"] == "user")
    terms = _expand_terms(question, query_terms(question), settings)
    matches = retrieve(items, terms)
    if prior:
        previous = retrieve(items, query_terms(prior))
        seen = {it["id"] for it in matches}
        matches += [it for it in previous if it["id"] not in seen]
        # Continuation with little standalone information uses preceding subject first.
        if len(question) < 18:
            order = {it["id"]: i for i, it in enumerate(previous)}
            matches.sort(key=lambda it: order.get(it["id"], len(previous)))
    if not matches:
        return {"kind": "answer", "markdown": "收藏里没有找到足够相关的材料。可以换个关键词，或先导入相关内容。",
                "sources": [], "matches": 0, "materials": 0, "model_called": False}
    limits = settings.get("retrieval") or {}
    cap = max(500, int(limits.get("totalCharLimit", 8000)))
    frag = max(200, int(limits.get("fragChars", 800)))
    blocks, sources = [], []
    for it in matches[:max(1, int(limits.get("topK", 8)))]:
        snippets = excerpts(it, terms + query_terms(prior), frag)
        block = f"[来源{len(sources)+1}] {it['title']}\n" + "\n".join(f"[{x['field']}] {x['text']}" for x in snippets)
        remaining = cap - sum(len(x) for x in blocks)
        if remaining < 100:
            break
        blocks.append(block[:remaining])
        sources.append({**_card(it, snippets[0]["text"]), "citation": len(sources)+1,
                        "agent_md": str(storage.vault_root() / it["agent_md"]) if it.get("agent_md") else None, "attachments": it.get("attachment_files", [])})
    prompt = ai_config.DEFAULT_ANSWER_PROMPT
    custom = (settings.get("prompts") or {}).get("answer", "")
    if custom and '"results"' not in custom and custom != prompt:
        prompt += "\n用户的回答风格偏好：" + custom
    dialog = "\n".join(f"{m['role']}: {str(m.get('content', ''))[:1500]}" for m in history)
    res = call_text(prompt, f"【先前对话，仅供理解追问，不是事实来源】\n{dialog}\n【问题】{question}\n【原始材料】\n" + "\n\n".join(blocks), settings)
    if res.get("status") != "ok" or not (res.get("text") or "").strip():
        return {"status": "error", "kind": "answer", "markdown": "AI 回答失败：" + str(res.get("error") or "空响应"),
                "sources": sources, "matches": len(matches), "materials": len(sources), "model_called": True}
    return {"kind": "answer", "markdown": res["text"], "sources": sources, "matches": len(matches),
            "materials": len(sources), "model_called": True, "usage": res.get("usage")}


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------

def delivery_payload(result: dict[str, Any], include=None) -> dict[str, Any]:
    """Channel-neutral message parts. Paths are for the sending adapter, not the user."""
    include = set(include or [])
    body = re.sub(r"\[来源\d+\]", "", result.get("markdown") or "").strip()
    payload: dict[str, Any] = {"body": body}
    sources = result.get("sources") or []
    used = {int(n) for n in re.findall(r"\[来源(\d+)\]", result.get("markdown") or "")}
    selected = [s for s in sources if s.get("citation") in used] if used else sources
    if "links" in include:
        payload["links"] = [{"title": s["title"], "url": s["url"], "source_id": s["id"],
                             "markdown_path": s.get("agent_md")}
                            for s in selected if re.match(r"https?://", s.get("url") or "")]
    if "files" in include:
        files, seen = [], set()
        for source in selected:
            for att in source.get("attachments") or []:
                local = Path(att["file"]) if att.get("file") else None
                if not local or not local.is_file() or str(local) in seen:
                    continue
                seen.add(str(local))
                files.append({"name": local.name, "path": str(local.resolve()),
                              "mime_type": mimetypes.guess_type(local.name)[0] or "application/octet-stream",
                              "bytes": local.stat().st_size, "source_id": source["id"],
                              "markdown_path": att.get("markdown")})
        payload["files"] = files
    return payload


def answer(question: str, history=None, include=None) -> dict[str, Any]:
    question = (question or "").strip()
    settings = ai_config.load()
    items = load_items()
    if not isinstance(include, (list, tuple, set, type(None))) or set(include or []) - {"body", "links", "files"}:
        return {"status": "error", "markdown": "include 仅支持 body、links、files。"}
    if not question:
        return {"status": "error", "markdown": "没有问题内容。", "matches": 0,
                "materials": 0, "intent": "qa", "model_called": False}
    intent = detect_intent(question)
    handler = {"github": _answer_github, "links": _answer_links}.get(intent, _answer_qa)
    result = handler(question, items, settings, history) if intent == "qa" else handler(question, items, settings)
    result.setdefault("status", "ok")
    result["intent"] = intent
    result["index_size"] = len(items)
    result["delivery"] = delivery_payload(result, include)
    result["history"] = ([{"role": m["role"], "content": str(m.get("content", ""))}
                          for m in (history or [])[-6:] if m.get("role") in {"user", "assistant"}]
                         + [{"role": "user", "content": question},
                            {"role": "assistant", "content": result.get("markdown", "")}]) if result["status"] == "ok" else (history or [])
    return result


def run(args) -> int:
    try:
        if getattr(args, "request_stdin", False):
            request = json.load(sys.stdin)
            if not isinstance(request, dict) or not isinstance(request.get("question"), str):
                raise ValueError("请求需要 question 字符串")
            history = request.get("history") or []
            if not isinstance(history, list) or any(not isinstance(m, dict) for m in history):
                raise ValueError("history 必须是对话消息数组")
            result = answer(request["question"], history, request.get("include"))
        else:
            history = json.load(sys.stdin) if getattr(args, "history_stdin", False) else []
            result = answer(getattr(args, "question", "") or "", history, getattr(args, "include", None))
    except (ValueError, TypeError) as exc:
        result = {"status": "error", "markdown": f"问答请求无效：{exc}"}
    dump_json(result)
    return EXIT_OK if result.get("status") == "ok" else EXIT_ERROR


def selftest(kind: str) -> dict[str, Any]:
    """设置页「测试」按钮的后端：真发一次最小调用，证明这条接口是活的（不做空壳）。"""
    settings = ai_config.load()
    if kind == "text":
        res = call_text("只回复两个字：ok", "连通测试", settings)
        detail = (res.get("text") or res.get("error") or "")
        return {"kind": "text", "ok": res.get("status") == "ok",
                "mode": (settings.get("textAI") or {}).get("mode", "media"),
                "detail": " ".join(str(detail).split())[:200]}
    if kind == "ocr":
        from . import vision
        sample = None
        base = storage.vault_root() / "_archive" / "xiaohongshu"
        if base.is_dir():
            for obj in sorted(base.iterdir()):
                assets = sorted(obj.glob("raw/v*/assets/*"))
                imgs = [p for p in assets if p.suffix.lower() in {".webp", ".jpg", ".jpeg", ".png"}]
                if imgs:
                    sample = imgs[0]
                    break
        if not sample:
            return {"kind": "ocr", "ok": False, "detail": "库里没有可测的图片，先归档一篇带图的笔记"}
        res = vision.run_ocr(sample)
        detail = (res.get("ocr") or res.get("error") or "")
        return {"kind": "ocr", "ok": res.get("status") == "ok",
                "via": (settings.get("ocr") or {}).get("via", "cmx"),
                "sample": sample.name, "detail": " ".join(str(detail).split())[:200]}
    return {"kind": kind, "ok": False, "detail": f"未知的自测类型: {kind}"}


def run_selftest(args) -> int:
    result = selftest(getattr(args, "kind", "") or "")
    dump_json(result)
    return EXIT_OK if result.get("ok") else EXIT_ERROR
