"""问收藏追问的会话状态（1018 v2.1 §5）：MCP 的 ask 以前只收 question、零状态，「只看刚才第一篇」被当新问题搜到科幻帖。

这里都是确定性规则、不调模型：
- bind_parent：这一问接哪一轮——客户端带 thread_id / context 最好；没带时只在命中强追问标记时取同一凭据 15 分钟内的最后一轮
  （绝不用全局最近一问，GPT33 C7 红线）；绑不到又是指代型 → 不检索，让她说是哪篇。
- resolve：指代怎么解析（设计 §5.4 表）：第 N 篇 → 单篇模式；第 N 个对象 → 那几篇；那 X 呢 → switch；其他 / 别的 → expand
  （排除上一轮的来源 id 和对象，「其他旅游」去掉「中国」这种最窄限定）。
- objects_from：答案里出现的对象（表格第一列、加粗的条目名），按出现顺序；下一轮「第 2 个」按它数。
模型输出和她的问句都是不可信文本：只做字符串匹配。
"""
from __future__ import annotations

import re
from typing import Any

BIND_WINDOW_S = 15 * 60   # 没带 thread_id 时兜底绑定的时间窗
# 地名表（places.json）只列国家 / 省；「其他旅游」要去掉的最窄限定还常是这些大词
REGION_WORDS = ("中国", "国内", "国外", "海外", "境外", "亚洲", "欧洲", "北美", "东南亚", "日韩", "港澳", "台湾", "华东", "华南", "华北", "西南", "东北")

_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "两": 2}
ORDINAL = re.compile(r"第\s*([一二三四五六七八九十两\d]+)\s*(篇|条|个|项|家|道|种|本|部|款|款|处|站)?")
# 「刚才第一篇」「刚才那篇」「那篇」「这篇」「上一篇」——指代某一篇
THIS_ONE = re.compile(r"(?:刚才|上面|前面|你(?:说|列|给|提)的)?(?:那|这|上一?)篇|刚才(?:那|这)个")
EXPAND = re.compile(r"其他|其它|别的|另外(?:的|还有)?|还有(?:什么|啥|别的|吗|呢|没有|哪些)|再(?:来|说|推荐|给)(?:几|些|点|一些)?")
SWITCH = re.compile(r"^(?:(?:好吧|好的|行|嗯|哦|ok)[\s,，、。!！]*)?(?:那么?|换成|换个|如果是|要是|换)\s*(.+?)\s*(?:的)?(?:呢|怎么样|如何|咋样)?\s*[？?]?\s*$")
# 指代型：没有上一轮就答不了的问法（兜不到就该反问，不该去全库搜「第一篇」）
DEICTIC = re.compile(r"第[一二三四五六七八九十两\d]+(?:篇|条|个|项)|刚才|上面|上文|前面|那篇|这篇|那几篇|这几篇|它们|^它|他们|这些|那些|上一(?:篇|个|答|轮)|"
                     r"其他|其它|别的|还有(?:什么|啥|呢|吗|没有)|再(?:来|说|推荐)")
_Y_AFTER = re.compile(r"(?:其他|其它|别的|另外(?:的)?)\s*(.*?)\s*(?:的)?(?:呢|吗|有没有|有哪些|推荐|有什么)?\s*[？?]?\s*$")


def _n(text: str) -> int | None:
    t = text.strip()
    if t.isdigit():
        return int(t)
    if t in _NUM:
        return _NUM[t]
    if len(t) == 2 and t[0] == "十" and t[1] in _NUM:
        return 10 + _NUM[t[1]]
    if len(t) == 2 and t[1] == "十" and t[0] in _NUM:
        return _NUM[t[0]] * 10
    return None


def is_followup(question: str) -> bool:
    """命中强追问标记（含「其他 / 那 X 呢」）才允许兜底绑定上一轮。"""
    from .ask_intent import STRONG_FOLLOWUP, strip_shell
    q = str(question or "").strip()
    if not q:
        return False
    if STRONG_FOLLOWUP.search(strip_shell(q)) or EXPAND.search(q) or THIS_ONE.search(q):
        return True
    return bool(SWITCH.match(q) and len(q) <= 30)


def is_deictic(question: str) -> bool:
    return bool(DEICTIC.search(str(question or "")))


