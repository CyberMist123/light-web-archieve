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
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ... import attachments as shared, domain, problems as problems_mod, storage
from ...errtext import errtext
from . import adapter as xhs

SERVICE_DOWN_CODES = ("TIMEOUT", "DISCONNECTED", "BUSY", "BROWSER_STUCK")


DOWNLOAD_TIMEOUT_SECONDS = 240


LOGGED_PROBE_TIMEOUT_SECONDS = 150


GUEST_PROBE_SECONDS = 130


def _open_gap_hi() -> float:
    from . import accounts
    return accounts._gap_range("LWA_OPEN_GAP", "20,40")[1]


def attempt_cost(attempt: int = 1) -> float:
    """下一个附件（第 attempt 次）最坏要多久：歇够 + 开页间隔 + 下载超时 + 校验转 md 的余量。"""
    return PACE_SECONDS[1] * attempt + _open_gap_hi() + DOWNLOAD_TIMEOUT_SECONDS + 60


def probe_cost() -> float:
    """补查一篇最坏要多久：探测间隔 + 游客探测 + 开页间隔 + 登录号补看超时。"""
    return PROBE_GAP_SECONDS[1] + GUEST_PROBE_SECONDS + _open_gap_hi() + LOGGED_PROBE_TIMEOUT_SECONDS


def guest_cost() -> float:
    """游客段补查一篇最坏要多久：探测间隔 90 + httpx 30 + 游客浏览器 100 = 220 秒（不碰号，没有开页间隔 / 登录号补看）。"""
    return PROBE_GAP_SECONDS[1] + GUEST_PROBE_SECONDS


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
            raise shared.AttachmentNeedsHuman(text, exc.code) from exc
        if exc.code == "NOTE_RESTRICTED":
            raise shared.AttachmentRestricted(reason) from exc
        if exc.code in SERVICE_DOWN_CODES:
            raise shared.AttachmentServiceDown(text, exc.code) from exc
        raise shared.AttachmentError(text) from exc
    path = Path(data["path"])
    if not path.is_file() or path.stat().st_size == 0:
        raise shared.AttachmentError(f"读取服务报告已下载，但文件不存在：{path}")
    return path


PACE_SECONDS = tuple(float(x) for x in os.environ.get("LWA_ATTACH_PACE", "90,240").split(","))


TRIES = max(1, int(os.environ.get("LWA_ATTACH_TRIES", "3")))


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


