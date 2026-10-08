"""恢复这篇（批次 D · F1）：快照 → 按存档重写同一路径 → 可撤销；以及「改坏了没有」的检测 / 扫描。

- restore：不识图、不调模型、不联网（render_object llm=False，不走 render_item）。
- 她写的属性、留言、<mark> 重点都保留（seed_text）；批注在 notes.json，不碰。
- 钉死原路径：她删了 item_id 也不会另写 `__id8` 副本、不删原文件。
- CLI：stdout 只有最后一行 JSON，进度进 stderr，stderr 最后一行是人话。退出码 0 成功 / 1 失败（没动或已回滚）/ 2 认不出 / 没有可撤销的快照。
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from . import history, problems, storage
from . import render as render_mod
from .render import (COMMENTS_END, COMMENTS_START, CONTENT_END, CONTENT_START, FRONTMATTER_RE, MANAGED_FM_KEYS)

STEP = "render.check"
CODE = "PERMANENT.NOTE_DAMAGED"
ISSUE_ORDER = ("FRONTMATTER_BROKEN", "ITEM_ID_MISSING", "CSSCLASSES_MISSING", "CONTENT_MARKERS_MISSING",
               "NOTE_BLOCK_MISSING", "NOTE_BLOCK_SPLIT", "COMMENTS_MARKERS_MISSING", "ANNOTATE_BLOCK_MISSING")
ISSUE_TEXT = {
    "FRONTMATTER_BROKEN": "属性（frontmatter）写坏了",
    "ITEM_ID_MISSING": "属性里的 item_id 没了",
    "CSSCLASSES_MISSING": "属性里的 cssclasses 没了，两栏样式会丢",
    "CONTENT_MARKERS_MISSING": "正文的受管标记被删了",
    "NOTE_BLOCK_MISSING": "两栏正文块没了",
    "NOTE_BLOCK_SPLIT": "两栏正文块被换行拆开了",
    "COMMENTS_MARKERS_MISSING": "留言层的标记被删了",
    "ANNOTATE_BLOCK_MISSING": "底部的批注块没了",
}


class RestoreError(Exception):
    def __init__(self, message: str, exit_code: int = 1, code: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# 检测
# --------------------------------------------------------------------------

def _content_region(text: str) -> str | None:
    s, e = text.find(CONTENT_START), text.find(CONTENT_END)
    return text[s:e] if s != -1 and e > s else None


def diagnose(text: str | None) -> list[str]:
    """按固定顺序返回问题码；空列表 = 没坏。块外有手写不算坏（F1-c 处理）。"""
    text = text or ""
    out: list[str] = []
    if render_mod.frontmatter_broken(text):
        out.append("FRONTMATTER_BROKEN")
    if not render_mod.frontmatter_item_id(text):
        out.append("ITEM_ID_MISSING")
    cc = render_mod.parse_frontmatter(text).get("cssclasses")
    if isinstance(cc, str):
        cc = [x.strip() for x in cc.strip("[]").split(",")]
    if not isinstance(cc, list) or "xhs-note" not in [str(x).strip() for x in cc]:
        out.append("CSSCLASSES_MISSING")
    region = _content_region(text)
    if region is None:
        out.append("CONTENT_MARKERS_MISSING")
    lines = [ln for ln in (region if region is not None else text).split("\n") if ln.lstrip().startswith('<div class="lb-note')]
    if not lines:
        out.append("NOTE_BLOCK_MISSING")
    elif lines[0].count("<div") != lines[0].count("</div>"):
        out.append("NOTE_BLOCK_SPLIT")
    s, e = text.find(COMMENTS_START), text.find(COMMENTS_END)
    if s == -1 or e == -1 or e < s:
        out.append("COMMENTS_MARKERS_MISSING")
    if not any("annotate-view.js" in m.group(0) for m in render_mod._DVJS_RE.finditer(text)):
        out.append("ANNOTATE_BLOCK_MISSING")
    return out


def reason_text(issues: list[str]) -> str:
    return "；".join(ISSUE_TEXT.get(x, x) for x in issues)


# --------------------------------------------------------------------------
# seed：只在 restore 用，正常 render 不走它
# --------------------------------------------------------------------------

def _salvage_frontmatter(block: str) -> tuple[dict[str, Any], int]:
    groups: list[list[str]] = []
    unparsed = 0
    for line in block.splitlines():
        if line.strip() and not line[0].isspace() and not line.startswith(("-", "#")):
            groups.append([line])
        elif groups:
            groups[-1].append(line)
        elif line.strip() and not line.lstrip().startswith("#"):
            unparsed += 1
    out: dict[str, Any] = {}
    for g in groups:
        try:
            part = yaml.safe_load("\n".join(g))
        except yaml.YAMLError:
            part = None
        if isinstance(part, dict):
            out.update(part)
        else:
            unparsed += len([x for x in g if x.strip()])
    return out, unparsed


_COMMENT_HEAD = re.compile(r"^>\s*\[!link-brain-comment\]")
_META_LINE = re.compile(r"^<!--\s*link-brain:\s*id=")


def _comment_groups(text: str) -> tuple[list[list[str]], set[int]]:
    lines = text.split("\n")
    groups, used = [], set()
    i = 0
    while i < len(lines):
        if _COMMENT_HEAD.match(lines[i].strip()):
            g, j = [lines[i]], i + 1
            while j < len(lines) and lines[j].lstrip().startswith(">") and not _COMMENT_HEAD.match(lines[j].strip()):
                g.append(lines[j]); j += 1
            if j < len(lines) and _META_LINE.match(lines[j].strip()):
                g.append(lines[j]); j += 1
            groups.append(g)
            used.update(range(i, j))
            i = j
        else:
            i += 1
    return groups, used


def seed_text(text: str) -> tuple[str, dict[str, Any]]:
    kept: dict[str, Any] = {"frontmatter_keys": [], "tags_kept": False, "comments": 0, "highlights": 0,
                            "moved_lines": 0, "unparsed_frontmatter_lines": 0}
    parts: list[str] = []
    m = FRONTMATTER_RE.match(text)
    if m and not render_mod.frontmatter_broken(text):
        parts.append(m.group(0).rstrip("\r\n"))
        data = render_mod.parse_frontmatter(text)
        kept["frontmatter_keys"] = [k for k in data if k not in MANAGED_FM_KEYS]
        kept["tags_kept"] = "tags" in data
    elif m:
        data, unparsed = _salvage_frontmatter(m.group(1))
        keep = {k: v for k, v in data.items() if k not in MANAGED_FM_KEYS or k == "tags"}
        kept["frontmatter_keys"] = [k for k in keep if k != "tags"]
        kept["tags_kept"] = "tags" in keep
        kept["unparsed_frontmatter_lines"] = unparsed
        dumped = yaml.safe_dump(keep, allow_unicode=True, sort_keys=False, default_flow_style=False) if keep else ""
        parts.append("---\n" + dumped.rstrip("\n") + ("\n" if dumped else "") + "---")
    # 重点
    layer = render_mod.existing_content_layer(text)
    marks = render_mod.collect_highlights(layer if layer is not None else text)
    kept["highlights"] = len(marks)
    parts.append(CONTENT_START + "\n" + "\n".join(f"<mark>{html.escape(h, quote=False)}</mark>" for h in marks)
                 + ("\n" if marks else "") + CONTENT_END)
    # 留言层
    block, _ = render_mod.split_layers(text)
    without = text
    if block is not None:
        parts.append(block)
        kept["comments"] = sum(1 for ln in block.split("\n") if _COMMENT_HEAD.match(ln.strip()))
        s = text.find(COMMENTS_START); e = text.find(COMMENTS_END) + len(COMMENTS_END)
        without = text[:s] + text[e:]
    else:
        groups, used = _comment_groups(text)
        if groups:
            parts.append("\n".join([COMMENTS_START, *["\n".join(g) for g in groups], COMMENTS_END]))
            kept["comments"] = len(groups)
        without = "\n".join(ln for i, ln in enumerate(text.split("\n")) if i not in used)
    # 块外手写原样留着，render 会把它搬进留言层（F1-c）
    human, _ = render_mod.stray_human_lines(without)
    human = [ln for ln in human if ln.strip() not in (COMMENTS_START, COMMENTS_END, CONTENT_START, CONTENT_END)]
    kept["moved_lines"] = len(human)
    if human:
        parts.append("\n".join(human))
    return "\n\n".join(parts) + "\n", kept


# --------------------------------------------------------------------------
# 认这篇
# --------------------------------------------------------------------------

def _rel(p: Path) -> str:
    return str(p.relative_to(storage.vault_root())).replace("\\", "/")


def _check_path(path: str) -> Path:
    raw = str(path or "").replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or ".." in raw.split("/") or not raw.lower().endswith(".md"):
        raise RestoreError(f"路径不对：{path}（要收藏库里的相对路径、.md 结尾）", 2)
    p = (storage.vault_root() / raw).resolve()
    vis = storage.visible_dir().resolve()
    try:
        p.relative_to(vis)
    except ValueError:
        raise RestoreError(f"路径不在收藏笔记目录里：{path}", 2) from None
    return p


def _meta_scan() -> dict[str, dict[str, Any]]:
    out = {}
    root = storage.archive_root()
    if not root.is_dir():
        return out
    for mp in root.glob("*/*/meta.json"):
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("item_id"):
            out[meta["item_id"]] = meta
    return out


def _obj_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {"item_id": meta["item_id"], "source": meta["source"], "source_id": meta["source_id"],
            "visible_note": meta.get("visible_note"), "title": meta.get("title") or ""}


def resolve(target: str | None = None, path: str | None = None) -> tuple[dict[str, Any], Path]:
    """→ (对象, 可见笔记绝对路径)。认不出抛 RestoreError(exit 2)。两者都给时以 path 为写入目标。"""
    from . import note as note_mod
    p = _check_path(path) if path else None
    obj = None
    if target:
        try:
            obj = note_mod.resolve(target)
        except Exception:  # noqa: BLE001 - index 打不开就退回扫 meta
            obj = None
        if obj is None:
            meta = _meta_scan().get(target)
            obj = _obj_from_meta(meta) if meta else None
    if obj is None and p is not None:
        iid = None
        if p.is_file():
            try:
                iid = render_mod.frontmatter_item_id(p.read_text(encoding="utf-8"))
            except OSError:
                iid = None
        rel = _rel(p)
        if not iid:
            try:
                data = json.loads((storage.archive_root() / "catalog-data.json").read_text(encoding="utf-8"))
                iid = next((it.get("id") for it in data.get("items") or [] if it.get("note") == rel), None)
            except (OSError, ValueError):
                iid = None
        metas = _meta_scan()
        if iid and iid in metas:
            obj = _obj_from_meta(metas[iid])
        elif not iid:
            meta = next((m for m in metas.values() if m.get("visible_note") == rel), None)
            obj = _obj_from_meta(meta) if meta else None
    if obj is None:
        raise RestoreError("认不出这篇是哪条收藏（属性里的 item_id 和目录都对不上）", 2)
    if p is None:
        if not obj.get("visible_note"):
            raise RestoreError("这条收藏还没有可见笔记，先渲染一次", 2)
        p = storage.vault_root() / obj["visible_note"]
    return obj, p


# --------------------------------------------------------------------------
# 动作
# --------------------------------------------------------------------------

def _kept_message(title: str, kept: dict[str, Any]) -> str:
    bits = [f"保留了 {len(kept.get('frontmatter_keys') or [])} 个属性", f"{kept.get('comments', 0)} 条留言",
            f"{kept.get('highlights', 0)} 处重点"]
    msg = f"已按存档恢复「{title}」：" + "、".join(bits) + "；批注不受影响"
    if kept.get("moved_lines"):
        msg += f"；正文外手写的 {kept['moved_lines']} 行搬进了留言"
    if kept.get("unparsed_frontmatter_lines"):
        msg += f"；有 {kept['unparsed_frontmatter_lines']} 行属性读不出来，原文在快照里"
    return msg


def restore(target: str | None = None, path: str | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    obj, vis = resolve(target, path)
    od = storage.object_dir(obj["source"], obj["source_id"])
    title = obj.get("title") or vis.stem
    base = {"item_id": obj["item_id"], "path": _rel(vis), "snapshot": None, "kept": {}, "issues_before": []}
    text = vis.read_text(encoding="utf-8") if vis.is_file() else None
    issues_before = diagnose(text) if text is not None else ["FILE_MISSING"]
    base["issues_before"] = issues_before
    seed, kept = seed_text(text) if text is not None else (None, {})
    base["kept"] = kept
    if dry_run:
        return {"ok": True, "code": "", "message": f"（试跑）会按存档重写「{title}」", **base}
    if text is not None:
        _log("[restore] 存快照")
        base["snapshot"] = history.snapshot(od, text, "restore")
    _log("[restore] 按存档重写")

    def rollback(msg: str) -> dict[str, Any]:
        if text is not None:
            try:
                cur = vis.read_text(encoding="utf-8") if vis.is_file() else None
            except OSError:
                cur = None
            if cur != text:
                storage.atomic_write_text(vis, text)
        snap = f"（快照 {base['snapshot']}）" if base["snapshot"] else ""
        return {"ok": False, "code": CODE, "message": msg + snap, **base}

    try:
        render_mod.render_object(obj["source"], obj["source_id"], target=vis, existing_override=seed)
    except Exception as exc:  # noqa: BLE001 - 失败放回原样，如实说
        return rollback(f"按存档重写没成功（{type(exc).__name__}: {exc}），已放回原样")
    after = vis.read_text(encoding="utf-8") if vis.is_file() else ""
    left = diagnose(after)
    if left:
        return rollback(f"按存档重写后还是不对（{reason_text(left)}），已放回原样")
    try:
        problems.resolve(STEP, obj["item_id"])
    except Exception:  # noqa: BLE001 - 问题记录写不上不挡恢复
        pass
    msg = _kept_message(title, kept) if text is not None else "笔记文件不在了，已按存档重新生成"
    return {"ok": True, "code": "", "message": msg, **base}


def undo(target: str | None = None, path: str | None = None, *, snapshot: str | None = None) -> dict[str, Any]:
    obj, vis = resolve(target, path)
    od = storage.object_dir(obj["source"], obj["source_id"])
    name = snapshot or history.latest(od, "restore")
    if not name:
        raise RestoreError("没有可撤销的快照", 2)
    try:
        old = history.read_snapshot(od, name)
    except (ValueError, FileNotFoundError) as exc:
        raise RestoreError(str(exc), 2) from None
    undo_name = None
    if vis.is_file():
        undo_name = history.snapshot(od, vis.read_text(encoding="utf-8"), "undo")
    storage.atomic_write_text(vis, old)
    return {"ok": True, "code": "", "message": "已撤销：回到恢复前那一版" if not snapshot or name.endswith("-restore.txt")
            else f"已从快照找回：{name}", "item_id": obj["item_id"], "path": _rel(vis), "snapshot": undo_name,
            "restored_from": name, "kept": {}, "issues_before": []}


def list_snaps(target: str | None = None, path: str | None = None) -> dict[str, Any]:
    obj, vis = resolve(target, path)
    od = storage.object_dir(obj["source"], obj["source_id"])
    return {"ok": True, "code": "", "item_id": obj["item_id"], "path": _rel(vis), "snapshots": history.list_snapshots(od)}


def _looks_archived(text: str) -> bool:
    return bool(render_mod.frontmatter_item_id(text)) or CONTENT_START in text or COMMENTS_START in text \
        or 'class="lb-note' in text or "annotate-view.js" in text


def scan(report: bool = False) -> dict[str, Any]:
    """只读扫可见目录里的归档笔记：坏的、块外有内容的各几篇。report=True 时登记 / 解除问题（render.check）。"""
    root = storage.visible_dir()
    metas = None
    rows: list[dict[str, Any]] = []
    damaged = stray = total = 0
    if root.is_dir():
        for p in root.rglob("*.md"):
            if any(part.startswith(("_", ".")) for part in p.relative_to(root).parts[:-1]):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if not _looks_archived(text):
                continue
            total += 1
            iid = render_mod.frontmatter_item_id(text)
            if not iid:
                if metas is None:
                    metas = {m.get("visible_note"): k for k, m in _meta_scan().items()}
                iid = metas.get(_rel(p))
            issues = diagnose(text)
            human, machine = render_mod.stray_human_lines(text)
            if issues:
                damaged += 1
            if human or machine:
                stray += 1
            if issues or human or machine:
                rows.append({"item_id": iid, "path": _rel(p), "issues": issues,
                             "stray_human": len(human), "stray_machine": len(machine)})
    if report:
        try:
            open_ids = {r.get("item_id") for r in problems.load() if r.get("step") == STEP}
        except Exception:  # noqa: BLE001
            open_ids = set()
        bad_ids = set()
        for r in rows:
            if r["issues"] and r["item_id"]:
                bad_ids.add(r["item_id"])
                if r["item_id"] not in open_ids:
                    # action 显式 retry_later：PERMANENT 默认是 gave_up，那样 repair 永远不会自动恢复（自动恢复失败才登记 gave_up）
                    problems.report(STEP, "PERMANENT.NOTE_DAMAGED", reason_text(r["issues"]),
                                    item_id=r["item_id"], title=Path(r["path"]).stem, action="retry_later")
        for iid in open_ids - bad_ids:
            if iid:
                problems.resolve(STEP, iid)
    return {"ok": True, "code": "", "message": f"扫了 {total} 篇：{damaged} 篇页面结构坏了，{stray} 篇正文外有内容",
            "total": total, "damaged": damaged, "stray": stray, "results": rows}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def add_parser(sub) -> None:
    p = sub.add_parser("restore", help="恢复这篇：存快照后按存档重写可见笔记（可撤销）；--scan 只读检查改坏的笔记")
    p.add_argument("target", nargs="?", help="item_id 或裸 source_id")
    p.add_argument("--path", help="收藏库相对路径（item_id 被删了时用）")
    p.add_argument("--undo", action="store_true", help="撤销：写回最近一次恢复前的快照")
    p.add_argument("--snapshot", help="配 --undo：写回指定的快照")
    p.add_argument("--list", action="store_true", help="列出这篇的快照")
    p.add_argument("--scan", action="store_true", help="只读扫描全部归档笔记")
    p.add_argument("--report", action="store_true", help="配 --scan：把坏的登记进问题面板")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")


def run(args) -> int:
    from .read import dump_json
    try:
        if args.scan:
            out = scan(report=args.report)
        elif args.list:
            out = list_snaps(args.target, args.path)
        elif args.undo:
            out = undo(args.target, args.path, snapshot=args.snapshot)
        else:
            if not args.target and not args.path:
                raise RestoreError("要给 item_id 或 --path", 2)
            out = restore(args.target, args.path, dry_run=args.dry_run)
        code = 0 if out.get("ok") else 1
    except RestoreError as exc:
        out = {"ok": False, "code": exc.code or "", "message": str(exc), "item_id": args.target,
               "path": args.path, "snapshot": None, "kept": {}, "issues_before": [], "results": []}
        code = exc.exit_code
    out.setdefault("results", [])
    _log(out.get("message") or ("完成" if code == 0 else "失败"))
    dump_json(out)
    return code
