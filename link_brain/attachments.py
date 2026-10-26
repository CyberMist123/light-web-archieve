"""来源无关的附件记录、转换、补查队列和命令入口。取件经 sources 能力调用。"""

from __future__ import annotations
from .errtext import errtext

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import domain, problems as problems_mod, sources, storage

EXIT_NEEDS_HUMAN = 5  # 登录态失效 / 安全验证，要人处理（和 ingest 同一套码）

class AttachmentError(RuntimeError):
    """下载附件失败（调用方负责不让它阻断主体归档）。"""


class AttachmentNeedsHuman(AttachmentError):
    """账号要人处理（未登录 / 安全验证）：同一批后面的附件别再试，试了只会再撞一次。"""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class AttachmentRestricted(AttachmentError):
    """1011：这篇在小红书网页版要验证才能看（读取组件 NOTE_RESTRICTED）——只是这一篇，不是号出事：不重试、不停整批，
    记一条「网页版要验证」等她点「打开验证」（link_brain/restricted.py）。"""


class AttachmentServiceDown(AttachmentError):
    """1020：读取服务那侧的失败（超时 / 断了 / 忙 / 浏览器卡住）——不是这份附件的问题，同一趟里重试只会再等一轮超时
    （1019 一份附件 3 次 × 240 秒干等，读取服务其实早卡死，最后被看门狗杀）。不重试，按退避等下次。"""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class AttachmentDeferred(Exception):
    """这一批的时间预算不够再开一个附件页了（1001）：不算失败，留给下一次（今晚 4 点 / 明晚）。"""


# 1001 时间预算：夜跑每一步外面都有限时（超时整棵杀）。开一个附件页 / 登录号补看之前，先确认剩下的时间
# 装得下这一步的最坏耗时；装不下就收手、正常收尾（重建目录、汇总），别在读取服务那侧下载到一半被杀。


def _clock() -> float:
    return time.monotonic()


def budget_from_minutes(minutes: float | None):
    """`--budget-min N` → 返回「还剩几秒」的函数；0 / None = 不限（返回 None）。"""
    if not minutes or float(minutes) <= 0:
        return None
    deadline = _clock() + float(minutes) * 60
    return lambda: deadline - _clock()


def _fits(budget_left, need: float) -> bool:
    return budget_left is None or budget_left() >= need


_MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK", ".pptx": b"PK", ".zip": b"PK"}


def _check_file(path: Path) -> None:
    """下下来的字节像不像这个类型（半截文件 / 网页占位页会在这里露馅）。"""
    magic = _MAGIC.get(path.suffix.lower())
    with path.open("rb") as fh:
        head = fh.read(8)
    if not head:
        raise AttachmentError(f"下到的是空文件：{path.name}")
    if magic and not head.startswith(magic):
        raise AttachmentError(f"下到的不是 {path.suffix} 文件（可能是网页或半截）：{path.name}")


def _have_by_name(object_dir: Path, name: str) -> Path | None:
    """库里已经有同名文件（以前手动挂过、doc_id 记成 manual-…）就别再去网上下一遍。"""
    local = object_dir / "attachments" / name
    return local if name and local.is_file() and local.stat().st_size > 0 else None


def grab_after_ingest(source_key: str, source_id: str, *, budget_left=None) -> str:
    """入库（ob 导入 / 同步收藏）后顺手把这篇的附件下好，不等半夜。出错只记，不影响入库。

    返回值（1001）：下载时撞到要人处理的码（掉登录 / 验证 / 风控 / 熔断）就返回那个码，调用方据此整批停车；
    否则返回空串。budget_left：同步的剩余时间，装不下下一个附件就留给 4 点的 `attachments --all`。
    """
    if _backend(source_key) is None:
        return ""
    blocked_code = ""
    try:
        object_dir = storage.object_dir(source_key, source_id)
        if not inventory(object_dir)["missing"]:
            return ""
        outcome = download_for_object(source_key, source_id, verbose=True, budget_left=budget_left)
        from . import index as index_mod, render as render_mod
        render_mod.render_object(source_key, source_id)
        meta = storage.read_json(object_dir / "meta.json")
        conn = index_mod.connect()
        try:
            index_mod.set_attachments_status(conn, meta["item_id"], meta.get("attachments_status"))
        finally:
            conn.close()
        for r in outcome["results"]:
            # 问题登记在 download_for_object 里统一做（账号类 NEEDS_HUMAN 推一次；其余 TRANSIENT，夜里再补）
            if r["status"] == "failed" and r.get("code") and not blocked_code:
                blocked_code = str(r["code"])
    except Exception as exc:  # noqa: BLE001 - 附件是锦上添花，别拖垮已落盘的归档
        print(f"[attachment] 入库后顺手下附件出错（今晚 4 点会再补）：{exc}", file=sys.stderr)
    return blocked_code


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def attachments_path(source_key: str, source_id: str) -> Path:
    return storage.object_dir(source_key, source_id) / "attachments.json"


def load_downloaded(source_key: str, source_id: str) -> dict[str, dict[str, Any]]:
    """`doc_id -> 记录` 的表；没下过就是空表。"""
    path = attachments_path(source_key, source_id)
    if not path.exists():
        return {}
    try:
        doc = storage.read_json(path)
    except (ValueError, OSError):
        return {}
    return {x["doc_id"]: x for x in doc.get("files", []) if x.get("doc_id")}


# 1001（审计 raw-1）：正文线索解析出的真编号、补查探到的附件，记在对象级 attachments-resolved.json，
# 读的时候和 source.json 的声明合并——已封存的 raw/vNNNN/source.json 一个字节都不再动（硬约束 4）。
RESOLVED_NAME = "attachments-resolved.json"
_RESOLVED_KEYS = ("doc_id", "name", "url", "page_num")


def resolved_path(object_dir: Path) -> Path:
    return object_dir / RESOLVED_NAME


def load_resolved(object_dir: Path) -> list[dict[str, Any]]:
    path = resolved_path(object_dir)
    if not path.exists():
        return []
    try:
        doc = storage.read_json(path)
    except (OSError, ValueError):
        return []
    return [x for x in doc.get("resolved", []) if isinstance(x, dict) and x.get("doc_id")]


def remember_resolved(object_dir: Path, found: dict[str, Any], *, hint: str | None = None, via: str) -> None:
    """记一条「事后才知道的附件声明」。同一线索 / 同一 doc_id 只留最新一条。"""
    entry = {k: found.get(k) for k in _RESOLVED_KEYS if found.get(k) is not None}
    entry.update({"hint": hint, "via": via,
                  "resolved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")})
    rows = [r for r in load_resolved(object_dir)
            if r.get("doc_id") != entry["doc_id"] and not (hint and r.get("hint") == hint)]
    storage.write_json(resolved_path(object_dir), {"schema_version": 1, "resolved": rows + [entry]})