def acquire(source_key: str, source_id: str, *, doc_id: str, name: str, xsec_token: str,
            verbose: bool = False, budget_left=None, tries: int | None = None) -> dict[str, Any]:
    """下一份附件，验到『文件头对得上类型』为止；半截 / 网页占位页就歇更久、重下，最多 TRIES 次。

    1001（审计 attach-4）：文件头校验通过就算下好了。转 md 失败（加密 / 损坏 / 扫描件空白页）不再删字节重下——
    那样每晚开 3 次附件页、永远循环；字节留着，记录上标 conversion_failed，报警给人看。
    账号要人处理（未登录 / 安全验证）直接抛 AttachmentNeedsHuman，绝不重试。
    budget_left（1001）：剩下的时间装不下下一次尝试的最坏耗时 → 抛 AttachmentDeferred（不算失败）。
    """
    from ...pdftext import convert_object_attachments

    object_dir = storage.object_dir(source_key, source_id)
    staging = object_dir / ".attachment-staging"
    last_error = ""
    for attempt in range(1, (tries or TRIES) + 1):
        if not shared._fits(budget_left, attempt_cost(attempt)):
            raise shared.AttachmentDeferred(f"时间预算不够再开附件页了（{name}），下次接着下"
                                     + (f"；前一次：{last_error}" if last_error else ""))
        _pace(attempt)
        try:
            try:
                got = fetch_bytes(doc_id=doc_id, note_id=source_id, xsec_token=xsec_token,
                                  file_name=name or "file", staging_dir=staging, verbose=verbose)
            except shared.AttachmentRestricted as exc:
                # 1011：网页版要验证才能看——不进 3 次循环：今天没搜过就用标题搜一次新口令、歇一会儿再开一次，还不行记一条就收
                got = _restricted_fallback(source_id, doc_id=doc_id, name=name, xsec_token=xsec_token, staging=staging,
                                           verbose=verbose, budget_left=budget_left, first=exc)
            else:
                from . import restricted
                restricted.clear(source_id, why="附件页打开了这篇")
            shared._check_file(got)
            out = shared.manual_attach(source_key, source_id, str(got), doc_id, origin="auto")
            record = next(r for r in shared.load_downloaded(source_key, source_id).values() if r.get("file") == out["file"])
            try:
                bad = [r for r in convert_object_attachments(source_key, source_id)
                       if r["doc_id"] == record["doc_id"] and r["status"] == "failed"]
            except Exception as exc:  # noqa: BLE001 - 转换出意外也不该让已下好的字节作废
                bad = [{"note": errtext(exc)}]
                next_at = shared.mark_conversion(source_key, source_id, record["doc_id"], bad[0]["note"],
                                          code="TRANSIENT.SERVICE_BUSY")
                problems_mod.report("attachments.convert", "TRANSIENT.SERVICE_BUSY",
                                    f"{record.get('file')}：{bad[0]['note']}"[:200], item_id=domain.item_id(xhs.SOURCE, source_id),
                                    next_at=next_at)
            if bad:
                # 第 4 批：不推送。转换失败已按码登记（加密 / 损坏 PERMANENT，卡片标「全文没转出来」；
                # OCR 故障 / 超时 TRANSIENT，按 next_at 退避自动再转）
                print(f"[attachment] {record['file']} 已下好，但转 md 失败（字节留着，不再重下）："
                      f"{bad[0].get('note') or ''}", file=sys.stderr)
            return shared.load_downloaded(source_key, source_id).get(record["doc_id"], record)
        except (shared.AttachmentNeedsHuman, shared.AttachmentRestricted, shared.AttachmentDeferred):
            raise
        except shared.AttachmentServiceDown as exc:
            raise shared.AttachmentServiceDown(f"读取服务这次没响应（{exc.code}），不再重试，下次接着下：{exc}", exc.code) from exc
        except (shared.AttachmentError, OSError, StopIteration, KeyError, ValueError) as exc:
            last_error = errtext(exc)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        print(f"[attachment] 第 {attempt}/{TRIES} 次没成：{last_error}", file=sys.stderr)
    raise shared.AttachmentError(f"试了 {TRIES} 次仍不行：{last_error}")


def _restricted_fallback(source_id: str, *, doc_id: str, name: str, xsec_token: str, staging: Path, verbose: bool,
                         budget_left, first: shared.AttachmentRestricted) -> Path:
    """1011：附件页那一步发现这篇在网页版要验证才能看。今天没为这篇搜过就用标题搜一次新口令（restricted.find_fresh_token：
    先歇 LWA_FETCH_REST），再按附件的开页节奏（_pace）用新口令开一次；还是不行 → 记「网页版要验证」、抛 AttachmentRestricted。
    时间预算装不下这一轮（搜索 + 歇 + 再开一次）→ AttachmentDeferred（不记、下次再来）。号要人处理 → AttachmentNeedsHuman。"""
    from . import accounts, restricted
    try:
        meta = storage.read_json(storage.object_dir("xiaohongshu", source_id) / "meta.json")
    except (OSError, ValueError):
        meta = {}
    title = meta.get("title") or ""
    item_id = meta.get("item_id") or domain.item_id(xhs.SOURCE, source_id)
    if restricted.search_due(restricted.load(source_id)):
        need = accounts._gap_range(restricted.REST_ENV, restricted.REST_DEFAULT)[1] + 150 + attempt_cost(1)
        if not shared._fits(budget_left, need):
            raise shared.AttachmentDeferred(f"这篇在网页版要验证才能看；用标题搜新口令再开一次的时间不够了，下次接着试（{name}）")

    def again(token: str) -> Path:
        _pace(1)
        return fetch_bytes(doc_id=doc_id, note_id=source_id, xsec_token=token, file_name=name or "file",
                           staging_dir=staging, verbose=verbose)

    try:
        opened, got = restricted.retry_with_fresh_token(
            source_id, title=title, old_token=xsec_token, attempt=again, restricted_exc=(shared.AttachmentRestricted,),
            item_id=item_id, via="attachments", detail=str(first)[:200])
    except xhs.NeedsHumanError as exc:
        raise shared.AttachmentNeedsHuman(str(exc), getattr(exc, "code", "") or "ACCOUNT_BLOCKED") from exc
    if not opened:
        raise shared.AttachmentRestricted(restricted.TEXT)
    return got


