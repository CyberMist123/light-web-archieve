"""10-04：手动导入（catch）和自愈轮也进同步记录。"""
from __future__ import annotations

from link_brain import catch, repair, synclog


def test_manual_import_gets_its_own_row(monkeypatch):
    monkeypatch.delenv(synclog.ENV_RUN, raising=False)
    monkeypatch.delenv(synclog.ENV_TRIGGER, raising=False)
    synclog.reset()
    catch._log_import({"found": 2, "items": [
        {"item_id": "xhs-a", "status": "new", "title": "甲", "visible_note": "Web/甲.md"},
        {"item_id": None, "status": "error", "url": "https://example.invalid/x", "error": "没抓到"},
    ]})
    synclog.finish_command("catch", None, 1)
    rows = synclog.load()
    assert len(rows) == 1
    row = rows[0]
    assert row["trigger"] == "import" and row["finished_at"] and row["new"] == 1
    assert synclog.TRIGGER_CN["import"] == "手动导入"
    assert "手动导入" in synclog.summary_line(row)
    kinds = [(it["kind"], it["ok"]) for it in row["items"]]
    assert ("note", True) in kinds and ("note", False) in kinds


def test_import_inside_another_run_joins_it(monkeypatch):
    synclog.reset()
    rid = synclog.begin("nightly", own=True)
    monkeypatch.setenv(synclog.ENV_RUN, rid)
    catch._log_import({"found": 1, "items": [{"item_id": "xhs-b", "status": "new", "title": "乙"}]})
    synclog.flush()
    rows = synclog.load()
    assert len(rows) == 1 and rows[0]["trigger"] == "nightly" and rows[0]["new"] == 1


def test_repair_round_opens_and_closes_a_repair_row(monkeypatch):
    monkeypatch.delenv(synclog.ENV_RUN, raising=False)
    synclog.reset()
    rid = repair._open_log()
    assert rid and __import__("os").environ.get(synclog.ENV_RUN) == rid
    repair._close_log(rid, [{"status": "unresolved", "step": "vision.refine", "message": "已试：换模型；没好：复读"},
                            {"status": "resolved", "step": "embed", "message": "已修好"}])
    assert synclog.ENV_RUN not in __import__("os").environ
    row = synclog.load()[0]
    assert row["trigger"] == "repair" and row["finished_at"]
    assert [e["step"] for e in row["errors"]] == ["repair.vision.refine"]
    assert synclog.TRIGGER_CN["repair"] == "自愈"
