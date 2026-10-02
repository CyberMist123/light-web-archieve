"""附件 PDF / Word → Markdown 执行器（CONVENTIONS §4）：`to_markdown(path, cfg)` → R（另带 markdown / method / note / partial）。

随包自带、全在本机、不要 key：
- PDF：pypdfium2（Apache-2.0 / BSD-3）抽文字层；文字层是坏的（子集化字体的康熙部首码位）或几乎没字（扫描件），
  就把页面渲成图交给本地 OCR（vision.run_ocr = rapidocr）。文字层整体能用时，只有个别空白页走 OCR。
- Word（.docx）：python-docx（MIT）读 XML 文字层，按正文顺序转段落 / 标题 / 列表 / 表格 / 超链接。
- 加密 → PERMANENT.PDF_ENCRYPTED；打不开 → PERMANENT.PDF_DAMAGED；.docx 打不开 / 别的格式 → PERMANENT.DOC_UNSUPPORTED。
  扫描件但 OCR 没开 → SKIPPED.NOT_CONFIGURED（开了以后再转）。单页失败只在那一页写占位，整份照出，标 partial。

为什么要判「文字层坏了」：小红书上传的教程 PDF 常常是设计工具导出的**子集化字体**，ToUnicode 表是坏的，
文字层抽出来是「⼈机恋」「9 flags」这种东西（2026-09-04 实测）。渲成图走 OCR 出来是「人机恋」。
判据是**康熙部首 / CJK 部首补充 / CJK 兼容形式**那几段码位——正常中文永远不用它们。
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import providers

DAMAGED_RANGES = ((0x2E80, 0x2EFF), (0x2F00, 0x2FDF), (0xFE30, 0xFE4F))
DAMAGED_RATIO = 0.002  # 千分之二就够判：正常文本是 0
MIN_CHARS_PER_PAGE = 40  # 每页平均还不到这些字 = 基本是扫描件，文字层没内容
EMPTY_PAGE_CHARS = 20  # 文字层整体能用时，单页少于这些字（封面图 / 扫描页）才单独 OCR
DEFAULT_DPI = 170
PDFIUM_ERR_PASSWORD = 4


def damage_ratio(text: str) -> float:
    """坏字形占比。正常文本返回 0。"""
    if not text:
        return 0.0
    bad = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in DAMAGED_RANGES))
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


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(f"[pdf] {msg}", file=sys.stderr)


def _fail(code: str, note: str, method: str | None = None) -> dict[str, Any]:
    status = "skipped" if code.startswith("SKIPPED.") else "failed"
    return providers.result(status, code=code, error=note, markdown=None, method=method, note=note, partial=0)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def open_pdf(path: Path):
    """打开 PDF。返回 (文档 或 None, 失败时的 R)。"""
    import pypdfium2 as pdfium
    try:
        return pdfium.PdfDocument(str(path)), None
    except pdfium.PdfiumError as exc:
        if getattr(exc, "err_code", None) == PDFIUM_ERR_PASSWORD:
            return None, _fail("PERMANENT.PDF_ENCRYPTED", "PDF 有打开密码，转不了（字节已保存）")
        return None, _fail("PERMANENT.PDF_DAMAGED", f"PDF 打不开（可能损坏）：{exc}")
    except Exception as exc:  # noqa: BLE001 - 读文件出任何意外都只算这一份
        return None, _fail("PERMANENT.PDF_DAMAGED", f"PDF 打不开（可能损坏）：{type(exc).__name__}: {exc}")


def page_texts(doc) -> list[str]:
    """每页文字层（阅读顺序）；某一页抽不出来就当空页（后面会走 OCR）。"""
    out = []
    for index in range(len(doc)):
        try:
            page = doc[index]
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_bounded()
            finally:
                textpage.close()
        except Exception:  # noqa: BLE001
            text = ""
        out.append((text or "").replace("\r\n", "\n").replace("\r", "\n").strip())
    return out


def ocr_page(doc, index: int, tmp_dir: Path, *, dpi: int = DEFAULT_DPI, ocr_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """把第 index 页渲成 PNG 交给本地 OCR。返回 vision.run_ocr 的结果；渲不出来算这一页失败。"""
    from . import vision
    png = tmp_dir / f"page-{index + 1:03d}.png"
    try:
        doc[index].render(scale=dpi / 72).to_pil().save(png)
        return vision.run_ocr(png, ocr_cfg)
    except Exception as exc:  # noqa: BLE001 - 单页坏了只影响这一页
        return {"status": "failed", "ocr": None, "error": f"这一页渲不出来：{type(exc).__name__}: {exc}"}
    finally:
        png.unlink(missing_ok=True)


def _ocr_text(result: dict[str, Any]) -> str:
    from .ocrtext import clean_ocr
    return clean_ocr(result.get("ocr") or "") if result.get("status") == "ok" else ""


def pdf_to_markdown(path: Path, *, force_ocr: bool = False, verbose: bool = False,
                    ocr_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """PDF → Markdown。先文字层，坏了 / 扫描件才 OCR。"""
    path = Path(path)
    if not path.is_file():
        return _fail("PERMANENT.DOC_UNSUPPORTED", f"文件不在: {path.name}")
    doc, err = open_pdf(path)
    if err:
        return err
    try:
        total = len(doc)
        texts = [""] * total if force_ocr else page_texts(doc)
        damaged, why = (True, "--force-ocr") if force_ocr else looks_damaged("\n".join(texts), pages=total or 1)
        ocr_pages = list(range(total)) if damaged else [i for i, t in enumerate(texts)
                                                        if len(re.sub(r"\s+", "", t)) < EMPTY_PAGE_CHARS]
        if damaged:
            _log(verbose, f"文字层不能要（{why}），逐页 OCR")
        from . import providers as prov, visual
        ocr_ready = bool(ocr_pages) and (ocr_cfg or prov.resolve("ocr")) is not None and visual.available()
        if damaged and not ocr_ready:
            reason = prov.why_not("ocr") or "没装本地 OCR（pip install rapidocr）"
            return _fail("SKIPPED.NOT_CONFIGURED", f"{why}，要本地 OCR 才转得出来：{reason}", "ocr")
        lines = [f"# {path.name}", "", f"（{total} 页" + ("，OCR 逐页识别）" if damaged else "）"), ""]
        failed = 0
        tmp_dir = Path(tempfile.mkdtemp(prefix="link-brain-pdf-"))
        try:
            for index in range(total):
                lines += [f"## 第 {index + 1} 页", ""]
                text = texts[index]
                if index in ocr_pages and ocr_ready:
                    _log(verbose, f"OCR 第 {index + 1}/{total} 页")
                    result = ocr_page(doc, index, tmp_dir, ocr_cfg=ocr_cfg)
                    got = _ocr_text(result)
                    if got.strip():
                        text = got.strip()
                    elif damaged:
                        failed += 1
                        text = f"（这一页没识别出来：{result.get('error') or '空结果'}）"
                if text:
                    lines += [text, ""]
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        doc.close()
    if damaged and total and failed >= total:
        return _fail("PERMANENT.PDF_DAMAGED", f"{why} → 逐页 OCR 一页都没认出来", "ocr")
    if damaged:
        note = f"{why} → 逐页 OCR {total}/{total} 页" + (f"，{failed} 页失败" if failed else "")
        method = "ocr"
    else:
        extra = len(ocr_pages) if ocr_ready else 0
        note = "文字层可用" + (f"；{extra} 页几乎没字，走了 OCR" if extra else "")
        method = "text_layer"
    return providers.result("ok", "\n".join(lines).rstrip() + "\n", markdown="\n".join(lines).rstrip() + "\n",
                            method=method, note=note, partial=failed)


# --------------------------------------------------------------------------
# Word（移植自作者本机脚本的 docx_to_markdown：段落、标题、列表、表格、超链接）
# --------------------------------------------------------------------------

def _docx_para_md(para) -> str:
    """一个段落 → 一行 Markdown。按 XML 子节点顺序走，保住超链接文字和地址。"""
    from docx.oxml.ns import qn

    rels = para.part.rels
    out: list[str] = []
    for child in para._p.iterchildren():
        tag = child.tag
        if tag == qn("w:r"):
            txt = "".join(node.text or "" for node in child.iter(qn("w:t")))
            if not txt:
                continue
            rpr = child.find(qn("w:rPr"))
            bold = rpr is not None and rpr.find(qn("w:b")) is not None
            italic = rpr is not None and rpr.find(qn("w:i")) is not None
            if bold:
                txt = f"**{txt}**"
            elif italic:
                txt = f"*{txt}*"
            out.append(txt)
        elif tag == qn("w:hyperlink"):
            txt = "".join(node.text or "" for node in child.iter(qn("w:t")))
            rid = child.get(qn("r:id"))
            url = ""
            if rid and rid in rels:
                try:
                    url = rels[rid].target_ref
                except Exception:  # noqa: BLE001
                    url = ""
            out.append(f"[{txt}]({url})" if url and txt else (txt or url))
    # 相邻加粗 run 拼一起会出 `****`，合并掉
    return re.sub(r"\*\*(\s*)\*\*", r"\1", "".join(out)).strip()


def _docx_table_md(table) -> str:
    """一个表格 → Markdown 表格。首行当表头；单元格里的换行压成空格；单列表格当普通段落。"""
    rows = []
    for row in table.rows:
        rows.append([re.sub(r"\s*\n\s*", " ", (c.text or "").strip()).replace("|", "\\|") for c in row.cells])
    if not rows or not any(any(c for c in r) for r in rows):
        return ""  # docx 里当视觉方框用的空单元格表格，跳过
    width = max(len(r) for r in rows)
    if width == 1:
        return "\n\n".join(r[0] for r in rows if r and r[0])
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def docx_markdown_text(path: Path) -> str:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    parts: list[str] = [f"# {Path(path).name}", ""]
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, doc)
            text = _docx_para_md(para)
            if not text:
                continue
            style = (para.style.name or "") if para.style is not None else ""
            m = re.match(r"Heading (\d+)", style)
            if style == "Title":
                parts.append(f"## {text}")
            elif m:
                parts.append(f"{'#' * min(int(m.group(1)) + 1, 6)} {text}")  # 文件名占 H1，标题从 H2 起
            elif style.startswith("List Bullet"):
                parts.append(f"- {text}")
            elif style.startswith("List Number"):
                parts.append(f"1. {text}")
            else:
                parts.append(text)
            parts.append("")
        elif child.tag == qn("w:tbl"):
            table_md = _docx_table_md(Table(child, doc))
            if table_md:
                parts += [table_md, ""]
    return "\n".join(parts).rstrip() + "\n"


def docx_to_markdown(path: Path, *, verbose: bool = False) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return _fail("PERMANENT.DOC_UNSUPPORTED", f"文件不在: {path.name}", "docx")
    try:
        import docx  # noqa: F401
    except ImportError:
        return _fail("SKIPPED.NOT_CONFIGURED", "没装 python-docx（pip install -e . 会装上）", "docx")
    try:
        body = docx_markdown_text(path)
    except Exception as exc:  # noqa: BLE001 - 坏文件 / 不是真 docx
        return _fail("PERMANENT.DOC_UNSUPPORTED", f"Word 文件打不开（可能损坏或不是 .docx）：{type(exc).__name__}", "docx")
    return providers.result("ok", body, markdown=body, method="docx", note="docx 文字层", partial=0)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

CONVERTIBLE_SUFFIXES = (".pdf", ".docx")


def to_markdown(path: Path, cfg: dict[str, Any] | None = None, *, force_ocr: bool = False,
                verbose: bool = False) -> dict[str, Any]:
    """按后缀分流。cfg 缺省 = providers.resolve('docConvert')；关了 → skipped。"""
    cfg = cfg if cfg is not None else providers.resolve("docConvert")
    if cfg is None:
        r = providers.skipped_for("docConvert")
        return {**r, "markdown": None, "method": None, "note": r["error"], "partial": 0}
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return docx_to_markdown(path, verbose=verbose)
    if suffix == ".pdf":
        return pdf_to_markdown(path, force_ocr=force_ocr, verbose=verbose)
    return _fail("PERMANENT.DOC_UNSUPPORTED", f"这种文档格式（{suffix or '无后缀'}）还转不了，原件已保存")
