"""个人 Wiki 检索（10-31）：问收藏 / MCP 读她自己写的 Wiki 页（`vault/PersonalWiki/*.md`）。

只读、纯本地、不联网、不调模型。页面读法照 `wiki_page.scan_dir`（和 personal_wiki 同一份解析，Obsidian 里改过也认）；库路径由调用方给
（不 import personal_wiki / storage：ask 读 Wiki 不能把它们卷进大 import 环，见 tests/test_guards.py MAX_CYCLE）；
`_archive/wiki-index.json` 不带正文，所以这里每次现扫目录（页数是几十到几百，读一遍很快），索引缺了也不影响。

打分（中文不分词）：查询切成「词」——中文段切 2 字片段（虚词片段如「什么」「怎么」丢掉）、英文 / 数字按整词——
看标题 / 标签 / 正文各盖住了几成，再加：问句里整段出现的最长连续片段、她的标签 / 页面标题原样出现在问句里。
分数只用来排序和过门槛，不跨查询比较。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import wiki_page as wp

SNIPPET_CHARS = 120
QUERY_MAX = 200          # 问句只看前 200 字（问收藏的问题可能很长，后面多是要求）
ASK_MIN_SCORE = 3.0      # 问收藏只要过这个分的页（search 默认门槛低，MCP 自己挑）
SEARCH_MIN_SCORE = 1.0
RUN_CAP = 8              # 最长连续片段最多算几个字

_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_SEG = re.compile(r"[㐀-鿿豈-﫿]+|[A-Za-z0-9][A-Za-z0-9_.+-]*")
# 两个字都是虚词的片段不算（「什么」「怎么」「我的」…）——和 ask._FUNC_CHARS 同一类字，另加疑问 / 人称
_FUNC = set("的了吗呢吧啊呀么嘛哦着过得地是在有和与或及把被给让那这个们也都就还又再很太怎什哪我你她他它些一下")
# 带语气词 / 人称的片段也不算（「静的」「店吗」「我喜」是跨词拼出来的，只会稀释覆盖率）；「地铁」「有点」这类照留
_EDGE = set("的了吗呢吧啊呀嘛哦我你她他它")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def pieces(query: str) -> list[str]:
    """查询 → 去重的片段：中文 2 字滑窗、英文 / 数字整词（≥2 个字符）。单个汉字的段落单独留着（「茶」也能搜）。"""
    out: list[str] = []
    for seg in _SEG.findall(_norm(query)[:QUERY_MAX]):
        if _CJK.match(seg):
            if len(seg) == 1:
                if seg not in _FUNC:
                    out.append(seg)
                continue
            out.extend(seg[i:i + 2] for i in range(len(seg) - 1)
                       if not (seg[i] in _FUNC and seg[i + 1] in _FUNC) and seg[i] not in _EDGE and seg[i + 1] not in _EDGE)
        elif len(seg) >= 2:
            out.append(seg)
    return list(dict.fromkeys(out))


def _cover(parts: list[str], text: str) -> float:
    if not parts or not text:
        return 0.0
    return sum(1 for p in parts if p in text) / len(parts)


def _longest_run(query: str, text: str) -> tuple[int, str]:
    """问句里在 text 中整段出现的最长连续片段（≥2 字）：(长度, 片段)。逐个起点往后伸，伸不动就换下一个起点。"""
    best, frag = 0, ""
    if not text:
        return 0, ""
    for seg in _SEG.findall(_norm(query)[:QUERY_MAX]):
        n = len(seg)
        for i in range(n - 1):
            if n - i <= best:
                break
            j = i + 2
            if seg[i:j] not in text:
                continue
            while j < n and seg[i:j + 1] in text:
                j += 1
            if j - i > best:
                best, frag = j - i, seg[i:j]
    return best, frag


def _plain_body(body: str) -> str:
    """正文 → 一行纯文字：去代码块（```pages 自动列表等）、链接留文字、去强调符号和标题井号。"""
    text = wp._strip_code(body or "")
    lines = [wp._plain(re.sub(r"^\s*(#{1,6}|[-*+]\s+\[[ xX]\]|[-*+]|\d+\.|>)\s*", "", ln)) for ln in text.split("\n")]
    return re.sub(r"\s+", " ", " ".join(ln for ln in lines if ln)).strip()


def _snippet(plain: str, needles: list[str]) -> str:
    """命中附近 ~120 字：先找最长的那个命中片段，前面留 1/3。没命中 = 开头。"""
    low = plain.lower()
    pos = -1
    for n in sorted((x for x in needles if x), key=len, reverse=True):
        pos = low.find(n)
        if pos >= 0:
            break
    if pos < 0:
        return plain[:SNIPPET_CHARS]
    start = max(0, pos - SNIPPET_CHARS // 3)
    end = min(len(plain), start + SNIPPET_CHARS)
    start = max(0, end - SNIPPET_CHARS)
    return ("…" if start > 0 else "") + plain[start:end] + ("…" if end < len(plain) else "")


def _pages(vault: Path) -> list[dict[str, Any]]:
    """现扫 PersonalWiki：[{page, file, plain, all_tags, lead}]。目录不在 / 读不了 = 空。"""
    out = []
    for e in wp.scan_dir(Path(vault) / wp.DIR_NAME).values():
        page = e["page"]
        d = wp.derive(page)
        out.append({"page": page, "file": e["path"].name, "plain": _plain_body(page.get("body") or ""),
                    "all_tags": d["all_tags"], "lead": d["lead"]})
    return out


def score_page(query: str, parts: list[str], row: dict[str, Any]) -> tuple[float, list[str]]:
    """一页的分 + 命中的片段（给摘要定位）。"""
    page = row["page"]
    title = _norm(page.get("title"))
    tags = [_norm(t) for t in row["all_tags"] if t]
    tag_text = " ".join(tags)
    body = row["plain"].lower()
    q = _norm(query)[:QUERY_MAX]
    s = 4 * _cover(parts, title) + 2 * _cover(parts, tag_text) + 3 * _cover(parts, body)
    run_t, frag_t = _longest_run(q, title)
    run_b, frag_b = _longest_run(q, body)
    if run_t >= 3:
        s += 0.6 * min(run_t, RUN_CAP)
    if run_b >= 3:
        s += 0.4 * min(run_b, RUN_CAP)
    # 她的标签 / 页面标题原样出现在问句里：很强的信号（「住宿偏好」「#露营」）
    s += 3 * min(2, sum(1 for t in tags if len(t) >= 2 and t in q))
    if len(title) >= 2 and title in q:
        s += 5
    if len(q) >= 2:   # 整句（短查询时常见）原样命中
        s += (4 if q in title else 0) + (3 if q in body else 0)
    hits = [x for x in (frag_b, q if q in body else "") if x] + [p for p in parts if p in body]
    return round(s, 2), hits


def search(query: str, vault: Path, limit: int = 5, *, min_score: float = SEARCH_MIN_SCORE) -> list[dict[str, Any]]:
    """[{id, title, tags, snippet, score, file}]，分高的在前（同分按更新时间新→旧）。查询空 / 没有 Wiki = []。"""
    query = str(query or "").strip()
    parts = pieces(query)
    if not query or not parts:
        return []
    rows = []
    for row in _pages(vault):
        s, hits = score_page(query, parts, row)
        if s < min_score:
            continue
        page = row["page"]
        rows.append({"id": page["id"], "title": page["title"], "role": page.get("role") or "page", "tags": row["all_tags"],
                     "snippet": _snippet(row["plain"], hits) if row["plain"] else row["lead"], "score": s,
                     "file": row["file"], "updated": page.get("updated") or ""})
    rows.sort(key=lambda r: r["updated"], reverse=True)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:max(1, int(limit or 5))]


def list_pages(vault: Path) -> list[dict[str, Any]]:
    """全部页：[{id, title, role, tags, lead, updated, file}]，更新时间新→旧。"""
    rows = [{"id": r["page"]["id"], "title": r["page"]["title"], "role": r["page"].get("role") or "page",
             "tags": r["all_tags"], "lead": r["lead"], "updated": r["page"].get("updated") or "", "file": r["file"]}
            for r in _pages(vault)]
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def get(id_or_title: str, vault: Path) -> dict[str, Any] | None:
    """按 id 或标题（先精确、再不分大小写）取整页：{id, title, role, tags, created, updated, file, body}。找不到 = None。"""
    ref = str(id_or_title or "").strip()
    if not ref:
        return None
    entries = wp.scan_dir(Path(vault) / wp.DIR_NAME)
    hit = entries.get(ref)
    if hit is None:
        hit = next((e for e in entries.values() if e["page"]["title"] == ref), None)
    if hit is None:
        low = ref.lower()
        hit = next((e for e in entries.values() if e["page"]["title"].lower() == low), None)
    if hit is None:
        return None
    page = hit["page"]
    return {"id": page["id"], "title": page["title"], "role": page.get("role") or "page",
            "tags": wp.derive(page)["all_tags"], "created": page.get("created") or "", "updated": page.get("updated") or "",
            "file": hit["path"].name, "body": page.get("body") or ""}
