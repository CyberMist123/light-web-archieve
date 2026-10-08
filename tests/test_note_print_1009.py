"""批次 D · F3-b：单篇导出 PDF（打印 HTML / 找浏览器 / 降级网页版 / 超时杀树）。只写 tmp 库；真浏览器用例只开本地 HTML、独立临时 profile。"""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from link_brain import cli, note as note_mod, note_print, render as render_mod, storage
from tests._l5_objects import add_media
from tests.test_restore_1009 import obj  # noqa: F401


@pytest.fixture
def no_browser(monkeypatch):
    monkeypatch.setattr(note_print, "find_browser", lambda: None)


def test_print_html_images_and_cleanup(obj, no_browser):
    add_media(obj, images=3)
    doc, info = note_print.print_html(obj["item_id"])
    assert doc.count("<img ") == 3 == info["images"]
    assert 'loading="lazy"' not in doc
    assert "<audio" not in doc and "<script" not in doc
    assert "IP 属地" not in doc
    assert f'<base href="{storage.visible_dir().as_uri()}/">' in doc
    assert '<div class="lb-note"><div class="lb-side">' in doc
    for d in re.findall(r"<details\b[^>]*>", doc):
        assert " open" in d


def test_print_html_video_becomes_cover(obj, no_browser):
    add_media(obj, images=1, video=True)
    doc, info = note_print.print_html(obj["item_id"])
    assert info["has_video"]
    assert "<video" not in doc
    assert 'class="lb-slide lb-print-video"' in doc and "1:02" in doc and "原视频在压缩包里" in doc


def test_print_html_no_media_single_column(obj, no_browser):
    doc, _ = note_print.print_html(obj["item_id"])
    body = doc[doc.find("<body>"):]
    assert "lb-note lb-no-media" in body and "lb-side" not in body


def test_print_html_marks_and_live_annotations(obj, no_browser):
    add_media(obj, images=1)
    t = obj["vis"].read_text(encoding="utf-8")
    body = storage.read_json(obj["dir"] / "raw" / "v0001" / "source.json")["note"]["body"]
    phrase = re.search(r"[一-鿿]{4}", body).group(0)
    region_s = t.find(render_mod.CONTENT_START)
    at = t.find(phrase, region_s)
    assert at > 0
    obj["vis"].write_text(t[:at] + f"<mark>{phrase}</mark>" + t[at + len(phrase):], encoding="utf-8")
    note_mod.save_notes(obj["source"], obj["source_id"], {"annotations": [
        {"id": "a1", "text": "留着的批注", "ts": "2026-10-01T10:00:00"},
        {"id": "a2", "text": "删掉的批注", "ts": "2026-10-02T10:00:00"},
    ], "deleted": ["a2"]})
    doc, _ = note_print.print_html(obj["item_id"])
    assert f"<mark>{phrase}</mark>" in doc
    side = doc[doc.find('<div class="lb-side">'):doc.find('<div class="lb-main">')]
    assert "留着的批注" in side and side.find("<img") < side.find("留着的批注")
    assert "删掉的批注" not in doc


def test_find_browser_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "msedge.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv(note_print.ENV_BROWSER, str(exe))
    assert note_print.find_browser() == str(exe)
    monkeypatch.setenv(note_print.ENV_BROWSER, str(tmp_path / "nope.exe"))
    assert note_print.find_browser() is None


def test_find_browser_none(tmp_path, monkeypatch):
    monkeypatch.delenv(note_print.ENV_BROWSER, raising=False)
    for k in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
        monkeypatch.setenv(k, str(tmp_path))
    monkeypatch.setattr(note_print.shutil, "which", lambda name: None)
    import sys
    if sys.platform == "win32":
        import winreg

        def no_key(*a, **k):
            raise OSError("no")
        monkeypatch.setattr(winreg, "OpenKey", no_key)
    assert note_print.find_browser() is None


def test_no_browser_falls_back_to_html(obj, no_browser, capsys):
    add_media(obj, images=1)
    code = cli.main(["export-note", obj["item_id"], "--pdf", "--json"])
    cap = capsys.readouterr()
    data = json.loads(cap.out.strip().splitlines()[-1])
    assert code == 0 and data["ok"] is True and data["fallback"] == "html"
    out = storage.vault_root() / "收藏导出"
    assert [p.suffix for p in out.iterdir()] == [".html"]
    assert "[export] 排版" in cap.err


def test_print_timeout_kills_own_tree(obj, monkeypatch, tmp_path):
    add_media(obj, images=1)
    exe = tmp_path / "msedge.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(note_print, "find_browser", lambda: str(exe))
    killed = []

    class Stuck:
        pid = 4242

        def __init__(self, args, **kw):
            assert any(a.startswith("--user-data-dir=") for a in args)
            assert args[-1].startswith("file:")
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            raise subprocess.TimeoutExpired("x", timeout)
    monkeypatch.setattr(note_print.subprocess, "Popen", Stuck)
    monkeypatch.setattr(note_print.procs, "kill_tree", lambda pid, **k: killed.append(pid))
    out = note_print.export_pdf(obj["item_id"])
    assert killed == [4242]
    assert out["ok"] is False and out["code"] == "TRANSIENT.STEP_TIMEOUT" and out["fallback"] == "html"
    names = [p.name for p in (storage.vault_root() / "收藏导出").iterdir()]
    assert not any(n.endswith((".pdf", ".part")) for n in names)


def test_same_name_twice_gets_suffix(obj, no_browser):
    a = note_print.export_pdf(obj["item_id"])
    b = note_print.export_pdf(obj["item_id"])
    assert a["path"] != b["path"] and "（2）" in b["path"]


@pytest.mark.skipif(note_print.find_browser() is None, reason="这台机器没有 Edge / Chrome")
def test_e2e_real_pdf(obj):
    """真出 PDF：独立临时 user-data-dir、只开本地 file:// HTML。"""
    add_media(obj, images=2)
    out = note_print.export_pdf(obj["item_id"])
    assert out["ok"], out
    assert out["path"].endswith(".pdf") and out["pages"] >= 1
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(out["path"])
    try:
        text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    finally:
        doc.close()
    title = storage.read_json(obj["dir"] / "meta.json")["title"]
    assert title in text.replace("\r", "").replace("\n", "")
