"""个人 Wiki 的「让 AI 改」（10-31）：改一段 / 整页，只回建议，不写盘。

页面拿到建议后给她看改了什么，她点「用这版」才照常经 `pwiki save`（kind=ai）存进去——写盘还是只有 personal_wiki 一个 writer。
模型用 indextree.text_ai()（问收藏正在用的文本 AI；命令行模型 / HTTP 接口都行，没 key 时退到归档摘要模型）。
提示词就在这个文件里（PRESETS = 页面上那排现成说法；她自己打的话直接当任务）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import storage
from .personal_wiki import CITE_RE, WikiError, get_page

TEXT_LIMIT = 24000        # 送进模型的正文上限（整页）；再长就让她分段改
MATERIAL_LIMIT = 700      # 每篇引用的收藏给模型看多少字
MAX_MATERIALS = 12

RULES = """你在帮她改她自己的个人 Wiki（Markdown 笔记）。这是她自己的思考、判断和偏好，不是给别人看的文章。
规矩：
1. 改好的 Markdown 放在 <replacement> 和 </replacement> 之间，外面一个字都不要写：不要解释，不要「以下是…」「好的，」这类开头结尾，不要用代码块包起来。
2. 保持她的口吻和观点；不替她下新结论，不编造事实、数字、链接、出处。
3. 收藏引用写成 [标题](lwa:编号)：原样保留，一个都不能丢，编号一个字都不能改；可以挪位置、可以改括号外面的话。
4. 只用这些写法：段落、## / ### 小标题、- 列表、- [ ] 待办、> 引用、**粗体**、`代码`。不要表格，不要 emoji。
5. 中文用全角标点。"""

# 页面上那排现成说法：key → (按钮上的字, 给模型的任务)
PRESETS: dict[str, tuple[str, str]] = {
    "polish": ("润色", "润色：读起来更顺，意思不变，长度差不多。"),
    "concise": ("精简", "精简：去掉重复和绕的话，要点和引用一个不少。"),
    "expand": ("说清楚一点", "展开一点：把意思说清楚，补一两句原因或例子；只能用她已经写了的和下面引用材料里有的内容。"),
    "list": ("改成列表", "改成要点列表：一条一个意思，保留引用。"),
    "fix": ("只改错字", "只改错别字、标点和明显的语病，别的一个字都不动。"),
    "structure": ("理顺结构", "理顺整页结构：按意思重新分组、补上 ## 小标题，内容不删不加，引用跟着它说的那句走。"),
    "from_cites": ("从引用补要点", "根据下面引用的收藏材料，在相关位置补几条要点；每条后面跟上对应的 [标题](lwa:编号)，材料里没有的不要写。"),
    "draft": ("搭个框架", "这页几乎是空的：按标题和她已经写的那一点，搭一个框架——几个 ## 小标题，每节一两句引导她自己往下写的话（问句也行），不编具体事实。"),
}
BLOCK_PRESETS = ("polish", "concise", "expand", "list", "fix")
PAGE_PRESETS = ("structure", "concise", "from_cites", "draft", "polish")


def main(argv: list[str]) -> int:
    """`python -m link_brain pwiki ai [--input 文件]`：stdin 一个 JSON，最后一行回 JSON（read.outcome 外形）。__main__ 直接调，不经 cli。"""
    import sys
    from .personal_wiki import _read_input, dump_json, outcome
    from .errtext import errtext
    path = argv[argv.index("--input") + 1] if "--input" in argv[:-1] else "-"
    try:
        res = rewrite(_read_input(path))
        dump_json(outcome(res, ok=True, message="AI 改好了，看过再用"))
        return 0
    except WikiError as exc:
        dump_json(outcome({}, ok=False, code=exc.code, message=str(exc)))
        print(str(exc), file=sys.stderr)
        return 2 if exc.code == "BAD_ARGS" else 1
    except Exception as exc:  # noqa: BLE001 - 插件要的是一行 JSON
        msg = f"AI 没改成：{errtext(exc)}"
        dump_json(outcome({}, ok=False, code="TRANSIENT.STEP_CRASHED", message=msg))
        print(msg, file=sys.stderr)
        return 1


def presets() -> dict[str, Any]:
    return {"block": [{"key": k, "label": PRESETS[k][0]} for k in BLOCK_PRESETS],
            "page": [{"key": k, "label": PRESETS[k][0]} for k in PAGE_PRESETS]}


def _materials(texts: list[str], vault: Path | None) -> list[dict[str, str]]:
    """正文里引用到的收藏：标题 + 摘要 + 正文开头（从 _archive/catalog-data.json 拿，读不到就没有）。"""
    ids = list(dict.fromkeys(m.group(2) for t in texts for m in CITE_RE.finditer(t or "")))[:MAX_MATERIALS]
    if not ids:
        return []
    try:
        data = json.loads(((vault or storage.vault_root()) / storage.ARCHIVE_DIRNAME / "catalog-data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    by = {str(it.get("id")): it for it in items or [] if isinstance(it, dict)}
    short: dict[str, Any] = {}
    for k, it in by.items():   # 引用里写短 id（不带 xhs- / bili- 前缀）也认，撞了就不猜
        tail = k.split("-", 1)[1] if "-" in k else ""
        if tail:
            short[tail] = None if tail in short else it
    out = []
    for i in ids:
        it = by.get(i) or short.get(i)
        if not it:
            continue
        body = str(((it.get("search_fields") or {}).get("body")) or "")
        text = " ".join(f"{it.get('summary') or ''} {body}".split())[:MATERIAL_LIMIT]
        out.append({"id": i, "title": str(it.get("title") or ""), "text": text})
    return out


# 模型没按 <replacement> 外框回时的兜底：剥代码块、开场白（「以下是改好的：」「好的，」）和收尾客套
_FENCE = re.compile(r"^```[\w-]*\n([\s\S]*?)\n```$")
_OPEN = re.compile(r"^(?:(?:好的|好|当然|可以|没问题|明白)[，,。！!]?\s*)?(?:(?:以下|下面|这)是[^\n]{0,30}?[：:]|好的[，,。！!][^\n]{0,30}?[：:]?)\s*\n+")
_CLOSE = re.compile(r"\n+(?:希望|如需|如果(?:你|您)|需要的话|有需要|还需要)[^\n]{0,60}$")


def _clean(out: str) -> str:
    """只认最外一层 <replacement>…</replacement>（第一个开头到最后一个结尾，内容里再出现同名标签不截断）；没有外框就走兜底。"""
    s = str(out or "").strip()
    a, b = s.find("<replacement>"), s.rfind("</replacement>")
    if a >= 0 and b > a:
        return s[a + len("<replacement>"):b].strip("\n")
    if a >= 0:   # 只有开头没有结尾（被截断）：从开头取到底
        s = s[a + len("<replacement>"):]
    m = _FENCE.match(s.strip())   # 模型还是包了代码块
    s = (m.group(1) if m else s).strip()
    s = _CLOSE.sub("", _OPEN.sub("", s, count=1))
    m = _FENCE.match(s.strip())
    return (m.group(1) if m else s).strip("\n")


def rewrite(data: dict[str, Any], vault: Path | None = None) -> dict[str, Any]:
    """data = {id, scope: part|page, text, instruction?, preset?}。返回 {text, model, lost_cites}，不写盘。
    part = 这页里的一截（当前那一节 / 选中的几段；旧的 block 也认）。"""
    from . import indextree, text_stream
    scope = str(data.get("scope") or "part")
    if scope == "block":
        scope = "part"
    if scope not in ("part", "page"):
        raise WikiError("BAD_ARGS", f"不认识的范围：{scope}")
    text = str(data.get("text") or "")
    instruction = str(data.get("instruction") or "").strip()
    preset = str(data.get("preset") or "")
    if preset and preset not in PRESETS:
        raise WikiError("BAD_ARGS", f"不认识的说法：{preset}")
    if not instruction and not preset:
        raise WikiError("BAD_ARGS", "要让 AI 怎么改？")
    if not text.strip() and preset != "draft" and scope == "part":
        raise WikiError("BAD_ARGS", "这一段是空的，先写一点再让 AI 改")
    if len(text) > TEXT_LIMIT:
        raise WikiError("BAD_ARGS", f"这次要改的字太多（{len(text)} 字），分几段改")
    page = get_page(str(data.get("id") or ""), vault) if data.get("id") else {"title": "", "body": ""}
    cfg, why = indextree.text_ai()
    if cfg is None:
        raise WikiError("NOT_CONFIGURED", f"没有能用的文本 AI（{why}）：去插件设置 → AI 里配一个，命令行模型或接口都行")
    task = "；".join(x for x in (PRESETS[preset][1] if preset else "", instruction) if x)
    mats = _materials([text, page.get("body") or ""] if preset == "from_cites" or scope == "page" else [text], vault)
    parts = [f"页面标题：《{page.get('title') or data.get('title') or ''}》"]
    if scope == "part":
        parts.append("要改的是这页里的一截（只输出改好的这一截，别把整页抄回来）。整页正文给你参考上下文：\n<<<整页\n" + (page.get("body") or "")[:TEXT_LIMIT] + "\n整页>>>")
    else:
        parts.append("要改的是整页正文（输出改好的整页正文，不含文件头）。")
    if mats:
        parts.append("引用的收藏材料（只当参考，别整段抄）：\n" + "\n".join(f"- [{m['title']}](lwa:{m['id']})：{m['text']}" for m in mats))
    prompt = RULES + "\n\n这次要做的：" + task + "\n\n" + "\n\n".join(parts)
    res = text_stream.call(prompt, ("<<<要改的\n" + text + "\n要改的>>>") if text.strip() else "（还没写内容）",
                           {**cfg, "noThinking": True, "timeoutSec": max(float(cfg.get("timeoutSec") or 0), 180.0)}, feature="other")
    if res.get("status") != "ok":
        raise WikiError(str(res.get("code") or "AI_FAILED"), "AI 没改成：" + str(res.get("error") or "模型没回"))
    out = _clean(res.get("text") or "")
    out = re.sub(r"^<<<要改的\n|\n?要改的>>>$", "", out).strip("\n")
    if not out.strip():
        raise WikiError("AI_FAILED", "AI 回了空的，再试一次")
    lost = sorted({m.group(2) for m in CITE_RE.finditer(text)} - {m.group(2) for m in CITE_RE.finditer(out)})
    return {"text": out, "model": str(cfg.get("model") or ""), "lost_cites": lost, "scope": scope}
