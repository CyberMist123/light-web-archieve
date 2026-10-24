"""1024 第 1 波 p0-meta：写 meta / 可见笔记时不丢她的数据。

- 完整重抓 / 续读都走 ingest.merge_meta：抓取管不着的字段（project、visible_note_pinned、兜底标题…）一律保留；
- meta.json 的读改写走 storage.update_json（单篇锁 obj-<item_id> → 重读 → 改 → 原子写）；
- 原子写的「原地覆写」退路只给派生文件，真相文件写不上就抛错；
- FileLock 同进程不同线程也互斥；
- render 默认不识图，手动导入不现场识图（只标 enrich 待办）。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from link_brain import enrich, ingest, render, storage
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"


def _fixture(desc_suffix: str = ""):
    text = FIXTURE.read_text(encoding="utf-8")
    if desc_suffix:  # 正文变了 → 规范化比对有变化 → 完整重建 meta、写新 RAW 版本
        text = text.replace("第一行正文。", "第一行正文。" + desc_suffix, 1)
    return json.loads(text)


def _parsed(text="https://example.invalid/share"):
    return {"note_id": NOTE_ID, "xsec_token": "FAKE_TOKEN",
            "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
            "input_url": text, "input_kind": "url", "resolved_url": text}


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _parsed(text))
    return tmp_path


def _meta_path():
    return storage.object_dir(xhs.SOURCE, NOTE_ID) / "meta.json"


# ---------------------------------------------------------------- 1. 重抓不丢字段

def test_full_refetch_keeps_fields_fetch_does_not_own(vault, monkeypatch):
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _fixture())
    ingest.ingest_url("https://example.invalid/share", origin="cli", ingest_kind="favorite")

    meta = storage.read_json(_meta_path())
    meta.update(project="写论文", visible_note_pinned=True, visible_note="她改过的名字.md", note="她的备注")
    storage.write_json(_meta_path(), meta)

    def fetch_changed(*a, **k):
        # 抓取进行中（最长 1500 秒）别的入口往 meta 里加了一个键：写回时不许被旧副本盖掉
        m = storage.read_json(_meta_path())
        m["favorited_by"] = [{"nickname": "a", "user_id": "u1", "first_seen": "2026-10-24T00:00:00+08:00"}]
        storage.write_json(_meta_path(), m)
        return _fixture("改过的正文")

    monkeypatch.setattr(xhs, "fetch_detail", fetch_changed)
    out = ingest.ingest_url("https://example.invalid/share", refresh=True, origin="tg", actor="ai:x",
                            ingest_kind="shared")
    assert out["version"] == 2

    after = storage.read_json(_meta_path())
    assert after["current_version"] == 2 and after["versions"] == [1, 2]
    assert after["project"] == "写论文"
    assert after["visible_note_pinned"] is True
    assert after["visible_note"] == "她改过的名字.md"
    assert after["note"] == "她的备注"
    assert after["ingest_kind"] == "favorite"  # 第一次怎么进来的，不被重抓覆盖（FORMAT.md）
    assert after["origin"] == "cli" and after["actor"] == "human"
    assert after["favorited_by"][0]["user_id"] == "u1"


def test_merge_meta_fetch_owned_fields_win_and_others_kept():
    old = {"item_id": "xhs-1", "title": "兜底标题", "project": "p", "visible_note_pinned": True,
           "ingest_kind": "favorite", "origin": "cli", "actor": "human", "current_version": 1,
           "images_complete": False, "first_archived_at": "2026-01-01", "custom": {"x": 1}}
    fetched = {"item_id": "xhs-1", "title": "", "current_version": 2, "images_complete": True,
               "ingest_kind": "shared", "origin": "tg", "actor": "ai:x", "visible_note": None,
               "first_archived_at": "2026-10-24", "last_checked_at": "2026-10-24"}
    merged = ingest.merge_meta(old, fetched)
    assert ingest.merge_meta({**old, "visible_note": "她的.md"}, fetched)["visible_note"] == "她的.md"
    assert merged["current_version"] == 2 and merged["images_complete"] is True
    assert merged["last_checked_at"] == "2026-10-24"
    assert merged["title"] == "兜底标题"  # 抓回来没标题：沿用 render 生成的兜底标题
    assert merged["project"] == "p" and merged["visible_note_pinned"] is True and merged["custom"] == {"x": 1}
    assert (merged["ingest_kind"], merged["origin"], merged["actor"]) == ("favorite", "cli", "human")
    assert merged["first_archived_at"] == "2026-01-01"
    assert merged.get("visible_note") is None  # 抓取不决定可见笔记的位置
    # 第一次入库（没有旧 meta）：抓取给的全收
    assert ingest.merge_meta({}, fetched)["ingest_kind"] == "shared"
    assert ingest.merge_meta(None, fetched)["visible_note"] is None


def test_merge_meta_title_from_fetch_wins_when_present():
    merged = ingest.merge_meta({"title": "旧"}, {"title": "新"})
    assert merged["title"] == "新"


# ---------------------------------------------------------------- 2. 读改写加锁

def test_update_json_two_threads_different_keys_both_survive(vault):
    path = vault / "_archive" / "xiaohongshu" / "n1" / "meta.json"
    storage.write_json(path, {"item_id": "xhs-n1"})
    errors = []

    def writer(key):
        try:
            for i in range(5):
                def fn(data, i=i):
                    time.sleep(0.01)  # 拉长读改写窗口：没锁时两边一定互相盖
                    data[f"{key}{i}"] = i
                storage.update_json(path, fn, lock_name="obj-xhs-n1")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(k,)) for k in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    data = storage.read_json(path)
    for key in ("a", "b"):
        for i in range(5):
            assert data[f"{key}{i}"] == i


def test_update_json_missing_file_raises_unless_missing_ok(vault):
    path = vault / "x" / "meta.json"
    with pytest.raises(FileNotFoundError):
        storage.update_json(path, lambda d: d.update(a=1), lock_name="obj-x")
    assert not path.exists()
    storage.update_json(path, lambda d: d.update(a=1), lock_name="obj-x", missing_ok=True)
    assert storage.read_json(path) == {"a": 1}


def test_update_json_no_change_does_not_write(vault, monkeypatch):
    path = vault / "m.json"
    storage.write_json(path, {"a": 1})
    calls = []
    monkeypatch.setattr(storage, "write_json", lambda *a, **k: calls.append(a))
    storage.update_json(path, lambda d: None, lock_name="obj-m")
    assert calls == []


def test_render_does_not_clobber_keys_written_during_render(vault, monkeypatch):
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _fixture())
    ingest.ingest_url("https://example.invalid/share")
    from link_brain import llm as llm_mod
    real = llm_mod.load_extracted

    def sneaky(*a, **k):
        # render 读完 meta 之后、写回之前，收藏同步给这篇记了账号
        m = storage.read_json(_meta_path())
        m["favorited_by"] = [{"nickname": "a", "user_id": "u1", "first_seen": "t"}]
        m["visible_note"] = None  # 逼 render 写回 visible_note
        storage.write_json(_meta_path(), m)
        return real(*a, **k)

    monkeypatch.setattr(render.llm_mod, "load_extracted", sneaky)
    render.render_object(xhs.SOURCE, NOTE_ID)
    after = storage.read_json(_meta_path())
    assert after["favorited_by"][0]["user_id"] == "u1"
    assert after["visible_note"]


def test_tag_account_goes_through_update_json(vault, monkeypatch):
    from link_brain import favorites
    path = _meta_path()
    storage.write_json(path, {"item_id": f"xhs-{NOTE_ID}"})
    seen = []
    real = storage.update_json
    monkeypatch.setattr(storage, "update_json", lambda *a, **k: (seen.append(k.get("lock_name")), real(*a, **k))[1])
    assert favorites.tag_account(NOTE_ID, {"user_id": "u1", "nickname": "a"}) is True
    assert favorites.tag_account(NOTE_ID, {"user_id": "u1", "nickname": "a"}) is False
    assert seen == [f"obj-xhs-{NOTE_ID}"] * 2
    assert len(storage.read_json(path)["favorited_by"]) == 1
    # 没归档过的篇：不凭空造一份只有 favorited_by 的 meta
    assert favorites.tag_account("nope", {"user_id": "u1"}) is False
    assert not (storage.object_dir(xhs.SOURCE, "nope") / "meta.json").exists()


# ---------------------------------------------------------------- 3. 原子写退路只给派生文件

def _deny_replace(monkeypatch):
    monkeypatch.setattr(storage.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "拒绝访问")))
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)


def test_truth_file_atomic_write_failure_raises_and_keeps_old(tmp_path, monkeypatch):
    obj = tmp_path / "_archive" / "xiaohongshu" / "n1"
    obj.mkdir(parents=True)
    for name in ("meta.json", "notes.json"):
        (obj / name).write_text('{"old": true}', encoding="utf-8")
    _deny_replace(monkeypatch)
    for name in ("meta.json", "notes.json"):
        with pytest.raises(PermissionError):
            storage.write_json(obj / name, {"new": True})
        assert (obj / name).read_text(encoding="utf-8") == '{"old": true}'
    assert sorted(p.name for p in obj.iterdir()) == ["meta.json", "notes.json"]


def test_derived_files_still_fall_back_in_place(tmp_path, monkeypatch):
    archive = tmp_path / "_archive"
    (archive / "xiaohongshu" / "n1" / "derived").mkdir(parents=True)
    targets = [tmp_path / "收藏" / "某篇.md", archive / "catalog-data.json",
               archive / "xiaohongshu" / "n1" / "derived" / "agent.md"]
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text("old content", encoding="utf-8")
    _deny_replace(monkeypatch)
    for t in targets:
        storage.atomic_write_text(t, "新")
        assert t.read_text(encoding="utf-8") == "新"


def test_in_place_fallback_whitelist():
    ok = storage.in_place_fallback_ok
    assert ok(Path("v/收藏/a.md")) and ok(Path("v/_archive/catalog-data.json"))
    assert ok(Path("v/_archive/xiaohongshu/n/derived/vision.json"))
    assert not ok(Path("v/_archive/xiaohongshu/n/meta.json"))
    assert not ok(Path("v/_archive/xiaohongshu/n/notes.json"))
    assert not ok(Path("v/_archive/xiaohongshu/n/raw/v0001/source.json"))
    assert not ok(Path("v/_archive/albums.json"))


# ---------------------------------------------------------------- 4. FileLock 线程间互斥

def test_file_lock_is_exclusive_between_threads_of_one_process(tmp_path):
    lock_path = tmp_path / "t.lock"
    held = threading.Event()
    release = threading.Event()

    def holder():
        with storage.FileLock(lock_path, name="t").hold("A"):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(5)
    try:
        with pytest.raises(storage.LockBusy):
            with storage.FileLock(lock_path, name="t").hold("B", wait_s=0):
                pass
    finally:
        release.set()
        t.join()
    # A 放了之后 B 能拿到；同一线程照旧可重入；计数不出负数
    lock = storage.FileLock(lock_path, name="t")
    with lock.hold("B", wait_s=1):
        with lock.hold("B"):
            assert lock_path.exists()
        assert lock_path.exists()
    assert not lock_path.exists()
    assert lock.state()["count"] == 0


def test_file_lock_threads_serialize_with_wait(tmp_path):
    lock_path = tmp_path / "s.lock"
    inside = []
    overlap = []

    def work(tag):
        with storage.FileLock(lock_path, name="s", poll_s=0.01).hold(tag, wait_s=10):
            if inside:
                overlap.append(tag)
            inside.append(tag)
            time.sleep(0.05)
            inside.remove(tag)

    threads = [threading.Thread(target=work, args=(str(i),)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap == []
    assert storage.FileLock(lock_path, name="s").state()["count"] == 0


# ---------------------------------------------------------------- 5. 默认不识图

def test_render_cli_default_does_not_call_vision(vault, monkeypatch):
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _fixture())
    ingest.ingest_url("https://example.invalid/share")
    calls = []
    monkeypatch.setattr(render.vision_mod, "build_vision", lambda *a, **k: calls.append(a))
    assert render.run(SimpleNamespace(all=False, target=f"xhs-{NOTE_ID}", verbose=False,
                                      extract=False, re_extract=False)) == 0
    assert calls == []
    # 显式 --vision 才跑
    render.run(SimpleNamespace(all=False, target=f"xhs-{NOTE_ID}", verbose=False,
                               extract=False, re_extract=False, vision=True))
    assert len(calls) == 1


def test_manual_ingest_does_not_run_vision_but_marks_enrich_pending(vault, monkeypatch):
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _fixture())
    calls = []
    monkeypatch.setattr(render.vision_mod, "build_vision", lambda *a, **k: calls.append(a))
    args = SimpleNamespace(target="https://example.invalid/share", origin="cli", actor="human",
                           ingest_kind="shared", note=None, verbose=False, refresh=False)
    assert ingest.run(args) in (0, 2)  # 测试里图片下不来 = 缺内容 gate 退 2，和识图无关
    assert calls == []
    assert enrich.load_state(xhs.SOURCE, NOTE_ID).get("pending") is True
    meta = storage.read_json(_meta_path())
    assert meta["visible_note"] and (vault / meta["visible_note"]).exists()  # 可见笔记照样写出来
