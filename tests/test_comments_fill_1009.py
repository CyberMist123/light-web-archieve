"""1009 Owner：评论楼层选 N = 前 N 楼、每楼全部楼中楼都要抓全；读不完的后台自动续读到补齐，不靠她手点。

根因（10-09 真库只读实查）：601 篇里 521 篇是 10-08 以前入库、没有 comment_load 的，其中 195 篇前 10 楼缺回复（共 5863 条）；
旧的 `--fill-pending` 只认 comment_load 里登记的缺口 → 这批永远排不上；另外每晚只续 2 篇、总共最多 3 次。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from link_brain import accounts, cli, comment_fill, ingest as ingest_mod, nightly, problems, storage
from link_brain.adapters import xiaohongshu as xhs

from test_render import NOTE_ID, load_fixture, setup_env

ITEM = f"xhs-{NOTE_ID}"


def _floor(cid: str, shown: int, have: int, *, start: int = 0) -> dict:
    return {"id": cid, "content": f"楼 {cid}", "userInfo": {"userId": "u1", "nickname": "某人"},
            "subCommentCount": str(shown),
            "subComments": [{"id": f"{cid}-r{i}", "content": f"回复 {i}", "userInfo": {"userId": "u2"}}
                            for i in range(start, start + have)]}


def _raw(floors: list[dict], *, has_more: bool = True, comment_count: int = 9999, cl: dict | None = None) -> dict:
    raw = load_fixture()
    raw["data"]["note"]["interactInfo"]["commentCount"] = str(comment_count)
    raw["data"]["comments"] = {"list": floors, "cursor": "", "hasMore": has_more}
    if cl is not None:
        raw["data"]["comment_load"] = cl
    return raw


def _ingest(monkeypatch, capsys, raw) -> None:
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: raw)
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)
    capsys.readouterr()


def _later(monkeypatch, minutes: int = 50) -> datetime:
    later = datetime.now().astimezone() + timedelta(minutes=minutes)
    monkeypatch.setattr(comment_fill, "_now", lambda: later)
    return later


def _source() -> dict:
    return comment_fill.current_source("xiaohongshu", NOTE_ID)[1]


def _set_floors(value) -> None:
    from link_brain import ai_config
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text("utf-8")) if p.exists() else {}
    data.setdefault("sync", {})["commentFloors"] = value
    p.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _md() -> str:
    return next(storage.vault_root().glob("Web/Xiaohongshu/*.md")).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 缺口模型
# --------------------------------------------------------------------------


def test_old_note_gap_inside_floor_setting_is_scheduled_and_filled(tmp_path, monkeypatch, capsys):
    """老读取组件存的笔记（没有 comment_load）：前 10 楼里缺回复 → 排进续读，只展开缺口那楼；第 12 楼缺的不管（不在 10 楼内）。"""
    setup_env(tmp_path, monkeypatch)
    floors = [_floor("c1", 7, 1)] + [_floor(f"c{i}", 2, 2) for i in range(2, 12)] + [_floor("c12", 30, 1)]
    _ingest(monkeypatch, capsys, _raw(floors))
    sv = comment_fill.survey(now=_later(monkeypatch))
    assert [(e["item_id"], e["mode"], e["targets"], e["missing"]) for e in sv["ready"]] == [(ITEM, "expand", ["c1"], 6)]
    md = _md()
    assert "前 10 楼的楼中楼还缺 6 条（以前只存了每楼前几条回复，后台在补）" in md
    assert "另有 29 条回复没存（只存了前 10 楼的回复）" in md  # 第 12 楼：在设置楼数外，如实说

    calls = []

    def fake(note_id, token, **kw):
        calls.append(kw)
        return _raw([_floor("c1", 7, 7)], cl={"floor_limit": 10, "floors_loaded": 1, "floors_expanded": 1,
                                               "stop_reason": "end", "replies_partial": []})
    monkeypatch.setattr(xhs, "fetch_detail", fake)
    out = comment_fill.fill_one(ITEM)
    assert calls[0]["expand_floors"] == ["c1"] and calls[0]["comment_budget_s"] == comment_fill.FILL_BUDGET_S
    assert out["done"] is True and out["missing_after"] == 0 and out["filled"] is True
    src = _source()
    ids = [c["comment_id"] for c in src["comments"]]
    assert ids[:3] == ["c1", "c2", "c3"] and len(ids) == 12  # 老顺序不变、其它楼一条不少
    assert len(src["comments"][0]["sub_comments"]) == 7
    state = comment_fill.load_state("xiaohongshu", NOTE_ID)
    assert state["attempts"] == 1 and state["no_progress"] == 0 and state.get("done_at")
    assert "楼中楼还缺" not in _md()
    assert comment_fill.survey(now=_later(monkeypatch, 200))["pending"] == 0


def test_raise_floors_loads_more_and_lower_never_deletes(tmp_path, monkeypatch, capsys):
    """楼数调大 = 旧笔记自动按新楼数补（floors 模式）；调小不删已抓的。"""
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor(f"c{i}", 1, 1) for i in range(1, 11)]))
    assert comment_fill.survey(now=_later(monkeypatch))["pending"] == 0  # 10 楼全了
    _set_floors(20)
    sv = comment_fill.survey(now=_later(monkeypatch))
    assert [(e["mode"], e["more_floors"]) for e in sv["ready"]] == [("floors", True)]
    calls = []

    def fake(note_id, token, **kw):
        calls.append(kw)
        return _raw([_floor(f"c{i}", 1, 1) for i in range(1, 21)], has_more=True)
    monkeypatch.setattr(xhs, "fetch_detail", fake)
    out = comment_fill.fill_one(ITEM)
    assert calls[0]["comment_limit"] == 20 and "expand_floors" not in calls[0]
    assert out["done"] is True and len(_source()["comments"]) == 20
    _set_floors(10)
    assert comment_fill.survey(now=_later(monkeypatch, 300))["pending"] == 0
    assert len(_source()["comments"]) == 20  # 调小不删


def test_union_merge_keeps_replies_the_site_no_longer_shows(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 6, 3)]))
    # 这次原站只给后 3 条（前面删了），合并后 6 条都在
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([_floor("c1", 6, 3, start=3)], cl={
        "floor_limit": 10, "stop_reason": "end", "replies_partial": []}))
    comment_fill.fill_one(ITEM)
    subs = [s["comment_id"] for s in _source()["comments"][0]["sub_comments"]]
    assert sorted(subs) == [f"c1-r{i}" for i in range(6)]


def test_no_progress_three_times_goes_to_problem_panel_then_resolves(tmp_path, monkeypatch, capsys):
    """连着 3 次续读都没多拿到 → 不再自动续、进问题面板（原因照实）；没多拿到的那几次不写新 RAW 版本。之后补上了 → 这条消掉。"""
    setup_env(tmp_path, monkeypatch)
    raw = _raw([_floor("c1", 9, 2)])
    _ingest(monkeypatch, capsys, raw)
    same = _raw([_floor("c1", 9, 2)], cl={"floor_limit": 10, "stop_reason": "budget", "replies_partial": [
        {"floor": 1, "comment_id": "c1", "shown": 9, "loaded": 2, "missing": 7, "reason": "click_failed"}]})
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: same)
    for i in range(comment_fill.NO_PROGRESS_LIMIT):
        out = comment_fill.fill_one(ITEM)
        assert out["refreshed_unchanged"] is True
    meta = storage.read_json(storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json")
    assert meta["current_version"] == 1
    state = comment_fill.load_state("xiaohongshu", NOTE_ID)
    assert state["stuck"] is True and state["no_progress"] == 3
    rows = [r for r in problems.load() if r.get("step") == comment_fill.STEP]
    assert len(rows) == 1 and rows[0]["code"] == "PERMANENT.COMMENTS_INCOMPLETE" and rows[0]["item_id"] == ITEM
    assert "还缺 7 条" in rows[0]["reason"] and "连着 3 次" in rows[0]["reason"]
    sv = comment_fill.survey(now=_later(monkeypatch, 600))
    assert sv["pending"] == 0 and [e["item_id"] for e in sv["stuck"]] == [ITEM]
    # 自动不再续；她点「再试一次」（manual）照跑，补齐了就消掉
    assert comment_fill.fill_one(ITEM)["reason"].startswith("连着几次补不上")
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([_floor("c1", 9, 9)], cl={
        "floor_limit": 10, "stop_reason": "end", "replies_partial": []}))
    out = comment_fill.fill_one(ITEM, manual=True)
    assert out["done"] is True
    assert not [r for r in problems.load() if r.get("step") == comment_fill.STEP]
    assert not comment_fill.load_state("xiaohongshu", NOTE_ID).get("stuck")


def test_count_mismatch_and_missing_floor_are_settled_not_gaps(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    cl = {"floor_limit": 10, "stop_reason": "end", "replies_partial": [
        {"floor": 1, "comment_id": "c1", "shown": 5, "loaded": 3, "missing": 2, "reason": "count_mismatch"}]}
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 5, 3), _floor("c2", 4, 1)], cl=cl, has_more=False))
    sc = comment_fill.scope(_source(), 10)
    assert [g["comment_id"] for g in sc["gaps"]] == ["c2"] and [g["comment_id"] for g in sc["settled"]] == ["c1"]
    assert "原站多显示 2 条回复（删了或被折叠，看不到）" in _md()
    # c2 这楼原帖里已经找不到了：读取组件 floors_not_found → 记成「已删」，不再续
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([], cl={
        "floor_limit": 10, "stop_reason": "end", "replies_partial": [], "floors_not_found": ["c2"]}))
    out = comment_fill.fill_one(ITEM)
    assert out["done"] is True
    assert comment_fill.load_state("xiaohongshu", NOTE_ID)["gone_floors"] == ["c2"]
    assert "这楼在原帖里已经找不到了" in _md()


def test_fill_reuses_downloaded_media_and_does_not_redownload(tmp_path, monkeypatch, capsys):
    """续读写新版本时：上一版下好的图引用旧文件（不重下、识图按资产路径复用），只下新冒出来的评论图。"""
    setup_env(tmp_path, monkeypatch)
    got = []

    def fake_download(url, dest_dir, stem, *, client):
        got.append(stem)
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{stem}.jpg").write_bytes(b"x")
        return {"file": f"{stem}.jpg", "requested_url": url, "mime": "image/jpeg", "width": 1, "height": 1,
                "bytes": 1, "sha256": "0", "download_status": "ok", "error": None}
    monkeypatch.setattr(ingest_mod, "download_image", fake_download)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 3, 1)]))
    assert got == ["image-001"]
    got.clear()
    reply = _floor("c1", 3, 3)
    reply["subComments"][2]["pictures"] = [{"urlDefault": "https://example.invalid/reply.jpg"}]
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([reply], cl={
        "floor_limit": 10, "stop_reason": "end", "replies_partial": []}))
    comment_fill.fill_one(ITEM)
    assert got == ["comment-c1-r2-001"]  # 正文图没重下
    meta = storage.read_json(storage.object_dir("xiaohongshu", NOTE_ID) / "meta.json")
    manifest = storage.read_json(storage.raw_dir("xiaohongshu", NOTE_ID, meta["current_version"]) / "manifest.json")
    note_img = next(m for m in manifest["media"] if m["role"] == "note_image")
    assert note_img["file"].startswith("raw/v0001/") and manifest["images_complete"] is True
    assert meta["current_version"] == 2


# --------------------------------------------------------------------------
# 后台补跑：等验证、让夜跑、单实例、让别的任务先用号
# --------------------------------------------------------------------------


def _args(**kw):
    base = dict(fill_pending=True, until_done=False, budget_min=0, limit=0, then_background=False, verbose=False,
                wait_lock_min=2, detach=False, fill_status=False, target=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _statuses(monkeypatch) -> list[dict]:
    seen: list[dict] = []
    real = comment_fill.Status.update

    def spy(self, **fields):
        real(self, **fields)
        seen.append(dict(self.data))
    monkeypatch.setattr(comment_fill.Status, "update", spy)
    return seen


def test_worker_waits_out_captcha_without_opening_pages_then_resumes(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 4, 1)]))
    _later(monkeypatch)
    # 1011：验证码改走冷却自查（test_night_captcha_1011）；要人处理的其它码（这里：风控跳页）照旧只看内存状态等她
    answers = iter([("ACCOUNT_RISK", "小红书把读取号跳到了安全页"), ("ACCOUNT_RISK", "小红书把读取号跳到了安全页")])
    monkeypatch.setattr(comment_fill, "account_wait_reason", lambda: next(answers, ("", "")))
    monkeypatch.setattr(comment_fill, "nightly_busy", lambda *a, **k: "")
    monkeypatch.setattr(accounts, "lock_wanted", lambda: False)
    calls = []

    def fake(note_id, token, **kw):
        calls.append(kw)
        return _raw([_floor("c1", 4, 4)], cl={"floor_limit": 10, "stop_reason": "end", "replies_partial": []})
    monkeypatch.setattr(xhs, "fetch_detail", fake)
    seen = _statuses(monkeypatch)
    naps = []
    assert comment_fill.run(_args(until_done=True), sleep=naps.append) == 0
    waiting = [s for s in seen if s.get("wait_code") == "ACCOUNT_RISK"]
    assert waiting and all(s["state"] == "waiting" for s in waiting)
    assert len(calls) == 1  # 熔断期间一页没开，过完验证才开
    assert seen[-1]["state"] == "done" and "都补齐了" in seen[-1]["message"]
    assert sum(naps) >= 2 * comment_fill.WAIT_HUMAN_S


def test_worker_yields_to_nightly_and_waiting_tasks(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 4, 1)]))
    _later(monkeypatch)
    busy = iter(["夜跑在跑，号让给它，做完接着补"])
    monkeypatch.setattr(comment_fill, "nightly_busy", lambda *a, **k: next(busy, ""))
    wanted = iter([True])
    monkeypatch.setattr(accounts, "lock_wanted", lambda: next(wanted, False))
    monkeypatch.setattr(comment_fill, "account_wait_reason", lambda: ("", ""))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([_floor("c1", 4, 4)], cl={
        "floor_limit": 10, "stop_reason": "end", "replies_partial": []}))
    seen = _statuses(monkeypatch)
    assert comment_fill.run(_args(until_done=True), sleep=lambda s: None) == 0
    codes = [s.get("wait_code") for s in seen if s.get("state") == "paused"]
    assert "NIGHTLY" in codes and "YIELD" in codes


def test_worker_is_single_instance(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    lock = storage.locks_dir() / f"{comment_fill.LOCK_NAME}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getppid(), "owner": "comments-fill", "heartbeat_ts": time.time()}), "utf-8")
    assert cli.main(["comments", "--fill-pending", "--until-done"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["already_running"] is True and out["ok"] is True


def test_polite_session_lets_waiting_task_go_first(tmp_path, monkeypatch):
    lock = accounts.lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    want = lock.with_name(lock.name + f".want-{os.getppid()}")
    want.write_text(json.dumps({"pid": os.getppid(), "owner": "sync-favorites", "ts": time.time()}), "utf-8")
    assert accounts.lock_wanted() is True
    with pytest.raises(accounts.AccountBusyError):
        with accounts.account_session("comments-fill", wait_s=0.3, polite=True):
            pass
    with accounts.account_session("sync-favorites", wait_s=0.3):  # 不让路的一方照拿
        pass
    want.unlink()
    with accounts.account_session("comments-fill", wait_s=0.3, polite=True):
        pass


def test_waiting_task_announces_itself_while_lock_is_held(tmp_path, monkeypatch):
    lock = accounts._account_lock()
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    lock.path.write_text(json.dumps({"pid": os.getppid(), "owner": "comments-fill", "heartbeat_ts": time.time()}), "utf-8")
    seen = []
    real_sleep = time.sleep

    def peek(s):
        seen.append([p.name for p in lock.path.parent.glob(lock.path.name + ".want-*")])
        real_sleep(0.01)
    monkeypatch.setattr(storage.time, "sleep", peek)
    with pytest.raises(accounts.AccountBusyError):
        with accounts.account_session("sync-favorites", wait_s=0.2):
            pass
    assert any(f"account.lock.want-{os.getpid()}" in names for names in seen)
    assert not list(lock.path.parent.glob(lock.path.name + ".want-*"))  # 放弃后撤掉标记


def test_nightly_busy_running_and_lead_time():
    now = datetime(2026, 10, 10, 3, 50).astimezone()
    assert comment_fill.nightly_busy(now, [{"name": "T", "state": "Running", "next": ""}])
    assert "04:00" in comment_fill.nightly_busy(now, [{"name": "T", "state": "Ready", "next": "2026-10-10T04:00:00"}])
    assert comment_fill.nightly_busy(now, [{"name": "T", "state": "Ready", "next": "2026-10-10T08:00:00"}]) == ""


def test_nightly_step_has_no_two_note_cap_and_hands_over_to_background(tmp_path, monkeypatch, capsys):
    step = next(s for s in nightly.default_steps() if s.name == "comments --fill-pending")
    assert "--limit" not in step.args and "--then-background" in step.args and step.account is True
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 4, 1)]))
    _later(monkeypatch)
    monkeypatch.setattr(comment_fill, "account_wait_reason", lambda: ("", ""))
    spawned = []
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: spawned.append(1) or {"ok": True, "started": True})
    # 预算不够开下一篇：一篇不读，转后台
    assert comment_fill.run(_args(budget_min=1, then_background=True)) == 0
    assert spawned == [1]
    st = comment_fill.read_status()
    assert st["state"] == "stopped" and "转到后台接着补" in st["message"]


def test_fill_status_payload_counts_pending(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 4, 1), _floor("c2", 3, 1)]))
    assert cli.main(["comments", "--fill-status"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["pending"] == 1 and out["missing"] == 5 and out["cooling"] == 1
    assert "还没补齐" in out["message"]


def test_repair_plan_for_incomplete_comments_is_manual_retry():
    from link_brain import repair
    p = repair.plan({"step": comment_fill.STEP, "code": comment_fill.CODE_INCOMPLETE, "item_id": ITEM})
    assert p["kind"] == "run" and p["action"] == "comments_fill_item" and p["auto"] is False
    assert repair.ACTIONS["comments_fill_item"].argv(ITEM) == ["comments", ITEM, "--fill"]
    assert repair.ACTIONS["comments_fill_item"].account is True
