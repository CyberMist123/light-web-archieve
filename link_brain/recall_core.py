"""宽召回核心（Lot R1）：问收藏、本地 MCP lb_retrieve、远程 search 共用这一个候选集；目录搜索（catalog-search.js）和
lb_search 走同一套关键词筛选规则（retrieval.keyword_hits，与目录页同口径），它们筛出来的篇也一并记进候选集。

三步分开（TASKBOOK 决策边界 1）：
- recall（这里）：candidate_set = 各路检出的并集，全量记录 + 排名，不截断、不补满（3 篇相关就是 3 篇）；
- selection_for_prompt（ask.py）：从首屏窗口里挑几篇、每篇多少字送模型；
- answer（ask.py）：作答。
首屏窗口 window = 各路前几名保底（POOL_HEADS）的篇，按融合顺序，最多 POOL_MAX 篇——页面「主要依据 + 其他相关」就从它切，
和她验收过的样子一样。窗口外的篇不丢：按同一顺序排在 candidates 后面（分页参数 / 以后的「继续看」从这里续取）。
各路的完整名单都在 routes 里，评测（tests/tools/ask_eval.py）据此证明「检出了却从候选集里静默消失」的篇数为 0。

四个入口同一个问题、同一份配置时，candidates 的顺序完全一样；条数差异只来自各入口显式的分页参数（top_k / limit / offset）。
fail-open：没 key（没语义、没扩词）/ 没索引时退回纯词法，和今天一样。
"""
from __future__ import annotations

import contextvars
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

POOL_MAX = 80  # 首屏窗口上限：全部回给页面（「其他相关」可删）；超出的留在 candidates 里
# 各路保底进首屏的名次：原词 BM25 / 语义 / 每个扩词 / 追问时上一问 / 二轮反馈词
POOL_HEADS = {"lexical": 40, "semantic": 40, "expand": 20, "followup": 40, "feedback": 10}

# 二轮扩词（伪相关反馈，不调模型）：从第一轮融合前 FEEDBACK_DOCS 篇的标题 / 标签里取「至少两篇都有」的词，
# 库里不算泛（≤ 全库 FEEDBACK_MAX_DF）也不算孤（≥ 2 篇），最多 FEEDBACK_TERMS 个。只做一轮，而且只补首屏窗口的空位：
# 第一轮已经检出、但排在各路保底名次之外的长尾篇，同时沾上反馈词的提进窗口尾部；第一轮的排序一点不动。
FEEDBACK_DOCS = 8
FEEDBACK_TERMS = 4
FEEDBACK_AGREE = 2
FEEDBACK_MAX_DF = 0.15

_UNSET = object()


def _semantic(question):
    """语义一路：先拿和以前一样的那份（测试 / 调用方可以换掉 retrieval.semantic_hits），再续取相对下限以上的全部篇
    （semantic.TOP_ITEMS 的上游截断不再吃掉长尾）。续取那份必须包含前一份，否则就用前一份（fail-open）。"""
    from . import retrieval
    sem = retrieval.semantic_hits(question)
    if not sem:
        return sem
    deeper = retrieval.semantic_deep(question)
    return deeper if deeper and set(sem) <= set(deeper) else sem


class Probe:
    """一问开头就并行起两件慢事：小模型扩词（顺带意图分类）和这一问的 embedding。
    问收藏先等扩词那份拿意图决定走哪条答法（链接清单 / GitHub / 正常作答），再把两份都交给 candidates，不重复调用。"""

    def __init__(self, question, history=None, *, semantic=True, expand=True, allow_expand_call=True):
        from . import ask
        self.question = question
        pool = ThreadPoolExecutor(max_workers=2)
        self._llm = None
        if expand and ask.query_terms(question):
            kwargs = {"allow_call": allow_expand_call}
            prev = previous_question(history)
            if prev:
                kwargs["previous"] = prev
            self._llm = pool.submit(contextvars.copy_context().run, ask.llm_expansions, question, **kwargs)
        self._sem = pool.submit(contextvars.copy_context().run, _semantic, question) if semantic else None
        pool.shutdown(wait=False)

    def llm(self):
        if self._llm is None:
            return {"terms": [], "status": "skipped"}
        try:
            return self._llm.result()
        except Exception as exc:  # noqa: BLE001 - 扩词失败 = 不扩
            return {"terms": [], "status": "failed", "error": type(exc).__name__}

    def sem(self):
        if self._sem is None:
            return None
        try:
            return self._sem.result()
        except Exception:  # noqa: BLE001 - 语义层失败 = 纯词法
            return None


