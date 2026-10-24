"""1024 第 1 波 p0-runtime：CLI 子命令漏出未知异常 → 最后一行是合法的 outcome JSON，问题记录登记一条。"""

from __future__ import annotations

import json

from link_brain import cli, night_captcha, problems, vision


def _boom(args):
    raise RuntimeError("意外的坏数据")


def test_unknown_exception_prints_outcome_and_reports(monkeypatch, capsys):
    monkeypatch.setattr(night_captcha, "run", _boom)
    code = cli.main(["captcha-recover"])
    out, err = capsys.readouterr()
    assert code == cli.EXIT_ERROR
    last = json.loads(out.strip().splitlines()[-1])
    assert last["ok"] is False and last["code"] == "TRANSIENT.STEP_CRASHED"
    assert "意外的坏数据" in last["message"] and "RuntimeError" in last["message"]
    assert "意外的坏数据" in err.strip().splitlines()[-1], "stderr 最后一行是给人看的原因"
    rows = [r for r in problems.load() if r["step"] == "cli.captcha-recover"]
    assert len(rows) == 1 and rows[0]["code"] == "TRANSIENT.STEP_CRASHED"
    assert problems.step_label("cli.captcha-recover") == "命令：captcha-recover"


def test_crash_resolved_when_command_later_succeeds(monkeypatch, capsys):
    monkeypatch.setattr(night_captcha, "run", _boom)
    cli.main(["captcha-recover"])
    monkeypatch.setattr(night_captcha, "run", lambda args: 0)
    assert cli.main(["captcha-recover"]) == 0
    assert not [r for r in problems.load() if r["step"] == "cli.captcha-recover"]


def test_problems_list_survives_retire_refine_crash(monkeypatch, capsys):
    def boom():
        raise OSError("vision.json 读不出来")
    monkeypatch.setattr(vision, "retire_refine_problems", boom)
    problems.report("embed", "TRANSIENT.NETWORK", "断网")
    assert cli.main(["problems", "list"]) == 0
    out = capsys.readouterr().out
    assert "断网" in out
