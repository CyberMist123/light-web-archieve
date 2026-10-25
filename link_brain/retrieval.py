"""Local field-weighted retrieval. No model or network needed for search."""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ALIASES = json.loads((Path(__file__).parent / "assets/search-aliases.json").read_text(encoding="utf-8"))
# cats 是展示分组（大类），不是内容语义：只留低权兜底，让「搜大类名」能召回
# 无词帖（如搜"笑话"命中只分了类的帖子）。语义召回由 embedding 接住后应降到 0。
# notes = 她自己写的批注（notes.json，第 10 批进检索）：她亲手写的，和标签同权
WEIGHTS = {"title": 12, "tags": 10, "notes": 10, "highlights": 10, "cats": 3, "body": 7, "attachments": 6, "transcript": 6, "screen": 6,
           "ocr": 5, "comments": 3, "comment_ocr": 3, "summary": 2, "author": 1}


def norm(text):
    return unicodedata.normalize("NFKC", str(text or "")).casefold().strip()


def variants(term):
    term = norm(term)
    expanded = [term]
    for group in ALIASES:
        if term in group or (term == "音" and "音乐" in group):
            expanded.extend(group)
    return list(dict.fromkeys(expanded))


# ── 英文按词边界（第 10 批）：拉丁字母 / 数字开头的词，前面不能紧挨字母数字（cafeine 不再命中 ai）；
# 4 个字母以下的短词，后面也不能紧挨字母（允许复数 s / es：llm → llms），长词按词首匹配（dream → dreaming）。
# 中文照旧子串匹配。目录页 catalog-search.js termRegex 同一规则。
_PATTERNS = {}


def _pattern(v):
    if v in _PATTERNS:
        return _PATTERNS[v]
    pat = None
    if re.match(r"[a-z0-9]", v):
        tail = r"(?:e?s)?(?![a-z])" if re.fullmatch(r"[a-z0-9]+", v) and len(v) < 4 else ""
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(v) + tail)
    _PATTERNS[v] = pat
    return pat


def has(text, v):
    """text、v 都已 norm。"""
    if not v or v not in text:
        return False
    pat = _pattern(v)
    return True if pat is None else pat.search(text) is not None


def count(text, v):
    if not v or v not in text:
        return 0
    pat = _pattern(v)
    return text.count(v) if pat is None else sum(1 for _ in pat.finditer(text))


def short_latin(v):
    """一两个字母的英文词（ai、ok）。图片文字里这种词常是 OCR 从货架标签 / 小字里拆出来的零散字母（10-03 目录搜「ai 做梦」
    冒出超市半价帖：小票上有一行「AI I」）：只在图片文字里中的算低置信度（进「可能相关」）。目录页 isShortLatin 同一规则。"""
    return bool(re.fullmatch(r"[a-z0-9]{1,2}", v)) and not v.isdigit()


def find(text, v, start=0):
    """第一次出现的位置（同 has 的规则）；没有 = -1。"""
    pat = _pattern(v)
    if pat is None:
        return text.find(v, start)
    m = pat.search(text, start)
    return m.start() if m else -1


# ── 拼音整音节匹配（第 1 批 1002；与目录页 catalog-search.js 同一套规则） ──
# 条目的 pinyin 字段 = 标题 + 概要 + 标签的整音节，空格分隔，标点/空白处用「/」断开（catalog.py 写入）。
# 查询词里一个汉字 = 一个整音节，连续字母 = 若干相邻整音节拼起来；至少两个音节才算，
# 所以「西尼」能找回悉尼（同音错字），「xin」撞不上「xi ni」。拼音命中只算「可能相关」，不压过原词命中。
_HAN_RUN = re.compile(r"[一-鿿]+|[a-z0-9]+|[^一-鿿a-z0-9]+")


def syllables(text):
    """文本 -> 整音节列表（汉字转拼音、字母数字按词、其余记为断点「/」）。"""
    from pypinyin import lazy_pinyin
    out = []
    for run in _HAN_RUN.findall(norm(text)):
        if "一" <= run[0] <= "鿿":
            out.extend(lazy_pinyin(run))
        elif run[0].isascii() and run[0].isalnum():
            out.append(run)
        elif out and out[-1] != "/":
            out.append("/")
    return out


def pinyin_text(*parts):
    """写进 catalog-data 的 pinyin 字段：各段之间也断开，避免标题末字和概要首字拼成一个词。"""
    out = []
    for part in parts:
        sy = syllables(part)
        if sy:
            out.extend((["/"] if out and out[-1] != "/" else []) + sy)
    while out and out[-1] == "/":
        out.pop()
    return " ".join(out)


def pinyin_units(term):
    """词 → 拼音单元（拼音整音节匹配用）。纯函数，按词记忆：match() 每篇每个词都要它，不记的话关键词筛选一次要调几万次 pypinyin
    （R1 10-04 合成库实测占问收藏召回耗时三成多）。返回新 list，调用方随便改。"""
    units = _pinyin_units(str(term))
    return list(units) if units is not None else None


