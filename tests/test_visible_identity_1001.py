"""1001 审计 ingest/render-8、ui/ui-5：可见笔记的「身份」按 frontmatter 的 item_id 认，不按文件名认。

- 她在 Obsidian 里改名 / 挪进自己的文件夹：重渲染沿用她那份，不冒一份新的；删除时同对象的所有 md 一起进回收站。
- 她手写的属性把 YAML 写坏了：不当「别人的文件」改名、不丢手写键；解析不了就原样保留 frontmatter。
"""

from __future__ import annotations

import pytest

from link_brain import cli, index as index_mod, remove, render as render_mod, storage

from test_attachments import _ids, setup_env


@pytest.fixture
def note(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _ids()
    meta = storage.read_json(storage.object_dir(source, source_id) / "meta.json")
    path = storage.vault_root() / meta["visible_note"]
    return {"item_id": item_id, "source": source, "source_id": source_id, "path": path}


def _visible_mds():
    return sorted(p.relative_to(storage.visible_dir()).as_posix() for p in storage.visible_dir().rglob("*.md"))


def _add_handwritten(path, key_line="finder: 我自己", tag="我的标签"):
    text = path.read_text(encoding="utf-8")
    text = text.replace("---\ncssclasses:", f"---\n{key_line}\ncssclasses:", 1)
    text = text.replace('tags: [', f'tags: ["{tag}", ', 1)
    path.write_text(text, encoding="utf-8")


def test_renamed_and_moved_note_is_reused_not_duplicated(note):
    _add_handwritten(note["path"])
    moved = storage.visible_dir() / "读书" / "我改的名字.md"
    moved.parent.mkdir()
    note["path"].rename(moved)

    out = render_mod.render_object(note["source"], note["source_id"])
    assert _visible_mds() == ["读书/我改的名字.md"], "不该再冒一份按标题命名的新文件"
    assert out["visible_note"].endswith("读书/我改的名字.md")
    text = moved.read_text(encoding="utf-8")
    assert "finder: 我自己" in text and "我的标签" in text and render_mod.CONTENT_START in text

    # 再渲染一次（标题没变 / 变了都一样）：尊重她的名字，不挪回去
    render_mod.render_object(note["source"], note["source_id"])
    assert _visible_mds() == ["读书/我改的名字.md"]


def test_delete_sweeps_every_copy_of_the_object(note):
    moved = storage.visible_dir() / "我改的名字.md"
    note["path"].rename(moved)
    render_mod.render_object(note["source"], note["source_id"])  # meta 指到 moved
    stray = storage.visible_dir() / "旧的那份.md"
    stray.write_text(moved.read_text(encoding="utf-8"), encoding="utf-8")  # 以前同步冒出来的重复份

    out = remove.delete_items([note["item_id"]])
    assert out["deleted"] == 1
    assert _visible_mds() == [], "同一对象的 md 都要进回收站，不留孤儿"

    conn = index_mod.connect()
    try:
        restored = remove.restore_item(conn, note["item_id"])
    finally:
        conn.close()
    assert restored["status"] == "restored"
    assert _visible_mds() == sorted(["我改的名字.md", "旧的那份.md"])


def test_colon_in_handwritten_value_keeps_name_and_keys(note, capsys):
    _add_handwritten(note["path"], key_line="comment: 注意: 这篇要回看")
    before = note["path"].name
    render_mod.render_object(note["source"], note["source_id"])
    assert _visible_mds() == [before], "不该被当成别人的文件改名"
    fm = render_mod.parse_frontmatter(note["path"].read_text(encoding="utf-8"))
    assert fm["comment"] == "注意: 这篇要回看" and "我的标签" in fm["tags"]
    assert fm["link_brain"]["item_id"] == note["item_id"]


def test_unparseable_frontmatter_is_kept_verbatim_in_place(note, capsys):
    text = note["path"].read_text(encoding="utf-8")
    broken = text.replace("---\ncssclasses:", "---\nmine: [没闭合的列表, 二\n  乱缩进: : x\ncssclasses:", 1)
    note["path"].write_text(broken, encoding="utf-8")
    assert render_mod.frontmatter_broken(broken)
    assert render_mod.owner_item_id(note["path"]) == note["item_id"], "YAML 坏了也认得出是自己的"
    head = render_mod.FRONTMATTER_RE.match(broken).group(0)

    capsys.readouterr()
    render_mod.render_object(note["source"], note["source_id"])
    assert _visible_mds() == [note["path"].name]
    after = note["path"].read_text(encoding="utf-8")
    assert after.startswith(head.rstrip("\n")), "她的 frontmatter 一字不改"
    assert render_mod.CONTENT_START in after
    assert "写坏了" in capsys.readouterr().err


def test_tolerant_parse_unit():
    assert render_mod._tolerant_yaml("a: 1\ncomment: 注意: 要回看\ntags:\n- x") == {
        "a": 1, "comment": "注意: 要回看", "tags": ["x"]}
    assert render_mod._tolerant_yaml("a: [1, 2\n  3\nb: 3") is None
    assert render_mod._tolerant_yaml("a: [1, 2\nb: 3") == {"a": "[1, 2", "b": 3}, "单行写坏的值原样当字符串留下"
    assert render_mod.frontmatter_item_id("---\nx: a: b: [\nlink_brain:\n  item_id: xhs-1\n---\n") == "xhs-1"
