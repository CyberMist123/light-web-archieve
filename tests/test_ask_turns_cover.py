"""ask_turns 的补充用例：轮次登记表落在 tmp 家目录（LINK_BRAIN_HOME + LINK_BRAIN_ASK_TURNS 都指 tmp_path），
latest_for_who 用固定带时区的 now 钉窗口边界；坏 JSON / 坏时间戳按 fail-open 盖。不碰真库、不起进程。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from link_brain import ask_turns as at
from link_brain import storage

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone(timedelta(hours=11)))


def _use(tmp_path, monkeypatch):
    f = tmp_path / "ask-turns.json"
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(f))
    return f


def _write(f, turns):
    f.write_text(json.dumps({"turns": turns}, ensure_ascii=False), encoding="utf-8")


def _ts(dt):
    return dt.isoformat(timespec="seconds")


def test_path_env_override(tmp_path, monkeypatch):
    monkeypatch.delenv("LINK_BRAIN_ASK_TURNS", raising=False)
    assert at.path() == storage.archive_root() / "ask-turns.json"      # 默认在 _archive 下
    f = _use(tmp_path, monkeypatch)
    assert at.path() == f                                               # 环境变量优先（评测 / 测试用）


def test_get_failopen_on_bad_shapes(tmp_path, monkeypatch):
    f = _use(tmp_path, monkeypatch)
    f.write_text("{oops", encoding="utf-8")                             # 坏 JSON → 当没有表
    assert at.get("t1") is None
    f.write_text(json.dumps({"turns": [1, 2]}), encoding="utf-8")       # turns 不是 dict → 当没有表
    assert at.get("t1") is None
    f.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")    # 顶层不是 dict → 当没有表
    assert at.get("t1") is None
    _write(f, {"t1": {"q": "问题"}, "t2": "不是字典"})
    assert at.get("t1") == {"q": "问题", "turn_id": "t1"}               # 命中时补 turn_id
    assert at.get("t2") is None                                         # 行不是字典不算一轮
    assert at.get("missing") is None
    assert at.get(123) is None and at.get("") is None                   # 非字符串 / 空 id 直接 None


def test_record_adds_ts_trims_and_fails_open(tmp_path, monkeypatch):
    f = _use(tmp_path, monkeypatch)
    assert at.record("t1", {"q": "问题", "who": "local"}) is True
    row = at.get("t1")
    assert row["q"] == "问题" and row["turn_id"] == "t1"
    assert datetime.fromisoformat(row["ts"])                             # record 自己补 ts（可解析）
    monkeypatch.setattr(at, "KEEP", 3)
    for i in range(2, 6):
        assert at.record(f"t{i}", {"q": f"q{i}"}) is True
    turns = json.loads(f.read_text(encoding="utf-8"))["turns"]
    assert sorted(turns) == ["t3", "t4", "t5"]                           # 超过 KEEP 丢最旧的
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path))            # 指到目录：写不进去
    assert at.record("tx", {"q": "x"}) is False                          # 登记失败不抛，返回 False


def test_latest_in_thread(tmp_path, monkeypatch):
    f = _use(tmp_path, monkeypatch)
    _write(f, {"a": {"thread_id": "th1", "ts": _ts(NOW - timedelta(minutes=10))},
               "b": {"thread_id": "th1", "ts": _ts(NOW - timedelta(minutes=2))},
               "c": {"thread_id": "th2", "ts": _ts(NOW)}})
    assert at.latest_in_thread("th1")["turn_id"] == "b"                  # 线内取 ts 最大的一轮
    assert at.latest_in_thread("th2")["turn_id"] == "c"
    assert at.latest_in_thread("nope") is None
    assert at.latest_in_thread(None) is None and at.latest_in_thread("") is None


def test_latest_for_who_window_and_credential(tmp_path, monkeypatch):
    f = _use(tmp_path, monkeypatch)
    _write(f, {
        "old":   {"who": "w1", "ts": _ts(NOW - timedelta(seconds=901))},
        "in1":   {"who": "w1", "ts": _ts(NOW - timedelta(seconds=500))},
        "in2":   {"who": "w1", "ts": _ts(NOW - timedelta(seconds=100))},
        "skew":  {"who": "w1", "ts": _ts(NOW + timedelta(seconds=30))},   # 快 30 秒的钟，仍在容忍窗内
        "toofar": {"who": "w3", "ts": _ts(NOW + timedelta(seconds=70))},  # 快超过 60 秒的不算
        "w3ok":  {"who": "w3", "ts": _ts(NOW - timedelta(seconds=10))},
        "other": {"who": "w2", "ts": _ts(NOW)},                           # 别的凭据绝不串
        "bad":   {"who": "w1", "ts": "not-a-ts"},                         # 坏时间戳跳过
    })
    assert at.latest_for_who("w1", now=NOW)["turn_id"] == "skew"          # 窗内取 ts 字符串最大的
    assert at.latest_for_who("w3", now=NOW)["turn_id"] == "w3ok"          # 未来超 60 秒的被丢
    assert at.latest_for_who("w2", now=NOW)["turn_id"] == "other"
    assert at.latest_for_who("nobody", now=NOW) is None
    assert at.latest_for_who(None, now=NOW) is None and at.latest_for_who("", now=NOW) is None
    assert at.latest_for_who("w1", within_s=200, now=NOW)["turn_id"] == "skew"   # 窗口收窄也不含 500 秒前那轮


def test_latest_for_matches_normalized_question(tmp_path, monkeypatch):
    f = _use(tmp_path, monkeypatch)
    _write(f, {"a": {"q": "hello   world", "ts": _ts(NOW - timedelta(minutes=1))},
               "b": {"q": "hello world", "ts": _ts(NOW)},                 # 空白归一后同一句
               "c": {"q": "别的", "ts": _ts(NOW)}})
    assert at.latest_for("hello world")["turn_id"] == "b"                 # 取最近的一轮
    assert at.latest_for("  hello \n world  ")["turn_id"] == "b"          # 提问原文也先归一空白
    assert at.latest_for("没有这句") is None
    assert at.latest_for("   ") is None and at.latest_for(None) is None


def test_id_formats():
    a, b = at.new_id(), at.new_id()
    assert a != b and a[0] == "t" and len(a) == 1 + 10 + 6              # t + 月日时分秒（10 位）+ 6 位 hex
    th1, th2 = at.new_thread_id(), at.new_thread_id()
    assert th1 != th2 and th1.startswith("th") and len(th1) == 2 + 8 + 8  # th + 月日时分 + 8 位 hex