def bind_parent(question: str, *, thread_id: str | None = None, parent_turn_id: str | None = None, who: str | None = None,
                turns=None) -> tuple[dict[str, Any] | None, str]:
    """(上一轮登记 | None, 绑定方式)。方式：parent（客户端给了 turn id）/ thread / fallback（同凭据 15 分钟内）/ none。"""
    from . import ask_turns as T
    T = turns or T
    if parent_turn_id:
        row = T.get(parent_turn_id)
        if row:
            return row, "parent"
    if thread_id:
        row = T.latest_in_thread(thread_id)
        if row:
            return row, "thread"
    if who and is_followup(question):
        row = T.latest_for_who(who, within_s=BIND_WINDOW_S)
        if row:
            return row, "fallback"
    return None, "none"


def parent_from_context(context: Any, items: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """客户端存不了状态时带的 context:{previous_question, source_ids} → 一条临时的「上一轮」。"""
    if not isinstance(context, dict):
        return None
    ids = [str(i) for i in (context.get("source_ids") or []) if isinstance(i, (str, int)) and str(i).strip()]
    prev = str(context.get("previous_question") or "").strip()
    if not ids and not prev:
        return None
    by_id = {it.get("id"): it for it in items or []}
    ordered = []
    for i, sid in enumerate(ids, 1):
        it = by_id.get(sid)
        if it is None:
            short = [k for k in by_id if k and (k.endswith(sid) or k.startswith(sid))]
            it = by_id.get(short[0]) if len(short) == 1 else None
        if it is not None:
            ordered.append({"n": i, "id": it.get("id"), "title": it.get("title") or "", "role": "A"})
    return {"q": prev, "mode": "direct", "ordered_sources": ordered, "ids": [o["id"] for o in ordered],
            "primary_ids": [o["id"] for o in ordered], "objects": [], "scope": {"topic": prev}, "from_context": True}


def _sources(parent: dict[str, Any]) -> list[dict[str, Any]]:
    rows = parent.get("ordered_sources")
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict) and r.get("id")]
    ids = parent.get("primary_ids") or parent.get("ids") or []
    return [{"n": i + 1, "id": sid, "title": "", "role": "A"} for i, sid in enumerate(ids) if isinstance(sid, str)]


def _topic(parent: dict[str, Any]) -> str:
    scope = parent.get("scope") if isinstance(parent.get("scope"), dict) else {}
    u = parent.get("understanding") if isinstance(parent.get("understanding"), dict) else {}
    return str(scope.get("topic") or u.get("core") or parent.get("q") or "").strip()


def expand_question(prev_topic: str, y: str) -> tuple[str, str]:
    """「中国旅行推荐」+「其他旅游」→ ('旅游推荐', '中国')：去掉上一轮最窄的那个限定（地名）。返回 (新问句, 被去掉的限定)。"""
    dropped = ""
    topic = prev_topic
    for w in REGION_WORDS:
        if w in prev_topic and w not in (y or ""):
            topic, dropped = prev_topic.replace(w, "", 1).strip(" ，,、的"), w
            break
    try:
        from . import places
        from .retrieval import norm
        for row in ([] if dropped else places.query_places(prev_topic)):
            for name in row["names"]:
                if name and name in norm(prev_topic) and name not in norm(y or ""):
                    idx = norm(prev_topic).find(name)
                    if idx >= 0:
                        topic = (prev_topic[:idx] + prev_topic[idx + len(name):]).strip(" ，,、的")
                        dropped = prev_topic[idx:idx + len(name)]
                        break
            if dropped:
                break
    except Exception:  # noqa: BLE001 - 地名表读不了就不去限定
        pass
    y = (y or "").strip(" ，,、的")
    if y and y not in topic:
        tail = ""
        m = re.search(r"(推荐|攻略|做法|清单|盘点|教程|方案)$", topic)
        if m and not re.search(m.group(1), y):
            tail = m.group(1)
        topic = y + tail
    return topic or y or prev_topic, dropped


