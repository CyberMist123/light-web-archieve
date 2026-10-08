"""批次 D · F1-d：改坏的笔记检测（diagnose，与插件 noteDamage 共用样本）+ scan 登记 / 解除 + repair 的 render.check 计划。

共用样本 tests/fixtures/note_damage_cases.json：base = 一份标准渲染输出；cases = [{name, patch, expect}]，
patch 是一串操作：["replace", 旧, 新]（只换第一处）/ ["cut", 起, 止]（从第一处「起」删到其后第一处「止」含）。
重新生成：LB_REGEN_DAMAGE=1 python -m pytest tests/test_note_damage_1009.py -o addopts= -q
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from link_brain import problems, render as render_mod, repair, restore, storage
from tests._l5_objects import add_media
from tests.test_restore_1009 import obj  # noqa: F401

FIXTURE = Path(__file__).parent / "fixtures" / "note_damage_cases.json"


def apply_patch(text: str, patch: list) -> str:
    for op in patch:
        if op[0] == "replace":
            text = text.replace(op[1], op[2], 1)
        elif op[0] == "cut":
            s = text.find(op[1])
            e = text.find(op[2], s)
            if s != -1 and e != -1:
                text = text[:s] + text[e + len(op[2]):]
    return text


def _cases(base: str) -> list[dict]:
    iid_line = next(ln for ln in base.split("\n") if ln.strip().startswith("item_id:"))
    cc_line = next(ln for ln in base.split("\n") if ln.startswith("cssclasses:"))
    return [
        {"name": "完好", "patch": []},
        {"name": "删了 CONTENT 开始标记", "patch": [["replace", render_mod.CONTENT_START, ""]]},
        {"name": "整个 CONTENT 层删了", "patch": [["cut", render_mod.CONTENT_START, render_mod.CONTENT_END]]},
        {"name": "删了 item_id", "patch": [["replace", iid_line + "\n", ""]]},
        {"name": "cssclasses 少了 xhs-note", "patch": [["replace", cc_line, "cssclasses: [link-brain]"]]},
        {"name": "两栏块被换行拆开", "patch": [["replace", '<div class="lb-main">', '\n<div class="lb-main">']]},
        {"name": "删了留言结束标记", "patch": [["replace", render_mod.COMMENTS_END, ""]]},
        {"name": "批注块没了", "patch": [["replace", "annotate-view.js", "x-view.js"]]},
        {"name": "frontmatter 写坏", "patch": [["replace", cc_line, "cssclasses: [link-brain, xhs-note\nbad:\n  - [unclosed\n  - x: : y"]]},
    ]


@pytest.mark.skipif(os.environ.get("LB_REGEN_DAMAGE") != "1", reason="只在重新生成共用样本时跑")
def test_regen_fixture(obj):
    add_media(obj, images=2)
    restore.restore(obj["item_id"])
    base = obj["vis"].read_text(encoding="utf-8")
    cases = _cases(base)
    for c in cases:
        c["expect"] = restore.diagnose(apply_patch(base, c["patch"]))
    FIXTURE.write_text(json.dumps({"base": base, "cases": cases}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


EXPECT = {
    "完好": [],
    "删了 CONTENT 开始标记": ["CONTENT_MARKERS_MISSING"],
    "整个 CONTENT 层删了": ["CONTENT_MARKERS_MISSING", "NOTE_BLOCK_MISSING"],
    "删了 item_id": ["ITEM_ID_MISSING"],
    "cssclasses 少了 xhs-note": ["CSSCLASSES_MISSING"],
    "两栏块被换行拆开": ["NOTE_BLOCK_SPLIT"],
    "删了留言结束标记": ["COMMENTS_MARKERS_MISSING"],
    "批注块没了": ["ANNOTATE_BLOCK_MISSING"],
    "frontmatter 写坏": ["FRONTMATTER_BROKEN", "CSSCLASSES_MISSING"],
}


def test_shared_cases_match():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert {c["name"] for c in data["cases"]} == set(EXPECT)
    for c in data["cases"]:
        assert c["expect"] == EXPECT[c["name"]], c["name"]
        assert restore.diagnose(apply_patch(data["base"], c["patch"])) == c["expect"], c["name"]


@pytest.mark.parametrize("variant", ["none", "images", "video", "comment_image"])
def test_fresh_renders_are_clean(obj, variant):
    if variant == "images":
        add_media(obj, images=3)
    elif variant == "video":
        add_media(obj, images=1, video=True)
    elif variant == "comment_image":
        add_media(obj, images=1, comment_image=True)
    assert restore.restore(obj["item_id"])["ok"]
    text = obj["vis"].read_text(encoding="utf-8")
    assert restore.diagnose(text) == []
    assert render_mod.stray_human_lines(text) == ([], [])


def _open(step=restore.STEP):
    return [r for r in problems.load() if r.get("step") == step]


def test_scan_reports_then_resolves(obj):
    obj["vis"].write_text(obj["clean"].replace(render_mod.CONTENT_END, "", 1), encoding="utf-8")
    out = restore.scan(report=True)
    assert out["damaged"] == 1 and out["results"][0]["issues"] == ["CONTENT_MARKERS_MISSING"]
    rows = _open()
    assert len(rows) == 1 and rows[0]["code"] == "PERMANENT.NOTE_DAMAGED" and rows[0]["item_id"] == obj["item_id"]
    restore.scan(report=True)
    assert len(_open()) == 1
    obj["vis"].write_text(obj["clean"], encoding="utf-8")
    restore.scan(report=True)
    assert _open() == []


def _row(obj):
    return {"step": restore.STEP, "code": "PERMANENT.NOTE_DAMAGED", "item_id": obj["item_id"], "key": "k"}


def _age(obj, hours):
    t = time.time() - hours * 3600
    os.utime(obj["vis"], (t, t))


def test_plan_wait_run_gave_up(obj, monkeypatch):
    now = datetime.now().astimezone()
    _age(obj, 1)
    p = repair.plan(_row(obj), now)
    assert p["kind"] == "wait" and p["action"] == "restore" and "24 小时" in p["why"]
    _age(obj, 30)
    monkeypatch.delenv(repair.ENV_AUTO_RESTORE, raising=False)
    p = repair.plan(_row(obj), now)
    assert p["kind"] == "run" and p["action"] == "restore" and p["auto"] is False   # 夜里自愈默认关
    monkeypatch.setenv(repair.ENV_AUTO_RESTORE, "1")
    assert repair.plan(_row(obj), now)["auto"] is True
    p = repair.plan({**_row(obj), "action": "gave_up"}, now)
    assert p["kind"] == "run" and p["auto"] is False


@pytest.mark.parametrize("on", [False, True])
def test_auto_round_scans_first_and_runs_restore_only_when_enabled(obj, monkeypatch, on):
    if on:
        monkeypatch.setenv(repair.ENV_AUTO_RESTORE, "1")
    else:
        monkeypatch.delenv(repair.ENV_AUTO_RESTORE, raising=False)
    obj["vis"].write_text(obj["clean"].replace(render_mod.CONTENT_END, "", 1), encoding="utf-8")
    _age(obj, 72)
    calls = []

    def execute(argv, timeout):
        calls.append(argv)
        return 0, "", False
    noon = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    repair.run(auto=True, execute=execute, now_fn=lambda: noon)
    hit = [a for a in calls if "restore" in a]
    if on:
        assert hit and hit[0][hit[0].index("restore"):] == ["restore", obj["item_id"], "--json"]
    else:
        assert hit == []