def declared_attachments(object_dir: Path, source_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """source.json 声明的附件 + 对象级补到的（线索解析出的编号 / 补查探到的文件）。返回新列表，不改 source_doc。"""
    base = [dict(a) for a in ((source_doc.get("note") or {}).get("attachments") or [])]
    for r in load_resolved(object_dir):
        if any(a.get("doc_id") == r["doc_id"] for a in base):
            continue
        target = next((a for a in base if r.get("hint") and not a.get("doc_id") and a.get("hint") == r["hint"]), None)
        fields = {k: r[k] for k in _RESOLVED_KEYS if r.get(k) is not None}
        if target is not None:
            target.update(fields, status="metadata_only")
        else:
            base.append({**fields, "status": "metadata_only"})
    return base


def inventory(object_dir: Path, meta=None) -> dict[str, Any]:
    """Count every declared file; a lone file cannot mark the whole note complete."""
    meta = meta or storage.read_json(object_dir / "meta.json")
    source_path = object_dir / "raw" / f"v{meta['current_version']:04d}" / "source.json"
    source = storage.read_json(source_path) if source_path.exists() else {}
    declared = declared_attachments(object_dir, source)
    record_path = object_dir / "attachments.json"
    records = storage.read_json(record_path).get("files", []) if record_path.exists() else []
    files = []
    represented = set()
    for att in declared:
        got = next((r for r in records if (att.get("doc_id") and r.get("doc_id") == att["doc_id"])
                    or ((att.get("name") or att.get("hint")) and r.get("name") == (att.get("name") or att.get("hint")))), {})
        local = object_dir / "attachments" / got.get("file", "")
        exists = local.is_file() and local.stat().st_size > 0
        doc_id = att.get("doc_id") or got.get("doc_id")
        md = object_dir / "derived" / "attachments" / f"{doc_id}.md"
        files.append({"doc_id": doc_id, "name": att.get("name") or got.get("name") or att.get("hint") or "附件",
                      "downloaded": exists, "status": "downloaded" if exists else att.get("status", "metadata_only"), "pages": att.get("page_num"), "file": str(local) if exists else None,
                      "markdown": str(md) if md.is_file() else None, "url": att.get("url")})
        if got:
            represented.add(got.get("doc_id"))
    for got in records:
        if got.get("doc_id") in represented:
            continue
        local = object_dir / "attachments" / got.get("file", "")
        md = object_dir / "derived" / "attachments" / f"{got.get('doc_id')}.md"
        files.append({"doc_id": got.get("doc_id"), "name": got.get("name") or local.name,
                      "downloaded": local.is_file() and local.stat().st_size > 0,
                      "file": str(local) if local.is_file() else None,
                      "status": "downloaded" if local.is_file() else "metadata_only",
                      "markdown": str(md) if md.is_file() else None})
    missing = sum(not f["downloaded"] for f in files)
    state_path = object_dir / "attachment-state.json"
    state = storage.read_json(state_path) if state_path.exists() else {}
    return {"item_id": meta["item_id"], "title": meta.get("title"), "files": files,
            "missing": missing, "total": len(files),
            "errors": state.get("errors", []),
            "unconfirmed": sum(not f["downloaded"] and not f.get("doc_id") for f in files),
            "status": ("unavailable" if all(not f.get("doc_id") for f in files) else "metadata_only") if missing else "downloaded" if files else "none"}


def update_status(source_key, source_id):
    obj = storage.object_dir(source_key, source_id)
    meta = storage.read_json(obj / "meta.json")
    report = inventory(obj, meta)
    # 1024：只改 attachments_status，单篇锁里重读再写
    storage.update_json(obj / "meta.json", lambda m: m.update(attachments_status=report["status"]),
                        lock_name=storage.obj_lock_name(meta["item_id"]))
    return report


CONVERT_BACKOFF_DAYS = (1, 2, 4, 7)  # TRANSIENT 转换失败第 1/2/3/≥4 次之后，隔几个日历日再转（封顶 7 天）


def conversion_next_at(tries: int, now: datetime | None = None) -> str:
    """TRANSIENT 转换失败后的下次可重试时刻：第 n 次失败后隔 CONVERT_BACKOFF_DAYS[n-1] 个**日历日**，
    从那天 00:00（本地时间）起可以再转。按日历日不按 24 小时：凌晨 4:10 失败、第二晚 4:05 的夜跑也照样重试。"""
    now = (now or datetime.now().astimezone()).astimezone()
    days = CONVERT_BACKOFF_DAYS[min(max(tries, 1), len(CONVERT_BACKOFF_DAYS)) - 1]
    day = (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return day.isoformat(timespec="seconds")


def mark_conversion(source_key: str, source_id: str, doc_id: str, note: str | None, *,
                    partial_pages: int = 0, code: str = "", now: datetime | None = None) -> str | None:
    """记下这份附件转 md 的结果：失败就标 conversion_failed（带故障码和当时的 sha256，换了文件自动作废），成功就清掉。

    第 4 批：PERMANENT 码（加密 / 损坏 / 不支持）的同一份字节 pdftext 不再重试；TRANSIENT 码（OCR 服务故障、超时）
    记 `tries`（同一份字节、连着几次 TRANSIENT）和 `next_at`（见 conversion_next_at：1、2、4、7 天，封顶 7 天），
    到点之前 pdftext 跳过、到点之后自动再转。返回 next_at（PERMANENT / 成功时为 None）。

    partial_pages：转出来了但有几页没认出来——记 conversion_partial（累计次数），pdftext 据此再试几次。
    """
    known = load_downloaded(source_key, source_id)
    rec = known.get(doc_id)
    if not rec:
        return None
    next_at = None
    if note is None:
        before = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        rec.pop("conversion_failed", None)
        if partial_pages:
            prior = rec.get("conversion_partial") or {}
            tries = int(prior.get("tries") or 0) + 1 if prior.get("sha256") == rec.get("sha256") else 1
            rec["conversion_partial"] = {"pages_failed": partial_pages, "sha256": rec.get("sha256"), "tries": tries}
        else:
            rec.pop("conversion_partial", None)
        if json.dumps(rec, sort_keys=True, ensure_ascii=False) == before:
            return None
    else:
        when = (now or datetime.now().astimezone()).astimezone()
        failed = {"note": str(note)[:300], "sha256": rec.get("sha256"), "code": code,
                  "at": when.isoformat(timespec="seconds")}
        if str(code or "").startswith("TRANSIENT."):
            prior = rec.get("conversion_failed") or {}
            same = prior.get("sha256") == rec.get("sha256") and str(prior.get("code") or "").startswith("TRANSIENT.")
            failed["tries"] = int(prior.get("tries") or 1) + 1 if same else 1
            failed["next_at"] = next_at = conversion_next_at(failed["tries"], when)
        rec["conversion_failed"] = failed
    storage.write_json(attachments_path(source_key, source_id), {"schema_version": 1, "files": list(known.values())})
    return next_at


def convert_downloads(source_key, source_id):
    from .pdftext import convert_object_attachments
    try:
        rows = convert_object_attachments(source_key, source_id)
    except Exception as exc:  # noqa: BLE001 - 一篇的坏文件别让整晚的附件补下停在这里（审计 attach-4 ②）
        msg = f"附件转换出错：{type(exc).__name__}: {exc}"
        print(msg, file=sys.stderr)
        return [msg]
    errors = [r.get("note", "转换失败") for r in rows if r["status"] == "failed"]
    if errors:
        print("附件已保存，但正文转换失败：" + "; ".join(errors), file=sys.stderr)
    return errors


def local_download(name: str) -> Path | None:
    """Reuse an exact filename from the configured download folder before browsing."""
    from .ai_config import load
    folder = Path(load().get("downloads", {}).get("folder") or Path.home() / "Downloads")
    if not folder.is_dir() or not name:
        return None
    def normalized(value):
        return re.sub(r"\s*\(\d+\)(?=\.[^.]+$)", "", value).casefold().strip()
    candidates = [p for p in folder.iterdir() if p.is_file() and normalized(p.name) == normalized(name)
                  and p.stat().st_size > 0 and time.time() - p.stat().st_mtime > 3]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def download_for_object(
    source_key: str, source_id: str, *, force: bool = False, verbose: bool = False, budget_left=None
) -> dict[str, Any]:
    """把一个对象的附件字节下下来，落对象级 `attachments/` 并写 `attachments.json`。

    不动任何 `raw/vNNNN/`（版本一旦写完就封存）。失败只返回 error，不抛给调用方之外。
    budget_left（1001）：时间不够再开页了 → 余下的记 status=deferred（不算失败），收手。
    """
    object_dir = storage.object_dir(source_key, source_id)
    meta_path = object_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"没有归档过: {source_key}/{source_id}")
    meta = storage.read_json(meta_path)
    backend = _backend(source_key)
    if backend is None:
        return {"item_id": meta["item_id"], "results": []}
    version = meta["current_version"]
    source_doc = storage.read_json(storage.raw_dir(source_key, source_id, version) / "source.json")
    note = source_doc["note"]
    attachments = declared_attachments(object_dir, source_doc)

    known = load_downloaded(source_key, source_id)
    results: list[dict[str, Any]] = []
    dest_dir = object_dir / "attachments"
    staging = object_dir / ".attachment-staging"
    backoff = _load_backoff(object_dir)
    now = datetime.now().astimezone()
    held_back = (not force) and backend.is_restricted(source_id)

    for att in attachments:
        if held_back:
            # 1011：这篇在网页版要验证才能看——等她点「打开验证」，不再每晚开页（问题面板 / 卡片上已有一条，不再按附件另记）
            known_rec = known.get(att.get("doc_id") or "") or {}
            if att.get("doc_id") and known_rec and (dest_dir / (known_rec.get("file") or "")).is_file():
                results.append({**known_rec, "status": "already"})
            else:
                results.append({"doc_id": att.get("doc_id"), "name": att.get("name") or att.get("hint"),
                                "status": "restricted", "error": backend.restricted_text()})
            continue
        doc_id = att.get("doc_id")
        if not doc_id:
            # 1001（审计 health/attach-1）：这条线索以前手动挂过文件（记录的 name 就是线索原文、文件在盘上）
            # = 已经满足，别每晚再用登录号开一次笔记页、再报一次「附件没下好」。
            claimed = next((r for r in known.values() if att.get("hint") and r.get("name") == att.get("hint")
                            and (dest_dir / (r.get("file") or "")).is_file()
                            and (dest_dir / r["file"]).stat().st_size > 0), None)
            if claimed and not force:
                results.append({**claimed, "status": "already"})
                continue
            # 0929 Owner：附件务必同步。只有正文线索（「prompt在附件」）的，当场去笔记页找文件编号：
            # 游客读不到（登录墙笔记）就用登录号看，找到就补进 source.json 接着下，别再静默跳过。
            if not _fits(budget_left, backend.probe_cost()):
                results.append({"doc_id": None, "name": att.get("hint"), "status": "deferred",
                                "error": "时间预算不够再去笔记页找附件了，下次接着找"})
                break
            found = backend.resolve_hint(source_id, note.get("xsec_token"))
            if found.get("needs_human"):
                # 1001：登录号补看撞到掉登录 / 风控 → 这篇记失败带上码，整批停车
                results.append({"doc_id": None, "name": att.get("hint"), "status": "failed",
                                "error": found.get("error"), "code": found.get("code") or "NOT_LOGGED_IN"})
                break
            if found.get("doc_id"):
                # 1001（审计 raw-1）：找到的编号记进对象级 attachments-resolved.json，不再回写已封存的 source.json
                remember_resolved(object_dir, found, hint=att.get("hint"), via="hint")
                att.update(found)
                doc_id = att["doc_id"]
            else:
                results.append({"doc_id": None, "name": att.get("hint"), "status": "failed",
                                "error": f"正文提到附件，笔记页没找到文件编号：{found.get('error')}"})
                continue
        if not force and doc_id in known and (dest_dir / known[doc_id]["file"]).is_file() and (dest_dir / known[doc_id]["file"]).stat().st_size > 0:
            results.append({**known[doc_id], "status": "already"})
            continue
        try:
            local = (None if force else _have_by_name(object_dir, att.get("name") or "")) or local_download(att.get("name") or "")
            if local:
                manual_attach(source_key, source_id, str(local), doc_id)
                # 1001（审计 attach-3）：整份重读——manual_attach 可能把 manual-… 那条并掉了，旧快照里还留着它
                known = load_downloaded(source_key, source_id)
                results.append({**known[doc_id], "status": "downloaded"})
                continue
            prior = backoff.get(doc_id) or {}
            if not force and prior.get("next_at") and now < _parse_dt(prior["next_at"], now):
                # 1008（B3-P3）：同一份附件下载失败后按 1/2/4/7 天跨夜退避，退避期内不开页（以前每晚最多开 6 次号页）
                results.append({"doc_id": doc_id, "name": att.get("name"), "status": "backoff",
                                "error": f"上次没下好（{prior.get('error') or '原因见上次'}），{prior['next_at'][5:16]} 之后再试"})
                continue
            record = backend.acquire(source_key, source_id, doc_id=doc_id, name=att.get("name") or "file",
                             xsec_token=backend.fresh_token(source_id) or backend.best_token(source_id, note.get("xsec_token")) or "",
                             verbose=verbose, budget_left=budget_left, tries=1 if prior else None)
            known = load_downloaded(source_key, source_id)
            backoff.pop(doc_id, None)
            results.append({**record, "status": "downloaded"})
        except AttachmentRestricted as exc:
            # 1011：只是这一篇（网页版要验证）——记进 restricted（acquire 里已登记一条），不算下载失败、不进跨夜退避；
            # 这篇剩下的附件同样打不开，不再开页
            results.append({"doc_id": doc_id, "name": att.get("name"), "status": "restricted", "error": str(exc)})
            held_back = True
        except AttachmentDeferred as exc:
            results.append({"doc_id": doc_id, "name": att.get("name"), "status": "deferred", "error": str(exc)})
            break  # 时间到了：余下的附件下次再下
        except AttachmentNeedsHuman as exc:
            results.append({"doc_id": doc_id, "status": "failed", "error": str(exc), "code": exc.code})
            break  # 账号要人处理：余下附件等处理完再补
        except (AttachmentError, subprocess.SubprocessError, OSError) as exc:
            results.append({"doc_id": doc_id, "status": "failed", "error": errtext(exc)})
            n = int((backoff.get(doc_id) or {}).get("tries") or 0) + 1
            backoff[doc_id] = {"tries": n, "next_at": conversion_next_at(n, now), "error": str(exc)[:120]}

    _save_backoff(object_dir, backoff)
    if staging.exists() and not any(staging.iterdir()):
        staging.rmdir()

    # 记录都由 manual_attach 写好了；这里不再拿循环前的快照往回合并（那样会把并掉的 manual-… 又写回去，审计 attach-3）
    update_status(source_key, source_id)

    errors = [{"doc_id": r.get("doc_id"), "error": r.get("error")} for r in results if r["status"] in {"failed", "skipped"}]
    deferred_ids = {r.get("doc_id") for r in results if r["status"] == "deferred"}
    if deferred_ids:  # 没轮到的（时间预算到了）：上次的错误原样留着，别当成「这次没出错」冲掉
        state_path = object_dir / "attachment-state.json"
        try:
            before = storage.read_json(state_path).get("errors", []) if state_path.exists() else []
        except (OSError, ValueError):
            before = []
        errors += [e for e in before if e.get("doc_id") in deferred_ids]
    storage.write_json(object_dir / "attachment-state.json", {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "errors": errors, **({"download_backoff": backoff} if backoff else {}),
    })
    _report_downloads(meta, results)
    return {"item_id": meta["item_id"], "results": results}


def _report_downloads(meta: dict[str, Any], results: list[dict[str, Any]]) -> None:
    """下附件的结论进问题记录（CONVENTIONS §2 迁移点；attachments.json / attachment-state.json 照写）。

    - 撞到账号要处理（带码，或报错文本像掉登录 / 验证）→ NEEDS_HUMAN，登记在 login（同一件事一把 key，只推一次）；
    - 其余没下好（下载超时、读取服务没起来、附件页没下载按钮、正文提到附件但没找到文件编号）→ TRANSIENT.DOWNLOAD_FAILED，
      只记不推：每晚 4 点 attachments --all 自动再补，同一篇连续 3 天都不行才升级 STUCK 推一次；
    - 这次没有失败、也没有因时间不够留到下次的 → 这篇的下载问题标已解决。"""
    item_id, title = meta.get("item_id"), meta.get("title")
    failed = [r for r in results if r.get("status") == "failed"]
    try:  # 10-03 同步记录：这次真下到的 ✅、没下好的 ❌（已有 / 留到下次的不算）
        from . import synclog
        for r in results:
            if r.get("status") == "downloaded":
                synclog.note("attachment", item_id, True, title=title, note_path=meta.get("visible_note"))
            elif r.get("status") == "failed":
                name = r.get("name") or r.get("file") or r.get("doc_id") or "附件"
                synclog.note("attachment", item_id, False, title=title, note_path=meta.get("visible_note"),
                             reason=f"{name}：{r.get('error') or '没下好'}", code=r.get("code") or "")
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] {type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        for r in failed:
            message = str(r.get("error") or "附件没下好")
            name = r.get("name") or r.get("file") or r.get("doc_id") or "附件"
            if r.get("code") or _looks_blocked(meta.get("source") or domain.parse_item_id(item_id)[0], message):
                problems_mod.report_blocked("attachments.download", r.get("code") or "", f"下附件时：{message}"[:200])
            else:
                problems_mod.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", f"{name}：{message}"[:200],
                                    item_id=item_id, title=title)
        if not failed and not any(r.get("status") in ("deferred", "backoff") for r in results):
            problems_mod.resolve("attachments.download", item_id)
    except Exception as exc:  # noqa: BLE001 - 登记失败不影响附件本身
        print(f"[attachment] 问题记录没写上：{exc}", file=sys.stderr)