def resolve_hint(note_id: str, token: str | None) -> dict[str, Any]:
    """正文线索 → 真附件：先游客看，游客被挡再用登录号看。返回 {doc_id,name,url,...} 或 {error}。"""
    from . import adapter as xhs
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
        return {"ok": False, "error": f"读取服务连接出错：{errtext(exc).replace(':', '', 1)}"[:200]}
    path = str(d.get("path") or "")
    if d.get("guest") or d.get("loginBtn") or path.startswith("/login") or "/website-login" in path:
        # 落到登录页一律是号的问题：停车、要人处理，绝不判成删帖（1008 B3-P2）
        accounts._note_account("NOT_LOGGED_IN", "附件补查：登录号打开笔记是游客")
        return {"ok": False, "needs_human": True, "code": "NOT_LOGGED_IN", "path": path,
                "error": "读取服务的号没登录：先在目录里点「扫码登录」"}
    if d.get("wall") or not d.get("hasNote"):
        return {"ok": False, "path": path, "wall": bool(d.get("wall")), "has_note": bool(d.get("hasNote")),
                "gone_like": (path.startswith("/explore") or path.startswith("/404")) and not d.get("hasNote"),
                "error": f"登录也打不开这篇（{path}：可能已删、仅作者可见、审核中，或链接口令过期）"}
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
        if m.get("gone"):
            # 1008（B3-P2）：原帖打不开 = 终态，不算没查清；每 30 天游客复查一次，以后再看到就翻回来
            gone_at = shared._parse_dt(m.get("gone_at"), None)
            if gone_at and datetime.now().astimezone() - gone_at < timedelta(days=GONE_RECHECK_DAYS):
                return "gone"
            return "unprobed"
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
    declared = shared.declared_attachments(obj, source_doc)
    if any(a.get("doc_id") == doc_id for a in declared):
        return
    try:
        extra = json.loads(rf.get("bizExtra") or "{}")
    except (TypeError, ValueError):
        extra = {}
    hints = [a.get("hint") for a in declared if not a.get("doc_id") and a.get("hint")]
    shared.remember_resolved(obj, {"doc_id": doc_id, "name": name, "url": xhs.FILE_PREVIEW_FMT.format(doc_id=doc_id),
                            "page_num": extra.get("page_num")},
                      hint=hints[0] if len(hints) == 1 else None, via="recheck")
    shared._sync_index_status("xiaohongshu", obj.name)


