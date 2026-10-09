"""LWA 专属 MCP 的**唯一一份**工具定义：本机 stdio（`python -m link_brain mcp`）和远程（`remote serve`）共用。

两个入口只管协议（stdio 的 JSON-RPC / 远程的 OAuth + Streamable HTTP），工具是什么、参数怎么校验、
返回什么，全在这里；换句话说「本机能做的，远程也能做；远程拒的路径，本机也拒」。

工具（名字 → 做什么）：
- search    搜收藏（关键词 + 语义 + 扩词缓存，和问收藏同一个召回核心）：标题 · 一句概要 · 日期 · id · agent.md 路径；
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
SEARCH_DEFAULT = 10
SEARCH_MAX = 30
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
    return str(ctx.policy.root.joinpath(*rel.split("/"))) if ctx.local else rel


def _to_rel(ctx: Ctx, path: str) -> str:
    """本机允许写绝对路径（必须在 vault 里），统一换成 vault 相对路径再过白名单。远程只收相对路径。"""
    if ctx.local and path and (os.path.isabs(path) or re.match(r"^[A-Za-z]:", path)):
        root = os.path.normcase(str(ctx.policy.root))
        p = os.path.normcase(os.path.realpath(path))
        if p == root:
            return ""
        if not p.startswith(root + os.sep):
            raise Denied("NOT_SHARED", "不在 vault 里")
        return os.path.realpath(path)[len(str(ctx.policy.root)) + 1:].replace("\\", "/")
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


def search(ctx: Ctx, args: dict[str, Any]) -> dict[str, Any]:
    from .remote import tools as rtools
    query = _str(args, "query", required=True)
    limit = _int(args.get("limit"), SEARCH_DEFAULT, 1, SEARCH_MAX)
    offset = _int(args.get("offset"), 0, 0, 10 ** 6)
    pol = ctx.policy
    library = rtools._library_candidates(pol, query) if pol.xhs else []
    folders = rtools._search_folders(pol, query, rtools.SCAN_FILES_MAX, ("Web/Xiaohongshu",) if pol.xhs else ())
    total = len(library) + len(folders)
    rows: list[dict[str, Any]] = []
    pos = offset
    while len(rows) < limit and pos < total:
        if pos < len(library):
            it = library[pos]["item"]
            agent = it.get("agent_md") if isinstance(it.get("agent_md"), str) and pol.allowed_file(it["agent_md"]) else None
            rows.append({"id": _short_id(it.get("id")), "title": it.get("title") or "",
                         "summary": _one_sentence(it.get("summary")), "date": it.get("date") or "",
                         "agent_md": _abs(ctx, agent)})
        else:
            f = folders[pos - len(library)]
            rows.append({"title": f["title"], "path": _abs(ctx, f["path"])})
        pos += 1
    if offset == 0:
        try:
            record_search(query, [r["title"] for r in rows], total, ctx.who)
        except Exception as exc:  # noqa: BLE001 - 历史只是记录，写不上不影响搜索
            print(f"[mcp] 搜索历史没写上：{type(exc).__name__}: {exc}", file=sys.stderr)
    return {"found": total, "offset": offset, "next_offset": pos if pos < total else None, "results": rows}


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

def _topic_public(t: dict[str, Any], items: list[dict[str, Any]], with_items: bool) -> dict[str, Any]:
    by_id = {str(it.get("id")): it for it in items}
    srcs = []
    for s in t.get("sources") or []:
        it = by_id.get(s)
        srcs.append({"id": _short_id(s), "title": (it or {}).get("title") or "（已不在库里）"})
    hit = [it for it in items if t["name"] in (it.get("topics") or []) or str(it.get("id")) in (t.get("sources") or [])]
    out = {"id": t["id"], "name": t["name"], "keywords": t["keywords"], "sources": srcs, "count": len(hit),
           "created": t.get("created") or ""}
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
        return {"topics": [_topic_public(t, items, False) for t in tmod.load()]}
    ref = _str(args, "topic", limit=60)
    if action == "get":
        t = tmod.find(tmod.load(), ref) if ref else None
        if not t:
            raise Denied("NOT_FOUND", f"没有这个主题：{ref}；有：{'、'.join(x['name'] for x in tmod.load())}")
        return {"topic": _topic_public(t, items, True),
                "note": "命中篇目按上次目录重建算；改过主题后后台会重建，约一两分钟后更新"}
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
            result: dict[str, Any] = {"created": _topic_public(topic, items, False), "keywords_from": kw_from}
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
                result = {"updated": _topic_public(new, items, False)}
    result["catalog"] = rebuild_catalog_async()
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


# ---------------------------------------------------------------- 工具表

def _ann(read_only: bool, *, open_world: bool = False, destructive: bool = False) -> dict[str, Any]:
    return {"readOnlyHint": read_only, "destructiveHint": destructive, "idempotentHint": read_only,
            "openWorldHint": open_world}


_ID_DESC = "文章 id（search / recent / selections 给出的；带不带 xhs- 都行，也可以直接贴原文链接）"

TOOLS: list[dict[str, Any]] = [
    {"name": "search",
     "description": ("搜我的收藏（小红书归档 + 开放的文件夹）：关键词或一句话都行，和「问收藏」同一套召回（词法 + 语义 + 扩词缓存），"
                     "不花模型钱。每条返回 id · 标题 · 一句话概要 · 日期 · agent_md（机读版全文路径）；文件夹命中给 path。"
                     "要看全文用 read(id)。found = 一共几条，next_offset 不为 null 时带 offset 续取。每次搜索会记进搜索历史。"),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "query": {"type": "string", "minLength": 1, "maxLength": 500, "description": "要找什么：关键词或一句话"},
         "limit": {"type": "integer", "minimum": 1, "maximum": SEARCH_MAX, "default": SEARCH_DEFAULT, "description": "这一页最多几条"},
         "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "从第几条开始（续取用上一页的 next_offset）"}},
         "required": ["query"]},
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
]

HANDLERS: dict[str, Callable[[Ctx, dict[str, Any]], dict[str, Any]]] = {
    "search": search, "ask": ask, "read": read, "image": image, "files": files, "topics": topics,
    "selections": selections, "recent": recent, "history": history,
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
