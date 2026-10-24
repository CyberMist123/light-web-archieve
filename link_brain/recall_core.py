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
    from .deps import require
    from .ask import _FUNC_CHARS, _STOP
    jieba = require("jieba", "问答 / 搜索切词")
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
               llm=None, sem=_UNSET, keyword=True, feedback=True, trace=False, core=None, standalone=None) -> dict[str, Any]:
    """一个问题 → 全量候选集。返回 dict：
    matches = 首屏窗口（≤ POOL_MAX，页面主要依据 + 其他相关从这里切）；candidates = 全量（窗口在前，窗口外的按融合顺序跟后面，
    最后是只有关键词筛选命中的篇）；mode / prior_terms / terms / sem / expansion / intent / feedback；routes = 各路完整名单；
    trace=True 时另给 stages（R0 六层记录）。llm / sem 传了就直接用（问收藏开头已经并行起好了，见 Probe）。
    standalone（1015 第三批 R1）：S1 改写的独立问句。原句照走词法；追问 / 换条件时语义路改 embed 独立问句（省略不再直接进向量），
    switch 时按它换条件检索（qa_matches）。embed 失败 = 用原句那份（fail-open）。"""
    from . import ask, places, retrieval
    terms = ask.query_terms(question)
    if core and str(core).strip() and str(core).strip() != str(question).strip():
        # 1015 S1：去口语壳 / 纠错后的检索核心（「鱼路」→「鱼露」）排在原词前面，原问题剥壳后的词照留（并集，不替换）
        terms = list(dict.fromkeys(ask.query_terms(str(core)) + terms))
    if llm is None or sem is _UNSET:
        probe = Probe(question, history, semantic=semantic and sem is _UNSET,
                      expand=expand and llm is None, allow_expand_call=allow_expand_call)
        llm = llm if llm is not None else probe.llm()
        sem = probe.sem() if sem is _UNSET else sem
    if not semantic:
        sem = None
    if standalone is None:
        standalone = (llm.get("s1") or {}).get("standalone_query") if isinstance(llm, dict) and isinstance(llm.get("s1"), dict) else None
    standalone = " ".join(str(standalone or "").split())[:60]
    from .retrieval import norm as _norm
    sem_source = "question"
    ctx = ((llm.get("intent") or {}).get("context") if isinstance(llm, dict) and isinstance(llm.get("intent"), dict) else None)
    # 只在追问 / 换条件时换：独立新问题的改写会把原话里的专名 / 错字写法（「西尼」）抹掉，真库 32 题两题因此掉了第 1 名
    if standalone and ctx in ("followup", "switch") and _norm(standalone) != _norm(question) and semantic and sem is not None:
        try:
            alt = _semantic(standalone)
        except Exception:  # noqa: BLE001 - 换不了就用原句那份
            alt = None
        if alt:
            sem, sem_source = alt, "standalone"
    expansion = ask.expand_query(question, terms, items, llm=llm)
    intent = llm.get("intent") if isinstance(llm.get("intent"), dict) else None
    s1 = llm.get("s1") if isinstance(llm.get("s1"), dict) else {}
    if s1.get("goal") in {"find", "ask", "survey"}:
        intent = {**(intent or {}), "goal": s1["goal"]}  # qa_matches 用：找回句里的「那个」不当追问
    # 扩词的语义一路：原问题 + 模型给的全部词（库里没有原词的说法，语义上也能接住）
    sem_expanded = retrieval.semantic_hits(question + " " + " ".join(expansion["llm"])) if semantic and expansion["llm"] else None
    # 扩出的每个词一路（全名单记下，融合只用前 EXPAND_ROUTE_DEPTH 名——排序和以前一样；更深的进候选集尾部）
    expand_full = {term: [it["id"] for _, it in retrieval.rank(items, [term], subword=False)] for term in expansion["terms"]}
    extra = [(ask.EXPAND_WEIGHT, ids[:ask.EXPAND_ROUTE_DEPTH], "expand") for ids in expand_full.values() if ids]
    expanded_sem_ids = retrieval.sem_order(sem_expanded)
    if expanded_sem_ids:
        extra.append((ask.EXPAND_WEIGHT, expanded_sem_ids[:ask.EXPAND_ROUTE_DEPTH]))
    # 1015 第三批 R3 地名层级：问「澳洲 / 🇦🇺」时下级地名（悉尼 / 墨尔本 / Chatswood / 新州…）单开一路，只写了城市名的帖也进候选；
    # switch 时按独立问句认地名（「那澳洲的呢」）。融合权重同扩词路，不硬过滤
    place_rows = places.query_places(" ".join([question, standalone or ""]))
    place_ids = places.route(items, place_rows) if place_rows else []
    if place_ids:
        extra.append((ask.EXPAND_WEIGHT, place_ids[:places.ROUTE_DEPTH], "place"))
    matches, mode, prior_terms = ask.qa_matches(question, items, terms, sem, history, extra=extra, intent=intent,
                                                standalone=standalone or None)
    if place_rows:
        try:
            # 上一问的话题词（switch 时的「广州」）不当 facet；只认独立问句里真有的
            sq = _norm(standalone or "")
            facet_terms = list(dict.fromkeys(terms + [t for t in prior_terms or [] if sq and _norm(t) in sq]))
            matches = places.boost(matches, facet_terms, items, rows=place_rows)
        except Exception:  # noqa: BLE001 - 地名加分只是重排，出错 = 原序
            pass
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
    followup_heads = {it["id"] for it in matches[:POOL_HEADS["followup"]]} if mode != "standalone" else set()
    heads |= followup_heads
    sem_all = ask._merge_sem(sem, sem_expanded)
    if WINDOW_GATE:
        # 1020 她：「可能相关」不管相关不相关都凑满 80。各路保底名次只是名次、不看分：语义分挤在 0.40–0.65 一个窄带里，
        # 前 40 名总有几十篇不沾边的；词法前 40 名里只沾一个碎词（「cp」「坏」）的也算。现在只收有证据的篇（见 _evident），
        # 追问继承上一问的篇照留；没证据的留在候选集里不丢。
        evident = _evident(matches, lexical_hits, sem_all, semantic_ids, expand_full, place_ids,
                           coverage=_coverage_fn(items, list(dict.fromkeys(terms + list(prior_terms or []))))) | followup_heads
        window = _window(matches, heads & evident, evident)
    else:
        # 回退：R1 口径（保底名次全进，空位补「语义 / 扩词路检出过或中了不泛原词」的篇）
        specific = (None if WINDOW_FILL_GENERIC else
                    _specific_ids(items, list(dict.fromkeys(terms + list(prior_terms or []))), matches, heads, sem, extra))
        evident = None
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
        if evident is not None:
            # 门槛口径下反馈词只是「佐证」：原问题也得沾上一点（词法相对分 ≥ lex_weak），且最多补 FEEDBACK_ADD_MAX 篇，不再拿它凑数
            top_lex = max((v for v, _ in lexical_hits), default=0) or 1
            touched = {it["id"] for v, it in lexical_hits if v / top_lex >= GATE["lex_weak"]}
            first_round &= touched
        room = POOL_MAX if evident is None else min(POOL_MAX, len(window) + FEEDBACK_ADD_MAX)
        for _, it in retrieval.fuse(fb_routes, items):
            if len(window) >= room:
                break
            if it["id"] not in shown and it["id"] in first_round:
                window.append(by_id.get(it["id"], it))
                shown.add(it["id"])
    ranked = window + [it for it in matches if it["id"] not in shown]
    routes = {"lexical": lexical, "semantic": semantic_ids, "expansion": expand_full,
              "expanded_semantic": expanded_sem_ids, "feedback": fb_full, "keyword": keyword_ids, "place": place_ids}
    # 融合只看各路前几名的那些路（扩词 / 反馈词更深的名次、只有关键词筛选命中的篇）：不进排序，但一篇不丢，按路的顺序接在最后
    have = {it["id"] for it in ranked}
    for item_id in _route_order(routes):
        if item_id in by_id and item_id not in have:
            ranked.append(by_id[item_id])
            have.add(item_id)
    result = {"matches": window, "candidates": ranked, "mode": mode, "prior_terms": prior_terms, "terms": terms,
              "sem": sem_all, "expansion": expansion, "intent": intent, "feedback": fb_terms,
              "routes": routes, "out_of_scope": out_of_scope, "standalone": standalone or None, "sem_source": sem_source,
              "scores": {it["id"]: float(it.get("_fused_score") or 0) for it in matches},
              "lex_scores": {it["id"]: round(float(value), 4) for value, it in lexical_hits[:POOL_MAX * 2]}}
    for value, it in lexical_hits:  # 没有融合分（纯词法）时用 BM25 分
        result["scores"][it["id"]] = result["scores"].get(it["id"]) or round(value, 4)
    if trace:
        result["stages"] = stages(result, matches)
    return result


