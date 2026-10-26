"""1015 索引大纲树：目录页直接改树（她裁定 D：可折叠、拖拽调层级、改名、合并）→ 写回 索引.md。

只动那几行：改名只换名字那一段（标签、说明括号、[wiki]、注释原样）；移动 = 把整棵子树的行剪下来、按目标层级重排缩进、
插到目标位置（缩进单位 / 行首符号照抄文件里已有的写法）；合并 = 源节点的标签（只写名字的就用名字）补到目标节点后面、
子节点挪过去（同名的递归合并）、删掉源节点那几行。改完还是她手写的那种格式，Python 照旧能解析。

路径变了，按路径记的东西跟着改（不然她手动改过的归属 / AI 归好的篇会丢、还会重新花钱判）：
index-overrides.json（手动归属、留着的空节点）· index-ai.json（每篇归进哪些路径、节点签名、细分结果）。
每一步都能撤销：写之前的 索引.md 原文 + 两份 json 存进 `_archive/index-edit-undo.json`（留最近 10 步）；
撤销时 索引.md 已经又被改过（她在编辑器里接着写了）就不撤，免得把她新写的冲掉。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import indexai, storage
from . import indextree as it
from .indextree import (MAX_DEPTH, SEP, Node, _BULLET, _COLON, _content_span, _line_body, _split_keep, _split_out,
                        _unit, blank_comments, clean_name, edit_add_tags, indent_of, key, node_name_for_write, parse,
                        split_desc)

UNDO_NAME = "index-edit-undo.json"
UNDO_KEEP = 10
ARGS = "PERMANENT.STEP_ARGS"


class EditError(ValueError):
    """改不了（说给她听的一句话）。"""


# ═══════════════════════════════════════════════════════════════════════════
# 纯文本改写（不碰磁盘，测试直接调）
# ═══════════════════════════════════════════════════════════════════════════

def _find(text: str, path: str) -> tuple[it.Parsed, Node]:
    parsed = parse(text)
    node = parsed.find(path)
    if node is None:
        raise EditError(f"索引里没有「{path}」（可能刚改过，刷新一下）")
    return parsed, node


def _solo(text: str, path: str) -> tuple[str, it.Parsed, Node]:
    """节点在「A, B, C」那种一行里：先拆到单独一行（_split_out 只动那一段）。重复写了几处的每一处都拆。"""
    for _ in range(20):
        parsed, node = _find(text, path)
        multi = next((ln for ln in node.lines if ln in parsed.lines and len(parsed.lines[ln].nodes) > 1
                      and node in parsed.lines[ln].nodes), None)
        if multi is None:
            return text, parsed, node
        if node.children and parsed.lines[multi].nodes[-1] is node:
            # 一行最后一个、下面挂着子节点：拆出去以后子节点要跟着它——_split_out 会把它放在原行后面，正好
            pass
        new = _split_out(text, _Probe(node, multi))
        if new == text:
            raise EditError(f"第 {multi} 行写法太复杂，没能自动改「{node.name}」：请在 索引.md 里手动拆成一行一个")
        text = new
    raise EditError(f"「{path}」写了太多处，请在 索引.md 里手动整理")


class _Probe:
    """_split_out 只看 name 和 line：同名节点写了几处时指定要拆哪一行。"""

    def __init__(self, node: Node, line: int):
        self.name, self.line = node.name, line


def _height(n: Node) -> int:
    return 1 + max((_height(c) for c in n.children), default=0)


def _subtree_lines(n: Node) -> list[int]:
    out = set(n.lines or [n.line])
    for c in n.children:
        out.update(_subtree_lines(c))
    return sorted(out)


def _is_under(path: str, maybe_parent: str) -> bool:
    a, b = it.norm_path(path), it.norm_path(maybe_parent)
    return bool(b) and (a == b or a.startswith(b + SEP))


def rename_text(text: str, path: str, new_name: str) -> str:
    """改名：只换名字那一段。只写了名字的节点原来是「按名字找」——老名字留作关键词（冒号后面），归进来的篇不变。"""
    name = node_name_for_write(new_name)
    if not name:
        raise EditError("名字是空的")
    text, parsed, node = _solo(text, path)
    sib = node.parent.children if node.parent is not None else parsed.roots
    if any(s is not node and key(s.name) == key(name) for s in sib):
        raise EditError(f"同一级已经有「{name}」了：要并在一起用「合并到…」")
    if key(name) == key(node.name):
        if name == node.name:
            return text
    old_name = node.name
    keep_old = not node.explicit and key(name) != key(old_name)
    blank = blank_comments(text)
    lines, blines = _split_keep(text), _split_keep(blank)
    for ln in sorted(set(node.lines)):
        info = parsed.lines.get(ln)
        if info is None or node not in info.nodes:
            continue                     # 第 4 级并进来的 / 占位行：不是它的名字行
        idx = ln - 1
        raw = lines[idx]
        body, end_nl = _line_body(raw), raw[len(_line_body(raw)):]
        bbody = _line_body(blines[idx])
        start, end = _content_span(bbody)
        cm = _COLON.search(bbody, start, end)
        name_end = cm.start() if cm else end
        seg = body[start:name_end]
        core, _desc = split_desc(seg)
        pos = seg.find(core) if core else -1
        if pos < 0 or clean_name(core) != old_name:
            # 名字带了 [[链接]] / ** 之类：整段名字（说明括号以外）换掉
            pos, core = 0, seg.rstrip()
            if _desc:
                core = seg[:seg.find("（") if "（" in seg else seg.find("(")].rstrip() or seg
        a = start + pos
        b = a + len(core)
        if keep_old:
            colon = it._colon_style(text)
            body = body[:a] + name + body[b:end] + colon + it.tag_text(old_name) + body[end:] if not cm else \
                body[:a] + name + body[b:cm.end()] + it.tag_text(old_name) + (", " if body[cm.end():end].strip() else "") + body[cm.end():]
        else:
            body = body[:a] + name + body[b:]
        lines[idx] = body + end_nl
    return "".join(lines)


def _cut(text: str, node: Node) -> tuple[str, list[str], int]:
    """把 node 整棵子树的行剪下来：(剩下的文本, 剪下的行（保留原顺序）, 子树里最浅那行的列宽)。"""
    drop = set(_subtree_lines(node))
    lines = _split_keep(text)
    nl = it._newline(text)
    cut = [ln if ln.endswith("\n") else ln + nl for i, ln in enumerate(lines, 1) if i in drop]
    rest = "".join(ln for i, ln in enumerate(lines, 1) if i not in drop)
    base = min(indent_of(ln)[0] for ln in cut) if cut else 0
    return rest, cut, base


def _reindent(cut: list[str], base_lead: str, unit: str) -> list[str]:
    """剪下来的行按相对层级重排缩进：最浅那一档 = base_lead，往里每一档加一个 unit。行首符号和正文原样。"""
    cols = sorted({indent_of(ln)[0] for ln in cut})
    rank = {c: i for i, c in enumerate(cols)}
    out = []
    for ln in cut:
        col, start = indent_of(ln)
        out.append(base_lead + unit * rank[col] + ln[start:])
    return out


def _bullet_style(parsed: it.Parsed) -> str:
    bl = [info.bullet for info in parsed.lines.values()]
    return max(set(bl), key=bl.count) if bl else ""


def _restyle_bullets(cut: list[str], bullet: str) -> list[str]:
    """剪下来的行跟着目标那边的行首符号（文件里混着「- 」和没有符号的时候，挪过去别显得突兀）。只换节点行，说明行不动。"""
    out = []
    for ln in cut:
        _, start = indent_of(ln)
        rest = ln[start:]
        m = _BULLET.match(rest)
        if m and m.group(0).strip() in {"-", "*", "+"} or (not m and bullet):
            rest = bullet + (rest[len(m.group(0)):] if m else rest)
        out.append(ln[:start] + rest)
    return out


def move_text(text: str, path: str, new_parent: str, before: str = "") -> str:
    """把 path 整棵子树挪到 new_parent 下面（空 = 第一级）；before = 插在这个兄弟节点前面（空 = 放最后）。"""
    text, parsed, node = _solo(text, path)
    if new_parent and _is_under(new_parent, path):
        raise EditError("不能挪进它自己下面")
    parent = parsed.find(new_parent) if new_parent else None
    if new_parent and parent is None:
        raise EditError(f"索引里没有「{new_parent}」")
    depth = (parent.depth if parent is not None else 0) + 1
    if depth + _height(node) - 1 > MAX_DEPTH:
        raise EditError(f"挪过去会超过 {MAX_DEPTH} 级（「{node.name}」下面还有 {_height(node) - 1} 级）：先把下面的挪出来，或换个地方")
    sib = parent.children if parent is not None else parsed.roots
    if any(s is not node and key(s.name) == key(node.name) for s in sib):
        raise EditError(f"那里已经有「{node.name}」了：要并在一起用「合并到…」")
    if before and it.norm_path(before) == it.norm_path(path):
        return text
    unit = _unit(text, parsed)
    bullet = _bullet_style(parsed)
    rest, cut, _ = _cut(text, node)
    if not rest.strip() and not cut:
        return text
    p2 = parse(rest)
    parent2 = p2.find(new_parent) if new_parent else None
    if new_parent and parent2 is None:
        raise EditError(f"索引里没有「{new_parent}」")
    if parent2 is not None:
        pinfo = p2.lines.get(parent2.line)
        if pinfo is not None and len(pinfo.nodes) > 1 and pinfo.nodes[-1] is not parent2:
            rest = _split_out(rest, parent2)
            p2 = parse(rest)
            parent2 = p2.find(new_parent)
    sib2 = parent2.children if parent2 is not None else p2.roots
    ref = next((s for s in sib2 if before and it.norm_path(s.path) == it.norm_path(
        (new_parent + SEP if new_parent else "") + before.split(SEP)[-1])), None) if before else None
    lines = _split_keep(rest)
    nl = it._newline(text)
    if ref is not None:
        rinfo = p2.lines.get(ref.line)
        lead = rinfo.lead if rinfo else ""
        at = min(ref.lines or [ref.line]) - 1           # 插在它第一行前面（0 起）
        bl = rinfo.bullet if rinfo else bullet
    else:
        if sib2:
            last = sib2[-1]
            linfo = p2.lines.get(last.line)
            lead, bl = (linfo.lead, linfo.bullet) if linfo else ("", bullet)
            at = it._subtree_last_line(last)
        elif parent2 is not None:
            pinfo = p2.lines.get(parent2.line)
            lead = (pinfo.lead if pinfo else "") + unit
            bl = pinfo.bullet if pinfo else bullet
            at = it._subtree_last_line(parent2)
        else:
            lead, bl, at = "", bullet, len(lines)
    if at - 1 >= 0 and at - 1 < len(lines) and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += nl
    moved = _restyle_bullets(_reindent(cut, lead, unit), bl)
    lines[at:at] = moved
    return "".join(lines)


def merge_text(text: str, src: str, dst: str) -> str:
    """把 src 并进 dst：src 的标签（只写名字的就用它的名字 + 第 4 级关键词）补到 dst 后面；src 的子节点挪到 dst 下面
    （dst 下面已有同名的就递归合并）；最后删掉 src 那几行。"""
    if it.norm_path(src) == it.norm_path(dst):
        raise EditError("不能并进它自己")
    if _is_under(dst, src):
        raise EditError("不能并进它自己下面的子类")
    text, parsed, s = _solo(text, src)
    d = parsed.find(dst)
    if d is None:
        raise EditError(f"索引里没有「{dst}」")
    if d.depth + _height(s) - 2 > MAX_DEPTH:
        raise EditError(f"并过去会超过 {MAX_DEPTH} 级：先把「{s.name}」下面的子类挪出来")
    tags = (list(s.tags) if s.explicit else [s.name]) + list(s.hints)
    tags = [t for t in tags if key(t) != key(d.name)]
    if tags:
        text = edit_add_tags(text, d.path, tags)
    # 子节点一个一个挪（同名的递归合并）
    for _ in range(200):
        parsed = parse(text)
        s = parsed.find(src)
        d = parsed.find(dst)
        if s is None or d is None:
            break
        if not s.children:
            break
        c = s.children[0]
        same = next((x for x in d.children if key(x.name) == key(c.name)), None)
        if same is not None:
            text = merge_text(text, c.path, same.path)
        else:
            text = move_text(text, c.path, d.path)
    text, parsed, s = _solo(text, src)
    if s.children:
        raise EditError(f"「{s.name}」下面的子类没挪完，没删它：请在 索引.md 里手动整理")
    rest, _cut_lines, _ = _cut(text, s)
    return rest


# ═══════════════════════════════════════════════════════════════════════════
# 路径变了：按路径记的东西跟着改
# ═══════════════════════════════════════════════════════════════════════════

def _remap_one(p: str, old: str, new: str) -> str:
    if p == old:
        return new
    if p.startswith(old + SEP):
        return new + p[len(old):]
    return p


def remap_paths(vault: Path, old: str, new: str, *, merged: bool = False) -> None:
    """old（及它下面的）路径 → new。merged=True：old 并进了已有的 new（重复的去掉）。"""
    if not old or old == new:
        return
    f = lambda p: _remap_one(p, old, new) if isinstance(p, str) else p  # noqa: E731
    dedup = lambda xs: list(dict.fromkeys(f(x) for x in xs))  # noqa: E731
    with storage.file_lock("index-overrides", wait_s=15, owner="index.edit"):
        ov = indexai.load_overrides(vault)
        for iid, row in list(ov["items"].items()):
            if not isinstance(row, dict):
                continue
            for k in ("only", "add", "remove"):
                if isinstance(row.get(k), list):
                    row[k] = dedup(row[k])
        ov["keep_empty"] = dedup(ov["keep_empty"])
        storage.write_json(indexai.overrides_path(vault), ov)
    with storage.file_lock(indexai.LOCK, wait_s=30, owner="index.edit"):
        cache = indexai.load_cache(vault)
        for row in cache["items"].values():
            if isinstance(row, dict) and isinstance(row.get("paths"), list):
                row["paths"] = dedup(row["paths"])
        for k in ("known", "splits"):
            tab = cache.get(k) or {}
            out: dict[str, Any] = {}
            for p, v in tab.items():
                q = f(p)
                if merged and q in out:
                    continue              # 并进去的那个：留目标自己的
                out[q] = v
            cache[k] = out
        indexai.save_cache(cache, vault)


def _resign(vault: Path, text: str, paths: list[str]) -> None:
    """改名 / 挪过的节点签名跟着换（签名含路径）：内容没变，别让它被当成新节点再花一遍钱。"""
    parsed = parse(text)
    with storage.file_lock(indexai.LOCK, wait_s=30, owner="index.edit"):
        cache = indexai.load_cache(vault)
        known = cache.get("known") or {}
        if not known:
            return
        for n in parsed.walk():
            if any(n.path == p or n.path.startswith(p + SEP) for p in paths) and n.path in known:
                known[n.path] = indexai.node_sig(n)
        cache["known"] = known
        indexai.save_cache(cache, vault)


# ═══════════════════════════════════════════════════════════════════════════
# 撤销
# ═══════════════════════════════════════════════════════════════════════════

def _undo_path(vault: Path) -> Path:
    return it.archive_dir(vault) / UNDO_NAME


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _read_bytes(p: Path) -> bytes | None:
    try:
        return p.read_bytes()
    except OSError:
        return None


def _push_undo(vault: Path, raw: bytes, new_bytes: bytes, ov: bytes | None, cache: bytes | None, what: str) -> str:
    uid = _sha((datetime.now().isoformat() + what).encode("utf-8"))[:8]
    try:
        log = json.loads(_undo_path(vault).read_text(encoding="utf-8"))
        log = log if isinstance(log, list) else []
    except (OSError, ValueError):
        log = []
    log.insert(0, {"id": uid, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "what": what,
                   "after": _sha(new_bytes), "index": raw.decode("utf-8", "surrogateescape"),
                   "bom": raw.startswith(it._BOM),
                   "overrides": ov.decode("utf-8") if ov is not None else None,
                   "cache": cache.decode("utf-8") if cache is not None else None})
    storage.write_json(_undo_path(vault), log[:UNDO_KEEP])
    return uid


def undo(uid: str, vault: Path | None = None) -> dict[str, Any]:
    vault = vault or storage.vault_root()
    try:
        log = json.loads(_undo_path(vault).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log = []
    rec = next((x for x in log if isinstance(x, dict) and x.get("id") == uid), None) if isinstance(log, list) else None
    if rec is None:
        return {"ok": False, "code": ARGS, "message": "撤销不了：这一步已经太早了"}
    with storage.file_lock(it.LOCK, wait_s=30, owner="index.edit-undo"):
        now = _read_bytes(it.index_path(vault))
        if now is None or _sha(now) != rec.get("after"):
            return {"ok": False, "code": ARGS, "message": f"{it.index_rel()} 之后又改过了，没敢撤（原文在 _archive/{it.HISTORY_DIR}/ 里）"}
        text = str(rec.get("index") or "")
        it.write_index(text, "undo", vault, old=now, bom=bool(rec.get("bom")))
        if rec.get("overrides") is not None:
            storage.atomic_write_bytes(indexai.overrides_path(vault), rec["overrides"].encode("utf-8"))
        if rec.get("cache") is not None:
            storage.atomic_write_bytes(indexai.cache_path(vault), rec["cache"].encode("utf-8"))
    storage.write_json(_undo_path(vault), [x for x in log if x is not rec])
    it.build(vault, force=True, auto_draft=False)
    return {"ok": True, "code": "", "message": "已撤销"}


# ═══════════════════════════════════════════════════════════════════════════
# 入口（CLI / 插件调）
# ═══════════════════════════════════════════════════════════════════════════

def edit(op: str, path: str, *, to: str = "", name: str = "", before: str = "", vault: Path | None = None) -> dict[str, Any]:
    """op：rename（name）/ move（to = 新的上级，空 = 第一级；before = 插在哪个兄弟前面）/ merge（to = 并进谁）/ undo（path = 撤销号）
    / add（1027 目录页编排「分类」模块：path = 上级，空 = 第一级；name = 新分类名；能撤销，和别的操作同一个写法 / 备份）。"""
    vault = vault or storage.vault_root()
    if op == "undo":
        return undo(path, vault)
    if op == "add":
        return _add(path, name, vault)
    if op not in {"rename", "move", "merge"}:
        return {"ok": False, "code": ARGS, "message": f"不认识的操作：{op}"}
    if not path:
        return {"ok": False, "code": ARGS, "message": "没说改哪个分类"}
    with storage.file_lock(it.LOCK, wait_s=30, owner="index.edit"):
        try:
            got = it.read_for_edit(it.index_path(vault))
        except it.NotUtf8:
            return {"ok": False, "code": ARGS, "message": f"{it.index_rel()} 不是 UTF-8 编码，没敢改它：在 Obsidian 里打开它存一下再试"}
        if got is None:
            return {"ok": False, "code": ARGS, "message": f"{it.index_rel()} 不在了，先刷新一次索引"}
        text, raw, bom = got
        parsed = parse(text)
        node = parsed.find(path)
        if node is None:
            return {"ok": False, "code": ARGS, "message": f"索引里没有「{path}」（可能刚改过，刷新一下）"}
        old_path = node.path
        try:
            if op == "rename":
                new_text = rename_text(text, old_path, name)
                new_name = node_name_for_write(name)
                new_path = (node.parent.path + SEP if node.parent is not None else "") + new_name.replace(SEP, "∕")
                msg = f"已把「{node.name}」改名为「{new_name}」"
            elif op == "move":
                new_text = move_text(text, old_path, to, before)
                tgt = parsed.find(to) if to else None
                new_path = ((tgt.path + SEP) if tgt is not None else "") + node.path.split(SEP)[-1]
                msg = f"已把「{node.name}」挪到" + (f"「{tgt.name}」下面" if tgt is not None else "第一级")
            else:
                tgt = parsed.find(to)
                if tgt is None:
                    return {"ok": False, "code": ARGS, "message": f"索引里没有「{to}」"}
                new_text = merge_text(text, old_path, tgt.path)
                new_path = tgt.path
                msg = f"已把「{node.name}」并进「{tgt.name}」"
        except EditError as exc:
            return {"ok": False, "code": ARGS, "message": str(exc)}
        except (KeyError, ValueError) as exc:
            return {"ok": False, "code": ARGS, "message": str(exc).strip("'\"") or "没改上"}
        if new_text == text:
            return {"ok": True, "code": "", "message": "没有要改的", "path": old_path, "unchanged": True}
        check = parse(new_text)
        if check.find(new_path) is None:
            return {"ok": False, "code": ARGS, "message": "改完对不上了，没写（请在 索引.md 里手动改）"}
        ov_raw = _read_bytes(indexai.overrides_path(vault))
        cache_raw = _read_bytes(indexai.cache_path(vault))
        it.write_index(new_text, op, vault, old=raw, bom=bom)
        new_bytes = (it._BOM if bom else b"") + new_text.encode("utf-8")
        uid = _push_undo(vault, raw, new_bytes, ov_raw, cache_raw, f"{op} {old_path}")
    if new_path != old_path:
        remap_paths(vault, old_path, new_path, merged=(op == "merge"))
    _resign(vault, new_text, [new_path])
    data = it.build(vault, force=True, auto_draft=False)
    return {"ok": True, "code": "", "message": msg, "path": new_path, "undo": uid,
            "unclassified": (data.get("unclassified") or {}).get("count", 0)}


def _add(parent: str, name: str, vault: Path) -> dict[str, Any]:
    """加一个分类（插在上级整棵子树最后；缩进 / 行首符号照抄 it.edit_new_node）。同名已在就不加。"""
    new_name = node_name_for_write(name or "")
    if not new_name:
        return {"ok": False, "code": ARGS, "message": "新分类要有名字"}
    with storage.file_lock(it.LOCK, wait_s=30, owner="index.edit"):
        try:
            got = it.read_for_edit(it.index_path(vault))
        except it.NotUtf8:
            return {"ok": False, "code": ARGS, "message": f"{it.index_rel()} 不是 UTF-8 编码，没敢改它：在 Obsidian 里打开它存一下再试"}
        if got is None:
            return {"ok": False, "code": ARGS, "message": f"{it.index_rel()} 不在了，先刷新一次索引"}
        text, raw, bom = got
        parsed = parse(text)
        up = parsed.find(parent) if parent else None
        if parent and up is None:
            return {"ok": False, "code": ARGS, "message": f"索引里没有「{parent}」（可能刚改过，刷新一下）"}
        if up is not None and _depth(up) >= MAX_DEPTH:
            return {"ok": False, "code": ARGS, "message": f"分类最多 {MAX_DEPTH} 级，「{up.name}」下面不能再加"}
        new_path = ((up.path + SEP) if up is not None else "") + new_name.replace(SEP, "∕")
        if parsed.find(new_path) is not None:
            return {"ok": True, "code": "", "message": f"「{new_name}」已经在了", "path": new_path, "unchanged": True}
        try:
            new_text = it.edit_new_node(text, up.path if up is not None else "", new_name)
        except (KeyError, ValueError) as exc:
            return {"ok": False, "code": ARGS, "message": str(exc).strip("'\"") or "没加上"}
        if parse(new_text).find(new_path) is None:
            return {"ok": False, "code": ARGS, "message": "加完对不上了，没写（请在 索引.md 里手动加）"}
        ov_raw = _read_bytes(indexai.overrides_path(vault))
        cache_raw = _read_bytes(indexai.cache_path(vault))
        it.write_index(new_text, "add", vault, old=raw, bom=bom)
        new_bytes = (it._BOM if bom else b"") + new_text.encode("utf-8")
        uid = _push_undo(vault, raw, new_bytes, ov_raw, cache_raw, f"add {new_path}")
    data = it.build(vault, force=True, auto_draft=False)
    where = f"「{up.name}」下面" if up is not None else "第一级"
    return {"ok": True, "code": "", "message": f"已在{where}加了分类「{new_name}」（还没有帖子：按内容归类或手动挪进来）", "path": new_path,
            "undo": uid, "unclassified": (data.get("unclassified") or {}).get("count", 0)}


def _depth(n: Node) -> int:
    d = 1
    while n.parent is not None:
        d += 1
        n = n.parent
    return d
