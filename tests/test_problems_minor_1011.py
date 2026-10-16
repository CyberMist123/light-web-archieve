"""1011（她：自愈的就不要显示报错）：问题面板只列「现在还要人看一眼」的。

- 已解决（自愈 / 修好）的：不进 `problems list`、不进顶部计数，只在「复制报错」里（状态「已解决」）；
- 轻微的：评论续读放弃了、但楼中楼只缺 ≤2 条（不影响阅读）——同样不列、不计数、「全部修一遍」不为它开页，
  诊断导出照留（状态「轻微（不进列表）」）；缺 3 条以上 / 续读报错（认不出缺几条）的照常列。

全部是本地文件操作（临时 vault，conftest 隔离），不开页、不碰号。
"""
from __future__ import annotations

import json

import pytest

from link_brain import alert as alert_mod, cli, problems, repair, report

FILL = "PERMANENT.COMMENTS_INCOMPLETE"


@pytest.fixture(autouse=True)
def quiet_alerts(monkeypatch):
    monkeypatch.setattr(alert_mod, "_alert", lambda *a, **k: True)


def _incomplete(item, n=None, *, reason=None, missing=None):
    reason = reason or f"前 10 楼的楼中楼还缺 {n} 条：这楼当时没展开；连着 3 次续读都没多拿到，先不自动读了"
    return problems.report("comments.fill", FILL, reason, item_id=item, title="合成标题", action="gave_up", missing=missing)


def _list(capsys, *extra):
    assert cli.main(["problems", "list", *extra]) == 0
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_minor_comment_gap_not_listed_or_counted_but_exported(capsys):
    one = _incomplete("xhs-one", 1)
    two = _incomplete("xhs-two", missing=2, reason="楼中楼没补全（新写法也认 missing 字段）")
    many = _incomplete("xhs-many", 7)
    err = _incomplete("xhs-err", reason="评论续读连着 3 次没成：AdapterError: 合成报错")
    assert problems.is_minor(one) and problems.is_minor(two)
    assert not problems.is_minor(many) and not problems.is_minor(err)
    out = _list(capsys)
    keys = {r["key"] for r in out["problems"]}
    assert keys == {problems.FOLD_PREFIX + "PERMANENT.COMMENTS_INCOMPLETE"}, "1017：两篇并成一条"
    assert {i["key"] for i in out["problems"][0]["items"]} == {many["key"], err["key"]}, "只缺 ≤2 条的不进面板；缺 7 条 / 续读报错的照常列"
    s = out["summary"]
    assert s["gave_up"] == 1 and s["minor"] == 2 and s["hidden"] == 0, "1017：并成一条，计数也只算一条"
    assert problems.summary()["last_runs"]["comments.fill"]["ok"] is False  # 还有真问题开着
    # --all（诊断用）照样带回来，并标 minor
    all_rows = {r["key"]: r for r in _list(capsys, "--all")["problems"]}
    assert all_rows[one["key"]]["minor"] is True and all_rows[many["key"]]["minor"] is False
    # 复制报错：留着，状态写「轻微」
    text = problems.export_redacted()
    line = next(x for x in text.splitlines() if "xhs-one" in x)
    assert "轻微（不进列表）" in line
    assert "轻微（不进列表）2" in text


def test_only_minor_open_means_step_ok_and_badge_zero():
    _incomplete("xhs-one", 1)
    s = problems.summary()
    assert (s["needs_human"], s["auto"], s["gave_up"], s["hidden"], s["minor"]) == (0, 0, 0, 0, 1)
    assert s["last_runs"]["comments.fill"]["ok"] is True
    problems.write_summary()
    on_disk = json.loads(problems.summary_path().read_text(encoding="utf-8"))
    assert on_disk["gave_up"] == 0 and on_disk["minor"] == 1


def test_resolved_rows_not_listed_but_exported(capsys):
    row = problems.report("embed", "TRANSIENT.NETWORK", "连不上")
    problems.resolve("embed")
    out = _list(capsys)
    assert out["problems"] == []
    assert out["summary"]["auto"] == 0
    line = next(x for x in problems.export_redacted().splitlines() if "TRANSIENT.NETWORK" in x)
    assert "已解决" in line and row["step"] in line


def test_minor_skipped_by_repair_all_and_group_dismiss_but_single_still_runs():
    one = _incomplete("xhs-one", 1)
    called = []
    run = lambda argv, t: called.append(argv) or (1, "", False)  # noqa: E731
    repair.run(execute=run)
    assert called == [], "「全部修一遍」不为看不见的轻微条目开页"
    out = problems.dismiss(group="gave_up")
    assert out["dismissed"] == []
    repair.run(key=one["key"], execute=run)  # 点名单条（诊断里照着 key 跑）照样能修
    assert len(called) == 1


def test_minor_hidden_row_not_in_hidden_section(capsys):
    one = _incomplete("xhs-one", 2)
    # 老数据：她以前隐藏过的轻微条目，现在既不在列表也不在「已隐藏」计数里
    problems._append([{"ts": one["ts"], "key": one["key"], "step": "comments.fill", "item_id": "xhs-one",
                       "code": FILL, "dismiss": True, "by": "owner"}])
    out = _list(capsys)
    assert out["problems"] == [] and out["summary"]["hidden"] == 0 and out["summary"]["minor"] == 1


def test_minor_not_open_in_weekly_report():
    _incomplete("xhs-one", 1)
    flat = [p for v in report._day_problems().values() for p in v]
    assert flat and all(p["open"] is False for p in flat if p["item_id"] == "xhs-one")


def test_comment_fill_report_carries_missing_count():
    row = _incomplete("xhs-one", 1, missing=1)
    assert row["missing"] == 1
    assert next(r for r in problems.load() if r["key"] == row["key"])["missing"] == 1
