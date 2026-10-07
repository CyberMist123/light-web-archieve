"""批次 D 地基：read.outcome —— 新 CLI 最后一行 JSON 的统一外形（CONVENTIONS §1）。"""

import json

from link_brain import read


def test_outcome_adds_three_keys_and_keeps_old_ones():
    payload = {"total": 3, "path": "_archive/x.json", "results": [{"item_id": "a", "status": "ok"}]}
    out = read.outcome(payload, ok=True, message="已删除 3 篇")
    assert out == {**payload, "ok": True, "code": "", "message": "已删除 3 篇"}
    assert "ok" not in payload and "message" not in payload, "不改调用方的原对象"


def test_outcome_code_defaults_to_existing_code_then_empty():
    assert read.outcome({"code": "RISK_HOLD"}, ok=False, message="风控冷却中")["code"] == "RISK_HOLD"
    assert read.outcome({}, ok=False, message="没做完")["code"] == ""
    assert read.outcome({"code": None}, ok=True, message="好了")["code"] == ""
    assert read.outcome({"code": "RISK_HOLD"}, ok=False, message="x", code="NEEDS_HUMAN.NOT_LOGGED_IN")["code"] == "NEEDS_HUMAN.NOT_LOGGED_IN"
    assert read.outcome(None, ok=True, message="完成") == {"ok": True, "code": "", "message": "完成"}


def test_outcome_ok_is_bool_and_message_is_text():
    out = read.outcome({"n": 1}, ok=1, message=None)
    assert out["ok"] is True and out["message"] == ""


def test_dump_outcome_is_single_json_line(capsys):
    read.dump_json(read.outcome({"notes": 2}, ok=True, message="已导出 2 篇（带原图）"))
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"notes": 2, "ok": True, "code": "", "message": "已导出 2 篇（带原图）"}
    assert "已导出" in lines[0], "中文原样输出（ensure_ascii=False）"