GENERIC_DF = 0.4  # 全库四成以上的篇都有的词算泛（同 ask.EXPAND_GENERIC）
# 首屏证据门槛（1020，WINDOW_GATE=True）：一篇进首屏要有下面任一条证据，否则只留在候选集里。
# 阈值在真库 53 题回归集（44 题带金标）+ 她 12 个真实提问上离线扫过：金标进首屏 0.951 → 0.939（掉的两篇原排 38 / 59 名），
# 首屏中位数 80 → 17。
#   lex_rel       原词 BM25 分 ≥ 第一名的这个比例（只沾一个碎词 / 单字的长尾分很低）；而且要么覆盖查询词 idf 权重的
#                 lex_cover 以上，要么 BM25 ≥ 第一名的 lex_strong（「中国旅行推荐」里只在标题沾「中国」的篇 BM25 不低，靠覆盖率拦）
#   expand_depth  某个扩词一路的前几名（扩词是小模型按问题给的说法，整词匹配，不拆单字）
#   sem_gap       语义分离第一名不超过这么多，且 ≥ sem_abs；只有语义一路沾上的要更近（sem_only_gap / sem_only_abs）
#   sem_top_n     语义前几名不论分数都进（库里没有原词的说法靠它接住）
#   agree_gap     原词沾上一点（≥ lex_weak）+ 语义离第一名不超过这么多 = 两路都弱但互相印证
GATE = {"lex_rel": .25, "lex_cover": .4, "lex_strong": .5, "lex_weak": .05, "expand_depth": 20, "sem_abs": .45, "sem_gap": .06,
        "sem_only_abs": .55, "sem_only_gap": .04, "sem_top_n": 3, "agree_gap": .08}
