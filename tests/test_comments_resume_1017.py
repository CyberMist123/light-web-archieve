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


def test_fill_floors_pass_does_not_click_replies():
    from link_brain import ingest
    assert ingest._detail_kwargs(50, None, 300, fill=True)["click_more_replies"] is False
    assert "click_more_replies" not in ingest._detail_kwargs(50, None, None)  # 正常入档照旧展开
    assert "click_more_replies" not in ingest._detail_kwargs(10, ["f1"], 300, ["f1:r1:2"], fill=True)


def test_cli_only_flag_parses():
    from link_brain import cli
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:
        return
    a = parser.parse_args(["comments", "--fill-pending", "--until-done", "--only", "xhs-a,xhs-b", "--only", "c", "--floors", "50"])
    assert a.only == ["xhs-a,xhs-b", "c"] and a.floors == "50"


def test_merge_takes_current_site_count_after_deletes():
    # 原站删了回复：显示 3 → 1。存档留着删掉的那两条，但缺口按现在的 1 算（不再永远缺 2 条）
    old = [{"comment_id": "f1", "sub_comment_count": 3, "sub_comments": [_reply(1, 1), _reply(2, 2), _reply(3, 3)]}]
    new = [{"comment_id": "f1", "sub_comment_count": 1, "sub_comments": [_reply(1, 1)]}]
    out = xhs.merge_comments(old, new, {"f1"})
    assert out[0]["sub_comment_count"] == 1 and len(out[0]["sub_comments"]) == 3 and out[0]["sub_comments_complete"]
    gone = [{"comment_id": "f1", "sub_comment_count": 3, "sub_comments": [_reply(1, 1)]}]
    out = xhs.merge_comments(gone, [{"comment_id": "f1", "sub_comment_count": 0, "sub_comments": []}], {"f1"})
    assert cf.scope({"comments": out}, 10)["gaps"] == []


def test_floors_resume_point():
    src = {"comments": [{"comment_id": f"c{i}"} for i in range(520)],
           "capture": {"comments_cursor": "c519", "comment_load": {"has_more": True}}}
    assert cf.floors_resume_point(src) == "c519:520"
    assert cf.floors_resume_point(src, {"resume_floors_stale": True}) is None
    assert cf.floors_resume_point({**src, "comments": src["comments"][:10]}) is None  # 楼少：从头滚
    done = {**src, "capture": {"comments_cursor": "c519", "comment_load": {"has_more": False}}}
    assert cf.floors_resume_point(done) is None
    from link_brain import ingest
    assert ingest._detail_kwargs(2000, None, 480, fill=True, floors_resume="c519:520")["floors_resume"] == "c519:520"


def test_merge_keep_old_order_appends_new_floors():
    old = [{"comment_id": f"c{i}", "sub_comments": []} for i in range(5)]
    new = [{"comment_id": "c0", "sub_comments": []}, {"comment_id": "c1", "sub_comments": []},
           {"comment_id": "c5", "sub_comments": []}, {"comment_id": "c6", "sub_comments": []}]
    out = xhs.merge_comments(old, new, set(), keep_old_order=True)
    assert [c["comment_id"] for c in out] == [f"c{i}" for i in range(7)]


def test_sub_quota_reads_raised_limit_file(tmp_path, monkeypatch):
    from link_brain import accounts
    monkeypatch.setattr(accounts, "profile_dir", lambda: tmp_path)
    monkeypatch.delenv("XHS_SUB_PER_HOUR", raising=False)
    now = datetime(2026, 10, 17, 12, 0, tzinfo=TZ)
    clicks = [(now - timedelta(minutes=30)).isoformat()] * 40
    (tmp_path / "sub-expand.json").write_text(json.dumps({"clicks": clicks}), encoding="utf-8")
    assert cf.sub_quota(now)[0] == 0
    (tmp_path / "sub-per-hour.json").write_text(json.dumps({"per_hour": 60}), encoding="utf-8")
    assert cf.sub_quota(now)[0] == 20


def _gap_source(n_floors, gap_floors):
    cs = []
    for i in range(n_floors):
        c = {"comment_id": f"f{i}", "sub_comment_count": 1, "sub_comments": [_reply(i * 10, 0)]}
        if i in gap_floors:
            c["sub_comment_count"] = 5
        cs.append(c)
    return {"comments": cs, "capture": {"comment_load": {"has_more": False}}}


def test_plan_fill_expand_window_and_resume_point():
    src = _gap_source(900, {600, 610, 790, 899})
    sc = cf.scope(src, cf.FLOOR_ALL)
    mode, targets = cf.plan_fill(sc)
    assert mode == "expand" and set(targets) == {"f600", "f610"}  # 只取最前缺口起 150 楼内的
    assert cf.expand_window_resume(src, targets) == "f599:600"  # 从目标前一楼接着翻
    assert cf.expand_window_resume(src, ["f5"]) is None  # 前 30 楼内不跳
    from link_brain import ingest
    kw = ingest._detail_kwargs(10, targets, 480, ["f600:r:1"], fill=True, floors_resume="f599:600")
    assert kw["floors_resume"] == "f599:600" and kw["expand_floors"] == targets


def test_floor_all_is_unbounded():
    assert cf.floor_target("all") >= 100_000


def test_floors_cursor_only_moves_deeper():
    cs = [{"comment_id": f"c{i}"} for i in range(100)]
    assert cf.deepest_cursor(cs, "c99", "c12", "c48") == "c99"
    assert cf.deepest_cursor(cs, None, "zz", "c3") == "c3"
    src = {"comments": cs, "capture": {"comments_cursor": "c12", "comment_load": {"has_more": True}}}
    assert cf.floors_resume_point(src, {"floors_cursor": "c99"}) == "c99:100"  # 续展冲掉的浅游标不用


def test_floors_end_is_remembered_against_later_has_more():
    # 续展回写 has_more=true 也不再判「还有楼」：floors_done 记住了翻到底
    src = {"comments": [{"comment_id": f"c{i}", "sub_comment_count": 0, "sub_comments": []} for i in range(40)],
           "capture": {"comment_load": {"has_more": True}}}
    assert cf.scope(src, cf.FLOOR_ALL, {})["more_floors"] is True
    assert cf.scope(src, cf.FLOOR_ALL, {"floors_done": cf.FLOOR_ALL})["more_floors"] is False
