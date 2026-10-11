"""1011 她的三张截图：同一时刻三处数对不上、同步记录说错来源 / 把被停的一趟记成「没有新内容」/ 早好了的报错还红着。

- 数（fav_counts 一份口径）：进度条（favorites._Live）、同步记录第一排（synclog.backlog）、setup backfill 同一组 (总数, 已入库, 还差)。
- 来源：没人看着（LINK_BRAIN_UNATTENDED）= 夜跑 / 定时，哪怕在控制台里（夜跑脚本由计划任务起在控制台，isatty 为真）。
- 被中断：收藏同步每篇当场写进同步记录；抓取进程没了又没收尾 → 「被中断 · 已收 N 篇」；老记录按库里入库时间补回。
- 自愈：之后同一个离线命令成功跑过（cli 收尾 heal_after_success）→ 夜跑那一步的报错在问题记录里标已解决，同步记录那条 resolved、不算出错。
不联网、不碰号：抓取全替身。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from link_brain import favorites as fav_mod, fav_counts, problems, storage, sync_state, synclog
from link_brain import index as index_mod
from link_brain.adapters import xiaohongshu as xhs
from link_brain.setup import backfill as backfill_mod


@pytest.fixture(autouse=True)
def _clean():
    synclog.reset()
    yield
    synclog.reset()


def _fav(nid: str) -> dict:
    return {"note_id": nid, "xsec_token": "TOK", "title": f"标题-{nid}",
            "url": f"https://www.xiaohongshu.com/explore/{nid}?xsec_token=TOK"}


def _objects(ids, *, favorite=True):
    root = storage.archive_root() / xhs.SOURCE
    for nid in ids:
        d = root / nid
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps({"favorited_by": ["me"] if favorite else [],
                                                 "ingest_kind": "favorite" if favorite else "shared"}), encoding="utf-8")


def _snapshot(ids):
    storage.write_json(storage.archive_root() / "fav-list.json",
                       {"schema_version": 1, "full_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "items": [_fav(n) for n in ids]})


def _tombstone(nid):
    conn = index_mod.connect()
    try:
        conn.execute("INSERT INTO tombstones (source, source_id, item_id, deleted_at, trash_dir) VALUES (?,?,?,?,?)",
                     (xhs.SOURCE, nid, f"xhs-{nid}", "2026-10-01T00:00:00+10:00", "_trash/x"))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- 一份口径

def test_progress_line_sync_log_and_backfill_share_one_count(monkeypatch):
    """名单 10 篇：库里有 5 篇（其中 1 篇是分享进来的不在名单里）+ 名单里 1 篇在回收站 → 已入库 5、还差 5；
    另有 2 篇从收藏进来、后来取消了收藏（不在名单）——以前同步记录数「从收藏进来的对象」会多算它们。"""
    favs = [f"n{i}" for i in range(10)]
    _snapshot(favs)
    _objects(["n0", "n1", "n2", "n3"])                 # 名单里、在库
    _objects(["old1", "old2"])                         # 从收藏进来、已取消收藏
    _objects(["shared1"], favorite=False)              # 分享进来的
    _tombstone("n4")                                   # 名单里、在回收站（删了 = 不再同步）
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 9})   # 停在旧值的基准不再被用
    monkeypatch.setattr("link_brain.ai_config.sync_options", lambda: {"dailyNewLimit": 2})

    c = fav_counts.counts()
    assert (c["favorites_total"], c["archived"], c["remaining"], c["library_total"], c["basis"]) == (10, 5, 5, 7, "list")
    live = fav_mod._Live(fav_mod._Quota())
    live.count([_fav(n) for n in favs])
    assert (live.total, live.archived, live.remaining) == (10, 5, 5), "进度条和同步记录同一组数"
    b = backfill_mod.backfill()
    assert (b["favorites_total"], b["archived"], b["remaining"], b["deferred"], b["days_left"]) == (10, 5, 5, 5, 3)
    assert synclog.backlog()["message"] == "收藏 10 篇，已入库 5 篇，还差 5 篇，预计还要 3 天同步完"
    assert fav_counts.text(c) == "收藏已入库 5/10（还差 5 篇）"


def test_counts_fall_back_to_baseline_without_list():
    _objects(["a", "b"])
    _objects(["s"], favorite=False)
    storage.write_json(sync_state.path(), {"state": "ready", "last_favorites": 5})
    c = fav_counts.counts()
    assert (c["favorites_total"], c["archived"], c["remaining"], c["basis"]) == (5, 2, 3, "baseline")


# ---------------------------------------------------------------- 来源

def test_unattended_is_nightly_or_schedule_even_in_a_console(monkeypatch):
    monkeypatch.delenv(synclog.ENV_TRIGGER, raising=False)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    four = datetime(2026, 10, 11, 4, 2).astimezone()
    afternoon = datetime(2026, 10, 11, 15, 0).astimezone()
    assert synclog.default_trigger(four) == "cli", "没设 LINK_BRAIN_UNATTENDED 的交互终端 = 命令行"
    monkeypatch.setenv("LINK_BRAIN_UNATTENDED", "nightly")
    assert synclog.default_trigger(four) == "nightly", "夜跑脚本（计划任务起在控制台里）不是命令行"
    assert synclog.default_trigger(afternoon) == "schedule"
    monkeypatch.setenv(synclog.ENV_TRIGGER, "manual")
    assert synclog.default_trigger(four) == "manual", "插件「立即同步」明说的优先"


def test_running_status_carries_trigger_for_the_plugin(monkeypatch):
    monkeypatch.setenv(synclog.ENV_TRIGGER, "cli")
    sync_state.record("running", message="正在同步收藏")
    assert storage.read_json(sync_state.path())["trigger"] == "cli"
    assert sync_state.page_state()["trigger"] == "cli"


# ---------------------------------------------------------------- 被中断

class _Killed(BaseException):
    """模拟进程被结束：不走任何 except Exception / finally 里的收尾（cli.finish_command 没机会跑）。"""


def _setup_sync(monkeypatch, favs, archived):
    monkeypatch.setattr(fav_mod, "fetch_favorites", lambda *, limit=50, verbose=False, mode="full": list(favs))
    monkeypatch.setattr(fav_mod, "_render_local", lambda *a, **k: None)
    monkeypatch.setattr(fav_mod, "_already_archived", lambda fav: fav.get("note_id") in archived)
    monkeypatch.setattr(fav_mod.read_mod, "item_payload", lambda key, sid, status: {
        "item_id": f"xhs-{sid}", "status": status, "url": None, "title": f"标题-{sid}"})
    monkeypatch.setattr("link_brain.ai_config.sync_options", lambda: {"dailyNewLimit": 150})
    monkeypatch.setattr(fav_mod, "_rest_wait", lambda: 0.0)
    monkeypatch.setattr(fav_mod, "_sleep", lambda s: None)
    monkeypatch.setattr("link_brain.enrich.mark_pending", lambda *a, **k: None)
    monkeypatch.setattr("link_brain.attachments.grab_after_ingest", lambda *a, **k: "")
    (storage.archive_root() / xhs.SOURCE).mkdir(parents=True, exist_ok=True)


def test_killed_sync_shows_interrupted_with_what_it_stored(monkeypatch):
    monkeypatch.delenv(synclog.ENV_RUN, raising=False)
    monkeypatch.setenv(synclog.ENV_TRIGGER, "cli")
    favs = [_fav(f"k{i}") for i in range(6)]
    _setup_sync(monkeypatch, favs, archived=set())
    stored = []

    def fake_ingest(url, **kw):
        nid = url.split("/explore/")[1].split("?")[0]
        if len(stored) == 3:
            raise _Killed()          # 第 4 篇抓到一半，进程被结束（她 17:00 为换新代码停掉的那种）
        stored.append(nid)
        return {"hit": False, "note_id": nid, "item_id": f"xhs-{nid}", "title": f"标题-{nid}"}

    monkeypatch.setattr(fav_mod.ingest_mod, "ingest_url", fake_ingest)
    synclog.begin(own=False)
    sync_state.record("running", message="正在同步收藏")
    synclog.fetch_started()
    with pytest.raises(_Killed):
        fav_mod.sync_favorites(limit=0)
    synclog.reset()                                   # 进程没了：攒着的、本进程记住的都没了
    monkeypatch.setattr(synclog, "_alive", lambda pid: False)
    row = synclog.load()[0]
    assert row["interrupted"] and not row.get("running") and row["finished_at"]
    assert row["new"] == 3 and row["counts"]["note"] == {"ok": 3, "failed": 0}, "每篇当场写进去了，被停也记得"
    assert "被中断 · 已收 3 篇" in synclog.summary_line(row) and "没有新内容" not in synclog.summary_line(row)


def test_normal_finish_is_not_interrupted(monkeypatch):
    monkeypatch.delenv(synclog.ENV_RUN, raising=False)
    monkeypatch.setenv(synclog.ENV_TRIGGER, "cli")
    synclog.begin(own=False)
    synclog.fetch_started()
    synclog.note("note", "xhs-a", True, title="A")
    synclog.count_new(1)
    synclog.finish_command("sync-favorites", SimpleNamespace(), 0)
    monkeypatch.setattr(synclog, "_alive", lambda pid: False)
    row = synclog.load()[0]
    assert not row.get("interrupted") and row["new"] == 1


def _index_object(nid, at, *, kind="favorite", title=None):
    conn = index_mod.connect()
    try:
        conn.execute("INSERT INTO objects (item_id, source, source_id, canonical_url, kind, title, first_archived_at, "
                     "last_checked_at, current_version, object_dir, visible_note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f"xhs-{nid}", xhs.SOURCE, nid, f"https://x/{nid}", "note", title or f"标题-{nid}", at, at, 1,
                      f"_archive/xiaohongshu/{nid}", f"Web/Xiaohongshu/{nid}.md"))
        conn.execute("INSERT INTO relations (item_id, origin, actor, ingest_kind, created_at) VALUES (?,?,?,?,?)",
                     (f"xhs-{nid}", "cli", "human", kind, at))
        conn.commit()
    finally:
        conn.close()


def test_old_row_that_lost_its_records_is_recovered_from_the_library():
    """1011 14:57 那趟：进程被结束、一条没写进去，记录是「没有新内容」；那段时间库里其实多了 43 篇收藏。"""
    t0 = datetime(2026, 10, 11, 14, 57, 30).astimezone()
    t1 = t0 + timedelta(hours=2, minutes=8)
    rows = [
        {**synclog._new_row("r-1457", "cli", "auto"), "started_at": t0.isoformat(), "updated_at": t0.isoformat(),
         "finished_at": t0.isoformat(), "pid": None},
        {**synclog._new_row("r-1705", "cli", "auto"), "started_at": t1.isoformat(), "updated_at": t1.isoformat(),
         "finished_at": t1.isoformat(), "pid": None},
    ]
    synclog._write(rows)
    for i in range(3):
        _index_object(f"w{i}", (t0 + timedelta(minutes=10 + i)).isoformat())
    _index_object("shared", (t0 + timedelta(minutes=20)).isoformat(), kind="shared")    # 别处导入的不算
    _index_object("later", (t1 + timedelta(minutes=5)).isoformat())                      # 下一趟的
    out = {r["run_id"]: r for r in synclog.load()}
    r = out["r-1457"]
    assert r["recovered"] and r["interrupted"] and r["new"] == 3
    assert [it["id"] for it in r["items"]] == ["xhs-w0", "xhs-w1", "xhs-w2"] and r["items"][0]["note"] == "Web/Xiaohongshu/w0.md"
    assert synclog.summary_line(r).endswith("被中断 · 已收 3 篇 · 正文 3 ✅")
    assert out["r-1705"]["new"] == 1, "最新那趟窗口开到现在"


# ---------------------------------------------------------------- 自愈

def test_step_error_shows_resolved_after_the_same_command_succeeds_later():
    t = datetime.now().astimezone() - timedelta(hours=10)
    row = {**synclog._new_row("r-0402", "nightly", "auto"), "started_at": t.isoformat(), "updated_at": t.isoformat(),
           "finished_at": t.isoformat(), "pid": None,
           "errors": [{"step": "repair.nightly.catalog", "reason": "已试：重写目录页（05:46）；没好：PermissionError", "code": "", "at": t.isoformat()},
                      {"step": "sync-favorites", "reason": "读收藏没成：小红书要求安全验证", "code": "CAPTCHA_REQUIRED", "at": t.isoformat()}]}
    synclog.recount(row)
    synclog._write([row])
    problems.report("nightly.catalog", "TRANSIENT.STEP_CRASHED", "catalog 崩溃（exit=1）")
    r = synclog.load()[0]
    assert r["error"] and not any(e.get("resolved") for e in r["errors"]), "还没好：照实红着"
    # 白天插件「刷新目录」/ 部署后跑了一次 catalog，成功了
    synclog.finish_command("catalog", SimpleNamespace(), 0)
    assert not any(not x.get("resolved_at") for x in problems._fold(problems._read_rows()).values()
                   if x.get("step") == "nightly.catalog"), "问题记录里那一步标已解决"
    r = synclog.load()[0]
    healed = [e for e in r["errors"] if e.get("resolved")]
    assert [e["step"] for e in healed] == ["repair.nightly.catalog"] and healed[0]["label"] == "重写目录页"
    assert r["error"], "号的事（验证）不算自愈，照实挂着"
    # 只剩自愈的那条时，这一行就不算出错
    row["errors"] = row["errors"][:1]
    synclog.recount(row)
    synclog._write([row])
    r = synclog.load()[0]
    assert r["error"] is False and synclog.summary_line(r).endswith("没有新内容")


def test_failed_command_does_not_heal():
    problems.report("nightly.videos-transcribe", "TRANSIENT.STEP_CRASHED", "videos --transcribe 崩溃")
    synclog.finish_command("videos", SimpleNamespace(all=True, transcribe=True), 1)
    assert synclog.heal_after_success("videos", SimpleNamespace(all=True, transcribe=False)) == 0, "不是同一个命令不算"
    assert any(not x.get("resolved_at") for x in problems._fold(problems._read_rows()).values() if x.get("step") == "nightly.videos-transcribe")
    assert synclog.heal_after_success("videos", SimpleNamespace(all=True, transcribe=True)) == 1
