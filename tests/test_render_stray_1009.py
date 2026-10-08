"""批次 D · F1-c：重渲染不再吞「受管块外」的手写段落——搬进留言层（幂等），机器碎片不搬、进快照。只写 tmp 库。"""

from __future__ import annotations

from link_brain import comments, history, render as render_mod, restore
from tests._l5_objects import add_media
from tests.test_restore_1009 import obj  # noqa: F401


def _rerender(obj):
    from link_brain import cli
    assert cli.main(["render", obj["item_id"]]) == 0


def _human_after_annotate(text: str, lines: list[str]) -> str:
    """在批注 dataviewjs 块之后（文件尾）加她手写的几行。"""
    return text.rstrip("\n") + "\n\n" + "\n\n".join(lines) + "\n"


def test_fresh_render_variants_have_no_stray(obj):
    for kw in ({}, {"images": 2}, {"images": 1, "video": True}, {"images": 1, "comment_image": True}):
        if kw:
            add_media(obj, **kw)
        restore.restore(obj["item_id"])
        assert render_mod.stray_human_lines(obj["vis"].read_text(encoding="utf-8")) == ([], [])


def test_handwritten_moves_into_comments_once(obj):
    obj["vis"].write_text(_human_after_annotate(obj["clean"], ["我自己写的第一段", "第二段 也是我写的"]), encoding="utf-8")
    _rerender(obj)
    text = obj["vis"].read_text(encoding="utf-8")
    got = [c.text for c in comments.read_comments(obj["vis"])]
    assert any("我自己写的第一段" in t for t in got) and any("第二段 也是我写的" in t for t in got)
    assert render_mod.stray_human_lines(text) == ([], [])
    _rerender(obj)
    again = obj["vis"].read_text(encoding="utf-8")
    assert again.count("我自己写的第一段") == 1
    snaps = history.list_snapshots(obj["dir"])
    assert any("render" in s["name"] for s in snaps)


def test_machine_fragments_go_to_snapshot_not_comments(obj):
    t = obj["clean"].replace(render_mod.CONTENT_END, "", 1)
    t = t.replace(render_mod.CONTENT_START, "", 1)   # 标记全丢：两栏 HTML 落在块外
    frag = '<div class="lb-side">碎片</div>'
    obj["vis"].write_text(_human_after_annotate(t, [frag]), encoding="utf-8")
    human, machine = render_mod.stray_human_lines(obj["vis"].read_text(encoding="utf-8"))
    assert machine and not any("碎片" in h for h in human)
    _rerender(obj)
    got = " ".join(c.text for c in comments.read_comments(obj["vis"]))
    assert "碎片" not in got
    snaps = [s for s in history.list_snapshots(obj["dir"]) if "render" in s["name"]]
    assert snaps and frag in history.read_snapshot(obj["dir"], snaps[0]["name"])


def test_no_snapshot_when_clean(obj):
    _rerender(obj)
    assert not any("render" in s["name"] for s in history.list_snapshots(obj["dir"]))
