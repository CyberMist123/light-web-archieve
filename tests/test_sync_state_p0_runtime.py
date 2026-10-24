"""1024 第 1 波 p0-runtime：sync-status.json 读改写加锁；判活走 storage.pid_state 并核 pid 复用。"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from link_brain import procs, storage, sync_state

REPO = Path(__file__).resolve().parents[1]

# 另一个进程：拿着 sync-status 锁读状态，停一会儿再把自己改过的版本写回去（读改写的另一方）。
_WRITER = textwrap.dedent("""
    import time
    from link_brain import storage, sync_state
    with storage.file_lock("sync-status", wait_s=10):
        st = storage.read_json(sync_state.path())
        print("READY", flush=True)
        time.sleep(1.5)
        storage.write_json(sync_state.path(), {**st, "last_favorites": 123})
""")


def test_record_waits_for_other_writer_and_keeps_both_changes(monkeypatch):
    # conftest 把 path 换到了 tmp 根；另一个进程看不到这个替换，两边都用真路径（vault 已隔离进 tmp）
    monkeypatch.setattr(sync_state, "path", lambda: storage.archive_root() / "sync-status.json")
    storage.write_json(sync_state.path(), {"state": "ready", "message": "旧"})
    proc = subprocess.Popen([sys.executable, "-c", _WRITER], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=str(REPO), env={**os.environ, "PYTHONPATH": str(REPO)})
    try:
        assert proc.stdout.readline().strip() == "READY", proc.stderr.read()
        sync_state.record("failed", message="同步没做完")
    finally:
        proc.wait(timeout=30)
    st = storage.read_json(sync_state.path())
    assert st["state"] == "failed", "我写的结果被另一方拿旧内容覆盖了"
    assert st.get("last_favorites") == 123, "另一方写的字段被我拿旧内容覆盖了"


def test_alive_delegates_to_storage_pid_state(monkeypatch):
    monkeypatch.setattr(storage, "pid_state", lambda pid: "dead")
    storage.write_json(sync_state.path(), {"state": "running", "pid": os.getpid()})
    assert sync_state.load()["code"] == "INTERRUPTED"
    monkeypatch.setattr(storage, "pid_state", lambda pid: "unknown")  # 拒绝访问：查不清不当死
    assert sync_state.load()["state"] == "running"


def test_reused_pid_counts_as_dead(monkeypatch):
    monkeypatch.setattr(procs, "created_of", lambda pid, table=None: 1000.0)
    storage.write_json(sync_state.path(), {"state": "running", "pid": os.getpid(), "pid_created": 5000.0})
    assert sync_state.load()["code"] == "INTERRUPTED", "pid 被别的进程复用了，不能当同步还在跑"
    storage.write_json(sync_state.path(), {"state": "running", "pid": os.getpid(), "pid_created": 1000.0})
    assert sync_state.load()["state"] == "running"


def test_running_record_stores_creation_time(monkeypatch):
    monkeypatch.setattr(procs, "created_of", lambda pid, table=None: 4242.0)
    st = sync_state.record("running", message="正在同步收藏")
    assert st["pid"] == os.getpid() and st["pid_created"] == 4242.0
    assert sync_state.load()["state"] == "running"
