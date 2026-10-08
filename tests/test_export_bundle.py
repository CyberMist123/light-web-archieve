import json
from zipfile import ZipFile
from link_brain.export_bundle import export_bundle
from link_brain.ask import locate_excerpts


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path))
    obj = tmp_path / "_archive/xiaohongshu/example"
    (obj / "derived").mkdir(parents=True)
    raw = obj / "raw/v0001"
    (raw / "assets").mkdir(parents=True)
    (raw / "assets/a.webp").write_bytes(b"original image bytes")
    (obj / "derived/agent.md").write_text("# 原文\n测试正文", encoding="utf-8")
    (obj / "meta.json").write_text(json.dumps({"current_version": 1}))
    (raw / "manifest.json").write_text(json.dumps({"media": [
        {"role": "note_image", "file": "raw/v0001/assets/a.webp"},
        {"role": "note_image", "file": "raw/v0001/assets/missing.webp"},
    ]}))
    item = {"id": "example", "title": "测试资料", "agent_md": "_archive/xiaohongshu/example/derived/agent.md", "note": "Web/a.md", "url": "https://example.org/note"}
    (tmp_path / "_archive/catalog-data.json").write_text(json.dumps({"items": [item]}))
    return item, obj


def test_portable_images_and_text_only(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    result = export_bundle(["example"], True, "答案及证据")
    assert result["images"] == 1 and len(result["missing"]) == 1
    with ZipFile(result["path"]) as archive:
        assert archive.read("images/01-0001.webp") == b"original image bytes"
        assert "images/01-0001.webp" in archive.read("测试资料_未知作者_小红书.md").decode()
        assert "未能打包" in archive.read("索引.md").decode()
        assert archive.read("回答与摘录.md").decode() == "答案及证据"
    result = export_bundle(["example"], False)
    with ZipFile(result["path"]) as archive:
        assert not any(name.startswith("images/") for name in archive.namelist())


def test_ocr_maps_only_verbatim_evidence(tmp_path, monkeypatch):
    item, obj = fixture(tmp_path, monkeypatch)
    text = "Dream context performs memory consolidation during idle periods."
    (obj / "derived/vision.json").write_text(json.dumps({"images": [
        {"asset": "raw/v0001/assets/a.webp", "ocr": text},
        {"asset": "raw/v0001/assets/b.webp", "ocr": "Unrelated dream photo"},
    ]}))
    located = locate_excerpts(item, [{"field": "ocr", "text": text[10:]}])
    assert located[0]["assets"] == ["raw/v0001/assets/a.webp"]
    assert "assets" not in locate_excerpts(item, [{"field": "ocr", "text": "dream"}])[0]


def test_question_naming_repeat_and_zero_source_answer(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    first = export_bundle(["example"], False, "本轮回答", "做梦机制", "2026-09-23T02:00:00+10:00")
    second = export_bundle(["example"], False, "本轮回答", "做梦机制", "2026-09-23T02:00:00+10:00")
    assert "做梦机制_1篇_" in first["path"]
    assert first["path"] != second["path"] and "（2）" in second["path"]
    empty = export_bundle([], False, "没有相关资料", "无结果", "unknown")
    assert "无结果_0篇_提问时间未记录" in empty["path"]


# ── 批次 D · F3-c：单篇压缩包 export_note_zip ──
import pytest  # noqa: E402
from zipfile import ZIP_STORED  # noqa: E402

from link_brain import note as note_mod, note_print, storage  # noqa: E402
from link_brain.export_bundle import export_note_zip  # noqa: E402
from tests._l5_objects import add_media  # noqa: E402
from tests.test_restore_1009 import obj  # noqa: E402,F401


@pytest.fixture
def full(obj, monkeypatch):
    monkeypatch.setattr(note_print, "find_browser", lambda: None)
    files = add_media(obj, images=2, video=True, comment_image=True)
    (obj["dir"] / "attachments").mkdir(exist_ok=True)
    (obj["dir"] / "attachments" / "速查表.pdf").write_bytes(b"%PDF-1.4 x")
    (obj["dir"] / "derived" / "attachments").mkdir(parents=True, exist_ok=True)
    (obj["dir"] / "derived" / "attachments" / "速查表.md").write_text("全文\n```dataviewjs\nx\n```\n", encoding="utf-8")
    (obj["dir"] / "derived" / "agent.md").write_text("# 正文\n```dataviewjs\nboom()\n```\n", encoding="utf-8")
    note_mod.save_notes(obj["source"], obj["source_id"], {"starred": True, "annotations": [
        {"id": "a1", "text": "活着的批注", "ts": "2026-10-01T10:00:00"},
        {"id": "a2", "text": "墓碑批注", "ts": "2026-10-02T10:00:00"},
        {"id": "a3", "text": "  ", "ts": "2026-10-03T10:00:00"}], "deleted": ["a2"]})
    return obj, files


def _names(z):
    return z.namelist()


def test_note_zip_full(full):
    obj, files = full
    out = export_note_zip(obj["item_id"])
    assert out["ok"] and out["counts"]["images"] == 3 and out["counts"]["video"] == 1
    with ZipFile(out["path"]) as z:
        names = _names(z)
        top = names[0].split("/")[0]
        assert all(n.startswith(top + "/") for n in names)
        assert z.read(f"{top}/images/01.png") == files["image-001.png"]
        assert any(n.startswith(f"{top}/comments/c1-") for n in names)
        info = z.getinfo(f"{top}/video/video.mp4")
        assert info.compress_type == ZIP_STORED
        assert f"{top}/attachments/速查表.pdf" in names and f"{top}/attachments/速查表.md" in names
        ann = z.read(f"{top}/批注.md").decode()
        assert "活着的批注" in ann and "墓碑批注" not in ann
        assert "```dataviewjs" not in z.read(f"{top}/正文与识图.md").decode()
        idx = z.read(f"{top}/索引.md").decode()
        assert "笔记页.pdf 没生成" in idx
        assert f"{top}/笔记页.pdf" not in names
        assert not any(n.endswith(("source.json", "manifest.json")) for n in names)


def test_note_zip_missing_listed(full):
    obj, _ = full
    raw = obj["dir"] / "raw" / "v0001"
    (raw / "assets" / "image-002.png").unlink()
    out = export_note_zip(obj["item_id"])
    with ZipFile(out["path"]) as z:
        top = z.namelist()[0].split("/")[0]
        assert "## 缺什么" in z.read(f"{top}/索引.md").decode()
    assert out["missing"]


def test_note_zip_no_video_and_suffix(full):
    obj, _ = full
    a = export_note_zip(obj["item_id"], include_video=False, include_pdf=False)
    with ZipFile(a["path"]) as z:
        assert not any("/video/" in n for n in z.namelist())
        top = z.namelist()[0].split("/")[0]
        assert "这次没放笔记页.pdf" in z.read(f"{top}/索引.md").decode()
    import link_brain.export_bundle as eb

    class Frozen(eb.datetime):
        @classmethod
        def now(cls, tz=None):
            return eb.datetime(2026, 10, 9, 1, 2, 3)
    import pytest as _p
    mp = _p.MonkeyPatch()
    try:
        mp.setattr(eb, "datetime", Frozen)
        b = export_note_zip(obj["item_id"], include_pdf=False)
        c = export_note_zip(obj["item_id"], include_pdf=False)
    finally:
        mp.undo()
    assert "（2）" in c["path"] and b["path"] != c["path"]
    assert not any(p.name.endswith(".part") for p in (storage.vault_root() / "收藏导出").iterdir())
