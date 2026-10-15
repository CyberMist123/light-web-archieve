"""查询侧地名层级（1015 第三批 R3）：她问「澳洲 / 🇦🇺 好吃的」时，只写了「悉尼 / 墨尔本 / Chatswood / 新州」的帖也算沾上「澳洲」。

只在查询侧用，不改索引、不硬过滤：
- expand_variants(term)：上级地名 → 自己的各种叫法 + 下级地名（核心词覆盖 / 真命中判定用）；
- route(items, places)：下级地名单开一路召回（融合权重同扩词路），只写了城市名的帖也能进候选；
- boost(pool, terms, items)：前 BOOST_HEAD 篇按「地名 facet + 其余核心词」在高权字段命中的程度另排一个名次，和现序做一次
  RRF（k=BOOST_K）——标题 / 标签里就写着「澳洲 + 好吃」的篇往前，完全沾不上地名的（「潮汕好吃的」）往后，但一篇不删。
表在 assets/places.json（国家 → 城市 / 州 / 常见区名，中国省 → 市少量）。读不了表 = 什么都不做（fail-open）。
"""
from __future__ import annotations

import json
from pathlib import Path

BOOST_HEAD = 40      # 只重排前这么多篇（首屏主要依据 + 目录前几页）；更后面的顺序不动
BOOST_K = 10         # 现序名次的 RRF 常数（同 ask.RERANK_FUSE_K 的口径）
FACET_K = 2          # facet 名次的 RRF 常数：小 = facet 前几名的加分明显（「标题就写着澳洲 + 好吃」的那篇顶上来），往后很快拉平
CHILD_FACTOR = 0.8   # 只写了下级地名：facet 分打八折（写明「澳洲」的更贴题）
PLACE_SHARE = 0.25   # facet 分里地名本身占的份量（其余核心词为主；只问「澳洲」时就按它排）
ROUTE_DEPTH = 40     # 下级地名那一路进融合的名次

_TABLE: list | None = None


def table() -> list[dict]:
    global _TABLE
    if _TABLE is None:
        from .retrieval import norm
        try:
            raw = json.loads((Path(__file__).parent / "assets" / "places.json").read_text(encoding="utf-8"))
            rows = raw.get("places") if isinstance(raw, dict) else []
            _TABLE = [{"names": [norm(n) for n in r.get("names") or [] if str(n).strip()],
                       "children": [norm(c) for c in r.get("children") or [] if str(c).strip()]}
                      for r in rows if isinstance(r, dict) and r.get("names")]
        except (OSError, ValueError, AttributeError):
            _TABLE = []
    return _TABLE


def place_of(term):
    """term 正好是表里某个上级地名的一种叫法 → 那一行；否则 None。"""
    from .retrieval import norm
    t = norm(term)
    for row in table():
        if t in row["names"]:
            return row
    return None


def query_places(text):
    """问题（或词表）里提到的上级地名行（去重、按表序）。「澳洲」「澳大利亚」「🇦🇺」都认。"""
    from .retrieval import has, norm
    if isinstance(text, (list, tuple, set)):
        text = " ".join(map(str, text))
    q = norm(text)
    return [row for row in table() if any(has(q, n) for n in row["names"])]


def expand_variants(term):
    """retrieval.variants 之外再带上地名层级：上级地名 → 自己的叫法 + 全部下级地名；别的词原样。"""
    from .retrieval import variants
    out = list(variants(term))
    row = place_of(term)
    if row:
        out += row["names"] + row["children"]
    return list(dict.fromkeys(out))


def route(items, rows):
    """下级地名一路的完整名单 [id…]（融合只用前 ROUTE_DEPTH 名）；没有下级地名 = []。不拆字（城市名是专名）。"""
    from .retrieval import rank
    children = [c for row in rows for c in row["children"]]
    if not children:
        return []
    return [it["id"] for _, it in rank(items, children, subword=False)]


def _best_field(doc, names):
    from .retrieval import WEIGHTS, has
    best = 0
    for key, text in doc.items():
        w = WEIGHTS.get(key, 1)
        if w > best and text and any(has(text, n) for n in names):
            best = w
    return best


def facet_score(doc, rows, others):
    """沾上地名（写明上级地名 = 字段权重；只写下级 = ×CHILD_FACTOR）才有分：其余核心词「最好字段权重 × 稀有度」之和为主，
    地名只按 PLACE_SHARE 计（它是条件不是主题——「澳洲看病保险」不能让标题写着澳洲、讲别的的帖顶上来）。没沾上地名 = 0。
    others = [(这个词的各种写法, 稀有度份量)]。"""
    names = [n for row in rows for n in row["names"]]
    children = [c for row in rows for c in row["children"]]
    place = max(_best_field(doc, names), CHILD_FACTOR * _best_field(doc, children))
    if not place:
        return 0.0
    return PLACE_SHARE * place + sum(share * _best_field(doc, vs) for vs, share in others)


def boost(pool, terms, items, *, rows=None, question=""):
    """前 BOOST_HEAD 篇按地名 facet 重排（见模块说明）。问题里没有上级地名 / 表空 = 原样返回。"""
    rows = rows if rows is not None else query_places(question or terms)
    if not rows or len(pool) < 2:
        return pool
    from .retrieval import _documents, term_stats, variants
    documents, _ = _documents(items)
    doc_of = {it.get("id"): doc for it, doc in zip(items, documents)}
    place_names = {n for row in rows for n in row["names"] + row["children"]}
    import math
    n_items = max(1, len(items))
    cand = [t for t in dict.fromkeys(terms or []) if len(t) >= 2 and t not in place_names
            and not any(t in n or n in t for n in place_names)]
    # 相邻实词拼成的短语（「广州好吃」= 广州 + 好吃）不单算，算它的组成词
    from .ask import _phrase_terms
    phrases = _phrase_terms(cand)
    cand = [t for t in cand if t not in phrases]
    # 同一个意思只算一次：「留学 / 学生」是「留学生」的子词，都算会把沾「留学」的生活帖抬过真讲保险的那篇
    cand = [t for t in cand if not any(t != o and t in o for o in cand)]
    others = []
    for t in cand:
        df = term_stats(items, t)[0]
        if df >= n_items * 0.6:
            continue
        # 按稀有度给份量（idf / 全库最稀有时的 idf）：「保险」比「学生」值钱；库里没有的词（df 0）不算
        if df:
            others.append((variants(t), math.log(1 + n_items / df) / math.log(1 + n_items)))
    head = list(pool[:BOOST_HEAD])
    scores = [facet_score(doc_of.get(it.get("id"), {}), rows, others) for it in head]
    if not any(scores):
        return pool
    facet_rank = {i: r for r, i in enumerate(sorted(range(len(head)), key=lambda i: (-scores[i], i)))}

    def fused(i):
        value = 1 / (BOOST_K + i + 1)
        if scores[i] > 0:
            value += 1 / (FACET_K + facet_rank[i] + 1)
        return -value
    order = sorted(range(len(head)), key=lambda i: (fused(i), i))
    return [head[i] for i in order] + list(pool[BOOST_HEAD:])
