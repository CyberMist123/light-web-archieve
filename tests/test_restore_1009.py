"""批次 D · F1-a：restore（快照 → 按存档重写同一路径 → 可撤销）。不碰网络、不碰真库（LINK_BRAIN_VAULT 指 tmp）。"""

from __future__ import annotations

import json
import re

import pytest

from link_brain import cli, history, note as note_mod, render as render_mod, restore, storage
from tests.test_render import _get_item_id, setup_env


@pytest.fixture
def obj(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])   # 图片下不来退出 2，笔记照样写出来
    item_id, source, source_id = _get_item_id(tmp_path)
    meta = storage.read_json(storage.object_dir(source, source_id) / "meta.json")
    vis = storage.vault_root() / meta["visible_note"]
    return {"item_id": item_id, "source": source, "source_id": source_id, "vis": vis,
            "dir": storage.object_dir(source, source_id), "clean": vis.read_text(encoding="utf-8")}


def _strip_volatile(text: str) -> str:
    return re.sub(r"「\d{8} ", "「D ", text)


def test_restore_after_content_layer_deleted(obj):
    t = obj["clean"]
    s, e = t.find(render_mod.CONTENT_START), t.find(render_mod.CONTENT_END) + len(render_mod.CONTENT_END)
    obj["vis"].write_text(t[:s] + t[e:], encoding="utf-8")
    out = restore.restore(obj["item_id"])
    assert out["ok"], out
    after = obj["vis"].read_text(encoding="utf-8")
    assert restore.diagnose(after) == []
    assert '<div class="lb-note' in after
    assert _strip_volatile(after) == _strip_volatile(t)
    assert "CONTENT_MARKERS_MISSING" in out["issues_before"]


def test_restore_keeps_handwritten_keys_and_tags(obj):
    t = obj["clean"].replace("---\ncssclasses", "---\ntime: 2026-10-01\nfrom: 朋友\ncomment: '注意: 要回看'\ncssclasses", 1)
    t = re.sub(r"(?m)^tags: .*$", 'tags: ["手改标签"]', t, count=1)
    t = t.replace(render_mod.COMMENTS_START, "", 1)
    obj["vis"].write_text(t, encoding="utf-8")
    out = restore.restore(obj["item_id"])
    assert out["ok"], out
    fm = render_mod.parse_frontmatter(obj["vis"].read_text(encoding="utf-8"))
    assert str(fm["time"]) == "2026-10-01" and fm["from"] == "朋友" and fm["comment"] == "注意: 要回看"
    assert fm["tags"] == ["手改标签"]
    assert set(out["kept"]["frontmatter_keys"]) >= {"time", "from", "comment"}


def test_restore_salvages_broken_frontmatter(obj):
    t = obj["clean"].replace("---\ncssclasses: [link-brain, xhs-note]", "---\nkeep: 1\ncssclasses: [link-brain, xhs-note\nbad:\n  - [unclosed\n  - x: : y", 1)
    obj["vis"].write_text(t, encoding="utf-8")
    assert render_mod.frontmatter_broken(t)
    out = restore.restore(obj["item_id"])
    assert out["ok"], out
    assert out["kept"]["unparsed_frontmatter_lines"] == 4
    fm = render_mod.parse_frontmatter(obj["vis"].read_text(encoding="utf-8"))
    assert fm["cssclasses"] == ["link-brain", "xhs-note"] and fm["keep"] == 1


def test_restore_rebuilds_half_deleted_comments_layer(obj):
    from link_brain import comments
    t = obj["clean"]
    extra = ("> [!link-brain-comment]\n> 「20261001 人」第一条\n<!-- link-brain: id=c1 actor=human target=none status=open -->\n"
             "> [!link-brain-comment]\n> 「20261002 人」第二条\n<!-- link-brain: id=c2 actor=human target=none status=open -->\n")
    t = t.replace(render_mod.COMMENTS_START + "\n", render_mod.COMMENTS_START + "\n" + extra, 1)
    t = t.replace(render_mod.COMMENTS_END, "", 1)
    obj["vis"].write_text(t, encoding="utf-8")
    out = restore.restore(obj["item_id"])
    assert out["ok"], out
    texts = [c.text for c in comments.read_comments(obj["vis"])]
    assert "第一条" in texts and "第二条" in texts


def test_restore_keeps_marks_when_content_markers_gone(obj):
    t = obj["clean"]
    note_at = t.find('<div class="lb-note')
    phrase = None
    for m in re.finditer(r">([^<>\s]{6,})<", t[note_at:]):
        phrase = m.group(1)[:4]
        break
    assert phrase
    t = t.replace(phrase, f"<mark>{phrase}</mark>", 1).replace(render_mod.CONTENT_START, "", 1)
    obj["vis"].write_text(t, encoding="utf-8")
    out = restore.restore(obj["item_id"])
    assert out["ok"], out
    assert f"<mark>{phrase}</mark>" in obj["vis"].read_text(encoding="utf-8")


