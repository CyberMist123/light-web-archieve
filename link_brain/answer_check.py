"""回答自检（1017 阶段 1，作者：「可检测的回答质量，不是做好就算数」）。纯规则、不调模型、fail-open。

一答生成后对着它引用的来源做六项检查，结果挂在 result["checks"]，要紧的几条在回答末尾标出来给她看：
  alignment  引用对齐：带 [来源N] 的句子，内容词有没有真出现在来源 N 的文本里（没对上 = 可能编了或张冠李戴）
  absence    缺席回查：回答说「没找到 / 没提 / 未披露」的句子，它说的东西是不是其实在引用来源的全文或「其他相关」里
  speaker    说话人：回答里点名的「作者 X」「「X」说」，X 必须是来源作者或评论区里出现过的昵称
  leak       模板泄漏：提示词里的措辞（「机制、触发条件」「本轮输出」…）漏进了回答
  padding    水字数：回答长度远超喂给模型的证据量；或直接答一个引用都没有
  uncited    无引用句比例：陈述句里没带 [来源N] 的占比（「缺口 / 推断 / 收藏之外」段不算）
评测（tests/tools/ask_answer_eval.py R9–R12）和生产在线自检用同一份代码；阈值集中在 THRESHOLDS。
回答和来源都是不可信文本：这里只做字符串比对，不执行任何内容。
"""
from __future__ import annotations

import re
from typing import Any

THRESHOLDS = {
    "align_ratio": 0.5,      # 句子内容词 ≥ 这个比例出现在来源里算对齐
    "align_min_hits": 3,     # 或至少命中这么多个内容词
    "absence_hits": 2,       # 「没有 X」的 X 的内容词在别处出现 ≥ 这么多个算冲突
    "padding_factor": 2.0,   # 回答字数 > 证据字数 × 这个 + 300 算水
    "uncited_ratio": 0.6,    # 陈述句无引用占比超过它提醒
}
CITE_RE = re.compile(r"\[来源\s*(\d+)\]")
ABSENCE_RE = re.compile(r"(?:原文|材料|收藏|来源|帖子|帖里)?(?:里|中)?没(?:有)?(?:找到|提到|提及|披露|写|给出|说明|看到|收录|相关|这方面|出现)"
                        r"|未(?:披露|提及|找到|给出|说明|出现)|不在(?:收藏|材料|来源)|(?:收藏|材料|原文)里没有")
_FUNC = set("的了和与及或在是把被让给对从到为也都就还又着过于之中里")
# 「写没写」「有没有」「能不能」这类正反问不是缺席断言；「如果没有 / 没有的话 / 要是没」是条件句
_NOT_ABSENCE_RE = re.compile(r"(写|有|给|说|提|用|放)没\1|没有的话|如果没|要是没|若没|没有就|没了就")
# 缺席断言里的「属性词」：说的是这个属性没给，不是没提这个东西
ATTR_WORDS = ("克数", "用量", "分量", "数字", "数值", "参数", "规则", "细则", "日期", "时间", "条件", "步骤", "尺寸", "价格", "地址", "名字",
              "定义", "原因", "答复", "回复", "出处", "链接", "数额", "比例", "温度", "时长", "具体做法", "具体", "多少")
COMMON_FREQ = 800   # jieba 词频 ≥ 这个的二字词当常用词（缺席回查不拿它当「她问的那件事」的证据）
# 「关键数字」是回答风格规则里的正常用词（配方类第一行要写关键数字），不算泄漏；下面这些才是只会出现在提示词里的措辞
LEAK_PATTERNS = ("机制、触发条件", "触发条件、步骤", "按机制", "本轮输出", "输出预算", "回答组织", "候选材料",
                 "【原始材料", "原始材料结束", "称呼规则", "输出上限为", "个中文字内", "按上面的")
