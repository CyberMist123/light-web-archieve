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


# --------------------------------------------------------------------------
# 1026 她（录屏 20:51）：「从快照中找回就成为这个样子」——快照多半是「恢复前」存下的那份坏页面（真库那篇：两栏正文块
# 从第 8 张图中间断掉，15 张图只剩 8 张、作者 / 标题 / 正文全没了），以前「从快照找回」把它原样写回去，页面就是坏的。
# --------------------------------------------------------------------------


def _truncated(clean: str) -> str:
    """照真库那份坏快照的样子：两栏正文块那一行中间被截掉一段（div 不配对 → NOTE_BLOCK_SPLIT）。"""
    line = next(ln for ln in clean.split("\n") if ln.lstrip().startswith('<div class="lb-note'))
    a = line.find('<div class="lb-main"')
    b = line.find("</section>", a)
    assert a > 0 and b > a
    return clean.replace(line, line[:a] + line[b:], 1)


def _with_mine(t: str) -> str:
    """她写的：一条留言 + 一个属性（快照找回要把这些取回来）。"""
    t = t.replace("---\ncssclasses", "---\nmood: 想再看\ncssclasses", 1)
    return t.replace(render_mod.COMMENTS_START + "\n", render_mod.COMMENTS_START + "\n"
                     "> [!link-brain-comment]\n> 「20261026 人」快照里的留言\n"
                     "<!-- link-brain: id=c9 actor=human target=none status=open -->\n", 1)


def test_snapshot_list_describes_each_snapshot(obj):
    bad = _with_mine(_truncated(obj["clean"]))
    assert restore.diagnose(bad) == ["NOTE_BLOCK_SPLIT"]
    obj["vis"].write_text(bad, encoding="utf-8")
    out = restore.restore(obj["item_id"])          # 存下的「恢复前」快照就是这份坏的
    assert out["ok"]
    snaps = restore.list_snaps(obj["item_id"])["snapshots"]
    s = next(x for x in snaps if x["name"] == out["snapshot"])
    assert s["broken"] is True and s["issues"] == ["NOTE_BLOCK_SPLIT"]
    assert s["summary"].startswith("页面结构坏了（两栏正文块被换行拆开了）") and "1 个属性、1 条留言" in s["summary"]
    assert "不会把坏的页面写回来" in s["how"]
    # 「保留了 0 个属性、0 条留言、0 处重点」那种零不再念；说清按哪一版存档
    obj["vis"].write_text(obj["clean"].replace(render_mod.CONTENT_END, "", 1), encoding="utf-8")
    msg = restore.restore(obj["item_id"])["message"]
    assert "0 个属性" not in msg and "抓的 v1 重新排版" in msg and "批注不受影响" in msg


def test_recover_broken_snapshot_rebuilds_instead_of_writing_it_back(obj):
    bad = _with_mine(_truncated(obj["clean"]))
    obj["vis"].write_text(bad, encoding="utf-8")
    snap = restore.restore(obj["item_id"])["snapshot"]
    good = obj["vis"].read_text(encoding="utf-8")
    out = restore.recover(obj["item_id"], snapshot=snap)
    assert out["ok"] and out["mode"] == "rebuilt", out
    after = obj["vis"].read_text(encoding="utf-8")
    assert restore.diagnose(after) == [], "找回后页面正常，不是那份坏的"
    assert after.count('<div class="lb-note') == 1 and '<div class="lb-main"' in after
    fm = render_mod.parse_frontmatter(after)
    assert fm["mood"] == "想再看" and "快照里的留言" in after, "她写的从快照里取回来了"
    assert "页面是坏的（两栏正文块被换行拆开了）" in out["message"] and "取回了你写的 1 个属性、1 条留言" in out["message"]
    # 撤销：回到找回前那一版（原样）
    u = restore.undo(obj["item_id"], snapshot=out["snapshot"])
    assert u["ok"] and obj["vis"].read_text(encoding="utf-8") == good


def test_recover_intact_snapshot_writes_it_back_verbatim(obj):
    older = obj["clean"]
    name = history.snapshot(obj["dir"], older, "render")
    obj["vis"].write_text(_with_mine(obj["clean"]), encoding="utf-8")
    cur = obj["vis"].read_text(encoding="utf-8")
    out = restore.recover(obj["item_id"], snapshot=name)
    assert out["ok"] and out["mode"] == "verbatim"
    assert obj["vis"].read_text(encoding="utf-8") == older and "原样写回" in out["message"]
    assert restore.undo(obj["item_id"])["ok"] and obj["vis"].read_text(encoding="utf-8") == cur


def test_cli_from_snapshot(obj, capsys):
    obj["vis"].write_text(_truncated(obj["clean"]), encoding="utf-8")
    snap = restore.restore(obj["item_id"])["snapshot"]
    capsys.readouterr()
    code = cli.main(["restore", obj["item_id"], "--from-snapshot", snap, "--json"])
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and data["ok"] and data["mode"] == "rebuilt" and data["restored_from"] == snap and data["snapshot"]
    assert restore.diagnose(obj["vis"].read_text(encoding="utf-8")) == []
    code = cli.main(["restore", obj["item_id"], "--from-snapshot", "visible-nope.txt", "--json"])
    capsys.readouterr()
    assert code == 2