def recheck(*, limit: int = 0, verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """补查「当时没探到附件」的笔记（0926）。

    入库时网页探测拿到反爬占位页 → web_raw.json ok=false，被当成「没附件」静默跳过，不报警、audit 也看不见
    （9-18 才加的游客浏览器兜底对之前入库的不生效）。这里对这些笔记重新探测（httpx → 游客浏览器），
    探到就下字节并挂上；结果记 derived/web_recheck.json，探明的不再重复查。仍探不到的汇总报警。
    """
    from . import adapter as xhs
    base = storage.vault_root() / "_archive" / "xiaohongshu"
    found, failed, checked = [], [], 0
    blocked = ""
    out_of_time = False
    # 从没补查过的排前面；查过的按上次查的时间轮流（谁最久没查谁先，1008：以前查过的永远垫底、一次都轮不到）
    for meta_path in sorted(base.glob("*/meta.json"), key=shared._queue_key):
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
        if not shared._fits(budget_left, probe_cost()):
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
            failed.append({"id": source_id, "line": shared.describe_problem("xiaohongshu", source_id, None, probe.get("error") or ""),
                           "error": probe.get("error") or "", "title": meta.get("title")})
            continue
        problems_mod.resolve("attachments.recheck", meta.get("item_id") or domain.item_id(xhs.SOURCE, source_id))
        doc_id = str(rf.get("docId") or "")
        if not doc_id:
            continue
        name = rf.get("name") or f"{doc_id}.bin"
        # 1001（审计 attach-4 ③）：探到的附件记进对象级声明，--all 能遍历到；下坏了 / 被删了也有人接着补
        _remember_probed(obj, meta, doc_id, name, rf)
        known_now = shared.load_downloaded("xiaohongshu", source_id)
        if doc_id in known_now and shared._have_by_name(obj, known_now[doc_id].get("file") or ""):
            continue
        have = shared._have_by_name(obj, name)
        if have:  # 以前手动挂过（记成 manual-…）：认回真 doc_id，不上网
            shared.manual_attach("xiaohongshu", source_id, str(have), doc_id)
            shared.convert_downloads("xiaohongshu", source_id)
            shared._render_object("xiaohongshu", source_id)
            continue
        try:
            acquire("xiaohongshu", source_id, doc_id=doc_id, name=name, xsec_token=token or "", verbose=verbose,
                    budget_left=budget_left)
            shared._render_object("xiaohongshu", source_id)
            found.append({"id": source_id, "file": name})
        except shared.AttachmentDeferred as exc:
            # 探到了但没时间下：记成「下载没完成」，这篇保持待查，明晚接着下（不算失败、不报警）
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            out_of_time = True
            break
        except shared.AttachmentNeedsHuman as exc:
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            blocked = exc.code or "NOT_LOGGED_IN"
            problems_mod.report_blocked("attachments.recheck", blocked, f"附件补查时下载撞墙：{exc}"[:200])
            break  # 撞验证就停，绝不接着开页
        except (shared.AttachmentError, OSError, KeyError, ValueError) as exc:
            storage.write_json(mark, {**storage.read_json(mark), "download_error": str(exc)[:200]})
            failed.append({"id": source_id, "line": shared.describe_problem("xiaohongshu", source_id, name, f"下载失败：{exc}"),
                           "error": f"探到了附件但下载失败：{exc}", "title": meta.get("title")})
    for f in failed:
        # 第 4 批：不推送。没查清的每篇登记 TRANSIENT（明晚接着查），连续 3 天都查不清才升级 STUCK 推一次
        problems_mod.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", str(f.get("error") or f["line"])[:200],
                            item_id=domain.item_id(xhs.SOURCE, f["id"]), title=f.get("title"))
    for f in failed:
        f.pop("error", None)
        f.pop("title", None)
    if found:
        shared._rebuild_catalog(True)
    out = {"checked": checked, "found": found, "failed": failed}
    if blocked:
        out["blocked"] = blocked
    if out_of_time:
        out["out_of_time"] = True
        print("[recheck] 时间预算到了，剩下的明晚接着查", file=sys.stderr)
    return out


# ==========================================================================
# 1008（L6·B3）附件补查拆两段 + 终态 + 本地对账 + 状态文件
#
# 游客段（--recheck --guest-only）：不碰号——不调读取服务、不拿账号锁、不调 check_risk_hold（它会拉起读取服务），
#   只读本地熔断文件；每篇前只读看一眼账号锁（号正被同步 / lwa 占着就收工，别和号的活动从同一个 IP 叠在一起）；
#   无条件保险丝：连续 2 篇游客读不到 / 游客浏览器自己出错 → 当晚停；游客页上出现验证专用词 → 立刻停、不起浏览器兜底、
#   登记步骤级 TRANSIENT.WEB_PROBE_BLOCKED。探到附件只登记（--all 去下），不下载。
#   熔断夜（她 1008 答：照跑）：开关 LWA_GUEST_RECHECK_DURING_HOLD 默认开，开了也守 ≤10 篇、离验证 ≥60 分钟。
# 收尾段（--recheck --logged-in-tail，碰号）：只看游客读不到的，每晚 ≤5 篇；原有门槛一条不少（熔断、账号锁、pace、
#   撞验证即停）；第一次遇到服务那侧的失败（TIMEOUT / BUSY / 连不上）就收工。
# 「原帖打不开」终态：登录号落到 /explore 或 /404、页面上没有这条笔记、不是游客、没有登录按钮——两个不同的晚上各看到
#   一次（或用读收藏时存下的新口令看到一次）才定；落到 /login 一律按号的问题停车，绝不判删帖。
# 状态文件 _archive/attachments-recheck-status.json：两段每次运行都写，跳过也写（--skipped），面板 / 夜跑如实说。
# ==========================================================================

