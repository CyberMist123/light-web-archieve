"""问收藏 S0 / S1：理解问题（1015 第二批 ask 车）。

S0 规则层（零 token，模型挂了也生效）：
- strip_shell：剥口语壳（「我有个 X 忘了哪儿了 帮我找一下」→「X」；「之前存的那个 X」→「X」）。只影响原词路，语义路照吃整句。
- rule_filters：作者（库里真有的昵称出现在问句里 / @昵称）、收藏时间（2024 年 / 去年 / 今年 / 上个月 / 最近 N 天）、
  文件类型（视频 / PDF / 附件 / 图片）、显式技能（「/菜谱」「用 wiki」）。
- heuristic_goal：find（找回某篇）/ ask（问一个事实）/ survey（盘点 / 推荐 / 某作者发过哪些）。

S1 模型层：扩词那一次小模型调用顺带吐的结构化理解（ask._EXPAND_INSTRUCTION），parse_s1 只认合法值：
goal / depth / core / entities / relations / constraints(must / prefer) / negation / filters / facets / skills。
模型输出不可信：枚举外的值丢；core 必须和原问题字面重合过半（防漂移）；作者过滤必须是库里真有的昵称；
技能只认给定列表里的 id。缺字段 = 没给（调用方退回 S0 / 旧启发式，fail-open）。

规则 > 模型：同一维度 S0 认出了就用 S0 的（她明说的作者 / 年份比模型猜的可靠）。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

# --------------------------------------------------------------------------
# S0：口语壳
# --------------------------------------------------------------------------

# 借 TREC Tip-of-the-Tongue 的「自我叙述 / 不确定性」类：这些词只说明她在找，不是要找的东西本身
_SHELL = re.compile(
    r"我(?:好像|记得|记着)?有(?:个|一个|篇|一篇)|我记得|好像|似乎|应该是|"
    r"(?:我)?之前(?:存|收藏|保存|看|刷)(?:过|到)?的?|我(?:存|收藏|保存)(?:过|了)?的?|"
    r"(?:那个|那篇|这个|这篇|那条|那家)|"
    r"忘(?:了|记)(?:在)?(?:哪儿|哪里|哪)?(?:了)?|想不起来?(?:了)?|找不到了?|"
    r"帮我找(?:一下|找)?|帮我|找一下|在哪(?:儿|里)?|收藏里(?:的)?|我的收藏(?:里)?|"
    r"是哪篇|是哪个|叫(?:啥|什么)(?:来着|名字)?|来着|一下|"
    r"(?:的(?:帖子|笔记)|帖子)(?=$|[\s，,。？?])")
_SPACE = re.compile(r"\s+")


def strip_shell(question: str) -> str:
    """去掉口语壳后剩下的检索核心；剥空了就原样返回（别把整问剥没了）。"""
    q = str(question or "")
    out = _SPACE.sub(" ", _SHELL.sub(" ", q)).strip(" ，,。.!！?？~～、")
    return out if re.search(r"[\w一-鿿]", out) else q.strip()


# 真正的「接着上一问」标记：「那个 / 这个」不算（「之前存的那个火锅粉」是新话题，0915 BENCH 同类事故）
STRONG_FOLLOWUP = re.compile(r"第[一二三四五六七八九十两\d]+(?:个|篇|条|项|种|家|步|点)?|上面|上文|刚才|前面|"
                             r"详细|具体说|展开|继续|多说|再说|它们|^它|他们|她们|这些|那些|还要|还需要|还有什么")

# --------------------------------------------------------------------------
# S0：目的
# --------------------------------------------------------------------------

_FIND_RE = re.compile(r"忘了|想不起|之前(?:存|收藏|保存|看)|我(?:存|收藏)(?:过|的)|找不到|^有(?:个|一个|篇)|是哪篇|是哪个|叫啥|叫什么来着|"
                      r"有(?:个|一个|篇)[^，。？?]{0,20}(?:找|在哪|哪儿)|那(?:篇|个)(?:讲|说|教|写)|写的.{0,12}那篇|那篇")
_SURVEY_RE = re.compile(r"有哪些|有什么(?!区别|不同)|推荐|盘点|汇总|总结一下|全部|都有|清单|列一下|列出|发过哪些|发过什么|"
                        r"哪些|几种|各种|攻略合集|大全")


# 要一张清单的问法（买 / 备 / 带什么）：规则认出就算盘点，比模型的 goal 可靠（F23「澳洲做越南菜要买啥 在哪买」模型给 ask）
_LIST_RE = re.compile(r"(?:要|该|得)?(?:买|备|准备|带)(?:些)?(?:啥|什么|哪些)(?:东西|材料|食材)?")


def heuristic_goal(question: str) -> str:
    q = str(question or "")
    if _SURVEY_RE.search(q) or _LIST_RE.search(q):
        return "survey"
    if _FIND_RE.search(q):
        return "find"
    return "ask"


# --------------------------------------------------------------------------
# S0：元数据过滤
# --------------------------------------------------------------------------

KINDS = ("video", "attachment", "pdf", "image")
_KIND_RE = [
    ("pdf", re.compile(r"pdf|PDF|Pdf")),
    ("attachment", re.compile(r"附件|文件|文档|电子书|资料包|\d+\s*页")),
    ("video", re.compile(r"视频|vlog|录屏")),
]


def _today() -> date:
    return date.today()


def _time_filter(q: str, today: date | None = None) -> tuple[str | None, str | None]:
    today = today or _today()
    m = re.search(r"(20\d\d)\s*年(?:(\d{1,2})\s*月)?", q)
    # 只认「2024 年存的 / 收藏的」：「2024 年签证政策」的年份是内容，不是收藏时间
    if m and re.search(r"存|收藏|保存", q[m.end():m.end() + 4]):
        y = int(m.group(1))
        if m.group(2):
            mo = max(1, min(12, int(m.group(2))))
            end = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
            return f"{y}-{mo:02d}-01", end.isoformat()
        return f"{y}-01-01", f"{y}-12-31"
    if re.search(r"去年(?:存|收藏|的)", q):
        return f"{today.year - 1}-01-01", f"{today.year - 1}-12-31"
    if re.search(r"今年(?:存|收藏|的)", q):
        return f"{today.year}-01-01", today.isoformat()
    if re.search(r"上个月(?:存|收藏|的)?", q):
        first = today.replace(day=1)
        last = first - timedelta(days=1)
        return last.replace(day=1).isoformat(), last.isoformat()
    m = re.search(r"最近\s*(\d{1,3}|[一两三四五六七八九十])\s*(天|周|个月)", q)
    if m:
        n = m.group(1)
        n = int(n) if n.isdigit() else "一两三四五六七八九十".index(n) + 1 if n != "两" else 2
        days = n * {"天": 1, "周": 7, "个月": 30}[m.group(2)]
        return (today - timedelta(days=days)).isoformat(), today.isoformat()
    if re.search(r"最近(?:存|收藏|刷到)", q):
        return (today - timedelta(days=30)).isoformat(), today.isoformat()
    return None, None


def library_authors(items) -> set[str]:
    return {str(it.get("author") or "").strip() for it in items or [] if len(str(it.get("author") or "").strip()) >= 2}


_AUTHOR_CUE = r"\s*(?:发|写|做|拍|说过|的那|的帖|的笔记|的视频|的文章|老师|博主|大大|的收藏)"
_AUTHOR_PRE = r"(?:作者|博主|up主|UP主|账号|那个|叫)\s*$"
COMMON_WORD_FREQ = 300   # jieba 词频 ≥ 这个的昵称当常用词（「随便」「苹果派」），必须带称呼线索才当作者


def _is_common_word(name: str) -> bool:
    try:
        import jieba
        jieba.initialize()
        return int(jieba.dt.FREQ.get(name, 0)) >= COMMON_WORD_FREQ
    except Exception:  # noqa: BLE001
        return False


def _author_filter(q: str, authors: set[str]) -> str | None:
    """问句里点名的库内作者。1017 修（阶段 0 核对 H03：「随便说律所加班多」把昵称「随便」当成作者硬过滤到只剩 1 篇）：
    昵称同时是常用词、或只有 2 字时，必须带称呼线索（前面「作者 / 博主 /@」或后面「发 / 写 / 的那篇 / 老师」）才算；
    「说」不再算线索（「随便说」「XX 说得对」都是口语）。≥3 字且不是常用词的照旧直接认。"""
    m = re.search(r"@([^\s，,。:：]{2,24})", q)
    if m and m.group(1) in authors:
        return m.group(1)
    hits = sorted((a for a in authors if a in q), key=len, reverse=True)
    for a in hits:
        cue = re.search(re.escape(a) + _AUTHOR_CUE, q) or re.search(_AUTHOR_PRE, q[:q.find(a)])
        if cue:
            return a
        # 没有称呼线索：≥3 字、不是常用词、且昵称后面是句尾 / 标点 / 空格 /「的」（「苹果派怎么做」里的「苹果派」紧接「怎么」，是食物不是人）
        boundary = re.search(re.escape(a) + r"(?=$|[\s，,。？?！!：:、]|的)", q)
        if len(a) >= 3 and not _is_common_word(a) and boundary:
            return a
    return None


def rule_filters(question: str, items=None, *, skills=None, today: date | None = None) -> dict[str, Any]:
    """S0 规则抽的过滤条件：{author, since, until, kind: [...], skill}（没认出的维度 = None / []）。"""
    q = str(question or "")
    since, until = _time_filter(q, today)
    kinds = []
    for kind, rx in _KIND_RE:
        if rx.search(q) and kind not in kinds:
            kinds.append(kind)
    if "pdf" in kinds and "attachment" in kinds:
        kinds.remove("attachment")
    out = {"author": _author_filter(q, library_authors(items)) if items else None,
           "since": since, "until": until, "kind": kinds, "skill": explicit_skill(q, skills)}
    return out


def explicit_skill(question: str, skills=None) -> str | None:
    """「/菜谱」「/recipe」「用 wiki 技能」= 她点名的技能；只认给定列表里有的（id 或中文名 / 别名）。"""
    if not skills:
        return None
    q = str(question or "")
    names = {}
    for s in skills:
        for key in [s.get("id"), s.get("name"), *(s.get("aliases") or [])]:
            if key:
                names[str(key).casefold()] = s.get("id")
    for m in re.finditer(r"(?:^|\s)/([^\s/]{1,20})|用\s*([^\s，。]{1,12}?)\s*(?:技能|skill)", q, re.I):
        key = (m.group(1) or m.group(2) or "").casefold()
        if key in names:
            return names[key]
    return None


def strip_meta(question: str, filters: dict[str, Any], *, keep_empty: bool = False) -> str:
    """原词路再去掉已经当过滤条件用掉的词（作者昵称、「2024年存的」），免得它们去匹配正文。
    keep_empty=True：去完什么都不剩就返回 ''（「科科科酱发过哪些」的检索核心是空的——只按作者列）。"""
    q = str(question or "")
    if filters.get("author"):
        q = q.replace(filters["author"], " ")
    q = re.sub(r"(?:20\d\d\s*年(?:\d{1,2}\s*月)?|去年|今年|上个月|最近\s*\S{1,3}(?:天|周|个月))(?:存|收藏|保存)?的?", " ", q)
    q = re.sub(r"(?:^|\s)/[^\s/]{1,20}", " ", q)
    if filters.get("kind"):
        q = re.sub(r"视频|vlog|录屏|pdf|PDF|附件|文件|文档|电子书|\d+\s*页(?:的)?", " ", q)
    q = re.sub(r"^(?:有个|有一个|有篇)|^教|的$", " ", q.strip())
    q = re.sub(r"(?:发|写|拍|做)过(?:哪些|什么|的)?|有哪些|都有啥|有什么", " ", q)
    q = _SPACE.sub(" ", q).strip()
    if keep_empty and not re.search(r"[\w一-鿿]", q):
        return ""
    return q or str(question or "")


def apply_filters(items, filters: dict[str, Any] | None):
    """按作者 / 收藏时间 / 类型筛；任何一维筛完是空 = 那一维不算（fail-open：她记错年份也照样有结果），返回 (items, 用上的维度)。"""
    filters = filters or {}
    out, used = list(items or []), []
    if filters.get("author"):
        got = [it for it in out if str(it.get("author") or "").strip() == filters["author"]]
        if got:
            out, used = got, used + ["author"]
    since, until = filters.get("since"), filters.get("until")
    if since or until:
        # 两种口径：默认按发帖日期（published），一篇都没有再按入库日期（date）；用的哪种记进 used（time:published / time:archived）
        for key, tag in (("published", "time:published"), ("date", "time:archived")):
            got = [it for it in out if it.get(key) and (not since or it[key] >= since) and (not until or it[key] <= until)]
            if got:
                out, used = got, used + [tag]
                break
    kinds = [k for k in filters.get("kind") or [] if k in KINDS]
    if kinds:
        got = [it for it in out if any(item_has_kind(it, k) for k in kinds)]
        if got:
            out, used = got, used + ["kind"]
    return out, used


def item_has_kind(item, kind: str) -> bool:
    files = item.get("attachment_files") or []
    if kind == "video":
        return item.get("kind") == "video"
    if kind == "attachment":
        return bool(files)
    if kind == "pdf":
        return any(str((f or {}).get("file") or f).lower().endswith(".pdf") for f in files)
    if kind == "image":
        return item.get("kind", "image") == "image"
    return False


def item_kinds(item) -> list[str]:
    return [k for k in KINDS if k != "image" and item_has_kind(item, k)] or ["image"]


# --------------------------------------------------------------------------
# S1：模型给的结构化理解
# --------------------------------------------------------------------------

GOALS = {"find", "ask", "survey"}
DEPTHS = {"precise", "detailed"}
# 1018 v2.1 理解层最小字段：task（作答模板按它挑）、note（研究笔记）、clues（找回题她亲口说的辨识细节）
TASKS = {"find", "howto", "synthesize", "survey", "inspire", "adapt", "evaluate", "browse", "absence", "portrait"}
NOTE_MAX = 300
CLUE_MAX = 4


def _short(value, limit=16) -> str:
    s = " ".join(str(value or "").split())
    return s[:limit] if isinstance(value, (str, int)) else ""


def _str_list(value, n, limit=16) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        s = _short(v, limit)
        if s and s not in out:
            out.append(s)
        if len(out) >= n:
            break
    return out


def _overlap(core: str, question: str) -> float:
    chars = [c for c in re.sub(r"\s", "", core.casefold())]
    if not chars:
        return 0.0
    q = question.casefold()
    return sum(c in q for c in chars) / len(chars)


def parse_s1(obj: Any, question: str, *, authors=None, skill_ids=None) -> dict[str, Any]:
    """模型 JSON → 合法字段（缺的不写）。obj 是已解析好的 dict（ask._parse_expand 同一次 JSON）。"""
    if not isinstance(obj, dict):
        return {}
    out: dict[str, Any] = {}
    intent = obj.get("intent") if isinstance(obj.get("intent"), dict) else {}
    for key, allowed in (("goal", GOALS), ("depth", DEPTHS), ("scope", ("single", "few", "many")), ("task", TASKS)):
        v = obj.get(key, intent.get(key))
        if isinstance(v, str) and v.strip().lower() in allowed:
            out[key] = v.strip().lower()
    # 1018 v2.1：研究笔记（给证据判定和作答看，绝不进 embedding）和找回线索；都是不可信文本，只限长、只认字符串
    note = " ".join(str(obj.get("note") or "").split()) if isinstance(obj.get("note"), str) else ""
    if len(note) >= 10:
        out["note"] = note[:NOTE_MAX]
    clues = _str_list(obj.get("clues"), CLUE_MAX, 40)
    if clues:
        out["clues"] = clues
    # 1015 第三批 R1：独立问句（追问补全省略、纠正错字）。只给语义路和 switch 换条件用，原句照样走词法
    sq = _short(obj.get("standalone_query"), 60)
    if sq and _overlap(sq, question) >= .3:
        out["standalone_query"] = sq
    core = _short(obj.get("core"), 16)
    # 同音错字（鱼路 → 鱼露）也算：字面重合过半；完全对不上原问题的 core 是模型漂移，丢
    if core and _overlap(core, question) >= .5:
        out["core"] = core
    ents = _str_list(obj.get("entities"), 5)
    if ents:
        out["entities"] = ents
    rels = []
    for r in obj.get("relations") if isinstance(obj.get("relations"), list) else []:
        if isinstance(r, dict):
            a, rel, b = _short(r.get("a") or r.get("from"), 16), _short(r.get("rel") or r.get("type"), 12), _short(r.get("b") or r.get("to"), 16)
            if a and b and rel:
                rels.append({"a": a, "rel": rel, "b": b})
        if len(rels) >= 3:
            break
    if rels:
        out["relations"] = rels
    cons = obj.get("constraints") if isinstance(obj.get("constraints"), dict) else {}
    must, prefer = _str_list(cons.get("must"), 4, 24), _str_list(cons.get("prefer"), 4, 24)
    if must or prefer:
        out["constraints"] = {"must": must, "prefer": prefer}
    neg = _str_list(obj.get("negation"), 4, 16)
    if neg:
        out["negation"] = neg
    facets = _str_list(obj.get("facets"), 3, 16)
    if len(facets) >= 2:
        out["facets"] = facets
    f = obj.get("filters") if isinstance(obj.get("filters"), dict) else {}
    filters: dict[str, Any] = {}
    author = _short(f.get("author"), 30)
    if author and authors is not None and author in authors:
        filters["author"] = author
    for key in ("since", "until"):
        v = str(f.get(key) or "")
        if re.fullmatch(r"20\d\d-\d\d-\d\d", v):
            filters[key] = v
    kinds = [k for k in _str_list(f.get("kind"), 4) if k in KINDS]
    if kinds:
        filters["kind"] = kinds
    if filters:
        out["filters"] = filters
    if skill_ids:
        sk = [s for s in _str_list(obj.get("skills"), 2, 24) if s in set(skill_ids)]
        if sk:
            out["skills"] = sk
    return out


def merge_filters(rule: dict[str, Any] | None, model: dict[str, Any] | None) -> dict[str, Any]:
    """规则 > 模型：每一维规则认出了就用规则的。"""
    rule, model = rule or {}, model or {}
    out = {}
    for key in ("author", "since", "until"):
        v = rule.get(key) or model.get(key)
        if v:
            out[key] = v
    kinds = rule.get("kind") or model.get("kind") or []
    if kinds:
        out["kind"] = list(kinds)
    return out


_PY_INDEX: dict[str, Any] = {"key": None}


def homophone_fix(word: str, items) -> str | None:
    """同音错字纠正（语音输入「鱼路」→「鱼露」）：word 在库里一处都没有时，按读音逐字换同音字，
    取库里真出现过的写法——和原词同字越多越优先，同分取出现次数多的。只认 2–4 个汉字；没把握返回 None。"""
    if not re.fullmatch(r"[一-鿿]{2,4}", word or "") or not items:
        return None
    from .retrieval import _CORPUS_CACHE, fields, norm
    from . import retrieval
    if retrieval._CORPUS_CACHE[0] is not items:
        retrieval._CORPUS_CACHE = (items, "\n".join(" ".join(norm(v) for v in fields(it).values()) for it in items))
    hay = retrieval._CORPUS_CACHE[1]
    if word in hay:
        return None
    if _PY_INDEX["key"] is not items:
        from .catalog import pinyin_chars
        by_py: dict[str, list[str]] = {}
        for ch, py in pinyin_chars(items).items():
            by_py.setdefault(py, []).append(ch)
        _PY_INDEX.update(key=items, by_py=by_py, char_py=None)
    from pypinyin import lazy_pinyin
    by_py = _PY_INDEX["by_py"]
    options = [[c] + [x for x in by_py.get(lazy_pinyin(c)[0], []) if x != c] for c in word]
    if any(len(o) > 80 for o in options):
        options = [o[:80] for o in options]
    best = None
    # 先只换一个字（最常见的错法），没有再换两个
    for changes in (1, 2):
        for i in range(len(word)):
            for a in options[i][1:]:
                cands = []
                if changes == 1:
                    cands = [word[:i] + a + word[i + 1:]]
                else:
                    for j in range(i + 1, len(word)):
                        cands += [word[:i] + a + word[i + 1:j] + b + word[j + 1:] for b in options[j][1:]]
                for cand in cands:
                    n = hay.count(cand)
                    if n and (best is None or n > best[1]):
                        best = (cand, n)
        if best:
            return best[0]
    return None


def understand(question: str, items=None, *, s1: dict[str, Any] | None = None, skills=None) -> dict[str, Any]:
    """S0 + S1 合起来的理解（检索 / 档位 / 作答都看这一份）。s1 = parse_s1 的结果（没有就纯规则）。"""
    s1 = s1 or {}
    rule = rule_filters(question, items, skills=skills)
    filters = merge_filters(rule, s1.get("filters"))
    stripped = strip_shell(question)
    goal = s1.get("goal") or heuristic_goal(question)
    list_rule = goal in ("ask", "survey") and bool(_LIST_RE.search(question or ""))
    if list_rule:
        goal = "survey"   # 1015 第三批 R1：显式规则路由（「要买啥 / 准备什么」= 要一张清单），模型说 ask 也按盘点
    if filters.get("author") and _SURVEY_RE.search(question or ""):
        goal = "survey"
    # 模型给的 core 也再过一遍规则（它常把「那个 / 叫啥」「某某发过哪些」留在里面）
    core = strip_meta(s1.get("core") or question, filters, keep_empty=True)
    core = strip_shell(core) if core else ""
    corrected = None
    if items and core:
        try:
            fixed = []
            for w in core.split():
                f = homophone_fix(w, items)
                fixed.append(f or w)
                if f:
                    corrected = (corrected or []) + [f"{w}→{f}"]
            core = " ".join(fixed)
        except Exception:  # noqa: BLE001 - 纠错只是兜底
            pass
    out = {"goal": goal, "goal_source": "rule-list" if list_rule else "model" if s1.get("goal") else "rule", "core": core[:40],
           **({"corrected": corrected} if corrected else {}),
           "stripped": stripped, "filters": filters,
           "skill": rule.get("skill"), "skill_source": "explicit" if rule.get("skill") else None}
    if s1.get("depth"):
        out["depth"] = s1["depth"]
    if s1.get("standalone_query"):
        out["standalone_query"] = s1["standalone_query"]
    if s1.get("scope"):
        out["scope"] = s1["scope"]   # 建议值（R1）：只作参考，深读几篇由检索后规则定（ask.select_primary）
    for key in ("entities", "relations", "constraints", "negation", "facets", "note", "clues"):
        if s1.get(key):
            out[key] = s1[key]
    # task：S1 给了就用；没给由 goal + 问法映射（answer_prompt.task_for），作答模板按它挑
    try:
        from .answer_prompt import task_for
        out["task"] = task_for({**out, "task": s1.get("task")}, question)
    except Exception:  # noqa: BLE001
        out["task"] = s1.get("task") if s1.get("task") in TASKS else {"find": "find", "survey": "survey"}.get(goal, "synthesize")
    if not out["skill"] and s1.get("skills"):
        out["skill"], out["skill_source"] = s1["skills"][0], "model"
    return out