def previous_question(history):
    """上一轮她问的话（意图分类判断「接着问 / 换话题」用）；没有 = ''。"""
    for m in reversed(list(history or [])[-8:]):
        if isinstance(m, dict) and m.get("role") == "user" and str(m.get("content") or "").strip():
            return str(m["content"])[:300]
    return ""


def feedback_terms(items, fused, own_terms, skip=(), *, docs=FEEDBACK_DOCS):
    """二轮扩词：第一轮真实召回的前几篇（不只第一名）标题 / 标签里，至少 FEEDBACK_AGREE 篇共有、库里不泛不孤的词。纯本地。"""
    import jieba
    from .ask import _FUNC_CHARS, _STOP
    from .retrieval import norm, term_stats, variants
    own = {v for t in own_terms for v in variants(t)} | {norm(t) for t in skip}
    agree: dict[str, int] = {}
    for it in fused[:docs]:
        text = norm(it.get("title")) + " " + " ".join(norm(t) for t in it.get("tags") or [])
        words = set()
        for chunk in re.findall(r"[a-z][a-z0-9]{2,}|[一-鿿]{2,}", text):
            parts = jieba.lcut(chunk) if "一" <= chunk[0] <= "鿿" else [chunk]
            words |= {w for w in parts if len(w) >= 2 and not set(w) <= _FUNC_CHARS and w not in _STOP}
        for w in words:
            agree[w] = agree.get(w, 0) + 1
    limit = max(2, len(items) * FEEDBACK_MAX_DF)
    scored = []
    for word, n in agree.items():
        if n < FEEDBACK_AGREE or word in own or any(word in o or o in word for o in own if len(o) >= 2):
            continue
        anywhere, _ = term_stats(items, word)
        if 2 <= anywhere <= limit:
            scored.append((-n, anywhere, word))
    return [word for *_, word in sorted(scored)[:FEEDBACK_TERMS]]


