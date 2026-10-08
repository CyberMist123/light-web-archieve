"""批次 D · F6-a：playlist（按标签连播的后端，纯读）。合成 catalog-data + 对象，只写 tmp 库。"""

from __future__ import annotations

import json
import os

import pytest

from link_brain import cli, playlist, storage


def _obj(sid, *, video="ok", version=1, old_version_file=False):
    od = storage.object_dir("xiaohongshu", sid)
    raw = od / "raw" / storage.version_name(version)
    (raw / "assets").mkdir(parents=True, exist_ok=True)
    (od / "meta.json").write_text(json.dumps({"current_version": version}), encoding="utf-8")
    media = []
    if video:
        if old_version_file:
            v1 = od / "raw" / "v0001" / "assets"
            v1.mkdir(parents=True, exist_ok=True)
            (v1 / "video.mp4").write_bytes(b"v" * 10)
            file = "raw/v0001/assets/video.mp4"
        else:
            file = "assets/video.mp4"
            if video == "ok":
                (raw / "assets" / "video.mp4").write_bytes(b"v" * 10)
        media.append({"role": "video", "file": file, "download_status": "ok" if video in ("ok", "gone") else "failed"})
        (raw / "assets" / "cover.png").write_bytes(b"p")
        media.append({"role": "video_cover", "file": "assets/cover.png", "download_status": "ok"})
    (raw / "manifest.json").write_text(json.dumps({"media": media}), encoding="utf-8")
    (raw / "source.json").write_text(json.dumps({"note": {"video": {"duration_sec": 61, "width": 64, "height": 64}}}), encoding="utf-8")


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    items = []

    def add(sid, tags, ts, kind="video", **kw):
        _obj(sid, **kw) if kind == "video" else _obj(sid, video=None)
        items.append({"id": f"xiaohongshu-{sid}", "source": "xiaohongshu", "source_id": sid, "title": f"T{sid}",
                      "author": "A", "note": f"Web/Xiaohongshu/T{sid}.md", "tags": tags, "kind": kind, "ts": ts, "date": ts[:10]})
    add("a1", ["健身"], "2026-01-01")
    add("a2", ["#健身"], "2026-03-01")
    add("a3", ["健身", "早餐"], "2026-02-01")
    add("p1", ["健身"], "2026-04-01", kind="image")
    add("n1", ["健身"], "2026-05-01", video="failed")
    add("o1", ["健身"], "2026-01-15", version=2, old_version_file=True)
    add("s1", ["健身/拉伸"], "2025-12-01")
    add("x1", ["健身房打卡"], "2025-11-01")
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    (storage.archive_root() / "catalog-data.json").write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _ids(out):
    return [x["item_id"].split("-")[1] for x in out["items"]]


def test_match_and_order(lib):
    out = playlist.build("#健身", "newest")
    assert _ids(out) == ["a2", "a3", "o1", "a1", "s1"]
    assert playlist.build("健身", "oldest")["items"][0]["item_id"].endswith("s1")
    assert [s["reason"] for s in out["skipped"]] == ["视频没下载"]
    assert "p1" not in _ids(out)
    o1 = next(x for x in out["items"] if x["item_id"].endswith("o1"))
    assert o1["video"].endswith("raw/v0001/assets/video.mp4") and o1["duration_sec"] == 61
    assert out["items"][0]["poster"].endswith("cover.png") and not out["items"][0]["video"].startswith("/")


def test_case_insensitive(lib):
    assert len(playlist.build("健身/拉伸")["items"]) == 1


def test_shuffle_seed_and_start(lib):
    a = playlist.build("健身", "shuffle", seed=7)
    b = playlist.build("健身", "shuffle", seed=7)
    assert _ids(a) == _ids(b) and sorted(_ids(a)) == sorted(_ids(playlist.build("健身")))
    s = playlist.build("健身", "shuffle", seed=7, start="xiaohongshu-a1")
    assert _ids(s)[0] == "a1"
    n = playlist.build("健身", "newest", start="xiaohongshu-a1")
    assert n["start_index"] == 3
    assert playlist.build("健身", "shuffle")["seed"] is not None


def test_tags_summary(lib):
    t = {r["tag"]: r for r in playlist.tags_summary()["tags"]}
    assert t["健身"]["count"] == 5 and t["健身"]["playable"] == 4
    assert "早餐" in t


def test_no_hit_exit_2_with_suggestions(lib, capsys):
    code = cli.main(["playlist", "--tag", "健", "--json"])
    cap = capsys.readouterr()
    data = json.loads(cap.out.strip().splitlines()[-1])
    assert code == 2 and data["ok"] is False and data["items"] == []
    assert "健身" in data["suggestions"]
    assert "{" not in cap.err


def test_no_catalog_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    assert cli.main(["playlist", "--tags", "--json"]) == 1
    assert "目录还没建好" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])["message"]


def test_cli_json_last_line_and_pure_read(lib, capsys):
    def snap():
        return {p: os.stat(p).st_mtime_ns for p in lib.rglob("*")}
    before = snap()
    assert cli.main(["playlist", "--tag", "健身", "--order", "oldest", "--json"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert json.loads(out[-1])["ok"] is True
    assert snap() == before
