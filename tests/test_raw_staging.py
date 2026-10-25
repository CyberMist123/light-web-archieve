"""第二波 PR④ RAW 暂存发布：写一半不算版本、号码不复用、发布原子、删除单篇锁、doctor 报数。网络无关。"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from link_brain import cli, doctor, domain, index as index_mod, remove, storage, videos
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"
SRC = xhs.SOURCE


def _manifest(v):
    return {"version": v, "media": []}


def _raw(tmp_path):
    return tmp_path / "_archive" / SRC / NOTE_ID / "raw"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / ".lbhome"))
    return tmp_path


# --------------------------------------------------------------------------
# 版本目录 / 暂存目录
# --------------------------------------------------------------------------

def test_staging_dir_is_not_a_version_and_gone_without_publish(vault):
    with storage.stage_version(SRC, NOTE_ID) as stg:
        assert stg.path.name.startswith(storage.STAGING_PREFIX)
        assert (stg.path / "assets").is_dir()
        assert storage.existing_versions(SRC, NOTE_ID) == []
        assert storage.next_version(SRC, NOTE_ID) == 1
        (stg.path / "source.json").write_text("{}", encoding="utf-8")
    assert not stg.path.exists()
    assert not storage.version_dirs(SRC, NOTE_ID)


def test_publish_writes_manifest_then_renames(vault):
    seen = []
    with storage.stage_version(SRC, NOTE_ID) as stg:
        (stg.path / "source.json").write_text("{}", encoding="utf-8")
        v = stg.publish(lambda n: seen.append(n) or _manifest(n))
    assert v == 1 and seen == [1] and stg.published
    out = _raw(vault) / "v0001"
    assert out.is_dir() and storage.is_complete_version(out)
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["version"] == 1
    assert storage.existing_versions(SRC, NOTE_ID) == [1]
    assert not any(p.name.startswith(storage.STAGING_PREFIX) for p in _raw(vault).iterdir())


def test_publish_refuses_without_manifest(vault):
    with storage.stage_version(SRC, NOTE_ID) as stg:
        with pytest.raises(RuntimeError, match="manifest.json"):
            stg.publish()
    assert storage.version_dirs(SRC, NOTE_ID) == {}


def test_publish_twice_refused(vault):
    with storage.stage_version(SRC, NOTE_ID) as stg:
        stg.publish(_manifest)
        with pytest.raises(RuntimeError):
            stg.publish(_manifest)


def test_half_version_is_not_counted_but_its_number_is_never_reused(vault):
    """老代码崩在下载中留下的 raw/v0001（没 manifest.json）：不算版本、不动；下一个号是 2，不是 1。"""
    half = _raw(vault) / "v0001"
    (half / "assets").mkdir(parents=True)
    (half / "source.json").write_text("{}", encoding="utf-8")
    assert storage.existing_versions(SRC, NOTE_ID) == []
    assert storage.incomplete_versions(SRC, NOTE_ID) == [1]
    assert storage.next_version(SRC, NOTE_ID) == 2
    with storage.stage_version(SRC, NOTE_ID) as stg:
        assert stg.publish(_manifest) == 2
    assert storage.existing_versions(SRC, NOTE_ID) == [2]
    assert (half / "source.json").is_file()          # 半截一个字节不动


def test_publish_takes_new_number_when_someone_published_first(vault):
    """finalize 里模拟别的进程抢先发了同一个号：改名撞上，重新取号、finalize 再调一次。"""
    calls = []

    def finalize(n):
        calls.append(n)
        if len(calls) == 1:
            other = _raw(vault) / storage.version_name(n)
            other.mkdir(parents=True)
            (other / "manifest.json").write_text("{}", encoding="utf-8")
        return _manifest(n)

    with storage.stage_version(SRC, NOTE_ID) as stg:
        v = stg.publish(finalize)
    assert calls == [1, 2] and v == 2
    assert storage.existing_versions(SRC, NOTE_ID) == [1, 2]
    assert json.loads((_raw(vault) / "v0002" / "manifest.json").read_text(encoding="utf-8"))["version"] == 2


def test_publish_retries_permission_error(vault, monkeypatch):
    real = os.rename
    left = {"n": 2}

    def flaky(a, b):
        if left["n"]:
            left["n"] -= 1
            raise PermissionError("被占")
        return real(a, b)

    monkeypatch.setattr(storage.os, "rename", flaky)
    with storage.stage_version(SRC, NOTE_ID) as stg:
        assert stg.publish(_manifest) == 1
    assert left["n"] == 0 and storage.existing_versions(SRC, NOTE_ID) == [1]


def test_publish_gives_up_after_retries_and_keeps_staging(vault, monkeypatch):
    monkeypatch.setattr(storage.os, "rename", lambda a, b: (_ for _ in ()).throw(PermissionError("一直占")))
    with pytest.raises(PermissionError):
        with storage.stage_version(SRC, NOTE_ID) as stg:
            stg.publish(_manifest, retries=2)
    assert storage.version_dirs(SRC, NOTE_ID) == {}      # 没发出半截版本
    assert not stg.path.exists()                          # 退出 with 没发布 → 暂存删掉


def test_two_threads_publish_distinct_numbers(vault):
    got, errors = [], []
    gate = threading.Barrier(4)

    def work():
        try:
            with storage.stage_version(SRC, NOTE_ID) as stg:
                gate.wait(5)
                got.append(stg.publish(_manifest))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors and sorted(got) == [1, 2, 3, 4]
    assert storage.existing_versions(SRC, NOTE_ID) == [1, 2, 3, 4]


def test_sweep_staging_only_removes_stale(vault):
    obj = storage.object_dir(SRC, NOTE_ID)
    with storage.stage_version(SRC, NOTE_ID) as fresh:
        stale = obj / "raw" / (storage.STAGING_PREFIX + "old")
        stale.mkdir()
        past = time.time() - storage.STAGING_STALE_S - 60
        os.utime(stale, (past, past))
        removed = storage.sweep_staging(obj)
        assert removed == [stale] and not stale.exists() and fresh.path.is_dir()
    # 进入 stage_version 时顺手清：再放一个过期的，下次 with 一进来就没了
    stale.mkdir()
    os.utime(stale, (past, past))
    with storage.stage_version(SRC, NOTE_ID):
        assert not stale.exists()


# --------------------------------------------------------------------------
# probe_object → domain.lookup
# --------------------------------------------------------------------------

def test_probe_object_states(vault):
    conn = index_mod.connect()
    try:
        p = storage.probe_object(conn, SRC, NOTE_ID)
        assert domain.lookup(p).state is domain.Presence.NEW
        # 磁盘上有完整版本、没 meta → 孤儿版本（PR⑤ 收编）；有 meta 没进索引 → 在库但要重建索引
        with storage.stage_version(SRC, NOTE_ID) as stg:
            stg.publish(_manifest)
        p = storage.probe_object(conn, SRC, NOTE_ID)
        assert p.complete_versions == (1,) and not p.has_meta and not p.in_index
        assert domain.lookup(p).state is domain.Presence.ORPHAN
        storage.write_json(storage.object_dir(SRC, NOTE_ID) / "meta.json", {"current_version": 1})
        p = storage.probe_object(conn, SRC, NOTE_ID)
        lk = domain.lookup(p)
        assert p.has_meta and lk.state is domain.Presence.IN_LIBRARY and lk.needs_reindex
        index_mod.write_tombstone(conn, {"source": SRC, "source_id": NOTE_ID, "item_id": domain.item_id(SRC, NOTE_ID),
                                         "deleted_at": "2026-10-25T00:00:00+11:00", "trash_dir": "_trash/x"})
        p = storage.probe_object(conn, SRC, NOTE_ID)
        assert p.tombstoned and domain.lookup(p).state is domain.Presence.DELETED
    finally:
        conn.close()
    # 不给连接：只看磁盘
    p = storage.probe_object(None, SRC, NOTE_ID)
    assert p.complete_versions == (1,) and not p.in_index and not p.tombstoned


# --------------------------------------------------------------------------
# videos.backfill 走暂存：下载中崩了不留版本
# --------------------------------------------------------------------------

def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _ingest_one(monkeypatch):
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: {
        "note_id": NOTE_ID, "xsec_token": "FAKE_TOKEN", "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": text, "input_kind": "url", "resolved_url": text})
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _fixture())
    cli.main(["ingest", "https://example.invalid/share"])
    conn = index_mod.connect()
    try:
        return dict(index_mod.find_object(conn, SRC, NOTE_ID))
    finally:
        conn.close()


class Boom(Exception):
    pass


def _client(handler):
    """videos 里的 httpx 换成只走假传输的；HTTPError 还得是真的（download 按它捕获）。"""
    return SimpleNamespace(Client=lambda *a, **k: httpx.Client(transport=httpx.MockTransport(handler)),
                           HTTPError=httpx.HTTPError)


def test_backfill_crash_mid_download_leaves_no_version(vault, monkeypatch):
    row = _ingest_one(monkeypatch)
    monkeypatch.setattr(xhs, "_video", lambda note: {"video_url": "https://x/vid"})

    def handler(req):
        raise Boom("网断了 / 进程被杀")

    monkeypatch.setattr(videos, "httpx", _client(handler))
    before = storage.read_json(storage.object_dir(SRC, NOTE_ID) / "meta.json")
    with pytest.raises(Boom):
        videos.backfill(row)
    assert storage.version_dirs(SRC, NOTE_ID).keys() == {1}
    assert not any(p.name.startswith(storage.STAGING_PREFIX) for p in _raw(vault).iterdir())
    assert storage.read_json(storage.object_dir(SRC, NOTE_ID) / "meta.json") == before


def test_backfill_publishes_complete_version(vault, monkeypatch):
    row = _ingest_one(monkeypatch)
    monkeypatch.setattr(xhs, "_video", lambda note: {"video_url": "https://x/vid"})
    monkeypatch.setattr(videos, "httpx",
                        _client(lambda req: httpx.Response(200, content=b"\x00\x00\x00\x20ftyp" + b"0" * 50)))
    out = videos.backfill(row)
    assert out["status"] == "ok" and out["bytes"] == 58
    raw = _raw(vault) / "v0002"
    assert storage.is_complete_version(raw) and (raw / "assets" / "video.mp4").stat().st_size == 58
    manifest = storage.read_json(raw / "manifest.json")
    entry = next(m for m in manifest["media"] if m["role"] == "video")
    assert entry["file"] == "raw/v0002/assets/video.mp4" and manifest["version"] == 2
    assert storage.read_json(raw / "source.json")["note"]["video"]["downloaded"] is True
    meta = storage.read_json(storage.object_dir(SRC, NOTE_ID) / "meta.json")
    assert meta["current_version"] == 2 and meta["versions"] == [1, 2]
    assert not any(p.name.startswith(storage.STAGING_PREFIX) for p in _raw(vault).iterdir())


# --------------------------------------------------------------------------
# 删除走单篇锁；doctor 报数
# --------------------------------------------------------------------------

def test_delete_item_holds_object_lock_and_reports_busy(vault, monkeypatch):
    row = _ingest_one(monkeypatch)
    names = []
    real = storage.file_lock

    def spy(name, wait_s=0, **kw):
        names.append((name, wait_s))
        return real(name, wait_s, **kw)

    monkeypatch.setattr(storage, "file_lock", spy)
    out = remove.delete_items([row["item_id"]])
    assert out["deleted"] == 1
    assert (storage.obj_lock_name(row["item_id"]), 30) in names

    def busy(name, wait_s=0, **kw):
        raise storage.LockBusy(name, {"owner": "ingest"})

    monkeypatch.setattr(storage, "file_lock", busy)
    conn = index_mod.connect()
    try:
        res = remove._one(remove.delete_item, conn, "xhs-nobody")
    finally:
        conn.close()
    assert res["status"] == "failed" and "别的任务" in res["error"]


def test_raw_health_and_doctor_row(vault):
    assert storage.raw_health() == {"objects_with_incomplete_versions": 0, "stale_staging_dirs": 0}
    half = _raw(vault) / "v0003"
    half.mkdir(parents=True)
    stale = _raw(vault) / (storage.STAGING_PREFIX + "old")
    stale.mkdir()
    past = time.time() - storage.STAGING_STALE_S - 60
    os.utime(stale, (past, past))
    (_raw(vault) / (storage.STAGING_PREFIX + "fresh")).mkdir()
    assert storage.raw_health() == {"objects_with_incomplete_versions": 1, "stale_staging_dirs": 1}
    rows = {r["id"]: r for r in doctor.diagnose(only="local")["checks"]}
    assert rows["raw"]["state"] == "notice" and rows["raw"]["optional"] is True
    assert "1 篇" in rows["raw"]["message"] and "1 个" in rows["raw"]["message"]
    half.rmdir()
    shutil.rmtree(stale)
    rows = {r["id"]: r for r in doctor.diagnose(only="local")["checks"]}
    assert rows["raw"]["state"] == "ready"


def test_backfill_holds_object_lock_and_reports_busy(vault, monkeypatch):
    row = _ingest_one(monkeypatch)
    names = []
    real = storage.file_lock

    def spy(name, wait_s=0, **kw):
        names.append((name, wait_s))
        return real(name, wait_s, **kw)

    monkeypatch.setattr(storage, "file_lock", spy)
    monkeypatch.setattr(xhs, "_video", lambda note: {})
    assert videos.backfill(row)["status"] == "missing_url"
    assert (storage.obj_lock_name(row["item_id"]), 30) in names
    monkeypatch.setattr(storage, "file_lock", lambda name, wait_s=0, **kw: (_ for _ in ()).throw(storage.LockBusy(name, {"owner": "remove"})))
    out = videos.backfill(row)
    assert out["status"] == "busy" and "别的任务" in out["error"] and row["item_id"] not in out["error"]


def test_delete_busy_reason_hides_lock_name(vault, monkeypatch):
    monkeypatch.setattr(storage, "file_lock", lambda name, wait_s=0, **kw: (_ for _ in ()).throw(storage.LockBusy(name, {"owner": "obj-xhs-1"})))
    conn = index_mod.connect()
    try:
        res = remove._one(remove.delete_item, conn, "xhs-nobody")
    finally:
        conn.close()
    assert res["status"] == "failed" and "obj-" not in res["error"] and "别的任务" in res["error"]