def candidates(question, items, *, settings=None, history=None, semantic=True, expand=True, allow_expand_call=True,
               llm=None, sem=_UNSET, keyword=True, feedback=True, trace=False) -> dict[str, Any]:
    """一个问题 → 全量候选集。返回 dict：
    matches = 首屏窗口（≤ POOL_MAX，页面主要依据 + 其他相关从这里切）；candidates = 全量（窗口在前，窗口外的按融合顺序跟后面，
    最后是只有关键词筛选命中的篇）；mode / prior_terms / terms / sem / expansion / intent / feedback；routes = 各路完整名单；
    trace=True 时另给 stages（R0 六层记录）。llm / sem 传了就直接用（问收藏开头已经并行起好了，见 Probe）。"""
    from . import ask, retrieval
    terms = ask.query_terms(question)
    if llm is None or sem is _UNSET:
        probe = Probe(question, history, semantic=semantic and sem is _UNSET,
                      expand=expand and llm is None, allow_expand_call=allow_expand_call)
        llm = llm if llm is not None else probe.llm()
        sem = probe.sem() if sem is _UNSET else sem
    if not semantic:
        sem = None
    expansion = ask.expand_query(question, terms, items, llm=llm)
    intent = llm.get("intent") if isinstance(llm.get("intent"), dict) else None
    # 扩词的语义一路：原问题 + 模型给的全部词（库里没有原词的说法，语义上也能接住）
    sem_expanded = retrieval.semantic_hits(question + " " + " ".join(expansion["llm"])) if semantic and expansion["llm"] else None
    # 扩出的每个词一路（全名单记下，融合只用前 EXPAND_ROUTE_DEPTH 名——排序和以前一样；更深的进候选集尾部）
    expand_full = {term: [it["id"] for _, it in retrieval.rank(items, [term], subword=False)] for term in expansion["terms"]}
    extra = [(ask.EXPAND_WEIGHT, ids[:ask.EXPAND_ROUTE_DEPTH], "expand") for ids in expand_full.values() if ids]
    expanded_sem_ids = retrieval.sem_order(sem_expanded)
    if expanded_sem_ids:
        extra.append((ask.EXPAND_WEIGHT, expanded_sem_ids[:ask.EXPAND_ROUTE_DEPTH]))
    matches, mode, prior_terms = ask.qa_matches(question, items, terms, sem, history, extra=extra, intent=intent)
    lexical_hits = retrieval.rank(items, terms)
    lexical = [it["id"] for _, it in lexical_hits]
    semantic_ids = retrieval.sem_order(sem)
    by_id = {it.get("id"): it for it in items}
    # 归档范围（archive_scope = 这一份 items）之外的 id：语义索引里还留着已删 / 进回收站的篇（索引下次重建才清）。
    # 它们不是「检出了却丢了」，单独记 out_of_scope（有系统理由、可查看），不算进 lost。10-04 真库评测 lost=8 全是这一类。
    out_of_scope = sorted({i for i in semantic_ids + expanded_sem_ids if i not in by_id})
    semantic_ids = [i for i in semantic_ids if i in by_id]
    expanded_sem_ids = [i for i in expanded_sem_ids if i in by_id]
    keyword_ids = []
    if keyword:
        try:
            keyword_ids = [it["id"] for _, _, it in retrieval.keyword_hits(question, items)]
        except Exception:  # noqa: BLE001
            keyword_ids = []
    heads = set(lexical[:POOL_HEADS["lexical"]]) | set(semantic_ids[:POOL_HEADS["semantic"]])
    for route in extra:
        heads |= set(list(dict.fromkeys(route[1]))[:POOL_HEADS["expand"]])
    if mode != "standalone":
        heads |= {it["id"] for it in matches[:POOL_HEADS["followup"]]}
    # 首屏窗口 = 「各路保底名次内」的篇先占位，空位再按融合顺序补「有具体证据」的篇，最多 POOL_MAX（见 _window）：具体证据 = 语义 / 扩词路检出过，或中了一个
    # 不泛的原词（全库不到 GENERIC_DF 的篇有）。以前不够 80 篇就按融合顺序硬补满，「ai」这种全库七成都沾的词把只沾它的尾巴
    # 混进来；现在只沾泛词的尾巴不补（3 篇相关就是 3 篇），它们留在候选集里不丢。
    specific = (None if WINDOW_FILL_GENERIC else
                _specific_ids(items, list(dict.fromkeys(terms + list(prior_terms or []))), matches, heads, sem, extra))
    window = _window(matches, heads, specific)
    shown = {it["id"] for it in window}
    # 二轮扩词（一轮为限）：只补首屏窗口的空位、不改第一轮的排序——反馈词是从结果里猜的，不许压过原问题
    fb_terms, fb_full = [], {}
    if feedback and mode == "standalone" and terms and matches and len(window) < POOL_MAX:
        try:
            fb_terms = feedback_terms(items, matches, terms, expansion["terms"])
        except Exception:  # noqa: BLE001 - 二轮扩词只是锦上添花
            fb_terms = []
        fb_routes = []
        for term in fb_terms:
            fb_full[term] = [it["id"] for _, it in retrieval.rank(items, [term], subword=False)]
            if fb_full[term]:
                fb_routes.append((1, fb_full[term][:POOL_HEADS["feedback"]]))
        # 只提「第一轮已经检出、但排在各路保底名次之外」的长尾篇（原问题也沾上了，又和前几篇共享话题词）；
        # 只沾反馈词的篇不进首屏，只记进候选集
        first_round = {it["id"] for it in matches}
        for _, it in retrieval.fuse(fb_routes, items):
            if len(window) >= POOL_MAX:
                break
            if it["id"] not in shown and it["id"] in first_round:
                window.append(by_id.get(it["id"], it))
                shown.add(it["id"])
    ranked = window + [it for it in matches if it["id"] not in shown]
    routes = {"lexical": lexical, "semantic": semantic_ids, "expansion": expand_full,
              "expanded_semantic": expanded_sem_ids, "feedback": fb_full, "keyword": keyword_ids}
    # 融合只看各路前几名的那些路（扩词 / 反馈词更深的名次、只有关键词筛选命中的篇）：不进排序，但一篇不丢，按路的顺序接在最后
    have = {it["id"] for it in ranked}
    for item_id in _route_order(routes):
        if item_id in by_id and item_id not in have:
            ranked.append(by_id[item_id])
            have.add(item_id)
    result = {"matches": window, "candidates": ranked, "mode": mode, "prior_terms": prior_terms, "terms": terms,
              "sem": ask._merge_sem(sem, sem_expanded), "expansion": expansion, "intent": intent, "feedback": fb_terms,
              "routes": routes, "out_of_scope": out_of_scope,
              "scores": {it["id"]: float(it.get("_fused_score") or 0) for it in matches}}
    for value, it in lexical_hits:  # 没有融合分（纯词法）时用 BM25 分
        result["scores"][it["id"]] = result["scores"].get(it["id"]) or round(value, 4)
    if trace:
        result["stages"] = stages(result, matches)
    return result


