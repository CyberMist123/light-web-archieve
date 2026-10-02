"""第 0 批：storage.file_lock（CONVENTIONS §6.4）、临界区加锁、原子写收口（§6.5）。"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from link_brain import accounts, answer_cache, catalog, storage, favorites

REPO = Path(__file__).resolve().parents[1]

HOLDER = r"""
import sys, time
from link_brain import storage
with storage.file_lock(sys.argv[1], owner=sys.argv[2]):
    print("held", flush=True)
    time.sleep(float(sys.argv[3]))
"""


@contextlib.contextmanager
def other_process_holds(name, owner="夜跑", seconds=30):
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, name, owner, str(seconds)], stdout=subprocess.PIPE,
                            text=True, env=env)
    try:
        assert proc.stdout.readline().strip() == "held"
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_file_lock_is_exclusive_across_processes_reentrant_and_released():
    path = storage.locks_dir() / "demo.lock"
    with other_process_holds("demo"):
        with pytest.raises(storage.LockBusy) as exc:
            with storage.file_lock("demo", wait_s=0):
                pass
        assert exc.value.holder["owner"] == "夜跑" and "夜跑" in str(exc.value)
    # 持有进程被杀（没来得及放锁）= pid 死了 → 陈旧锁，可以接管
    with storage.file_lock("demo", owner="插件"):
        info = json.loads(path.read_text("utf-8"))
        assert info["pid"] == os.getpid() and info["owner"] == "插件" and info["heartbeat"]
        with storage.file_lock("demo"):  # 同进程可重入
            pass
        assert path.exists()
    assert not path.exists()


def test_file_lock_waits_for_release():
    with other_process_holds("demo-wait", seconds=1.5):
        t0 = time.monotonic()
        with storage.file_lock("demo-wait", wait_s=30):
            waited = time.monotonic() - t0
    assert 0.5 < waited < 20


def test_stale_heartbeat_is_taken_over_and_unknown_pid_with_fresh_heartbeat_is_not():
    path = storage.locks_dir() / "demo-stale.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = time.time()
    path.write_text(json.dumps({"pid": 424242, "owner": "x", "heartbeat_ts": fresh}), "utf-8")
    lock = storage.FileLock(path, pid_state_fn=lambda pid: "unknown")
    with pytest.raises(storage.LockBusy):
        with lock.hold("me", 0):
            pass
    path.write_text(json.dumps({"pid": 424242, "owner": "x", "heartbeat_ts": fresh - 11 * 60}), "utf-8")
    with lock.hold("me", 0):
        assert json.loads(path.read_text("utf-8"))["owner"] == "me"


def test_locked_decorator_and_heartbeat_marks_lost_when_taken_over():
    calls = []

    @storage.locked("demo-deco", wait_s=0)
    def work(x):
        calls.append(x)
        return x * 2

    assert work(3) == 6 and calls == [3]
    lock = storage.FileLock(storage.locks_dir() / "demo-lost.lock", heartbeat_s=0.05)
    with lock.hold("me", 0):
        lock.path.write_text(json.dumps({"pid": 1, "owner": "别人", "heartbeat_ts": time.time()}), "utf-8")
        deadline = time.monotonic() + 5
        while not lock.lost and time.monotonic() < deadline:
            time.sleep(0.05)
        assert lock.lost
    assert lock.path.exists(), "被别人接管的锁不删"


def test_catalog_build_runs_inside_the_catalog_lock(monkeypatch):
    seen = {}
    real_collect = catalog.collect

    def collect(vault, source="xiaohongshu"):
        info = json.loads((storage.locks_dir() / "catalog-build.lock").read_text("utf-8"))
        seen["pid"] = info["pid"]
        return real_collect(vault, source)

    monkeypatch.setattr(catalog, "collect", collect)
    catalog.build()
    assert seen["pid"] == os.getpid()
    assert not (storage.locks_dir() / "catalog-build.lock").exists()


def test_catalog_build_waits_for_another_build():
    with other_process_holds("catalog-build", owner="link_brain.catalog.build", seconds=1.0):
        t0 = time.monotonic()
        catalog.build()
    assert time.monotonic() - t0 > 0.3


def test_account_lock_is_an_instance_of_file_lock():
    assert isinstance(accounts._account_lock(), storage.FileLock)
    assert accounts._account_lock().path == accounts.lock_path()
    with accounts.account_session("catch"):
        assert accounts.lock_holder() is None  # 本进程自己的不算「别人占着」
        assert not accounts.lock_lost()


def test_answer_cache_record_is_locked_and_atomic(monkeypatch):
    seen = []
    real = storage.file_lock

    def spy(name, *a, **k):
        seen.append(name)
        return real(name, *a, **k)

    monkeypatch.setattr(storage, "file_lock", spy)
    entry = answer_cache.record("问题", ["词"], [{"id": "xhs-1", "title": "t"}], "答案第一行")
    assert entry and seen == ["answers"]
    assert answer_cache.attach_export("问题", None, storage.vault_root() / "收藏导出" / "a.zip") is True
    assert seen == ["answers", "answers"]
    leftovers = [p.name for p in answer_cache.index_path().parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_answer_cache_fails_open_when_lock_busy():
    with other_process_holds("answers", seconds=30):
        t0 = time.monotonic()
        assert answer_cache.record("q", [], [], "a") is None  # 拿不到锁：静默放弃，不挡回答
        assert time.monotonic() - t0 < 30


def test_no_hand_rolled_atomic_writes_left():
    """§6.5：四处自写的「写 .tmp 再 os.replace」收进 storage.*。"""
    offenders = []
    for name in ("enrich.py", "topics.py", "answer_cache.py", "accounts.py"):
        text = (REPO / "link_brain" / name).read_text("utf-8")
        if "os.replace(tmp" in text or "mkstemp(" in text or ".tmp')" in text:
            offenders.append(name)
    assert offenders == []


def test_sync_quota_counts_across_writers():
    q1, q2 = favorites._Quota(), favorites._Quota()
    q1.add()
    q2.add()  # 另一个入口（插件白天点的同步）用的是自己内存里的旧数：在锁里以文件为准再 +1
    assert storage.read_json(storage.archive_root() / "sync-quota.json")["new"] == 2


def test_cli_reports_lock_busy_as_readable_stderr(monkeypatch, capsys):
    from link_brain import cli

    monkeypatch.setattr(catalog, "build", storage.locked("catalog-build", wait_s=0)(catalog.build.__wrapped__))
    with other_process_holds("catalog-build", owner="夜跑重建目录"):
        assert cli.main(["catalog"]) == 1
    assert capsys.readouterr().err.strip().splitlines()[-1] == "没跑完：「catalog-build」正被「夜跑重建目录」占用，稍后再试"
