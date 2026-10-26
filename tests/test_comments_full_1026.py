"""1026 她（录屏 21:58）：「抓全部评论这里有 bug……有一些它会不齐。」

真库只读实查（10-26，数据形状照抄 vault/_archive 里的 source.json：comment_id 24 位 hex、sub_comment_count、
comment_load.gaps 里 reason=sub_paused）：
- 一篇手动抓全部评论翻到底（306 楼、has_more=false、comments_complete=true），之后夜里按设置楼数（10 楼）续展缺口楼，
  续展那趟读取组件只读前 20 楼、报 has_more=true——合并时直接拿这趟的盖掉：存档被记回「没读全、还有下一页」，
  游标退回第 20 楼（全库 22 篇这样）。
- 抓完只说「评论已更新：N 条」，19 楼因楼中楼小时额度停下缺 25 条没人告诉她；再点一次从第 1 楼整篇重来。

这里不联网：读取组件用 monkeypatch 的 fetch_detail 假装，楼 / 回复的形状照真数据。
"""

from __future__ import annotations

import json

from link_brain import cli, comment_fill, storage
from link_brain.adapters import xiaohongshu as xhs

from test_comments_fill_1009 import ITEM, _ingest, _raw, _source
from test_render import NOTE_ID, setup_env


def _cid(i: int) -> str:
    """真数据里的楼 id 是 24 位 hex（如 69e383530000000014019811）。"""
    return f"69e3{i:04x}0000000014019811"


def _floor(i: int, shown: int, have: int, *, start: int = 0) -> dict:
    cid = _cid(i)
    return {"id": cid, "content": f"楼 {i}", "userInfo": {"userId": f"u{i}", "nickname": f"人{i}"},
            "createTime": 1775000000000 + i * 1000, "subCommentCount": str(shown),
            "subComments": [{"id": f"{cid}r{k:03d}", "content": f"回复 {k}", "userInfo": {"userId": "u2"},
                             "createTime": 1775000000000 + i * 1000 + k} for k in range(start, start + have)]}


def _cl(n: int, *, has_more: bool, stop: str, gaps=None, limit: int = 100_000) -> dict:
    return {"floor_limit": limit, "floors_loaded": n, "floors_expanded": n, "comments_has_more": has_more,
            "stop_reason": stop, "partial": bool(gaps), "replies_partial": gaps or []}


def _ids(src: dict) -> list[str]:
    return [c["comment_id"] for c in src["comments"]]


def _assert_no_dupes(src: dict) -> None:
    ids = _ids(src)
    assert len(ids) == len(set(ids)), "一级评论有重复楼"
    for c in src["comments"]:
        subs = [s["comment_id"] for s in c.get("sub_comments") or []]
        assert len(subs) == len(set(subs)), f"楼 {c['comment_id']} 的回复有重复"


def _state() -> dict:
    return comment_fill.load_state("xiaohongshu", NOTE_ID)


def _md() -> str:
    return next(storage.vault_root().glob("Web/Xiaohongshu/*.md")).read_text(encoding="utf-8")


def _run_comments(capsys) -> dict:
    code = cli.main(["comments", ITEM])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0, out
    return out


# --------------------------------------------------------------------------
# 不产生重复楼层
# --------------------------------------------------------------------------