def _can_claim_lone(att: dict[str, Any], known: dict[str, dict[str, Any]], src: Path) -> bool:
    """只有一条附件声明、手动挂的文件名又对不上时，能不能把它认成那一条（审计 attach-5）。"""
    label = att.get("name") or att.get("hint")
    if (att.get("doc_id") and att["doc_id"] in known) or (label and any(r.get("name") == label for r in known.values())):
        return False  # 那一条已经有下载记录了：这是另一个文件
    suffix = Path(att.get("name") or "").suffix.lower()
    return not suffix or suffix == src.suffix.lower()  # 只有正文线索（没文件名）时不比扩展名


def _free_name(dest: Path) -> Path:
    for n in range(2, 1000):
        cand = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not cand.exists():
            return cand
    raise AttachmentError(f"同名文件太多了：{dest.name}")


def _is_manual(doc_id: Any) -> bool:
    return str(doc_id or "").startswith("manual-")


def _manual_ids(replaced: list[dict[str, Any]], keep_id: str) -> list[str]:
    """被取代的记录里的 manual-… 编号（连同它们以前合并过的），新记录是真编号时才记。"""
    if _is_manual(keep_id):
        return []
    out: list[str] = []
    for r in replaced:
        for mid in [r.get("doc_id"), *(r.get("manual_ids") or [])]:
            if _is_manual(mid) and mid not in out:
                out.append(mid)
    return out


