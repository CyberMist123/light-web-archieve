"""r5 补测：按标签连播（纯读 tmp vault 里的 catalog-data + manifest；不写库、不联网、不起进程）。"""
from __future__ import annotations

import json

import pytest

from link_brain import playlist, storage


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    return tmp_path / "vault"


def _video(vault, sid, *, media_status="ok", file_exists=True, dims=(1080, 1920), dur=61.5, cover=True):
    obj = vault / "_archive" / "xiaohongshu" / sid
    raw = obj / "raw" / "v0001"
    raw.mkdir(parents=True)
    (obj / "meta.json").write_text(json.dumps({"current_version": 1}), encoding="utf-8")
    rows = [{"role": "video", "file": "videos/x.mp4", "download_status": media_status}]
    if cover:
        rows.append({"role": "video_cover", "file": "videos/cover.jpg", "download_status": "ok"})
    (raw / "manifest.json").write_text(json.dumps({"media": rows}), encoding="utf-8")
    (raw / "source.json").write_text(json.dumps({"note": {"video": {"duration_sec": dur, "width": dims[0], "height": dims[1]}}}),
                                     encoding="utf-8")
    (raw / "videos").mkdir()
    if file_exists:
        (raw / "videos" / "x.mp4").write_bytes(b"0123456789")
        (raw / "videos" / "cover.jpg").write_bytes(b"cover")
    return obj


