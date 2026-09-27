"""笔记附件字节的下载（小红书要登录才给文件）。

为什么非要开浏览器：下载走 `POST https://webapi.rednote.com/web_api/sns/v1/file/download`，
它要 `X-s` / `X-t` / `X-S-Common` 三个签名头，签名逻辑在小红书自己的前端 bundle 里且会变——
本仓不复刻签名，让浏览器自己去发这个请求（`docs/POC-xiaohongshu.md` 第 4 节）。

实测约束（2026-09-04）：
- **必须 headed**。headless 下那个 POST 会一直挂着不返回，页面也不报错。
- 必须先在 profile 的 `Preferences` 里关掉"每次都问保存位置"，否则自动点击会被当成取消。
- 2026-09-25 起改由读取服务下载：与收藏、评论同一个号、同一个浏览器目录，不再需要
  agent-browser 第二套登录（那套会和主会话互相顶号）。只认 xiaohongshu.com 的 /file 页，
  按钮刚出现就点无效，要等预览挂好。

字节落**对象级**目录 `_archive/<source>/<id>/attachments/`，不进 `raw/vNNNN/`——
RAW 版本写完就封存（TASKBOOK 硬约束 4），附件是事后补下来的，不能回头改已封存的版本。
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import alert as alert_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_NEEDS_HUMAN = 5  # 登录态失效 / 安全验证，要人处理（和 ingest 同一套码）

class AttachmentError(RuntimeError):
    """下载附件失败（调用方负责不让它阻断主体归档）。"""


class AttachmentNeedsHuman(AttachmentError):
    """账号要人处理（未登录 / 安全验证）：同一批后面的附件别再试，试了只会再撞一次。"""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def fetch_bytes(
    *,
    doc_id: str,
    note_id: str,
    xsec_token: str,
    file_name: str,
    staging_dir: Path,
    verbose: bool = False,
) -> Path:
    """经读取服务 `/api/v1/attachments/download` 下附件（与收藏/评论同一个号、同一个会话）。

    服务端开有界面的浏览器点附件页的「下载」（headless 下那个下载请求会挂住），
    文件落进 staging_dir。实测细节见 link-brain-reader 的 linkbrain_api.go。
    """
    from . import accounts

    staging_dir.mkdir(parents=True, exist_ok=True)
    if verbose:
        print(f"[attachment] 下载 {file_name} ({doc_id})", file=sys.stderr)
    try:
        accounts.ensure_reader()
        data = accounts.api("POST", "/api/v1/attachments/download", timeout=240, body={
            "doc_id": doc_id, "note_id": note_id, "xsec_token": xsec_token,
            "file_name": file_name, "dest_dir": str(staging_dir.resolve())})
    except accounts.ReaderError as exc:
        _, reason, step, _ = accounts.SOLUTIONS.get(exc.code, ("", str(exc), "", ""))
        text = f"{reason}：{step}" if step else f"{exc} {exc.detail}".strip()
        if exc.needs_human:
            raise AttachmentNeedsHuman(text, exc.code) from exc
        raise AttachmentError(text) from exc
    path = Path(data["path"])
    if not path.is_file() or path.stat().st_size == 0:
        raise AttachmentError(f"读取服务报告已下载，但文件不存在：{path}")
    return path


# 0927 防风控：一次只开一个附件页，两次之间像人一样随机隔 1.5–4 分钟（重试时再翻倍拉长）。
# 上次开页时刻落盘，跨进程也算（每晚 attachments 与 --recheck 背靠背跑，别在交界处连开）。
PACE_SECONDS = tuple(float(x) for x in os.environ.get("LWA_ATTACH_PACE", "90,240").split(","))
TRIES = max(1, int(os.environ.get("LWA_ATTACH_TRIES", "3")))
_MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK", ".pptx": b"PK", ".zip": b"PK"}


def _pace(attempt: int = 1) -> None:
    from . import accounts
    stamp = accounts.home() / "attach-last-fetch.txt"
    try:
        last = float(stamp.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        last = 0.0
    wait = random.uniform(*PACE_SECONDS) * attempt - (time.time() - last)
    if wait > 0:
        print(f"[attachment] 像人一样歇 {wait:.0f} 秒再开下一个附件页", file=sys.stderr)
        time.sleep(wait)
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


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


def acquire(source_key: str, source_id: str, *, doc_id: str, name: str, xsec_token: str,
            verbose: bool = False) -> dict[str, Any]:
    """下一份附件，并验到『文件完整 + 能转成 md』为止；不行就删掉、歇更久、重下，最多 TRIES 次。

    账号要人处理（未登录 / 安全验证）直接抛 AttachmentNeedsHuman，绝不重试。
    """
    from .pdftext import convert_object_attachments

    object_dir = storage.object_dir(source_key, source_id)
    staging = object_dir / ".attachment-staging"
    last_error = ""
    for attempt in range(1, TRIES + 1):
        _pace(attempt)
        try:
            got = fetch_bytes(doc_id=doc_id, note_id=source_id, xsec_token=xsec_token,
                              file_name=name or "file", staging_dir=staging, verbose=verbose)
            _check_file(got)
            out = manual_attach(source_key, source_id, str(got), doc_id, origin="auto")
            record = next(r for r in load_downloaded(source_key, source_id).values() if r.get("file") == out["file"])
            try:
                bad = [r for r in convert_object_attachments(source_key, source_id)
                       if r["doc_id"] == record["doc_id"] and r["status"] == "failed"]
            except Exception as exc:  # noqa: BLE001 - 打不开的文件 pymupdf 直接抛
                bad = [{"note": f"{type(exc).__name__}: {exc}"}]
            if not bad:
                return record
            last_error = f"转 md 失败：{bad[0].get('note') or ''}"
            (object_dir / "attachments" / record["file"]).unlink(missing_ok=True)
        except AttachmentNeedsHuman:
            raise
        except (AttachmentError, OSError, StopIteration, KeyError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        print(f"[attachment] 第 {attempt}/{TRIES} 次没成：{last_error}", file=sys.stderr)
    raise AttachmentError(f"试了 {TRIES} 次仍不行：{last_error}")


def grab_after_ingest(source_key: str, source_id: str) -> None:
    """入库（ob 导入 / 同步收藏）后顺手把这篇的附件下好，不等半夜。出错只记，不影响入库。"""
    try:
        object_dir = storage.object_dir(source_key, source_id)
        if not inventory(object_dir)["missing"]:
            return
        outcome = download_for_object(source_key, source_id, verbose=True)
        from . import index as index_mod, render as render_mod
        render_mod.render_object(source_key, source_id)
        meta = storage.read_json(object_dir / "meta.json")
        conn = index_mod.connect()
        try:
            index_mod.set_attachments_status(conn, meta["item_id"], meta.get("attachments_status"))
        finally:
            conn.close()
        for r in outcome["results"]:
            if r["status"] == "failed":
                blocked = bool(r.get("code"))
                alert_mod.alert(alert_mod.KIND_ACCOUNT if blocked else alert_mod.KIND_ATTACHMENT,
                                "附件没拿到" + ("（账号要处理：登录/安全验证）" if blocked else "（今晚 4 点会再补）"),
                                f"{outcome['item_id']}: {str(r.get('error'))[:300]}", item_id=outcome["item_id"])
    except Exception as exc:  # noqa: BLE001 - 附件是锦上添花，别拖垮已落盘的归档
        print(f"[attachment] 入库后顺手下附件出错（今晚 4 点会再补）：{exc}", file=sys.stderr)


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


def inventory(object_dir: Path, meta=None) -> dict[str, Any]:
    """Count every declared file; a lone file cannot mark the whole note complete."""
    meta = meta or storage.read_json(object_dir / "meta.json")
    source_path = object_dir / "raw" / f"v{meta['current_version']:04d}" / "source.json"
    source = storage.read_json(source_path) if source_path.exists() else {}
    declared = (source.get("note") or {}).get("attachments") or []
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
        files.append({"doc_id": doc_id, "name": att.get("name") or att.get("hint") or "附件",
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
    meta["attachments_status"] = report["status"]
    storage.write_json(obj / "meta.json", meta)
    return report


def convert_downloads(source_key, source_id):
    from .pdftext import convert_object_attachments
    rows = convert_object_attachments(source_key, source_id)
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
    source_key: str, source_id: str, *, force: bool = False, verbose: bool = False
) -> dict[str, Any]:
    """把一个对象的附件字节下下来，落对象级 `attachments/` 并写 `attachments.json`。

    不动任何 `raw/vNNNN/`（版本一旦写完就封存）。失败只返回 error，不抛给调用方之外。
    """
    object_dir = storage.object_dir(source_key, source_id)
    meta_path = object_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"没有归档过: {source_key}/{source_id}")
    meta = storage.read_json(meta_path)
    version = meta["current_version"]
    source_doc = storage.read_json(storage.raw_dir(source_key, source_id, version) / "source.json")
    note = source_doc["note"]
    attachments = note.get("attachments") or []

    known = load_downloaded(source_key, source_id)
    results: list[dict[str, Any]] = []
    dest_dir = object_dir / "attachments"
    staging = object_dir / ".attachment-staging"

    for att in attachments:
        doc_id = att.get("doc_id")
        if not doc_id:
            results.append({"doc_id": None, "status": "skipped", "error": "没有 doc_id（只有正文线索）"})
            continue
        if not force and doc_id in known and (dest_dir / known[doc_id]["file"]).is_file() and (dest_dir / known[doc_id]["file"]).stat().st_size > 0:
            results.append({**known[doc_id], "status": "already"})
            continue
        try:
            local = (None if force else _have_by_name(object_dir, att.get("name") or "")) or local_download(att.get("name") or "")
            if local:
                manual_attach(source_key, source_id, str(local), doc_id)
                record = load_downloaded(source_key, source_id)[doc_id]
                known[doc_id] = record
                results.append({**record, "status": "downloaded"})
                continue
            record = acquire(source_key, source_id, doc_id=doc_id, name=att.get("name") or "file",
                             xsec_token=note.get("xsec_token") or "", verbose=verbose)
            known = load_downloaded(source_key, source_id)
            results.append({**record, "status": "downloaded"})
        except AttachmentNeedsHuman as exc:
            results.append({"doc_id": doc_id, "status": "failed", "error": str(exc), "code": exc.code})
            break  # 账号要人处理：余下附件等处理完再补
        except (AttachmentError, subprocess.SubprocessError, OSError) as exc:
            results.append({"doc_id": doc_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})

    if staging.exists() and not any(staging.iterdir()):
        staging.rmdir()

    merged = dict(known)
    merged.update({r["doc_id"]: dict(known.get(r["doc_id"], {}), **r) for r in results if r.get("status") in ("downloaded", "already")})
    files = list(merged.values())
    for f in files:
        f.pop("status", None)
    if files:
        storage.write_json(
            attachments_path(source_key, source_id), {"schema_version": 1, "files": files}
        )
    update_status(source_key, source_id)

    storage.write_json(object_dir / "attachment-state.json", {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "errors": [{"doc_id": r.get("doc_id"), "error": r.get("error")} for r in results if r["status"] in {"failed", "skipped"}],
    })

    return {"item_id": meta["item_id"], "results": results}


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
    declared = (source_doc.get("note") or {}).get("attachments") or []

    dest_dir = object_dir / "attachments"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)

    # 按文件名认领元数据里声明过的 doc_id（认不出就当 manual）
    matched = next((a for a in declared if (doc_id and a.get("doc_id") == doc_id) or (a.get("name") or "") == src.name), None)
    if not matched and len(declared) == 1:
        matched = declared[0]
    record = {
        # 调用方给了真 doc_id 就用它（0927：recheck 下的附件元数据里没声明过，旧逻辑记成 manual-… 对不上号，每晚重下）
        "doc_id": (matched or {}).get("doc_id") or doc_id or "manual-" + re.sub(r"[^\w.-]", "_", src.stem),
        "name": (matched or {}).get("name") or (matched or {}).get("hint") or src.name,
        "file": dest.name,
        "bytes": dest.stat().st_size,
        "sha256": _sha256(dest),
        "downloaded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": origin,
    }
    known = load_downloaded(source_key, source_id)
    files = [v for k, v in known.items() if v.get("file") != dest.name and k != record["doc_id"]]
    files.append(record)
    storage.write_json(attachments_path(source_key, source_id), {"schema_version": 1, "files": files})
    report = update_status(source_key, source_id)
    state_path = object_dir / "attachment-state.json"
    if state_path.exists():
        state = storage.read_json(state_path)
        state["errors"] = [r for r in state.get("errors", []) if r.get("doc_id") != record["doc_id"]]
        storage.write_json(state_path, state)
    return {"item_id": meta["item_id"], "file": dest.name, "bytes": record["bytes"], "status": report["status"]}


def run(args) -> int:
    from . import index as index_mod

    if getattr(args, "recheck", False):
        from .read import dump_json
        dump_json(recheck(limit=getattr(args, "limit", 0) or 0, verbose=True))
        return 0
    if getattr(args, "audit", False):
        from .read import dump_json
        metas = list((storage.vault_root() / "_archive" / "xiaohongshu").glob("*/meta.json"))
        rows = [inventory(p.parent) for p in metas]
        unprobed = [p.parent.name for p in metas if probe_state(p.parent) == "unprobed"]
        dump_json({"items": [r for r in rows if r["total"]], "missing": sum(r["missing"] for r in rows),
                   "unprobed": len(unprobed), "unprobed_ids": unprobed,
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
    for source_key, source_id in targets:
        outcome = download_for_object(
            source_key, source_id, force=getattr(args, "force", False), verbose=getattr(args, "verbose", False)
        )
        for r in outcome["results"]:
            if r["status"] == "downloaded":
                any_downloaded = True
                print(f"{outcome['item_id']}  ↓ {r['file']}  {r['bytes']} 字节  {r['sha256'][:12]}…")
            elif r["status"] == "already":
                print(f"{outcome['item_id']}  = {r['file']}（已有，--force 可重下）")
            elif r["status"] == "skipped":
                print(f"{outcome['item_id']}  - {r.get('error')}", file=sys.stderr)
            else:
                failed = True
                message = str(r.get("error") or "")
                print(f"{outcome['item_id']}  ✗ {message}", file=sys.stderr)
                # 附件要登录态，挂了很可能是掉线/撞风控 —— 这种不能默默地就过去了
                blocked = bool(r.get("code")) or xhs.looks_blocked(message)
                alert_mod.alert(
                    alert_mod.KIND_ACCOUNT if blocked else alert_mod.KIND_ATTACHMENT,
                    "附件没拿到" + ("（账号要处理：登录/安全验证）" if blocked else ""),
                    f"{outcome['item_id']}: {message[:300]}",
                    item_id=outcome["item_id"],
                )
                if blocked:
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
            print("停车：小红书账号要处理（扫码登录或安全验证），剩下的附件处理完再补", file=sys.stderr)
            return EXIT_NEEDS_HUMAN

    # 下到了新字节就重建目录，否则 UI 角标还停在「待补」（补跑却没同步就是这坑）
    rebuilt = _rebuild_catalog(True)
    pending = sum(inventory(storage.object_dir(source_key, source_id))["missing"] for source_key, source_id in targets)
    if pending:
        print(f"仍有 {pending} 个附件或附件线索待处理，请在目录打开待补面板。", file=sys.stderr)
    return 1 if failed or not rebuilt else 2 if pending else 0


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


def probe_state(obj: Path) -> str:
    """这篇原网页有没有附件，查清了没有（0927 闭环）。

    checked = 入库时网页探测成功，或补查成功且没有未完成的下载；
    unprobed = 入库时被挡 / 早期入库根本没探过 / 补查下到一半失败——都要（再）查；
    补查过但游客也读不到的仍算 unprobed，每晚重试，直到读到或她删掉这篇。
    """
    mark = obj / "derived" / "web_recheck.json"
    if mark.exists():
        m = storage.read_json(mark)
        if m.get("ok") and not m.get("download_error"):
            return "checked"
        return "unprobed"
    meta = storage.read_json(obj / "meta.json")
    web = storage.raw_dir("xiaohongshu", obj.name, meta["current_version"]) / "web_raw.json"
    return "checked" if web.exists() and storage.read_json(web).get("ok") else "unprobed"


def recheck(*, limit: int = 0, verbose: bool = False) -> dict[str, Any]:
    """补查「当时没探到附件」的笔记（0926）。

    入库时网页探测拿到反爬占位页 → web_raw.json ok=false，被当成「没附件」静默跳过，不报警、audit 也看不见
    （9-18 才加的游客浏览器兜底对之前入库的不生效）。这里对这些笔记重新探测（httpx → 游客浏览器），
    探到就下字节并挂上；结果记 derived/web_recheck.json，探明的不再重复查。仍探不到的汇总报警。
    """
    from .adapters import xiaohongshu as xhs
    from . import alert as alert_mod, render as render_mod
    base = storage.vault_root() / "_archive" / "xiaohongshu"
    found, failed, checked = [], [], 0
    # 从没补查过的排前面，游客也读不到的排后面，免得它们每晚占满名额
    for meta_path in sorted(base.glob("*/meta.json"),
                            key=lambda p: ((p.parent / "derived" / "web_recheck.json").exists(), p.parent.name)):
        obj = meta_path.parent
        source_id = obj.name
        mark = obj / "derived" / "web_recheck.json"
        if probe_state(obj) != "unprobed":
            continue
        meta = storage.read_json(meta_path)
        raw = storage.raw_dir("xiaohongshu", source_id, meta["current_version"])
        web = raw / "web_raw.json"
        if limit and checked >= limit:
            break
        checked += 1
        url = storage.read_json(web).get("url") or "" if web.exists() else ""
        token = (re.search(r"xsec_token=([^&]+)", url) or [None, None])[1]
        if token:
            from urllib.parse import unquote
            token = unquote(token)
        else:  # 0927：早期入库没留 web_raw 的，从 source.json 拿 token
            src = raw / "source.json"
            token = (storage.read_json(src).get("note") or {}).get("xsec_token") if src.exists() else None
        probe = xhs.fetch_related_file(source_id, token)
        rf = probe.get("related_file") or {}
        storage.write_json(mark, {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ok": bool(probe.get("ok")),
                                  "related_file": rf or None, "error": probe.get("error")})
        if not probe.get("ok"):
            failed.append({"id": source_id, "error": (probe.get("error") or "")[:120]})
            continue
        doc_id = str(rf.get("docId") or "")
        if not doc_id or doc_id in load_downloaded("xiaohongshu", source_id):
            continue
        name = rf.get("name") or f"{doc_id}.bin"
        have = _have_by_name(obj, name)
        if have:  # 以前手动挂过（记成 manual-…）：认回真 doc_id，不上网
            manual_attach("xiaohongshu", source_id, str(have), doc_id)
            convert_downloads("xiaohongshu", source_id)
            render_mod.render_object("xiaohongshu", source_id)
            continue
        try:
            acquire("xiaohongshu", source_id, doc_id=doc_id, name=name, xsec_token=token or "", verbose=verbose)
            render_mod.render_object("xiaohongshu", source_id)
            found.append({"id": source_id, "file": name})
        except AttachmentNeedsHuman as exc:
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            alert_mod.alert(alert_mod.KIND_ACCOUNT, "附件没拿到（账号要处理：登录/安全验证）", f"{source_id}: {exc}"[:300])
            break  # 撞验证就停，绝不接着开页
        except (AttachmentError, OSError, KeyError, ValueError) as exc:
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            failed.append({"id": source_id, "error": f"{name} 下载失败：{exc}"[:160]})
    if failed:
        alert_mod.alert("normal", f"附件补查：{len(failed)} 篇没查清",
                        "；".join(f"{f['id']} {f['error']}" for f in failed[:5]) + ("…" if len(failed) > 5 else ""))
    if found:
        _rebuild_catalog(True)
    return {"checked": checked, "found": found, "failed": failed}
