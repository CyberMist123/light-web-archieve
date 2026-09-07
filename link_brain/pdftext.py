"""附件 PDF / .docx → Markdown（`derived/attachments/<doc_id>.md`）。

PDF 两条路，先便宜后贵，全都在本机：

1. **文字层直抽**：`media.py pdf <文件> --out`（本地 pymupdf，免费、秒级）。
2. **渲成图再 OCR**：文字层是坏的就退回这条——pymupdf 把每页渲成 PNG，
   再逐页 `media.py image --ocr`（本地 RapidOCR + Owner 自己的 key，也免费）。

为什么需要第 2 条：小红书上传的教程 PDF 常常是设计工具导出的**子集化字体**，
ToUnicode 表是坏的，文字层抽出来是「⼈机恋」「9 flags」「dPPPf」这种鬼东西
（2026-09-04 实测 `p模式教程-机教版.pdf`）。渲成图走 OCR 出来的是「人机恋」「：flags」，
平均置信度 0.95。判据就是**康熙部首 / CJK 兼容区**那几段码位——正常中文永远不用它们。

硬约束 3：不自研图片理解，一律 subprocess 调 `media.py`（和 `vision.py` 同一套）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import storage, vision as vision_mod

MEDIA_PY = vision_mod.MEDIA_PY

# 正常中文文本永远不会用到这几段：康熙部首、CJK 部首补充、CJK 兼容形式。
# 出现它们 = PDF 的 ToUnicode 映射坏了（子集化字体），文字层不能要。
DAMAGED_RANGES = ((0x2E80, 0x2EFF), (0x2F00, 0x2FDF), (0xFE30, 0xFE4F))
DAMAGED_RATIO = 0.002  # 千分之二就够判：正常文本是 0
MIN_CHARS_PER_PAGE = 40  # 每页平均还不到这些字 = 基本是扫描件，文字层没内容
DEFAULT_DPI = 170
OCR_TIMEOUT = 180
MAX_PAGES = 50  # 再多就不值当了，说明这不是"笔记附件"而是本书


def damage_ratio(text: str) -> float:
    """坏字形占比。正常文本返回 0。"""
    if not text:
        return 0.0
    bad = sum(
        1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in DAMAGED_RANGES)
    )
    return bad / len(text)


def looks_damaged(text: str, *, pages: int = 1) -> tuple[bool, str]:
    """文字层能不能要。返回 `(要不要退回 OCR, 原因)`。"""
    stripped = re.sub(r"\s+", "", text or "")
    if not stripped:
        return True, "文字层是空的（扫描件？）"
    if pages > 0 and len(stripped) / pages < MIN_CHARS_PER_PAGE:
        return True, f"每页平均只有 {len(stripped) // max(pages, 1)} 个字，像扫描件"
    ratio = damage_ratio(stripped)
    if ratio > DAMAGED_RATIO:
        return True, f"字形映射坏了（康熙部首/兼容区占 {ratio:.1%}，子集化字体）"
    return False, "文字层可用"


def _run_media(args: list[str], *, timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["python", MEDIA_PY, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"subprocess 调用失败: {type(exc).__name__}: {exc}"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return False, (proc.stderr or "").strip() or out or f"media.py 退出码 {proc.returncode}"
    return True, out


def text_layer_markdown(pdf_path: Path, *, timeout: int = 300) -> tuple[str | None, str]:
    """`media.py pdf --out` 抽文字层。返回 `(markdown 或 None, 说明)`。

    `--out` 只回一行「[已落文件] <路径> (N 字)」，所以要把那个路径读回来。
    """
    ok, out = _run_media(["pdf", str(pdf_path), "--out"], timeout=timeout)
    if not ok:
        return None, out
    match = re.search(r"\[已落文件\]\s*(.+?\.md)", out)
    if not match:
        return None, f"media.py pdf 没给出落地文件：{out[:200]}"
    produced = Path(match.group(1).strip())
    if not produced.exists():
        return None, f"media.py pdf 说落在 {produced}，但文件不在"
    return produced.read_text(encoding="utf-8"), f"文字层来自 {produced.name}"


def ocr_markdown(
    pdf_path: Path, *, dpi: int = DEFAULT_DPI, max_pages: int = MAX_PAGES, verbose: bool = False
) -> tuple[str | None, str]:
    """每页渲成 PNG 再 `media.py image --ocr`，拼成一份 Markdown。"""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - 环境问题，说清楚就行
        return None, f"没装 pymupdf，渲不了页：{exc}"

    def log(msg: str) -> None:
        if verbose:
            print(f"[pdf] {msg}", file=sys.stderr)

    doc = pymupdf.open(str(pdf_path))
    total = doc.page_count
    pages = min(total, max_pages)
    lines = [f"# {pdf_path.name}", "", f"（{total} 页，OCR 逐页识别）", ""]
    if total > max_pages:
        lines += [f"> 只识别了前 {max_pages} 页（上限 {MAX_PAGES}）。", ""]

    failed = 0
    tmp_dir = Path(tempfile.mkdtemp(prefix="link-brain-pdf-"))
    try:
        for index in range(pages):
            png = tmp_dir / f"page-{index + 1:03d}.png"
            doc[index].get_pixmap(dpi=dpi).save(str(png))
            log(f"OCR 第 {index + 1}/{pages} 页")
            result = vision_mod.run_ocr(png, timeout=OCR_TIMEOUT)
            lines += [f"## 第 {index + 1} 页", ""]
            if result["status"] == "ok" and (result.get("ocr") or "").strip():
                lines += [result["ocr"].strip(), ""]
            else:
                failed += 1
                lines += [f"（这一页没识别出来：{result.get('error') or '空结果'}）", ""]
            png.unlink(missing_ok=True)
    finally:
        doc.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    note = f"逐页 OCR {pages}/{total} 页" + (f"，{failed} 页失败" if failed else "")
    return "\n".join(lines), note


def pdf_to_markdown(
    pdf_path: Path, *, force_ocr: bool = False, verbose: bool = False
) -> dict[str, Any]:
    """PDF → Markdown 文本。先文字层，坏了才 OCR。返回 `{status, method, markdown, note}`。"""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"status": "failed", "method": None, "markdown": None, "note": f"文件不在: {pdf_path}"}

    pages = 0
    try:
        import pymupdf

        with pymupdf.open(str(pdf_path)) as doc:
            pages = doc.page_count
    except Exception:  # noqa: BLE001 - 数不出页数不影响后面的判断
        pages = 0

    if not force_ocr:
        text, note = text_layer_markdown(pdf_path)
        if text is not None:
            damaged, why = looks_damaged(text, pages=pages or 1)
            if not damaged:
                return {"status": "ok", "method": "text_layer", "markdown": text, "note": f"{note}；{why}"}
            if verbose:
                print(f"[pdf] 文字层不能要（{why}），退回逐页 OCR", file=sys.stderr)
            fallback_reason = why
        else:
            fallback_reason = note
    else:
        fallback_reason = "--force-ocr"

    text, note = ocr_markdown(pdf_path, verbose=verbose)
    if text is None:
        return {"status": "failed", "method": "ocr", "markdown": None, "note": note}
    return {"status": "ok", "method": "ocr", "markdown": text, "note": f"{fallback_reason} → {note}"}


def docx_to_markdown(docx_path: Path, *, verbose: bool = False) -> dict[str, Any]:
    """.docx → Markdown，走 `media.py docx --out`（本地 python-docx 读文字层）。

    docx 不像 PDF 那样有子集化字体坏文字层的问题——python-docx 读的是 `word/document.xml`
    里的 Unicode 文本，不经排版引擎，所以没有 PDF 那条 OCR 退回路。返回和 `pdf_to_markdown`
    同构的 `{status, method, markdown, note}`。
    """
    docx_path = Path(docx_path)
    if not docx_path.exists():
        return {"status": "failed", "method": "docx", "markdown": None, "note": f"文件不在: {docx_path}"}
    ok, out = _run_media(["docx", str(docx_path), "--out"], timeout=180)
    if not ok:
        return {"status": "failed", "method": "docx", "markdown": None, "note": out}
    match = re.search(r"\[已落文件\]\s*(.+?\.md)", out)
    if not match:
        return {"status": "failed", "method": "docx", "markdown": None,
                "note": f"media.py docx 没给出落地文件：{out[:200]}"}
    produced = Path(match.group(1).strip())
    if not produced.exists():
        return {"status": "failed", "method": "docx", "markdown": None,
                "note": f"media.py docx 说落在 {produced}，但文件不在"}
    return {"status": "ok", "method": "docx", "markdown": produced.read_text(encoding="utf-8"),
            "note": f"docx 文字层来自 {produced.name}"}


CONVERTIBLE_SUFFIXES = (".pdf", ".docx")


def attachment_to_markdown(
    path: Path, *, force_ocr: bool = False, verbose: bool = False
) -> dict[str, Any]:
    """按后缀分流：.pdf 走 pdf_to_markdown（坏文字层退回 OCR）、.docx 走 docx_to_markdown。"""
    if Path(path).suffix.lower() == ".docx":
        return docx_to_markdown(path, verbose=verbose)
    return pdf_to_markdown(path, force_ocr=force_ocr, verbose=verbose)


def attachment_md_path(source_key: str, source_id: str, doc_id: str) -> Path:
    return storage.derived_dir(source_key, source_id) / "attachments" / f"{doc_id}.md"


def convert_object_attachments(
    source_key: str, source_id: str, *, force: bool = False, force_ocr: bool = False,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """把一个对象已经下下来的 PDF 附件都转成 `derived/attachments/<doc_id>.md`。"""
    from . import attachments as attachments_mod

    object_dir = storage.object_dir(source_key, source_id)
    results = []
    for doc_id, record in attachments_mod.load_downloaded(source_key, source_id).items():
        path = object_dir / "attachments" / (record.get("file") or "")
        if not path.exists() or path.suffix.lower() not in CONVERTIBLE_SUFFIXES:
            continue
        out = attachment_md_path(source_key, source_id, doc_id)
        if out.exists() and not force:
            results.append({"doc_id": doc_id, "status": "already", "path": str(out)})
            continue
        outcome = attachment_to_markdown(path, force_ocr=force_ocr, verbose=verbose)
        if outcome["status"] != "ok":
            results.append({"doc_id": doc_id, "status": "failed", "note": outcome["note"]})
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(outcome["markdown"], encoding="utf-8")
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
        print("没有下过附件字节的对象（先跑 attachments）")
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
                print(f"{source_id}  ↳ {r['path']}  [{r['method']}] {r['note']}")
            elif r["status"] == "already":
                print(f"{source_id}  = {r['path']}（已有，--force 可重转）")
            else:
                failed = True
                print(f"{source_id}  ✗ {r.get('note')}", file=sys.stderr)
        if results:
            render_mod.render_object(source_key, source_id)
    return 1 if failed else 0
