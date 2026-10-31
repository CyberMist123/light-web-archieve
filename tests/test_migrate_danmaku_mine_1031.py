"""1031 她「弹幕直接复用批注」：一次性把 `_archive/bilibili/<BV>/danmaku-mine.json` 迁成 notes.json 里带 video_t 的批注。

不丢数据、只追加（⭐ / 草稿 / 墓碑 / 原有批注原样）、可重跑（同 id / 她删过的不再加）、原文件改名 .migrated；
读不懂的原文件 / 读坏的 notes.json 跳过不碰；--dry-run 不写不改名；只剩 .bak 时迁 .bak。conftest 已把 vault 指到 tmp。
"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import migrate_danmaku_mine as mig
from link_brain import note, storage


def _obj(sid: str) -> Path:
    d = storage.object_dir("bilibili", sid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mine(items):
    return json.dumps({"schema_version": 1, "item_id": "bili-x", "source_id": "x", "updated_at": "", "items": items}, ensure_ascii=False)


def test_migrates_items_into_notes_and_renames(capsys):
    d = _obj("BV1mig00001")
    (d / "notes.json").write_text(json.dumps({
        "starred": True, "starred_at": "2026-10-29T18:15:39+11:00", "draft": "没写完",
        "annotations": [{"id": "aold", "ts": "2026-10-01T00:00:00Z", "text": "原有批注"}],
        "deleted": ["adm-gone"],
    }, ensure_ascii=False), encoding="utf-8")
    (d / "danmaku-mine.json").write_text(_mine([
        {"id": "m1", "time": 12.34567, "text": "第一条\n弹幕", "mode": 1, "color": 16777215, "size": 25, "created_at": "2026-10-31T17:35:12+11:00"},
        {"id": "gone", "time": 3, "text": "她删过的", "created_at": "2026-10-31T17:36:00+11:00"},
        {"id": "m2", "time": 0, "text": "试一下", "created_at": "2026-10-31T17:37:00+11:00"},
        {"id": "bad", "time": "x", "text": "坏时间"},
        {"id": "empty", "time": 5, "text": "   "},
    ]), encoding="utf-8")

    assert mig.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["moved"] == 1 and out["errors"] == 0
    assert out["files"][0]["added"] == 2 and out["files"][0]["kept_existing"] == 1

    data = json.loads((d / "notes.json").read_text(encoding="utf-8"))
    assert data["starred"] is True and data["draft"] == "没写完" and data["deleted"] == ["adm-gone"], "别的键原样"
    assert [a["text"] for a in data["annotations"]] == ["原有批注", "第一条 弹幕", "试一下"]
    a = data["annotations"][1]
    assert a == {"id": "adm-m1", "ts": "2026-10-31T17:35:12+11:00", "text": "第一条 弹幕", "to_fable": False,
                 "video_t": 12.346, "migrated_from": "danmaku-mine"}
    assert data["annotations"][2]["video_t"] == 0, "0 秒也是时间"
    assert not (d / "danmaku-mine.json").exists()
    assert (d / "danmaku-mine.json.migrated").is_file(), "原文件留着改名"
    assert note.live_annotations(data)[1]["video_t"] == 12.346

    # 重跑：没有 danmaku-mine.json 了，什么都不做；把 .migrated 放回去再跑也不重复加
    assert mig.run()["files"] == []
    (d / "danmaku-mine.json").write_bytes((d / "danmaku-mine.json.migrated").read_bytes())
    r = mig.run()
    assert r["files"][0]["added"] == 0 and r["files"][0]["kept_existing"] == 3
    assert len(json.loads((d / "notes.json").read_text(encoding="utf-8"))["annotations"]) == 3
    assert (d / "danmaku-mine.json.migrated").is_file() and len(list(d.glob("danmaku-mine.json.migrated-*"))) == 1, "已有 .migrated 就加时间戳"


def test_dry_run_changes_nothing():
    d = _obj("BV1mig00002")
    (d / "danmaku-mine.json").write_text(_mine([{"id": "m1", "time": 1, "text": "hi", "created_at": "2026-10-31T17:35:12+11:00"}]), encoding="utf-8")
    r = mig.run(dry_run=True)
    assert r["skipped"] == 1 and r["files"][0]["added"] == 1 and r["files"][0]["status"] == "dry_run"
    assert (d / "danmaku-mine.json").is_file() and not (d / "notes.json").exists()


def test_broken_files_are_left_alone():
    d1 = _obj("BV1mig00003")
    (d1 / "danmaku-mine.json").write_text("{坏的", encoding="utf-8")
    d2 = _obj("BV1mig00004")
    (d2 / "danmaku-mine.json").write_text(_mine([{"id": "m1", "time": 1, "text": "hi"}]), encoding="utf-8")
    (d2 / "notes.json").write_text("{也坏了", encoding="utf-8")
    r = mig.run()
    assert r["errors"] == 2 and r["moved"] == 0
    assert (d1 / "danmaku-mine.json").read_text(encoding="utf-8") == "{坏的"
    assert (d2 / "notes.json").read_text(encoding="utf-8") == "{也坏了", "读坏的 notes.json 不碰"
    assert (d2 / "danmaku-mine.json").is_file()
    assert mig.main([]) == 1


def test_bak_only_and_new_notes_file():
    d = _obj("BV1mig00005")
    (d / "danmaku-mine.json.bak").write_text(_mine([{"id": "m1", "time": 7.5, "text": "只剩 bak"}]), encoding="utf-8")
    _obj("BV1mig00006")   # 没发过弹幕的：不管
    r = mig.run()
    assert [f["source_id"] for f in r["files"]] == ["BV1mig00005"]
    data = json.loads((d / "notes.json").read_text(encoding="utf-8"))
    assert data["annotations"][0]["video_t"] == 7.5 and data["annotations"][0]["text"] == "只剩 bak"
    assert data["annotations"][0]["ts"], "没有 created_at 也给一个时间"
    assert not (d / "danmaku-mine.json.bak").exists() and (d / "danmaku-mine.json.migrated").is_file()
