"""1024 第一波返修：append-only jsonl 末尾 / 中间截在多字节字符中间时，只丢那一行，别的行照读。

复审 tomb#1（index.py 读 tombstones.jsonl）、runtime#1（problems.py 读 problems.jsonl）各自发现：
整份按 utf-8 解码，一个半截汉字就让整份读不出来。统一走 storage.read_jsonl。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from link_brain import actionlog, alert as alert_mod, index, posttags, problems, storage, synclog, usage

TZ = timezone(timedelta(hours=10))


def _half_cn_line(obj: dict) -> bytes:
    """一行 JSON 截在一个中文字的 3 个字节中间（写到一半断电）。"""
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    cut = raw.index("中".encode("utf-8")) + 1
    return raw[:cut]


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_mod, "_alert", lambda kind, title, body, **extra: sent.append((kind, title, body)) or True)
    return sent


# ---------------------------------------------------------------- storage.read_jsonl


def test_read_jsonl_skips_line_cut_in_multibyte_and_counts_it(tmp_path):
    p = tmp_path / "x.jsonl"
    good1 = json.dumps({"a": "好"}, ensure_ascii=False).encode()
    good2 = json.dumps({"b": "行"}, ensure_ascii=False).encode()
    p.write_bytes(good1 + b"\n" + _half_cn_line({"t": "中文"}) + b"\n" + b"{not json\n" + good2 + b"\n"
                  + _half_cn_line({"t": "中文"}))
    rows, bad = storage.read_jsonl(p)
    assert rows == [{"a": "好"}, {"b": "行"}]
    assert bad == 3


def test_read_jsonl_missing_file_is_empty(tmp_path):
    assert storage.read_jsonl(tmp_path / "nope.jsonl") == ([], 0)


# ---------------------------------------------------------------- tombstones


def test_connect_survives_tombstones_cut_in_multibyte():
    conn = index.connect()
    index.write_tombstone(conn, {"item_id": "xhs-t1", "source": "xhs", "source_id": "t1", "title": "好帖"})
    path = index.tombstones_path(conn)
    conn.close()
    with path.open("ab") as fh:
        fh.write(_half_cn_line({"op": "delete", "source": "xhs", "source_id": "t2", "title": "中文标题"}))
    conn = index.connect()  # 修前：UnicodeDecodeError，所有命令起不来
    try:
        assert {r["source_id"] for r in conn.execute("SELECT source_id FROM tombstones")} == {"t1"}
    finally:
        conn.close()


# ---------------------------------------------------------------- problems


def _cut_problems_tail():
    p = problems.path()
    with p.open("ab") as fh:
        fh.write(_half_cn_line({"ts": "2026-10-01T03:00:00+10:00", "key": "x||Y", "reason": "中断"}))


def test_problems_push_after_tail_cut_in_multibyte(pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 1, 4, tzinfo=TZ))
    _cut_problems_tail()
    problems.report("login", "NEEDS_HUMAN.NOT_LOGGED_IN", "掉登录",
                    _now_fn=lambda: datetime(2026, 10, 1, 5, tzinfo=TZ))
    assert len(pushes) == 1, "主文件末尾半个汉字不能让要人处理的事永久不推"
    keys = {r["key"] for r in problems.load()}
    assert {"embed||NETWORK", "login||NOT_LOGGED_IN"} <= keys


def test_problems_merge_pending_after_tail_cut_in_multibyte(pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 1, 4, tzinfo=TZ))
    _cut_problems_tail()
    problems.pending_dir().mkdir(parents=True, exist_ok=True)
    side = {"ts": "2026-10-01T04:30:00+10:00", "key": "ocr|xhs-s|NETWORK", "step": "ocr", "item_id": "xhs-s",
            "code": "TRANSIENT.NETWORK", "reason": "旁路", "count": 1, "resolved_at": None}
    (problems.pending_dir() / "1-1-1.jsonl").write_text(json.dumps(side, ensure_ascii=False) + "\n", "utf-8")
    # 修前：并回旁路时严格读主文件抛 UnicodeDecodeError，直接抛到调用方，这一行和旁路都丢
    row = problems.report("asr", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 1, 5, tzinfo=TZ))
    assert row["written"]
    keys = {r["key"] for r in problems._read_rows()}
    assert {"embed||NETWORK", "ocr|xhs-s|NETWORK", "asr||NETWORK"} <= keys
    assert not list(problems.pending_dir().glob("*.jsonl"))
    assert problems.resolve("asr") == 1


# ---------------------------------------------------------------- 其余 append-only 账本


def test_actionlog_read_after_cut_in_multibyte():
    actionlog.record("save", ok=True, item="a")
    with actionlog.path().open("ab") as fh:
        fh.write(_half_cn_line({"action": "save", "item": "中"}) + b"\n")
    actionlog.record("save", ok=True, item="b")
    assert [r["item"] for r in actionlog.read()] == ["a", "b"]
    assert [r["item"] for r in actionlog.read(limit=1)] == ["b"]


def test_synclog_read_after_cut_in_multibyte_keeps_other_runs():
    p = synclog.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(json.dumps({"run_id": "r1", "note": "好"}, ensure_ascii=False).encode() + b"\n"
                  + _half_cn_line({"run_id": "r2", "note": "中文"}) + b"\n"
                  + json.dumps({"run_id": "r3"}).encode() + b"\n")
    # 修前：整份 UnicodeError → []，下一次 _edit 拿 [] 整份写回，同步记录被清空
    assert [r["run_id"] for r in synclog._read()] == ["r1", "r3"]


def test_posttags_history_after_cut_in_multibyte():
    p = posttags.history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(json.dumps({"item": "xhs-1", "who": "ai"}).encode() + b"\n"
                  + _half_cn_line({"item": "xhs-2", "after": "中文"}) + b"\n")
    assert [r["item"] for r in posttags.history()] == ["xhs-1"]


def test_usage_load_after_cut_in_multibyte():
    now = datetime.now().astimezone()
    d = usage._dir()
    d.mkdir(parents=True, exist_ok=True)
    good = json.dumps({"ts": now.isoformat(), "model": "m"}).encode()
    (d / f"{now:%Y-%m}.jsonl").write_bytes(good + b"\n" + _half_cn_line({"ts": now.isoformat(), "x": "中文"}) + b"\n")
    rows = usage.load(now=now)
    assert [r["model"] for r in rows] == ["m"]


# ---------------------------------------------------------------- runtime#2：主文件一时打不开，新行退到旁路


def _side_row():
    problems.pending_dir().mkdir(parents=True, exist_ok=True)
    side = {"ts": "2026-10-01T04:30:00+10:00", "key": "ocr|xhs-s|NETWORK", "step": "ocr", "item_id": "xhs-s",
            "code": "TRANSIENT.NETWORK", "reason": "旁路", "count": 1, "resolved_at": None}
    (problems.pending_dir() / "1-1-1.jsonl").write_text(json.dumps(side, ensure_ascii=False) + "\n", "utf-8")


def test_problems_row_kept_when_main_file_unreadable_with_pending(monkeypatch, pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 1, 4, tzinfo=TZ))
    _side_row()
    cls = type(problems.path())
    real_b, real_t = cls.read_bytes, cls.read_text

    def busy(real):
        def f(self, *a, **k):
            if self.name == problems.FILE_NAME:
                raise PermissionError(32, "另一个程序正在使用此文件")
            return real(self, *a, **k)
        return f

    monkeypatch.setattr(cls, "read_bytes", busy(real_b))
    monkeypatch.setattr(cls, "read_text", busy(real_t))
    row = problems.report("asr", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 1, 5, tzinfo=TZ))
    assert row["written"], "修前：并回旁路时读主文件抛 OSError，这一行丢了"
    monkeypatch.setattr(cls, "read_bytes", real_b)
    monkeypatch.setattr(cls, "read_text", real_t)
    keys = {r["key"] for r in problems._read_rows()}
    assert {"embed||NETWORK", "ocr|xhs-s|NETWORK", "asr||NETWORK"} <= keys


def test_problems_row_goes_to_pending_when_main_file_unwritable(monkeypatch, pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 1, 4, tzinfo=TZ))

    def busy(p, blob):
        raise PermissionError(32, "另一个程序正在使用此文件")

    real_append = problems._append_text
    monkeypatch.setattr(problems, "_append_text", busy)
    row = problems.report("asr", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 1, 5, tzinfo=TZ))
    assert row["written"]
    assert list(problems.pending_dir().glob("*.jsonl")), "写不了主文件就退到旁路"
    monkeypatch.setattr(problems, "_append_text", real_append)
    problems.compact()
    assert "asr||NETWORK" in problems.path().read_text("utf-8")
