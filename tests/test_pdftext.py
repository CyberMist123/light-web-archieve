"""附件 PDF / Word → Markdown（第 1B 批：随包自带的 docconv，pypdfium2 + rapidocr + python-docx）。

真机背景（2026-09-04）：`p模式教程-机教版.pdf` 是子集化字体导出的，文字层抽出来是
「⼈机恋」「9 flags」「dPPPf」；渲成图走 OCR 就是「人机恋」「：flags」，置信度 0.95。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _samples import blank_pdf, docx, encrypted_pdf_bytes, image_pdf, text_pdf
from link_brain import attachments as att_mod, docconv, pdftext, problems, storage, vision as vision_mod, visual

REAL_DAMAGED = "⼈机恋⾃建前端陪伴场景的完整技术参考9 flags､事件 schema､可抄的服务器⻣架"
REAL_CLEAN = "人机恋自建前端陪伴场景的完整技术参考：flags、事件 schema、可抄的服务器骨架"
CLEAN_LINES = ["Tutorial: build a companion front end with flags and an event schema."] * 6


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


def test_text_layer_pdf_converts_without_ocr(monkeypatch, tmp_path):
    pdf = text_pdf(tmp_path / "a.pdf", [CLEAN_LINES, CLEAN_LINES])

    def no_ocr(*a, **k):
        raise AssertionError("文字层干净时不该再花力气 OCR")

    monkeypatch.setattr(vision_mod, "run_ocr", no_ocr)
    out = pdftext.pdf_to_markdown(pdf)
    assert out["status"] == "ok" and out["method"] == "text_layer" and out["code"] == ""
    md = out["markdown"]
    assert md.startswith("# a.pdf") and "（2 页）" in md and "## 第 2 页" in md
    assert "companion front end" in md


def test_scanned_pdf_goes_through_local_ocr(monkeypatch, tmp_path):
    pdf = image_pdf(tmp_path / "scan.pdf", ["PAGE ONE", "PAGE TWO"])
    seen = []
    monkeypatch.setattr(visual, "available", lambda: True)
    monkeypatch.setattr(vision_mod, "run_ocr", lambda path, cfg=None, **k: seen.append(path) or
                        {"status": "ok", "ocr": f"第{len(seen)}页的字\n(OCR 行数 1，均信心 0.95)"})
    out = pdftext.pdf_to_markdown(pdf)
    assert out["status"] == "ok" and out["method"] == "ocr" and len(seen) == 2
    assert "第1页的字" in out["markdown"] and "第2页的字" in out["markdown"]
    assert "OCR 行数" not in out["markdown"], "统计行不进正文"
    assert "扫描件" in out["note"] or "空的" in out["note"]


def test_scanned_pdf_without_ocr_is_skipped_not_failed(monkeypatch, tmp_path):
    pdf = image_pdf(tmp_path / "scan.pdf", ["PAGE ONE"])
    monkeypatch.setattr(visual, "available", lambda: False)
    out = docconv.pdf_to_markdown(pdf)
    assert out["status"] == "skipped" and out["code"] == "SKIPPED.NOT_CONFIGURED"
    assert "OCR" in out["error"]


def test_partial_ocr_keeps_good_pages_with_placeholder(monkeypatch, tmp_path):
    """1001（审计 attach-4）：一页没认出来只在那页写占位，整份照出；标 partial 让后面再试几次。"""
    pdf = blank_pdf(tmp_path / "partial.pdf", pages=2)
    results = iter([{"status": "ok", "ocr": "first page"},
                    {"status": "failed", "error": "service unavailable"}])
    monkeypatch.setattr(visual, "available", lambda: True)
    monkeypatch.setattr(vision_mod, "run_ocr", lambda *a, **k: next(results))
    outcome = pdftext.pdf_to_markdown(pdf, force_ocr=True)
    assert outcome["status"] == "ok" and outcome["partial"] == 1
    assert "first page" in outcome["markdown"] and "这一页没识别出来" in outcome["markdown"]
    assert "1 页失败" in outcome["note"]


def test_damaged_text_layer_falls_back_to_ocr(monkeypatch, tmp_path):
    pdf = text_pdf(tmp_path / "a.pdf", [["x"]])
    monkeypatch.setattr(docconv, "page_texts", lambda doc: [REAL_DAMAGED * 20])
    monkeypatch.setattr(visual, "available", lambda: True)
    monkeypatch.setattr(vision_mod, "run_ocr", lambda *a, **k: {"status": "ok", "ocr": "人机恋"})
    out = pdftext.pdf_to_markdown(pdf)
    assert out["status"] == "ok" and out["method"] == "ocr"
    assert "字形映射坏了" in out["note"] and "逐页 OCR" in out["note"] and "人机恋" in out["markdown"]


def test_encrypted_and_damaged_pdfs_are_permanent(tmp_path):
    locked = tmp_path / "locked.pdf"
    locked.write_bytes(encrypted_pdf_bytes())
    out = docconv.to_markdown(locked)
    assert out["status"] == "failed" and out["code"] == "PERMANENT.PDF_ENCRYPTED" and "密码" in out["error"]
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nnot really a pdf")
    out = docconv.to_markdown(broken)
    assert out["status"] == "failed" and out["code"] == "PERMANENT.PDF_DAMAGED"


def test_docx_to_markdown_keeps_headings_lists_and_tables(tmp_path):
    out = pdftext.docx_to_markdown(docx(tmp_path / "说明.docx"))
    assert out["status"] == "ok" and out["method"] == "docx"
    md = out["markdown"]
    assert md.startswith("# 说明.docx")
    assert "## 合成说明书" in md and "- 第一条要点" in md and "1. 第二条要点" in md
    assert "| 材料 | 用量 |" in md and "| --- | --- |" in md and "| 番茄 | 两个 |" in md


def test_broken_docx_and_unknown_formats_are_permanent(tmp_path):
    bad = tmp_path / "坏.docx"
    bad.write_bytes(b"PK\x03\x04 not a real zip")
    out = docconv.to_markdown(bad)
    assert out["status"] == "failed" and out["code"] == "PERMANENT.DOC_UNSUPPORTED"
    other = tmp_path / "x.pptx"
    other.write_bytes(b"PK")
    assert docconv.to_markdown(other)["code"] == "PERMANENT.DOC_UNSUPPORTED"


def test_doc_convert_off_is_skipped(monkeypatch, tmp_path):
    from link_brain import ai_config
    monkeypatch.setattr(ai_config, "load", lambda: ai_config._deep_merge(ai_config.DEFAULTS, {"docConvert": {"mode": "off"}}))
    out = docconv.to_markdown(text_pdf(tmp_path / "a.pdf", [CLEAN_LINES]))
    assert out["status"] == "skipped" and out["code"] == "SKIPPED.DISABLED"


def test_attachment_to_markdown_routes_by_suffix(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(docconv, "docx_to_markdown", lambda p, **kw: calls.append("docx") or {"status": "ok"})
    monkeypatch.setattr(docconv, "pdf_to_markdown", lambda p, **kw: calls.append("pdf") or {"status": "ok"})
    pdftext.attachment_to_markdown(tmp_path / "a.docx")
    pdftext.attachment_to_markdown(tmp_path / "a.PDF")  # 大小写不敏感
    assert calls == ["docx", "pdf"]


def _object_with(tmp_path, monkeypatch, name, payload, source_id="0000000000000000deadbeef", doc_id="7658854832003020032"):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    source = "xiaohongshu"
    object_dir = storage.object_dir(source, source_id)
    (object_dir / "attachments").mkdir(parents=True)
    (object_dir / "attachments" / name).write_bytes(payload)
    storage.write_json(object_dir / "meta.json", {"item_id": f"xhs-{source_id}", "title": "合成笔记"})
    storage.write_json(object_dir / "attachments.json",
                       {"schema_version": 1, "files": [{"doc_id": doc_id, "file": name, "name": name, "sha256": "s1"}]})
    return source, source_id, doc_id


def test_convert_object_writes_derived_attachment_md(monkeypatch, tmp_path):
    payload = text_pdf(tmp_path / "src.pdf", [CLEAN_LINES]).read_bytes()
    source, source_id, doc_id = _object_with(tmp_path / "v", monkeypatch, "教程.pdf", payload)
    results = pdftext.convert_object_attachments(source, source_id)
    assert results and results[0]["status"] == "ok" and results[0]["method"] == "text_layer"
    out = Path(results[0]["path"])
    assert out == pdftext.attachment_md_path(source, source_id, doc_id)
    assert out.read_text(encoding="utf-8").startswith("# 教程.pdf")
    # 再来一次是 already，不重复转
    assert pdftext.convert_object_attachments(source, source_id)[0]["status"] == "already"


def test_convert_object_handles_docx_attachment(monkeypatch, tmp_path):
    payload = docx(tmp_path / "src.docx").read_bytes()
    source, source_id, doc_id = _object_with(tmp_path / "v", monkeypatch, "说明.docx", payload,
                                             source_id="0000000000000000cafef00d", doc_id="7674670185753611914")
    results = pdftext.convert_object_attachments(source, source_id)
    assert results and results[0]["status"] == "ok" and results[0]["method"] == "docx"
    assert Path(results[0]["path"]).read_text(encoding="utf-8").startswith("# 说明.docx")


def test_permanent_failure_is_recorded_and_not_retried(monkeypatch, tmp_path):
    source, source_id, doc_id = _object_with(tmp_path / "v", monkeypatch, "锁.pdf", encrypted_pdf_bytes())
    first = pdftext.convert_object_attachments(source, source_id)
    assert first[0]["status"] == "failed" and first[0]["code"] == "PERMANENT.PDF_ENCRYPTED"
    rec = att_mod.load_downloaded(source, source_id)[doc_id]
    assert rec["conversion_failed"]["code"] == "PERMANENT.PDF_ENCRYPTED"
    rows = [r for r in problems.load() if r["step"] == "attachments.convert"]
    assert rows and rows[0]["code"] == "PERMANENT.PDF_ENCRYPTED" and rows[0]["item_id"] == f"xhs-{source_id}"
    again = pdftext.convert_object_attachments(source, source_id)
    assert again[0]["status"] == "conversion_failed", "同一份字节的 PERMANENT 失败不再每晚重转"


def test_transient_failure_is_retried_next_time(monkeypatch, tmp_path):
    payload = text_pdf(tmp_path / "src.pdf", [CLEAN_LINES]).read_bytes()
    source, source_id, doc_id = _object_with(tmp_path / "v", monkeypatch, "教程.pdf", payload)
    real = pdftext.attachment_to_markdown
    monkeypatch.setattr(pdftext, "attachment_to_markdown", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("一时出错")))
    first = pdftext.convert_object_attachments(source, source_id)
    assert first[0]["status"] == "failed" and first[0]["code"].startswith("TRANSIENT.")
    monkeypatch.setattr(pdftext, "attachment_to_markdown", real)
    again = pdftext.convert_object_attachments(source, source_id)
    assert again[0]["status"] == "ok", "TRANSIENT 失败下次照转"
    assert not [r for r in problems.load() if r["step"] == "attachments.convert"], "转成了就标已解决"


def test_skipped_conversion_is_not_marked_failed(monkeypatch, tmp_path):
    payload = image_pdf(tmp_path / "src.pdf", ["SCAN"]).read_bytes()
    source, source_id, doc_id = _object_with(tmp_path / "v", monkeypatch, "扫描.pdf", payload)
    monkeypatch.setattr(visual, "available", lambda: False)
    out = pdftext.convert_object_attachments(source, source_id)
    assert out[0]["status"] == "skipped"
    assert "conversion_failed" not in att_mod.load_downloaded(source, source_id)[doc_id]
    assert att_mod.convert_downloads(source, source_id) == [], "没开不算转换失败"
    rows = [r for r in problems.load() if r["step"] == "attachments.convert"]
    assert rows and rows[0]["code"] == "SKIPPED.NOT_CONFIGURED" and rows[0]["action"] == "skipped"


@pytest.mark.parametrize("suffix", [".pdf", ".docx"])
def test_no_private_paths_needed(suffix, tmp_path):
    """随包自带：不需要任何仓库外脚本或环境变量就能转。"""
    import os
    assert not any(k.startswith("LINK_BRAIN_MEDIA") for k in os.environ)
    path = text_pdf(tmp_path / "a.pdf", [CLEAN_LINES]) if suffix == ".pdf" else docx(tmp_path / "a.docx")
    assert docconv.to_markdown(path)["status"] == "ok"