GONE_RECHECK_DAYS = 30


GUEST_HOLD_LIMIT = 10


GUEST_HOLD_MIN_GAP_MIN = 60


GUEST_FUSE_MISSES = 2


FAV_TOKENS_NAME = "fav-tokens.json"


FRESH_TOKEN_DAYS = 7


SERVICE_CODES = ("TIMEOUT", "BUSY", "DISCONNECTED", "RATE_LIMITED", "VERIFY_WINDOW_OPEN", "LOGIN_IN_PROGRESS",
                 "BROWSER_STUCK")


def fav_tokens_path() -> Path:
    return storage.archive_root() / FAV_TOKENS_NAME


def remember_fav_tokens(items: list[dict[str, Any]], *, partial: bool, merge: bool = False) -> int:
    """读收藏读全（partial=false）时，把「笔记 id → 最新口令」存到本地（纯本地写，零开页）。补查 / 下载优先用它。
    只认读全的那一次：读一截时存下来的不全，判「原帖打不开」时会误以为它不在收藏里。返回存了几条。永不抛异常。

    1011 增量读（merge=True）：只读了最新那一段——把读到的这些合进去（口令和时刻按这次的），没读到的原样留着
    （各自带自己的 at，FRESH_TOKEN_DAYS 照算），整份文件的 full_at 不动：「全量名单」只由每周那次全量读刷新。"""
    if partial and not merge:
        return 0
    try:
        from urllib.parse import parse_qs, urlsplit
        now = shared._iso(shared._now_local())
        out: dict[str, Any] = {}
        prior: dict[str, Any] = {}
        if merge:
            try:
                prior = storage.read_json(fav_tokens_path()) or {}
            except (OSError, ValueError):
                prior = {}
            if not isinstance(prior, dict):
                prior = {}
            out = dict(prior.get("tokens") or {})
        written = 0
        for it in items or []:
            nid = str(it.get("note_id") or it.get("id") or "")
            token = it.get("xsec_token") or (parse_qs(urlsplit(str(it.get("url") or "")).query).get("xsec_token") or [""])[0]
            if nid and token:
                out[nid] = {"token": token, "at": now}
                written += 1
        if out:
            full_at = (prior.get("full_at") or prior.get("at")) if merge else now
            storage.write_json(fav_tokens_path(), {"schema_version": 1, "at": now, "full_at": full_at, "tokens": out})
        return written
    except Exception as exc:  # noqa: BLE001
        print(f"[recheck] 新口令没存上（不影响同步）：{exc}", file=sys.stderr)
        return 0


def fresh_token(note_id: str) -> str | None:
    """最近一次读全收藏时拿到的这篇的口令（FRESH_TOKEN_DAYS 天内）；没有就 None（调用方退回入库时的旧口令）。"""
    try:
        data = storage.read_json(fav_tokens_path())
    except (OSError, ValueError):
        return None
    row = ((data or {}).get("tokens") or {}).get(str(note_id)) or {}
    at = shared._parse_dt(row.get("at"), None)
    if not row.get("token") or not at or shared._now_local() - at > timedelta(days=FRESH_TOKEN_DAYS):
        return None
    return str(row["token"])


def _old_token(obj: Path, meta: dict[str, Any]) -> str | None:
    raw = storage.raw_dir("xiaohongshu", obj.name, meta["current_version"])
    web = raw / "web_raw.json"
    url = (storage.read_json(web).get("url") or "") if web.exists() else ""
    token = (re.search(r"xsec_token=([^&]+)", url) or [None, None])[1]
    if token:
        from urllib.parse import unquote
        return unquote(token)
    src = raw / "source.json"
    return (storage.read_json(src).get("note") or {}).get("xsec_token") if src.exists() else None