SKIP_SECTION_RE = re.compile(r"^#{1,6}\s*(?:缺口|推断|收藏之外|延伸|补充说明|说明)")
_NAME_CHARS = r"[^\s，,。；;：:「」“”‘’'\"（）()\[\]、—\-]"
# 只认写得明确的点名：「作者：X」「作者「X」」「评论者“X”」「作者 X 说」；「作者提醒……」这种后面直接接动词的不算人名
NAME_PATTERNS = (
    re.compile(r"(?:作者|评论者)\s*[：:]\s*「?(" + _NAME_CHARS + r"{2,16})」?"),
    re.compile(r"(?:作者|评论者)\s*[「“](" + _NAME_CHARS + r"{2,16})[」”]"),
    re.compile(r"(?:作者|评论者)\s+(" + _NAME_CHARS + r"{2,16})\s*(?:说|认为|表示|提到|回复|建议|指出|补充|称)"),
)
_NAME_SKIP = ("本人", "原帖", "楼主", "评论区", "网友", "有人", "本帖", "原作者", "博主", "回复")
# 内容词里不算数的（太泛，哪篇都有）；缺席回查另按候选池内词频再滤一遍
_STOP = {"没有", "可以", "能够", "需要", "一个", "一种", "一样", "一些", "比较", "非常", "已经", "可能", "因为", "所以", "如果", "但是",
         "而且", "然后", "只是", "就是", "作为", "进行", "使用", "通过", "来源", "原文", "评论", "作者", "帖子", "笔记", "收藏", "材料",
         "回答", "问题", "内容", "用户", "根据", "提到", "说明", "表示", "认为", "这些", "那些", "什么", "怎么", "如何", "哪些", "我们",
         "你们", "他们", "其中", "彼此", "互相", "引用", "重要", "具体", "相关", "信息", "没提", "没写", "给出", "披露", "明确", "直接",
         "建议", "推荐", "方法", "做法", "步骤", "时间", "地方", "东西", "各条", "各种", "部分", "方面", "情况", "细节", "完整", "主要"}


def _tokens(text: str) -> set[str]:
    """内容词：中文用 jieba，≥2 字；英文数字 ≥2；去停用词。"""
    out = set()
    for chunk in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+\-]{1,}|[一-鿿]{2,}", text or ""):
        if re.match(r"[一-鿿]", chunk):
            try:
                import jieba
                cut = jieba.lcut(chunk)
            except Exception:  # noqa: BLE001
                cut = list(chunk)
            parts = [w for w in cut if len(w) >= 2]
            # jieba 切成单字的那一串（「味玉汁」「味醂」这种词典里没有的名词）按二字片段补上，不然专名永远对不上
            run = ""
            for w in cut + [""]:
                if len(w) == 1:
                    run += w
                else:
                    if len(run) >= 2:
                        parts += [run[i:i + 2] for i in range(len(run) - 1) if not set(run[i:i + 2]) & _FUNC]
                    run = ""
            out |= {w for w in parts if w not in _STOP}
        else:
            out.add(chunk.lower())
    return out


