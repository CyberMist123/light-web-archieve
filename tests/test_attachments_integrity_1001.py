"""1001 审计「数据正确性」附件一批：raw-1 / attach-3 / attach-4 / attach-5。

入口走生产真跑的那条（download_for_object / recheck / cli attachments --attach / --dedupe），
只把网络那一侧（读取服务下载、网页探测）换成假的。
"""

from __future__ import annotations

import json

import pytest

from link_brain import attachments as att_mod, cli, index as index_mod, pdftext, render as render_mod, storage
from link_brain.adapters import xiaohongshu as xhs

from test_attachments import DOC_ID, RELATED_FILE, _ids, fake_fetch, real_pdf, setup_env


def _raw_snapshot(source, source_id):
    raw = storage.raw_dir(source, source_id, 1)
    return {p.name: p.read_bytes() for p in raw.iterdir() if p.is_file()}


def _probe_fails(monkeypatch):
    monkeypatch.setattr(
        xhs, "fetch_related_file",
        lambda note_id, xsec_token, **kw: {"ok": False, "related_file": None, "url": "u", "error": "连不上"},
    )


def encrypted_pdf() -> bytes:
    from _samples import encrypted_pdf_bytes
    return encrypted_pdf_bytes()  # AES-256，有打开密码（tests/fixtures/encrypted.pdf）


# --------------------------------------------------------------------------
# raw-1：解析出的编号不再回写封存的 source.json
# --------------------------------------------------------------------------


