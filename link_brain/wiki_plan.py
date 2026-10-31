"""个人 Wiki「按我的思路搭框架」（10-31 第二块）：用户写一段话 + 思路 → AI 先出计划（每节标题 + 去收藏里搜什么）→ 用户改过、点头 →
每节用问收藏同一套检索（retrieval.retrieve_payload，不现调扩词模型）找候选收藏 → 模型只许引候选编号 S1…Sn，每条要点附一句原帖原话 →
程序把编号换成 [标题](lwa:id)、删掉不存在的编号、核对原话是不是原帖里的字（对不上的标出来），用户写的字一个不动，只往节下补；
和用户相反的说法单独放「相反的说法」。只回建议（整页新正文），不写盘——页面照第一块逐处勾选，用户点了才经 pwiki save（kind=ai）存。

CLI：`python -m link_brain pwiki plan`（stdin {id, idea, text}）/ `pwiki fill`（stdin {id, idea, text, sections:[{title, query}]}），__main__ 直接转过来。
借的思路（只借思路）：先出计划、批准再写（odere-pro/claude-wiki-pages-plugin）；资料编号 [S1] 只许引编号、程序换回并删掉不存在的（kytmanov/obsidian-llm-wiki-local）；
引文必须是原文逐字子串（odere ADR-0017）；用户已写的不改、只在节下追加、冲突两边都留（GD4AI/obsidian-llm-wiki）。
"""
from __future__ import annotations

import re
from typing import Any

from .personal_wiki import WikiError, get_page

MAX_SECTIONS = 8
PER_SECTION = 5          # 每节最多几篇候选
EXCERPT_CHARS = 700      # 每篇给模型看多少字摘录
IDEA_LIMIT = 4000

PLAN_RULES = """你在帮用户给其个人 Wiki 页搭框架。用户写了一段话，说了自己的思路 / 想要的几节。
先只出计划，不写正文：按用户的思路拆成几节（用户点名了的节一定要有、顺序照用户的；用户没说的你可以补 1–2 节但别喧宾夺主），
每节给：title（小标题，短）、query（去用户的收藏里搜什么：一句关键词，中文，越具体越好）、why（这一节要回答什么，一句话）。
只输出 JSON：{"sections":[{"title":"…","query":"…","why":"…"}]}，最多 8 节，不要别的字。"""

FILL_RULES = """你在帮用户往其个人 Wiki 页里补材料。用户的思路和每一节要回答什么在下面；每节附了从用户的收藏里检索到的候选材料，编号 S1、S2…
规矩：
1. 每条要点只能来自候选材料，引用只写编号（如 S3），不许写别的编号、链接或你自己知道的东西；材料里没有的就不写，这一节可以空着。
2. 每条要点附一句原帖原话 quote：必须从那篇材料里一字不差地抄（可以截短，但不能改字、不能拼接）。
3. 和用户的思路 / 已经写下的观点相反的说法，放进那一节的 against，不要混进 points。
4. 要点用用户的口吻写成一句话，中文全角标点，不要 emoji。
只输出 JSON：{"sections":[{"title":"和计划里一样","points":[{"text":"…","src":"S3","quote":"…"}],"against":[{"text":"…","src":"S5","quote":"…"}]}]}，不要别的字。"""


def _call(prompt: str, text: str) -> tuple[dict[str, Any], str]:
    from . import indextree, llm, text_stream
    cfg, why = indextree.text_ai()
    if cfg is None:
        raise WikiError("NOT_CONFIGURED", f"没有能用的文本 AI（{why}）：去插件设置 → AI 里配一个，命令行模型或接口都行")
    res = text_stream.call(prompt, text, {**cfg, "noThinking": True, "timeoutSec": max(float(cfg.get("timeoutSec") or 0), 240.0)}, feature="other")
    if res.get("status") != "ok":
        raise WikiError(str(res.get("code") or "AI_FAILED"), "AI 没回来：" + str(res.get("error") or "模型没回"))
    try:
        return llm.parse_json(str(res.get("text") or "")), str(cfg.get("model") or "")
    except ValueError as exc:
        raise WikiError("AI_FAILED", "AI 回的格式不对，再试一次") from exc


