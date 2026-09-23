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