@__import__("functools").lru_cache(maxsize=4096)
def _pinyin_units(term):
    from pypinyin import lazy_pinyin
    units = []
    for part in re.findall(r"[a-z]+|[一-鿿]|[^\sa-z一-鿿]+", norm(term)):
        if re.fullmatch(r"[a-z]+", part):
            units.append(("latin", part))
        elif re.fullmatch(r"[一-鿿]", part):
            units.append(("syl", lazy_pinyin(part)[0]))
        elif re.search(r"[0-9a-z一-鿿]", part):
            return None  # 带数字等：不按拼音猜
    return tuple(units) or None


def pinyin_match(item_syllables, units):
    if not units or not item_syllables:
        return False
    sy = item_syllables

    def go(u, s, used):
        if u == len(units):
            return used >= 2
        kind, value = units[u]
        if kind == "syl":
            return s < len(sy) and sy[s] == value and go(u + 1, s + 1, used + 1)
        acc = ""
        for k in range(s, len(sy)):
            if len(acc) >= len(value):
                break
            acc += sy[k]
            if acc == value and go(u + 1, k + 1, used + k - s + 1):
                return True
        return False

    return any(go(0, i, 0) for i in range(len(sy)))


def item_syllables(item):
    return str(item.get("pinyin") or "").split()


def fields(item):
    return {"title": item.get("title", ""), "tags": " ".join(item.get("tags") or []),
            "cats": " ".join(item.get("cats") or []),
            "summary": item.get("summary", ""), "author": item.get("author", ""),
            **(item.get("search_fields") or {"body": item.get("search_text", "")})}


def _typo_in(text, term):
    """标题里有一段和词只差一个字（9 个字以上差两个）；三个字以下不算，免得到处都中。"""
    if term in text:
        return True
    if len(term) < 3:
        return False
    limit = 2 if len(term) >= 9 else 1
    prev = list(range(len(term) + 1))
    for ch in text:
        row = [0]
        for j in range(1, len(term) + 1):
            row.append(min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ch != term[j - 1])))
        if row[-1] <= limit:
            return True
        prev = row
    return False


def _gap_match(hay, term):
    """漏字 / 不连续输入：词里的字按顺序出现、总跨度不超过词长两倍（「鸡肉」找回「鸡腿肉」）。与目录页同一规则。"""
    if len(term) < 2:
        return False
    start = hay.find(term[0])
    while start >= 0:
        p = start
        for c in term:
            p = hay.find(c, p)
            if p < 0:
                break
            p += 1
        if p >= 0 and p - start <= len(term) * 2:
            return True
        start = hay.find(term[0], start + 1)
    return False


STAR_BOOST = 1.15  # ★ 只做小幅加成：目录页 catalog-search.js 和 rank() 同一个数


# ── CJK 复合词子词回退（R1）：短查询（≤ SUBWORD_MAX_TERMS 个词）里的中文词（2–4 个字）整词全库只中 ≤ SUBWORD_MAX_HITS 篇、
# 整个查询也只找回这么几篇时，
# 把它拆成单字参与匹配（「面点」→「面」「点」），但降权：BM25 里一个字的命中最多抵整词命中的一半、不算覆盖加成；
# 关键词筛选里算「可能相关」（kind subword），排在原词命中之后。目录页 catalog-search.js 同一规则（subwordParts / SUBWORD_*）。
GENERIC_DF = 0.4  # 全库四成以上的篇都有的词算泛（同 ask.EXPAND_GENERIC、recall_core.GENERIC_DF）
COMMON_DF = 0.6     # 全库六成以上的篇都有：查询侧动态 DF 抑制（R3）
COMMON_WEIGHT = 0.3
SUBWORD_MAX_HITS = 2
SUBWORD_MAX_TERMS = 3      # 只给短查询（「面点」这种一两个词的）：长句子别的词已经够召回，拆字只会添噪声
SUBWORD_WEIGHT = 0.3       # BM25：一个字的得分 × 这个数
SUBWORD_FIELD_SCALE = 0.05  # 关键词筛选：每个字取它最好的字段权重 × 这个数，几个字相加
_SUB_FUNC = set("的了吗呢吧啊呀么嘛哦着过得地是在有和与或及把被给让那这个们也都就还又再很太")


def subword_parts(term, others=()):
    """中文词 → 拆出的单字（去虚字）；不是 2–4 个汉字、或查询里已经有它的子串（已经拆过）→ []。"""
    term = norm(term)
    if not re.fullmatch(r"[一-鿿]{2,4}", term) or any(o != term and o and o in term for o in map(norm, others)):
        return []
    parts = [c for c in dict.fromkeys(term) if c not in _SUB_FUNC]
    return parts if parts and parts != [term] else []


def _subword_score(fs, parts):
    total = 0.0
    for part in parts:
        # cats 不算（目录页的字段里没有它）
        total += max((WEIGHTS.get(key, 1) for key, text in fs.items() if key != "cats" and part in text), default=0) * SUBWORD_FIELD_SCALE
    return total


