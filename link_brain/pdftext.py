"""附件 PDF / .docx → Markdown（`derived/attachments/<doc_id>.md`）：哪几份要转、转完记在哪、失败了下次还试不试。

真正的转换在 `docconv.py`（随包自带：pypdfium2 抽文字层 → 坏了 / 扫描件渲成图走本地 OCR；python-docx 读 Word）。
这里只管编排：
- 转出来 → 写 md（落盘前 mdsafe.neutralize），清掉失败标记，问题记录里这篇的转换问题标已解决；
- 失败 → attachments.json 记 conversion_failed（带故障码和当时的 sha256），问题记录登记；
  **只有 PERMANENT（加密 / 损坏 / 不支持的格式）同一份字节不再重试**；SKIPPED（OCR 没开）下次照转；
  TRANSIENT（OCR 服务故障、超时）按 conversion_failed.next_at 退避（attachments.CONVERT_BACKOFF_DAYS：
  第 1/2/3/≥4 次失败后隔 1/2/4/7 个日历日，从那天 0 点起可再转）——到点前跳过，到点后自动再转（第 4 批）。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage
from .docconv import DAMAGED_RATIO, damage_ratio, looks_damaged  # noqa: F401 - 兼容旧引用


def _legacy_shape(r: dict[str, Any]) -> dict[str, Any]:
    """docconv 的 R → 旧调用方认的 {status, method, markdown, note, partial, code}。"""
    return {"status": r.get("status"), "method": r.get("method"), "markdown": r.get("markdown"),
            "note": r.get("note") or r.get("error"), "partial": int(r.get("partial") or 0), "code": r.get("code") or ""}


def pdf_to_markdown(pdf_path: Path, *, force_ocr: bool = False, verbose: bool = False) -> dict[str, Any]:
    from . import docconv
    return _legacy_shape(docconv.pdf_to_markdown(pdf_path, force_ocr=force_ocr, verbose=verbose))


def docx_to_markdown(docx_path: Path, *, verbose: bool = False) -> dict[str, Any]:
    from . import docconv
    return _legacy_shape(docconv.docx_to_markdown(docx_path, verbose=verbose))


CONVERTIBLE_SUFFIXES = (".pdf", ".docx")
PARTIAL_RETRIES = 3  # 有几页没认出来的，同一份字节最多再转几次（之后就认这份带占位的）


def attachment_to_markdown(
    path: Path, *, force_ocr: bool = False, verbose: bool = False
) -> dict[str, Any]:
    """按后缀分流（docconv.to_markdown；设置里关了附件转换就是 skipped）。"""
    from . import docconv
    return _legacy_shape(docconv.to_markdown(path, force_ocr=force_ocr, verbose=verbose))


def _permanent(code: str | None) -> bool:
    # 旧记录没有码：当时只有加密 / 损坏才会落 conversion_failed，按 PERMANENT 算
    return not code or str(code).startswith("PERMANENT.")


def _backing_off(prior: dict[str, Any], now: datetime | None = None) -> bool:
    """TRANSIENT 转换失败还没到 next_at：这次先不转。next_at 缺 / 读不出来 = 不退避（照转）。"""
    if not str(prior.get("code") or "").startswith("TRANSIENT.") or not prior.get("next_at"):
        return False
    try:
        return datetime.fromisoformat(str(prior["next_at"])) > (now or datetime.now().astimezone())
    except (TypeError, ValueError):
        return False


def attachment_md_path(source_key: str, source_id: str, doc_id: str) -> Path:
    return storage.derived_dir(source_key, source_id) / "attachments" / f"{doc_id}.md"


def _synclog_convert(item_id: str, meta: dict[str, Any], ok: bool, reason: str = "", code: str = "") -> None:
    """10-03 同步记录：附件转文字这次真转了的结果（并在「附件」那一项里；重试 = pdf2md 这一篇）。"""
    try:
        from . import synclog
        synclog.note("attachment", item_id, ok, title=meta.get("title"), note_path=meta.get("visible_note"),
                     reason=reason, code=code, retry=None if ok else ["pdf2md", item_id])
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] {type(exc).__name__}: {exc}", file=sys.stderr)


def convert_object_attachments(
    source_key: str, source_id: str, *, force: bool = False, force_ocr: bool = False,
    verbose: bool = False, now: datetime | None = None,
) -> list[dict[str, Any]]:
    """把一个对象已经下下来的 PDF 附件都转成 `derived/attachments/<doc_id>.md`。"""
    from . import attachments as attachments_mod

    from . import problems

    object_dir = storage.object_dir(source_key, source_id)
    try:
        meta = storage.read_json(object_dir / "meta.json")
    except (OSError, ValueError):
        meta = {}
    item_id = meta.get("item_id") or f"{source_key}-{source_id}"
    results = []
    for doc_id, record in attachments_mod.load_downloaded(source_key, source_id).items():
        path = object_dir / "attachments" / (record.get("file") or "")
        if not path.exists() or path.suffix.lower() not in CONVERTIBLE_SUFFIXES:
            continue
        out = attachment_md_path(source_key, source_id, doc_id)
        partial = record.get("conversion_partial") or {}
        retry_partial = bool(partial) and partial.get("sha256") == record.get("sha256") \
            and int(partial.get("tries") or 0) < PARTIAL_RETRIES
        if out.exists() and out.stat().st_mtime >= path.stat().st_mtime and not force and not retry_partial:
            # 1001 C-2：清洗之前转出来的旧 md 顺手补洗一遍（只在有变化时写盘，不重转）
            from .mdsafe import neutralize
            try:
                old = out.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                old = ""
            if old and neutralize(old) != old:
                storage.atomic_write_text(out, neutralize(old))
            results.append({"doc_id": doc_id, "status": "already", "path": str(out)})
            continue
        # 1001（审计 attach-4）：同一份字节已经转失败过（加密 / 损坏）就别每晚再 OCR 一遍；换了文件或 --force 才重试
        prior = record.get("conversion_failed") or {}
        if prior and not force and prior.get("sha256") == record.get("sha256") and _permanent(prior.get("code")):
            results.append({"doc_id": doc_id, "status": "conversion_failed", "note": prior.get("note"),
                            "code": prior.get("code") or ""})
            continue
        if prior and not force and prior.get("sha256") == record.get("sha256") and _backing_off(prior, now):
            # TRANSIENT 退避中：不算这次失败、不重复登记（问题记录里那条带着 next_at）
            results.append({"doc_id": doc_id, "status": "backoff", "note": prior.get("note"),
                            "code": prior.get("code") or "", "next_at": prior.get("next_at")})
            continue
        try:
            outcome = attachment_to_markdown(path, force_ocr=force_ocr, verbose=verbose)
        except Exception as exc:  # noqa: BLE001 - 转换出任何意外都只算这一份失败（下次再试）
            outcome = {"status": "failed", "note": f"{type(exc).__name__}: {exc}", "code": "TRANSIENT.SERVICE_BUSY"}
        if outcome["status"] == "skipped":
            # 没开（附件转换关了 / 扫描件但 OCR 没开）：不算失败、不标 conversion_failed，开了以后下次自然转
            problems.report("attachments.convert", outcome.get("code") or "SKIPPED.NOT_CONFIGURED",
                            f"{record.get('name') or path.name}：{outcome['note']}", action="skipped")
            results.append({"doc_id": doc_id, "status": "skipped", "note": outcome["note"],
                            "code": outcome.get("code") or "SKIPPED.NOT_CONFIGURED"})
            continue
        if outcome["status"] != "ok":
            code = outcome.get("code") or "TRANSIENT.SERVICE_BUSY"
            next_at = attachments_mod.mark_conversion(source_key, source_id, doc_id, outcome["note"], code=code, now=now)
            problems.report("attachments.convert", code, f"{record.get('name') or path.name}：{outcome['note']}",
                            item_id=item_id, title=meta.get("title"), next_at=next_at)
            results.append({"doc_id": doc_id, "status": "failed", "note": outcome["note"], "code": code,
                            "next_at": next_at})
            _synclog_convert(item_id, meta, False, f"{record.get('name') or path.name} 没转成文字：{outcome['note']}", code)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        from .mdsafe import neutralize  # 1001 C-2：附件全文是别人写的，落盘前打断 Dataview 可执行形态
        storage.atomic_write_text(out, neutralize(outcome["markdown"]))
        attachments_mod.mark_conversion(source_key, source_id, doc_id, None,
                                        partial_pages=int(outcome.get("partial") or 0))
        problems.resolve("attachments.convert", item_id)
        _synclog_convert(item_id, meta, True)
        results.append(
            {"doc_id": doc_id, "status": "ok", "method": outcome["method"],
             "note": outcome["note"], "path": str(out)}
        )
    return results


def run(args) -> int:
    """`pdf2md` 子命令。"""
    from . import index as index_mod, render as render_mod

    conn = index_mod.connect()
    try:
        if getattr(args, "all", False):
            rows = conn.execute(
                # 索引里的状态可能落后（附件是事后补下来的），凡是"有附件"的都扫一遍，
                # 真没下过 PDF 的在 convert_object_attachments 里自然跳过
                "SELECT source, source_id FROM objects WHERE attachments_status IN"
                " ('downloaded', 'metadata_only') ORDER BY item_id"
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
        print("没有下过附件字节的对象（先跑 attachments）", file=sys.stderr)
        return 0

    failed = False
    for source_key, source_id in targets:
        results = convert_object_attachments(
            source_key,
            source_id,
            force=getattr(args, "force", False),
            force_ocr=getattr(args, "force_ocr", False),
            verbose=getattr(args, "verbose", False),
        )
        for r in results:
            if r["status"] == "ok":
                print(f"{source_id}  ↳ {r['path']}  [{r['method']}] {r['note']}", file=sys.stderr)
            elif r["status"] == "already":
                print(f"{source_id}  = {r['path']}（已有，--force 可重转）")
            elif r["status"] == "skipped":
                print(f"{source_id}  - 跳过：{r.get('note')}", file=sys.stderr)
            elif r["status"] == "backoff":
                # 上次 TRANSIENT 失败、还没到下次重试时刻：有计划的剩余，不算这次出错（CONVENTIONS §1.2）
                print(f"{source_id}  … 上次没转成（{r.get('note')}），{r.get('next_at')} 之后再转", file=sys.stderr)
            else:
                failed = True
                print(f"{source_id}  ✗ {r.get('note')}", file=sys.stderr)
        if results:
            render_mod.render_object(source_key, source_id)
    from .catalog import build
    build()
    return 1 if failed else 0
