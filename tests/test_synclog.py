"""10-03 同步记录（`vault/_archive/sync-log.jsonl`）：每次同步一行，数据来自这次实际处理的对象。

不联网、不起真同步：各步骤的记录点直接喂假结果；夜跑用假子命令（python -c）；重试用假 runner。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

from link_brain import cli, nightly, storage, synclog
from link_brain.nightly import Nightly, Step

PY = sys.executable


def rows():
    return synclog._read()


def test_one_line_per_sync_counts_and_titles():
    rid = synclog.begin("manual")
    synclog.count_new(2)
    synclog.note("note", "xhs-a", True, title="悉尼咖啡地图", note_path="Web/a.md")
    synclog.note("note", "xhs-b", True, title="电饭煲鸡肉饭")
    synclog.note("attachment", "xhs-a", True, title="悉尼咖啡地图")
    synclog.note("video", "xhs-c", False, title="视频", reason="语音识别失败：服务没开", code="TRANSIENT.SERVICE_BUSY")
    synclog.error("sync-favorites", "收藏只读回 3 条", "FAVORITES_SUSPICIOUS")
    assert synclog.flush() == rid
    synclog.end(rid, exit_code=1)
    [row] = rows()
    assert row["run_id"] == rid and row["trigger"] == "manual" and row["finished_at"] and row["exit"] == 1
    assert row["new"] == 2
    assert row["counts"] == {"note": {"ok": 2, "failed": 0}, "attachment": {"ok": 1, "failed": 0},
                             "video": {"ok": 0, "failed": 1}}
    assert row["error"] is True
    bad = [it for it in row["items"] if not it["ok"]]
    assert bad[0]["title"] == "视频" and bad[0]["reason"].startswith("语音识别失败")
    assert row["errors"][0]["step"] == "sync-favorites"
    assert synclog.summary_line(row).endswith("新收 2 · 正文 2 ✅ · 附件 1 ✅ · 视频 1 ❌")


def test_same_item_twice_in_one_process_failure_wins():
    """一篇两个附件：一个下好、一个没下好 / 下好了但没转成文字 → 这一项算没成，原因都在。"""
    synclog.begin("manual")
    synclog.note("attachment", "xhs-a", True, title="T")
    synclog.note("attachment", "xhs-a", False, reason="b.pdf：下载超时")
    synclog.note("attachment", "xhs-a", False, reason="a.pdf 没转成文字：PDF 有打开密码", retry=["pdf2md", "xhs-a"])
    synclog.flush()
    [it] = rows()[0]["items"]
    assert it["ok"] is False and "下载超时" in it["reason"] and "打开密码" in it["reason"]
    assert it["retry"] is None, "两种失败要不同命令补：退回默认（attachments 这一篇）"


def test_later_flush_overrides_same_item():
    rid = synclog.begin("nightly", own=False)
    synclog.note("attachment", "xhs-a", False, reason="超时")
    synclog.flush()
    synclog.note("attachment", "xhs-a", True)
    synclog.flush()
    row = rows()[0]
    assert row["run_id"] == rid and len(row["items"]) == 1 and row["items"][0]["ok"] is True
    assert row["error"] is False and row["items"][0]["reason"] == ""


def test_meta_fills_title_and_note(tmp_path):
    obj = storage.archive_root() / "xiaohongshu" / "n1"
    obj.mkdir(parents=True)
    (obj / "meta.json").write_text(json.dumps({"title": "旧书店", "visible_note": "Web/旧书店.md"}), encoding="utf-8")
    synclog.begin("manual")
    synclog.note("summary", "xhs-n1", True)
    synclog.flush()
    it = rows()[0]["items"][0]
    assert it["title"] == "旧书店" and it["note"] == "Web/旧书店.md"


def test_out_of_repo_script_path_auto_attach_and_audit_closes(monkeypatch):
    """仓外夜跑脚本什么都不带：sync-favorites 开一行（自动），后面的步骤并进来，attachments --audit 收尾。"""
    rid = synclog.begin(own=False)
    synclog.count_new(1)
    synclog.finish_command("sync-favorites")
    assert rows()[0]["finished_at"] is None, "自动行：同步那一步结束不收尾"
    synclog.reset()   # 下一步是另一个进程
    synclog.note("attachment", "xhs-a", True)
    synclog.finish_command("attachments")
    synclog.reset()
    synclog.note("video", "xhs-b", True)
    synclog.finish_command("videos")
    row = rows()[0]
    assert row["run_id"] == rid and {it["kind"] for it in row["items"]} == {"attachment", "video"}
    synclog.reset()
    synclog.finish_command("attachments", type("A", (), {"audit": True})())
    assert rows()[0]["finished_at"], "夜跑最后一步（附件闸门）收尾"
    # 收尾以后不带编号的步骤不再并进来（也不另开一行）
    synclog.reset()
    synclog.note("vision", "xhs-c", True)
    synclog.finish_command("enrich")
    assert len(rows()) == 1 and len(rows()[0]["items"]) == 2


def test_manual_trigger_closes_own_run_and_new_begin_closes_stale_auto(monkeypatch):
    old = synclog.begin(own=False)
    synclog.reset()
    monkeypatch.setenv(synclog.ENV_TRIGGER, "manual")
    rid = synclog.begin(own=True)
    assert rid != old
    r = {x["run_id"]: x for x in rows()}
    assert r[old]["finished_at"], "新的一次开始：上一条没收尾的自动行收尾"
    synclog.count_new(1)
    synclog.finish_command("sync-favorites", None, 0)
    r = {x["run_id"]: x for x in rows()}
    assert r[rid]["finished_at"] and r[rid]["trigger"] == "manual" and r[rid]["exit"] == 0


def test_env_run_id_routes_to_that_line(monkeypatch):
    rid = synclog.begin("nightly")
    synclog.reset()
    monkeypatch.setenv(synclog.ENV_RUN, rid)
    synclog.note("summary", "xhs-x", True)
    synclog.finish_command("enrich")
    assert rows()[0]["items"][0]["kind"] == "summary"
    assert rows()[0]["finished_at"] is None, "带编号的子进程不收尾（夜跑自己收）"


def test_nothing_recorded_without_a_sync():
    """平时手动跑 enrich / videos，不在任何一次同步里：不记、不开新行。"""
    synclog.note("vision", "xhs-a", True)
    synclog.finish_command("enrich")
    assert rows() == []


def test_keeps_last_200_runs():
    path = synclog.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = "".join(json.dumps(synclog._new_row(f"r{i}", "nightly", "own")) + "\n" for i in range(205))
    path.write_text(blob + "坏行\n", encoding="utf-8")
    synclog.begin("manual")
    got = rows()
    assert len(got) == synclog.MAX_RUNS and got[0]["run_id"] == "r6"


def test_load_marks_running_and_stale():
    path = synclog.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old = synclog._new_row("old", "nightly", "auto")
    old["started_at"] = old["updated_at"] = (datetime.now().astimezone() - timedelta(hours=20)).isoformat(timespec="seconds")
    now = synclog._new_row("now", "manual", "own")
    path.write_text(json.dumps(old) + "\n" + json.dumps(now) + "\n", encoding="utf-8")
    got = synclog.load()
    assert [r["run_id"] for r in got] == ["now", "old"]
    assert got[0].get("running") is True
    assert got[1].get("stale") is True and got[1]["finished_at"] == old["updated_at"]


def test_default_trigger(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert synclog.default_trigger(datetime(2026, 10, 3, 4, 0)) == "nightly"
    assert synclog.default_trigger(datetime(2026, 10, 3, 16, 0)) == "schedule"
    monkeypatch.setenv(synclog.ENV_TRIGGER, "manual")
    assert synclog.default_trigger(datetime(2026, 10, 3, 4, 0)) == "manual"


# ---------------------------------------------------------------- 重试

def _failed_run():
    rid = synclog.begin("nightly")
    synclog.note("attachment", "xhs-a", False, title="A", reason="超时")
    synclog.note("video", "xhs-b", False, title="B", reason="服务没开")
    synclog.note("summary", "xhs-c", False, title="C", reason="接口 500")
    synclog.note("vision", "xhs-c", False, title="C", reason="接口 500")
    synclog.note("note", None, False, title="D", reason="页面打不开", url="https://www.xiaohongshu.com/explore/d")
    synclog.note("attachment", "xhs-e", False, title="E", reason="没转成文字", retry=["pdf2md", "xhs-e"])
    synclog.note("note", "xhs-f", True, title="F")
    synclog.error("nightly.embed", "超过 25 分钟", "TRANSIENT.STEP_TIMEOUT")
    synclog.error("nightly.sync-favorites", "掉登录", "NOT_LOGGED_IN")
    synclog.flush()
    synclog.end(rid)
    return rid


def test_retry_plan_maps_failures_to_existing_commands():
    rid = _failed_run()
    jobs, notes = synclog.retry_plan(rows()[0])
    cmds = [j["cmd"] for j in jobs]
    assert ["attachments", "xhs-a"] in cmds and ["videos", "xhs-b", "--transcribe"] in cmds
    assert cmds.count(["enrich", "--item", "xhs-c"]) == 1, "同一篇识图 + 概要只跑一次"
    assert ["ingest", "https://www.xiaohongshu.com/explore/d", "--origin", "cli"] in cmds
    assert ["pdf2md", "xhs-e"] in cmds and ["embed"] in cmds
    assert any("立即同步" in n for n in notes), "碰号的同步那一步不在这里重跑，说清楚"
    assert ["sync-favorites"] not in [c[:1] for c in cmds]
    assert rid


def test_retry_runs_only_failures_and_records_honestly():
    rid = _failed_run()
    ran = []

    def runner(cmd, run_id, timeout):
        ran.append(cmd)
        assert run_id == rid
        if cmd[0] == "videos":   # 子进程自己记了结果（还是没好）
            os.environ[synclog.ENV_RUN] = run_id
            try:
                synclog.reset()
                synclog.note("video", "xhs-b", False, reason="还是没开")
                synclog.flush()
            finally:
                os.environ.pop(synclog.ENV_RUN, None)
            return 2, "", False
        if cmd[0] == "ingest":
            return 1, "Traceback…\n抓不到：笔记已删除", False
        if cmd[0] == "embed":
            return None, "", True
        return 0, "", False
    out = synclog.retry(rid, runner=runner)
    assert len(ran) == 6
    row = rows()[0]
    by = {(it["kind"], it.get("id") or it.get("url")): it for it in row["items"]}
    assert by[("attachment", "xhs-a")]["ok"] is True and by[("summary", "xhs-c")]["ok"] is True
    assert by[("video", "xhs-b")]["ok"] is False and by[("video", "xhs-b")]["reason"] == "还是没开", "子进程记的为准"
    assert by[("note", "https://www.xiaohongshu.com/explore/d")]["reason"] == "抓不到：笔记已删除"
    assert any(e["step"] == "nightly.embed" for e in row["errors"]), "超时的那步还挂着"
    assert row["retried_at"] and row["error"] is True
    assert out["ok"] is False and out["message"].startswith("重跑了 6 项，成了 3 项") and "立即同步" in out["message"]
    # 都好了：步骤级报错也摘掉
    out2 = synclog.retry(rid, runner=lambda cmd, run_id, timeout: (0, "", False))
    row = rows()[0]
    assert all(it["ok"] for it in row["items"])
    assert [e["step"] for e in row["errors"]] == ["nightly.sync-favorites"]
    assert out2["ok"] is True or out2["notes"]


def test_retry_nothing_to_do_and_unknown_run():
    rid = synclog.begin("manual")
    synclog.note("note", "xhs-a", True)
    synclog.flush()
    assert synclog.retry(rid, runner=lambda *a: pytest.fail("没有失败项不该跑"))["message"] == "这次没有失败项要重试"
    assert synclog.retry("nope")["ok"] is False


# ---------------------------------------------------------------- 记录点

def test_sync_favorites_records_new_and_failed(monkeypatch):
    from link_brain import favorites as fav
    favs = [{"note_id": n, "url": f"https://www.xiaohongshu.com/explore/{n}", "title": f"标题-{n}"} for n in ("a", "b", "c")]
    monkeypatch.setattr(fav, "fetch_favorites", lambda **k: favs)
    monkeypatch.setattr(fav, "_already_archived", lambda f: f["note_id"] == "c")
    out_by = {"a": {"item_id": "xhs-a", "status": "new", "title": "标题-a", "_source_id": "a"},
              "b": {"item_id": None, "status": "error", "url": favs[1]["url"], "error": "页面打不开"},
              "c": {"item_id": "xhs-c", "status": "hit", "_source_id": "c"}}
    monkeypatch.setattr(fav, "_sync_one", lambda f, **k: dict(out_by[f["note_id"]]))
    synclog.begin("manual")
    fav.sync_favorites()
    synclog.flush()
    row = rows()[0]
    assert row["new"] == 1
    items = {it["title"]: it for it in row["items"]}
    assert items["标题-a"]["ok"] is True
    assert items["标题-b"]["ok"] is False and items["标题-b"]["url"] == favs[1]["url"] and items["标题-b"]["id"] == "xhs-b"
    assert "标题-c" not in items, "已在库的不算这次处理的"


def test_cli_sync_favorites_manual_opens_and_closes_a_line(monkeypatch, capsys):
    from link_brain import accounts, favorites as fav
    monkeypatch.setenv(synclog.ENV_TRIGGER, "manual")
    monkeypatch.setattr(accounts, "check_risk_hold", lambda: None)

    class Sess:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(accounts, "account_session", Sess)
    monkeypatch.setattr(fav.sync_state, "record", lambda *a, **k: None)

    def fake_sync(**k):
        synclog.count_new(1)
        synclog.note("note", "xhs-z", True, title="Z")
        return {"favorites": 1, "synced": 1, "items": [{"item_id": "xhs-z", "status": "new"}]}
    monkeypatch.setattr(fav, "sync_favorites", fake_sync)
    rc = cli.main(["sync-favorites"])
    assert rc == 0
    [row] = rows()
    assert row["trigger"] == "manual" and row["finished_at"] and row["new"] == 1 and row["exit"] == 0


def test_attachments_enrich_videos_record(monkeypatch):
    from link_brain import attachments, enrich, videos
    synclog.begin("manual")
    attachments._report_downloads({"item_id": "xhs-a", "title": "A", "visible_note": "Web/A.md"},
                                  [{"status": "downloaded"}, {"status": "already"},
                                   {"status": "deferred", "error": "时间到了"}])
    attachments._report_downloads({"item_id": "xhs-b", "title": "B"}, [{"status": "failed", "name": "b.pdf", "error": "超时"}])
    # enrich：补之前缺识图 + 概要，补完概要好了、识图还缺
    calls = []
    monkeypatch.setattr(enrich, "needs", lambda *a, **k: (calls.append(1), ["vision", "summary"] if len(calls) == 1 else ["vision"])[1])
    monkeypatch.setattr(enrich, "_child", lambda *a: enrich._CHILD_INCOMPLETE)
    monkeypatch.setattr(enrich, "_title", lambda *a: "C")
    enrich.enrich_one("xiaohongshu", "c")
    videos._report({"item_id": "xhs-d", "title": "D"}, {"status": "no_speech"})
    videos._report({"item_id": "xhs-e", "title": "E"}, {"status": "failed", "error": "服务没开"})
    videos._report({"item_id": "xhs-f", "title": "F"}, {"status": "skipped", "error": "没开"})
    synclog.flush()
    by = {(it["kind"], it["id"]): it for it in rows()[0]["items"]}
    assert by[("attachment", "xhs-a")]["ok"] is True and by[("attachment", "xhs-a")]["note"] == "Web/A.md"
    assert by[("attachment", "xhs-b")]["ok"] is False and by[("attachment", "xhs-b")]["reason"] == "b.pdf：超时"
    assert by[("summary", "xhs-c")]["ok"] is True and by[("vision", "xhs-c")]["ok"] is False
    assert by[("video", "xhs-d")]["ok"] is True and by[("video", "xhs-e")]["ok"] is False
    assert ("video", "xhs-f") not in by, "没开的不记"


def test_nightly_opens_one_line_children_join_it_and_it_closes(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir(exist_ok=True)
    monkeypatch.setattr(Nightly, "running_sync", lambda self: None)
    repo = str(storage.repo_root())
    child = ("import os,sys;sys.path.insert(0,r'%s');from link_brain import synclog;"
             "print('run='+os.environ.get('LINK_BRAIN_SYNC_RUN',''));"
             "synclog.note('video','xhs-v',True,title='V');synclog.flush()" % repo)
    job = Nightly(steps=[Step("videos --transcribe", [], 1, argv=[PY, "-c", child], reserve_min=0),
                         Step("embed", [], 1, argv=[PY, "-c", "raise SystemExit(3)"], reserve_min=0)],
                  log_path=tmp_path / "nightly.log", workdir=tmp_path, sleep=lambda s: None)
    out = job.run()
    [row] = rows()
    assert ("run=" + row["run_id"]) in job.log_path.read_text("utf-8"), "每一步子进程带着这一晚的编号"
    assert row["items"][0]["title"] == "V"
    assert row["finished_at"] and row["exit"] == out["exit"] == 1
    assert any(e["step"] == "nightly.embed" for e in row["errors"]), "步骤出错也进这一行"


def test_cli_list_begin_end_record(capsys):
    assert cli.main(["synclog", "begin", "--trigger", "nightly"]) == 0
    rid = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["run_id"]
    assert cli.main(["synclog", "record", "--step", "nightly.catalog", "--error", "超时被杀"]) == 0
    capsys.readouterr()
    assert cli.main(["synclog", "end"]) == 0
    capsys.readouterr()
    assert cli.main(["synclog", "list"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] and out["runs"][0]["run_id"] == rid and out["runs"][0]["finished_at"]
    assert out["runs"][0]["errors"][0]["reason"] == "超时被杀"
    assert out["backlog"] is None and out["kinds"]["note"] == "正文"


def test_backlog_row_from_setup_backfill(monkeypatch):
    from link_brain.setup import backfill as bf
    monkeypatch.setattr(bf, "backfill", lambda: {"favorites_total": 1159, "archived": 361, "deferred": 798, "days_left": 16,
                                                 "daily_limit": 50})
    b = synclog.backlog()
    assert b["message"] == "一共 1159 篇收藏，已入库 361 篇，预计还要 16 天同步完"
    monkeypatch.setattr(bf, "backfill", lambda: {"favorites_total": 1159, "archived": 1159, "deferred": 0, "days_left": 0})
    assert synclog.backlog() is None, "积压清零不显示"
