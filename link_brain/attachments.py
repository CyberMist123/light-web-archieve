"""笔记附件字节的下载（小红书要登录才给文件）。

为什么非要开浏览器：下载走 `POST https://webapi.rednote.com/web_api/sns/v1/file/download`，
它要 `X-s` / `X-t` / `X-S-Common` 三个签名头，签名逻辑在小红书自己的前端 bundle 里且会变——
本仓不复刻签名，让浏览器自己去发这个请求（`docs/POC-xiaohongshu.md` 第 4 节）。

实测约束（2026-09-04）：
- **必须 headed**。headless 下那个 POST 会一直挂着不返回，页面也不报错。
- 必须先在 profile 的 `Preferences` 里关掉"每次都问保存位置"，否则自动点击会被当成取消。
- 用的是 agent-browser 的**小号** profile；主号在 18060 MCP 那侧，两边不能同时在线。
- `agent-browser open <url>` 在登录态的小红书页面上会卡住不返回（页面不进 idle），
  所以一律 `open` 空白页再用 `eval` 改 `location.href` 导航。

字节落**对象级**目录 `_archive/<source>/<id>/attachments/`，不进 `raw/vNNNN/`——
RAW 版本写完就封存（TASKBOOK 硬约束 4），附件是事后补下来的，不能回头改已封存的版本。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import alert as alert_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_NEEDS_HUMAN = 5  # 小号登录态失效 / 风控，要人处理（和 ingest 同一套码）

PROFILE_PREFS = Path(r"C:\Users\18717\Tools\agent-browser\profile\Default\Preferences")
FILE_PAGE_FMT = (
    "https://www.rednote.com/file/{doc_id}"
    "?noteId={note_id}&fileName={file_name}&xsec_token={xsec_token}&xsec_source=note_detail_file"
)
DOWNLOAD_BUTTON_RE = re.compile(r"下载.*?\[ref=(e\d+)\]")
SNAPSHOT_TIMEOUT = 90
NAV_SETTLE_MS = 9000
DOWNLOAD_WAIT_SEC = 90


class AttachmentError(RuntimeError):
    """下载附件失败（调用方负责不让它阻断主体归档）。"""


def _agent_browser_exe() -> str:
    """Windows 上 npm 装的是 `agent-browser.cmd`，subprocess 不认那个无扩展名的 shim。"""
    for name in ("agent-browser.cmd", "agent-browser.exe", "agent-browser"):
        found = shutil.which(name)
        if found:
            return found
    fallback = Path.home() / "AppData" / "Roaming" / "npm" / "agent-browser.cmd"
    if fallback.exists():
        return str(fallback)
    raise AttachmentError("PATH 里找不到 agent-browser（附件下载要靠它带登录态）")


def _ab(args: list[str], *, timeout: int) -> tuple[int | None, str]:
    """跑一条 agent-browser 命令，返回 `(returncode, stdout)`；超时就杀掉整棵进程树。

    **不要换回 `subprocess.run(capture_output=True, timeout=...)`**：Windows 上入口是
    `agent-browser.cmd`，超时只杀得掉外层 `cmd.exe`，底下的 node 还攥着管道，
    `run()` 会一直等管道关闭——超时形同虚设，整个命令永远挂住（2026-09-04 踩过）。
    所以这里把输出重定向到临时文件，超时后 `taskkill /T /F` 连子孙进程一起杀。
    """
    fd, name = tempfile.mkstemp(prefix="link-brain-ab-", suffix=".txt")
    os.close(fd)  # 不关掉这个句柄，后面 unlink 会 WinError 32
    out_file = Path(name)
    handle = out_file.open("w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            [_agent_browser_exe(), *args], stdout=handle, stderr=subprocess.STDOUT
        )
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=30,
            )
            proc.wait(timeout=15)
            code = None
    finally:
        handle.close()
    text = out_file.read_text(encoding="utf-8", errors="replace")
    try:
        out_file.unlink(missing_ok=True)
    except OSError:  # 临时文件删不掉不该影响结果
        pass
    return code, text


def ensure_download_prefs(dest_dir: Path) -> None:
    """关掉"每次都问保存位置"并把默认下载目录指到 dest_dir。

    Chrome 开着时 Preferences 会被回写覆盖，所以调用前要先 `close --all`。
    """
    if not PROFILE_PREFS.exists():
        raise AttachmentError(f"找不到 agent-browser profile 的 Preferences: {PROFILE_PREFS}")
    prefs = json.loads(PROFILE_PREFS.read_text(encoding="utf-8"))
    download = prefs.setdefault("download", {})
    download["prompt_for_download"] = False
    download["default_directory"] = str(dest_dir)
    prefs.setdefault("savefile", {})["default_directory"] = str(dest_dir)
    PROFILE_PREFS.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")


def _wait_for_download(dest_dir: Path, before: set[Path], *, timeout: int) -> Path:
    """等下载目录里冒出一个新文件（跳过 Chrome 的 .crdownload 临时文件）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = {p for p in dest_dir.iterdir() if p.is_file()}
        fresh = [p for p in current - before if p.suffix != ".crdownload"]
        if fresh:
            newest = max(fresh, key=lambda p: p.stat().st_mtime)
            size = -1
            # 等文件大小稳定，避免读到写了一半的
            while time.time() < deadline:
                now = newest.stat().st_size
                if now == size and now > 0:
                    return newest
                size = now
                time.sleep(1)
        time.sleep(1)
    raise AttachmentError(f"等了 {timeout}s 下载目录里没有出现新文件")