def _catalog(vault, items):
    d = vault / "_archive"
    d.mkdir(parents=True, exist_ok=True)
    (d / "catalog-data.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def test_tag_match_norm_and_subtag():
    tags = ["做饭", "烤箱/空气炸锅", "#Vlog"]
    assert playlist.tag_match(tags, "#做饭") and playlist.tag_match(tags, " 做饭 ")
    assert playlist.tag_match(tags, "烤箱")            # 子标签算命中父标签
    assert playlist.tag_match(tags, "VLOG")            # 大小写不敏感
    assert not playlist.tag_match(tags, "烤箱/别的")
    assert not playlist.tag_match(tags, "") and not playlist.tag_match(None, "做饭")


def test_video_of_all_statuses(tmp_path, monkeypatch):
    vault = _env(tmp_path, monkeypatch)
    ok = _video(vault, "ok1")
    item = {"id": "xhs-ok1", "source": "xiaohongshu", "source_id": "ok1"}
    v = playlist.video_of(item)
    assert v["status"] == "ok"
    assert v["video"] == "_archive/xiaohongshu/ok1/raw/v0001/videos/x.mp4"  # 库内相对、正斜杠
    assert v["poster"].endswith("cover.jpg") and v["bytes"] == 10
    assert v["duration_sec"] == 61.5 and v["width"] == 1080 and v["height"] == 1920
    # agent_md 给了就用它定位（不靠 source 拆）
    assert playlist.video_of({"id": "zzz", "agent_md": "_archive/xiaohongshu/ok1/derived/agent.md"})["status"] == "ok"
    assert playlist.video_of({"id": "xhs-none"}) == {"status": "none"}       # 目录都不在
    _video(vault, "nd1", media_status="failed")
    assert playlist.video_of({"id": "xhs-nd1", "source": "xiaohongshu", "source_id": "nd1"})["status"] == "not_downloaded"
    _video(vault, "miss1", file_exists=False)
    assert playlist.video_of({"id": "xhs-miss1", "source": "xiaohongshu", "source_id": "miss1"})["status"] == "missing"
    # 目录在但 manifest 里没有视频轨
    _ = _video(vault, "nv1", cover=False)
    (vault / "_archive" / "xiaohongshu" / "nv1" / "raw" / "v0001" / "manifest.json").write_text(
        json.dumps({"media": [{"role": "note_image", "file": "a.jpg", "download_status": "ok"}]}), encoding="utf-8")
    assert playlist.video_of({"id": "xhs-nv1", "source": "xiaohongshu", "source_id": "nv1"}) == {"status": "none"}


def test_tags_summary_counts_playable_only(tmp_path, monkeypatch):
    vault = _env(tmp_path, monkeypatch)
    _video(vault, "a"); _video(vault, "b"); _video(vault, "c", media_status="failed")
    _catalog(vault, [
        {"id": "xhs-a", "kind": "video", "source": "xiaohongshu", "source_id": "a", "tags": ["做饭", "烤箱"]},
        {"id": "xhs-b", "kind": "video", "source": "xiaohongshu", "source_id": "b", "tags": ["做饭"]},
        {"id": "xhs-c", "kind": "video", "source": "xiaohongshu", "source_id": "c", "tags": ["烤箱"]},
        {"id": "xhs-d", "kind": "image", "source": "xiaohongshu", "source_id": "d", "tags": ["做饭"]},  # 非视频不算
    ])
    out = playlist.tags_summary()
    assert out["ok"] is True
    assert out["tags"] == [
        {"tag": "做饭", "count": 2, "playable": 2},
        {"tag": "烤箱", "count": 2, "playable": 1},   # 一条没下载：count 有、playable 无；同 playable 按条数排
    ]
    # 目录文件不在：明确报「还没建好」、退出码 1
    (vault / "_archive" / "catalog-data.json").unlink()
    with pytest.raises(playlist.PlaylistError) as err2:
        playlist.tags_summary()
    assert err2.value.exit_code == 1 and "目录还没建好" in str(err2.value)


def test_build_orders_and_start(tmp_path, monkeypatch):
    vault = _env(tmp_path, monkeypatch)
    pairs = (("a", "2026-01-02"), ("b", "2026-03-04"), ("c", "2026-02-05"))
    for sid, ts in pairs:
        _video(vault, sid)
    _catalog(vault, [
        {"id": f"xhs-{s}", "kind": "video", "source": "xiaohongshu", "source_id": s, "tags": ["做饭"],
         "title": f"t{s}", "ts": ts} for s, ts in pairs
    ])
    newest = playlist.build("做饭")
    assert [x["item_id"] for x in newest["items"]] == ["xhs-b", "xhs-c", "xhs-a"]  # 按 ts 降序
    oldest = playlist.build("做饭", order="oldest")
    assert [x["item_id"] for x in oldest["items"]] == ["xhs-a", "xhs-c", "xhs-b"]
    sh1 = playlist.build("做饭", order="shuffle", seed=7)
    sh2 = playlist.build("做饭", order="shuffle", seed=7)
    assert [x["item_id"] for x in sh1["items"]] == [x["item_id"] for x in sh2["items"]]  # 同种子确定
    assert sh1["seed"] == 7
    # --start：正常顺序挪 start_index；shuffle 把那一条换到最前
    assert playlist.build("做饭", start="xhs-c")["start_index"] == 1
    sh3 = playlist.build("做饭", order="shuffle", seed=7, start="xhs-a")
    assert sh3["items"][0]["item_id"] == "xhs-a" and sh3["start_index"] == 0
    with pytest.raises(playlist.PlaylistError) as err:
        playlist.build("做饭", order="random")
    assert err.value.exit_code == 2


def test_build_skips_and_counts_missing(tmp_path, monkeypatch):
    vault = _env(tmp_path, monkeypatch)
    _video(vault, "ok"); _video(vault, "nd", media_status="failed"); _video(vault, "gone", file_exists=False)
    _catalog(vault, [
        {"id": "xhs-ok", "kind": "video", "source": "xiaohongshu", "source_id": "ok", "tags": ["做饭"], "ts": "1"},
        {"id": "xhs-nd", "kind": "video", "source": "xiaohongshu", "source_id": "nd", "tags": ["做饭"], "ts": "2"},
        {"id": "xhs-gone", "kind": "video", "source": "xiaohongshu", "source_id": "gone", "tags": ["做饭"], "ts": "3"},
    ])
    out = playlist.build("做饭")
    assert out["ok"] is True and [x["item_id"] for x in out["items"]] == ["xhs-ok"]
    assert [(s["item_id"], s["reason"]) for s in out["skipped"]] == [
        ("xhs-nd", "视频没下载"), ("xhs-gone", "视频文件不在了")]
    assert "2 条没下载，跳过了" in out["message"]


def test_build_no_hit_suggests_similar_tags(tmp_path, monkeypatch):
    vault = _env(tmp_path, monkeypatch)
    _video(vault, "a"); _video(vault, "b"); _video(vault, "c")
    _catalog(vault, [
        {"id": "xhs-a", "kind": "video", "source": "xiaohongshu", "source_id": "a", "tags": ["空气炸锅"], "ts": "1"},
        {"id": "xhs-b", "kind": "video", "source": "xiaohongshu", "source_id": "b", "tags": ["空气炸锅"], "ts": "2"},
        {"id": "xhs-c", "kind": "video", "source": "xiaohongshu", "source_id": "c", "tags": ["烤箱"], "ts": "3"},
    ])
    out = playlist.build("炸锅")      # 部分命中别的标签 → 建议；精确同名的不再建议
    assert out["ok"] is False and out["_exit"] == 2 and out["items"] == []
    assert out["suggestions"] == ["空气炸锅"]
    assert "是不是要找：#空气炸锅" in out["message"]
    exact = playlist.build("不存在的标签")
    assert exact["suggestions"] == [] and "_exit" in exact
