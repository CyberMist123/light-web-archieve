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
WEIGHTS = {"title": 12, "tags": 10, "cats": 3, "body": 7, "attachments": 6, "transcript": 6, "ocr": 5, "comments": 3, "summary": 2, "author": 1}


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
            "cats": " ".join(item.get("cats") or []),
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


_RANK_CACHE = (None, None)


def rank(items, terms):
    """BM25 字段加权；同分保持稳定 ID 顺序，不按日期偏向新收藏。"""
    import math
    global _RANK_CACHE
    if not terms:
        return []
    if _RANK_CACHE[0] is not items:
        documents = [{k: norm(v) for k, v in fields(it).items()} for it in items]
        averages = {k:sum(len(doc.get(k,'')) for doc in documents)/max(1,len(documents)) or 1 for k in WEIGHTS}
        _RANK_CACHE = (items, (documents, averages))
    documents, averages = _RANK_CACHE[1]
    totals = [0.0] * len(items)
    covered = [0] * len(items)
    for term in terms:
        vs = variants(term)
        counts=[]
        for doc in documents:
            best=0
            for v in vs:
                value=0
                for k,text in doc.items():
                    tf=text.count(v)
                    if tf:
                        # Saturate within each field: a long attachment must not erase a title hit.
                        length=min(len(text)/averages.get(k,1),3)
                        value+=WEIGHTS.get(k,1)*tf*2.2/(tf+1.2*(.25+.75*length))
                best=max(best,value*(1 if v==term else .75))
            counts.append(best)
        df = sum(tf>0 for tf in counts)
        if not df:
            continue
        idf = math.log(1 + (len(items)-df+.5)/(df+.5))
        for i, tf in enumerate(counts):
            if tf:
                covered[i] += 1
                totals[i] += idf * tf
    # ★（磁吸）是显式信号：轻微上浮，别盖过内容相关性
    hits = [(value * (1 + .15 * covered[i]) * (1.15 if it.get('starred') else 1), it)
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


def _rrf(lexical_hits, sem, items, k=60):
    """词法 BM25 排名 × 语义 chunk 排名的 RRF 混排；语义可引入词法零分的 item。"""
    lex_rank = {it['id']: r for r, (_, it) in enumerate(lexical_hits, 1)}
    sem_order = sorted(sem.items(), key=lambda kv: -kv[1]['score'])
    sem_rank = {item_id: r for r, (item_id, _) in enumerate(sem_order, 1)}
    by_id = {it.get('id'): it for it in items}
    fused = []
    for item_id in dict.fromkeys(list(lex_rank) + list(sem_rank)):
        it = by_id.get(item_id)
        if it is None:
            continue
        value = (1 / (k + lex_rank[item_id]) if item_id in lex_rank else 0) \
              + (1 / (k + sem_rank[item_id]) if item_id in sem_rank else 0)
        fused.append((value, it))
    fused.sort(key=lambda x: (-x[0], str(x[1].get('id', ''))))
    return fused


def rank_query(items, question, terms=None):
    """Keep distinct clauses represented when a request contains several topics."""
    from .ask import query_terms
    terms=terms if terms is not None else query_terms(question)
    hits=rank(items,terms)
    sem=semantic_hits(question)
    if sem:
        hits=_rrf(hits,sem,items)
    clauses=query_facets(items,question)
    if len(clauses)<2:return hits
    chosen=[];seen=set()
    for _,candidates in clauses:
        value,it=candidates[0]
        if it['id'] not in seen:chosen.append((value,it));seen.add(it['id'])
    return chosen+[(s,it) for s,it in hits if it['id'] not in seen]


def excerpts(item, terms, limit=800, window_chars=450):
    """取命中密度最高的最多三段原文，跨正文/附件/转写，严格共享字数上限。"""
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
            if any(v in h for group in groups for v in group):
                starts[heading.start()] = 3
        for start, heading_bonus in starts.items():
            window = text[start:start+width]
            normalized = norm(window)
            counts = [max((normalized.count(v) for v in group), default=0) for group in groups]
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
    if not selected:
        fs=fields(item)
        key=next((k for k in ['body','ocr','attachments','transcript'] if len(str(fs.get(k,'')))>80),'body')
        text=str(fs.get(key) or item.get('search_text') or item.get('summary') or '')
        if len(text)>limit:
            half=limit//2;selected=[(key,0,text[:half]),(key,len(text)-(limit-half),text[-(limit-half):])]
        else:selected=[(key,0,text)]
    return [{'field':key,'text':text} for key,_,text in selected]


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
        results.append({"item_id": it["id"], "title": it["title"], "score": s, "starred": bool(it.get("starred")),
                        "excerpts": excerpts(it, terms, 700), "url": it.get("url"),
                        "visible_note": str(storage.vault_root() / it["note"]) if it.get("note") else None,
                        "agent_md": str(storage.vault_root() / it["agent_md"]) if it.get("agent_md") else None,
                        "attachments": it.get("attachment_files", []), "tags": it.get("tags", []),
                        "summary": it.get("summary", ""), "first_archived": it.get("date", "")})
    return {"status": "ok", "query": query, "total": len(hits), "results": results, "found": len(results), "items": [{k: row[k] for k in ("item_id", "title", "summary", "tags", "url", "first_archived")} for row in results]}


def retrieve_payload(question, top_k=8):
    """与问答共享 BM25 和摘录；给 Fable 返回材料，不调用模型。"""
    import os
    from urllib.parse import quote
    from .ask import load_items, query_terms
    terms=query_terms(question)
    hits=rank_query(load_items(),question,terms)
    sem=semantic_hits(question) or {}
    count=max(1,min(20,top_k))
    budget=max(100,2500//min(count,len(hits) or 1))
    results=[]
    for value,it in hits[:count]:
        note=it.get('note') or ''
        parts=excerpts(it,terms,budget)
        chunks=[c for c in (sem.get(it['id']) or {}).get('chunks') or [] if c.get('field')!='meta']
        if chunks:
            # 命中 chunk 的原文优先充当证据，词法窗口补足预算
            evidence=[];used=0
            for part in chunks+parts:
                if used>=budget or len(evidence)==3:break
                text=str(part['text'])[:budget-used]
                if not text or any(text[:60] in e['text'] or e['text'][:60] in text for e in evidence):
                    continue
                evidence.append({'field':part['field'],'text':text});used+=len(text)
            parts=evidence or parts
        results.append({'item_id':it['id'],'title':it['title'],'score':round(value,3),
            'excerpts':parts,'note':note,
            'obsidian_url':'obsidian://open?vault='+quote(os.environ.get('LINK_BRAIN_OBSIDIAN_VAULT','vault'))+'&file='+quote(note),
            'web_url':os.environ.get('LINK_BRAIN_WEB_URL','https://lwa.ler428.xyz').rstrip('/')+'/'+quote(note),
            'source_url':it.get('url'),'has_attachments':bool(it.get('attachment_files')),
            'has_transcript':bool((it.get('search_fields') or {}).get('transcript')),
            'starred':bool(it.get('starred')),'starred_at':it.get('starred_at')})
    return {'status':'ok','query':question,'total':len(hits),'results':results,'model_called':False}