def _guest_during_hold() -> bool:
    return os.environ.get("LWA_GUEST_RECHECK_DURING_HOLD", "1").strip().lower() not in ("0", "false", "no", "off")


def recheck_guest(*, limit: int = 0, verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """游客段（不碰号）。返回 {phase, checked, found, guest_unseen, stopped_reason, account_hold, reconciled}；永远退出 0。"""
    from . import accounts
    from . import adapter as xhs
    out: dict[str, Any] = {"phase": "guest", "checked": 0, "found": [], "guest_unseen": 0, "stopped_reason": "done"}
    out["reconciled"] = shared.reconcile()
    q = shared.recheck_queues()
    lim = limit or shared.guest_limit(q["unprobed"])
    hold = accounts._hold_file()
    out["account_hold"] = bool(hold)
    if hold:
        since = shared._parse_dt(hold.get("since"), None)
        if not _guest_during_hold():
            out["stopped_reason"] = "account_hold"
        elif since and shared._now_local() - since < timedelta(minutes=GUEST_HOLD_MIN_GAP_MIN):
            out["stopped_reason"] = "hold_too_recent"
        lim = min(lim, GUEST_HOLD_LIMIT)
    out["limit"] = lim
    if out["stopped_reason"] != "done":
        print(f"[recheck] 游客补查今晚不开页：{out['stopped_reason']}（本地对账照做了）", file=sys.stderr)
        shared.write_recheck_status("guest", out)
        return out
    misses = 0
    for obj in q["guest"]:
        if out["checked"] >= lim:
            out["stopped_reason"] = "limit"
            break
        if not shared._fits(budget_left, guest_cost()):
            out["stopped_reason"] = "out_of_time"
            break
        now_hold = accounts._hold_file()
        if now_hold and not hold:
            out["stopped_reason"] = "account_hold"  # 跑着跑着号出事了：游客也先停，别和那件事叠在一起
            break
        if accounts.lock_holder():
            out["stopped_reason"] = "account_busy"
            break
        try:
            meta = storage.read_json(obj / "meta.json")
        except (OSError, ValueError):
            continue
        if out["checked"]:
            gap = random.uniform(*PROBE_GAP_SECONDS)
            if verbose:
                print(f"[recheck] 歇 {gap:.0f} 秒再看下一篇", file=sys.stderr)
            time.sleep(gap)
        token = fresh_token(obj.name) or _old_token(obj, meta)
        probe = xhs.fetch_related_file(obj.name, token, stop_on_captcha=True)
        out["checked"] += 1
        now = shared._iso(shared._now_local())
        if probe.get("captcha"):
            out["stopped_reason"] = "captcha"
            problems_mod.report("attachments.recheck", "TRANSIENT.WEB_PROBE_BLOCKED",
                                "附件补查（游客）打开笔记页时出现了安全验证 / 访问频繁：当晚游客补查停了，没碰号")
            break
        if probe.get("ok"):
            misses = 0
            rf = probe.get("related_file") or {}
            gone_back = {"gone": False, "gone_at": None} if shared._mark_of(obj).get("gone") else {}
            shared._write_mark(obj, checked_at=now, guest_at=now, ok=True, related_file=rf or None, error=None,
                        stage="guest", via=probe.get("via") or "httpx", **gone_back)
            problems_mod.resolve("attachments.recheck", meta.get("item_id") or domain.item_id(xhs.SOURCE, obj.name))
            if rf.get("docId"):
                _remember_probed(obj, meta, str(rf["docId"]), rf.get("name") or f"{rf['docId']}.bin", rf)
                out["found"].append({"id": obj.name, "file": rf.get("name")})
            continue
        misses += 1
        out["guest_unseen"] += 1
        m = shared._mark_of(obj)
        if m.get("gone"):
            shared._write_mark(obj, gone_at=now, guest_at=now)  # 30 天复查游客还是看不到：终态续 30 天
        else:
            shared._write_mark(obj, checked_at=now, guest_at=now, ok=False, related_file=None,
                        stage="guest_unseen", error=str(probe.get("error") or "")[:200])
        if probe.get("browser_error"):
            out["stopped_reason"] = "guest_browser_error"
            break
        if misses >= GUEST_FUSE_MISSES:
            out["stopped_reason"] = "fuse"
            break
    if out["found"]:
        shared._rebuild_catalog(True)
    shared.write_recheck_status("guest", out)
    return out


def recheck_tail(*, limit: int = shared.TAIL_LIMIT, verbose: bool = False, budget_left=None) -> dict[str, Any]:
    """收尾段：游客读不到的用登录号看一眼（每晚 ≤limit 篇）。调用方（run）已过熔断检查、拿了账号锁。
    撞验证 / 掉登录 → blocked（退出 5）；服务那侧第一次失败就收工。返回 {phase, checked, found, gone, blocked?, stopped_reason}。"""
    q = shared.recheck_queues()
    out: dict[str, Any] = {"phase": "tail", "checked": 0, "found": [], "gone": 0, "stopped_reason": "done", "limit": limit}
    today = shared._now_local().date().isoformat()
    for obj in q["tail"]:
        if out["checked"] >= limit:
            out["stopped_reason"] = "limit"
            break
        if not shared._fits(budget_left, _open_gap_hi() + LOGGED_PROBE_TIMEOUT_SECONDS):
            out["stopped_reason"] = "out_of_time"
            break
        try:
            meta = storage.read_json(obj / "meta.json")
        except (OSError, ValueError):
            continue
        item_id = meta.get("item_id") or domain.item_id(xhs.SOURCE, obj.name)
        from . import restricted
        if restricted.is_restricted(obj.name):
            continue  # 1011：网页版要验证才能看的，等她点「打开验证」，碰号的补查不替她开页
        fresh = fresh_token(obj.name)
        logged = _probe_logged_in(obj.name, fresh or _old_token(obj, meta))
        out["checked"] += 1
        now = shared._iso(shared._now_local())
        if logged.get("needs_human"):
            shared._write_mark(obj, logged_at=now, error=logged.get("error"))
            out["blocked"] = logged.get("code") or "NOT_LOGGED_IN"
            out["stopped_reason"] = "blocked"
            problems_mod.report_blocked("attachments.recheck", out["blocked"], f"附件补查停了：{logged.get('error')}"[:200])
            break
        if logged.get("ok"):
            rf = logged.get("related_file") or {}
            shared._write_mark(obj, checked_at=now, logged_at=now, ok=True, related_file=rf or None, error=None, stage="logged")
            problems_mod.resolve("attachments.recheck", item_id)
            if rf.get("docId"):
                _remember_probed(obj, meta, str(rf["docId"]), rf.get("name") or f"{rf['docId']}.bin", rf)
                out["found"].append({"id": obj.name, "file": rf.get("name")})
            continue
        err = str(logged.get("error") or "")
        if logged.get("code") in SERVICE_CODES or "读取服务连接出错" in err:
            out["stopped_reason"] = "service"  # 09-29 连着 4 次 TIMEOUT 还接着开页：第一次就收工
            print(f"[recheck] 读取服务那侧出错，今晚收尾段收工：{err[:120]}", file=sys.stderr)
            break
        from . import restricted
        if logged.get("gone_like") and restricted.is_restricted(obj.name):
            # 1011：读取组件判过「网页版要验证才能看」的——她浏览器里打得开，不是原帖没了：不判「原帖打不开」，等她点「打开验证」
            shared._write_mark(obj, logged_at=now, error=err[:200], stage="restricted")
            continue
        if logged.get("gone_like"):
            m = shared._mark_of(obj)
            nights = sorted({*(m.get("gone_nights") or []), today})
            if len(nights) >= 2 or fresh:
                shared._write_mark(obj, checked_at=now, logged_at=now, ok=False, gone=True, gone_at=now, stage="gone",
                            gone_nights=nights, error=err[:200],
                            gone_why="游客和登录号都打不开、登录号落到 " + str(logged.get("path") or "") +
                                     ("（用读收藏时的新口令看的）" if fresh else "（两个晚上各看了一次）"))
                problems_mod.resolve("attachments.recheck", item_id)
                out["gone"] += 1
            else:
                shared._write_mark(obj, logged_at=now, stage="gone_suspected", gone_nights=nights, error=err[:200])
            continue
        shared._write_mark(obj, logged_at=now, error=err[:200])
        eta = shared.recheck_eta(item_id)
        next_at = None
        if eta.get("when"):
            try:
                y = shared._now_local().year
                next_at = shared._iso(datetime.strptime(f"{y}-{eta['when']} 04:00", "%Y-%m-%d %H:%M").astimezone())
            except ValueError:
                next_at = None
        problems_mod.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", f"登录号也没看清：{err}"[:200],
                            item_id=item_id, title=meta.get("title"), next_at=next_at)
    if out["found"]:
        shared._rebuild_catalog(True)
    shared.write_recheck_status("tail", out)
    return out