def _retire_manual_md(object_dir: Path, manual_ids: list[str], keep_id: str, *, dry_run: bool = False) -> list[str]:
    """manual-… 那份转好的 md：真编号还没有 md 就改名沿用（同一份文件，不必再转一遍），有了就删掉重复的。"""
    md_dir = object_dir / "derived" / "attachments"
    real = md_dir / f"{keep_id}.md"
    actions = []
    for mid in manual_ids:
        old = md_dir / f"{mid}.md"
        if not old.is_file():
            continue
        if not real.exists():
            actions.append(f"{old.name} → {real.name}")
            if not dry_run:
                os.replace(old, real)
        else:
            actions.append(f"删 {old.name}（与 {real.name} 重复）")
            if not dry_run:
                old.unlink()
    return actions


def manual_attach(source_key: str, source_id: str, file_path: str, doc_id: str | None = None,
                  origin: str = "manual") -> dict[str, Any]:
    """把 Owner 自己下好的文件手动挂到这篇（系统 headed 下不了时用）。

    复制进对象级 `attachments/`，尽量按文件名认领一个 doc_id（认不出就存 manual 记录），
    标 meta 为 downloaded。不联网。
    """
    src = Path(file_path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在: {src}")
    object_dir = storage.object_dir(source_key, source_id)
    meta_path = object_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"没有归档过: {source_key}/{source_id}")
    meta = storage.read_json(meta_path)
    version = meta["current_version"]
    source_doc = storage.read_json(storage.raw_dir(source_key, source_id, version) / "source.json")
    declared = declared_attachments(object_dir, source_doc)

    known = load_downloaded(source_key, source_id)
    dest_dir = object_dir / "attachments"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 认领哪一条声明：调用方给了 doc_id 就只认它；否则按文件名认。
    # 1001（审计 attach-5）：只有一个声明时的兜底认领要三条同时成立——没给 doc_id、那一个还没有下载记录、
    # 扩展名对得上；否则新增 manual-… 记录，不再把已有附件的记录顶掉。
    if doc_id:
        matched = next((a for a in declared if a.get("doc_id") == doc_id), None)
    else:
        matched = next((a for a in declared if a.get("name") and a["name"] == src.name), None)
        if not matched and len(declared) == 1 and _can_claim_lone(declared[0], known, src):
            matched = declared[0]
    # 调用方给了真 doc_id 就用它（0927：recheck 下的附件元数据里没声明过，旧逻辑记成 manual-… 对不上号，每晚重下）
    record_id = doc_id or (matched or {}).get("doc_id") or "manual-" + re.sub(r"[^\w.-]", "_", src.stem)

    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        holder = next((r for r in known.values() if r.get("file") == dest.name), None)
        if dest.is_file() and holder and holder.get("doc_id") != record_id and _sha256(dest) != _sha256(src):
            dest = _free_name(dest)  # 同名但不是同一份：别覆盖别的附件的字节
        shutil.copyfile(src, dest)

    record = {
        "doc_id": record_id,
        "name": (matched or {}).get("name") or (matched or {}).get("hint") or src.name,
        "file": dest.name,
        "bytes": dest.stat().st_size,
        "sha256": _sha256(dest),
        "downloaded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": origin,
    }
    # 同一个文件 / 同一个 doc_id 的旧记录被这条取代。1001（审计 attach-3）：手动挂的 manual-… 被认回真编号时
    # 合并成一条——保留真 doc_id，manual 来源记在 manual_ids 里，它那份 md 也并过来，不再留两份。
    replaced = [v for k, v in known.items() if v.get("file") == dest.name or k == record_id]
    manual_ids = _manual_ids(replaced, record_id)
    if manual_ids:
        record["manual_ids"] = manual_ids
        record["source"] = "manual"
    files = [v for v in known.values() if v not in replaced] + [record]
    storage.write_json(attachments_path(source_key, source_id), {"schema_version": 1, "files": files})
    _retire_manual_md(object_dir, manual_ids, record_id)
    report = update_status(source_key, source_id)
    state_path = object_dir / "attachment-state.json"
    if state_path.exists():
        state = storage.read_json(state_path)
        state["errors"] = [r for r in state.get("errors", []) if r.get("doc_id") != record["doc_id"]]
        storage.write_json(state_path, state)
    return {"item_id": meta["item_id"], "file": dest.name, "bytes": record["bytes"], "status": report["status"]}


