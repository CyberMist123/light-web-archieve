"""1017 楼中楼断点续展：续读把每楼存下的最后一条回复当游标交给读取组件；合并时新的接在旧的后面；额度用完不白开页。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from link_brain import comment_fill as cf
from link_brain.adapters import xiaohongshu as xhs

TZ = timezone(timedelta(hours=11))


def _reply(i: int, minute: int) -> dict:
    return {"comment_id": f"r{i:03d}", "text": f"回复{i}", "created_at": f"2026-10-01T10:{minute:02d}:00+11:00"}


def test_resume_points_uses_latest_reply_not_list_tail():
    # 置顶的首条回复时间晚、却排在最前；其余按时间正序。游标要取发得最晚的那条
    subs = [_reply(0, 59)] + [_reply(i, i) for i in range(1, 6)]
    subs.append({"comment_id": "r900", "text": "旧版接在后面的", "created_at": "2026-10-01T10:30:00+11:00"})
    source = {"comments": [
        {"comment_id": "f1", "sub_comment_count": 50, "sub_comments": subs},
        {"comment_id": "f2", "sub_comment_count": 9, "sub_comments": [_reply(1, 1)]},  # 只存 1 条：从头点
        {"comment_id": "f3", "sub_comment_count": 9, "sub_comments": [_reply(1, 1), _reply(2, 2)]},  # 不在目标里
    ]}
    assert cf.resume_points(source, ["f1", "f2"]) == ["f1:r000:7"]


def test_union_replies_appends_resumed_after_stored():
    prev = [_reply(i, i) for i in range(5)]
    cur = [_reply(0, 0), _reply(5, 5), _reply(6, 6)]  # 续展：首屏第 1 条 + 接着拉的
    out = xhs._union_replies(prev, cur)
    assert [s["comment_id"] for s in out] == [f"r{i:03d}" for i in range(7)]


def test_union_replies_from_scratch_keeps_page_order_and_old_extras():
    prev = [_reply(0, 0), _reply(2, 2), _reply(9, 9)]  # r009 这次没读到（删了）
    cur = [_reply(0, 0), _reply(1, 1), _reply(2, 2), _reply(3, 3)]
    out = [s["comment_id"] for s in xhs._union_replies(prev, cur)]
    assert out == ["r000", "r001", "r002", "r009", "r003"]  # 新的插在后面第一条已存的前面；后面没有就接末尾


def test_sub_quota_reads_reader_file(tmp_path, monkeypatch):
    from link_brain import accounts
    monkeypatch.setattr(accounts, "profile_dir", lambda: tmp_path)
    monkeypatch.delenv("XHS_SUB_PER_HOUR", raising=False)
    now = datetime(2026, 10, 17, 12, 0, tzinfo=TZ)
    clicks = [(now - timedelta(minutes=50) + timedelta(seconds=i)).isoformat() for i in range(30)]
    clicks.append((now - timedelta(hours=2)).isoformat())  # 一小时外的不算
    (tmp_path / "sub-expand.json").write_text(json.dumps({"clicks": clicks}), encoding="utf-8")
    left, free_at = cf.sub_quota(now)
    assert left == 0 and free_at == now + timedelta(minutes=10)
    (tmp_path / "sub-expand.json").write_text(json.dumps({"clicks": clicks[:10]}), encoding="utf-8")
    assert cf.sub_quota(now) == (20, None)
    (tmp_path / "sub-expand.json").write_text("坏的", encoding="utf-8")
    assert cf.sub_quota(now) == (30, None)


def test_detail_kwargs_passes_resume_only_with_expand():
    from link_brain import ingest
    kw = ingest._detail_kwargs(10, ["f1"], 300, ["f1:r1:20"])
    assert kw["expand_resume"] == ["f1:r1:20"] and kw["expand_floors"] == ["f1"]
    assert "expand_resume" not in ingest._detail_kwargs(10, ["f1"], 300)
