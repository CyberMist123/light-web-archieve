import json
import tempfile
from zipfile import ZipFile

import pytest
from link_brain import export_bundle as bundle


@pytest.fixture
def entry(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    obj = tmp_path / "_archive/example/sample"
    raw = obj / "raw/v0001"
    (raw / "assets").mkdir(parents=True)
    (obj / "derived").mkdir()
    (raw / "assets/a.png").write_bytes(b"sample image")
    (obj / "derived/agent.md").write_text("# Sample\nBody", encoding="utf-8")
    (obj / "meta.json").write_text(json.dumps({"current_version": 1, "item_id": "sample",
        "source": "example", "source_id": "sample", "title": "Sample"}), encoding="utf-8")
    (raw / "source.json").write_text(json.dumps({"note": {"title": "Sample"}}), encoding="utf-8")
    (raw / "manifest.json").write_text(json.dumps({"media": [
        {"role": "note_image", "file": "assets/a.png"}]}), encoding="utf-8")
    (tmp_path / "_archive/catalog-data.json").write_text(json.dumps({"items": [{
        "id": "sample", "title": "Sample", "source": "example", "note": "Web/sample.md",
        "agent_md": "_archive/example/sample/derived/agent.md"}]}), encoding="utf-8")
    return obj


def test_safe_name_replaces_forbidden_and_trims():
    assert bundle._safe_name(' .a/b:c? .') == "a_b_c_"
    assert bundle._safe_name(None) == "未命名"
    assert bundle._safe_name("abcdef", 3) == "abc"
    assert bundle._safe_name("ab .cd", 4) == "ab"


def test_size_kilobytes_and_megabyte_boundary():
    assert bundle._fmt_size(0) == "1 KB"
    assert bundle._fmt_size(2048) == "2 KB"
    assert bundle._fmt_size(1024 * 1024 - 1) == "1023 KB"
    assert bundle._fmt_size(1024 * 1024) == "1 MB"


def test_object_media_paths_filter_and_missing(entry):
    raw = entry / "raw/v0001"
    media = [{"role": "note_image", "file": "raw/v0001/assets/a.png"},
             {"role": "note_image", "file": "assets/a.png"},
             {"role": "video", "file": "assets/a.png"},
             {"role": "note_image", "file": "assets/missing.png"},
             {"role": "note_image"}]
    (raw / "manifest.json").write_text(json.dumps({"media": media}), encoding="utf-8")
    rows = list(bundle._object_media(entry, {"current_version": "1"}, {"note_image"}))
    assert [r[2] for r in rows] == [media[i] for i in (0, 1, 3, 4)]
    assert [r[1] for r in rows] == [raw / "assets/a.png", raw / "assets/a.png", None, None]


def test_export_bundle_real_entry(entry):
    result = bundle.export_bundle(["sample", "sample", "absent"])
    assert result["notes"] == result["images"] == 1
    assert result["missing"] == []
    with ZipFile(result["path"]) as archive:
        assert archive.read("images/01-0001.png") == b"sample image"
        assert "Body" in archive.read("Sample_未知作者_example.md").decode("utf-8")


def test_export_note_zip_real_entry_without_pdf(entry):
    result = bundle.export_note_zip("sample", include_pdf=False)
    assert result["ok"]
    assert result["counts"]["images"] == 1
    assert result["missing"] == []
    with ZipFile(result["path"]) as archive:
        assert archive.read("Sample/images/01.png") == b"sample image"
        assert "Body" in archive.read("Sample/正文与识图.md").decode("utf-8")
        assert not any(name.endswith(".pdf") for name in archive.namelist())
