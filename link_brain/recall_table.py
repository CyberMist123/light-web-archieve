"""召回表模式（1017 阶段 1 的第一个交付物，设计见作者 workdesk「问收藏流程设计 v1」§v1.1-d）。

只做到「选材」为止、不作答：一问进来，走和生产 `_answer_qa` **同一条**前半段（S1 理解 → apply_filters → recall → core_first →
rerank / lead_by_dominance → select_primary → decide_mode），把首屏窗口里每篇候选摆成一张表——它从哪几路检出、命中了哪个字段的哪段原文、
生产现在会把它放进「主要依据」还是「其他相关」、档位会不会出目录——再让作答模型逐篇判「深读 / 待定 / 剔除」并给一句理由。
目的：先把「召回准不准、挑得对不对」看清楚（评测的理解层 + 召回层），作答质量另议。

模型输出一律当不可信数据：只认「编号|判定|理由」这一种行，判定词不在词表里的按「待定」记，多余的话全丢。
不写收藏库：这里只读 items / 索引；评测脚本 tests/tools/recall_table.py 再套一层写保护。
"""
from __future__ import annotations

import re
from typing import Any

VERDICTS = ("deep_read", "tentative", "reject")
VERDICT_LABEL = {"deep_read": "深读", "tentative": "待定", "reject": "剔除"}
JUDGE_CAP = 40      # 最多给判定模型看多少篇（首屏窗口 ≤ 80，再多它看不过来）
HIT_CHARS = 200     # 每处命中给模型 / 表格看的原文长度

JUDGE_INSTRUCTION = (
    "你在帮一个人从她自己的收藏库里挑材料。下面是她的问题、系统对问题的理解，以及按相关度排好的候选篇（每篇：标题、作者、"
    "类型、概要、命中的原文片段和出自哪个字段）。请逐篇判断这篇对回答这个问题有没有用：\n"
    "- deep_read：这篇的内容能直接用来回答（她问做法就是做法、问推荐它就是一个可推荐的候选、问比较它就是比较的一方），值得整篇读；\n"
    "- tentative：可能有用但只沾边（比如只有一处顺带提到、或只是同类但不对题）；\n"
    "- reject：无关，或只是评论区偶然出现了同一个词，或是什么都沾一点的长文目录。\n"
    "原则：按内容判，不按「是不是唯一答案」判——推荐 / 盘点 / 比较类问题通常有多篇 deep_read；找回某一篇的问题只有最像的那一两篇 deep_read。"
    "不要为了凑数把无关的标成 deep_read；一篇也不相关就全部 reject。理由一句话、说清依据（引用命中片段里的具体内容）。\n"
    "只输出候选行，每篇一行，格式严格为：编号|判定|理由。不要输出别的。"
)