def dedupe(*, dry_run: bool = True) -> dict[str, Any]:
    """一次性修复（审计 attach-3）：同一个文件被记了两条（manual-… 和真 doc_id）的，并成真 doc_id 一条。

    不联网。dry_run 只读、只报会改哪几篇；不 dry_run 才写 attachments.json、并掉重复的 md、重渲染这一篇。
    同一文件下有两个以上真编号、或全是 manual 的，判不了谁对，只报不改。
    """
    base = storage.vault_root() / "_archive"
    plans, skipped = [], []
    for path in sorted(base.glob("*/*/attachments.json")):
        obj = path.parent
        source_key, source_id = obj.parent.name, obj.name
        known = load_downloaded(source_key, source_id)
        by_file: dict[str, list[dict[str, Any]]] = {}
        for r in known.values():
            by_file.setdefault(r.get("file") or "", []).append(r)
        for file, group in by_file.items():
            if len(group) < 2:
                continue
            real = [r for r in group if not _is_manual(r.get("doc_id"))]
            manual = [r for r in group if _is_manual(r.get("doc_id"))]
            if len(real) != 1 or not manual:
                skipped.append({"source_id": source_id, "file": file, "doc_ids": [r.get("doc_id") for r in group],
                                "why": "同一文件下真编号不止一个或全是 manual，判不了"})
                continue
            keep = real[0]
            manual_ids = _manual_ids(group, keep["doc_id"])
            plans.append({"source": source_key, "source_id": source_id, "file": file, "keep": keep["doc_id"],
                          "drop": [r["doc_id"] for r in manual],
                          "same_sha256": len({r.get("sha256") for r in group}) == 1,
                          "md": _retire_manual_md(obj, manual_ids, keep["doc_id"], dry_run=True)})
            if dry_run:
                continue
            merged = {**keep, "manual_ids": manual_ids, "source": "manual"}
            files = [r for r in known.values() if r not in group] + [merged]
            storage.write_json(attachments_path(source_key, source_id), {"schema_version": 1, "files": files})
            _retire_manual_md(obj, manual_ids, keep["doc_id"])
            known = load_downloaded(source_key, source_id)
    if not dry_run:
        from . import render as render_mod
        for sid in sorted({(p["source"], p["source_id"]) for p in plans}):
            _sync_index_status(*sid)
            try:
                render_mod.render_object(*sid)  # agent.md / 可见笔记里的附件只列一次
            except (OSError, ValueError, KeyError) as exc:
                print(f"[dedupe] {sid[1]} 重渲染失败（记录已并好，下次渲染会带上）：{exc}", file=sys.stderr)
        if plans:
            _rebuild_catalog(True)
    return {"dry_run": dry_run, "merge": plans, "skipped": skipped}


def describe_problem(source_key: str, source_id: str, file_name: str | None, reason: str) -> str:
    """一条没下好的附件 = 哪篇 + 哪个文件 + 为什么 + 单项重跑命令（0929 Owner：别概括报错）。"""
    try:
        meta = storage.read_json(storage.object_dir(source_key, source_id) / "meta.json")
    except (OSError, ValueError):
        meta = {}
    item_id = meta.get("item_id") or domain.item_id(source_key, source_id)
    return (f"《{meta.get('title') or source_id}》{item_id} · {file_name or '附件'} · {reason.strip()[:160]}"
            f" → 重跑：python -m link_brain attachments {item_id}")


EXIT_ACCOUNT_BUSY = 6


def run(args) -> int:
    """`attachments`。会用号开页的（--recheck / --all / 单篇下载）先查熔断和账号锁：
    熔断中 → 退出 5 一页不开；号被别的任务占着 → 退出 6。--audit / --attach 不联网，不受影响。"""
    if getattr(args, "audit", False) or getattr(args, "attach", None) or getattr(args, "dedupe", False):
        return _run(args)
    from .read import dump_json
    if getattr(args, "recheck_status", False) or getattr(args, "skipped", None) or getattr(args, "reconcile", False):
        # 纯本地：状态 / 跳过记一笔（夜跑脚本用 -Account 跳过收尾段时调）/ 本地对账
        if getattr(args, "skipped", None):
            write_recheck_status("tail", {"checked": 0, "skipped": args.skipped, "stopped_reason": "skipped"})
        if getattr(args, "reconcile", False):
            dump_json(reconcile())
        else:
            dump_json(recheck_status())
        return 0
    if getattr(args, "recheck", False) and getattr(args, "guest_only", False):
        # 1008（B3-P1）：游客段——不调 check_risk_hold / ensure_reader（那会拉起读取服务）、不拿账号锁；
        # 只读本地熔断文件决定开不开页（见 recheck_guest）
        out = recheck_guest(limit=getattr(args, "limit", 0) or 0, verbose=True,
                            budget_left=budget_from_minutes(getattr(args, "budget_min", 0)))
        dump_json(out)
        return 0
    return _backend(_default_source()).run_with_account(args, _run)


