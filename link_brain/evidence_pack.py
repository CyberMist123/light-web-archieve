"""问收藏证据三段的后两段（1015 第三批 R1）：先选篇（ask.select_primary）→ 每篇各字段内定位命中段再扩窗 → 全局装箱。

思路借 LlamaIndex SentenceWindowNodeParser / MetadataReplacementPostProcessor：命中落在一句上，送模型的是「这一句前后几句」
的窗口，而且窗口只在同一个字段里扩（正文的窗口不会扩进评论区）；EmbeddingsFilter 的「先选后装箱」：先定送哪几篇，
再在全局字数预算（totalCharLimit，默认 8000）里按得分装段，而不是先给每篇平分预算。

- passages(item, …)：一篇的候选段 [{field, offset, text, score}]。命中点 = 检索词（核心词加权）的每处出现 + 语义命中的 chunk；
  每个命中点按句子边界向前后扩（同字段、≤ WINDOW 字），同字段重叠的窗口合并。
- pack(docs, …)：全局装箱。主来源（第 1 篇）短正文（≤ SHORT_BODY 字）整段先放；整篇都不长的篇（所有字段加起来不超过它该分的份）
  整篇放；其余按段得分 × 篇次权重装，每篇先保底一段；同字段重叠的段去重。评论区没有固定配额：和别的字段按得分竞争，
  问题本身问到评论区时评论区段加权。保留 field / offset（评论楼号 / 说话人由 ask.locate_excerpts 挂上）。

只读、不调模型；任何异常由调用方退回旧证据（fail-open）。
"""
from __future__ import annotations

import math
import re
from typing import Any

from .retrieval import WEIGHTS, count, fields, norm, variants

SHORT_BODY = 1000   # 主来源正文不超过这么多字就整段给（作者写的干货，不截）
WINDOW = 420        # 一个命中点扩出的窗口上限（字）
MAX_SEG = 900       # 同字段合并后的一段最长
MIN_PIECE = 100     # 装箱剩下的预算不到这么多字就不再切一小截
HEADER_RESERVE = 140  # 每篇来源头（标题 / 作者 / 日期）大约占的字数，装箱时预留
DOC_DECAY = (1.0, .7, .55, .45, .4)
MAIN_WHOLE = 0.7    # 主来源整篇不超过总预算的这个比例就整篇给
_SENT_END = re.compile(r"[。！？!?；;\n]|\.\s")
_NON_CONTENT = {"title", "tags", "cats", "author", "summary"}
# 字段先验：作者写的正文 > 视频文字稿 / 画面文字 / 图片文字 / 附件 > 评论区。问题问到评论区时评论区和正文同级
FIELD_PRIOR = {"body": 1.0, "notes": 1.0, "highlights": 1.0, "transcript": .85, "screen": .8, "ocr": .8, "attachments": .8,
               "comments": .55, "comment_ocr": .5}
_COMMENT_Q = re.compile(r"评论|网友|有人说|大家说|楼里|回复")
FIELD_ORDER = ("body", "notes", "highlights", "transcript", "screen", "ocr", "attachments", "comments", "comment_ocr")


def content_fields(item) -> dict[str, str]:
    return {k: str(v) for k, v in fields(item).items() if k not in _NON_CONTENT and v}