def resolve(question: str, parent: dict[str, Any] | None) -> dict[str, Any]:
    """指代解析（§5.4 表）。返回 {kind, source_ids?, exclude_ids?, avoid?, question, note}；kind=none = 照常检索。"""
    q = str(question or "").strip()
    out: dict[str, Any] = {"kind": "none", "question": q, "note": ""}
    if not parent:
        return out
    srcs = _sources(parent)
    objs = [o for o in (parent.get("objects") or []) if isinstance(o, dict) and o.get("name")]
    # 1 其他 / 别的 → expand（先判，「那其他旅游呢」也是 expand 不是 switch）
    if EXPAND.search(q):
        m = _Y_AFTER.search(q)
        y = (m.group(1) if m else "").strip()
        y = re.sub(r"^(?:的|还有|有)", "", y).strip()
        topic, dropped = expand_question(_topic(parent), y)
        out.update(kind="expand", question=topic, exclude_ids=[s["id"] for s in srcs], avoid=[o["name"] for o in objs][:20],
                   note=("按「" + (f"{dropped}以外、" if dropped else "") + "上次没提的」来"))
        return out
    # 2 第 N 篇 / 第 N 个对象
    m = ORDINAL.search(q)
    if m:
        n, unit = _n(m.group(1)), m.group(2) or ""
        if n:
            if unit and unit not in ("篇", "条") and objs and n <= len(objs):
                obj = objs[n - 1]
                ids = [s["id"] for s in srcs if s.get("n") in set(obj.get("ns") or [])] or [s["id"] for s in srcs[:1]]
                out.update(kind="object", source_ids=ids, object=obj["name"], question=f"关于「{obj['name']}」：{q}",
                           note=f"（第 {n} 个：{obj['name']}）")
                return out
            if n <= len(srcs):
                s = srcs[n - 1]
                out.update(kind="single", source_ids=[s["id"]], question=f"只看《{s.get('title') or ''}》这一篇：{q}" if s.get("title") else q,
                           note=f"（第 {n} 篇：《{s.get('title') or ''}》）")
                return out
            out.update(kind="missing", note=f"上一轮只有 {len(srcs)} 篇，没有第 {n} 篇")
            return out
    if THIS_ONE.search(q) and srcs:
        s = srcs[0]
        out.update(kind="single", source_ids=[s["id"]], question=f"只看《{s.get('title') or ''}》这一篇：{q}" if s.get("title") else q,
                   note=f"（那篇：《{s.get('title') or ''}》）")
        return out
    # 3 那 X 呢 → switch（检索交给现有的 standalone / switch 机制，这里只标记）
    sm = SWITCH.match(q)
    if sm and len(q) <= 30:
        out.update(kind="switch", switch_to=sm.group(1).strip())
        return out
    return out


# --------------------------------------------------------------------------
# 答案里的对象
# --------------------------------------------------------------------------

_CITE = re.compile(r"\[来源\s*(\d+)\]")
_BOLD_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.、)])\s*\*\*([^*]{1,24}?)\*\*")
_BOLD_HEAD = re.compile(r"^\s*#{2,4}\s*\**([^*#\[]{1,24}?)\**\s*(?:\[来源\s*\d+\])*\s*$")
OBJECTS_MAX = 20


def _clean(name: str) -> str:
    name = _CITE.sub("", name)
    name = re.sub(r"[*_`「」《》【】\[\]（）()]", "", name)
    return re.sub(r"[：:—\-–].*$", "", name).strip(" ，,。")


def objects_from(markdown: str) -> list[dict[str, Any]]:
    """表格第一列（去表头 / 分隔行）+ 列表里加粗的条目名 + 小标题，按出现顺序；每个带它那一行引用的来源编号。"""
    from .answer_prompt import split_guide
    body, _g = split_guide(markdown)
    out, seen = [], set()

    def add(name, ns):
        name = _clean(name)
        if not name or len(name) < 2 or name in seen or re.fullmatch(r"[\d\s.%]+", name):
            return
        seen.add(name)
        out.append({"name": name, "ns": sorted(set(ns))})

    in_table, header_done = False, False
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if re.fullmatch(r"[-:\s|]+", line):
                header_done = True
                in_table = True
                continue
            if not in_table:
                in_table = True
                continue   # 表头行
            if cells and header_done:
                add(cells[0], [int(n) for n in _CITE.findall(line)])
            continue
        in_table, header_done = False, False
        m = _BOLD_ITEM.match(line) or _BOLD_HEAD.match(line)
        if m:
            add(m.group(1), [int(n) for n in _CITE.findall(line)])
        if len(out) >= OBJECTS_MAX:
            break
    return out