def _run(args, budget_left=None) -> int:
    from . import index as index_mod

    # 1001：--budget-min N 到点收手、正常收尾（夜跑外层限时会整棵杀，别在下载到一半时被杀）
    if budget_left is None:
        budget_left = budget_from_minutes(getattr(args, "budget_min", 0))
    if getattr(args, "recheck", False):
        from .read import dump_json
        if getattr(args, "logged_in_tail", False):
            out = recheck_tail(limit=getattr(args, "limit", 0) or TAIL_LIMIT, verbose=True, budget_left=budget_left)
        else:
            out = recheck(limit=getattr(args, "limit", 0) or 0, verbose=True, budget_left=budget_left)
        dump_json(out)
        return EXIT_NEEDS_HUMAN if out.get("blocked") else 0
    if getattr(args, "dedupe", False):
        from .read import dump_json
        dump_json(dedupe(dry_run=getattr(args, "dry_run", False)))
        return 0
    if getattr(args, "audit", False):
        from .read import dump_json
        metas = list(_attachment_metas())
        rows = [inventory(p.parent) for p in metas]
        states = {p.parent.name: _backend(p.parent.parent.name).probe_state(p.parent) for p in metas}
        unprobed = [k for k, v in states.items() if v == "unprobed"]
        dump_json({"items": [r for r in rows if r["total"]], "missing": sum(r["missing"] for r in rows),
                   "unprobed": len(unprobed), "unprobed_ids": unprobed,
                   "gone": sum(1 for v in states.values() if v == "gone"),
                   "recheck": recheck_status(),
                   "total": sum(r["total"] for r in rows), "unconfirmed": sum(r["unconfirmed"] for r in rows)})
        return 0
    # 手动挂本地文件：认领一篇 → 复制进 attachments → 标已下 → 渲染 + 重建目录
    if getattr(args, "attach", None):
        if not args.target:
            print("挂本地文件要指定是哪篇（item_id）", file=sys.stderr)
            return 1
        conn = index_mod.connect()
        try:
            row = index_mod.get_object(conn, args.target)
        finally:
            conn.close()
        if not row:
            print(f"没有归档过: {args.target}", file=sys.stderr)
            return 1
        try:
            out = manual_attach(row["source"], row["source_id"], args.attach, getattr(args, "doc_id", None))
        except (OSError, KeyError, ValueError) as exc:
            print(f"挂文件失败: {exc}", file=sys.stderr)
            return 1
        from . import render as render_mod

        conversion_errors = convert_downloads(row["source"], row["source_id"])
        render_mod.render_object(row["source"], row["source_id"])
        conn2 = index_mod.connect()
        try:
            index_mod.set_attachments_status(conn2, out["item_id"], out["status"])
        finally:
            conn2.close()
        print(f"{out['item_id']}  ↓(手动) {out['file']}  {out['bytes']} 字节")
        rebuilt = _rebuild_catalog(True)
        return 2 if conversion_errors or not rebuilt else 0

    conn = index_mod.connect()
    try:
        if getattr(args, "all", False):
            rows = conn.execute(
                "SELECT source, source_id FROM objects WHERE attachments_status IN "
                "('metadata_only', 'downloaded', 'unavailable') ORDER BY item_id"
            ).fetchall()
            targets = [(r["source"], r["source_id"]) for r in rows]
        elif args.target:
            row = index_mod.get_object(conn, args.target)
            if not row:
                print(f"没有归档过: {args.target}", file=sys.stderr)
                return 1
            targets = [(row["source"], row["source_id"])]
        else:
            print("需要 target 或 --all", file=sys.stderr)
            return 1
    finally:
        conn.close()

    if not targets:
        print("没有带附件元数据的对象")
        return 0

    from . import render as render_mod

    failed = False
    account_blocked = False
    any_downloaded = False
    problem_lines: list[str] = []
    deferred_objects = 0
    for n, (source_key, source_id) in enumerate(targets):
        backend = _backend(source_key)
        if backend is None:
            continue
        if not _fits(budget_left, backend.attempt_cost(1)):
            deferred_objects = len(targets) - n  # 时间到了：剩下的篇不再看，留着下次
            break
        outcome = download_for_object(
            source_key, source_id, force=getattr(args, "force", False), verbose=getattr(args, "verbose", False),
            budget_left=budget_left,
        )
        for r in outcome["results"]:
            if r["status"] == "downloaded":
                any_downloaded = True
                print(f"{outcome['item_id']}  ↓ {r['file']}  {r['bytes']} 字节  {r['sha256'][:12]}…")
            elif r["status"] == "already":
                print(f"{outcome['item_id']}  = {r['file']}（已有，--force 可重下）")
            elif r["status"] in ("deferred", "backoff", "restricted"):
                print(f"{outcome['item_id']}  … {r.get('name') or r.get('doc_id') or '附件'}：{r.get('error')}",
                      file=sys.stderr)
            else:
                failed = True
                message = str(r.get("error") or "")
                line = describe_problem(source_key, source_id, r.get("name") or r.get("file") or r.get("doc_id"), message)
                problem_lines.append(line)
                print(f"✗ {line}", file=sys.stderr)
                # 附件要登录态，挂了很可能是掉线/撞风控 —— 停车；问题已在 download_for_object 里登记
                # （账号类 NEEDS_HUMAN 推一次，其余 TRANSIENT 只记）
                if r.get("code") or _looks_blocked(source_key, message):
                    account_blocked = True
        if convert_downloads(source_key, source_id):
            failed = True
        render_mod.render_object(source_key, source_id)
        meta_now = storage.read_json(storage.object_dir(source_key, source_id) / "meta.json")
        if meta_now.get("attachments_status"):
            conn2 = index_mod.connect()
            try:
                index_mod.set_attachments_status(conn2, meta_now["item_id"], meta_now["attachments_status"])
            finally:
                conn2.close()
        if account_blocked:
            _rebuild_catalog(True)
            print(backend.blocked_message(), file=sys.stderr)
            return EXIT_NEEDS_HUMAN

    if deferred_objects:
        print(f"时间预算到了：还有 {deferred_objects} 篇没看，下次接着补", file=sys.stderr)
    # 下到了新字节就重建目录，否则 UI 角标还停在「待补」（补跑却没同步就是这坑）
    rebuilt = _rebuild_catalog(True)
    if problem_lines:
        # 一条一条列清楚是哪篇哪个文件，单项重跑即可（0929 Owner）。第 4 批：不推送，
        # 每篇已按码登记进问题记录（目录页顶部问题入口 / 卡片悬停看得到）
        print(f"\n附件没下好 {len(problem_lines)} 个：", file=sys.stderr)
        for line in problem_lines:
            print(f"  - {line}", file=sys.stderr)
    # 1001 统一退出码：0 成功 / 部分完成 · 1 出错 · 5 要人处理（上面已返回）· 6 号被占用
    return 1 if failed or not rebuilt else 0


def _rebuild_catalog(any_downloaded: bool) -> bool:
    if not any_downloaded:
        return True
    try:
        from . import catalog as catalog_mod

        _, count, _ = catalog_mod.build()
        print(f"目录已重建（{count} 篇）")
        return True
    except Exception as exc:  # 重建失败不该拖累已下好的字节
        print(f"目录重建失败（附件已下好，手动跑 `link_brain catalog`）：{exc}", file=sys.stderr)
        return False


def _sync_index_status(source_key: str, source_id: str) -> None:
    from . import index as index_mod
    try:
        report = update_status(source_key, source_id)
        conn = index_mod.connect()
        try:
            index_mod.set_attachments_status(conn, report["item_id"], report["status"])
        finally:
            conn.close()
    except (OSError, ValueError, KeyError) as exc:
        print(f"[attachment] 附件状态没写进索引（不影响下载）：{exc}", file=sys.stderr)


