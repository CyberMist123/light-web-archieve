"""LWA 专属 MCP 的**唯一一份**工具定义：本机 stdio（`python -m link_brain mcp`）和远程（`remote serve`）共用。

两个入口只管协议（stdio 的 JSON-RPC / 远程的 OAuth + Streamable HTTP），工具是什么、参数怎么校验、
返回什么，全在这里；换句话说「本机能做的，远程也能做；远程拒的路径，本机也拒」。

工具（名字 → 做什么）：
- search    搜收藏（关键词 + 语义 + 扩词缓存，和问收藏同一个召回核心）：标题 · 作者 · 一句概要 · 日期 · 类型 · id · agent.md 路径
            + 命中原文段 hits（来源类型 / 说话人 / 图号楼号）；可按作者 / 收藏时间 / 类型过滤；
            每次搜索（第一页）追加一行到 `_archive/search-history.md`（按日期分节）。
- ask       问收藏：检索后调已配置的文本模型作答，**会花模型钱**。
- read      按 id 读一篇：默认机读版（概要 / 原文 / 图片 OCR / 视频文字稿 / 评论 + 附件全文），
            头部给本地 raw 包路径和文件清单、可选 part 只取一段。
- image     看一篇里的一张原图（read 结果 images 给的路径）。
- files     列 / 读开放的文件夹（白名单：设置 remote.folders；路径越界一律拒）。
- topics    星标主题：list / get / create / update / delete。
- selections 暗号（选集）：list / get / save。get 认「最新」、编号「2」、多个「3,4,5」/「345」、名字。
- recent    最近新增（标题 · 概要 · 日期）+ 最近几次同步记录。
- history   搜索历史 md 的尾部。
- index     索引树（10-10）：无参数 = 整棵树带篇数；带节点路径 = 这个节点的笔记（id · 标题 · 日期 · 一句概要）；
            `unclassified` = 未归类。读 `_archive/index-data.json`（和 索引.md 对不上就当场重算，解析 / 归类只在 indextree）。
- wiki      节点 wiki：无参数列出有哪些（已生成 / 标了还没生成）；带节点路径读全文（分页）。
- guide     收藏深度报告的方法（docs/deep-report.md）：GPT 要自己写某个节点的汇总时先取它；带 skill = 取某个问答技能。
- skills    问收藏的技能（1015 第二批）：list 列出 / get 取正文（写法要求，只读）。

上下文 `Ctx`：policy（路径白名单，见 remote/policy.py）、local（本机 stdio 给绝对路径，远程给 vault 相对路径）、
who（谁在调，进搜索历史）。返回值是可 JSON 化的 dict；拒绝抛 `policy.Denied`；带图的结果另有私有键
`_images: [{"data": bytes, "mime": str}]`，两个入口各自翻成图片块。

写操作（topics / selections / 搜索历史）一律「进程内线程锁 + storage.file_lock 跨进程锁 + 原子写」，
不和插件 / 夜跑 / 另一个入口并发写坏文件。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import storage
from .remote.policy import XHS_ARCHIVE, Denied, Policy, MAX_READ_BYTES

HISTORY_FILE = "search-history.md"
HISTORY_TOP = 3            # 搜索历史每条记前几个命中标题
HISTORY_TAIL_DEFAULT = 60
HISTORY_TAIL_MAX = 500
SEARCH_DEFAULT = 15        # 1015 第二批：十几个合适来源都列一行防漏（E 节）
SEARCH_MAX = 40
SEARCH_HITS = 3            # 每篇最多几段命中原文
SEARCH_HIT_CHARS = 240
READ_DEFAULT = 30000
READ_MAX = 100000
RAW_FILES_MAX = 200
RECENT_DAYS = 7
RECENT_LIMIT = 20
LOCK_WAIT = 15

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_GUARD = threading.Lock()


@dataclass
class Ctx:
    policy: Policy
    local: bool = True
    who: str = "本机"


# ---------------------------------------------------------------- 小工具

def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _str(args: dict[str, Any], key: str, *, required: bool = False, limit: int = 500) -> str:
    v = args.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise Denied("INVALID_ARGUMENT", f"{key} 不能为空")
        return ""
    if not isinstance(v, (str, int)):
        raise Denied("INVALID_ARGUMENT", f"{key} 要是文字")
    return str(v).strip()[:limit]


def _str_list(value: Any, key: str) -> list[str]:
    """数组或逗号分隔的字符串都收。"""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [x for x in re.split(r"[,，、\n]+", value)]
    if not isinstance(value, list) or not all(isinstance(x, (str, int)) for x in value):
        raise Denied("INVALID_ARGUMENT", f"{key} 要是文字数组")
    return [str(x).strip() for x in value if str(x).strip()]


@contextmanager
def write_guard(name: str):
    """写临界区：同进程多线程（远程服务）用线程锁，跨进程（插件 / 夜跑 / 另一个入口）用 storage.file_lock。
    file_lock 同进程可重入，挡不住同进程的两个线程，所以两层都要。"""
    with _THREAD_GUARD:
        lock = _THREAD_LOCKS.setdefault(name, threading.Lock())
    if not lock.acquire(timeout=LOCK_WAIT):
        raise Denied("BUSY", "另一个写入正在进行，稍后再试")
    try:
        try:
            with storage.file_lock(name, wait_s=LOCK_WAIT, owner=f"mcp:{name}"):
                yield
        except storage.LockBusy:
            raise Denied("BUSY", "另一个程序正在写这个文件，稍后再试") from None
    finally:
        lock.release()


def _write_json(path: Path, payload: Any) -> None:
    storage.atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=1))


def _items() -> list[dict[str, Any]]:
    try:
        from .ask import load_items
        return [it for it in load_items() if isinstance(it, dict)]
    except Exception:  # noqa: BLE001 - 目录数据坏 = 空库，不拖垮
        return []


def _short_id(item_id: Any) -> str:
    return str(item_id or "").removeprefix("xhs-")


_URL_ID = re.compile(r"/(?:explore|discovery/item|item)/([0-9A-Za-z]{8,64})")


def find_item(ref: Any, items: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """id（带不带 xhs- 都行）或原文链接 → 目录里的那一篇。"""
    text = str(ref or "").strip()
    if not text:
        return None
    items = _items() if items is None else items
    m = _URL_ID.search(text)
    want = _short_id(m.group(1) if m else text)
    for it in items:
        if _short_id(it.get("id")) == want:
            return it
    return None


def _one_sentence(text: Any, limit: int = 80) -> str:
    s = " ".join(str(text or "").split())
    m = re.search(r"[。！？!?；;]|\.(\s|$)", s)
    if m and m.end() <= limit:
        return s[:m.end()].strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def _abs(ctx: Ctx, rel: str | None) -> str | None:
    if not rel:
        return None
    if not ctx.local:
        return rel
    try:
        return str(ctx.policy.abspath(rel))
    except Denied:
        return rel


def _to_rel(ctx: Ctx, path: str) -> str:
    """本机允许写绝对路径（必须在 vault 里），统一换成 vault 相对路径再过白名单。远程只收相对路径。"""
    if ctx.local and path and (os.path.isabs(path) or re.match(r"^[A-Za-z]:", path)):
        rel = ctx.policy.rel_for_abs(path)
        if rel is None:
            raise Denied("NOT_SHARED", "不在 vault 或开放的库外文件夹里")
        return rel
    return path


# ---------------------------------------------------------------- search + 搜索历史

def history_path() -> Path:
    return storage.archive_root() / HISTORY_FILE


def _clean_line(text: str, limit: int) -> str:
    return " ".join(str(text or "").replace("|", "/").split())[:limit]


def record_search(query: str, titles: list[str], found: int, who: str, *, now: datetime | None = None) -> None:
    """追加一行到搜索历史 md：按日期分节（`## 2026-10-09`），一行 = 时间 · 查询 · 来源 · 命中数 · 前几条标题。"""
    now = now or datetime.now().astimezone()
    day = now.strftime("%Y-%m-%d")
    line = (f"- {now:%H:%M} · {_clean_line(query, 120)} · {_clean_line(who, 40)} · 命中 {found}"
            + (("：" + "；".join(_clean_line(t, 40) for t in titles[:HISTORY_TOP])) if titles else "") + "\n")
    path = history_path()
    with write_guard("search-history"):
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = "# 搜索历史\n\nMCP 搜索（search 工具）每次的查询和前几条命中，按日期分节、新的在下面。\n"
        last = None
        for m in re.finditer(r"^## (\d{4}-\d{2}-\d{2})\s*$", text, re.M):
            last = m.group(1)
        if not text.endswith("\n"):
            text += "\n"
        if last != day:
            text += f"\n## {day}\n\n"
        storage.atomic_write_text(path, text + line)


def _search_filters(args: dict[str, Any]) -> dict[str, Any]:
    from .ask_intent import KINDS
    out: dict[str, Any] = {}
    author = _str(args, "author", limit=40)
    if author:
        out["author"] = author
    for key in ("since", "until"):
        v = _str(args, key, limit=10)
        if v:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise Denied("INVALID_ARGUMENT", f"{key} 要是 YYYY-MM-DD")
            out[key] = v
    kinds = _str_list(args.get("kinds"), "kinds")
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise Denied("INVALID_ARGUMENT", f"kinds 只能是 {'/'.join(KINDS)}：{'、'.join(bad)}")
    if kinds:
        out["kind"] = kinds
    return out


def _hits_for(cand: dict[str, Any]) -> list[dict[str, Any]]:
    from . import ask as ask_mod
    try:
        return [{k: (v[:SEARCH_HIT_CHARS] if k == "text" else v) for k, v in h.items()}
                for h in ask_mod.search_hits(cand["item"], cand.get("terms") or [], cand.get("sem"), SEARCH_HITS, SEARCH_HIT_CHARS)]
    except Exception as exc:  # noqa: BLE001 - 命中段只是加成，取不到照样列这一篇
        print(f"[mcp] 命中段没取到：{type(exc).__name__}: {exc}", file=sys.stderr)
        return []


def search(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from .remote import tools as rtools
    from .ask_intent import item_kinds
    filters = _search_filters(args)
    query = _str(args, "query", required=not filters)
    limit = _int(args.get("limit"), SEARCH_DEFAULT, 1, SEARCH_MAX)
    offset = _int(args.get("offset"), 0, 0, 10 ** 6)
    detail = _str(args, "detail", limit=10) or "hits"
    if detail not in ("hits", "brief"):
        raise Denied("INVALID_ARGUMENT", "detail 只能是 hits 或 brief")
    pol = ctx.policy
    library = rtools._library_candidates(pol, query, filters) if pol.xhs else []
    # 带过滤条件时只搜收藏库（文件夹没有作者 / 收藏时间）
    folders = [] if filters or not query else rtools._search_folders(pol, query, rtools.SCAN_FILES_MAX, ("Web/Xiaohongshu",) if pol.xhs else ())
    total = len(library) + len(folders)
    rows: list[dict[str, Any]] = []
    pos = offset
    while len(rows) < limit and pos < total:
        if pos < len(library):
            cand = library[pos]
            it = cand["item"]
            agent = it.get("agent_md") if isinstance(it.get("agent_md"), str) and pol.allowed_file(it["agent_md"]) else None
            row = {"id": _short_id(it.get("id")), "title": it.get("title") or "", "author": it.get("author") or "",
                   "summary": _one_sentence(it.get("summary")), "date": it.get("date") or "",
                   "kinds": item_kinds(it), "score": round(float(cand.get("score") or 0), 4), "agent_md": _abs(ctx, agent)}
            if detail == "hits":
                row["hits"] = _hits_for(cand)
            rows.append(row)
        else:
            f = folders[pos - len(library)]
            rows.append({"title": f["title"], "path": _abs(ctx, f["path"])})
        pos += 1
    if offset == 0:
        try:
            record_search(query or ("过滤：" + json.dumps(filters, ensure_ascii=False)), [r["title"] for r in rows], total, ctx.who)
        except Exception as exc:  # noqa: BLE001 - 历史只是记录，写不上不影响搜索
            print(f"[mcp] 搜索历史没写上：{type(exc).__name__}: {exc}", file=sys.stderr)
    return {"found": total, "offset": offset, "next_offset": pos if pos < total else None, "results": rows,
            **({"filters": filters} if filters else {})}


# ---------------------------------------------------------------- ask

def ask(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import ask as ask_mod
    if not ctx.policy.xhs:
        raise Denied("NOT_OPEN", "收藏库没有开放给你")
    question = _str(args, "question", required=True, limit=2000)
    return ask_mod.answer(question)


# ---------------------------------------------------------------- read

_SECTION = re.compile(r"^## +(.+?)\s*$", re.M)


def split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(# 标题那段, [(小节名, 小节全文含标题行)])。"""
    marks = list(_SECTION.finditer(text))
    if not marks:
        return text, []
    head = text[:marks[0].start()]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), text[m.start():end]))
    return head, out