def test_notes_json_untouched_and_undo_roundtrip(obj):
    note_mod.save_notes(obj["source"], obj["source_id"], {"starred": True, "annotations": [{"id": "a", "text": "x", "ts": "1"}]})
    nj = obj["dir"] / "notes.json"
    before_bytes, before_mtime = nj.read_bytes(), nj.stat().st_mtime_ns
    broken = obj["clean"].replace(render_mod.CONTENT_END, "", 1)
    obj["vis"].write_text(broken, encoding="utf-8")
    out = restore.restore(obj["item_id"])
    assert out["ok"]
    assert nj.read_bytes() == before_bytes and nj.stat().st_mtime_ns == before_mtime
    assert history.read_snapshot(obj["dir"], out["snapshot"]) == broken
    restored = obj["vis"].read_text(encoding="utf-8")
    u = restore.undo(obj["item_id"])
    assert u["ok"] and obj["vis"].read_text(encoding="utf-8") == broken
    restore.undo(obj["item_id"], snapshot=u["snapshot"])
    assert obj["vis"].read_text(encoding="utf-8") == restored


def test_snapshots_keep_20(obj):
    for i in range(25):
        history.snapshot(obj["dir"], f"v{i}", "restore")
    snaps = history.list_snapshots(obj["dir"])
    assert len(snaps) == 20
    assert history.read_snapshot(obj["dir"], snaps[0]["name"]) == "v24"


def test_restore_path_pins_when_item_id_deleted(obj):
    t = re.sub(r"(?m)^  item_id: .*\n", "", obj["clean"], count=1)
    obj["vis"].write_text(t, encoding="utf-8")
    rel = str(obj["vis"].relative_to(storage.vault_root())).replace("\\", "/")
    before = sorted(p.name for p in storage.visible_dir().rglob("*.md"))
    out = restore.restore(path=rel)
    assert out["ok"], out
    assert sorted(p.name for p in storage.visible_dir().rglob("*.md")) == before
    assert obj["vis"].is_file() and render_mod.frontmatter_item_id(obj["vis"].read_text(encoding="utf-8")) == obj["item_id"]
    assert not any("__" in p.name for p in storage.visible_dir().rglob("*.md"))


def test_restore_renamed_and_moved_note(obj):
    sub = storage.visible_dir() / "子目录"
    sub.mkdir()
    moved = sub / "她改的名字.md"
    obj["vis"].rename(moved)
    rel = str(moved.relative_to(storage.vault_root())).replace("\\", "/")
    out = restore.restore(path=rel)
    assert out["ok"], out
    assert moved.is_file() and not obj["vis"].exists()


@pytest.mark.parametrize("bad", ["../../x.md", "C:/x.md", "/abs/x.md", "Web/Xiaohongshu/x.txt"])
def test_bad_paths_exit_2_no_write(obj, bad, capsys):
    before = obj["vis"].read_bytes()
    code = cli.main(["restore", "--path", bad, "--json"])
    assert code == 2
    assert obj["vis"].read_bytes() == before
    assert not (obj["dir"] / "history").exists()


def test_restore_does_not_call_models_or_network(obj, monkeypatch):
    from link_brain import llm as llm_mod, vision as vision_mod
    import httpx

    def boom(*a, **k):
        raise AssertionError("不该调")
    monkeypatch.setattr(vision_mod, "build_vision", boom, raising=False)
    monkeypatch.setattr(llm_mod, "extract", boom)
    monkeypatch.setattr(httpx, "Client", boom)
    obj["vis"].write_text(obj["clean"].replace(render_mod.CONTENT_END, "", 1), encoding="utf-8")
    assert restore.restore(obj["item_id"])["ok"]


def test_render_failure_rolls_back(obj, monkeypatch):
    broken = obj["clean"].replace(render_mod.CONTENT_END, "", 1)
    obj["vis"].write_text(broken, encoding="utf-8")
    raw = obj["vis"].read_bytes()

    def boom(**k):
        raise RuntimeError("炸")
    monkeypatch.setattr(render_mod, "render_visible_md", boom)
    out = restore.restore(obj["item_id"])
    assert not out["ok"] and out["code"] == "PERMANENT.NOTE_DAMAGED"
    assert obj["vis"].read_bytes() == raw
    assert out["snapshot"] and (obj["dir"] / "history" / out["snapshot"]).is_file()


def test_cli_json_and_exit_code(obj, capsys):
    obj["vis"].write_text(obj["clean"].replace(render_mod.CONTENT_END, "", 1), encoding="utf-8")
    code = cli.main(["restore", obj["item_id"], "--json"])
    cap = capsys.readouterr()
    data = json.loads(cap.out.strip().splitlines()[-1])
    assert code == 0 and data["ok"] is True
    assert "已按存档恢复" in cap.err.strip().splitlines()[-1]
    code = cli.main(["restore", obj["item_id"], "--list", "--json"])
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and data["snapshots"]
