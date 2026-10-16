"""1008（L6·B2）：问题面板「隐藏」——只隐藏已放弃的、可恢复、照样导出；隐藏到解决为止；删笔记撤问题；
「全部修一遍」不再拿当场修过没好的已放弃条目反复花钱；last_runs 按步骤取最近一次结论。

全部是本地文件操作（临时 vault，conftest 隔离），不开页、不碰号。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from link_brain import alert as alert_mod, cli, problems, repair, report, storage

TZ = timezone(timedelta(hours=10))
REFINE = "PERMANENT.PDF_ENCRYPTED"  # 1017：精细识图放弃不再登记，「已放弃」样例换成附件转不出


def at(day, hour=4):
    return lambda: datetime(2026, 10, day, hour, 0, tzinfo=TZ)


@pytest.fixture(autouse=True)
def quiet_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_mod, "_alert", lambda *a, **k: sent.append(a) or True)
    return sent


def _gave_up(item="xhs-aaa", reason="a.pdf：有打开密码"):
    return problems.report("attachments.convert", REFINE, reason, item_id=item, title="合成标题")


def _one(key):
    return next(r for r in problems.load(include_resolved=True) if r["key"] == key)


def test_dismiss_only_gave_up_rows():
    cap = problems.report("login", "CAPTCHA_REQUIRED", "要验证")
    probe = problems.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", "没查清", item_id="xhs-p")
    row = _gave_up()
    for r in (cap, probe):
        out = problems.dismiss(key=r["key"])
        assert out["ok"] is False and out["code"] == "NOT_DISMISSABLE" and out["message"]
    out = problems.dismiss(key=row["key"])
    assert out["ok"] and out["dismissed"] == [row["key"]]
    assert _one(row["key"])["hidden"] is True
    assert _one(cap["key"])["hidden"] is False


def test_dismissed_not_counted_and_hidden_reported():
    row = _gave_up()
    _gave_up(item="xhs-bbb")
    assert problems.summary()["gave_up"] == 2
    problems.dismiss(key=row["key"])
    s = problems.summary()
    assert s["gave_up"] == 1 and s["hidden"] == 1
    on_disk = storage.read_json(problems.summary_path())
    assert on_disk["gave_up"] == 1 and on_disk["hidden"] == 1


def test_dismiss_survives_same_cause_recurrence():
    row = _gave_up()
    problems.dismiss(key=row["key"])
    _gave_up()  # 同一篇、同一 key 又报一次（自愈轮 / 夜跑再撞）
    r = _one(row["key"])
    assert r["hidden"] is True and r["hidden_repeats"] == 1 and r["count"] == 2
    assert problems.summary()["gave_up"] == 0


def test_dismiss_reappears_after_resolve_then_recur():
    row = _gave_up()
    problems.dismiss(key=row["key"])
    problems.resolve("attachments.convert", "xhs-aaa", REFINE)
    _gave_up()
    r = _one(row["key"])
    assert r["hidden"] is False and not r.get("dismissed_at")
    assert problems.summary()["gave_up"] == 1


def test_dismiss_survives_compaction(monkeypatch):
    monkeypatch.setattr(problems, "MAX_KEYS", 5)
    for n in range(8):
        problems.report("embed", "TRANSIENT.NETWORK", f"n{n}", item_id=f"xhs-{n}", _now_fn=at(1 + n % 3))
    row = _gave_up()
    problems.dismiss(key=row["key"])
    problems.compact()
    rows = problems._fold(problems._read_rows())
    assert len(problems._read_rows()) <= 5 and problems.is_hidden(rows[row["key"]])
    _gave_up()  # 压实之后再复发一次也还藏着
    r = problems._fold(problems._read_rows())[row["key"]]
    assert problems.is_hidden(r) and r["hidden_repeats"] == 1


def test_undismiss_restores():
    row = _gave_up()
    problems.dismiss(key=row["key"])
    out = problems.undismiss(row["key"])
    assert out["ok"] and out["restored"] == [row["key"]]
    assert _one(row["key"])["hidden"] is False and problems.summary()["hidden"] == 0


def test_dismiss_group_gave_up_batch():
    a, b = _gave_up(), _gave_up(item="xhs-bbb")
    cap = problems.report("login", "CAPTCHA_REQUIRED", "要验证")
    probe = problems.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", "没查清", item_id="xhs-p")
    out = problems.dismiss(group="gave_up")
    assert out["ok"] and sorted(out["dismissed"]) == sorted([a["key"], b["key"]])
    assert not _one(cap["key"])["hidden"] and not _one(probe["key"])["hidden"]
    assert "恢复" in out["message"]


def test_cli_dismiss_undismiss_json_shape(capsys):
    row = _gave_up()
    assert cli.main(["problems", "dismiss", "--key", row["key"]]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert {"ok", "code", "message", "dismissed"} <= set(out) and out["dismissed"] == [row["key"]]
    assert cli.main(["problems", "undismiss", "--key", row["key"]]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["restored"] == [row["key"]]
    cap = problems.report("login", "CAPTCHA_REQUIRED", "要验证")
    assert cli.main(["problems", "dismiss", "--key", cap["key"]]) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is False and out["code"] == "NOT_DISMISSABLE"
    assert cli.main(["problems", "dismiss", "--group", "gave_up"]) == 0


def test_export_marks_hidden_rows():
    row = _gave_up()
    problems.dismiss(key=row["key"])
    text = problems.export_redacted()
    line = next(x for x in text.splitlines() if "xhs-aaa" in x)
    assert "已隐藏" in line and "已隐藏 1" in text


def test_repair_all_skips_failed_permanent_but_single_still_runs():
    row = _gave_up()
    called = []
    run = lambda argv, t: called.append(argv) or (1, "还是复读", False)  # noqa: E731
    repair.run(execute=run)  # 第一次：「全部修一遍」照样试一次
    assert called == [["pdf2md", "xhs-aaa", "--force"]]
    repair.run(execute=run)  # 当场修过没好：不再进「全部修一遍」（不再花钱）
    assert len(called) == 1
    repair.run(key=row["key"], execute=run)  # 点名单条照样跑
    assert len(called) == 2


def test_repair_all_skips_hidden_rows():
    row = _gave_up()
    problems.dismiss(key=row["key"])
    called = []
    repair.run(execute=lambda argv, t: called.append(argv) or (1, "", False))
    assert called == []


def test_describe_permanent_repeated_failure_suggests_hide():
    _gave_up()
    _gave_up()
    r = next(x for x in problems.load() if x["step"] == "attachments.convert")
    assert "已失败 2 次" in r["status_text"] and "隐藏" in r["status_text"]
    assert r["dismissable"] is True


def test_remove_item_resolves_its_problems():
    _gave_up(item="xhs-gone")
    problems.report("attachments.recheck", "TRANSIENT.PROBE_FAILED", "没查清", item_id="xhs-gone")
    problems.report("embed", "TRANSIENT.NETWORK", "连不上")
    assert problems.resolve_item("xhs-gone") == 2
    left = problems.load()
    assert [r["step"] for r in left] == ["embed"]


def test_report_day_problems_hidden_not_open():
    row = _gave_up()
    problems.dismiss(key=row["key"])
    days = report._day_problems()
    flat = [p for v in days.values() for p in v]
    assert flat and all(p["open"] is False for p in flat if p["item_id"] == "xhs-aaa")
    assert len([p for p in flat if p["item_id"] == "xhs-aaa"]) == 1  # 隐藏行 / 注记行不另算一条


def test_last_runs_reflect_latest_result_per_step():
    problems.report("embed", "TRANSIENT.NETWORK", "连不上", _now_fn=at(5))
    assert problems.summary()["last_runs"]["embed"]["ok"] is False
    problems.resolve("embed", None, _now_fn=at(6))
    row = problems.summary()["last_runs"]["embed"]
    assert row["ok"] is True and row["ts"].startswith("2026-10-06")


def test_captcha_pushes_again_on_new_incident(quiet_alerts):
    problems.report("login", "CAPTCHA_REQUIRED", "04:01 读收藏时判到验证", _now_fn=at(8, 4))
    problems.report("login", "CAPTCHA_REQUIRED", "同一次，另一条路又登一回", _now_fn=lambda: datetime(2026, 10, 8, 4, 1, 30, tzinfo=TZ))
    assert len(quiet_alerts) == 1, "同一次出事只推一次"
    problems.report("login", "CAPTCHA_REQUIRED", "05:19 又撞了一次", _now_fn=lambda: datetime(2026, 10, 8, 5, 19, tzinfo=TZ))
    assert len(quiet_alerts) == 2, "面板没刷掉之前又撞一次新的：当时就通知"
    problems.report("login", "RISK_HOLD", "熔断中", _now_fn=at(8, 6))
    assert len(quiet_alerts) == 3  # RISK_HOLD 是另一个码，原规则：没推过就推一次
    problems.report("login", "RISK_HOLD", "熔断中", _now_fn=at(8, 7))
    assert len(quiet_alerts) == 3, "熔断中不算新出事"


def test_delete_note_resolves_its_problems_via_remove(tmp_path, monkeypatch):
    """真入口：remove.delete_items 删一篇 → 它名下没解决的问题都标已解决，别的篇不动。"""
    from link_brain import index as index_mod, remove
    from link_brain.adapters import xiaohongshu as xhs
    import test_remove as tr

    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: tr._fake_parsed(text))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: tr._fixture())
    cli.main(["ingest", "https://example.invalid/share"])
    conn = index_mod.connect()
    item_id = index_mod.find_object(conn, xhs.SOURCE, tr.NOTE_ID)["item_id"]
    conn.close()
    _gave_up(item=item_id)
    _gave_up(item="xhs-other")
    assert remove.delete_items([item_id])["deleted"] == 1
    assert [r["item_id"] for r in problems.load()] == ["xhs-other"]
