"""第 2 批（CONVENTIONS §5）Python 一侧：

- catalog.build 把共享前导 lb-page-lib.js 内联进三张页，并拼在 _archive/annotate-view.js 最前面；
- catalog-data 带封面宽高（目录页先占位，返回时滚动一次到位）；
- 点星标时就地改 catalog-data 的 starred（目录页以它为准，不再每次读几百份 notes.json）；正在重建拿不到锁就跳过。
"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import catalog, note, storage

ASSETS = Path(catalog.__file__).parent / "assets"


def _obj(vault: Path, sid: str, title: str, *, width=600, height=800) -> None:
    obj = vault / "_archive" / "xiaohongshu" / sid
    (obj / "raw" / "v0001" / "assets").mkdir(parents=True, exist_ok=True)
    (obj / "raw" / "v0001" / "assets" / "image-001.png").write_bytes(b"x")
    visible = f"Web/Xiaohongshu/{title}.md"
    (obj / "meta.json").write_text(json.dumps({"item_id": f"xhs-{sid}", "title": title, "visible_note": visible,
                                               "first_archived_at": "2026-09-10T12:00:00+10:00", "current_version": 1,
                                               "source": "xiaohongshu", "source_id": sid}, ensure_ascii=False), encoding="utf-8")
    media = {"role": "note_image", "index": 1, "file": "raw/v0001/assets/image-001.png", "mime": "image/png", "download_status": "ok"}
    if width:
        media.update(width=width, height=height)
    (obj / "raw" / "v0001" / "manifest.json").write_text(json.dumps({"media": [media]}), encoding="utf-8")
    (vault / visible).parent.mkdir(parents=True, exist_ok=True)
    (vault / visible).write_text("---\ntags: [x]\n---\n正文\n", encoding="utf-8")


def test_build_inlines_page_lib_everywhere(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _obj(tmp_path, "a1", "一篇")
    catalog_path, _, _ = catalog.build()
    lib = (ASSETS / "lb-page-lib.js").read_text(encoding="utf-8")
    pages = catalog.library_pages(tmp_path)
    for role in ("catalog", "chat", "starred"):
        text = (tmp_path / pages[role]).read_text(encoding="utf-8")
        assert text.count("function lbPageLib(") == 1, role
        assert text.index("function lbPageLib(") < text.rindex("const LB = lbPageLib("), role
    assert "const starredPage = true;" in (tmp_path / pages["starred"]).read_text(encoding="utf-8")
    annot = (tmp_path / "_archive" / "annotate-view.js").read_text(encoding="utf-8")
    assert annot.startswith(lib)
    assert "lbPageLib(dv, app, 'annotate')" in annot
    assert "```" not in lib, "前导里不能有三个反引号（会截断 dataviewjs 代码块）"


def test_cover_size_from_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _obj(tmp_path, "a1", "有宽高")
    _obj(tmp_path, "b2", "没宽高", width=None)
    _, _, data_path = catalog.build()
    items = {it["id"]: it for it in json.loads(data_path.read_text(encoding="utf-8"))["items"]}
    assert (items["xhs-a1"]["cover_w"], items["xhs-a1"]["cover_h"]) == (600, 800)
    assert items["xhs-b2"]["cover"].endswith("image-001.png")
    assert items["xhs-b2"]["cover_w"] is None and items["xhs-b2"]["cover_h"] is None


def test_star_patches_catalog_data(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _obj(tmp_path, "a1", "一篇")
    _obj(tmp_path, "b2", "另一篇")
    _, _, data_path = catalog.build()
    monkeypatch.setattr(note, "_resolve", lambda target: {"item_id": "xhs-a1", "source": "xiaohongshu", "source_id": "a1"})
    out = note.set_star("xhs-a1", True)
    assert out["status"] == "ok" and out["starred"] is True
    items = {it["id"]: it for it in json.loads(data_path.read_text(encoding="utf-8"))["items"]}
    assert items["xhs-a1"]["starred"] is True and items["xhs-a1"]["starred_at"] == out["starred_at"]
    assert items["xhs-b2"]["starred"] is False
    note.set_star("xhs-a1", False)
    items = {it["id"]: it for it in json.loads(data_path.read_text(encoding="utf-8"))["items"]}
    assert items["xhs-a1"]["starred"] is False and items["xhs-a1"]["starred_at"] is None


def test_patch_skips_when_build_holds_lock(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _obj(tmp_path, "a1", "一篇")
    _, _, data_path = catalog.build()
    before = data_path.read_text(encoding="utf-8")
    def busy(*a, **k):  # 目录正在重建（锁被别的进程拿着）
        raise storage.LockBusy("catalog-build", {"owner": "catalog.build"})

    monkeypatch.setattr(storage, "file_lock", busy)
    assert catalog.patch_items({"xhs-a1": {"starred": True}}) == 0
    assert data_path.read_text(encoding="utf-8") == before
    # 只认星标两个字段，别的键不改
    monkeypatch.undo()
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    assert catalog.patch_items({"xhs-a1": {"title": "被改了", "starred": True}}) == 1
    it = json.loads(data_path.read_text(encoding="utf-8"))["items"][0]
    assert it["title"] == "一篇" and it["starred"] is True
    # 文件不在：0，不抛
    data_path.unlink()
    assert catalog.patch_items({"xhs-a1": {"starred": False}}) == 0