def fetch_bytes(
    *,
    doc_id: str,
    note_id: str,
    xsec_token: str,
    file_name: str,
    staging_dir: Path,
    verbose: bool = False,
) -> Path:
    """用 agent-browser（headed，小号登录态）把附件下到 staging_dir，返回文件路径。"""
    staging_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        if verbose:
            print(f"[attachment] {msg}", file=sys.stderr)

    _ab(["close", "--all"], timeout=60)
    ensure_download_prefs(staging_dir)

    before = {p for p in staging_dir.iterdir() if p.is_file()}

    log("启动 headed 浏览器（headless 下那个下载 POST 会挂住）")
    code, out = _ab(["open", "--headed"], timeout=90)
    if code not in (0, None):
        raise AttachmentError(f"agent-browser open 失败: {out[:200]}")

    url = FILE_PAGE_FMT.format(
        doc_id=doc_id, note_id=note_id, file_name=file_name, xsec_token=xsec_token
    )
    log(f"导航 {url[:90]}…")
    # 不用 open <url>：登录态的小红书页面不进 idle，open 会一直不返回
    _ab(["eval", f'location.href={json.dumps(url)};"go"'], timeout=60)
    _ab(["wait", str(NAV_SETTLE_MS)], timeout=NAV_SETTLE_MS // 1000 + 30)

    _, snapshot = _ab(["snapshot", "-i", "-c"], timeout=SNAPSHOT_TIMEOUT)
    match = DOWNLOAD_BUTTON_RE.search(snapshot)
    if not match:
        raise AttachmentError(
            "页面上找不到「下载」按钮——多半是这个 profile 没登录（或小号没权限）；"
            "先跑 `agent-browser open --headed <笔记URL>` 人工看一眼"
        )
    ref = match.group(1)
    log(f"点下载按钮 @{ref}")
    _ab(["click", f"@{ref}"], timeout=90)

    path = _wait_for_download(staging_dir, before, timeout=DOWNLOAD_WAIT_SEC)
    log(f"下到 {path.name}（{path.stat().st_size} 字节）")
    _ab(["close", "--all"], timeout=60)
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
        if not force and doc_id in known and (dest_dir / known[doc_id]["file"]).exists():
            results.append({**known[doc_id], "status": "already"})
            continue
        try:
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
        except (AttachmentError, subprocess.SubprocessError, OSError) as exc:
            results.append({"doc_id": doc_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})

    if staging.exists() and not any(staging.iterdir()):
        staging.rmdir()

    files = [dict(known.get(r["doc_id"], {}), **r) for r in results if r.get("status") in ("downloaded", "already")]
    for f in files:
        f.pop("status", None)
    if files:
        storage.write_json(
            attachments_path(source_key, source_id), {"schema_version": 1, "files": files}
        )
        meta["attachments_status"] = "downloaded"
        storage.write_json(meta_path, meta)

    return {"item_id": meta["item_id"], "results": results}


def run(args) -> int:
    from . import index as index_mod

    conn = index_mod.connect()
    try:
        if getattr(args, "all", False):
            rows = conn.execute(
                "SELECT source, source_id FROM objects WHERE attachments_status IN "
                "('metadata_only', 'downloaded') ORDER BY item_id"
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
    for source_key, source_id in targets:
        outcome = download_for_object(
            source_key, source_id, force=getattr(args, "force", False), verbose=getattr(args, "verbose", False)
        )
        for r in outcome["results"]:
            if r["status"] == "downloaded":
                print(f"{outcome['item_id']}  ↓ {r['file']}  {r['bytes']} 字节  {r['sha256'][:12]}…")
            elif r["status"] == "already":
                print(f"{outcome['item_id']}  = {r['file']}（已有，--force 可重下）")
            elif r["status"] == "skipped":
                print(f"{outcome['item_id']}  - {r.get('error')}", file=sys.stderr)
            else:
                failed = True
                message = str(r.get("error") or "")
                print(f"{outcome['item_id']}  ✗ {message}", file=sys.stderr)
                # 附件要登录态，挂了很可能是小号掉线/撞风控 —— 这种不能默默地就过去了
                blocked = xhs.looks_blocked(message)
                alert_mod.alert(
                    alert_mod.KIND_ACCOUNT if blocked else alert_mod.KIND_ATTACHMENT,
                    "附件没拿到" + ("（小号登录态/风控）" if blocked else ""),
                    f"{outcome['item_id']}: {message[:300]}",
                    item_id=outcome["item_id"],
                )
                if blocked:
                    account_blocked = True
        render_mod.render_object(source_key, source_id)
        if account_blocked:
            print("停车：小号登录态/风控，剩下的不再试", file=sys.stderr)
            return EXIT_NEEDS_HUMAN

    return 1 if failed else 0