def match(item, terms, *, require_all=False, subword=(), fs=None):
    """(分数, 是否模糊)。原词（含同义词）命中按字段权重计分；原词不中才认拼写相近 / 拼音整音节，
    这类命中记 fuzzy=True，调用方把它放进「可能相关」，排在原词命中之后（与目录页同一套规则）。
    第 10 批：英文按词边界（has），cafeine 不再命中 ai。
    subword：允许子词回退的词（见 subword_parts；调用方按全库命中数判过），其余模糊都不中时按单字算低分「可能相关」。
    fs：这篇各字段 norm 过的全文（调用方从 _documents 缓存里给，省得每次重算）。"""
    fs = fs if fs is not None else {key: norm(value) for key, value in fields(item).items()}
    total = 0.0
    fuzzy = False
    for term in terms:
        term = norm(term)
        if not term:
            continue
        best = max((WEIGHTS.get(key, 1) * (1 if v == term else .75)
                    for v in variants(term) for key, text in fs.items()
                    if has(text, v) and not (key == "ocr" and short_latin(v))), default=0)
        if not best and any(short_latin(v) and has(fs.get("ocr", ""), v) for v in variants(term)):
            best, fuzzy = 2, True  # 只在图片文字里的零散字母：可能相关
        # 纯字母短词（xin、ai）错一个字母 / 漏字母能撞上一大片英文单词：字母词至少 4 个才认这两种模糊（与目录页同）
        latin_short = bool(re.fullmatch(r"[a-z0-9]+", term)) and len(term) < 4
        if not best and not latin_short and _typo_in(fs["title"], term):
            best, fuzzy = 3, True  # 标题里错一个字（长词两个）：与目录页 fuzzyContains 同一规则
        if not best and re.fullmatch(r"[a-z]{4,}", term):
            if any(SequenceMatcher(None, term, word).ratio() >= .8
                   for word in re.findall(r"[a-z]+", fs["title"] + " " + fs["tags"])):
                best, fuzzy = 2, True
        if not best and pinyin_match(item_syllables(item), pinyin_units(term)):
            best, fuzzy = 2, True
        if not best and not latin_short and _gap_match(" ".join(fs.values()), term):
            best, fuzzy = 1, True
        if not best and term in subword:
            sub = _subword_score(fs, subword_parts(term))
            if sub:
                best, fuzzy = sub, True
        if not best and require_all:
            return 0, False
        total += best
    return total, fuzzy


def score(item, terms, *, require_all=False):
    return match(item, terms, require_all=require_all)[0]


_RANK_CACHE = (None, None)


def _documents(items):
    """各篇各字段 norm 过的全文 + 字段平均长度；同一份 items 只算一次（rank / term_stats 共用）。"""
    global _RANK_CACHE
    if _RANK_CACHE[0] is not items:
        documents = [{k: norm(v) for k, v in fields(it).items()} for it in items]
        _RANK_MEMO.clear()
        _STATS_MEMO.clear()
        averages = {k:sum(len(doc.get(k,'')) for doc in documents)/max(1,len(documents)) or 1 for k in WEIGHTS}
        _RANK_CACHE = (items, (documents, averages))
    return _RANK_CACHE[1]


_META_KEYS = ("title", "tags", "cats")


def term_stats(items, term):
    """(多少篇里有这个词, 其中多少篇是标题 / 标签 / 分类里就有)。只认原词和同义词，不算拼音、错字。

    问答判断追问用：人名、地名这类话题词大多出现在标题标签里；「调料」「价格」「步骤」这类属性词几乎只在正文里。"""
    documents, _ = _documents(items)
    key = (id(documents), str(term))
    hit = _STATS_MEMO.get(key)
    if hit is not None:
        return hit
    vs = variants(term)
    anywhere = meta = 0
    for doc in documents:
        if any(has(text, v) for v in vs for text in doc.values()):
            anywhere += 1
            if any(has(doc.get(k, ""), v) for v in vs for k in _META_KEYS):
                meta += 1
    if len(_STATS_MEMO) >= 2048:
        _STATS_MEMO.clear()
    _STATS_MEMO[key] = (anywhere, meta)
    return anywhere, meta


_STATS_MEMO: dict = {}  # term_stats 按 (这份规范化全文, 词) 记：一问里扩词过滤、话题词、窗口判泛都要问同一个词（R1 10-04）


def _bm25(documents, averages, term, aliases=True, best_field=False):
    """一个词在各篇的字段加权 BM25 词频分（同义词 ×0.75，取最好的那个说法）。各字段相加；best_field = 只取最好的那个字段（泛词用）。"""
    vs = variants(term) if aliases else [norm(term)]
    counts = []
    for doc in documents:
        best = 0
        for v in vs:
            value = 0
            for k, text in doc.items():
                tf = count(text, v)
                if tf:
                    # Saturate within each field: a long attachment must not erase a title hit.
                    length = min(len(text)/averages.get(k, 1), 3)
                    part = WEIGHTS.get(k, 1)*tf*2.2/(tf+1.2*(.25+.75*length))
                    value = max(value, part) if best_field else value + part
            best = max(best, value*(1 if v == term else .75))
        counts.append(best)
    return counts


_RANK_MEMO: dict = {}