def run_with_account(args, callback):
    from . import accounts
    from ...read import dump_json
    try:
        accounts.check_risk_hold()
    except accounts.ReaderError as exc:
        print(f"附件补下没跑：风控暂停中（{exc.detail}）。处理完（扫码登录 / 打开验证）会自动恢复。", file=sys.stderr)
        if getattr(args, "recheck", False):
            dump_json({"checked": 0, "found": [], "failed": [], "blocked": exc.code})
        return shared.EXIT_NEEDS_HUMAN
    owner = "attachments --recheck" if getattr(args, "recheck", False) else "attachments"
    budget_left = shared.budget_from_minutes(getattr(args, "budget_min", 0))  # 从进程开头算：等锁的时间也在预算里
    try:
        with accounts.account_session(owner, wait_s=float(getattr(args, "wait_lock_min", 10) or 0) * 60):
            return callback(args, budget_left=budget_left)
    except accounts.AccountBusyError as exc:
        print(f"附件补下没跑：{exc}", file=sys.stderr)
        if getattr(args, "recheck", False):
            dump_json({"checked": 0, "found": [], "failed": [], "busy": True})
        return shared.EXIT_ACCOUNT_BUSY


def reconcile_object(obj, meta, m):
    out = {"cleared": 0, "declared": 0, "gone": 0}
    mark_path = obj / "derived" / "web_recheck.json"
    changed = False
    rf = m.get("related_file") or {}
    if m.get("ok") and rf.get("docId"):
        before = len(shared.load_resolved(obj))
        try:
            _remember_probed(obj, meta, str(rf["docId"]), rf.get("name") or f"{rf['docId']}.bin", rf)
        except (OSError, ValueError, KeyError) as exc:
            print(f"[recheck] {obj.name} 附件声明没记上：{exc}", file=sys.stderr)
        out["declared"] += len(shared.load_resolved(obj)) > before
        if m.get("download_error"):
            m.pop("download_error", None)
            m["download_error_cleared"] = "下载交给 attachments --all（带跨夜退避）"
            out["cleared"] += 1
            changed = True
    elif (not m.get("ok") and not m.get("gone") and not m.get("stage")
          and "登录也打不开" in str(m.get("error") or "") and "/explore" in str(m.get("error") or "")):
        m.update(gone=True, gone_at=m.get("checked_at") and shared._iso(shared._parse_dt(m["checked_at"], shared._now_local())) or shared._iso(shared._now_local()),
                 stage="gone", gone_why="游客和登录号都打不开，登录号落到 /explore（本地对账）")
        out["gone"] += 1
        changed = True
        problems_mod.resolve("attachments.recheck", meta.get("item_id") or domain.item_id(xhs.SOURCE, obj.name))
    if changed:
        storage.write_json(mark_path, m)
    return out


def is_restricted(source_id):
    from . import restricted
    return restricted.is_restricted(source_id)


def restricted_text():
    from . import restricted
    return restricted.TEXT


def best_token(source_id, token):
    from . import restricted
    return restricted.best_token(source_id, token)


def looks_blocked(message):
    return xhs.looks_blocked(message)


def blocked_message():
    return "停车：小红书账号要处理（扫码登录或安全验证），剩下的附件处理完再补"