GUEST_RETRY_DAYS = 7          # 游客读不到的：7 天内不再用游客看（交给收尾段），之后游客再试一次（口令可能换了）
GUEST_LIMIT = 20
GUEST_LIMIT_BACKLOG = 40      # 她 1008：积压期（没查清 >20 篇）游客段每晚上限提到 40
BACKLOG_THRESHOLD = 20
TAIL_LIMIT = 5                # 她 1008：号正常的晚上收尾段每晚 ≤5 篇
STATUS_NAME = "attachments-recheck-status.json"


def _parse_dt(value, default):
    try:
        return datetime.fromisoformat(str(value)).astimezone()
    except (TypeError, ValueError):
        return default


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _load_backoff(object_dir: Path) -> dict[str, Any]:
    try:
        state = storage.read_json(object_dir / "attachment-state.json")
    except (OSError, ValueError):
        return {}
    data = state.get("download_backoff") if isinstance(state, dict) else None
    return dict(data) if isinstance(data, dict) else {}


def _save_backoff(object_dir: Path, backoff: dict[str, Any]) -> None:
    """退避表跟着 attachment-state.json 走（download_for_object 末尾整份写），这里不单独写。"""
    return None


# ---------------------------------------------------------------- 队列

def _mark_of(obj: Path) -> dict[str, Any]:
    try:
        m = storage.read_json(obj / "derived" / "web_recheck.json")
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _queue_key(path: Path):
    """从没补查过的在前；查过的按上次查的时间轮流（谁最久没查谁先）。"""
    obj = path.parent if path.name == "meta.json" else path
    m = _mark_of(obj)
    if not m:
        return (0, "", obj.name)
    return (1, str(m.get("guest_at") or m.get("checked_at") or ""), obj.name)


def _recent(value, days: int) -> bool:
    at = _parse_dt(value, None)
    return bool(at) and _now_local() - at < timedelta(days=days)


def recheck_queues() -> dict[str, Any]:
    """{guest: [obj], tail: [obj], gone: n, unprobed: n}：游客段要看的、收尾段（登录号）要看的、已判原帖打不开的。"""
    guest, tail, gone = [], [], 0
    for meta_path in _attachment_metas():
        obj = meta_path.parent
        try:
            state = _backend(obj.parent.name).probe_state(obj)
        except (OSError, ValueError, KeyError):
            continue
        if state == "gone":
            gone += 1
            continue
        if state != "unprobed":
            continue
        m = _mark_of(obj)
        if m.get("stage") in ("guest_unseen", "gone_suspected") and _recent(m.get("guest_at"), GUEST_RETRY_DAYS):
            tail.append(obj)
        else:
            guest.append(obj)
    guest.sort(key=_queue_key)
    tail.sort(key=lambda o: (str(_mark_of(o).get("logged_at") or ""), o.name))
    return {"guest": guest, "tail": tail, "gone": gone, "unprobed": len(guest) + len(tail)}


def guest_limit(backlog: int) -> int:
    return GUEST_LIMIT_BACKLOG if backlog > BACKLOG_THRESHOLD else GUEST_LIMIT


# ---------------------------------------------------------------- 本地对账（P0，零联网）

def reconcile() -> dict[str, Any]:
    """纯本地对账（部署当刻跑一次，以后每晚游客段开头也跑）：
    - 补查探到了附件（web_recheck 带 docId）→ 记进对象级声明（_remember_probed），附件检查如实数「未下载」，--all 去下；
      download_error 清掉（下载归 --all 管，带跨夜退避），这篇算查清；
    - 旧记录里游客 + 登录号两路都打不开、登录号落在 /explore 的 → 判「原帖打不开」（gone），PROBE_FAILED 标已解决。
    返回 {cleared, declared, gone}。"""
    out = {"cleared": 0, "declared": 0, "gone": 0}
    for meta_path in _attachment_metas():
        obj = meta_path.parent
        mark_path = obj / "derived" / "web_recheck.json"
        if not mark_path.exists():
            continue
        try:
            m = storage.read_json(mark_path)
            meta = storage.read_json(meta_path)
        except (OSError, ValueError):
            continue
        result = _backend(obj.parent.name).reconcile_object(obj, meta, m)
        for key in out:
            out[key] += result[key]
    return out


# ---------------------------------------------------------------- 状态文件（P4）

def status_path() -> Path:
    return storage.archive_root() / STATUS_NAME


def _read_status() -> dict[str, Any]:
    try:
        st = storage.read_json(status_path())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _eta_date(nights: int) -> str:
    when = _now_local()
    if when.hour >= 4:
        when += timedelta(days=1)
    return (when + timedelta(days=max(0, nights - 1))).strftime("%m-%d")