def test_overlapping_pages_and_repeated_fetch_never_duplicate_floors(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor(i, 2, 2) for i in range(1, 6)]))
    # 读取组件这趟：游标那一页和上一页重叠（楼 5 给了两遍、楼 6 的回复也给了两遍）
    f6 = _floor(6, 3, 3)
    f6["subComments"].append(dict(f6["subComments"][0]))
    page = [_floor(4, 2, 2), _floor(5, 2, 2), _floor(5, 2, 2), f6, _floor(7, 1, 1)]
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw(page, has_more=False, cl=_cl(len(page), has_more=False, stop="end")))
    _run_comments(capsys)
    src = _source()
    _assert_no_dupes(src)
    by_id = {c["comment_id"]: c for c in src["comments"]}
    assert len(src["comments"]) == 7 and len(by_id[_cid(6)]["sub_comments"]) == 3
    version = json.loads((storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json").read_text("utf-8"))["current_version"]
    # 同一份再抓两遍：楼数不变、不出新版本
    for _ in range(2):
        out = _run_comments(capsys)
        _assert_no_dupes(_source())
        assert len(_source()["comments"]) == 7
    meta = json.loads((storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json").read_text("utf-8"))
    assert meta["current_version"] == version and out["refreshed_unchanged"] is True


def test_merge_dedupes_duplicates_already_in_old_and_floors_without_id():
    a = {"comment_id": "f1", "sub_comment_count": 2, "sub_comments": [{"comment_id": "r1"}]}
    a2 = {"comment_id": "f1", "sub_comment_count": 2, "sub_comments": [{"comment_id": "r2"}]}
    noid1 = {"comment_id": None, "author": {"user_id": "u1"}, "created_at": "t1", "text": "没 id 的楼 1", "sub_comments": []}
    noid2 = {"comment_id": None, "author": {"user_id": "u2"}, "created_at": "t2", "text": "没 id 的楼 2", "sub_comments": []}
    out = xhs.merge_comments([a, a2, noid1], [noid2, noid1, a], set())
    keys = [xhs.floor_key(c) for c in out]
    assert len(keys) == len(set(keys)) == 3, "旧版自己的重复楼合成一楼；没 id 的两楼不会互相吞掉"
    f1 = next(c for c in out if c["comment_id"] == "f1")
    assert sorted(s["comment_id"] for s in f1["sub_comments"]) == ["r1", "r2"]
    for keep in (True, False):
        again = xhs.merge_comments(out, out + out, set(), keep_old_order=keep)
        assert [xhs.floor_key(c) for c in again] == keys, "同一份并两遍还是这几楼"


# --------------------------------------------------------------------------
# 翻到底的结论不被浅的续读冲掉
# --------------------------------------------------------------------------


def test_shallow_expand_after_full_read_keeps_reached_end(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor(i, 1, 1) for i in range(1, 11)]))
    # 手动抓全部评论：翻到底 40 楼，第 2 楼楼中楼因小时额度停下（真数据：reason=sub_paused）
    full = [_floor(1, 1, 1), _floor(2, 10, 9)] + [_floor(i, 1, 1) for i in range(3, 41)]
    gaps = [{"floor": 2, "comment_id": _cid(2), "shown": 10, "loaded": 9, "missing": 1, "reason": "sub_paused"}]
    raw = _raw(full, has_more=False, cl=_cl(40, has_more=False, stop="end", gaps=gaps))
    raw["data"]["comments"]["cursor"] = _cid(40)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: raw)
    out = _run_comments(capsys)
    assert "已翻到最后一页" in out["message"] and "1 楼的楼中楼还缺 1 条" in out["message"], out["message"]
    assert out["report"]["reached_end"] is True and out["report"]["resumable"] is True
    assert _state().get("floors_done") == comment_fill.FLOOR_ALL
    # 夜里按设置楼数续展第 2 楼：读取组件这趟只读前 20 楼、has_more=true、游标是第 20 楼
    shallow = _raw([_floor(2, 10, 10)] + [_floor(i, 1, 1) for i in range(3, 21)], has_more=True,
                   cl=_cl(20, has_more=True, stop="floor_limit", limit=10))
    shallow["data"]["comments"]["cursor"] = _cid(20)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: shallow)
    res = comment_fill.fill_one(ITEM)
    assert res["done"] is True
    src = _source()
    cap = src["capture"]
    assert cap["comments_complete"] is True, "翻到底的不被记回没读全"
    assert cap["comment_load"]["has_more"] is False and cap["comment_load"]["stop_reason"] == "end"
    assert cap["comment_load"]["last_read"]["stop_reason"] == "floor_limit"
    assert cap["comments_cursor"] == _cid(40), "游标不退回第 20 楼"
    assert len(src["comments"]) == 40
    _assert_no_dupes(src)
    meta = json.loads((storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json").read_text("utf-8"))
    assert meta["comments_complete"] is True
    assert "comments_complete: true" in _md() and "评论没读全" not in _md()
    rep = comment_fill.fetch_report(src, _state())
    assert rep["complete"] is True and rep["text"].startswith("评论全部抓齐了：已抓 40 楼")


def test_migration_remembers_end_for_notes_already_downgraded(tmp_path, monkeypatch, capsys):
    """真库那 22 篇：老代码已经写出「翻到底的版本 → 被浅续读冲掉的版本」。一次性补记 floors_done，下一版恢复 comments_complete。"""
    setup_env(tmp_path, monkeypatch)
    full = [_floor(i, 1, 1) for i in range(1, 31)]
    _ingest(monkeypatch, capsys, _raw(full, has_more=False, cl=_cl(30, has_more=False, stop="end")))
    # 模拟老代码写出的下一版：楼一楼不少，但 capture 被浅的续读冲成没读全
    od = storage.object_dir("xiaohongshu", NOTE_ID)
    meta = json.loads((od / "meta.json").read_text("utf-8"))
    v1 = storage.raw_dir("xiaohongshu", NOTE_ID, meta["current_version"])
    src = json.loads((v1 / "source.json").read_text("utf-8"))
    src["capture"]["comments_complete"] = False
    src["capture"]["comment_load"] = {"floor_limit": 10, "floors_loaded": 20, "has_more": True, "stop_reason": "floor_limit", "gaps": []}
    v2 = storage.raw_dir("xiaohongshu", NOTE_ID, meta["current_version"] + 1)
    v2.mkdir(parents=True)
    (v2 / "source.json").write_text(json.dumps(src, ensure_ascii=False), "utf-8")
    (v2 / "manifest.json").write_text((v1 / "manifest.json").read_text("utf-8"), "utf-8")
    meta["current_version"] += 1
    (od / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    assert comment_fill.reached_end(_source()["capture"]) is False
    assert comment_fill.remember_reached_end() == 1
    assert _state()["floors_done"] == comment_fill.FLOOR_ALL
    assert comment_fill.remember_reached_end() == 0, "一次性：做过就不再扫"
    assert comment_fill.fetch_report(_source(), _state())["reached_end"] is True


# --------------------------------------------------------------------------
# 抓不全能接着补、抓到最后一页
# --------------------------------------------------------------------------


def test_manual_fetch_is_resumable_until_last_page(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor(i, 1, 1) for i in range(1, 11)], comment_count=200))
    calls: list[dict] = []
    # ① 第一下：整篇读，评论区太长、时间用完停在第 40 楼（stop=budget，还有下一页）
    first = _raw([_floor(i, 1, 1) for i in range(1, 41)], has_more=True, comment_count=200,
                 cl=_cl(40, has_more=True, stop="budget"))
    first["data"]["comments"]["cursor"] = _cid(40)
    monkeypatch.setattr(xhs, "fetch_detail", lambda note_id, token, **kw: (calls.append(kw), first)[1])
    out = _run_comments(capsys)
    rep = out["report"]
    assert rep["floors"] == 40 and rep["paging"] == "more" and rep["next_floor"] == 41 and rep["resumable"] is True
    assert "还没翻到最后一页（评论区太长，这次时间用完），接着补抓会从第 41 楼往后翻" in out["message"]
    assert "原帖显示共 200 条评论" in out["message"] and "再点「接着补抓」" in out["message"]
    md = _md()
    assert "全部评论 · 已抓 40 楼" in md and ">接着补抓</span>" in md, "评论区顶上照实写 + 接着补抓按钮"
    assert calls[-1]["comment_limit"] == 100_000 and "floors_resume" not in calls[-1]

    # ② 第二下：接着翻——从第 40 楼的游标往后（读取组件把游标那楼又给了一遍：不许重复）；翻到底，第 45 楼楼中楼停在额度上
    def second(note_id, token, **kw):
        calls.append(kw)
        floors = [_floor(40, 1, 1)] + [_floor(i, 1, 1) for i in range(41, 45)] + [_floor(45, 12, 1)]
        gaps = [{"floor": 45, "comment_id": _cid(45), "shown": 12, "loaded": 1, "missing": 11, "reason": "sub_paused"}]
        return _raw(floors, has_more=False, comment_count=200, cl=_cl(len(floors), has_more=False, stop="end", gaps=gaps))
    monkeypatch.setattr(xhs, "fetch_detail", second)
    out = _run_comments(capsys)
    assert calls[-1]["floors_resume"] == f"{_cid(40)}:40", "从停下那页接着翻，不从第 1 楼重来"
    assert calls[-1]["click_more_replies"] is False
    src = _source()
    _assert_no_dupes(src)
    assert _ids(src)[:40] == [_cid(i) for i in range(1, 41)] and len(src["comments"]) == 45
    rep = out["report"]
    assert out["resumed"] is True and rep["reached_end"] is True and rep["missing"] == 11 and rep["resumable"] is True
    assert "已翻到最后一页" in out["message"] and "1 楼的楼中楼还缺 11 条（楼中楼这会儿暂停" in out["message"]

    # ③ 第三下：只展开缺回复的那楼，带游标从存下的最后一条往后拉
    def third(note_id, token, **kw):
        calls.append(kw)
        return _raw([_floor(45, 12, 12)], has_more=True, cl=_cl(1, has_more=True, stop="floor_limit", limit=10))
    monkeypatch.setattr(xhs, "fetch_detail", third)
    out = _run_comments(capsys)
    assert calls[-1]["expand_floors"] == [_cid(45)]
    rep = out["report"]
    assert rep["complete"] is True and rep["resumable"] is False and rep["reached_end"] is True
    assert out["message"].startswith("接着补抓完了：评论全部抓齐了：已抓 45 楼、56 条回复")
    _assert_no_dupes(_source())
    assert ">再抓一遍</span>" in _md() and "is-complete" in _md()

    # ④ 齐了再点：整篇读一遍看有没有新评论（不是续读），合并后照样不重复
    monkeypatch.setattr(xhs, "fetch_detail", lambda note_id, token, **kw: (calls.append(kw), second(note_id, token))[1])
    out = _run_comments(capsys)
    assert "floors_resume" not in calls[-2] and "expand_floors" not in calls[-2]
    _assert_no_dupes(_source())
    assert len(_source()["comments"]) == 45


def test_failed_manual_fetch_records_reason_on_the_page(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor(i, 1, 1) for i in range(1, 4)]))

    def boom(*a, **k):
        raise xhs.AdapterError("读取服务超时（480 秒）")
    monkeypatch.setattr(xhs, "fetch_detail", boom)
    code = cli.main(["comments", ITEM])
    capsys.readouterr()
    assert code == 1
    st = _state()
    assert st.get("full_at") and "读取服务超时" in st.get("last_error", "")
    rep = comment_fill.fetch_report(_source(), st)
    assert "上次没成：" in rep["text"] and rep["resumable"] is True


def test_report_wording_and_settled_counts():
    src = {"note": {"engagement": {"comment_count": 480}},
           "comments": [{"comment_id": "a", "sub_comment_count": 5, "sub_comments": [{"comment_id": "a1"}]},
                        {"comment_id": "b", "sub_comment_count": 3, "sub_comments": [{"comment_id": "b1"}]}],
           "capture": {"comments_complete": True, "comment_load": {"has_more": False, "stop_reason": "end", "gaps": [
               {"comment_id": "b", "missing": 2, "reason": "count_mismatch"}]}}}
    rep = comment_fill.fetch_report(src, {})
    assert rep["floors"] == 2 and rep["replies"] == 2 and rep["declared_total"] == 480
    assert rep["missing"] == 4 and rep["settled_missing"] == 2 and rep["gap_floors"] == 1
    assert rep["text"] == ("已抓 2 楼、2 条回复（原帖显示共 480 条评论，含回复），已翻到最后一页，"
                           "1 楼的楼中楼还缺 4 条（这楼当时没展开），另有 2 条原站显示但看不到（删了或被折叠，抓多少次都一样）")
