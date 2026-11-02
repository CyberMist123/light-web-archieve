"""1102：页面块从 Dataview 挪到 LWA 插件自己身上。

- 默认生成 ```lb-page 块（插件 page-host.js 执行，不要 Dataview）；环境变量 LINK_BRAIN_PAGE_BLOCK / 插件设置 pageBlock=dataviewjs
  照旧生成 dataviewjs 引导（手机上没有 LWA 插件、靠 Dataview 看的库）。
- 所有页（目录 / 星标 / 问收藏 / Wiki / 回收站 / B 站挑选）和每篇笔记的批注块都跟着换；旧库的 md 在 catalog 重建时自然换掉，
  笔记里的批注块只换那一块（只扫一次，记在 _archive/page-blocks.json；换了写法才再扫）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import ai_config, catalog, render, storage

from test_catalog import _make_object

OLD_ANNOT = render.annotate_block("xhs-a1", "_archive/xiaohongshu/a1/notes.json", "dataviewjs")
NEW_ANNOT = render.annotate_block("xhs-a1", "_archive/xiaohongshu/a1/notes.json", "lb-page")
PAGES = ("catalog", "starred", "chat", "wiki", "trash")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.delenv(catalog.PAGE_BLOCK_ENV, raising=False)
    _make_object(tmp_path, "a1", title="一篇", tags=["x"], summary="s", stem="一篇")
    return tmp_path


def _pages(vault: Path) -> dict[str, str]:
    names = catalog.library_pages(vault)
    return {role: (vault / names[role]).read_text(encoding="utf-8") for role in PAGES}


def test_mode_default_env_and_setting(monkeypatch):
    monkeypatch.delenv(catalog.PAGE_BLOCK_ENV, raising=False)
    monkeypatch.setattr(ai_config, "load", lambda: {})
    assert catalog.page_block_mode() == "lb-page"
    monkeypatch.setattr(ai_config, "load", lambda: {"pageBlock": "dataviewjs"})
    assert catalog.page_block_mode() == "dataviewjs"
    monkeypatch.setattr(ai_config, "load", lambda: {"pageBlock": "乱写"})
    assert catalog.page_block_mode() == "lb-page", "认不得的值当默认"
    monkeypatch.setenv(catalog.PAGE_BLOCK_ENV, "DataviewJS")
    assert catalog.page_block_mode() == "dataviewjs", "环境变量优先"

    def boom():
        raise OSError("读不到")
    monkeypatch.delenv(catalog.PAGE_BLOCK_ENV)
    monkeypatch.setattr(ai_config, "load", boom)
    assert catalog.page_block_mode() == "lb-page", "设置读不到也照样生成页面"


def test_page_bootstrap_shapes():
    assert catalog._page_bootstrap("catalog-page.js", mode="lb-page") == "```lb-page\ncatalog-page.js\n```"
    assert NEW_ANNOT == '```lb-page\nannotate-view.js\nitemId: "xhs-a1"\nnotePath: "_archive/xiaohongshu/a1/notes.json"\n```'
    old = catalog._page_bootstrap("catalog-page.js", mode="dataviewjs")
    assert old.startswith("```dataviewjs\n") and old.endswith("\n```") and '"catalog-page.js"' in old
    assert "lb-page-core:begin" in old, "旧写法用的也是同一段载入核心（唯一源）"
    with pytest.raises(ValueError):
        catalog._page_bootstrap("annotate-view.js", {"itemId": "x"}, mode="dataviewjs")


def test_build_writes_lb_page_everywhere(vault):
    catalog.build()
    pages = _pages(vault)
    for role, text in pages.items():
        assert "```lb-page\n" in text and "dataviewjs" not in text, role
    assert "```lb-page\ntrash-page.js\n```" in pages["trash"]
    assert (vault / "_archive" / "trash-page.js").is_file()
    note = (vault / "Web/Xiaohongshu/一篇.md").read_text(encoding="utf-8")
    assert "dataviewjs" not in note


def test_old_vault_pages_and_notes_switch_on_rebuild(vault):
    """旧库：页面和笔记里都是 dataviewjs → catalog 重建一次全换成 lb-page；再重建什么也不动。"""
    note_path = vault / "Web/Xiaohongshu/一篇.md"
    body = note_path.read_text(encoding="utf-8") + "\n用户手写的一行\n\n" + OLD_ANNOT + "\n\n结尾也是用户写的\n"
    note_path.write_text(body, encoding="utf-8")
    catalog.build()   # 先按旧写法起一个旧库
    for role, text in _pages(vault).items():
        assert "lb-page" in text  # 默认就是新写法
    # 模拟真的旧库：页面 md 是旧 dataviewjs、没有 page-blocks.json
    (vault / "_archive" / catalog.PAGE_BLOCKS_NAME).unlink()
    names = catalog.library_pages(vault)
    (vault / names["catalog"]).write_text("---\nlb-page: catalog\ncssclasses: [lb-catalog]\n---\n\n"
                                          + catalog._page_bootstrap(catalog.CATALOG_SCRIPT_NAME, mode="dataviewjs") + "\n", encoding="utf-8")
    note_path.write_text(body, encoding="utf-8")
    catalog.build()
    assert "```lb-page\ncatalog-page.js\n```" in _pages(vault)["catalog"]
    text = note_path.read_text(encoding="utf-8")
    assert NEW_ANNOT in text and OLD_ANNOT not in text
    assert text == body.replace(OLD_ANNOT, NEW_ANNOT), "只换批注块，用户手写的一个字不动"
    marker = json.loads((vault / "_archive" / catalog.PAGE_BLOCKS_NAME).read_text(encoding="utf-8"))
    assert marker["notes"] == "lb-page" and marker["changed"] == 1
    # 再重建：已经换过，不再扫（笔记被人改回旧写法也不动——只在换写法时扫一次）
    note_path.write_text(body, encoding="utf-8")
    catalog.build()
    assert note_path.read_text(encoding="utf-8") == body


def test_dataviewjs_setting_keeps_old_blocks_and_switches_back(vault, monkeypatch):
    note_path = vault / "Web/Xiaohongshu/一篇.md"
    note_path.write_text(note_path.read_text(encoding="utf-8") + "\n" + NEW_ANNOT + "\n", encoding="utf-8")
    monkeypatch.setenv(catalog.PAGE_BLOCK_ENV, "dataviewjs")
    catalog.build()
    for role, text in _pages(vault).items():
        assert "```dataviewjs\n" in text and "```lb-page" not in text, role
    assert OLD_ANNOT in note_path.read_text(encoding="utf-8")
    # 换回默认：下一次重建换回 lb-page
    monkeypatch.delenv(catalog.PAGE_BLOCK_ENV)
    catalog.build()
    assert NEW_ANNOT in note_path.read_text(encoding="utf-8")
    assert all("```lb-page\n" in t for t in _pages(vault).values())


def test_library_pages_finds_renamed_lb_page_without_header(vault):
    (vault / "我的问收藏.md").write_text("---\ncssclasses: [lb-chatpage]\n---\n\n```lb-page\nchat-page.js\n```\n", encoding="utf-8")
    assert catalog.library_pages(vault)["chat"] == "我的问收藏.md"


def test_render_uses_mode(monkeypatch):
    meta = {"item_id": "xhs-a1", "source": "xiaohongshu", "source_id": "a1"}
    monkeypatch.setenv(catalog.PAGE_BLOCK_ENV, "dataviewjs")
    assert render._annotate_block(meta) == OLD_ANNOT
    monkeypatch.delenv(catalog.PAGE_BLOCK_ENV)
    monkeypatch.setattr(ai_config, "load", lambda: {})
    assert render._annotate_block(meta) == NEW_ANNOT


def test_convert_leaves_other_blocks_alone():
    user = "```dataviewjs\ndv.list([1, 2])\n```"
    text = "a\n" + user + "\n" + OLD_ANNOT + "\nb"
    out = render.convert_annotate_block(text, "lb-page")
    assert user in out and NEW_ANNOT in out
    assert render.convert_annotate_block(out, "dataviewjs") == text
    assert render.convert_annotate_block("", "lb-page") == ""


def test_stray_lines_ignore_lb_page_annotate_block():
    human, _ = render.stray_human_lines("---\na: 1\n---\n" + NEW_ANNOT + "\n用户写的\n")
    assert human == ["用户写的"]