def rank(items, terms, *, subword=True):
    """BM25 字段加权；同分保持稳定 ID 顺序，不按日期偏向新收藏。
    同一份 items、同一组词一问里会被几处要（宽召回核心、追问、多主题），结果按 (items, 词) 记最近几份，返回副本。
    subword：允不允许 CJK 子词回退（见 _rank）。只给她原话里的词；扩词 / 二轮反馈词这类单开一路的词一律 False——
    它们本来就是稀有的专名（「布里斯班」整词只中 2 篇），拆成「布」「里」「斯」「班」会把几百篇不相干的拉进融合（10-04 实测）。"""
    if not terms:
        return []
    documents, _ = _documents(items)
    key = (id(documents), tuple(map(str, terms)), bool(subword), tuple(bool(it.get("starred")) for it in items))
    hit = _RANK_MEMO.get(key)
    if hit is not None:
        return list(hit)
    out = _rank(items, terms, subword=subword)
    if len(_RANK_MEMO) >= 64:
        _RANK_MEMO.clear()
    _RANK_MEMO[key] = out
    return list(out)


def _rank(items, terms, subword=True):
    import math
    documents, averages = _documents(items)
    totals = [0.0] * len(items)
    covered = [0] * len(items)
    whole = {}
    raw = {term: _bm25(documents, averages, term) for term in dict.fromkeys(terms)}
    dfs = {term: sum(tf > 0 for tf in counts) for term, counts in raw.items()}
    generic = {term for term, df in dfs.items() if df >= len(items) * GENERIC_DF}
    # 泛词只算最好的那个字段（R1 10-04）：问题里既有泛词（全库四成以上都有，如「ai」）又有不泛的词时，泛词的 idf 虽低，
    # 可它在标题 / 标签 / 正文 / 附件里处处都中，逐字段累加起来，一篇只沾「ai」的能压过只在长附件里提到一次「回避」的篇
    # （「ai 吵架 回避」金标第 4 篇词法排 #103，前面八十来篇只沾 ai）。只取最好字段后它排 #21；
    # 31 题 capped recall@20 0.867 → 0.878，池覆盖持平。只有泛词的问题（就问「AI」）照旧逐字段累加。
    if generic and any(df and term not in generic for term, df in dfs.items()):
        raw.update({term: _bm25(documents, averages, term, best_field=True) for term in generic})
    # 动态 DF 抑制（1015 第三批 R3）：全库 ≥ COMMON_DF 的篇都有的词（「区」「老」「机」这类碎字），和不泛的词一起问时
    # 只给 COMMON_WEIGHT 的分、不算覆盖——它中不中几乎不区分篇，不该靠它把只沾它的篇抬上来。只有它的问题照旧。
    common = {term for term, df in dfs.items() if df >= len(items) * COMMON_DF}
    damp = bool(common) and any(df and term not in common for term, df in dfs.items())
    for term in terms:
        counts = raw[term]
        df = dfs[term]
        literal = df > 0
        if not df:
            # 原词哪篇都没有（多半是语音同音错字，如「西尼」）：退到拼音整音节，低权，只给标题/概要/标签读音相同的篇
            units = pinyin_units(term)
            counts = [1.0 if units and pinyin_match(item_syllables(it), units) else 0 for it in items]
            df = sum(tf>0 for tf in counts)
        whole[term] = (counts, df, literal)
        if not df:
            continue
        idf = math.log(1 + (len(items)-df+.5)/(df+.5))
        weak = damp and term in common
        for i, tf in enumerate(counts):
            if tf:
                if weak:
                    totals[i] += COMMON_WEIGHT * idf * tf
                    continue
                covered[i] += 1
                totals[i] += idf * tf
    # 子词回退（R1）：整个查询只找回 ≤ SUBWORD_MAX_HITS 篇时，稀有的中文复合词拆单字再找一遍，降权、不算覆盖，
    # 而且一篇从子词拿到的分最多是整词命中里最低那篇的一半——整词命中永远排前
    if subword and len(terms) <= SUBWORD_MAX_TERMS and sum(1 for value in totals if value > 0) <= SUBWORD_MAX_HITS:
        floor = min((value for value in totals if value > 0), default=0)
        for term in terms:
            counts, df, literal = whole.get(term, ([], 0, False))
            # 拼音整音节已经找回读音相同的篇（同音错字）：那才是她要的，不再拆字
            parts = subword_parts(term, terms) if df <= SUBWORD_MAX_HITS and (literal or not df) else []
            for part in parts:
                pc = _bm25(documents, averages, part, aliases=False)
                pdf = sum(tf > 0 for tf in pc)
                if not pdf:
                    continue
                pidf = math.log(1 + (len(items)-pdf+.5)/(pdf+.5))
                for i, tf in enumerate(pc):
                    if tf and not (counts and counts[i]):
                        totals[i] += SUBWORD_WEIGHT * pidf * tf
        if floor:
            totals = [value if covered[i] else min(value, floor * .5) for i, value in enumerate(totals)]
    # ★（磁吸）是显式信号：轻微上浮，别盖过内容相关性
    hits = [(value * (1 + .15 * covered[i]) * (STAR_BOOST if it.get('starred') else 1), it)
            for i,(value,it) in enumerate(zip(totals,items)) if value>0]
    hits.sort(key=lambda x:(-x[0],str(x[1].get('id',''))))
    return hits