GENERIC_DF = 0.4  # 全库四成以上的篇都有的词算泛（同 ask.EXPAND_GENERIC）
# 回退开关：True = 回到 R1 以前「首屏不够 80 篇就按融合顺序补满」（只沾泛词的尾巴也补）。真库带语义复测后再定，见 R1 报告
WINDOW_FILL_GENERIC = False


def _window(matches, heads, specific):
    """首屏窗口：先保各路保底名次内的篇（heads），空位再按融合顺序补「有具体证据」的篇（specific；None = 不论证据都补），
    最后按融合顺序排、最多 POOL_MAX。

    10-04 修：上一版把 heads 和 specific 混在一起按融合顺序截 80——语义续取（不再截前 40）把几十篇语义长尾带进融合，
    分数压过扩词路的保底篇，「AI 记忆层」这类题扩词路前 20 的金标被挤出窗口（31 题池覆盖 0.981 → 0.972）。
    保底名次是窗口的硬承诺，长尾只能补空位。"""
    # 保底本身就超了：按融合顺序取前 POOL_MAX 个保底篇
    keep = set([it["id"] for it in matches if it["id"] in heads][:POOL_MAX])
    for it in matches:
        if len(keep) >= POOL_MAX:
            break
        if it["id"] not in keep and (specific is None or it["id"] in specific):
            keep.add(it["id"])
    return [it for it in matches if it["id"] in keep]


def _specific_ids(items, terms, matches, heads, sem, extra):
    """融合顺序里、保底名次之外的篇，哪些有「具体证据」：语义 / 扩词路检出过，或中了一个不泛的原词。只看前 POOL_MAX 个候选位。"""
    from .retrieval import _documents, has, term_stats, variants
    pending = [it for it in matches if it["id"] not in heads]
    if not pending:
        return set()
    out = set(sem or {})
    for route in extra or []:
        out |= set(route[1])
    limit = len(items) * GENERIC_DF
    narrow = [t for t in terms if 0 < term_stats(items, t)[0] < limit]
    if narrow:
        documents, _ = _documents(items)
        doc_of = {it.get("id"): doc for it, doc in zip(items, documents)}
        groups = [variants(t) for t in narrow]
        for it in pending[:POOL_MAX * 2]:
            doc = doc_of.get(it["id"])
            if doc is None:
                continue
            if any(has(text, v) for vs in groups for v in vs for text in doc.values()):
                out.add(it["id"])
    return out


def _route_order(routes):
    yield from routes.get("lexical") or []
    yield from routes.get("semantic") or []
    for ids in (routes.get("expansion") or {}).values():
        yield from ids
    yield from routes.get("expanded_semantic") or []
    for ids in (routes.get("feedback") or {}).values():
        yield from ids
    yield from routes.get("keyword") or []


def route_ids(routes) -> set:
    """各路检出的全部 id（「检出了」的定义）。"""
    return set(_route_order(routes))


def stages(found, fused=None) -> dict[str, Any]:
    """R0 六层记录的召回半边：每路完整名单 → 融合 → 候选集（全量）→ 首屏窗口；lost = 检出了却不在候选集里的（应恒为空）。"""
    routes = found["routes"]
    ranked = [it["id"] for it in found["candidates"]]
    window = [it["id"] for it in found["matches"]]
    lost = sorted(route_ids(routes) - set(ranked))
    return {
        "lexical": routes["lexical"], "semantic": routes["semantic"],
        "expansion": [{"term": t, "ids": ids} for t, ids in routes["expansion"].items()],
        "expanded_semantic": routes["expanded_semantic"],
        "feedback": [{"term": t, "ids": ids} for t, ids in routes["feedback"].items()],
        "keyword": routes["keyword"],
        "fusion": [it["id"] for it in (fused if fused is not None else found["candidates"])],
        "candidate_set": ranked, "candidate_pool": window, "window": window,
        "beyond_window": len(ranked) - len(window), "lost": lost, "out_of_scope": list(found.get("out_of_scope") or []),
        "intent": found.get("intent"), "mode": found.get("mode"),
    }


def page(found, offset=0, limit=None) -> tuple[list, dict]:
    """分页（四个入口唯一的条数差异来源）：返回 (这一页的篇, {total, offset, returned, next_offset, has_more})。"""
    ranked = found["candidates"]
    offset = max(0, int(offset or 0))
    rows = ranked[offset:] if limit is None else ranked[offset:offset + max(0, int(limit))]
    end = offset + len(rows)
    return rows, {"total": len(ranked), "offset": offset, "returned": len(rows),
                  "next_offset": end if end < len(ranked) else None, "has_more": end < len(ranked)}