def _sentence_window(text: str, start: int, end: int, limit: int = WINDOW) -> tuple[int, int]:
    """把命中 [start, end) 向两边扩到 ≤ limit 字，两端吸附到句子边界（SentenceWindow：给命中句的前后几句）。"""
    room = max(0, limit - (end - start))
    lo = max(0, start - room // 2)
    hi = min(len(text), end + room - (start - lo))
    if lo > 0:
        m = _SENT_END.search(text, lo, start)
        if m:
            lo = m.end()
    if hi < len(text):
        last = None
        for m in _SENT_END.finditer(text, end, hi):
            last = m
        if last:
            hi = last.end()
    return lo, max(hi, end)


def _hit_spans(text: str, groups: list[tuple[float, list[str]]], cap: int = 40):
    low = norm(text)
    if len(low) != len(text):   # NFKC 改了长度（极少）：按比例折回原文位置
        scale = len(text) / max(1, len(low))
    else:
        scale = 1.0
    spans = []
    for gi, (_, vs) in enumerate(groups):
        for v in vs:
            if not v or v not in low:
                continue
            pos = low.find(v)
            n = 0
            while pos >= 0 and n < cap:
                spans.append((int(pos * scale), int((pos + len(v)) * scale), gi))
                pos = low.find(v, pos + len(v))
                n += 1
    return spans


def passages(item, terms, sem=None, *, core=(), question: str = "") -> list[dict[str, Any]]:
    """一篇的候选段（得分降序）。terms = 检索词（原词 + 扩词 + 上一问的词），core = 核心词（权重 ×2）。"""
    content = content_fields(item)
    if not content:
        return []
    core_n = {norm(c) for c in core or () if norm(c)}
    groups = []
    seen = set()
    for t in list(core or ()) + list(terms or ()):
        key = norm(t)
        if not key or key in seen:
            continue
        seen.add(key)
        groups.append((2.0 if key in core_n else 1.0, variants(t)))
    # 篇内稀有度：一个词在这篇里到处都是（「澳洲」「评论」），它的每处命中就不值钱
    total_hits = [sum(count(norm(text), v) for text in content.values() for v in vs) for _, vs in groups]
    rarity = [w / (1 + math.log(1 + n)) if n else 0 for (w, _), n in zip(groups, total_hits)]
    comment_q = bool(_COMMENT_Q.search(question or ""))
    chunks = [c for c in ((sem or {}).get(item.get("id")) or {}).get("chunks") or [] if c.get("field") in content]
    out = []
    for key, text in content.items():
        prior = FIELD_PRIOR.get(key, .7)
        if comment_q and key in ("comments", "comment_ocr"):
            prior = 1.0
        spans = _hit_spans(text, groups)
        for c in chunks:
            if c.get("field") != key:
                continue
            ctext = str(c.get("text") or "")
            pos = text.find(ctext[:40]) if ctext else -1
            if pos >= 0:
                spans.append((pos, min(len(text), pos + min(len(ctext), WINDOW)), -1))
        if not spans:
            continue
        wins = []
        for s, e, gi in spans:
            lo, hi = _sentence_window(text, s, e)
            wins.append([lo, hi, {gi}])
        wins.sort()
        merged = []
        for lo, hi, gs in wins:
            if merged and lo <= merged[-1][1] and hi - merged[-1][0] <= MAX_SEG:
                merged[-1][1] = max(merged[-1][1], hi)
                merged[-1][2] |= gs
            elif merged and lo <= merged[-1][1]:
                merged.append([merged[-1][1], hi, gs])
            else:
                merged.append([lo, hi, gs])
        for lo, hi, gs in merged:
            if hi <= lo:
                continue
            seg = text[lo:hi]
            sc = sum(rarity[g] for g in gs if g >= 0) + (1.2 if -1 in gs else 0)
            # 同样的词，段越长越稀：按长度轻微折算（不至于让一句话的窗口压过一大段干货）
            sc = sc * prior * WEIGHTS.get(key, 3) / 7 / (1 + len(seg) / 2000)
            out.append({"field": key, "offset": lo, "text": seg, "score": round(sc, 4)})
    out.sort(key=lambda p: (-p["score"], FIELD_ORDER.index(p["field"]) if p["field"] in FIELD_ORDER else 99, p["offset"]))
    return out


def _overlaps(a, taken):
    return any(t["field"] == a["field"] and a["offset"] < t["offset"] + len(t["text"]) and t["offset"] < a["offset"] + len(a["text"])
               for t in taken)


def _trim(p, room):
    if len(p["text"]) <= room:
        return p
    return {**p, "text": p["text"][:room], "trimmed": True}


def pack(docs, terms, sem=None, *, cap: int = 8000, core=(), question: str = "") -> dict[str, list[dict[str, Any]]]:
    """全局装箱。docs = 选好的篇（第 1 篇是主来源）。返回 {id: [段…]}，每篇的段按字段 + 位置排好（读起来连贯）。"""
    docs = [d for d in docs if d]
    if not docs:
        return {}
    budget = max(200, cap - HEADER_RESERVE * len(docs))
    taken: dict[str, list[dict[str, Any]]] = {d["id"]: [] for d in docs}
    used = 0
    share = budget // len(docs)

    def put(doc_id, p):
        nonlocal used
        room = budget - used
        if room < min(MIN_PIECE, len(p["text"])):
            return False
        if _overlaps(p, taken[doc_id]):
            return False
        q = _trim(p, room)
        taken[doc_id].append(q)
        used += len(q["text"])
        return True

    cands = {}
    for rank, d in enumerate(docs):
        content = content_fields(d)
        whole = sum(map(len, content.values()))
        # 主来源整篇不超过总预算的 MAIN_WHOLE 就整篇给（「讲了什么」类问题要全貌）；其余篇不超过平均份额才整篇给
        if whole and whole <= (max(share, int(budget * MAIN_WHOLE)) if rank == 0 else share) and whole <= budget - used:
            # 整篇都不长：全给（F24「猪皮」在评论第 259 字之后、F08 蒜香鱼片全文 ~470 字）
            for key in [k for k in FIELD_ORDER if k in content] + [k for k in content if k not in FIELD_ORDER]:
                put(d["id"], {"field": key, "offset": 0, "text": content[key], "score": 99})
            cands[d["id"]] = []
            continue
        body = content.get("body") or ""
        if body and (len(body) <= SHORT_BODY if rank == 0 else len(body) <= SHORT_BODY // 2):
            put(d["id"], {"field": "body", "offset": 0, "text": body, "score": 99})
        cands[d["id"]] = passages(d, terms, sem, core=core, question=question)
    # 每篇保底一段（得分最高的）
    for d in docs:
        for p in cands[d["id"]]:
            if put(d["id"], p):
                break
    # 其余按「段得分 × 篇次权重」全局竞争
    rest = []
    for rank, d in enumerate(docs):
        w = DOC_DECAY[min(rank, len(DOC_DECAY) - 1)]
        rest += [(p["score"] * w, rank, d["id"], p) for p in cands[d["id"]]]
    rest.sort(key=lambda r: (-r[0], r[1]))
    for _, _, doc_id, p in rest:
        if budget - used < MIN_PIECE:
            break
        put(doc_id, p)
    # 一段都没命中（纯语义 / 标题命中）的篇：退回各字段开头
    for d in docs:
        if not taken[d["id"]]:
            content = content_fields(d)
            for key in [k for k in FIELD_ORDER if k in content][:2]:
                put(d["id"], {"field": key, "offset": 0, "text": content[key][:max(MIN_PIECE, share // 2)], "score": 0})
    order = {k: i for i, k in enumerate(FIELD_ORDER)}
    return {i: [{k: v for k, v in p.items() if k != "score"}
                for p in sorted(ps, key=lambda p: (order.get(p["field"], 99), p["offset"]))]
            for i, ps in taken.items()}