def query_facets(items, question):
    """Separate topic clauses from formatting instructions and broad filler."""
    from .ask import query_terms
    clauses=[]
    for clause in re.split(r'[；;，,。！？?!\n]',question):
        part=query_terms(clause)
        if not part or set(part)<={'ai','项目'}:continue
        candidates=rank(items,part)
        # Broad filler such as AI alone is not a separate facet in a long request.
        selective=any(sum(score(it,[t])>0 for it in items)<len(items)*.5 for t in part)
        if candidates and selective:clauses.append((clause,candidates))
    return clauses


def semantic_hits(question):
    """语义层 chunk 命中；任何失败返回 None，检索退纯词法（Lot B 硬约束）。"""
    try:
        from . import semantic
        return semantic.query_hits(question)
    except Exception:  # noqa: BLE001 - fail-open：语义层缺失/损坏不许影响词法路径
        return None


def semantic_deep(question):
    """语义一路的续取（R1）：相对下限以上的全部篇，不截前 TOP_ITEMS。同一问的查询向量有缓存，不多调接口。失败 = None。"""
    try:
        from . import semantic
        return semantic.query_hits(question, top_items=None)
    except Exception:  # noqa: BLE001
        return None


def fuse(routes, items, k=60):
    """多路召回的加权 RRF：routes = [(权重, [item_id 按名次]) 或 (权重, [...], 组名)]；一篇在几路里都靠前就排前。

    同一组的几路只取这一篇在组里最好的那一路（第 10 批：扩出的十来个词各开一路，一篇泛泛沾上好几个扩词
    不该累加得比原词命中还高——实测累加时「美食」「餐厅」这类扩词把原词命中的篇挤出前 8）。返回 [(分数, item)]。"""
    by_id = {it.get('id'): it for it in items}
    scores, groups = {}, {}
    for route in routes:
        weight, ids, group = (route + (None,))[:3]
        for r, item_id in enumerate(dict.fromkeys(ids), 1):
            if item_id not in by_id:
                continue
            value = weight / (k + r)
            if group is None:
                scores[item_id] = scores.get(item_id, 0.0) + value
            else:
                key = (group, item_id)
                groups[key] = max(groups.get(key, 0.0), value)
    for (_, item_id), value in groups.items():
        scores[item_id] = scores.get(item_id, 0.0) + value
    fused = [(value, by_id[item_id]) for item_id, value in scores.items()]
    fused.sort(key=lambda x: (-x[0], str(x[1].get('id', ''))))
    return fused


def sem_order(sem):
    return [item_id for item_id, _ in sorted((sem or {}).items(), key=lambda kv: -kv[1]['score'])]


_ASK_SEM = object()


def rank_query(items, question, terms=None, sem=_ASK_SEM, extra=None):
    """Keep distinct clauses represented when a request contains several topics.

    sem：调用方已经拿过的 semantic_hits 结果（问答要接着用它的 chunk 当证据，不重算）。
    extra：别的召回路 [(权重, [item_id…])]（第 10 批：扩词每个词一路、扩词的语义一路），和原词、语义一起 RRF。
    """
    from .ask import query_terms
    terms=terms if terms is not None else query_terms(question)
    hits=rank(items,terms)
    if sem is _ASK_SEM:
        sem=semantic_hits(question)
    if sem or extra:
        routes=[(1,[it['id'] for _,it in hits])]
        if sem:
            routes.append((1,sem_order(sem)))
        hits=fuse(routes+list(extra or []),items)
    clauses=query_facets(items,question)
    if len(clauses)<2:return hits
    chosen=[];seen=set()
    for _,candidates in clauses:
        value,it=candidates[0]
        if it['id'] not in seen:chosen.append((value,it));seen.add(it['id'])
    return chosen+[(s,it) for s,it in hits if it['id'] not in seen]


