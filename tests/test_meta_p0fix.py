"""1024 第一波返修（复审 meta 中2 / 低）：索引.md 是她手写的真相，不进「原地覆写」退路；收藏账号没记上要吭声。"""

from __future__ import annotations

from pathlib import Path

from link_brain import indextree, storage


def test_index_md_is_not_in_place_fallback():
    ok = storage.in_place_fallback_ok
    assert not ok(Path("v/索引.md")), "修前：所有 .md 都放行，Obsidian 开着 索引.md 时被杀会留半截索引"
    assert ok(Path("v/收藏/a.md"))


def test_configured_index_file_is_not_in_place_fallback(monkeypatch):
    monkeypatch.setattr(indextree, "index_rel", lambda: "目录/我的索引.md")
    vault = storage.vault_root()
    assert not storage.in_place_fallback_ok(vault / "目录" / "我的索引.md")
    assert storage.in_place_fallback_ok(vault / "目录" / "别的.md")


def test_tag_account_lock_busy_says_so(monkeypatch, capsys):
    """meta 低：拿不到单篇锁时悄悄不记收藏账号——至少往 stderr 打一行。"""
    from link_brain import favorites
    obj = storage.object_dir("xiaohongshu", "n1")
    obj.mkdir(parents=True)
    storage.write_json(obj / "meta.json", {"item_id": "xhs-n1"})

    def busy(*a, **k):
        raise storage.LockBusy("obj-xhs-n1")

    monkeypatch.setattr(storage, "update_json", busy)
    assert favorites.tag_account("n1", {"user_id": "u1", "nickname": "x"}) is False
    assert "没记上" in capsys.readouterr().err


def test_thread_waiting_on_same_process_lock_gets_on_wait(tmp_path):
    """meta 低：同进程另一个线程拿着锁时，排队的一方也要收到一次 on_wait（插件据此显示「在等号」）。"""
    import threading
    lock_path = tmp_path / "t.lock"
    held, release = threading.Event(), threading.Event()

    def holder():
        with storage.file_lock("t", path=lock_path, owner="A"):
            held.set()
            release.wait(10)

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    assert held.wait(5)
    told = []
    threading.Timer(0.5, release.set).start()
    with storage.FileLock(lock_path, name="t").hold("B", wait_s=5, on_wait=lambda h, left: told.append(h)):
        pass
    t.join(5)
    assert len(told) == 1, "修前：卡在 mutex.acquire 上，走不到 on_wait"