def status_text(st: dict[str, Any], q: dict[str, Any]) -> str:
    """一行如实的话（面板 / 夜跑日志）：还剩几篇、每晚怎么查、预计哪天查完、上次查了什么 / 为什么没查。"""
    left_g, left_t = len(q["guest"]), len(q["tail"])
    if not left_g and not left_t:
        gone = f"（{q['gone']} 篇原帖打不开，本地存档还在）" if q["gone"] else ""
        return "每篇原网页都查过附件了" + gone
    lim = guest_limit(left_g + left_t)
    parts = []
    if left_g:
        nights = -(-left_g // lim)
        parts.append(f"附件补查：还有 {left_g} 篇没查清原网页有没有附件 · 每晚用游客方式查 {lim} 篇，不用你的号 · "
                     f"预计 {_eta_date(nights)} 查完")
    if left_t:
        parts.append(f"要用登录号看一眼的 {left_t} 篇：号正常的晚上每晚看 {TAIL_LIMIT} 篇（约 {-(-left_t // TAIL_LIMIT)} 晚）")
    g = st.get("guest") or {}
    if g.get("at"):
        why = {"account_hold": "号要验证，按开关今晚游客补查没开页", "hold_too_recent": "刚撞验证不到 1 小时，游客补查今晚没开页",
               "account_busy": "号正被别的任务用着，游客补查让路", "captcha": "游客页出现安全验证，当晚停了",
               "fuse": "连着 2 篇游客读不到，当晚停了", "guest_browser_error": "游客浏览器出错，当晚停了"}.get(
                   str(g.get("stopped_reason") or ""), "")
        parts.append(f"上次 {str(g['at'])[5:16].replace('T', ' ')} 查了 {g.get('checked', 0)} 篇，"
                     f"{len(g.get('found') or [])} 篇发现附件" + (f"（{why}）" if why else ""))
    t = st.get("tail") or {}
    if t.get("skipped"):
        parts.append(f"碰号的补查 {str(t.get('at') or '')[5:16].replace('T', ' ')} 没跑：{t['skipped']}")
    return " · ".join(parts)


def write_recheck_status(phase: str, data: dict[str, Any]) -> dict[str, Any]:
    """记一次补查运行（跑了 / 跳过 / 被拦 / 时间用完都写）。永不抛异常。"""
    try:
        st = _read_status()
        q = recheck_queues()
        entry = {"at": _iso(_now_local()), "phase": phase,
                 **{k: v for k, v in data.items() if k in ("checked", "found", "gone", "guest_unseen", "stopped_reason",
                                                         "skipped", "account_hold", "limit", "reconciled")}}
        if isinstance(entry.get("found"), list):
            entry["found"] = [x.get("id") if isinstance(x, dict) else x for x in entry["found"]][:20]
        st[phase] = entry
        st.update(at=entry["at"], phase=phase, stopped_reason=entry.get("stopped_reason"),
                  skipped=entry.get("skipped"), left_unprobed=len(q["guest"]), tail_pending=len(q["tail"]),
                  gone_total=q["gone"])
        st["eta_nights"] = -(-len(q["guest"]) // guest_limit(q["unprobed"])) + -(-len(q["tail"]) // TAIL_LIMIT)
        st["text"] = status_text(st, q)
        hist = [h for h in (st.get("history") or []) if isinstance(h, dict)][-13:]
        st["history"] = hist + [{k: entry.get(k) for k in ("at", "phase", "checked", "stopped_reason", "skipped")}]
        storage.write_json(status_path(), st)
        try:
            problems_mod.write_summary()
        except Exception:  # noqa: BLE001
            pass
        return st
    except Exception as exc:  # noqa: BLE001
        print(f"[recheck] 状态文件没写上：{exc}", file=sys.stderr)
        return {}


def recheck_status() -> dict[str, Any]:
    """当前的补查状态（读状态文件 + 现数一遍队列），给 --audit / 面板 / 夜跑用。"""
    st = _read_status()
    q = recheck_queues()
    return {**{k: v for k, v in st.items() if k != "history"}, "left_unprobed": len(q["guest"]),
            "tail_pending": len(q["tail"]), "gone_total": q["gone"], "text": status_text(st, q)}


def recheck_eta(item_id: str) -> dict[str, Any]:
    """这一篇在补查队列里的真实位置（repair.describe 写状态句用）：{queue: guest|tail|none, pos, nights, when, skipped}。"""
    sid = domain.short_id(item_id)
    q = recheck_queues()
    st = _read_status()
    for name, lim in (("tail", TAIL_LIMIT), ("guest", guest_limit(q["unprobed"]))):
        ids = [o.name for o in q[name]]
        if sid in ids:
            pos = ids.index(sid) + 1
            nights = -(-pos // lim)
            return {"queue": name, "pos": pos, "nights": nights, "when": _eta_date(nights),
                    "skipped": ((st.get("tail") or {}).get("skipped") if name == "tail" else None),
                    "last_at": (st.get(name) or {}).get("at")}
    return {"queue": "none"}


def _write_mark(obj: Path, **fields: Any) -> dict[str, Any]:
    mark = obj / "derived" / "web_recheck.json"
    mark.parent.mkdir(parents=True, exist_ok=True)
    m = {**_mark_of(obj), **fields}
    storage.write_json(mark, m)
    return m


def _default_source():
    return next(name for name in sources.names() if "attachments" in sources.get(name).capabilities)


def _backend(source_key):
    src = sources.get(source_key)
    return src.attachment_backend() if "attachments" in src.capabilities else None


def _attachment_metas():
    for name in sources.names():
        if "attachments" in sources.get(name).capabilities:
            yield from (storage.archive_root() / name).glob("*/meta.json")


def _looks_blocked(source_key, message):
    backend = _backend(source_key)
    return bool(backend and backend.looks_blocked(message))


def _render_object(*args, **kwargs):
    from . import render
    return render.render_object(*args, **kwargs)


def __getattr__(name):
    if name in _LEGACY_CONSTANTS:
        return getattr(_backend(_default_source()), name)
    raise AttributeError(name)

_LEGACY_CONSTANTS = frozenset({
    'DOWNLOAD_TIMEOUT_SECONDS',
    'FAV_TOKENS_NAME',
    'FRESH_TOKEN_DAYS',
    'GONE_RECHECK_DAYS',
    'GUEST_FUSE_MISSES',
    'GUEST_HOLD_LIMIT',
    'GUEST_HOLD_MIN_GAP_MIN',
    'GUEST_PROBE_SECONDS',
    'LOGGED_PROBE_TIMEOUT_SECONDS',
    'PACE_SECONDS',
    'PROBE_GAP_SECONDS',
    'SERVICE_CODES',
    'SERVICE_DOWN_CODES',
    'TRIES',
})


def _guest_during_hold() -> bool:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source())._guest_during_hold()


def _old_token(obj: Path, meta: dict[str, Any]) -> str | None:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(obj.parent.name)._old_token(obj, meta)


def _open_gap_hi() -> float:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source())._open_gap_hi()


def _pace(attempt: int = 1) -> None:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source())._pace(attempt)


def _probe_logged_in(note_id: str, token: str | None) -> dict[str, Any]:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source())._probe_logged_in(note_id, token)


def _remember_probed(obj: Path, meta: dict[str, Any], doc_id: str, name: str, rf: dict[str, Any]) -> None:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(obj.parent.name)._remember_probed(obj, meta, doc_id, name, rf)


def _restricted_fallback(source_id: str, *, doc_id: str, name: str, xsec_token: str, staging: Path, verbose: bool,
                         budget_left, first: AttachmentRestricted) -> Path:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source())._restricted_fallback(source_id, doc_id=doc_id, name=name, xsec_token=xsec_token, staging=staging, verbose=verbose, budget_left=budget_left, first=first)


def acquire(source_key: str, source_id: str, *, doc_id: str, name: str, xsec_token: str,
            verbose: bool = False, budget_left=None, tries: int | None = None) -> dict[str, Any]:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(source_key).acquire(source_key, source_id, doc_id=doc_id, name=name, xsec_token=xsec_token, verbose=verbose, budget_left=budget_left, tries=tries)


def attempt_cost(attempt: int = 1) -> float:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).attempt_cost(attempt)


def fav_tokens_path() -> Path:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).fav_tokens_path()


def fetch_bytes(
    *,
    doc_id: str,
    note_id: str,
    xsec_token: str,
    file_name: str,
    staging_dir: Path,
    verbose: bool = False,
) -> Path:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).fetch_bytes(doc_id=doc_id, note_id=note_id, xsec_token=xsec_token, file_name=file_name, staging_dir=staging_dir, verbose=verbose)


def fresh_token(note_id: str) -> str | None:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).fresh_token(note_id)


def guest_cost() -> float:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).guest_cost()


def probe_cost() -> float:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).probe_cost()


def probe_state(obj: Path) -> str:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(obj.parent.name).probe_state(obj)


def recheck(*, limit: int = 0, verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).recheck(limit=limit, verbose=verbose, budget_left=budget_left)


def recheck_guest(*, limit: int = 0, verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).recheck_guest(limit=limit, verbose=verbose, budget_left=budget_left)


def recheck_tail(*, limit: int = TAIL_LIMIT, verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).recheck_tail(limit=limit, verbose=verbose, budget_left=budget_left)


def remember_fav_tokens(items: list[dict[str, Any]], *, partial: bool, merge: bool = False) -> int:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).remember_fav_tokens(items, partial=partial, merge=merge)


def resolve_hint(note_id: str, token: str | None) -> dict[str, Any]:
    """旧路径兼容：实际取件由来源能力提供。"""
    return _backend(_default_source()).resolve_hint(note_id, token)