def excerpts(item, terms, limit=800, window_chars=450, fallback=True):
    """取命中密度最高的最多三段原文，跨正文/附件/转写，严格共享字数上限。

    一个词都没命中时：fallback=True 退回某字段的开头+结尾；False 返回 []（交给 evidence 用语义片段）。
    """
    import math
    candidates = []
    windows = []
    focused = [t for t in terms if norm(t) not in {'ai', '系统', '项目', '功能', '内容', '相关'}]
    groups = list(dict.fromkeys(tuple(variants(t)) for t in (focused or terms)))
    width = max(80, min(window_chars, limit // 2))
    for key, value in fields(item).items():
        if key in {'title','tags','cats','author','summary'} or not value:
            continue
        text = str(value)
        starts = dict.fromkeys(range(0, len(text), max(40,width//2)), 0)
        for heading in re.finditer(r'(?m)^(?:#{1,6}\s+|\d+[.、 /|]).{1,75}$', text):
            h = norm(heading.group())
            if any(has(h, v) for group in groups for v in group):
                starts[heading.start()] = 3
        for start, heading_bonus in starts.items():
            window = text[start:start+width]
            normalized = norm(window)
            counts = [max((count(normalized, v) for v in group), default=0) for group in groups]
            windows.append((key, start, window, counts, heading_bonus))
    # A topic word in a few windows carries more evidence than "AI/system"
    # repeated throughout a long post. Score actual occurrences, not just presence.
    rarity = [math.log(1 + len(windows) / (1 + sum(row[3][i] > 0 for row in windows)))
              for i in range(len(groups))]
    for key, start, window, counts, heading_bonus in windows:
        relevance = sum(weight * min(count, 3) for weight, count in zip(rarity, counts)) * (1 + heading_bonus)
        if relevance:
            candidates.append((relevance * WEIGHTS.get(key,1), key, start, window))
    candidates.sort(key=lambda x:(-x[0],x[1],x[2]))
    selected=[];budget=limit
    body = str(fields(item).get('body') or '')
    for _,key,start,text in candidates:
        # Keep short author posts intact: adjacent numbered updates often explain
        # each other, and a high-scoring later heading must not erase an earlier one.
        if key == 'body' and any(k == 'body' and old == body for k, _, old in selected):
            continue
        if key == 'body' and len(body) <= min(1000, budget):
            start, text = 0, body
        if any(k==key and abs(pos-start)<width for k,pos,_ in selected):
            continue
        selected.append((key,start,text[:budget]));budget-=len(text[:budget])
        if len(selected)==3 or budget<=0:break
    if not selected and not fallback:
        return []
    if not selected:
        fs=fields(item)
        key=next((k for k in ['body','ocr','attachments','transcript'] if len(str(fs.get(k,'')))>80),'body')
        text=str(fs.get(key) or item.get('search_text') or item.get('summary') or '')
        if len(text)>limit:
            half=limit//2;selected=[(key,0,text[:half]),(key,len(text)-(limit-half),text[-(limit-half):])]
        else:selected=[(key,0,text)]
    return [{'field':key,'text':text} for key,_,text in selected]


def _evidence(item, terms, limit, sem=None, window_chars=450, max_parts=3):
    """一篇的证据片段：语义命中的 chunk 原文在前，词法窗口补足预算；两边都没有才退回开头+结尾。

    1001 审计 ask-7：只靠语义召回的长文（换了说法提问），词法一个词都不中，
    以前问答送给模型的是开头+结尾，真正相关的中间那段不在里面。问答和 lb_retrieve 共用这一份。
    """
    chunks=[c for c in ((sem or {}).get(item.get('id')) or {}).get('chunks') or [] if c.get('field')!='meta']
    if not chunks:
        return excerpts(item,terms,limit,window_chars)
    out=[];used=0
    for part in chunks+excerpts(item,terms,limit,window_chars,fallback=False):
        if used>=limit or len(out)==max_parts:break
        text=str(part['text'])[:limit-used]
        if not text or any(text[:60] in e['text'] or e['text'][:60] in text for e in out):
            continue
        out.append({'field':part['field'],'text':text});used+=len(text)
    return out or excerpts(item,terms,limit,window_chars)


def lexical_excerpt(item, terms, limit=120):
    """一篇的单段命中摘录（R2「其他相关」卡用）：只走词法、只取一个字段、逐字原文、不超过 limit 字。

    选「中的不同词最多」的字段（同数按字段权重），窗口从该字段第一个命中前 limit/4 处开始。
    一个词都没中返回空串——不拿概要冒充命中依据。"""
    groups = list(dict.fromkeys(tuple(variants(t)) for t in terms or () if norm(t)))
    best = None
    for key, value in fields(item).items():
        if key in {'title', 'tags', 'cats', 'author', 'summary'} or not value or not groups:
            continue
        text = str(value)
        # 不 strip：位置要和原文对得上；NFKC 改了长度（极少见）时按比例折回原文位置，摘录照样是原文切片
        low = unicodedata.normalize("NFKC", text).casefold()
        firsts = []
        for group in groups:
            spots = [p for p in (find(low, v) for v in group if v and v in low) if p >= 0]
            if spots:
                firsts.append(min(spots))
        if not firsts:
            continue
        hit = min(firsts)
        if len(low) != len(text):
            hit = hit * len(text) // max(1, len(low))
        start = max(0, min(hit - limit // 4, len(text) - limit))
        rank_key = (len(firsts), WEIGHTS.get(key, 1))
        if best is None or rank_key > best[0]:
            best = (rank_key, {'field': key, 'text': text[start:start + limit]})
    return best[1] if best else {'field': '', 'text': ''}


def _content_fields(item):
    return {key: str(value) for key, value in fields(item).items()
            if key not in {'title', 'tags', 'cats', 'author', 'summary'} and value}


def _field_evidence(item, key, text, terms, budget, sem, window_chars, max_parts):
    if len(text) <= budget:
        return [{'field': key, 'text': text}]
    chunks = [part for part in ((sem or {}).get(item.get('id')) or {}).get('chunks', []) if part.get('field') == key]
    scoped = {item.get('id'): {'chunks': chunks}}
    parts = _evidence({'id': item.get('id'), 'search_fields': {key: text}}, terms, budget,
                      scoped, window_chars, max_parts)
    if max_parts == 1 and parts:
        start = text.find(parts[0]['text'])
        if start >= 0:
            start = min(start, max(0, len(text) - budget))
            return [{'field': key, 'text': text[start:start + budget]}]
    return parts[:max_parts]


def evidence(item, terms, limit, sem=None, window_chars=450, max_parts=3, deep=False):
    legacy = _evidence(item, terms, limit, sem, window_chars, max_parts)
    try:
        content = _content_fields(item)
        if deep:
            quotas = {}
            if 'body' in content and len(content['body']) <= 1000:
                quotas['body'] = min(len(content['body']), limit)
            remaining = limit - sum(quotas.values())
            rest = {key: text for key, text in content.items() if key not in quotas}
            total = sum(map(len, rest.values()))
            for index, (key, text) in enumerate(rest.items()):
                budget = min(len(text), remaining if index == len(rest) - 1 else remaining * len(text) // total)
                quotas[key] = budget
                remaining -= budget
                total -= len(text)
            parts = []
            for key, budget in quotas.items():
                if budget > 0:
                    parts.extend(_field_evidence(item, key, content[key], terms, budget, sem, window_chars, 1))
            return parts[:max_parts] or legacy
        total = sum(map(len, content.values()))
        required = [key for key, text in content.items() if len(text) >= total * .4
                    and any(has(norm(text), variant) for term in terms for variant in variants(term))]
        missing = [key for key in required if not any(part['field'] == key for part in legacy)]
        if not missing:
            return legacy
        reserved = []
        budget = min(window_chars, limit // (len(missing) + 1))
        for key in missing:
            reserved.extend(_field_evidence(item, key, content[key], terms, budget, sem, window_chars, 1)[:1])
        out, remaining = [], limit
        for part in reserved + legacy:
            if remaining <= 0 or len(out) >= max_parts:
                break
            text = part['text'][:remaining]
            if text:
                out.append({**part, 'text': text})
                remaining -= len(text)
        return out or legacy
    except Exception:
        return legacy


_CORPUS_CACHE = (None, "")


def split_phrase(term, items):
    """整串中文短语库里一处都没有时，拆成库里出现过的词（每段至少两个字、段数最少）：
    「悉尼咖啡」→ [悉尼, 咖啡]、「AI做梦」→ [ai, 做梦]，和拆开输入找回同一批。与 catalog-search.js splitPhrase 同一规则。"""
    global _CORPUS_CACHE
    scripts = re.findall(r"[a-z0-9]+|[一-鿿]+", term)
    mixed = len(scripts) > 1 and "".join(scripts) == term and all(len(p) >= 2 for p in scripts)
    if not mixed and not re.fullmatch(r"[一-鿿]{4,12}", term):
        return [term]
    if _CORPUS_CACHE[0] is not items:
        _CORPUS_CACHE = (items, "\n".join(" ".join(norm(v) for v in fields(it).values()) for it in items))
    hay = _CORPUS_CACHE[1]
    if term in hay:
        return [term]
    if mixed:  # 中英混写（「AI做梦」）先按字母 / 汉字分开，汉字那段再拆
        return [q for p in scripts for q in (split_phrase(p, items) if "一" <= p[0] <= "鿿" else [p])]
    best = [None] * (len(term) + 1)
    best[0] = []
    for i in range(len(term)):
        if best[i] is None:
            continue
        for j in range(i + 2, min(len(term), i + 8) + 1):
            part = term[i:j]
            if part in hay and (best[j] is None or len(best[i]) + 1 < len(best[j])):
                best[j] = best[i] + [part]
    got = best[len(term)]
    return got if got and len(got) > 1 else [term]


def _keyword_sort(hits):
    # 与目录页同口径：原词命中在前、「可能相关」在后；组内 分数 × 星标加成，同分星标在前，再同分新收藏在前
    hits.sort(key=lambda x: (not x[1], x[0] * (STAR_BOOST if x[2].get("starred") else 1),
                             bool(x[2].get("starred")), x[2].get("ts", "")), reverse=True)
    return hits


def keyword_terms(query, items):
    return [part for x in str(query or "").split() if x.strip() for part in split_phrase(norm(x), items)]


def keyword_hits(query, items):
    """目录页关键词筛选的 Python 版（与 catalog-search.js rankItems 同规则）：[(分数, 是否可能相关, item)]，已排好序。
    多个词都要中（AND）；整个查询原词只中 ≤ SUBWORD_MAX_HITS 篇时，稀有中文词再按单字找一遍（只进「可能相关」）。
    lb_search 和宽召回核心（recall_core 的 keyword 一路）都用它。"""
    query = str(query or "").strip()
    tag_query = query.startswith("#")
    terms = keyword_terms(query, items)
    documents, _ = _documents(items)
    hits = []
    for item, doc in zip(items, documents):
        if tag_query:
            s, fuzzy = (10 if any(norm(t).lstrip("#") in query.lower().split("#")[1:] for t in item.get("tags", [])) else 0), False
        else:
            s, fuzzy = match(item, terms, require_all=True, fs=doc) if terms else (1, False)
        if s:
            hits.append((s, fuzzy, item))
    if terms and not tag_query and len(terms) <= SUBWORD_MAX_TERMS and sum(1 for _, fuzzy, _ in hits if not fuzzy) <= SUBWORD_MAX_HITS:
        documents, _ = _documents(items)
        def literal_df(t):
            return sum(1 for doc in documents if any(has(text, v) for v in variants(t) for k, text in doc.items() if k != "cats"))

        def homophone(t):  # 原词一篇没有、拼音整音节找回了读音相同的篇（同音错字）：那才是她要的，不再拆字
            units = pinyin_units(t)
            return bool(units) and any(pinyin_match(item_syllables(it), units) for it in items)

        rare = set()
        for t in terms:
            if subword_parts(t):
                df = literal_df(t)
                if df <= SUBWORD_MAX_HITS and not (df == 0 and homophone(t)):
                    rare.add(t)
        if rare:
            have = {id(it) for _, _, it in hits}
            for item, doc in zip(items, documents):
                if id(item) in have:
                    continue
                s, fuzzy = match(item, terms, require_all=True, subword=rare, fs=doc)
                if s:
                    hits.append((s, True, item))
    return _keyword_sort(hits)


def search(query, limit=20, offset=0):
    from .ask import load_items, query_terms
    from . import storage
    items = load_items()
    hits = keyword_hits(query, items)
    if not hits and not query.startswith("#"):
        fallback = query_terms(query)
        hits = _keyword_sort([(s, fuzzy, it) for it in items for s, fuzzy in [match(it, fallback)] if s > 0])
    terms = keyword_terms(query, items)
    offset = max(0, int(offset or 0))
    page = hits[offset:offset + max(0, int(limit))]
    results = []
    for s, fuzzy, it in page:
        results.append({"item_id": it["id"], "title": it["title"], "score": s, "starred": bool(it.get("starred")),
                        "match": "possible" if fuzzy else "exact",
                        "excerpts": excerpts(it, terms, 700), "url": it.get("url"),
                        "visible_note": str(storage.vault_root() / it["note"]) if it.get("note") else None,
                        "agent_md": str(storage.vault_root() / it["agent_md"]) if it.get("agent_md") else None,
                        "attachments": it.get("attachment_files", []), "tags": it.get("tags", []),
                        "summary": it.get("summary", ""), "first_archived": it.get("date", "")})
    end = offset + len(results)
    # total = 一共找到几篇；found = 这一页给了几篇（旧键，含义不变）；has_more / next_offset = 还有没有、从哪续取
    return {"status": "ok", "query": query, "total": len(hits), "results": results, "found": len(results),
            "offset": offset, "next_offset": end if end < len(hits) else None, "has_more": end < len(hits),
            "items": [{k: row[k] for k in ("item_id", "title", "summary", "tags", "url", "first_archived")} for row in results]}


def _web_url(note):
    """手机浏览器能开的地址：LINK_BRAIN_WEB_URL（WebDAV 等）+ 笔记路径；没配就不给，别把私人域名写进公开代码。"""
    import os
    from urllib.parse import quote
    base=os.environ.get('LINK_BRAIN_WEB_URL','').rstrip('/')
    return base+'/'+quote(note) if base else None


def retrieve_payload(question, top_k=8, offset=0):
    """与问答共用宽召回核心（recall_core.candidates：同一个候选集、同一个顺序）和摘录；给 Fable 返回材料，不调作答模型。
    条数只由 top_k（这一页几篇，封顶 20）和 offset（从第几篇续取）决定；total = 候选集一共几篇。"""
    import os
    from urllib.parse import quote
    from .ask import load_items
    from . import recall_core
    # 不现调扩词小模型（README：lb_retrieve 不花模型钱）：只用问收藏已经算过的扩词缓存，没缓存 = 不扩
    found=recall_core.candidates(question,load_items(),allow_expand_call=False)
    terms,sem=found["terms"]+found["expansion"]["terms"],found["sem"]
    count=max(1,min(20,top_k))
    rows,info=recall_core.page(found,offset,count)
    scores=found.get("scores") or {}
    budget=max(100,2500//max(1,min(count,len(rows) or 1)))
    results=[]
    for it in rows:
        value=scores.get(it['id'],0.0)
        note=it.get('note') or ''
        parts=evidence(it,terms,budget,sem)  # 命中 chunk 的原文优先充当证据，词法窗口补足预算
        results.append({'item_id':it['id'],'title':it['title'],'score':round(value,3),
            'excerpts':parts,'note':note,
            'obsidian_url':'obsidian://open?vault='+quote(os.environ.get('LINK_BRAIN_OBSIDIAN_VAULT','vault'))+'&file='+quote(note),
            'web_url':_web_url(note),
            'source_url':it.get('url'),'has_attachments':bool(it.get('attachment_files')),
            'has_transcript':bool((it.get('search_fields') or {}).get('transcript') or (it.get('search_fields') or {}).get('screen')),
            'starred':bool(it.get('starred')),'starred_at':it.get('starred_at')})
    return {'status':'ok','query':question,'total':info['total'],'results':results,'model_called':False,
            'offset':info['offset'],'next_offset':info['next_offset'],'has_more':info['has_more'],
            'expand_status':found["expansion"].get("status")}