def _object_files(obj: Path) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(obj):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, fn), obj).replace("\\", "/"))
            if len(out) >= RAW_FILES_MAX:
                return out
    return out


def read(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from .remote import tools as rtools
    if args.get("id") in (None, "") and isinstance(args.get("path"), str):
        return rtools.read(ctx.policy, {**args, "path": _to_rel(ctx, args["path"])})   # 旧客户端：read(path) = 读文件
    ref = _str(args, "id", required=True, limit=300)
    pol = ctx.policy
    if not pol.xhs:
        raise Denied("NOT_OPEN", "收藏库没有开放给你")
    it = find_item(ref)
    if not it:
        raise Denied("NOT_FOUND", f"没有这篇：{ref}（id 用 search / recent / selections 给出的）")
    agent = it.get("agent_md") if isinstance(it.get("agent_md"), str) else None
    if not agent:
        raise Denied("NOT_FOUND", "这篇还没有机读版（agent.md），等下次同步渲染")
    target = pol.resolve_file(agent)
    if os.path.getsize(target) > MAX_READ_BYTES:
        raise Denied("TOO_LARGE", "机读版太大，不提供")
    text = target.read_bytes().decode("utf-8", errors="replace")
    _, atts = rtools._archive_paths(it)
    for a in atts:
        if not pol.allowed_file(a):
            continue
        try:
            body = pol.resolve_file(a).read_bytes().decode("utf-8", errors="replace")
        except (Denied, OSError):
            continue
        text = text.rstrip("\n") + f"\n\n## 附件全文：{a.rsplit('/', 1)[-1]}\n\n" + body.strip() + "\n"
    head, sections = split_sections(text)
    part = _str(args, "part", limit=60)
    if part:
        key = part.casefold().lstrip("#").strip()
        hits = [s for s in sections if s[0].casefold() == key] or [s for s in sections if key in s[0].casefold()]
        if not hits:
            raise Denied("NOT_FOUND", f"没有「{part}」这一段；有：{'、'.join(s[0] for s in sections)}")
        text = "".join(s[1] for s in hits)
    offset = _int(args.get("offset"), 0, 0, len(text))
    limit = _int(args.get("max_chars"), READ_DEFAULT, 1, READ_MAX)
    chunk = text[offset:offset + limit]
    end = offset + len(chunk)
    sid = _short_id(it.get("id"))
    obj = pol.root.joinpath(*XHS_ARCHIVE.split("/"), sid)
    out: dict[str, Any] = {
        "id": sid, "title": it.get("title") or "", "date": it.get("date") or "", "source_url": it.get("url"),
        "agent_md": _abs(ctx, agent), "note": _abs(ctx, it.get("note") if isinstance(it.get("note"), str) else None),
        "raw_dir": str(obj), "raw_files": _object_files(obj) if obj.is_dir() else [],
        "parts": [s[0] for s in sections], "part": part or None,
        "total_chars": len(text), "offset": offset, "next_offset": end if end < len(text) else None, "text": chunk}
    images = rtools.image_list(pol, agent)
    if images:
        out["images"] = images
    return out


def image(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from .remote import tools as rtools
    p = args.get("path")
    return rtools.read_asset(ctx.policy, {"path": _to_rel(ctx, p) if isinstance(p, str) else p})


# ---------------------------------------------------------------- files

def files(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from .remote import tools as rtools
    raw = args.get("path")
    path = _to_rel(ctx, raw.strip() if isinstance(raw, str) else "")
    pol = ctx.policy
    is_file = False
    if path:
        try:
            pol.resolve_dir(path)
        except Denied:
            is_file = True
    if is_file:
        out = rtools.read(pol, {**args, "path": path})
        out["kind"] = "file"
    else:
        out = rtools.list_dir(pol, {"path": path, "offset": args.get("offset"), "limit": args.get("limit")})
        out["kind"] = "dir"
        if ctx.local:
            out["vault"] = str(pol.root)
    return out


# ---------------------------------------------------------------- topics

def _live_hits(t: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """当场按这个主题重算命中（和目录重建同一个 topics.memberships：词法 + 本地向量库，不调外部接口）。算不了 → None。"""
    try:
        from . import topics as tmod
        member = tmod.memberships(items, [t])
    except Exception:  # noqa: BLE001 - fail-open：退回目录里的旧结果
        return None
    return [it for it in items if t["name"] in member.get(str(it.get("id")), [])]


def _topics_stale() -> bool:
    """主题文件比目录数据新 = 目录里的命中还是改之前算的。"""
    from . import topics as tmod
    try:
        return tmod.topics_path().stat().st_mtime > (storage.archive_root() / "catalog-data.json").stat().st_mtime
    except OSError:
        return False


def _topic_public(t: dict[str, Any], items: list[dict[str, Any]], with_items: bool, live: bool = False) -> dict[str, Any]:
    by_id = {str(it.get("id")): it for it in items}
    srcs = []
    for s in t.get("sources") or []:
        it = by_id.get(s)
        srcs.append({"id": _short_id(s), "title": (it or {}).get("title") or "（已不在库里）"})
    hit = _live_hits(t, items) if live else None
    fresh = hit is not None
    if hit is None:
        hit = [it for it in items if t["name"] in (it.get("topics") or []) or str(it.get("id")) in (t.get("sources") or [])]
    out = {"id": t["id"], "name": t["name"], "keywords": t["keywords"], "sources": srcs, "count": len(hit),
           "created": t.get("created") or "", "count_fresh": fresh}
    if with_items:
        hit.sort(key=lambda it: str(it.get("ts") or it.get("date") or ""), reverse=True)
        out["items"] = [{"id": _short_id(it.get("id")), "title": it.get("title") or "", "date": it.get("date") or "",
                         "summary": _one_sentence(it.get("summary"))} for it in hit[:100]]
    return out


def rebuild_catalog_async() -> str:
    """主题改了：后台重算目录（命中篇目写在目录数据里），不让这次调用等它。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen([sys.executable, "-m", "link_brain", "catalog"], cwd=str(storage.repo_root()),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
        return "queued"
    except OSError as exc:
        return f"failed: {exc}"


def _resolve_sources(refs: list[str], items: list[dict[str, Any]]) -> list[str]:
    out, bad = [], []
    for r in refs:
        it = find_item(r, items)
        (out.append(str(it["id"])) if it else bad.append(r))
    if bad:
        raise Denied("NOT_FOUND", "这些 id 不在库里：" + "、".join(bad[:10]))
    return out


def topics(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import topics as tmod
    if not ctx.policy.xhs:
        raise Denied("NOT_OPEN", "收藏库没有开放给你")
    action = _str(args, "action") or "list"
    items = _items()
    if action == "list":
        stale = _topics_stale()
        out = {"topics": [_topic_public(t, items, False) for t in tmod.load()]}
        if stale:
            out["note"] = "主题刚改过、目录还在后台重建：这里的 count 可能是旧的；get 某个主题会当场重算"
        return out
    ref = _str(args, "topic", limit=60)
    if action == "get":
        t = tmod.find(tmod.load(), ref) if ref else None
        if not t:
            raise Denied("NOT_FOUND", f"没有这个主题：{ref}；有：{'、'.join(x['name'] for x in tmod.load())}")
        pub = _topic_public(t, items, True, live=True)
        return {"topic": pub, "note": "命中篇目是刚刚当场算的" if pub["count_fresh"]
                else "命中篇目按上次目录重建算（当场重算没成功）" + ("；目录正在后台重建" if _topics_stale() else "")}
    if action not in ("create", "update", "delete"):
        raise Denied("INVALID_ARGUMENT", "action 只能是 list / get / create / update / delete")
    with write_guard("topics"):
        current = tmod.load()
        if action == "create":
            name = tmod.clean_name(_str(args, "name", required=True, limit=200))
            if not name:
                raise Denied("INVALID_ARGUMENT", f"主题名要 1-{tmod.MAX_NAME_CHARS} 个字、不含换行")
            if tmod.find(current, name):
                raise Denied("EXISTS", f"已经有主题「{name}」了，要改用 action=update")
            given = _str_list(args.get("keywords"), "keywords")
            kw_from = "given"
            if not given:
                given, kw_from = (tmod.expand_keywords(name) or []), "model"
            topic = {"id": tmod._next_id(current), "name": name,
                     "keywords": tmod.clean_keywords(given, name=name, strict=False) or [name],
                     "sources": _resolve_sources(_str_list(args.get("add_sources"), "add_sources"), items),
                     "created": datetime.now().astimezone().isoformat(timespec="seconds")}
            tmod.save(current + [topic])
            result: dict[str, Any] = {"created": _topic_public(topic, items, False, live=True), "keywords_from": kw_from}
        else:
            t = tmod.find(current, ref)
            if not t:
                raise Denied("NOT_FOUND", f"没有这个主题：{ref}")
            if action == "delete":
                tmod.save([x for x in current if x["id"] != t["id"]])
                result = {"deleted": {"id": t["id"], "name": t["name"]}}
            else:
                new = dict(t)
                if _str(args, "new_name", limit=200):
                    nn = tmod.clean_name(_str(args, "new_name", limit=200))
                    if not nn:
                        raise Denied("INVALID_ARGUMENT", f"新名字要 1-{tmod.MAX_NAME_CHARS} 个字")
                    clash = tmod.find(current, nn)
                    if clash and clash["id"] != t["id"]:
                        raise Denied("EXISTS", f"已有同名主题：{clash['name']}")
                    new["name"] = nn
                drop = {k.casefold() for k in _str_list(args.get("remove_keywords"), "remove_keywords")}
                kws = [k for k in new["keywords"] if k.casefold() not in drop]
                kws += _str_list(args.get("add_keywords"), "add_keywords")
                new["keywords"] = tmod.clean_keywords(kws, strict=False) or [new["name"]]
                srcs = list(new.get("sources") or [])
                drop_src = set(_resolve_sources(_str_list(args.get("remove_sources"), "remove_sources"), items)) \
                    if args.get("remove_sources") else set()
                srcs = [s for s in srcs if s not in drop_src and _short_id(s) not in {_short_id(d) for d in drop_src}]
                for s in _resolve_sources(_str_list(args.get("add_sources"), "add_sources"), items):
                    if s not in srcs:
                        srcs.append(s)
                new["sources"] = srcs
                if new == t:
                    raise Denied("INVALID_ARGUMENT", "没有要改的：给 new_name / add_keywords / remove_keywords / add_sources / remove_sources")
                tmod.save([new if x["id"] == t["id"] else x for x in current])
                result = {"updated": _topic_public(new, items, False, live=True)}
    result["catalog"] = rebuild_catalog_async()
    result["note"] = ("这个主题的命中数是刚刚当场算的；目录页 / 其他主题的统计在后台重建，约一两分钟" if action != "delete"
                      else "已删除；目录在后台重建，约一两分钟")
    return result


# ---------------------------------------------------------------- selections（暗号）

def _parse_time(s: Any) -> datetime:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.astimezone()


def numbered_selections() -> list[dict[str, Any]]:
    """所有暗号，带编号（按创建时间从 1 编起，最早的是 1），新的在前。"""
    from . import selections as smod
    rows = smod.load()
    ordered = sorted(rows, key=lambda r: _parse_time(r["created_at"]))
    for i, r in enumerate(ordered, 1):
        r["no"] = i
    return sorted(ordered, key=lambda r: _parse_time(r["created_at"]), reverse=True)


_LATEST = {"latest", "最新", "最近", "最新的", "最近的", "上一个", "刚才", "刚存的", "last", "newest"}


def resolve_selection_ref(ref: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """暗号 → 选集列表。顺序：名字原样 → 最新 → 编号（精确优先；单数字编号 <10 时连写拆开）→ 宽松名字。
    返回 (命中, 候选名)。"""
    from . import selections as smod
    text = str(ref or "").strip()
    for r in rows:
        if r["name"] == text:
            return [r], []
    core = re.sub(r"^(暗号|选集|编号|第|#|no\.?)\s*", "", text, flags=re.I).strip()
    core = re.sub(r"\s*(号|个)$", "", core)
    if not rows:
        return [], []
    if core.casefold() in _LATEST or text.casefold() in _LATEST:
        return [rows[0]], []
    by_no = {r["no"]: r for r in rows}
    if re.fullmatch(r"\d+", core):
        if int(core) in by_no:                            # 有歧义时精确优先：「12」有 12 号就是 12 号
            return [by_no[int(core)]], []
        digits = [int(c) for c in core]
        if len(digits) > 1 and all(d in by_no and d < 10 for d in digits):
            return [by_no[d] for d in dict.fromkeys(digits)], []
        return [], []
    if re.fullmatch(r"\d+(\s*[,，、/\s]\s*\d+)+", core):
        nums = [int(x) for x in re.split(r"[,，、/\s]+", core) if x]
        missing = [n for n in nums if n not in by_no]
        if missing:
            return [], [f"没有编号 {', '.join(map(str, missing))}"]
        return [by_no[n] for n in dict.fromkeys(nums)], []
    hit, maybe = smod.find(core or text, rows)
    return ([hit] if hit else []), maybe


def _selection_rows(sel: dict[str, Any], ctx: Ctx, by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    from .remote import tools as rtools
    out, missing = [], []
    for i in sel["ids"]:
        it = by_id.get(i) or by_id.get("xhs-" + _short_id(i))
        if not it:
            missing.append(_short_id(i))
            continue
        agent, atts = rtools._archive_paths(it)
        note = it.get("note") if isinstance(it.get("note"), str) else None
        out.append({"id": _short_id(it.get("id")), "title": it.get("title") or "",
                    "agent_md": _abs(ctx, agent if agent and ctx.policy.allowed_file(agent) else None),
                    "note": _abs(ctx, note if note and ctx.policy.allowed_file(note) else None),
                    "source_url": it.get("url")})
    return out, missing


def _sel_summary(r: dict[str, Any]) -> dict[str, Any]:
    return {"no": r["no"], "name": r["name"], "count": len(r["ids"]), "created_at": r["created_at"]}


def selections(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import selections as smod
    if not ctx.policy.xhs:
        raise Denied("NOT_OPEN", "收藏库没有开放给你，暗号也读不到")
    action = _str(args, "action") or "list"
    if action == "list":
        rows = numbered_selections()
        limit = _int(args.get("limit"), 50, 1, 500)
        return {"count": len(rows), "selections": [_sel_summary(r) for r in rows[:limit]]}
    if action == "get":
        ref = _str(args, "ref", required=True, limit=200)
        rows = numbered_selections()
        hits, maybe = resolve_selection_ref(ref, rows)
        if not hits:
            raise Denied("NOT_FOUND", f"没有暗号「{ref}」" + (("；可能是：" + "、".join(maybe)) if maybe else "")
                         + "；现有：" + "、".join(f"{r['no']}.{r['name']}" for r in rows[:15]))
        by_id = {str(it.get("id")): it for it in _items()}
        groups = []
        for sel in hits:
            items, missing = _selection_rows(sel, ctx, by_id)
            g = {**_sel_summary(sel), "items": items}
            if missing:
                g["missing"] = missing
            groups.append(g)
        return {"selections": groups, "note": "用 read 按 id 读全文"}
    if action == "save":
        refs = _str_list(args.get("ids"), "ids")
        if not refs:
            raise Denied("INVALID_ARGUMENT", "ids 不能为空：给一组文章 id")
        items = _items()
        ids = list(dict.fromkeys(_resolve_sources(refs, items)))
        name = " ".join(_str(args, "name", limit=200).split())[:40]
        overwrite = args.get("overwrite") is True
        path = smod.path()
        with write_guard("selections"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                doc = {}
            except (OSError, ValueError):
                raise Denied("CORRUPT", "selections.json 读不了（坏了），先修好再存") from None
            if not isinstance(doc, dict):
                doc = {}
            raw_rows = [r for r in (doc.get("selections") or []) if isinstance(r, dict)] \
                if isinstance(doc.get("selections"), list) else []
            no = len(smod.load()) + 1
            if not name:
                taken = {str(r.get("name")) for r in raw_rows}
                name = f"暗号{no}"
                while name in taken:
                    no += 1
                    name = f"暗号{no}"
            if any(r.get("name") == name for r in raw_rows) and not overwrite:
                raise Denied("EXISTS", f"已经有暗号「{name}」了；要覆盖就带 overwrite=true，或换个名字")
            now = datetime.now(timezone.utc)
            row = {"name": name, "ids": ids, "created_at": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"}
            doc["selections"] = [row] + [r for r in raw_rows if r.get("name") != name]
            _write_json(path, doc)
        saved = next(r for r in numbered_selections() if r["name"] == name)
        return {"saved": _sel_summary(saved),
                "hint": f"以后说「暗号 {saved['no']}」或「{name}」就能取回"}
    raise Denied("INVALID_ARGUMENT", "action 只能是 list / get / save")


# ---------------------------------------------------------------- recent / history

def recent(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import synclog
    if not ctx.policy.xhs:
        raise Denied("NOT_OPEN", "收藏库没有开放给你")
    days = _int(args.get("days"), RECENT_DAYS, 1, 3650)
    limit = _int(args.get("limit"), RECENT_LIMIT, 1, 200)
    since = datetime.now().astimezone() - timedelta(days=days)
    rows = []
    for it in _items():
        ts = it.get("ts") or it.get("date")
        dt = _parse_time(ts)
        if dt >= since:
            rows.append((dt, it))
    rows.sort(key=lambda x: x[0], reverse=True)
    syncs = []
    try:
        for r in synclog.load(30):
            if _parse_time(r.get("started_at")) >= since:
                syncs.append(synclog.summary_line(r))
    except Exception:  # noqa: BLE001
        pass
    return {"days": days, "found": len(rows),
            "items": [{"id": _short_id(it.get("id")), "title": it.get("title") or "", "date": it.get("date") or "",
                       "summary": _one_sentence(it.get("summary"), 120)} for _, it in rows[:limit]],
            "syncs": syncs[:10]}


def history(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    n = _int(args.get("lines"), HISTORY_TAIL_DEFAULT, 1, HISTORY_TAIL_MAX)
    try:
        lines = history_path().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {"text": "", "total_lines": 0, "note": "还没有搜索历史"}
    tail = lines[-n:]
    # 尾部没带上日期标题时补一个，免得看不出是哪天
    if tail and not any(l.startswith("## ") for l in tail[:1]):
        for l in reversed(lines[:len(lines) - n]):
            if l.startswith("## "):
                tail = [l, "（…前面略…）"] + tail
                break
    return {"text": "\n".join(tail), "total_lines": len(lines), "path": _abs(ctx, f"_archive/{HISTORY_FILE}")}


# ---------------------------------------------------------------- index / wiki / guide（10-10 索引树）

INDEX_LIST_DEFAULT = 50
INDEX_LIST_MAX = 200
WIKI_READ_DEFAULT = 30000


def _compact(it: dict[str, Any]) -> dict[str, Any]:
    return {"id": _short_id(it.get("id")), "title": it.get("title") or "", "date": it.get("date") or "",
            "summary": _one_sentence(it.get("summary"))}


def index(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import indextree
    if not ctx.policy.xhs:
        raise Denied("NOT_OPEN", "收藏库没有开放给你")
    data = indextree.load()
    path = _str(args, "path", limit=300)
    wiki_rows = data.get("wiki") or {}
    if not path:
        nodes = [{"path": n.get("path"), "name": n.get("name"), "depth": n.get("depth"), "count": n.get("count"),
                  **({"wiki": True, "wiki_page": bool((wiki_rows.get(n.get("path")) or {}).get("exists"))} if n.get("wiki") else {})}
                 for n in data.get("nodes") or []]
        out = {"generated_at": data.get("generated_at"), "total": data.get("total"), "classified": data.get("classified"),
               "unclassified": (data.get("unclassified") or {}).get("count", 0), "nodes": nodes,
               "note": "path 给节点路径（如「美食/菜谱」）看这个节点的笔记；path='unclassified' 看未归类；"
                       "一篇可以在几个节点里，父节点的篇数含子节点"}
        if data.get("warnings"):
            out["warnings"] = [w.get("text") for w in data["warnings"] if isinstance(w, dict)][:20]
        return out
    limit = _int(args.get("limit"), INDEX_LIST_DEFAULT, 1, INDEX_LIST_MAX)
    offset = _int(args.get("offset"), 0, 0, 10 ** 6)
    if indextree.norm_path(path) in {indextree.norm_path(x) for x in indextree.UNCLASSIFIED_REFS}:
        ids, head = list((data.get("unclassified") or {}).get("items") or []), {"path": indextree.UNCLASSIFIED}
    else:
        node, near = indextree.find_node(data, path)
        if node is None:
            raise Denied("NOT_FOUND", f"索引里没有「{path}」" + (f"；是不是：{'、'.join(near[:8])}" if near else "")
                         + "（不带 path 调用看整棵树）")
        ids = list(node.get("items") or [])
        by_path = {n.get("path"): n for n in data.get("nodes") or []}
        head = {"path": node["path"], "tags": node.get("tags") or [], "wiki": bool(node.get("wiki")),
                "children": [{"path": c, "count": (by_path.get(c) or {}).get("count", 0)} for c in node.get("children") or []]}
        if node.get("wiki"):
            head["wiki_page"] = bool((wiki_rows.get(node["path"]) or {}).get("exists"))
    by_id = {str(it.get("id")): it for it in _items()}
    page = [by_id[i] for i in ids[offset:offset + limit] if i in by_id]
    end = offset + limit
    return {**head, "count": len(ids), "offset": offset, "next_offset": end if end < len(ids) else None,
            "items": [_compact(it) for it in page], "note": "要看全文用 read(id)"}


def wiki(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import wiki as wiki_mod
    if not ctx.policy.xhs:
        raise Denied("NOT_OPEN", "收藏库没有开放给你")
    path = _str(args, "path", limit=300)
    if not path:
        rows = wiki_mod.pages()
        return {"pages": [{**r, "file": _abs(ctx, r.get("file")) if r.get("exists") else None} for r in rows],
                "note": "path 给节点路径读全文；标了 wiki 还没生成的，可以照 guide 的方法用 index + read 自己整理"}
    row, text, cands = wiki_mod.read_page(path)
    if row is None:
        raise Denied("NOT_FOUND", f"没有「{path}」的 wiki" + (f"；有：{'、'.join(cands[:10])}" if cands else ""))
    if text is None:
        return {"path": row["path"], "exists": False,
                "note": "这个节点标了 wiki，还没生成：可以照 guide 的方法，用 index(path) 拿篇目、read 逐篇读，自己写一份"}
    offset = _int(args.get("offset"), 0, 0, len(text))
    limit = _int(args.get("max_chars"), WIKI_READ_DEFAULT, 1, READ_MAX)
    chunk = text[offset:offset + limit]
    end = offset + len(chunk)
    return {"path": row["path"], "exists": True, "file": _abs(ctx, row.get("file")), "based": row.get("based"),
            "new_since": row.get("new_since"), "generated_at": row.get("generated_at"), "total_chars": len(text),
            "offset": offset, "next_offset": end if end < len(text) else None, "text": chunk}


def skills(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    """问收藏的技能（1015 第二批）：list = 有哪些（id · 名字 · 一句说明 · 内置 / 用户）；get = 某个技能的正文（写法要求）。只读。"""
    from . import skills as skills_mod
    action = _str(args, "action", limit=10) or "list"
    if action == "list":
        rows = skills_mod.list_skills()["skills"]
        return {"skills": [{k: r.get(k) for k in ("id", "title", "description", "source", "ok", "error") if r.get(k) is not None}
                           for r in rows],
                "how": "回答某类问题前用 skills(action='get', id=…) 取那个技能的写法要求，照它组织；收藏内容用 search / read 取。"}
    if action == "get":
        sid = _str(args, "id", required=True, limit=40)
        s = skills_mod.get(sid)
        if not s:
            raise Denied("NOT_FOUND", f"没有这个技能：{sid}（先 skills(action='list')）")
        return {"id": s["id"], "title": s.get("title"), "description": s["description"], "source": s.get("source"),
                "text": s.get("body") or ""}
    raise Denied("INVALID_ARGUMENT", "action 只能是 list 或 get")


def guide(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    skill = _str(args, "skill", limit=40)
    if skill:
        return skills(ctx, {"action": "get", "id": skill})
    from . import wiki as wiki_mod
    text = wiki_mod.method_text()
    if text is None:
        raise Denied("NOT_FOUND", "方法文档（docs/deep-report.md）不在这个安装里")
    return {"name": "收藏深度报告 / 节点 wiki 的方法", "text": text,
            "how": "index 看树、index(path) 拿某个节点的篇目 → read 逐篇读（核心帖连评论区、图片文字一起读）→ 按方法写；"
                   "已经生成过的用 wiki(path) 先看"}


# ---------------------------------------------------------------- 工具表

def _ann(read_only: bool, *, open_world: bool = False, destructive: bool = False) -> dict[str, Any]:
    return {"readOnlyHint": read_only, "destructiveHint": destructive, "idempotentHint": read_only,
            "openWorldHint": open_world}


_ID_DESC = "文章 id（search / recent / selections 给出的；带不带 xhs- 都行，也可以直接贴原文链接）"

TOOLS: list[dict[str, Any]] = [
    {"name": "search",
     "description": ("搜我的收藏（小红书归档 + 开放的文件夹）：关键词或一句话都行，和「问收藏」同一套召回（词法 + 语义 + 扩词缓存），"
                     "不花模型钱。每条一行：id · 标题 · 作者 · 一句话概要 · 收藏日期 · kinds（video / attachment / pdf / image）· "
                     "hits（命中的原文段，每段标来源类型 type：body 正文 / ocr 图片文字 / comment_ocr 评论区图片 / comments 评论区（带 speaker 说话人）/ "
                     "transcript 视频文字稿 / screen 视频画面文字 / attachments 附件 / notes 她的批注 / highlights 她划的重点；"
                     "loc = 图N / 楼号 cN，图可以用 read 的 images 路径交给 image 看原图）· agent_md。"
                     "可按 author / since / until / kinds 过滤（只给过滤不给 query = 按收藏时间新→旧列出）。"
                     "默认一页 15 条，十几个来源都列一行防漏；found = 一共几条，next_offset 不为 null 时带 offset 续取。"
                     "要看全文用 read(id)。每次搜索会记进搜索历史。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "query": {"type": "string", "maxLength": 500, "description": "要找什么：关键词或一句话（有过滤条件时可以不给）"},
         "author": {"type": "string", "description": "只要这个作者（小红书昵称，原样）"},
         "since": {"type": "string", "description": "收藏日期从（YYYY-MM-DD）"},
         "until": {"type": "string", "description": "收藏日期到（YYYY-MM-DD）"},
         "kinds": {"type": "array", "items": {"type": "string", "enum": ["video", "attachment", "pdf", "image"]},
                   "description": "只要这些类型：video 视频 / attachment 带附件 / pdf 带 PDF 附件 / image 图文"},
         "detail": {"type": "string", "enum": ["hits", "brief"], "default": "hits",
                    "description": "hits = 每条带最多 3 段命中原文（默认）；brief = 只要标题和概要"},
         "limit": {"type": "integer", "minimum": 1, "maximum": SEARCH_MAX, "default": SEARCH_DEFAULT, "description": "这一页最多几条"},
         "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "从第几条开始（续取用上一页的 next_offset）"}}},
     "annotations": _ann(False)},
    {"name": "ask",
     "description": ("问收藏：先检索，再调用已配置的文本模型写一段带出处的回答。**每次都会花模型钱**；"
                     "只想找资料、自己组织答案时用 search + read，不要用它。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "question": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "自然语言问题"}},
         "required": ["question"]},
     "annotations": _ann(True, open_world=True)},
    {"name": "read",
     "description": ("按 id 读一篇收藏的机读版：概要 · 重要细节 · 原文 · 图片 OCR · 视频文字稿 / 画面文字 · 评论区 · 附件全文。"
                     "头部给 raw_dir（本机原始包目录）和 raw_files（包里的文件清单，原图 / 附件 / 抓取原始 JSON），"
                     "要翻原件照清单去找，不用一张张读。parts 是可选的段名，part='评论' 只取那一段。"
                     "长文分页：next_offset 不为 null 就带 offset 续读。图片文字只用来找，细节用 image 看原图。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "id": {"type": "string", "minLength": 1, "description": _ID_DESC},
         "part": {"type": "string", "description": "只取某一段：概要 / 重要细节 / 原文 / 图片 OCR / 视频文字稿 / 评论 / 附件全文 …（包含匹配）"},
         "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "从第几个字符开始"},
         "max_chars": {"type": "integer", "minimum": 1, "maximum": READ_MAX, "default": READ_DEFAULT, "description": "这一页最多多少字符"}},
         "required": ["id"]},
     "annotations": _ann(True)},
    {"name": "image",
     "description": ("看收藏里的一张原图（返回图片本身 + 尺寸）。path 用 read 结果 images 里给的原样路径；"
                     "大图会等比缩到长边 2048 再给。OCR 有错字时以原图为准。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "path": {"type": "string", "minLength": 1, "description": "图片路径（read 结果 images[].path）"}},
         "required": ["path"]},
     "annotations": _ann(True)},
    {"name": "files",
     "description": ("浏览开放给你的本地文件夹（Obsidian 库里设置开放的文件夹 + 收藏库）：path 留空列出开放的根；"
                     "给文件夹就列里面（分页）；给 .md / .txt 文件就读全文（分页）。只读；越界、隐藏目录、程序内部文件一律拒。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "path": {"type": "string", "description": "vault 内相对路径（/ 分隔，照列表给出的原样写）；留空 = 列根"},
         "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "分页起点（文件夹按项、文件按字符）"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "列文件夹时这一页最多几项"},
         "max_chars": {"type": "integer", "minimum": 1, "maximum": 100000, "description": "读文件时这一页最多多少字符"}}},
     "annotations": _ann(True)},
    {"name": "topics",
     "description": ("星标主题（目录页上那排主题 chip）。action=list 列全部；get 看一个主题的关键词、钉住的文章（sources）和命中文章；"
                     "create 新建（不给 keywords 时用文本模型扩 5-10 个关键词，花一点点模型钱）；"
                     "update 改名 / 加减关键词 / 加减钉住的文章；delete 删除。改完目录在后台重算命中。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "action": {"type": "string", "enum": ["list", "get", "create", "update", "delete"], "default": "list"},
         "topic": {"type": "string", "description": "get / update / delete：主题 id（t1）或名字"},
         "name": {"type": "string", "description": "create：主题名（≤30 字）"},
         "keywords": {"type": "array", "items": {"type": "string"}, "description": "create：关键词（不给就让模型扩）"},
         "new_name": {"type": "string", "description": "update：改成这个名字"},
         "add_keywords": {"type": "array", "items": {"type": "string"}, "description": "update：加这些关键词"},
         "remove_keywords": {"type": "array", "items": {"type": "string"}, "description": "update：去掉这些关键词"},
         "add_sources": {"type": "array", "items": {"type": "string"}, "description": "create / update：钉进这个主题的文章 id"},
         "remove_sources": {"type": "array", "items": {"type": "string"}, "description": "update：从这个主题拿掉的文章 id"}}},
     "annotations": _ann(False)},
    {"name": "selections",
     "description": ("暗号（选集）：她把几篇存成一组，给名字或编号，之后一句话取回。action=list 按日期倒序列出（编号 · 名字 · 篇数）；"
                     "get 取回每篇的标题和源文档路径——ref 可以是「最新」、编号「2」、多个「3,4,5」或连写「345」"
                     "（编号都小于 10 时拆成 3、4、5；正好有 345 号就取 345 号）、或名字；"
                     "save 把一组文章 id 存成新暗号（name 可选，不给就自动叫「暗号N」）。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "action": {"type": "string", "enum": ["list", "get", "save"], "default": "list"},
         "ref": {"type": "string", "description": "get：最新 / 编号 / 多个编号 / 名字"},
         "ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "description": "save：文章 id 列表"},
         "name": {"type": "string", "maxLength": 40, "description": "save：暗号名字（可选）"},
         "overwrite": {"type": "boolean", "default": False, "description": "save：同名时覆盖"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "list：最多几条"}}},
     "annotations": _ann(False)},
    {"name": "recent",
     "description": "同步记录：最近 days 天新进库的文章（标题 · 一句概要 · 日期，新的在前）和这几天每次同步的一行摘要。",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "days": {"type": "integer", "minimum": 1, "maximum": 3650, "default": RECENT_DAYS, "description": "看最近几天"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": RECENT_LIMIT, "description": "最多几篇"}}},
     "annotations": _ann(True)},
    {"name": "history",
     "description": "搜索历史（search-history.md）的最后几行：按日期分节，每行 = 时间 · 查询 · 谁搜的 · 命中数 · 前几条标题。",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "lines": {"type": "integer", "minimum": 1, "maximum": HISTORY_TAIL_MAX, "default": HISTORY_TAIL_DEFAULT,
                   "description": "要最后几行"}}},
     "annotations": _ann(True)},
    {"name": "index",
     "description": ("她的收藏「索引树」（她自己在库根 索引.md 里写的多级分类，一个节点按标签 / 名字收笔记）。"
                     "不带 path = 整棵树和每个节点的篇数（先看这个，知道收藏大概分布）；path=节点路径（如「美食/菜谱」，也可以只写唯一的名字）"
                     " = 这个节点的笔记：id · 标题 · 日期 · 一句概要（分页）；path='unclassified' = 哪个节点都没收的。"
                     "一篇可以在几个节点里，父节点含子节点。要看全文用 read(id)。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "path": {"type": "string", "description": "节点路径（/ 分隔）；'unclassified' = 未归类；不给 = 整棵树"},
         "limit": {"type": "integer", "minimum": 1, "maximum": INDEX_LIST_MAX, "default": INDEX_LIST_DEFAULT, "description": "这一页最多几篇"},
         "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "从第几篇开始（续取用 next_offset）"}}},
     "annotations": _ann(True)},
    {"name": "wiki",
     "description": ("节点 wiki：索引里标了 [wiki] 的节点，按 guide 的方法从这个节点的笔记里整理出的清单"
                     "（名字 · 链接 · 出自哪篇 · 帖里怎么说 · 借鉴，分类排好，顶部「先看这几个」）。"
                     "不带 path = 列出有哪些（已生成 / 标了还没生成，new_since = 生成之后这个节点又多了几篇）；"
                     "带 path = 读全文（分页）。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "path": {"type": "string", "description": "节点路径；不给 = 列出全部"},
         "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "从第几个字符开始"},
         "max_chars": {"type": "integer", "minimum": 1, "maximum": READ_MAX, "default": WIKI_READ_DEFAULT,
                       "description": "这一页最多多少字符"}}},
     "annotations": _ann(True)},
    {"name": "guide",
     "description": ("取「收藏深度报告 / 节点 wiki」的方法全文：她让你从收藏里整理一个主题（「我收藏里关于 X 有什么」"
                     "「给 X 做个汇总 / wiki」）时，先取这个照着做：广搜、通读核心帖、抽具体对象、每条写出处和借鉴、7 类左右。"
                     "带 skill = 取某个问答技能的写法要求（同 skills get）。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "skill": {"type": "string", "description": "可选：技能 id（skills list 给出的），取它的写法要求"}}},
     "annotations": _ann(True)},
    {"name": "skills",
     "description": ("问收藏的技能（写法要求）：action=list 列出有哪些（通用 / 菜谱 / wiki / 旅行攻略 / 调研对比 / 灵感陈列 + 她导入的）；"
                     "action=get + id 取正文。回答菜谱、攻略、汇总这类问题前先取对应技能，照它组织；内容从 search / read 拿。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "action": {"type": "string", "enum": ["list", "get"], "default": "list"},
         "id": {"type": "string", "description": "get：技能 id"}}},
     "annotations": _ann(True)},
]

HANDLERS: dict[str, Callable[[Ctx, dict[str, Any]], dict[str, Any]]] = {
    "search": search, "ask": ask, "read": read, "image": image, "files": files, "topics": topics,
    "selections": selections, "recent": recent, "history": history,
    "index": index, "wiki": wiki, "guide": guide, "skills": skills,
}
NAMES = [t["name"] for t in TOOLS]


# 旧名字（不在 tools/list 里，老客户端 / 老配置照样能调）
def _legacy_lb_search(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import retrieval
    q = _str(args, "query", required=True)
    return retrieval.search(q, _int(args.get("limit"), 20, 1, 200), _int(args.get("offset"), 0, 0, 10 ** 6))


def _legacy_lb_retrieve(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from . import retrieval
    q = _str(args, "question", required=True, limit=2000)
    return retrieval.retrieve_payload(q, _int(args.get("top_k"), 8, 1, 20), _int(args.get("offset"), 0, 0, 10 ** 6))


def _legacy_read_selection(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from .remote import tools as rtools
    return rtools.read_selection(ctx.policy, args)


def _legacy_lb_selections() -> dict[str, Any]:
    from . import selections as smod
    return smod.list_selections()


def _legacy_lb_selection(args: dict[str, Any]) -> dict[str, Any]:
    from . import selections as smod
    root = storage.vault_root()
    paths = lambda it: {"visible_note": str(root / it["note"]) if it.get("note") else None,  # noqa: E731
                        "agent_md": str(root / it["agent_md"]) if it.get("agent_md") else None}
    return smod.get_selection(args.get("name"), paths=paths, read_text=smod.read_agent)


LEGACY: dict[str, Callable[[Ctx, dict[str, Any]], dict[str, Any]]] = {
    "lb_search": _legacy_lb_search,
    "lb_retrieve": _legacy_lb_retrieve,
    "lb_ask": ask,
    "lb_selections": lambda ctx, a: _legacy_lb_selections(),
    "lb_selection": lambda ctx, a: _legacy_lb_selection(a),
    "list": lambda ctx, a: files(ctx, {**a, "path": a.get("path") or ""}),
    "read_asset": image,
    "read_selection": _legacy_read_selection,
}


def call(ctx: Ctx, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """按名字调一个工具。未知名字抛 KeyError；参数 / 路径问题抛 Denied。"""
    handler = HANDLERS.get(name) or LEGACY.get(name)
    if handler is None:
        raise KeyError(name)
    if not isinstance(args, dict):
        args = {}
    return handler(ctx, args)


def local_policy() -> Policy:
    """本机 stdio 的白名单：和远程同一份设置（data.json 的 remote.folders）；设置读不到就只开收藏库。"""
    from .remote import config as cfg_mod
    try:
        cfg, _ = cfg_mod.load()
        folders = cfg.get("folders") or [cfg_mod.XHS]
    except Exception:  # noqa: BLE001
        folders = [cfg_mod.XHS]
    return Policy.build(storage.vault_root(), folders)