def _context(data: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    page = get_page(str(data.get("id") or "")) if data.get("id") else {"title": "", "body": ""}
    idea = str(data.get("idea") or "").strip()[:IDEA_LIMIT]
    if not idea:
        raise WikiError("BAD_ARGS", "先写几句你的思路：想写什么、想要哪几节")
    text = str(data.get("text") if data.get("text") is not None else page.get("body") or "")
    return page, idea, text


def make_plan(data: dict[str, Any]) -> dict[str, Any]:
    page, idea, text = _context(data)
    got, model = _call(PLAN_RULES, f"页面标题：《{page.get('title') or ''}》\n\n用户的思路：\n{idea}\n\n这页现在的正文（用户写的，可能是空的）：\n{text[:6000] or '（空）'}")
    secs = []
    for s in (got.get("sections") or [])[:MAX_SECTIONS]:
        if not isinstance(s, dict):
            continue
        title = " ".join(str(s.get("title") or "").split())[:40]
        if title:
            secs.append({"title": title, "query": " ".join(str(s.get("query") or title).split())[:80], "why": " ".join(str(s.get("why") or "").split())[:120]})
    if not secs:
        raise WikiError("AI_FAILED", "AI 没拆出小节，换个说法再试")
    return {"sections": secs, "model": model}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _full_text(item: dict[str, Any]) -> str:
    """原帖全文（标题 + 摘要 + 各个检索字段：正文 / OCR / 转写 / 评论 / 附件），核对原话用。"""
    from . import retrieval
    try:
        fields = retrieval._content_fields(item)
    except Exception:  # noqa: BLE001 - 字段取不到就用 search_fields 原样
        fields = item.get("search_fields") or {}
    parts = [str(item.get("title") or ""), str(item.get("summary") or "")] + [str(v) for v in (fields or {}).values() if isinstance(v, str)]
    return "\n".join(parts)


def _heading_index(lines: list[str]) -> list[tuple[int, int, str]]:
    out, fence = [], False
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            out.append((i, len(m.group(1)), m.group(2).strip()))
    return out


def merge_into(text: str, blocks: list[tuple[str, list[str]]]) -> str:
    """把每节补的那几行接到用户的正文里：已经有同名小标题的接在那一节末尾，没有的在页尾新开 ## 小标题。用户写的行一行不动。"""
    lines = text.rstrip("\n").split("\n") if text.strip() else []
    tail: list[str] = []
    for title, add in blocks:
        if not add:
            continue
        heads = _heading_index(lines)
        hit = next((h for h in heads if _norm(h[2]) == _norm(title)), None)
        if hit:
            i, lv, _ = hit
            end = next((h[0] for h in heads if h[0] > i and h[1] <= lv), len(lines))
            while end > i + 1 and not lines[end - 1].strip():
                end -= 1
            lines[end:end] = [""] + add
        else:
            tail += ["", f"## {title}", ""] + add
    out = "\n".join(lines + tail).strip("\n")
    return re.sub(r"\n{3,}", "\n\n", out)


def fill(data: dict[str, Any]) -> dict[str, Any]:
    from . import ask, retrieval
    page, idea, text = _context(data)
    plan = [s for s in (data.get("sections") or []) if isinstance(s, dict) and str(s.get("title") or "").strip()][:MAX_SECTIONS]
    if not plan:
        raise WikiError("BAD_ARGS", "计划里一节都没有")
    by_id = {str(it.get("id")): it for it in ask.load_items()}
    srcs: list[dict[str, Any]] = []          # S1… 全页一套编号（同一篇在几节里出现只编一次）
    num: dict[str, str] = {}
    material = []
    for s in plan:
        q = " ".join(str(s.get("query") or s.get("title")).split())
        try:
            got = retrieval.retrieve_payload(q, top_k=PER_SECTION)
        except Exception as exc:  # noqa: BLE001 - 一节检索失败不拖垮整页
            got = {"results": [], "error": str(exc)}
        rows = []
        for r in got.get("results") or []:
            iid = str(r.get("item_id") or "")
            if not iid:
                continue
            if iid not in num:
                num[iid] = f"S{len(srcs) + 1}"
                srcs.append({"n": num[iid], "id": iid, "title": str(r.get("title") or "未命名收藏")})
            ex = "\n".join(str(x.get("text") or "") for x in (r.get("excerpts") or []) if isinstance(x, dict))
            rows.append(f"[{num[iid]}]《{r.get('title') or ''}》\n{ex[:EXCERPT_CHARS]}")
        material.append(f"### 节：{s['title']}\n这一节要回答：{s.get('why') or s['title']}\n候选材料：\n" + ("\n\n".join(rows) if rows else "（收藏里没搜到）"))
    if not srcs:
        raise WikiError("NOT_FOUND", "每一节都没在收藏里搜到材料：换几个搜什么的词再试")
    got, model = _call(FILL_RULES, f"页面标题：《{page.get('title') or ''}》\n\n用户的思路：\n{idea}\n\n用户已经写下的正文（不要改，只作参考）：\n{text[:4000] or '（空）'}\n\n"
                       + "\n\n".join(material))
    valid = {x["n"]: x for x in srcs}
    used: set[str] = set()
    bad_quotes, dropped = [], 0
    blocks: list[tuple[str, list[str]]] = []
    secs = {(_norm(x.get("title"))): x for x in (got.get("sections") or []) if isinstance(x, dict)}

    def line(p: dict[str, Any]) -> list[str] | None:
        nonlocal dropped
        src = str(p.get("src") or "").strip().upper().strip("[]")
        body = " ".join(str(p.get("text") or "").split())
        if src not in valid or not body:   # 编了不存在的编号 / 空话：整条不要
            dropped += 1
            return None
        s = valid[src]
        used.add(src)
        out = [f"- {body} [{s['title']}](lwa:{s['id']})"]
        quote = " ".join(str(p.get("quote") or "").split())
        if quote:
            ok = _norm(quote) in _norm(_full_text(by_id.get(s["id"]) or {}))
            if not ok:
                bad_quotes.append({"src": src, "title": s["title"], "quote": quote})
            out.append(f"  > 「{quote}」" + ("" if ok else "（⚠ 原帖里没找到这句，别直接信）"))
        return out

    for s in plan:
        got_s = secs.get(_norm(s["title"])) or {}
        add: list[str] = []
        for p in got_s.get("points") or []:
            if isinstance(p, dict) and (ln := line(p)):
                add += ln
        against = [ln for p in (got_s.get("against") or []) if isinstance(p, dict) and (ln := line(p))]
        if against:
            add += ["", "### 相反的说法"] + [x for ln in against for x in ln]
        blocks.append((s["title"], add))
    new = merge_into(text, blocks)
    if new.strip() == text.strip():
        raise WikiError("AI_FAILED", "AI 这次一条能用的都没补出来（编号对不上的都删了）：换几个搜什么的词再试")
    return {"text": new, "model": model, "sources": [x for x in srcs if x["n"] in used], "bad_quotes": bad_quotes, "dropped": dropped,
            "scope": "page"}


def main(argv: list[str]) -> int:
    """`python -m link_brain pwiki plan|fill [--input 文件]`：stdin 一个 JSON，最后一行回 JSON（read.outcome 外形）。"""
    import sys
    from .errtext import errtext
    from .personal_wiki import _read_input, dump_json, outcome
    op = argv[0] if argv else ""
    rest = argv[1:]
    path = rest[rest.index("--input") + 1] if "--input" in rest[:-1] else "-"
    try:
        data = _read_input(path)
        if op == "plan":
            res, msg = make_plan(data), "计划出来了：改好再点「按这个去收藏里找」"
        elif op == "fill":
            res = fill(data)
            msg = f"补好了：用了 {len(res['sources'])} 篇收藏" + (f"，{len(res['bad_quotes'])} 句原话没对上" if res["bad_quotes"] else "")
        else:
            raise WikiError("BAD_ARGS", f"不认识的子命令：{op}")
        dump_json(outcome(res, ok=True, message=msg))
        return 0
    except WikiError as exc:
        dump_json(outcome({}, ok=False, code=exc.code, message=str(exc)))
        print(str(exc), file=sys.stderr)
        return 2 if exc.code in ("BAD_ARGS", "NOT_FOUND") else 1
    except Exception as exc:  # noqa: BLE001 - 插件要的是一行 JSON
        msg = f"没搭成：{errtext(exc)}"
        dump_json(outcome({}, ok=False, code="TRANSIENT.STEP_CRASHED", message=msg))
        print(msg, file=sys.stderr)
        return 1
