"""附件 PDF → Markdown：文字层坏了要认得出来，并自动退回逐页 OCR。

真机背景（2026-09-04）：`p模式教程-机教版.pdf` 是子集化字体导出的，文字层抽出来是
「⼈机恋」「9 flags」「dPPPf」；渲成图走 OCR 就是「人机恋」「：flags」，置信度 0.95。
"""

from __future__ import annotations

from pathlib import Path

from link_brain import pdftext, storage

REAL_DAMAGED = "⼈机恋⾃建前端陪伴场景的完整技术参考9 flags､事件 schema､可抄的服务器⻣架"
REAL_CLEAN = "人机恋自建前端陪伴场景的完整技术参考：flags、事件 schema、可抄的服务器骨架"


def test_damage_ratio_only_fires_on_broken_glyphs():
    assert pdftext.damage_ratio(REAL_CLEAN) == 0
    assert pdftext.damage_ratio(REAL_DAMAGED) > pdftext.DAMAGED_RATIO
    assert pdftext.damage_ratio("") == 0


def test_looks_damaged_covers_broken_empty_and_scanned():
    long_clean = REAL_CLEAN * 3
    assert pdftext.looks_damaged(long_clean, pages=1) == (False, "文字层可用")
    damaged, why = pdftext.looks_damaged(REAL_DAMAGED * 3, pages=1)
    assert damaged and "字形映射坏了" in why
    damaged, why = pdftext.looks_damaged("", pages=1)
    assert damaged and "空的" in why
    damaged, why = pdftext.looks_damaged("页码", pages=19)  # 扫描件：文字层几乎没东西
    assert damaged and "扫描件" in why


def test_text_layer_used_when_clean(monkeypatch, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        pdftext, "text_layer_markdown", lambda p, **kw: (REAL_CLEAN * 20, "文字层来自 x.md")
    )

    def no_ocr(*a, **k):
        raise AssertionError("文字层干净时不该再花力气 OCR")

    monkeypatch.setattr(pdftext, "ocr_markdown", no_ocr)
    out = pdftext.pdf_to_markdown(pdf)
    assert out["status"] == "ok" and out["method"] == "text_layer"


def test_falls_back_to_ocr_when_text_layer_is_broken(monkeypatch, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        pdftext, "text_layer_markdown", lambda p, **kw: (REAL_DAMAGED * 20, "文字层来自 x.md")
    )
    monkeypatch.setattr(pdftext, "ocr_markdown", lambda p, **kw: ("# OCR 出来的", "逐页 OCR 2/2 页"))
    out = pdftext.pdf_to_markdown(pdf)
    assert out["status"] == "ok" and out["method"] == "ocr"
    assert "字形映射坏了" in out["note"] and "逐页 OCR" in out["note"]


def test_convert_object_writes_derived_attachment_md(monkeypatch, tmp_path):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    source, source_id, doc_id = "xiaohongshu", "0000000000000000deadbeef", "7658854832003020032"

    object_dir = storage.object_dir(source, source_id)
    (object_dir / "attachments").mkdir(parents=True)
    (object_dir / "attachments" / "教程.pdf").write_bytes(b"%PDF-1.4\n")
    storage.write_json(
        object_dir / "attachments.json",
        {"schema_version": 1, "files": [{"doc_id": doc_id, "file": "教程.pdf", "name": "教程.pdf"}]},
    )
    monkeypatch.setattr(pdftext, "pdf_to_markdown", lambda p, **kw: {
        "status": "ok", "method": "ocr", "markdown": "# 教程\n\n正文", "note": "逐页 OCR 1/1 页",
    })

    results = pdftext.convert_object_attachments(source, source_id)
    assert results and results[0]["status"] == "ok"
    out = Path(results[0]["path"])
    assert out == pdftext.attachment_md_path(source, source_id, doc_id)
    assert out.read_text(encoding="utf-8").startswith("# 教程")

    # 再来一次是 already，不重复烧 OCR
    assert pdftext.convert_object_attachments(source, source_id)[0]["status"] == "already"


def test_docx_to_markdown_reads_media_output(monkeypatch, tmp_path):
    docx = tmp_path / "说明.docx"
    docx.write_bytes(b"PK\x03\x04")  # 真解析在 media.py，这里只要文件存在
    produced = tmp_path / "out.md"
    produced.write_text("# 说明.docx\n\n正文", encoding="utf-8")
    monkeypatch.setattr(
        pdftext, "_run_media", lambda args, **kw: (True, f"[已落文件] {produced}  (5 字)")
    )
    out = pdftext.docx_to_markdown(docx)
    assert out["status"] == "ok" and out["method"] == "docx"
    assert out["markdown"].startswith("# 说明") and "docx" in out["note"]


def test_docx_to_markdown_reports_media_failure(monkeypatch, tmp_path):
    docx = tmp_path / "说明.docx"
    docx.write_bytes(b"PK\x03\x04")
    monkeypatch.setattr(pdftext, "_run_media", lambda args, **kw: (False, "没装 python-docx"))
    out = pdftext.docx_to_markdown(docx)
    assert out["status"] == "failed" and "python-docx" in out["note"]


def test_attachment_to_markdown_routes_by_suffix(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(pdftext, "docx_to_markdown", lambda p, **kw: calls.append("docx"))
    monkeypatch.setattr(pdftext, "pdf_to_markdown", lambda p, **kw: calls.append("pdf"))
    pdftext.attachment_to_markdown(tmp_path / "a.docx")
    pdftext.attachment_to_markdown(tmp_path / "a.PDF")  # 大小写不敏感
    assert calls == ["docx", "pdf"]


def test_convert_object_handles_docx_attachment(monkeypatch, tmp_path):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    source, source_id, doc_id = "xiaohongshu", "0000000000000000cafef00d", "7674670185753611914"
    object_dir = storage.object_dir(source, source_id)
    (object_dir / "attachments").mkdir(parents=True)
    (object_dir / "attachments" / "说明.docx").write_bytes(b"PK\x03\x04")
    storage.write_json(
        object_dir / "attachments.json",
        {"schema_version": 1, "files": [{"doc_id": doc_id, "file": "说明.docx", "name": "说明.docx"}]},
    )
    monkeypatch.setattr(pdftext, "docx_to_markdown", lambda p, **kw: {
        "status": "ok", "method": "docx", "markdown": "# 说明\n\n正文", "note": "docx 文字层来自 x.md",
    })
    results = pdftext.convert_object_attachments(source, source_id)
    assert results and results[0]["status"] == "ok" and results[0]["method"] == "docx"
    out = Path(results[0]["path"])
    assert out == pdftext.attachment_md_path(source, source_id, doc_id)
    assert out.read_text(encoding="utf-8").startswith("# 说明")