def gather(question: str, items: list[dict[str, Any]], settings: dict[str, Any], history=None, *, probe=None) -> dict[str, Any]:
    """问题 → 候选表（不调判定模型）。前半段的调用顺序和参数照抄 ask._answer_qa，改那边要同步改这里（评测必须测生产那条路）。"""
    from . import ask, recall_core
    from .ask_intent import apply_filters
    from .recall_core import POOL_MAX

    history = [m for m in (history or [])[-8:] if isinstance(m, dict) and m.get("role") in {"user", "assistant"}]
    if probe is None:
        probe = recall_core.Probe(question, history)
    skills_list = ask._skills_list()
    understood = ask.understand_question(question, items, probe.llm(), skills_list)
    scope_items, used_filters = apply_filters(items, understood.get("filters"))
    found = ask.recall(question, scope_items, settings, history, probe=probe, core=understood.get("core"),
                       standalone=understood.get("standalone_query"))
    found_mode = found.get("mode") or "standalone"
    pool = list(found["matches"][:POOL_MAX])
    if found_mode == "standalone":
        try:
            pool = ask.core_first(pool, understood, items)
        except Exception:  # noqa: BLE001 - 同生产：重排失败 = 原序
            pass
    rr_scores = None
    try:
        pool, rr_scores = ask.rerank_pool(question, pool, settings, {})
    except Exception:  # noqa: BLE001
        rr_scores = None
    if rr_scores is None:
        try:
            pool = ask.lead_by_dominance(pool, found.get("lex_scores"), found.get("sem"))
        except Exception:  # noqa: BLE001
            pass
    notes_pool = [it for it in pool if it.get("source_kind") != "saved"]
    try:
        n, select_reason = ask.select_primary(question, notes_pool, understood, items, scores=rr_scores, inherited=[],
                                              lex=found.get("lex_scores"), sem=found.get("sem"))
    except Exception as exc:  # noqa: BLE001
        n, select_reason = 0, f"error:{type(exc).__name__}"
    deep = select_reason in ("named", "inherited")
    try:
        mode, info = ask.decide_mode(understood, notes_pool, items, deep=deep, expansion_terms=found["expansion"]["terms"],
                                     used_filters=used_filters)
    except Exception:  # noqa: BLE001
        mode, info = "direct", {}
    core = list(ask.core_words(understood, items) or [])
    terms_all = list(dict.fromkeys(core + list(found["terms"]) + list(found["expansion"]["terms"])))
    routes = found.get("routes") or {}
    strong_ids = {it.get("id") for it in (info.get("strong_items") or [])}
    rows = rows_for(notes_pool, terms_all, found.get("sem"), routes=routes, scores=found.get("scores") or {})
    for row in rows:
        row["production"] = "primary" if row["rank"] <= n else "related"   # 规则选篇的结果；judge_select 之后按模型判定改写
        row["rule_production"] = row["production"]
        row["strong"] = row["id"] in strong_ids
    return {
        "question": question,
        "understanding": ask._public_understanding(understood, used_filters),
        "core_words": core, "terms": list(found["terms"]), "expansion": list(found["expansion"]["terms"]),
        "terms_all": terms_all, "sem": found.get("sem"), "understood": understood,
        "found_mode": found_mode, "filters_used": list(used_filters),
        "candidates_total": len(found.get("candidates") or []), "window": len(found["matches"]),
        "production": {"mode": mode, "mode_reason": info.get("reason"), "primary_n": n, "rule_n": n,
                       "select_reason": select_reason, "strong": info.get("strong")},
        "rows": rows,
    }


def rows_for(pool, terms_all, sem, *, routes=None, scores=None) -> list[dict[str, Any]]:
    """候选 → 表行（给模型看、给人看都是这一份）。"""
    from . import ask
    rows = []
    for rank, it in enumerate(pool, 1):
        try:
            hits = ask.search_hits(it, terms_all, sem, limit=2, chars=HIT_CHARS)
        except Exception:  # noqa: BLE001 - 命中段只是给人看的
            hits = []
        if not hits:   # search_hits 要反查对象目录挂楼号 / 图号，对象文件不在（合成库 / 评测副本）时退回纯词法摘录
            try:
                from .retrieval import lexical_excerpt
                ex = lexical_excerpt(it, terms_all, HIT_CHARS)
                if ex.get("field"):
                    hits = [{"type": ex["field"], "label": ask.HIT_TYPES.get(ex["field"], ex["field"]),
                             "text": " ".join(str(ex["text"]).split())}]
            except Exception:  # noqa: BLE001
                hits = []
        rows.append({
            "rank": rank, "id": it.get("id"), "title": it.get("title") or "未命名", "author": it.get("author") or "",
            "kind": it.get("kind") or "", "date": it.get("date") or "",
            "summary": " ".join(str(it.get("summary") or "").split()),
            "hits": hits, "routes": _route_tags(routes or {}, it.get("id")),
            "score": (scores or {}).get(it.get("id")),
        })
    return rows


def judge_select(question, pool, understood, items, settings, *, terms=(), sem=None, cap: int = JUDGE_CAP) -> dict[str, Any] | None:
    """生产选篇（1017 阶段 1 S3）：让作答模型看候选逐篇判，deep_read 的排前、全部送读（≤ ask.SELECT_HARD_MAX）。
    返回 {pool: 重排后的候选, n, deep, tentative, reject, judged, verdicts: {id: (判定, 理由)}}；模型没配 / 失败 / 一篇没判 = None（退回规则）。"""
    from . import ask
    if not pool:
        return None
    core = list(ask.core_words(understood, items) or [])
    terms_all = list(dict.fromkeys(core + list(terms or ())))
    rows = rows_for(pool, terms_all, sem)
    result = {"question": question, "understanding": ask._public_understanding(understood, []), "core_words": core, "rows": rows}
    info = judge(result, settings, cap)
    if info.get("status") != "ok" or not info.get("judged"):
        return None
    verdicts = {r["id"]: (r.get("verdict") or "", r.get("reason") or "") for r in rows}
    deep = [r["id"] for r in rows if r.get("verdict") == "deep_read"]
    tent = [r["id"] for r in rows if r.get("verdict") == "tentative"]
    rej = [r["id"] for r in rows if r.get("verdict") == "reject"]
    by_id = {it["id"]: it for it in pool}
    taken = set(deep) | set(tent)
    ordered = [by_id[i] for i in deep] + [by_id[i] for i in tent] + [it for it in pool if it["id"] not in taken]
    n = select_count(len(deep), len(tent))
    return {"pool": ordered, "n": n, "deep": len(deep), "tentative": len(tent), "reject": len(rej),
            "judged": info.get("judged", 0), "verdicts": verdicts, "rows": rows}


