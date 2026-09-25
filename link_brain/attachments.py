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
            local = local_download(att.get("name") or "")
            if local:
                manual_attach(source_key, source_id, str(local), doc_id)
                record = load_downloaded(source_key, source_id)[doc_id]
                known[doc_id] = record
                results.append({**record, "status": "downloaded"})
                continue
            got = fetch_bytes(
                doc_id=doc_id,
                note_id=source_id,
                xsec_token=note.get("xsec_token") or "",
                file_name=att.get("name") or "file",
                staging_dir=staging,
                verbose=verbose,
            )
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / got.name
            shutil.move(str(got), dest)
            results.append(
                {
                    "doc_id": doc_id,
                    "name": att.get("name") or dest.name,
                    "file": dest.name,
                    "bytes": dest.stat().st_size,
                    "sha256": _sha256(dest),
                    "downloaded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                    "status": "downloaded",
                }
            )
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


def manual_attach(source_key: str, source_id: str, file_path: str, doc_id: str | None = None) -> dict[str, Any]:
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
        "doc_id": (matched or {}).get("doc_id") or "manual-" + re.sub(r"[^\w.-]", "_", src.stem),
        "name": (matched or {}).get("name") or (matched or {}).get("hint") or src.name,
        "file": dest.name,
        "bytes": dest.stat().st_size,
        "sha256": _sha256(dest),
        "downloaded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": "manual",
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

    if getattr(args, "audit", False):
        from .read import dump_json
        rows = [inventory(p.parent) for p in (storage.vault_root() / "_archive" / "xiaohongshu").glob("*/meta.json")]
        dump_json({"items": [r for r in rows if r["total"]], "missing": sum(r["missing"] for r in rows),
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
