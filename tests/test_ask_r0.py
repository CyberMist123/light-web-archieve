import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tools"))
import ask_eval
from link_brain import ask


def test_coverage_denominator():
    gold = {str(index) for index in range(10)}
    ids = list(map(str, range(8)))
    assert ask_eval._coverage(ids, gold, 8) == .8
    assert ask_eval._recall(ids, gold, 8) == 1
    assert ask_eval._coverage(["0", "0"], gold, 2) == .1
    assert ask_eval._coverage([], set(), 8) is None


def test_stages_and_holdout(monkeypatch):
    monkeypatch.setattr(ask, "llm_expansions", lambda *args, **kwargs: {"terms": ["烤箱"], "status": "mock"})
    items = [{"id": "recipe", "title": "面包", "search_fields": {"body": "烤箱面包步骤"}},
             {"id": "other", "title": "交通", "search_fields": {"body": "车站地图"}},
             {"id": "third", "title": "小说", "search_fields": {"body": "情节"}}]
    cases = [{"question": "面包", "expected": ["recipe"], "set": "train"},
             {"question": "面包", "expected": ["missing"], "must_pool": ["missing"], "set": "holdout"}]
    report = ask_eval.evaluate(cases, items, use_semantic=False, expand_llm=False)
    assert report["summary"]["coverage_at_8"] == 1
    assert report["summary"]["sets"]["holdout"]["coverage_at_8"] == 0
    assert report["summary"]["tuning_questions"] == 1
    assert report["summary"]["blocked"]
    assert report["results"][1]["false_rejection"] == ["missing"]
    stages = report["results"][0]["stages"]
    assert {"lexical", "semantic", "expansion", "fusion", "candidate_pool", "primary"} <= stages.keys()
    assert stages["expansion"] == [{"term": "烤箱", "ids": ["recipe"]}]
    assert stages["primary"][0]["evidence"] == [["body", 6]]
    assert report["results"][0]["evidence_budget"] == ask.evidence_budget(8000, 800, 1)
