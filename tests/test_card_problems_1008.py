"""1008（L6·B2）：目录卡片问题角标——减去她隐藏的、过期的接口码不再标（1009 起连灰色「待补」也不上卡片）、原帖打不开出标；
卡片有标、面板没有的精细识图失败一次性补登记（1017 起作废，精细识图放弃不算故障）。全部本地文件。"""
from __future__ import annotations

from link_brain import ai_health, catalog, cli, problems, storage


def _obj(sid="6aa00000"):
    obj = storage.archive_root() / "xiaohongshu" / sid
    (obj / "derived").mkdir(parents=True, exist_ok=True)
    storage.write_json(obj / "meta.json", {"item_id": f"xhs-{sid}", "current_version": 1})
    return obj


def _codes(obj, *, vision=None, extracted=None):
    rows = catalog.item_problems(obj, {"item_id": f"xhs-{obj.name}", "errors": []}, vision or {}, {}, extracted or {})
    return [r["code"] for r in rows]


def test_item_problems_skips_dismissed_pairs():
    obj = _obj()
    storage.write_json(obj / "attachments.json", {"files": [{"name": "a.pdf", "sha256": "s1",
                       "conversion_failed": {"sha256": "s1", "code": "PERMANENT.PDF_ENCRYPTED", "note": "有密码"}}]})
    assert _codes(obj) == ["PERMANENT.PDF_ENCRYPTED"]
    row = problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "x", item_id=f"xhs-{obj.name}")
    problems.dismiss(key=row["key"])
    assert _codes(obj) == []
    problems.undismiss(row["key"])
    assert _codes(obj) == ["PERMANENT.PDF_ENCRYPTED"]


def test_refine_gave_up_gets_no_card_badge_1017():
    """1017 作者裁决：精细识别没过、退回第一层不是故障——卡片不出「AI 结果不可用」（机读版里标识图存疑）。"""
    obj = _obj()
    vision = {"images": [{"asset": "a/image-006.webp", "refine": {"status": "failed", "error": "复读"}}]}
    assert _codes(obj, vision=vision) == []


def test_item_problems_drops_stale_api_codes_when_ai_health_clear():
    obj = _obj()
    vision = {"images": [{"visual": {"status": "failed", "code": "NEEDS_HUMAN.AUTH_FAILED", "error": "401"}}]}
    extracted = {"status": "failed", "code": "NEEDS_HUMAN.AUTH_FAILED", "error": "401"}
    # ai-health 里没有这两个能力（key 早好了）：1009 她——后台静默补，卡片上不标（以前降成灰色「待补」）
    assert _codes(obj, vision=vision, extracted=extracted) == []
    # ai-health 里识图还开着：识图那条照原码出；概要那侧已好，不标
    storage.write_json(storage.archive_root() / ai_health.FILE_NAME, {"visionAI": {"code": "NEEDS_HUMAN.AUTH_FAILED"}})
    assert _codes(obj, vision=vision, extracted=extracted) == ["NEEDS_HUMAN.AUTH_FAILED"]
    # 不是接口码（这篇自己的问题）不受影响
    own = {"status": "failed", "code": "PERMANENT.MODEL_OUTPUT_INVALID", "error": "坏"}
    assert _codes(obj, extracted=own) == ["PERMANENT.MODEL_OUTPUT_INVALID"]


def test_gone_note_gets_card_badge_only():
    obj = _obj()
    storage.write_json(obj / "derived" / "web_recheck.json", {"ok": True, "gone": True})
    rows = catalog.item_problems(obj, {"item_id": f"xhs-{obj.name}", "errors": []}, {}, {}, {})
    assert [r["code"] for r in rows] == ["PERMANENT.NOTE_GONE"] and "本地存档还在" in rows[0]["hover"]
    assert problems.load() == []


def test_orphan_refine_not_backfilled_after_1017(capsys):
    """1008 的一次性补登记（卡片有标、面板没有的精细识图失败）1017 起作废：精细识图放弃不是故障，新库第一次打开面板也不补登记。"""
    obj = _obj()
    storage.write_json(obj / "derived" / "vision.json", {"images": [
        {"asset": "raw/v0001/assets/image-003.webp",
         "refine": {"status": "failed", "error": "出现复读", "at": "2026-10-02T05:28:00+11:00"}}]})
    assert cli.main(["problems", "list"]) == 0
    assert [r for r in problems.load() if r["step"] == "vision.refine"] == []
    assert cli.main(["problems", "list"]) == 0
    assert [r for r in problems.load() if r["step"] == "vision.refine"] == []
    capsys.readouterr()


def test_light_mode_shows_no_ai_badges():
    """1009 她：轻量版（「开始」页没勾 AI）本来就不做识图 / 概要——卡片上什么都不标（附件 / 原帖打不开这类照旧）。"""
    from link_brain import ai_config
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(p, {"setup": {"selected": ["core", "reader", "dataview", "ocr"], "aiSynced": True}})
    catalog._CTX.update(key=None)
    obj = _obj("6aa00001")
    vision = {"images": [{"visual": {"status": "failed", "code": "TRANSIENT.HTTP_5XX", "error": "503"},
                          "refine": {"status": "failed", "error": "复读"}}]}
    extracted = {"status": "failed", "code": "PERMANENT.MODEL_OUTPUT_INVALID", "error": "坏"}
    storage.write_json(obj / "enrich-state.json", {"fails": 5, "last_error": "x"})
    storage.write_json(storage.archive_root() / ai_health.FILE_NAME, {"visionAI": {"code": "TRANSIENT.HTTP_5XX"}})
    assert _codes(obj, vision=vision, extracted=extracted) == []
    storage.write_json(obj / "derived" / "web_recheck.json", {"ok": True, "gone": True})
    assert _codes(obj, vision=vision, extracted=extracted) == ["PERMANENT.NOTE_GONE"]
    # 勾回 AI：这篇自己的失败照常出标
    storage.write_json(p, {"setup": {"selected": ["core", "reader", "dataview", "ocr", "ai_text", "ai_vision"], "aiSynced": True}})
    catalog._CTX.update(key=None)
    got = _codes(obj, vision=vision, extracted=extracted)
    assert "TRANSIENT.RETRY_EXHAUSTED" in got
    assert "PERMANENT.MODEL_OUTPUT_INVALID" not in got, "1017：精细识别没过不出标（机读版标识图存疑）"
