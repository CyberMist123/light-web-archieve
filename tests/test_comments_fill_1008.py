"""1008 Owner：评论区长楼层 / 楼中楼没下全——缺口如实记（归档、可见页、机读版、同步记录），下次续读接着拿。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from link_brain import cli, ingest as ingest_mod, nightly, render as render_mod, storage, synclog
from link_brain.adapters import xiaohongshu as xhs

from test_render import NOTE_ID, fake_parsed, load_fixture, setup_env


# --------------------------------------------------------------------------
# comment_load 压缩：missing=0 的楼不是缺口（旧组件会把陈旧 hasMore=true 的楼也列进来）
# --------------------------------------------------------------------------

RAW_CL = {"floor_limit": 10, "floors_loaded": 20, "floors_expanded": 0, "replies_missing": 1307, "partial": True,
          "stop_reason": "cancelled", "seconds": 479.1, "budget_seconds": 480, "comments_has_more": True,
          "replies_partial": [
              {"floor": 1, "comment_id": "c1", "shown": 2, "loaded": 2, "missing": 0, "has_more": True, "reason": "no_button"},
              {"floor": 2, "comment_id": "c2", "shown": 1153, "loaded": 171, "missing": 982, "has_more": True, "reason": "not_reached"},
              {"floor": 3, "comment_id": "c3", "shown": 476, "loaded": 151, "missing": 325, "has_more": True, "reason": "not_reached"},
              {"floor": 4, "comment_id": "c4", "shown": 67, "loaded": 67, "missing": 0, "has_more": True, "reason": "no_button"},
          ]}


def test_compact_drops_zero_missing_and_sums():
    cl = xhs.compact_comment_load(RAW_CL)
    assert [g["comment_id"] for g in cl["gaps"]] == ["c2", "c3"]
    assert cl["replies_missing"] == 1307 and cl["partial"] is True and cl["stop_reason"] == "cancelled"
    assert xhs.compact_comment_load(None) is None
    done = xhs.compact_comment_load({**RAW_CL, "replies_partial": RAW_CL["replies_partial"][:1], "partial": True})
    assert done["gaps"] == [] and done["replies_missing"] == 0 and done["partial"] is False


def test_merge_keeps_old_replies_for_floors_not_expanded_this_time():
    old = [{"comment_id": "c1", "sub_comment_count": 9, "sub_comments": [{"comment_id": f"s{i}"} for i in range(9)]},
           {"comment_id": "c2", "sub_comment_count": 1153, "sub_comments": [{"comment_id": f"t{i}"} for i in range(171)]},
           {"comment_id": "c9", "sub_comment_count": 0, "sub_comments": []}]
    new = [{"comment_id": "c1", "sub_comment_count": 9, "sub_comments": [{"comment_id": "s0"}]},   # 这次没要求展开，只有首屏 1 条
           {"comment_id": "c2", "sub_comment_count": 1153, "sub_comments": [{"comment_id": f"t{i}"} for i in range(700)]}]
    merged = xhs.merge_comments(old, new, {"c2"})
    by = {c["comment_id"]: c for c in merged}
    assert len(by["c1"]["sub_comments"]) == 9 and len(by["c2"]["sub_comments"]) == 700
    assert "c9" in by  # 老版本有、这次没滚到的楼不丢
    cl = xhs.merge_comment_load(xhs.compact_comment_load(RAW_CL),
                                xhs.compact_comment_load({**RAW_CL, "stop_reason": "budget", "replies_partial": [
                                    {"floor": 2, "comment_id": "c2", "shown": 1153, "loaded": 700, "missing": 453, "reason": "not_reached"}]}),
                                {"c2"}, merged)
    assert cl["fill_attempts"] == 1 and cl["replies_missing"] == 453 + 325
    assert sorted(g["comment_id"] for g in cl["gaps"]) == ["c2", "c3"]


# --------------------------------------------------------------------------
# 入库：缺口进归档 + 可见页 + 机读版 + 同步记录；fetch_detail 带预算 / 续读参数
# --------------------------------------------------------------------------


def _fixture_with_gaps():
    raw = load_fixture()
    comments = raw["data"]["comments"]["list"]
    assert comments, "样本里要有评论"
    first = comments[0]
    first["subCommentCount"] = 40
    first["subComments"] = (first.get("subComments") or [])[:1] or [{"id": "sub-x", "content": "回复", "userInfo": {}}]
    raw["data"]["comment_load"] = {**RAW_CL, "replies_missing": 39, "stop_reason": "budget", "replies_partial": [
        {"floor": 1, "comment_id": first["id"], "shown": 40, "loaded": len(first["subComments"]), "missing": 39,
         "reason": "not_reached"}]}
    return raw, first["id"]


def test_ingest_records_gap_everywhere(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    raw, cid = _fixture_with_gaps()
    calls = []

    def fake_fetch(note_id, token, **kw):
        calls.append(kw)
        return raw
    monkeypatch.setattr(xhs, "fetch_detail", fake_fetch)
    synclog.reset()
    synclog.begin("manual", own=True)  # 生产里这一行由 sync-favorites / 导入开；裸 ingest 命令自己不开
    assert cli.main(["ingest", "https://example.invalid/share", "--origin", "cli"]) in (0, 2)
    capsys.readouterr()
    assert calls[0]["full_comments"] is True and "expand_floors" not in calls[0]
    meta = storage.read_json(storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json")
    source = storage.read_json(storage.raw_dir("xiaohongshu", NOTE_ID, meta["current_version"]) / "source.json")
    cl = source["capture"]["comment_load"]
    assert cl["replies_missing"] == 39 and cl["gaps"][0]["comment_id"] == cid and cl["gaps"][0]["reason"] == "not_reached"
    # 可见页：顶上一行 + 那楼标「还有 39 条回复没拿到」
    vault = storage.vault_root()
    md = next(vault.glob("Web/Xiaohongshu/*.md")).read_text(encoding="utf-8")
    assert "楼中楼还缺 39 条" in md and "下次同步接着读" in md
    assert "还有 39 条回复没拿到（评论区太长，这次时间用完，下次同步接着读）" in md
    assert "展开 40 条回复" not in md
    # 机读版
    agent = (storage.object_dir("xiaohongshu", NOTE_ID) / "derived" / "agent.md").read_text(encoding="utf-8")
    assert "楼中楼还缺 39 条" in agent and "（还缺 39 条回复）" in agent
    # 同步记录：评论一项 ❌，带续读命令
    rows = [json.loads(l) for l in (storage.archive_root() / "sync-log.jsonl").read_text(encoding="utf-8").splitlines()]
    item = next(it for r in rows for it in r.get("items", []) if it["kind"] == "comments")
    assert item["ok"] is False and "缺 39 条" in item["reason"] and item["retry"] == ["comments", f"xhs-{NOTE_ID}", "--fill"]
    assert "评论" in synclog.summary_line(rows[-1])


def test_fill_expands_only_gap_floors_and_merges(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    raw, cid = _fixture_with_gaps()
    calls = []
    state = {"raw": raw}

    def fake_fetch(note_id, token, **kw):
        calls.append(kw)
        return state["raw"]
    monkeypatch.setattr(xhs, "fetch_detail", fake_fetch)
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)
    capsys.readouterr()
    # 续读那次：读取组件把那楼补齐
    raw2 = json.loads(json.dumps(raw))
    first = raw2["data"]["comments"]["list"][0]
    first["subComments"] = [{"id": f"sub-{i}", "content": f"回复 {i}", "userInfo": {}} for i in range(40)]
    raw2["data"]["comment_load"] = {**RAW_CL, "replies_missing": 0, "partial": False, "stop_reason": "floor_limit",
                                    "replies_partial": [], "floors_expanded": 1}
    # 其它楼在这次响应里只有首屏（没要求展开）——合并后不能丢
    for c in raw2["data"]["comments"]["list"][1:]:
        c["subComments"] = []
    state["raw"] = raw2
    assert cli.main(["comments", f"xhs-{NOTE_ID}", "--fill"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["filled"] is True
    assert calls[-1]["expand_floors"] == [cid] and calls[-1]["comment_budget_s"] == ingest_mod.FILL_BUDGET_S
    meta = storage.read_json(storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json")
    assert meta["current_version"] == 2
    source = storage.read_json(storage.raw_dir("xiaohongshu", NOTE_ID, 2) / "source.json")
    by = {c["comment_id"]: c for c in source["comments"]}
    assert len(by[cid]["sub_comments"]) == 40
    old = storage.read_json(storage.raw_dir("xiaohongshu", NOTE_ID, 1) / "source.json")
    for c in old["comments"][1:]:
        assert len(by[c["comment_id"]]["sub_comments"]) == len(c["sub_comments"])
    cl = source["capture"]["comment_load"]
    assert cl["replies_missing"] == 0 and cl["fill_attempts"] == 1 and cl["fill_last_at"]
    md = next(storage.vault_root().glob("Web/Xiaohongshu/*.md")).read_text(encoding="utf-8")
    assert "楼中楼还缺" not in md and "没拿到" not in md
    # 没缺口了：再 --fill 不开页
    n = len(calls)
    assert cli.main(["comments", f"xhs-{NOTE_ID}", "--fill"]) == 0
    assert json.loads(capsys.readouterr().out)["filled"] is False and len(calls) == n


def test_pending_fills_respects_attempts_and_gap_hours(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    raw, cid = _fixture_with_gaps()
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: raw)
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)
    capsys.readouterr()
    assert [sid for _, sid, _ in ingest_mod.pending_fills()] == [NOTE_ID]
    meta = storage.read_json(storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json")
    path = storage.raw_dir("xiaohongshu", NOTE_ID, meta["current_version"]) / "source.json"
    source = storage.read_json(path)
    source["capture"]["comment_load"]["fill_last_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    storage.write_json(path, source)
    assert ingest_mod.pending_fills() == []  # 刚续过，20 小时内不再开
    assert ingest_mod.pending_fills(now=datetime.now().astimezone() + timedelta(hours=21))
    source["capture"]["comment_load"]["fill_attempts"] = ingest_mod.FILL_MAX_ATTEMPTS
    storage.write_json(path, source)
    assert ingest_mod.pending_fills(now=datetime.now().astimezone() + timedelta(hours=21)) == []
    # 可见页如实说「不再读」
    render_mod.render_object("xiaohongshu", NOTE_ID, verbose=False, llm=False)
    md = next(storage.vault_root().glob("Web/Xiaohongshu/*.md")).read_text(encoding="utf-8")
    assert f"已续读 {ingest_mod.FILL_MAX_ATTEMPTS} 次" in md


def test_fill_pending_cli_and_nightly_step(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    raw, cid = _fixture_with_gaps()
    calls = []

    def fake_fetch(note_id, token, **kw):
        calls.append(kw)
        return raw
    monkeypatch.setattr(xhs, "fetch_detail", fake_fetch)
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)
    capsys.readouterr()
    assert cli.main(["comments", "--fill-pending", "--limit", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["candidates"] == 1 and out["done"][0]["item_id"] == f"xhs-{NOTE_ID}"
    assert calls[-1].get("expand_floors") == [cid]
    names = [s.name for s in nightly.default_steps()]
    assert "comments --fill-pending" in names
    step = next(s for s in nightly.default_steps() if s.name == "comments --fill-pending")
    assert step.account is True and names.index(step.name) < names.index("enrich --pending")


def test_old_reader_without_comment_load_renders_plain_hint(tmp_path, monkeypatch, capsys):
    """老读取组件没有 comment_load：楼层上限外的楼只说「只展开前几楼」，不编原因。"""
    setup_env(tmp_path, monkeypatch)
    raw = load_fixture()
    raw["data"].pop("comment_load", None)
    first = raw["data"]["comments"]["list"][0]
    first["subCommentCount"] = 7
    first["subComments"] = []
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: raw)
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)
    capsys.readouterr()
    md = next(storage.vault_root().glob("Web/Xiaohongshu/*.md")).read_text(encoding="utf-8")
    # 批次 D · N8：说人话；老读取组件按楼算出缺口时顶上也出一行（同样不编原因）+「现在抓全部评论」
    assert "另有 7 条回复没存（只存了前几楼的回复）" in md and "楼中楼还缺 7 条（只存了前几楼的回复）" in md
    assert ingest_mod.pending_fills() == []
