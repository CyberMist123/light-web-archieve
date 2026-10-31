"""个人 Wiki 页面文件的纯函数（10-31 从 personal_wiki 拆出来）：解析文件头 + 正文、hash、派生（引用 / 标签 / 小标题 / 待办 / 首句）、扫一个目录。

不碰 storage、不加锁、不写盘：问收藏 / MCP 的 Wiki 检索（personal_wiki_search）只用这里，库路径由调用方给——
这样 ask 读 Wiki 不会把 personal_wiki（→ storage → indextree …）卷进大 import 环（tests/test_guards.py MAX_CYCLE）。
personal_wiki 是唯一写手，照旧从这里拿这些函数（名字不变）。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

DIR_NAME = "PersonalWiki"
ROLES = ("page", "topic")
FIELD_ORDER = ("id", "title", "role", "index_tag", "order", "tags", "created", "updated")

# 和页面（wiki-view.js / 原型）同一套认法
WL_RE = re.compile(r"\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]")
CITE_RE = re.compile(r"\[([^\]\n]+)\]\(lwa:([\w-]+)\)")
TAG_RE = re.compile(r"(?:^|(?<=[\s(（，。、；：·]))#([^\s#\[\]()（）,，。、;；:：!！?？\"'<>*`·]+)", re.M)
HEAD_RE = re.compile(r"^(#{1,4})\s+(.*)$")
TASK_RE = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$")
FENCE_RE = re.compile(r"```[\s\S]*?```")

# Windows 设备名：当文件 / 目录名（带不带扩展名都算）会写到一半才失败
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$", re.I)


def _valid_id(pid: str) -> bool:
    return bool(re.fullmatch(r"[\w-]{1,64}", pid or "")) and not _RESERVED.match(pid)


def _clean_tag(t: Any) -> str:
    return re.sub(r"[\s,，#\[\]\"]+", "", str(t or "")).strip()


def _scalar(v: str) -> Any:
    v = v.strip()
    if v.startswith('"') or v.startswith("["):
        try:
            return json.loads(v)
        except ValueError:
            if v.startswith("["):   # 原型写的 [a, b]（不带引号）
                return [s.strip().strip("'\"") for s in v[1:-1].split(",") if s.strip()]
    return v


def parse_page(text: str) -> dict[str, Any]:
    """文件全文 → {id, title, role, index_tag, order, tags, created, updated, body, extra}。没有文件头也能读（Obsidian 里新建的）。"""
    text = text.replace("\r\n", "\n")
    meta: dict[str, Any] = {}
    extra: list[str] = []
    body = text
    m = re.match(r"^---\n([\s\S]*?)\n---\n?", text)
    if m:
        body = text[m.end():]
        # 一个属性 = 顶格的 `key: 值` + 后面缩进 / `- ` 开头的续行。Obsidian 属性面板写列表是块状的：
        #   tags:
        #     - travel
        # 认出来当列表；不认识的属性连同续行原样留着（用户在 Obsidian 里加的）
        groups: list[list[str]] = []
        for line in m.group(1).split("\n"):
            # 空行跟着上一个属性走（`summary: |` 这种多段文字中间的空行），写回时原样还给用户
            if groups and (not line.strip() or line[:1] in (" ", "\t") or line.startswith("- ") or line == "-"):
                groups[-1].append(line)
            elif line.strip():
                groups.append([line])
        for g in groups:
            while len(g) > 1 and not g[-1].strip():
                g.pop()   # 属性之间的空行不算任何一个属性的内容
            mm = re.match(r"^([\w-]+):\s*(.*)$", g[0])
            if mm and mm.group(1) in FIELD_ORDER:
                items = [re.sub(r"^\s*-\s?", "", x).strip() for x in g[1:] if re.match(r"^\s*-", x)]
                if not mm.group(2).strip() and items:
                    meta[mm.group(1)] = [_scalar(x) if x.startswith('"') else x.strip("'") for x in items if x]
                else:
                    meta[mm.group(1)] = _scalar(mm.group(2))
            else:
                extra.extend(g)
    as_list = lambda v: [x for x in ([v] if isinstance(v, str) else (v or [])) if str(x).strip()]  # noqa: E731
    role = str(meta.get("role") or "page")
    return {
        "id": str(meta.get("id") or ""),
        "title": str(meta.get("title") or "").strip(),
        "role": role if role in ROLES else "page",
        "index_tag": _clean_tag(meta.get("index_tag")),
        "order": [str(x) for x in as_list(meta.get("order"))],
        "tags": [t for t in (_clean_tag(x) for x in as_list(meta.get("tags"))) if t],
        "created": str(meta.get("created") or ""),
        "updated": str(meta.get("updated") or ""),
        "body": body.lstrip("\n"),
        "extra": extra,
    }


def content_hash(text: str) -> str:
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:16]


# ── 扫描 ──
def _derived_id(rel: str) -> str:
    """没写 id 的页（Obsidian 里直接新建的）：按相对路径给一个稳定 id，第一次经这里保存时写进文件头。"""
    return "pf-" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]


def scan_dir(root: Path) -> dict[str, dict[str, Any]]:
    """id → {page, path, hash}。只看 PersonalWiki 顶层的 .md（.history / .trash 不算）。同一个 id 出现两次，后读到的那份换派生 id。"""
    out: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        page = parse_page(text)
        pid = page["id"]
        if not _valid_id(pid) or pid in out:
            pid = _derived_id(path.name)
            page["id"] = pid
            page["adopted"] = False
        if not page["title"]:
            page["title"] = path.stem
        out[pid] = {"page": page, "path": path, "hash": content_hash(text)}
    return out


# ── 派生（引用 / 标签 / 小标题 / 待办 / 首句） ──
def _strip_code(body: str) -> str:
    return FENCE_RE.sub(lambda m: re.sub(r"[^\n]", "", m.group(0)), body)


def _plain(s: str) -> str:
    s = WL_RE.sub(lambda m: m.group(2) or m.group(1), s)
    s = CITE_RE.sub(r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return re.sub(r"[*`]", "", s).strip()


def lead_of(body: str) -> str:
    """首句：第一段正文；页面以列表开头就取第一条列表项（和设计稿一致）。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", _strip_code(body)) if b.strip()]
    for b in blocks:
        if not re.match(r"^(#|>|[-*+]\s|\d+\.)", b):
            return _plain(b.split("\n")[0])[:80]
    for b in blocks:
        m = re.match(r"^\s*([-*+]|\d+\.)\s+(\[[ xX]\]\s+)?(.*)$", b.split("\n")[0])
        if m:
            return _plain(m.group(3))[:80]
    return ""


def derive(page: dict[str, Any]) -> dict[str, Any]:
    b = _strip_code(page.get("body") or "")
    cites = list(dict.fromkeys(m.group(2) for m in CITE_RE.finditer(b)))
    inline = list(dict.fromkeys(t for t in TAG_RE.findall(b) if not t.isdigit()))
    heads, tasks = [], []
    for i, line in enumerate(b.split("\n")):
        h = HEAD_RE.match(line)
        if h:
            heads.append({"level": len(h.group(1)), "text": _plain(h.group(2)), "line": i})
        t = TASK_RE.match(line)
        if t:
            tasks.append({"done": t.group(1) != " ", "text": _plain(t.group(2)), "line": i})
    return {"cites": cites, "links": [m.group(1).strip() for m in WL_RE.finditer(b)],
            "all_tags": list(dict.fromkeys(list(page.get("tags") or []) + inline)),
            "heads": heads, "tasks": tasks, "open_tasks": sum(1 for t in tasks if not t["done"]),
            "lead": lead_of(page.get("body") or ""), "chars": len(re.sub(r"\s", "", page.get("body") or ""))}