def select_count(deep: int, tentative: int) -> int:
    """送读几篇：deep_read 全送（≤ SELECT_HARD_MAX）；deep 不到 2 篇时补最多 2 篇 tentative（作答模型自己核对），
    一篇 deep 都没有但有沾边的就送沾边的前 2 篇；全是 reject = 0（调用方退回规则 / 说没有）。"""
    from . import ask
    if deep >= 2:
        return min(deep, ask.SELECT_HARD_MAX)
    return min(deep + min(tentative, 2), ask.SELECT_HARD_MAX)


def apply_judge(result: dict[str, Any], settings: dict[str, Any], cap: int = JUDGE_CAP) -> dict[str, Any]:
    """召回表评测用：对 gather() 的结果跑 judge_select（和生产同一个函数），把判定、模型选篇写回 rows / production。"""
    from . import ask
    rows = result["rows"]
    # judge_select 要原条目算命中段；这里 rows 已经带 hits，直接复用：构造最小条目并用已有 hits
    sub = {"question": result["question"], "understanding": result.get("understanding") or {},
           "core_words": result.get("core_words") or [], "rows": rows[:cap]}
    info = judge(sub, settings, cap)
    result["judge"] = info
    if info.get("status") != "ok" or not info.get("judged"):
        return info
    deep = [r for r in rows if r.get("verdict") == "deep_read"]
    tent = [r for r in rows if r.get("verdict") == "tentative"]
    n = select_count(len(deep), len(tent))
    chosen = {r["id"] for r in (deep + tent)[:n]}
    for r in rows:
        r["production"] = "primary" if r["id"] in chosen else "related"
    result["production"]["primary_n"] = n
    result["production"]["select_reason"] = f"judge:{len(deep)}/{info.get('judged')}"
    return info


def _route_tags(routes: dict[str, Any], item_id) -> list[str]:
    tags = []
    for name, label in (("lexical", "原词"), ("semantic", "语义"), ("keyword", "关键词"), ("place", "地名"),
                        ("expanded_semantic", "扩词语义")):
        ids = routes.get(name) or []
        if item_id in ids:
            tags.append(f"{label}#{ids.index(item_id) + 1}")
    for term, ids in (routes.get("expansion") or {}).items():
        if item_id in ids:
            tags.append(f"扩词「{term}」#{ids.index(item_id) + 1}")
    return tags


def judge_text(result: dict[str, Any], cap: int = JUDGE_CAP) -> str:
    """给判定模型看的材料（纯文本，不含任何可执行指令）。"""
    u = result.get("understanding") or {}
    lines = [f"问题：{result['question']}",
             f"系统理解：目标={u.get('goal') or ''}；核心={u.get('core') or ''}；核心词={'、'.join(result.get('core_words') or []) or '无'}",
             "", "候选："]
    for row in result["rows"][:cap]:
        hits = "；".join(f"[{h.get('label') or h.get('type')}{('·' + h['loc']) if h.get('loc') else ''}]「{(h.get('text') or '')[:HIT_CHARS]}」"
                        for h in row["hits"]) or "（无字面命中，靠语义 / 扩词进来）"
        lines.append(f"{row['rank']}. 《{row['title']}》 作者 {row['author'] or '未知'} · {row['kind'] or '图文'}\n"
                     f"   概要：{row['summary'][:160] or '无'}\n   命中：{hits}")
    return "\n".join(lines)


_LINE = re.compile(r"^\s*(\d{1,3})\s*[|｜]\s*([A-Za-z_]+|深读|待定|剔除)\s*[|｜]\s*(.*?)\s*$")
_ALIAS = {"深读": "deep_read", "待定": "tentative", "剔除": "reject", "deepread": "deep_read", "read": "deep_read",
          "keep": "deep_read", "maybe": "tentative", "drop": "reject", "rejected": "reject"}


