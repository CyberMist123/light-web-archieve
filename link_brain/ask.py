"""知识库问答（Owner 2026-09-16 的 /问AI）。

不是通用聊天：基于本地归档库做**总结 / 列举 / 给链接 / 简单分析**。
入口是插件的 `answerArchive`，它 spawn `python -m link_brain ask`，拿回一段 JSON。

设计要点（TASKBOOK 顶部「还没做」1-8）：
- **本地索引免费**：读整个 `catalog-data.json`（正文在 `search_text` 里），自己重新检索，
  不依赖页面传来的 shown。只有**发给模型**的内容才限量。
- **先规则、后模型**：提取 GitHub / 链接这类意图纯本地出，不花 token；
  普通问题必要时最多一次小模型把问题扩成 3-6 个检索词。
- **token 控制**：本地 OR 召回 → 排序 → 取 topK 条、每条 ≤fragChars 字、总输入 ≤totalCharLimit 字。
  一次回答，不自动循环 agent。
- **「所有」给真实计数 + 完整链接列表**，不能默默 top8 就说全库只有 8 条。
- 模型调用复用 `llm.call_media_text`（media.py 通路，key 在仓外）；Owner 配了自定义
  HTTP endpoint 就走 httpx（key 读自 data.json，绝不打印）。
- 输出走 `read.dump_json`（UTF-8 字节，绕开 Windows GBK 控制台）。
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from . import ai_config, llm, storage
from .read import EXIT_ERROR, EXIT_OK, dump_json

GITHUB_RE = re.compile(r"https?://github\.com/[^\s)]+", re.I)
_URL_RE = re.compile(r"https?://[^\s)]+", re.I)
_TERM_SPLIT = re.compile(r"[\s,，、;；/|]+")
# 中文按 2-gram 也切一份，好让「做梦」命中「做梦/梦境」这类
_STOP = {"的", "了", "我", "有", "和", "与", "给", "所有", "全部", "关于", "一下",
         "请", "帮", "找", "查", "列", "列出", "提取", "地址", "链接", "分析", "简单",
         "相关", "这些", "那些", "哪些", "是", "在", "吗", "呢", "把", "对", "里"}


# --------------------------------------------------------------------------
# 本地索引
# --------------------------------------------------------------------------

def load_items() -> list[dict[str, Any]]:
    """读 catalog-data.json 的 items；没有就空列表（fail-open）。"""
    path = storage.vault_root() / "_archive" / "catalog-data.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _norm(text: Any) -> str:
    return str(text or "").casefold()


def _hay(it: dict[str, Any]) -> str:
    parts = [it.get("title"), it.get("summary"), it.get("search_text"),
             it.get("author"), " ".join(it.get("tags") or [])]
    return _norm(" ".join(str(p or "") for p in parts))


def query_terms(question: str) -> list[str]:
    """从问句里抠检索词：切词 + 去停用词 + 中文 2-gram 兜底。"""
    terms: list[str] = []
    for raw in _TERM_SPLIT.split(question or ""):
        raw = raw.strip().strip("#＃?？!！。.,，、").casefold()
        if raw and raw not in _STOP and len(raw) >= 1:
            terms.append(raw)
    # 中文连写的问句切不出词时，退回 2-gram
    cjk = "".join(re.findall(r"[一-鿿]", question or ""))
    if len(terms) <= 1 and len(cjk) >= 2:
        terms += [cjk[i:i + 2].casefold() for i in range(len(cjk) - 1)]
    seen: list[str] = []
    for t in terms:
        if t not in seen:
            seen.append(t)
    return seen


def score(it: dict[str, Any], terms: list[str]) -> int:
    """OR 召回：命中任一词就算数，标题命中权重高。"""
    if not terms:
        return 0
    title = _norm(it.get("title"))
    tags = _norm(" ".join(it.get("tags") or []))
    hay = _hay(it)
    total = 0
    for term in terms:
        if not term:
            continue
        if term in title:
            total += 10
        elif term in tags:
            total += 6
        elif term in hay:
            total += 4
    return total


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


def wants_all(question: str) -> bool:
    return bool(re.search(r"所有|全部|都有哪些|列出", question or ""))


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
    terms = query_terms(question)
    pool = retrieve(items, terms) if terms and not wants_all(question) else items
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
    # 模型给的仓库名线索（未证实），单列，明确标注
    hints: list[str] = []
    for it in pool[:40]:
        for link in it.get("suggested_links") or []:
            hint = (link.get("hint") if isinstance(link, dict) else "") or ""
            url = (link.get("url") if isinstance(link, dict) else "") or ""
            if hint and not url and not GITHUB_RE.search(hint):
                hints.append(f"- {hint} — {_note_link(it)}")
    if hints:
        lines += ["", "**模型提到但未证实的仓库/项目名（不是确认地址，需自行搜索核对）：**", ""]
        lines += list(dict.fromkeys(hints))[:15]
    return {"markdown": "\n".join(lines), "matches": len(seen), "materials": len(rows),
            "usage": None, "model_called": False}


def _answer_links(question: str, items: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    terms = query_terms(question)
    matches = retrieve(items, terms) if terms and not wants_all(question) else items
    lines = [f"**匹配到 {len(matches)} 篇**（下面给完整链接列表，可继续查看）：", ""]
    for it in matches:
        url = it.get("url")
        link = f" · [原文]({url})" if url and _URL_RE.match(str(url)) else ""
        lines.append(f"- {_note_link(it)}{link}")
    if not matches:
        lines.append("（没有命中的笔记。）")
    return {"markdown": "\n".join(lines), "matches": len(matches), "materials": len(matches),
            "usage": None, "model_called": False}


def _expand_terms(question: str, base: list[str], settings: dict[str, Any]) -> list[str]:
    """普通问题：可选一次小模型把问句扩成 3-6 个检索词/同义词。失败就用 base。"""
    if not (settings.get("retrieval") or {}).get("expandTerms", True):
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


def _local_excerpt(item: dict[str, Any], terms: list[str], limit: int) -> str:
    """从正文里截一段命中检索词附近的**原文**（她要的「选取的正文」，不改写、不概括）。"""
    text = " ".join(str(item.get("search_text") or item.get("summary") or "").split())
    if not text:
        return ""
    low = text.lower()
    pos = -1
    for t in terms:
        if t:
            i = low.find(t)
            if i >= 0:
                pos = i
                break
    if pos < 0:
        return text[:limit] + ("…" if len(text) > limit else "")
    start = max(0, pos - limit // 3)
    snippet = text[start:start + limit]
    return ("…" if start > 0 else "") + snippet + ("…" if start + limit < len(text) else "")


def _card(item: dict[str, Any], excerpt: str) -> dict[str, Any]:
    url = item.get("url")
    return {
        "id": item.get("id"),
        "title": item.get("title") or "未命名",
        "cover": item.get("cover"),
        "note": item.get("note"),
        "url": url if _URL_RE.match(str(url or "")) else "",
        "excerpt": excerpt,
    }


def _build_context(matches: list[dict[str, Any]], limits: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """给模型看的编号片段（仅 useModel 时用）。materials[i] 对应「片段(i+1)」，带回原 item。"""
    top_k = int(limits.get("topK", 8))
    frag_chars = int(limits.get("fragChars", 800))
    total_cap = int(limits.get("totalCharLimit", 8000))
    blocks: list[str] = []
    materials: list[dict[str, Any]] = []
    used = 0
    for i, it in enumerate(matches[:top_k], start=1):
        body = " ".join(str(it.get("search_text") or it.get("summary") or "").split())[:frag_chars]
        block = f"[片段{i}] 标题：{it.get('title') or '未命名'}\n内容：{body or '（无正文）'}"
        if used + len(block) > total_cap and blocks:
            break
        blocks.append(block)
        used += len(block)
        materials.append({"item": it})
    return "\n\n".join(blocks), materials


def _answer_qa(question: str, items: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    fmt = settings.get("answerFormat") or {}
    excerpt_chars = int(fmt.get("excerptChars", 200))
    top_k = int((settings.get("retrieval") or {}).get("topK", 8))
    base = query_terms(question)
    terms = _expand_terms(question, base, settings)  # 默认关，不多花一次调用
    matches = retrieve(items, terms)
    if not matches:
        return {"kind": "cards", "results": [], "matches": 0, "materials": 0,
                "model_called": False, "markdown": "库里没有检索到相关归档。换个关键词试试。"}

    results: list[dict[str, Any]] = []
    model_called = False
    if fmt.get("useModel"):
        context, mats = _build_context(matches, {**(settings.get("retrieval") or {}), "topK": top_k})
        prompt = (settings.get("prompts") or {}).get("answer") or ai_config.DEFAULT_ANSWER_PROMPT
        res = call_text(prompt, f"【问题】{question}\n\n【片段】\n{context}", settings)
        model_called = True
        if res.get("status") == "ok":
            try:
                m = re.search(r"\{.*\}", res.get("text") or "", re.S)
                payload = json.loads(m.group(0)) if m else {}
                for r in payload.get("results", []):
                    idx_m = re.search(r"(\d+)", str(r.get("id", "")))
                    if not idx_m:
                        continue
                    idx = int(idx_m.group(1)) - 1
                    if 0 <= idx < len(mats):
                        it = mats[idx]["item"]
                        ex = " ".join(str(r.get("excerpt") or "").split())[:excerpt_chars] \
                            or _local_excerpt(it, terms, excerpt_chars)
                        results.append(_card(it, ex))
            except (ValueError, AttributeError, TypeError):
                pass

    if not results:  # 默认路径（快）：纯本地检索出小图 + 原文摘录
        for it in matches[:top_k]:
            results.append(_card(it, _local_excerpt(it, terms, excerpt_chars)))

    return {"kind": "cards", "results": results, "matches": len(matches),
            "materials": len(results), "model_called": model_called}


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------

def answer(question: str) -> dict[str, Any]:
    question = (question or "").strip()
    settings = ai_config.load()
    items = load_items()
    if not question:
        return {"status": "error", "markdown": "没有问题内容。", "matches": 0,
                "materials": 0, "intent": "qa", "model_called": False}
    intent = detect_intent(question)
    handler = {"github": _answer_github, "links": _answer_links}.get(intent, _answer_qa)
    result = handler(question, items, settings)
    result["status"] = "ok"
    result["intent"] = intent
    result["index_size"] = len(items)
    return result


def run(args) -> int:
    result = answer(getattr(args, "question", "") or "")
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