def test_resolved_hint_goes_to_object_file_not_sealed_raw(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    _probe_fails(monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    before = _raw_snapshot(source, source_id)

    probes = []

    def logged(note_id, token):
        probes.append(note_id)
        return {"ok": True, "related_file": RELATED_FILE, "error": None}

    monkeypatch.setattr(att_mod, "_probe_logged_in", logged)
    monkeypatch.setattr(att_mod, "local_download", lambda name: None)
    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch())
    out = att_mod.download_for_object(source, source_id)

    assert [r["status"] for r in out["results"]] == ["downloaded"]
    assert _raw_snapshot(source, source_id) == before, "封存的 raw 一个字节都不许动"
    obj = storage.object_dir(source, source_id)
    resolved = storage.read_json(obj / att_mod.RESOLVED_NAME)["resolved"]
    assert resolved[0]["doc_id"] == DOC_ID and resolved[0]["hint"]
    report = att_mod.inventory(obj)
    assert report["total"] == 1 and report["missing"] == 0 and report["files"][0]["doc_id"] == DOC_ID

    # 第二晚：声明合并后已有编号 → 不再去笔记页找
    att_mod.download_for_object(source, source_id)
    assert len(probes) == 1


def test_recheck_found_file_is_declared_so_all_picks_it_up(tmp_path, monkeypatch):
    """审计 attach-4 ③：recheck 探到的附件下坏了，--all 也得遍历到它接着下。"""
    setup_env(tmp_path, monkeypatch)
    _probe_fails(monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _ids()
    before = _raw_snapshot(source, source_id)
    monkeypatch.setattr(
        xhs, "fetch_related_file",
        lambda note_id, xsec_token, **kw: {"ok": True, "related_file": RELATED_FILE, "url": "u", "error": None},
    )

    def broken_download(**kw):
        raise att_mod.AttachmentError("下到一半断了")

    monkeypatch.setattr(att_mod, "fetch_bytes", broken_download)
    out = att_mod.recheck()
    assert out["failed"] and _raw_snapshot(source, source_id) == before

    conn = index_mod.connect()
    try:
        status = index_mod.get_object(conn, item_id)["attachments_status"]
    finally:
        conn.close()
    assert status == "metadata_only"  # attachments --all 按这个挑对象

    seen = []
    monkeypatch.setattr(att_mod, "resolve_hint", lambda *a: pytest.fail("编号已知，不该再去找"))
    monkeypatch.setattr(att_mod, "local_download", lambda name: None)
    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch(calls=seen))
    res = att_mod.download_for_object(source, source_id)
    assert seen == [DOC_ID] and [r["status"] for r in res["results"]] == ["downloaded"]


# --------------------------------------------------------------------------
# attach-5：手动再挂一个文件不顶掉已有附件
# --------------------------------------------------------------------------


def test_second_manual_attach_adds_record_instead_of_replacing(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _ids()
    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch())
    att_mod.download_for_object(source, source_id)
    obj = storage.object_dir(source, source_id)
    first_md = obj / "derived" / "attachments" / f"{DOC_ID}.md"
    md_before = first_md.read_bytes()

    extra = tmp_path / "评论区截图.pdf"
    extra.write_bytes(real_pdf())
    code = cli.main(["attachments", item_id, "--attach", str(extra)])  # 目录页拖放走的就是这条（不带 doc_id）
    assert code in (0, 2)

    known = att_mod.load_downloaded(source, source_id)
    assert set(known) == {DOC_ID, "manual-评论区截图"}
    assert known[DOC_ID]["file"] == "教程.pdf" and (obj / "attachments" / "教程.pdf").is_file()
    assert first_md.read_bytes() == md_before, "原附件的 md 不能被新文件覆盖"
    assert att_mod.inventory(obj)["total"] == 2


def test_lone_declared_claim_needs_no_record_and_matching_extension(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()

    other = tmp_path / "别的.docx"
    other.write_bytes(b"PK\x03\x04docx")
    att_mod.manual_attach(source, source_id, str(other))
    assert set(att_mod.load_downloaded(source, source_id)) == {"manual-别的"}, "扩展名对不上不认领"

    renamed = tmp_path / "下载的教程 (1).pdf"
    renamed.write_bytes(real_pdf())
    att_mod.manual_attach(source, source_id, str(renamed))
    assert DOC_ID in att_mod.load_downloaded(source, source_id), "还没下载记录 + 扩展名对得上 → 认领"

    again = tmp_path / "又一份.pdf"
    again.write_bytes(real_pdf())
    att_mod.manual_attach(source, source_id, str(again))
    known = att_mod.load_downloaded(source, source_id)
    assert known[DOC_ID]["file"] == "下载的教程 (1).pdf" and "manual-又一份" in known


def test_hint_only_note_still_claims_manual_file(tmp_path, monkeypatch):
    """只有正文线索的笔记（审计 health/attach-1 那条）：手动挂的文件照旧认成那条线索。"""
    setup_env(tmp_path, monkeypatch)
    _probe_fails(monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    f = tmp_path / "prompt.docx"
    f.write_bytes(b"PK\x03\x04docx")
    att_mod.manual_attach(source, source_id, str(f))
    report = att_mod.inventory(storage.object_dir(source, source_id))
    assert report["total"] == 1 and report["missing"] == 0


def test_same_name_different_file_does_not_overwrite_bytes(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch())
    att_mod.download_for_object(source, source_id)
    obj = storage.object_dir(source, source_id)
    original = (obj / "attachments" / "教程.pdf").read_bytes()

    elsewhere = tmp_path / "x"
    elsewhere.mkdir()
    clash = elsewhere / "教程.pdf"
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "a different file with the same name")
    clash.write_bytes(doc.tobytes())
    att_mod.manual_attach(source, source_id, str(clash), "manual-另一份")
    assert (obj / "attachments" / "教程.pdf").read_bytes() == original
    known = att_mod.load_downloaded(source, source_id)
    assert known["manual-另一份"]["file"] == "教程 (2).pdf" and known[DOC_ID]["file"] == "教程.pdf"


# --------------------------------------------------------------------------
# attach-3：manual-… 认回真编号时并成一条；--dedupe 修存量
# --------------------------------------------------------------------------


def test_reclaimed_manual_record_merges_into_real_doc_id(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    local = tmp_path / "教程.pdf"
    local.write_bytes(real_pdf())
    att_mod.manual_attach(source, source_id, str(local), "manual-教程")
    md_dir = storage.derived_dir(source, source_id) / "attachments"
    md_dir.mkdir(parents=True, exist_ok=True)
    (md_dir / "manual-教程.md").write_text("# 已转好的", encoding="utf-8")

    monkeypatch.setattr(att_mod, "fetch_bytes", lambda **kw: pytest.fail("库里已有同名文件，不该上网"))
    att_mod.download_for_object(source, source_id)

    known = att_mod.load_downloaded(source, source_id)
    assert list(known) == [DOC_ID], "只留真 doc_id 一条"
    assert known[DOC_ID]["manual_ids"] == ["manual-教程"] and known[DOC_ID]["source"] == "manual"
    assert sorted(p.name for p in md_dir.glob("*.md")) == [f"{DOC_ID}.md"], "md 沿用、不留两份"
    render_mod.render_object(source, source_id)
    agent = (storage.derived_dir(source, source_id) / "agent.md").read_text(encoding="utf-8")
    assert "manual-教程" not in agent
    assert att_mod.inventory(storage.object_dir(source, source_id))["total"] == 1


def _plant_duplicate(source, source_id):
    """复现 9-30 那次的存量：同一个文件记了 manual-… 和真编号两条、md 两份。"""
    obj = storage.object_dir(source, source_id)
    (obj / "attachments").mkdir(parents=True, exist_ok=True)
    (obj / "attachments" / "教程.pdf").write_bytes(real_pdf())
    sha = att_mod._sha256(obj / "attachments" / "教程.pdf")
    rec = {"name": "教程.pdf", "file": "教程.pdf", "bytes": 1, "sha256": sha, "downloaded_at": "2026-09-30T04:04:00+10:00"}
    storage.write_json(att_mod.attachments_path(source, source_id), {"schema_version": 1, "files": [
        {**rec, "doc_id": "manual-教程", "source": "manual"}, {**rec, "doc_id": DOC_ID, "source": "manual"}]})
    md_dir = obj / "derived" / "attachments"
    md_dir.mkdir(parents=True, exist_ok=True)
    for d in ("manual-教程", DOC_ID):
        (md_dir / f"{d}.md").write_text("# 同一份", encoding="utf-8")
    return obj


def test_dedupe_dry_run_reports_without_writing(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    obj = _plant_duplicate(source, source_id)
    capsys.readouterr()
    snap = {p: p.read_bytes() for p in obj.rglob("*") if p.is_file()}

    assert cli.main(["attachments", "--dedupe", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] and len(out["merge"]) == 1
    plan = out["merge"][0]
    assert plan["keep"] == DOC_ID and plan["drop"] == ["manual-教程"] and plan["same_sha256"]
    assert {p: p.read_bytes() for p in obj.rglob("*") if p.is_file()} == snap, "dry-run 一个字节都不许写"


def test_dedupe_merges_existing_duplicates(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    obj = _plant_duplicate(source, source_id)
    capsys.readouterr()

    assert cli.main(["attachments", "--dedupe"]) == 0
    known = att_mod.load_downloaded(source, source_id)
    assert list(known) == [DOC_ID] and known[DOC_ID]["manual_ids"] == ["manual-教程"]
    assert sorted(p.name for p in (obj / "derived" / "attachments").glob("*.md")) == [f"{DOC_ID}.md"]
    assert att_mod.inventory(obj)["total"] == 1
    capsys.readouterr()
    assert cli.main(["attachments", "--dedupe", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["merge"] == [], "修完再跑是空的"


# --------------------------------------------------------------------------
# attach-4：转 md 失败不删字节、不重下；坏 PDF 不让整晚停下
# --------------------------------------------------------------------------


def test_unconvertible_download_is_kept_and_not_refetched(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    _, source, source_id = _ids()
    calls = []
    monkeypatch.setattr(att_mod, "fetch_bytes", fake_fetch(encrypted_pdf(), calls=calls))
    out = att_mod.download_for_object(source, source_id)

    assert [r["status"] for r in out["results"]] == ["downloaded"] and calls == [DOC_ID], "下一次就够，不删了重下"
    obj = storage.object_dir(source, source_id)
    assert (obj / "attachments" / "教程.pdf").is_file()
    rec = att_mod.load_downloaded(source, source_id)[DOC_ID]
    assert "密码" in rec["conversion_failed"]["note"]

    # 之后每晚：不再开附件页，也不再每晚转一遍、报一遍错
    converted = []
    real_convert = pdftext.attachment_to_markdown
    monkeypatch.setattr(pdftext, "attachment_to_markdown", lambda *a, **k: converted.append(1) or real_convert(*a, **k))
    again = att_mod.download_for_object(source, source_id)
    assert [r["status"] for r in again["results"]] == ["already"] and calls == [DOC_ID]
    assert att_mod.convert_downloads(source, source_id) == [] and converted == []


def test_encrypted_pdf_fails_cleanly_with_password_note(tmp_path):
    pdf = tmp_path / "locked.pdf"
    pdf.write_bytes(encrypted_pdf())
    outcome = pdftext.pdf_to_markdown(pdf, force_ocr=True)
    assert outcome["status"] == "failed" and "密码" in outcome["note"]
    assert outcome["code"] == "PERMANENT.PDF_ENCRYPTED"
    outcome = pdftext.pdf_to_markdown(pdf)
    assert outcome["status"] == "failed" and outcome["code"] == "PERMANENT.PDF_ENCRYPTED"


def test_one_page_crash_only_blanks_that_page(tmp_path, monkeypatch):
    from _samples import blank_pdf
    from link_brain import vision as vision_mod, visual
    pdf = blank_pdf(tmp_path / "scan.pdf", pages=2)
    calls = []

    def ocr(path, cfg=None, timeout=0):
        calls.append(path)
        if len(calls) == 2:
            raise RuntimeError("这一页渲坏了")
        return {"status": "ok", "ocr": "page text"}

    monkeypatch.setattr(vision_mod, "run_ocr", ocr)
    monkeypatch.setattr(visual, "available", lambda: True)
    outcome = pdftext.pdf_to_markdown(pdf)
    text, note = outcome["markdown"], outcome["note"]
    assert outcome["status"] == "ok" and outcome["partial"] == 1
    assert text and "page text" in text and "第 2 页" in text and "这一页没识别出来" in text
    assert "1 页失败" in note


def test_convert_downloads_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ValueError("document closed or encrypted")

    monkeypatch.setattr(pdftext, "convert_object_attachments", boom)
    errors = att_mod.convert_downloads("xiaohongshu", "whatever")
    assert errors and "encrypted" in errors[0]