def parse_verdicts(text: str) -> dict[int, tuple[str, str]]:
    """「编号|判定|理由」→ {编号: (判定, 理由)}。认不出的行丢掉；判定词不认识的记 tentative。"""
    out: dict[int, tuple[str, str]] = {}
    for line in str(text or "").splitlines():
        m = _LINE.match(line.strip().strip("`"))
        if not m:
            continue
        n = int(m.group(1))
        word = m.group(2).strip().lower()
        verdict = word if word in VERDICTS else _ALIAS.get(word, _ALIAS.get(m.group(2).strip(), "tentative"))
        out[n] = (verdict, " ".join(m.group(3).split())[:200])
    return out


def judge(result: dict[str, Any], settings: dict[str, Any], cap: int = JUDGE_CAP) -> dict[str, Any]:
    """调作答模型逐篇判定，结果写回 rows[*].verdict / reason；返回 {status, error?, judged}。没配模型 = skipped，表照出。"""
    from . import ask
    rows = result["rows"][:cap]
    if not rows:
        result["judge"] = {"status": "skipped", "judged": 0, "error": "没有候选"}
        return result["judge"]
    # 1020 她：回答前冒出一堆「1|deep_read|…」——判定是内部一步，别把它的输出流到回答区（同 _select_sources）
    token = ask._ON_DELTA.set(None)
    try:
        res = ask.call_text(JUDGE_INSTRUCTION, judge_text(result, cap), settings) or {}
    finally:
        ask._ON_DELTA.reset(token)
    status = res.get("status") or "failed"
    verdicts = parse_verdicts(res.get("text") or "") if status == "ok" else {}
    for row in rows:
        v = verdicts.get(row["rank"])
        row["verdict"], row["reason"] = (v if v else ("", ""))
    result["judge"] = {"status": status if verdicts or status != "ok" else "failed", "judged": len(verdicts),
                       "error": res.get("error") or ("模型没按格式输出" if status == "ok" and not verdicts else None)}
    return result["judge"]


def markdown(result: dict[str, Any], cap: int = JUDGE_CAP) -> str:
    """给人看的召回表。"""
    p = result.get("production") or {}
    u = result.get("understanding") or {}
    head = [f"# 召回表：{result['question']}", "",
            f"- 理解：目标 {u.get('goal') or '-'} · 核心「{u.get('core') or ''}」 · 核心词 {'、'.join(result.get('core_words') or []) or '无'}"
            + (f" · 过滤 {'、'.join(result['filters_used'])}" if result.get("filters_used") else "")
            + (f" · 追问模式 {result['found_mode']}" if result.get("found_mode") != "standalone" else ""),
            f"- 扩词：{'、'.join(result.get('expansion') or []) or '无'}",
            f"- 候选：全量 {result.get('candidates_total')} 篇，首屏窗口 {result.get('window')} 篇，下表列前 {min(cap, len(result['rows']))} 篇",
            f"- 生产现在会：档位 **{p.get('mode')}**（{p.get('mode_reason')}），送读 **{p.get('primary_n')}** 篇（{p.get('select_reason')}），真命中 {p.get('strong')}",
            ]
    j = result.get("judge")
    if j:
        head.append(f"- 模型判定：{j.get('status')}，判了 {j.get('judged')} 篇" + (f"（{j['error']}）" if j.get("error") else ""))
    head += ["", "| # | 判定 | 生产 | 篇 | 检出路 | 命中 | 理由 |", "|---|---|---|---|---|---|---|"]
    body = []
    for row in result["rows"][:cap]:
        hits = "<br>".join(f"{h.get('label') or h.get('type')}{('·' + h['loc']) if h.get('loc') else ''}：「{_cell((h.get('text') or '')[:90])}」"
                           for h in row["hits"]) or "（语义 / 扩词）"
        verdict = VERDICT_LABEL.get(row.get("verdict") or "", row.get("verdict") or "—")
        prod = "主要依据" if row["production"] == "primary" else "其他相关"
        title = f"**{_cell(row['title'])}**" + (f"<br>{_cell(row['author'])} · {row['kind']}" if row["author"] else "")
        body.append(f"| {row['rank']} | {verdict} | {prod} | {title} | {_cell('、'.join(row['routes']) or '-')} | {hits} | {_cell(row.get('reason') or '')} |")
    return "\n".join(head + body) + "\n"


def _cell(text: str) -> str:
    return " ".join(str(text or "").replace("|", "｜").split())
