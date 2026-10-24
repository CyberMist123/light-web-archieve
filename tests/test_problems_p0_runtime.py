"""1024 第 1 波 p0-runtime：问题记录不丢行、不粘行、读不出来不推送；压实留余量。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from link_brain import actionlog, alert as alert_mod, problems, storage

TZ = timezone(timedelta(hours=10))
REPO = Path(__file__).resolve().parents[1]


def at(day: int, hour: int = 4):
    return lambda: datetime(2026, 10, day, hour, 0, tzinfo=TZ)


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_mod, "_alert", lambda kind, title, body, **extra: sent.append((kind, title, body, extra)) or True)
    return sent


# 另一个进程：拿着 problems 锁读完整份记录，等主进程追加完，再按自己读到的内容压实写回（atomic），然后放锁。
_COMPACTOR = textwrap.dedent("""
    import sys
    from link_brain import problems, storage
    with storage.file_lock("problems", wait_s=10):
        rows = problems._read_rows()
        print("READY", flush=True)
        sys.stdin.readline()
        storage.atomic_write_text(problems.path(), "".join(
            __import__("json").dumps(r, ensure_ascii=False) + "\\n" for r in rows))
    print("DONE", flush=True)
""")


def test_append_while_other_process_compacts_does_not_lose_row(monkeypatch, pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网 a", item_id="xhs-a", _now_fn=at(1))
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen([sys.executable, "-c", _COMPACTOR], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=str(REPO), env=env)
    try:
        assert proc.stdout.readline().strip() == "READY", proc.stderr.read()
        monkeypatch.setattr(problems, "LOCK_WAIT_S", 0.3, raising=False)
        problems.report("embed", "TRANSIENT.NETWORK", "断网 b", item_id="xhs-b", _now_fn=at(1, 5))
        proc.stdin.write("go\n")
        proc.stdin.flush()
        assert proc.stdout.readline().strip() == "DONE"
    finally:
        proc.wait(timeout=30)
    keys = {r["key"] for r in problems.load()}
    assert "embed|xhs-b|NETWORK" in keys, "等不到锁时写的那行被别人的压实冲掉了"
    # 下一个拿到锁的人把旁路并回主文件
    problems.report("embed", "TRANSIENT.NETWORK", "断网 c", item_id="xhs-c", _now_fn=at(1, 6))
    main = problems.path().read_text("utf-8")
    assert "xhs-b" in main and "xhs-c" in main
    assert not list(problems.pending_dir().glob("*.jsonl"))


def test_pending_rows_fold_in_time_order(pushes):
    """旁路里的 report 比主文件里后来的 resolve 早：并回后仍是已解决。"""
    problems.pending_dir().mkdir(parents=True, exist_ok=True)
    early = {"ts": "2026-10-01T04:00:00+10:00", "key": "embed||NETWORK", "step": "embed", "item_id": None,
             "code": "TRANSIENT.NETWORK", "reason": "x", "count": 1, "resolved_at": None}
    (problems.pending_dir() / "1-1-1.jsonl").write_text(json.dumps(early) + "\n", "utf-8")
    problems.path().write_text(json.dumps({**early, "ts": "2026-10-01T05:00:00+10:00",
                                           "resolved_at": "2026-10-01T05:00:00+10:00", "count": 0}) + "\n", "utf-8")
    assert not [r for r in problems.load() if r["key"] == "embed||NETWORK"]
    problems.compact()
    assert not list(problems.pending_dir().glob("*.jsonl"))
    row = problems._fold(problems._read_rows())["embed||NETWORK"]
    assert row["resolved_at"]


def test_append_after_half_line_keeps_both_rows(pushes):
    first = problems.report("embed", "TRANSIENT.NETWORK", "断网", item_id="xhs-1", _now_fn=at(1))
    p = problems.path()
    p.write_bytes(p.read_bytes().rstrip(b"\r\n"))  # 上次写到行尾前被打断：没有换行
    problems.report("embed", "TRANSIENT.NETWORK", "断网", item_id="xhs-2", _now_fn=at(1, 5))
    keys = {r["key"] for r in problems._read_rows()}
    assert {first["key"], "embed|xhs-2|NETWORK"} <= keys


def test_actionlog_append_after_half_line_keeps_both_rows():
    actionlog.record("save", ok=True, item="a")
    p = actionlog.path()
    p.write_bytes(p.read_bytes().rstrip(b"\r\n"))
    actionlog.record("save", ok=True, item="b")
    assert [r["item"] for r in actionlog.read()] == ["a", "b"]


def test_report_does_not_push_when_record_unreadable(monkeypatch, pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(1))
    real = Path.read_bytes

    def flaky(self, *a, **k):
        if self.name == problems.FILE_NAME:
            raise PermissionError(13, "被占用")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", flaky)  # 1024 返修：问题记录改成按字节逐行读（storage.read_jsonl）
    row = problems.report("login", "NEEDS_HUMAN.NOT_LOGGED_IN", "掉登录", _now_fn=at(1, 5))
    assert pushes == [], "读不出来就不知道推没推过：不推，下次读得出来再判"
    assert not row.get("notified")
    monkeypatch.setattr(Path, "read_bytes", real)
    problems.report("login", "NEEDS_HUMAN.NOT_LOGGED_IN", "掉登录", _now_fn=at(1, 6))
    assert len(pushes) == 1, "读得出来之后照常推一次"


def test_compaction_leaves_headroom(monkeypatch, pushes):
    monkeypatch.setattr(problems, "MAX_KEYS", 20)
    monkeypatch.setattr(problems, "COMPACT_SLACK", 5, raising=False)
    writes = []
    real = storage.atomic_write_text
    monkeypatch.setattr(storage, "atomic_write_text",
                        lambda p, t: (writes.append(Path(p).name), real(p, t))[1])
    for i in range(26):
        problems.report("attachments.convert", "PERMANENT.PDF_DAMAGED", "坏", item_id=f"xhs-{i:03d}",
                        _now_fn=lambda i=i: datetime(2026, 10, 1, 0, i, tzinfo=TZ))
    assert writes.count(problems.FILE_NAME) == 1, "压实后留了余量，不该每登记一次就整份重写"
    assert len(problems.path().read_text("utf-8").splitlines()) == 20