FEEDBACK_ADD_MAX = 10  # 门槛口径下二轮反馈词最多往首屏补几篇
WINDOW_GATE = True     # 回退开关：False = 回到 R1 的保底名次口径
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


def _coverage_fn(items, terms):
    """id → 这篇覆盖了查询词 idf 权重的几成（0–1）。只认原词和同义词（同 term_stats），不算拼音、错字。"""
    import math
    from .retrieval import _documents, has, term_stats, variants
    terms = [t for t in terms if str(t).strip()]
    if len(terms) <= 1:
        return lambda item_id: 1.0
    documents, _ = _documents(items)
    doc_of = {it.get("id"): doc for it, doc in zip(items, documents)}
    n = len(items)
    idf = {t: math.log((n + 1) / (term_stats(items, t)[0] + .5)) for t in terms}
    total = sum(idf.values()) or 1
    groups = {t: variants(t) for t in terms}

    def cover(item_id):
        doc = doc_of.get(item_id) or {}
        return sum(idf[t] for t, vs in groups.items() if any(has(text, v) for v in vs for text in doc.values())) / total
    return cover


def _evident(matches, lexical_hits, sem_scores, sem_ids, expand_full, place_ids, gate=None, coverage=None):
    """融合顺序里哪些篇有「进首屏」的证据（规则见 GATE）。纯本地、不调模型。coverage = _coverage_fn 的结果（None = 不看覆盖率）。"""
    g = {**GATE, **(gate or {})}
    top_lex = max((v for v, _ in lexical_hits), default=0) or 1
    lex_rel = {it["id"]: v / top_lex for v, it in lexical_hits}
    scores = {k: float((v or {}).get("score") or 0) for k, v in (sem_scores or {}).items()}
    sem_top = max(scores.values(), default=0)
    sem_rank = {i: n for n, i in enumerate(sem_ids or [], 1)}
    expand_near, expand_any = set(), set()
    for ids in (expand_full or {}).values():
        expand_near |= set(ids[:g["expand_depth"]])
        expand_any |= set(ids)
    places = set(place_ids or [])
    out = set()
    for it in matches:
        i = it["id"]
        lr = lex_rel.get(i)
        lex_ok = (lr is not None and lr >= g["lex_rel"]
                  and (coverage is None or lr >= g["lex_strong"] or coverage(i) >= g["lex_cover"]))
        if lex_ok or i in expand_near or i in places:
            out.add(i)
            continue
        if sem_rank.get(i, 10 ** 9) <= g["sem_top_n"]:
            out.add(i)
            continue
        s = scores.get(i)
        if s is None:
            continue
        if lr is not None or i in expand_any:
            if s >= max(g["sem_abs"], sem_top - g["sem_gap"]) or (lr is not None and lr >= g["lex_weak"] and s >= sem_top - g["agree_gap"]):
                out.add(i)
        elif s >= max(g["sem_only_abs"], sem_top - g["sem_only_gap"]):
            out.add(i)
    return out


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
    yield from routes.get("place") or []


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
