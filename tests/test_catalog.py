"""目录页（封面瀑布流版）：纯程序拼数据，不联网。

验：build() 出 catalog-data.json（封面取 manifest 第一张图、tag 读可见笔记 frontmatter、
概要读 extracted.json），md 页面带 dataviewjs 块。全部走 tmp vault（LINK_BRAIN_VAULT）。
"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import catalog, storage


def _make_object(vault: Path, source_id: str, *, title: str, tags: list[str], summary: str,
                 stem: str, kind: str = "image") -> None:
    obj = vault / "_archive" / "xiaohongshu" / source_id
    raw = obj / "raw" / "v0001" / "assets"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "image-001.webp").write_bytes(b"fake")
    visible = f"Web/Xiaohongshu/{stem}.md"
    (obj / "meta.json").write_text(json.dumps({
        "item_id": f"xhs-{source_id}",
        "title": title,
        "visible_note": visible,
        "first_archived_at": "2026-09-10T12:00:00+10:00",
        "current_version": 1,
        "attachments_status": "none",
        "kind": kind,
    }, ensure_ascii=False), encoding="utf-8")
    (obj / "raw" / "v0001" / "manifest.json").write_text(json.dumps({
        "media": [{
            "role": "note_image", "index": 1, "file": "raw/v0001/assets/image-001.webp",
            "mime": "image/webp", "download_status": "ok",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    (obj / "derived").mkdir(parents=True, exist_ok=True)
    (obj / "derived" / "extracted.json").write_text(json.dumps({
        "data": {"summary": summary, "tags": ["兜底tag"]},
    }, ensure_ascii=False), encoding="utf-8")
    note = vault / visible
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntags: [" + ", ".join(tags) + "]\n---\n\n正文\n",
        encoding="utf-8",
    )


def test_build_emits_data_and_page(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _make_object(tmp_path, "a1", title="记忆系统分享", tags=["AI", "记忆"],
                 summary="一段概要", stem="记忆系统分享")

    catalog_path, total, data_path = catalog.build()
    assert total == 1
    assert catalog_path.name == catalog.CATALOG_NAME

    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["count"] == 1
    it = data["items"][0]
    assert it["title"] == "记忆系统分享"
    assert it["tags"] == ["AI", "记忆"]  # 来自 frontmatter，不是 extracted 的兜底
    assert it["cover"] == "_archive/xiaohongshu/a1/raw/v0001/assets/image-001.webp"
    assert it["summary"] == "一段概要"
    assert it["note"] == "Web/Xiaohongshu/记忆系统分享.md"

    page = catalog_path.read_text(encoding="utf-8")
    assert "```dataviewjs" in page
    # 1017：页面脚本在 _archive/catalog-page.js（md 里只是载入它的引导）
    assert "_archive/catalog-page.js" in page
    assert "catalog-data.json" in (tmp_path / "_archive" / "catalog-page.js").read_text(encoding="utf-8")


def test_tags_fall_back_to_extracted_when_no_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _make_object(tmp_path, "b2", title="无 frontmatter tag", tags=[],
                 summary="x", stem="无fm")
    # 覆盖成没有 tags 的可见笔记
    (tmp_path / "Web" / "Xiaohongshu" / "无fm.md").write_text(
        "---\ncssclasses: [x]\n---\n正文\n", encoding="utf-8")

    _, _, data_path = catalog.build()
    it = json.loads(data_path.read_text(encoding="utf-8"))["items"][0]
    assert it["tags"] == ["兜底tag"]


def test_empty_vault_is_ok(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _, total, data_path = catalog.build()
    assert total == 0
    assert json.loads(data_path.read_text(encoding="utf-8"))["items"] == []


def test_explicitly_empty_tags_stay_empty(tmp_path):
    _make_object(tmp_path, 'empty', title='清空标签', tags=[], summary='摘要', stem='清空标签')
    assert catalog.collect(tmp_path)[0]['tags'] == []


def test_collect_carries_hashtags(tmp_path, monkeypatch):
    """批次 D · N9：catalog-data 每篇带原帖话题 hashtags（去掉开头 #，最多 30 个）。"""
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _make_object(tmp_path, "h1", title="悉尼咖啡", tags=["咖啡"], summary="x", stem="悉尼咖啡")
    src = tmp_path / "_archive" / "xiaohongshu" / "h1" / "raw" / "v0001" / "source.json"
    src.write_text(json.dumps({"note": {"hashtags": ["#悉尼生活", "咖啡", " ", "#"] + [f"t{i}" for i in range(40)]}}, ensure_ascii=False), encoding="utf-8")
    _, _, data_path = catalog.build()
    it = json.loads(data_path.read_text(encoding="utf-8"))["items"][0]
    assert it["hashtags"][:2] == ["悉尼生活", "咖啡"]
    assert len(it["hashtags"]) == 30


def test_build_built_at_advances(tmp_path, monkeypatch):
    """F4：每次 build 都重写 built_at（页面「更新」显示它）。"""
    import time
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _, _, data_path = catalog.build()
    a = json.loads(data_path.read_text(encoding="utf-8"))["built_at"]
    time.sleep(1.1)
    catalog.build()
    b = json.loads(data_path.read_text(encoding="utf-8"))["built_at"]
    assert b > a
