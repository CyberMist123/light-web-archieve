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
事后解析出的附件编号同理，记对象级 `attachments-resolved.json`（1001，审计 raw-1）。
"""

from __future__ import annotations

import httpx
import json
import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import problems as problems_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_NEEDS_HUMAN = 5  # 登录态失效 / 安全验证，要人处理（和 ingest 同一套码）

class AttachmentError(RuntimeError):
    """下载附件失败（调用方负责不让它阻断主体归档）。"""


class AttachmentNeedsHuman(AttachmentError):
    """账号要人处理（未登录 / 安全验证）：同一批后面的附件别再试，试了只会再撞一次。"""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class AttachmentDeferred(Exception):
    """这一批的时间预算不够再开一个附件页了（1001）：不算失败，留给下一次（今晚 4 点 / 明晚）。"""


# 1001 时间预算：夜跑每一步外面都有限时（超时整棵杀）。开一个附件页 / 登录号补看之前，先确认剩下的时间
# 装得下这一步的最坏耗时；装不下就收手、正常收尾（重建目录、汇总），别在读取服务那侧下载到一半被杀。
DOWNLOAD_TIMEOUT_SECONDS = 240
LOGGED_PROBE_TIMEOUT_SECONDS = 150
GUEST_PROBE_SECONDS = 90


def _clock() -> float:
    return time.monotonic()


def budget_from_minutes(minutes: float | None):
    """`--budget-min N` → 返回「还剩几秒」的函数；0 / None = 不限（返回 None）。"""
    if not minutes or float(minutes) <= 0:
        return None
    deadline = _clock() + float(minutes) * 60
    return lambda: deadline - _clock()


def _open_gap_hi() -> float:
    from . import accounts
    return accounts._gap_range("LWA_OPEN_GAP", "20,40")[1]


def attempt_cost(attempt: int = 1) -> float:
    """下一个附件（第 attempt 次）最坏要多久：歇够 + 开页间隔 + 下载超时 + 校验转 md 的余量。"""
    return PACE_SECONDS[1] * attempt + _open_gap_hi() + DOWNLOAD_TIMEOUT_SECONDS + 60


def probe_cost() -> float:
    """补查一篇最坏要多久：探测间隔 + 游客探测 + 开页间隔 + 登录号补看超时。"""
    return PROBE_GAP_SECONDS[1] + GUEST_PROBE_SECONDS + _open_gap_hi() + LOGGED_PROBE_TIMEOUT_SECONDS


def _fits(budget_left, need: float) -> bool:
    return budget_left is None or budget_left() >= need


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
        data = accounts.api("POST", "/api/v1/attachments/download", timeout=DOWNLOAD_TIMEOUT_SECONDS, body={
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
    accounts.pace("开附件页")  # 1001：再和所有碰号的开页（笔记详情、补看、读收藏）共用 20–40 秒间隔
    try:
        accounts._atomic_write_text(stamp, str(time.time()))
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
            verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """下一份附件，验到『文件头对得上类型』为止；半截 / 网页占位页就歇更久、重下，最多 TRIES 次。

    1001（审计 attach-4）：文件头校验通过就算下好了。转 md 失败（加密 / 损坏 / 扫描件空白页）不再删字节重下——
    那样每晚开 3 次附件页、永远循环；字节留着，记录上标 conversion_failed，报警给人看。
    账号要人处理（未登录 / 安全验证）直接抛 AttachmentNeedsHuman，绝不重试。
    budget_left（1001）：剩下的时间装不下下一次尝试的最坏耗时 → 抛 AttachmentDeferred（不算失败）。
    """
    from .pdftext import convert_object_attachments

    object_dir = storage.object_dir(source_key, source_id)
    staging = object_dir / ".attachment-staging"
    last_error = ""
    for attempt in range(1, TRIES + 1):
        if not _fits(budget_left, attempt_cost(attempt)):
            raise AttachmentDeferred(f"时间预算不够再开附件页了（{name}），下次接着下"
                                     + (f"；前一次：{last_error}" if last_error else ""))
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
            except Exception as exc:  # noqa: BLE001 - 转换出意外也不该让已下好的字节作废
                bad = [{"note": f"{type(exc).__name__}: {exc}"}]
                next_at = mark_conversion(source_key, source_id, record["doc_id"], bad[0]["note"],
                                          code="TRANSIENT.SERVICE_BUSY")
                problems_mod.report("attachments.convert", "TRANSIENT.SERVICE_BUSY",
                                    f"{record.get('file')}：{bad[0]['note']}"[:200], item_id=f"xhs-{source_id}",
                                    next_at=next_at)
            if bad:
                # 第 4 批：不推送。转换失败已按码登记（加密 / 损坏 PERMANENT，卡片标「全文没转出来」；
                # OCR 故障 / 超时 TRANSIENT，按 next_at 退避自动再转）
                print(f"[attachment] {record['file']} 已下好，但转 md 失败（字节留着，不再重下）："
                      f"{bad[0].get('note') or ''}", file=sys.stderr)
            return load_downloaded(source_key, source_id).get(record["doc_id"], record)
        except AttachmentNeedsHuman:
            raise
        except (AttachmentError, OSError, StopIteration, KeyError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        print(f"[attachment] 第 {attempt}/{TRIES} 次没成：{last_error}", file=sys.stderr)
    raise AttachmentError(f"试了 {TRIES} 次仍不行：{last_error}")


def grab_after_ingest(source_key: str, source_id: str, *, budget_left=None) -> str:
    """入库（ob 导入 / 同步收藏）后顺手把这篇的附件下好，不等半夜。出错只记，不影响入库。

    返回值（1001）：下载时撞到要人处理的码（掉登录 / 验证 / 风控 / 熔断）就返回那个码，调用方据此整批停车；
    否则返回空串。budget_left：同步的剩余时间，装不下下一个附件就留给 4 点的 `attachments --all`。
    """
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
    meta["attachments_status"] = report["status"]
    storage.write_json(obj / "meta.json", meta)
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
    version = meta["current_version"]
    source_doc = storage.read_json(storage.raw_dir(source_key, source_id, version) / "source.json")
    note = source_doc["note"]
    attachments = declared_attachments(object_dir, source_doc)

    known = load_downloaded(source_key, source_id)
    results: list[dict[str, Any]] = []
    dest_dir = object_dir / "attachments"
    staging = object_dir / ".attachment-staging"

    for att in attachments:
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
            if not _fits(budget_left, probe_cost()):
                results.append({"doc_id": None, "name": att.get("hint"), "status": "deferred",
                                "error": "时间预算不够再去笔记页找附件了，下次接着找"})
                break
            found = resolve_hint(source_id, note.get("xsec_token"))
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
            record = acquire(source_key, source_id, doc_id=doc_id, name=att.get("name") or "file",
                             xsec_token=note.get("xsec_token") or "", verbose=verbose, budget_left=budget_left)
            known = load_downloaded(source_key, source_id)
            results.append({**record, "status": "downloaded"})
        except AttachmentDeferred as exc:
            results.append({"doc_id": doc_id, "name": att.get("name"), "status": "deferred", "error": str(exc)})
            break  # 时间到了：余下的附件下次再下
        except AttachmentNeedsHuman as exc:
            results.append({"doc_id": doc_id, "status": "failed", "error": str(exc), "code": exc.code})
            break  # 账号要人处理：余下附件等处理完再补
        except (AttachmentError, subprocess.SubprocessError, OSError) as exc:
            results.append({"doc_id": doc_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})

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
        "errors": errors,
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
            if r.get("code") or xhs.looks_blocked(message):
                problems_mod.report_blocked("attachments.download", r.get("code") or "", f"下附件时：{message}"[:200])
            else:
                problems_mod.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", f"{name}：{message}"[:200],
                                    item_id=item_id, title=title)
        if not failed and not any(r.get("status") == "deferred" for r in results):
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


def resolve_hint(note_id: str, token: str | None) -> dict[str, Any]:
    """正文线索 → 真附件：先游客看，游客被挡再用登录号看。返回 {doc_id,name,url,...} 或 {error}。"""
    from .adapters import xiaohongshu as xhs
    probe = xhs.fetch_related_file(note_id, token)
    if not probe.get("ok"):
        logged = _probe_logged_in(note_id, token)
        if logged.get("needs_human"):
            return {"error": str(logged.get("error"))[:300], "needs_human": True, "code": logged.get("code")}
        if not logged.get("ok"):
            return {"error": f"游客：{probe.get('error')}；登录号：{logged.get('error')}"[:300]}
        probe = logged
    rf = probe.get("related_file") or {}
    if not rf.get("docId"):
        return {"error": "笔记页上确实没挂文件（作者可能放在评论区或别处）"}
    try:
        extra = json.loads(rf.get("bizExtra") or "{}")
    except (TypeError, ValueError):
        extra = {}
    doc_id = str(rf["docId"])
    return {"doc_id": doc_id, "name": rf.get("name") or f"{doc_id}.bin", "status": "metadata_only",
            "url": xhs.FILE_PREVIEW_FMT.format(doc_id=doc_id), "page_num": extra.get("page_num")}


def describe_problem(source_key: str, source_id: str, file_name: str | None, reason: str) -> str:
    """一条没下好的附件 = 哪篇 + 哪个文件 + 为什么 + 单项重跑命令（0929 Owner：别概括报错）。"""
    try:
        meta = storage.read_json(storage.object_dir(source_key, source_id) / "meta.json")
    except (OSError, ValueError):
        meta = {}
    item_id = meta.get("item_id") or f"xhs-{source_id}"
    return (f"《{meta.get('title') or source_id}》{item_id} · {file_name or '附件'} · {reason.strip()[:160]}"
            f" → 重跑：python -m link_brain attachments {item_id}")


EXIT_ACCOUNT_BUSY = 6


def run(args) -> int:
    """`attachments`。会用号开页的（--recheck / --all / 单篇下载）先查熔断和账号锁：
    熔断中 → 退出 5 一页不开；号被别的任务占着 → 退出 6。--audit / --attach 不联网，不受影响。"""
    if getattr(args, "audit", False) or getattr(args, "attach", None) or getattr(args, "dedupe", False):
        return _run(args)
    from . import accounts
    from .read import dump_json
    try:
        accounts.check_risk_hold()
    except accounts.ReaderError as exc:
        print(f"附件补下没跑：风控暂停中（{exc.detail}）。处理完（扫码登录 / 打开验证）会自动恢复。", file=sys.stderr)
        if getattr(args, "recheck", False):
            dump_json({"checked": 0, "found": [], "failed": [], "blocked": exc.code})
        return EXIT_NEEDS_HUMAN
    owner = "attachments --recheck" if getattr(args, "recheck", False) else "attachments"
    budget_left = budget_from_minutes(getattr(args, "budget_min", 0))  # 从进程开头算：等锁的时间也在预算里
    try:
        with accounts.account_session(owner, wait_s=float(getattr(args, "wait_lock_min", 10) or 0) * 60):
            return _run(args, budget_left=budget_left)
    except accounts.AccountBusyError as exc:
        print(f"附件补下没跑：{exc}", file=sys.stderr)
        if getattr(args, "recheck", False):
            dump_json({"checked": 0, "found": [], "failed": [], "busy": True})
        return EXIT_ACCOUNT_BUSY


def _run(args, budget_left=None) -> int:
    from . import index as index_mod

    # 1001：--budget-min N 到点收手、正常收尾（夜跑外层限时会整棵杀，别在下载到一半时被杀）
    if budget_left is None:
        budget_left = budget_from_minutes(getattr(args, "budget_min", 0))
    if getattr(args, "recheck", False):
        from .read import dump_json
        out = recheck(limit=getattr(args, "limit", 0) or 0, verbose=True, budget_left=budget_left)
        dump_json(out)
        return EXIT_NEEDS_HUMAN if out.get("blocked") else 0
    if getattr(args, "dedupe", False):
        from .read import dump_json
        dump_json(dedupe(dry_run=getattr(args, "dry_run", False)))
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
    problem_lines: list[str] = []
    deferred_objects = 0
    for n, (source_key, source_id) in enumerate(targets):
        if not _fits(budget_left, attempt_cost(1)):
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
            elif r["status"] == "deferred":
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
                if r.get("code") or xhs.looks_blocked(message):
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


PROBE_GAP_SECONDS = tuple(float(x) for x in os.environ.get("LWA_PROBE_GAP", "30,90").split(","))


def _probe_logged_in(note_id: str, token: str | None) -> dict[str, Any]:
    """用读取服务的登录号打开笔记页读 relatedFile（游客被登录墙挡的笔记用）。

    页面上看得到附件卡片但 state 里没 docId 时，报成『要人看』而不是『没附件』。
    """
    from . import accounts
    try:
        accounts.ensure_reader()
        accounts.pace("用登录号打开笔记页")
        d = accounts.api("POST", "/api/v1/notes/related-file", timeout=150,
                         body={"note_id": note_id, "xsec_token": token or ""})
    except accounts.ReaderError as exc:
        return {"ok": False, "needs_human": exc.needs_human, "code": exc.code, "error": f"{exc.code} {exc}".strip()}
    except (httpx.HTTPError, OSError, ValueError) as exc:
        # 0929：读取服务连接被重置（10054）以前直接抛出，整晚补查崩掉、后面的笔记全没查；现在只算这篇没查清，明晚再来
        return {"ok": False, "error": f"读取服务连接出错：{type(exc).__name__} {exc}"[:200]}
    if d.get("guest") or d.get("loginBtn"):
        accounts._note_account("NOT_LOGGED_IN", "附件补查：登录号打开笔记是游客")
        return {"ok": False, "needs_human": True, "code": "NOT_LOGGED_IN",
                "error": "读取服务的号没登录：先在目录里点「扫码登录」"}
    if d.get("wall") or not d.get("hasNote"):
        return {"ok": False, "error": f"登录也打不开这篇（{d.get('path')}：多半已删或仅作者可见）"}
    rf = d.get("relatedFile")
    if rf and rf.get("docId"):
        return {"ok": True, "related_file": rf, "error": None}
    if d.get("cardText"):
        return {"ok": False, "error": f"页面上有附件卡片（{d['cardText'][:60]}）但读不到编号，要人打开下一次"}
    return {"ok": True, "related_file": None, "error": None}


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


def _remember_probed(obj: Path, meta: dict[str, Any], doc_id: str, name: str, rf: dict[str, Any]) -> None:
    """补查探到的附件 → 对象级声明 + 索引状态，让 `attachments --all` 也遍历得到（以前只在 recheck 这一处记）。"""
    raw = storage.raw_dir("xiaohongshu", obj.name, meta["current_version"]) / "source.json"
    source_doc = storage.read_json(raw) if raw.exists() else {}
    declared = declared_attachments(obj, source_doc)
    if any(a.get("doc_id") == doc_id for a in declared):
        return
    try:
        extra = json.loads(rf.get("bizExtra") or "{}")
    except (TypeError, ValueError):
        extra = {}
    hints = [a.get("hint") for a in declared if not a.get("doc_id") and a.get("hint")]
    remember_resolved(obj, {"doc_id": doc_id, "name": name, "url": xhs.FILE_PREVIEW_FMT.format(doc_id=doc_id),
                            "page_num": extra.get("page_num")},
                      hint=hints[0] if len(hints) == 1 else None, via="recheck")
    _sync_index_status("xiaohongshu", obj.name)


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


def recheck(*, limit: int = 0, verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """补查「当时没探到附件」的笔记（0926）。

    入库时网页探测拿到反爬占位页 → web_raw.json ok=false，被当成「没附件」静默跳过，不报警、audit 也看不见
    （9-18 才加的游客浏览器兜底对之前入库的不生效）。这里对这些笔记重新探测（httpx → 游客浏览器），
    探到就下字节并挂上；结果记 derived/web_recheck.json，探明的不再重复查。仍探不到的汇总报警。
    """
    from .adapters import xiaohongshu as xhs
    from . import render as render_mod
    base = storage.vault_root() / "_archive" / "xiaohongshu"
    found, failed, checked = [], [], 0
    blocked = ""
    out_of_time = False
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
        if not _fits(budget_left, probe_cost()):
            out_of_time = True  # 1001：时间预算到了，剩下的明晚再查
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
        if checked > 1:  # 0927 防风控：探测之间也像人一样隔一会儿
            gap = random.uniform(*PROBE_GAP_SECONDS)
            if verbose:
                print(f"[recheck] 歇 {gap:.0f} 秒再看下一篇", file=sys.stderr)
            time.sleep(gap)
        probe = xhs.fetch_related_file(source_id, token)
        if not probe.get("ok"):
            # 游客被登录墙挡住（有些笔记游客看不了）→ 用登录的号看一眼笔记页
            logged = _probe_logged_in(source_id, token)
            if logged.get("needs_human"):
                storage.write_json(mark, {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ok": False,
                                          "related_file": None, "error": logged["error"]})
                blocked = logged.get("code") or "NOT_LOGGED_IN"
                problems_mod.report_blocked("attachments.recheck", blocked, f"附件补查停了：{logged['error']}"[:200])
                break
            if logged.get("ok"):
                probe = logged
            else:
                probe["error"] = f"{probe.get('error')}；登录看：{logged.get('error')}"
        rf = probe.get("related_file") or {}
        storage.write_json(mark, {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ok": bool(probe.get("ok")),
                                  "related_file": rf or None, "error": probe.get("error")})
        if not probe.get("ok"):
            failed.append({"id": source_id, "line": describe_problem("xiaohongshu", source_id, None, probe.get("error") or ""),
                           "error": probe.get("error") or "", "title": meta.get("title")})
            continue
        problems_mod.resolve("attachments.recheck", meta.get("item_id") or f"xhs-{source_id}")
        doc_id = str(rf.get("docId") or "")
        if not doc_id:
            continue
        name = rf.get("name") or f"{doc_id}.bin"
        # 1001（审计 attach-4 ③）：探到的附件记进对象级声明，--all 能遍历到；下坏了 / 被删了也有人接着补
        _remember_probed(obj, meta, doc_id, name, rf)
        known_now = load_downloaded("xiaohongshu", source_id)
        if doc_id in known_now and _have_by_name(obj, known_now[doc_id].get("file") or ""):
            continue
        have = _have_by_name(obj, name)
        if have:  # 以前手动挂过（记成 manual-…）：认回真 doc_id，不上网
            manual_attach("xiaohongshu", source_id, str(have), doc_id)
            convert_downloads("xiaohongshu", source_id)
            render_mod.render_object("xiaohongshu", source_id)
            continue
        try:
            acquire("xiaohongshu", source_id, doc_id=doc_id, name=name, xsec_token=token or "", verbose=verbose,
                    budget_left=budget_left)
            render_mod.render_object("xiaohongshu", source_id)
            found.append({"id": source_id, "file": name})
        except AttachmentDeferred as exc:
            # 探到了但没时间下：记成「下载没完成」，这篇保持待查，明晚接着下（不算失败、不报警）
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            out_of_time = True
            break
        except AttachmentNeedsHuman as exc:
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            blocked = exc.code or "NOT_LOGGED_IN"
            problems_mod.report_blocked("attachments.recheck", blocked, f"附件补查时下载撞墙：{exc}"[:200])
            break  # 撞验证就停，绝不接着开页
        except (AttachmentError, OSError, KeyError, ValueError) as exc:
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            failed.append({"id": source_id, "line": describe_problem("xiaohongshu", source_id, name, f"下载失败：{exc}"),
                           "error": f"探到了附件但下载失败：{exc}", "title": meta.get("title")})
    for f in failed:
        # 第 4 批：不推送。没查清的每篇登记 TRANSIENT（明晚接着查），连续 3 天都查不清才升级 STUCK 推一次
        problems_mod.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", str(f.get("error") or f["line"])[:200],
                            item_id=f"xhs-{f['id']}", title=f.get("title"))
    for f in failed:
        f.pop("error", None)
        f.pop("title", None)
    if found:
        _rebuild_catalog(True)
    out = {"checked": checked, "found": found, "failed": failed}
    if blocked:
        out["blocked"] = blocked
    if out_of_time:
        out["out_of_time"] = True
        print("[recheck] 时间预算到了，剩下的明晚接着查", file=sys.stderr)
    return out