def _norm(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def sentences(markdown: str):
    """(句子, 所在小节标题, 是否跳过段) 列表；去掉代码块、图片、表格线。"""
    out, section, skip = [], "", False
    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```") or line.startswith("![[") or line.startswith("![") or re.match(r"^\|?[-\s|]+\|?$", line):
            continue
        if line.startswith("#"):
            section, skip = line, bool(SKIP_SECTION_RE.match(line))
            continue
        line = re.sub(r"^(?:[-*•]|\d+[.、)]|>)\s*", "", line)
        for s in re.split(r"(?<=[。！？!?；;])", line):
            s = s.strip()
            if not s:
                continue
            if re.fullmatch(r"(?:\s*\[来源\s*\d+\]\s*[。.]?)+", s) and out and out[-1][1] == section:
                # 「……。[来源1]」：句号后面才标的引用，归到前一句
                prev = out.pop()
                out.append((prev[0] + s, prev[1], prev[2]))
                continue
            if len(s) >= 6:
                out.append((s, section, skip))
    return out


def source_text(source: dict[str, Any], item: dict[str, Any] | None = None) -> str:
    """来源的可比对文本：喂过模型的摘录 + 标题 +（有对象时）全字段。"""
    parts = [str(source.get("title") or ""), str(source.get("excerpt") or "")]
    parts += [str(e.get("text") or "") for e in (source.get("excerpts") or []) if isinstance(e, dict)]
    if item:
        try:
            from .retrieval import fields
            parts += [str(v) for v in fields(item).values() if v]
        except Exception:  # noqa: BLE001
            pass
    return _norm("\n".join(parts))


def run(markdown: str, sources: list[dict[str, Any]], *, items_by_id: dict[str, Any] | None = None, related=None,
        mode: str = "direct", evidence_chars: int | None = None, must_not_text=()) -> dict[str, Any]:
    """主入口。任何一步出错只影响那一项（记 error），不抛。"""
    checks: dict[str, Any] = {}
    sents = sentences(markdown)
    by_n = {}
    for s in sources or []:
        try:
            by_n[int(s.get("citation"))] = s
        except (TypeError, ValueError):
            continue
    items_by_id = items_by_id or {}
    texts = {n: source_text(s, items_by_id.get(s.get("id"))) for n, s in by_n.items()}
    # 1 引用对齐
    try:
        cited_total, aligned, bad = 0, 0, []
        for s, _sec, skip in sents:
            ns = [int(x) for x in CITE_RE.findall(s)]
            if not ns:
                continue
            cited_total += 1
            toks = _tokens(CITE_RE.sub("", s))
            if not toks:
                aligned += 1
                continue
            best = 0
            for n in ns:
                t = texts.get(n)
                if not t:
                    continue
                hits = sum(1 for w in toks if w in t)
                best = max(best, hits)
            ok = best >= THRESHOLDS["align_min_hits"] or best / len(toks) >= THRESHOLDS["align_ratio"]
            if ok:
                aligned += 1
            else:
                bad.append({"text": s[:100], "cites": ns, "hits": best, "tokens": len(toks)})
        checks["alignment"] = {"cited": cited_total, "aligned": aligned,
                               "rate": round(aligned / cited_total, 3) if cited_total else None, "unaligned": bad[:8]}
    except Exception as exc:  # noqa: BLE001
        checks["alignment"] = {"error": type(exc).__name__}
    # 2 缺席回查
    try:
        pool = [(f"来源{n}《{s.get('title') or ''}》", texts[n]) for n, s in by_n.items()]
        for r in related or []:
            rid = r.get("id")
            pool.append((f"其他相关《{r.get('title') or ''}》", source_text(r, items_by_id.get(rid))))
        conflicts, claims = [], 0

        def together(text, words, window=400):
            # 命中词要在同一段里（≥2 个词落在 window 字内）：几十万字的长文（274 页 PDF）里零散各出现一次不算「它在这篇里」
            spots = []
            for w in words:
                p = text.find(w)
                while p >= 0 and len(spots) < 40:
                    spots.append((p, w))
                    p = text.find(w, p + 1)
            spots.sort()
            for i, (p, w) in enumerate(spots):
                seen = {w}
                for q, w2 in spots[i + 1:]:
                    if q - p > window:
                        break
                    seen.add(w2)
                if len(seen) >= THRESHOLDS["absence_hits"]:
                    return True
            return False

        def specific(word):
            # 常用词（「日期」「价格」「确认」）在哪篇长文里都能撞上，说明不了「她问的那件事在这篇里」：
            # 只认 jieba 词典里不常见的词（词频低）或 ≥3 字的专名；再去掉候选池里一半以上的篇都有的词
            if len(word) < 3:
                try:
                    import jieba
                    jieba.initialize()
                    if int(jieba.dt.FREQ.get(word, 0)) >= COMMON_FREQ:
                        return False
                except Exception:  # noqa: BLE001
                    pass
            if len(pool) < 4:
                return True
            return sum(1 for _l, t in pool if word in t) / len(pool) <= 0.5
        for s, _sec, _skip in sents:
            if not ABSENCE_RE.search(s) or _NOT_ABSENCE_RE.search(s):
                continue
            claims += 1
            toks = {w for w in _tokens(ABSENCE_RE.sub("", CITE_RE.sub("", s))) if specific(w)}
            if len(toks) < 2:
                continue
            # 「没写意面的具体克数」：说的是「属性没给」，不是「没提这个东西」——来源里有「意面」不算冲突，得连「克数」（或数字）一起在
            attrs = [a for a in ATTR_WORDS if a in s]
            for label, t in pool:
                hits = [w for w in toks if w in t]
                if attrs and not (any(a in t for a in attrs) or re.search(r"\d", t)):
                    continue
                if attrs:
                    hits = hits + [a for a in attrs if a in t and a not in hits]
                if len(hits) >= THRESHOLDS["absence_hits"] and len(hits) / len(toks) >= 0.4 and together(t, hits):
                    conflicts.append({"text": s[:100], "where": label, "words": hits[:6],
                                      "tier": "cited" if label.startswith("来源") else "related"})
                    break
        checks["absence"] = {"claims": claims, "conflicts": conflicts[:8]}
    except Exception as exc:  # noqa: BLE001
        checks["absence"] = {"error": type(exc).__name__}
    # 3 说话人
    try:
        known = _norm("\n".join([str(s.get("author") or "") for s in by_n.values()] + list(texts.values())))
        unknown, named = [], 0
        seen_in_sentence = set()
        for s, _sec, _skip in sents:
            seen_in_sentence = set()
            for rx in NAME_PATTERNS:
                for m in rx.finditer(s):
                    name = m.group(1).strip("「」*_ ")
                    if (not name or name.startswith(_NAME_SKIP) or name in seen_in_sentence
                            or re.search(r"认为|表示|建议|提到|说|回复|指出|补充|称", name)):
                        continue
                    seen_in_sentence.add(name)
                    named += 1
                    if _norm(name) not in known:
                        unknown.append({"name": name, "text": s[:80]})
        checks["speaker"] = {"named": named, "unknown": unknown[:8]}
    except Exception as exc:  # noqa: BLE001
        checks["speaker"] = {"error": type(exc).__name__}
    # 4 模板泄漏
    leaks = [p for p in LEAK_PATTERNS if p in (markdown or "")]
    checks["leak"] = {"found": leaks}
    # 5 水字数
    try:
        answer_len = len(re.sub(r"\s", "", markdown or ""))
        ev = evidence_chars if evidence_chars is not None else sum(len(t) for t in texts.values())
        no_cite = mode == "direct" and bool(sources) and not CITE_RE.search(markdown or "")
        padded = ev is not None and answer_len > ev * THRESHOLDS["padding_factor"] + 300
        checks["padding"] = {"answer_chars": answer_len, "evidence_chars": ev, "padded": bool(padded), "no_citation": no_cite}
    except Exception as exc:  # noqa: BLE001
        checks["padding"] = {"error": type(exc).__name__}
    # 6 无引用句比例
    try:
        decl = [s for s, _sec, skip in sents if not skip and len(s) >= 15 and not s.endswith(("？", "?", "："))]
        unc = [s for s in decl if not CITE_RE.search(s)]
        checks["uncited"] = {"sentences": len(decl), "uncited": len(unc),
                             "ratio": round(len(unc) / len(decl), 3) if decl else None}
    except Exception as exc:  # noqa: BLE001
        checks["uncited"] = {"error": type(exc).__name__}
    # 7 题集给的禁词（评测用）
    bad_text = [rx for rx in must_not_text or () if re.search(rx, markdown or "")]
    if must_not_text:
        checks["must_not_text"] = {"hit": bad_text}
    checks["warnings"] = warnings(checks)
    checks["ok"] = not checks["warnings"]
    return checks


def warnings(checks: dict[str, Any]) -> list[str]:
    """要给她看的那几条（短句）。"""
    out = []
    a = checks.get("alignment") or {}
    if a.get("unaligned"):
        out.append(f"{len(a['unaligned'])} 句引用没对上来源原文（如「{a['unaligned'][0]['text'][:40]}…」）")
    b = checks.get("absence") or {}
    # 只把「引用来源里其实有」的说出来（这是真假缺口）；「其他相关」里有的只记在 checks 里（候选没送读是选篇的事，不是编）
    for c in [x for x in (b.get("conflicts") or []) if x.get("tier") == "cited"][:2]:
        out.append(f"说「没有」但 {c['where']} 里出现了：{'、'.join(c['words'][:4])}")
    sp = checks.get("speaker") or {}
    if sp.get("unknown"):
        out.append("点名的说话人不在来源里：" + "、".join(u["name"] for u in sp["unknown"][:3]))
    if (checks.get("leak") or {}).get("found"):
        out.append("回答里漏出了提示词措辞：" + "、".join(checks["leak"]["found"][:3]))
    p = checks.get("padding") or {}
    if p.get("no_citation"):
        out.append("直接答却一个引用都没有")
    elif p.get("padded"):
        out.append(f"回答 {p['answer_chars']} 字远超证据 {p['evidence_chars']} 字，可能有水分")
    if (checks.get("must_not_text") or {}).get("hit"):
        out.append("出现了题目禁止的内容")
    return out


def footnote(checks: dict[str, Any]) -> str:
    """挂在回答末尾的自检行；没问题返回空串。"""
    ws = (checks or {}).get("warnings") or []
    if not ws:
        return ""
    return "\n\n> ⚠ 自检：" + "；".join(ws[:4])
