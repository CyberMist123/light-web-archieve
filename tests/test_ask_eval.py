"""问收藏检索回归（合成数据，纯词法、不联网）：tests/fixtures/ask_eval_synthetic.json。

真库评测用 tests/tools/ask_eval.py（题目放仓外）；这里用同一个 evaluate() 跑合成版。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import ask_eval  # noqa: E402

from link_brain import ask  # noqa: E402

DATA = json.loads((Path(__file__).parent / "fixtures" / "ask_eval_synthetic.json").read_text(encoding="utf-8"))
K = 3


@pytest.fixture(scope="module")
def report():
    return ask_eval.evaluate(DATA["cases"], items=DATA["items"], k=K, use_semantic=False)


@pytest.mark.parametrize("index", range(len(DATA["cases"])), ids=[c["question"] for c in DATA["cases"]])
def test_case(report, index):
    case, row = DATA["cases"][index], report["results"][index]
    if case.get("mode"):
        assert row["mode"] == case["mode"], row
    assert (row[f"recall_at_{K}"] or 0) >= case["min_recall"], row
    top = [r["id"] for r in row["top"]]
    for bad in case.get("not_top") or []:
        assert bad not in top, row


def test_summary_recall(report):
    assert report["summary"][f"recall_at_{K}"] >= .95


def test_query_terms_drop_function_word_fragments():
    terms = ask.query_terms("推荐几个适合新手的低脂早餐")
    assert {"低脂", "早餐", "新手"} <= set(terms)
    assert not {"的低", "手的", "几个", "个适"} & set(terms)
    assert "那澳" not in ask.query_terms("行 那日本好吃的")


def _qa(monkeypatch, question, history, selected):
    calls = []

    def model(prompt, text, settings):
        calls.append((prompt, text))
        if "收藏资料筛选器" in prompt:
            return {"status": "ok", "text": json.dumps({"selected": selected})}
        return {"status": "ok", "text": "据材料作答。[来源1]"}

    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in DATA["items"]])
    monkeypatch.setattr(ask, "call_text", model)
    # 字数预算调小（每篇约 700 字 → 只送 2 篇），让合成库也走到「挑选材料」那一步
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(
        ask.ai_config.DEFAULTS, {"retrieval": {"topK": 2, "totalCharLimit": 1400}}))
    monkeypatch.setattr("link_brain.retrieval.semantic_hits", lambda q: None)
    hist = [m for q in history for m in ({"role": "user", "content": q}, {"role": "assistant", "content": "（略）"})]
    return ask.answer(question, hist), calls


def test_selection_empty_keeps_titled_hits(monkeypatch):
    """挑材料挑空，但前几条标题标签就写着「三体」：排到前面交给作答模型核对，不直接答「没有」。"""
    r, calls = _qa(monkeypatch, "三体相关", ["广州好吃的", "东京好吃的"], [])
    assert any("收藏资料筛选器" in p for p, _ in calls)
    assert r.get("selection_kept") is True
    ids = [s["id"] for s in r["sources"]]
    assert len(ids) == 2 and set(ids) <= {"dmbj-1", "dmbj-2", "dmbj-3"}


def test_selection_empty_no_longer_drops_candidates(monkeypatch):
    """第 10 批：挑空了也不丢候选（以前直接答「候选收藏中没有符合」）——材料照样送去，提示作答模型逐条核对、真没有就直说；
    其余候选回给页面（「其他相关」）。"""
    r, calls = _qa(monkeypatch, "广州好吃的有哪些推荐", [], [])
    assert r.get("selection_empty") is True and r["sources"]
    answer_input = calls[-1][1]
    assert "真没有符合的就直说没有" in answer_input
    assert all(s["tier"] == "primary" for s in r["sources"]) and all(s["tier"] == "related" for s in r["related"])


def test_selection_only_reorders(monkeypatch):
    """挑选只排序：挑中的排前面，没挑中的照样在来源里（不再硬上限 5 篇）。"""
    r, calls = _qa(monkeypatch, "三体相关", [], [3])
    ids = [s["id"] for s in r["sources"]] + [s["id"] for s in r["related"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 3
    assert "筛选认为最符合" in calls[-1][1]
