"""Lot R2 会话面（后端）：会话级排除 / 保留（pin）显式传入并生效；证据带身份（评论楼号、图序号）。

GPT 场景表三例：「pin 后补搜」（pin 不丢、新来源能进）、「删多源支持的一条来源」（按剩下的重答不引用已删）、
排除压过保留。全部合成数据，不调模型。"""
import io
import json

from link_brain import ask, storage

ITEMS = [{"id": f"t{i}", "title": f"交通攻略 {i}", "tags": [], "summary": "", "note": f"t{i}.md", "url": "",
          "search_fields": {"body": f"机场到市区的交通路线 {i}，地铁和巴士。"}} for i in range(4)]
ITEMS.append({"id": "food", "title": "甜品店", "tags": [], "summary": "", "note": "food.md", "url": "",
              "search_fields": {"body": "这家蛋糕很好吃。"}})


def _setup(monkeypatch, seen=None):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    monkeypatch.setattr(ask, "llm_expansions", lambda *a, **k: {"terms": [], "status": "mock"})
    monkeypatch.setattr("link_brain.retrieval.semantic_hits", lambda *a: None)
    recorded = []
    monkeypatch.setattr(ask.answer_cache, "record", lambda *a, **k: recorded.append(a))
    monkeypatch.setattr(ask, "call_text", lambda p, text, s: (seen.append(text) if seen is not None else None)
                        or {"status": "ok", "text": "答[来源1]"})
    return recorded


def _ids(result):
    return [s["id"] for s in result["sources"]], [s["id"] for s in result["related"]]


def test_no_constraints_unchanged(monkeypatch):
    recorded = _setup(monkeypatch)
    plain = ask.answer("交通路线")
    assert "constraints" not in plain and len(recorded) == 1
    again = ask.answer("交通路线", exclude_ids=[], pin_ids=None)
    assert _ids(again) == _ids(plain)


def test_exclude_drops_source_everywhere_and_skips_cache(monkeypatch):
    recorded = _setup(monkeypatch)
    phases = []
    r = ask.answer("交通路线", exclude_ids=["t0"], on_phase=phases.append)
    primary, related = _ids(r)
    assert "t0" not in primary + related and {"t1", "t2", "t3"} <= set(primary)
    assert r["constraints"] == {"excluded": ["t0"], "pinned": []}
    assert recorded == []
    assert any("已排除 1 条" in p for p in phases)


def test_pin_kept_first_and_new_sources_still_come_in(monkeypatch):
    seen = []
    _setup(monkeypatch, seen)
    # 甜品店和「交通」一个字都不沾：保留了它，补搜交通时它照样在主要依据第一条，交通的新来源也都进来
    r = ask.answer("交通路线", pin_ids=["food"])
    primary, _ = _ids(r)
    assert primary[0] == "food" and {"t0", "t1", "t2", "t3"} <= set(primary)
    assert "[来源1] 甜品店" in seen[-1] and "[来源1] 是用户手动加入的来源" in seen[-1]
    assert r["constraints"]["pinned"] == ["food"]


def test_exclusion_beats_pin(monkeypatch):
    _setup(monkeypatch)
    r = ask.answer("交通路线", pin_ids=["food", "t1"], exclude_ids=["t1"])
    primary, related = _ids(r)
    assert primary[0] == "food" and "t1" not in primary + related
    assert r["constraints"] == {"excluded": ["t1"], "pinned": ["food"]}


def test_reask_with_kept_sources_never_uses_excluded(monkeypatch):
    seen = []
    _setup(monkeypatch, seen)
    r = ask.answer("交通路线", source_ids=["t0", "t1", "t2"], exclude_ids=["t1"])
    assert _ids(r)[0] == ["t0", "t2"] and "交通攻略 1" not in seen[-1]
    assert r["pinned"] is True


def test_bad_constraint_types_are_ignored(monkeypatch):
    _setup(monkeypatch)
    r = ask.answer("交通路线", exclude_ids="t0", pin_ids=[1, None, {"x": 1}])
    assert r["status"] == "ok" and "constraints" not in r and "t0" in _ids(r)[0]


def test_cli_request_passes_constraints(monkeypatch):
    got = {}
    monkeypatch.setattr(ask, "answer", lambda *a, **k: got.update(k) or {"status": "ok", "markdown": "x"})
    monkeypatch.setattr(ask, "dump_json", lambda result: None)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"question": "q", "exclude_ids": ["a"], "pin_ids": ["b"]})))
    assert ask.run(type("A", (), {"request_stdin": True})()) == ask.EXIT_OK
    assert got == {"exclude_ids": ["a"], "pin_ids": ["b"]}


def _object(tmp_path):
    obj = tmp_path / "_archive" / "xiaohongshu" / "x1"
    (obj / "raw" / "v0001").mkdir(parents=True)
    (obj / "derived").mkdir(parents=True)
    (obj / "meta.json").write_text(json.dumps({"current_version": 1}), encoding="utf-8")
    comments = [{"comment_id": "aa11", "text": "不加汤就完美了", "sub_comments": []},
                {"comment_id": "bb22", "text": "担担面是没有汤的", "sub_comments": [{"comment_id": "cc33", "text": "那是燃面吧，做法不统一"}]}]
    (obj / "raw" / "v0001" / "source.json").write_text(json.dumps({"comments": comments}, ensure_ascii=False), encoding="utf-8")
    images = [{"asset": "image-001.webp", "status": "ok", "ocr": "第一张图只有封面标题文字而已没有别的内容"},
              {"asset": "image-002.webp", "status": "failed"},
              {"asset": "comment-aa11-1.webp", "status": "ok", "ocr": "小贴士：牛肉逆纹切条，黑胡椒多放一点更香"}]
    (obj / "derived" / "vision.json").write_text(json.dumps({"images": images}, ensure_ascii=False), encoding="utf-8")
    (obj / "derived" / "agent.md").write_text("# x", encoding="utf-8")
    return {"id": "x1", "agent_md": "_archive/xiaohongshu/x1/derived/agent.md", "search_fields": {
        "comments": "不加汤就完美了\n担担面是没有汤的\n那是燃面吧，做法不统一",
        "ocr": "第一张图只有封面标题文字而已没有别的内容\n小贴士：牛肉逆纹切条，黑胡椒多放一点更香"}}


def test_evidence_identity_comment_floor_and_image_number(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    item = _object(tmp_path)
    parts = ask.locate_excerpts(item, [
        {"field": "comments", "text": "有汤的\n那是燃面吧"},           # 逐字切片：跨 c2 和 c2.1
        {"field": "comments", "text": "不加汤就完美了"},
        {"field": "ocr", "text": "小贴士：牛肉逆纹切条"},
        {"field": "ocr", "text": "封面标题文字"},
        {"field": "body", "text": "正文"}])
    assert parts[0]["comment_labels"] == ["c2", "c2.1"]
    assert parts[1]["comment_labels"] == ["c1"]
    assert parts[2]["images"] == ["评论c1的图1"] and parts[2]["assets"] == ["comment-aa11-1.webp"]
    assert parts[3]["images"] == ["图1"]
    assert parts[4] == {"field": "body", "text": "正文"}
    assert [p["text"] for p in parts] == ["有汤的\n那是燃面吧", "不加汤就完美了", "小贴士：牛肉逆纹切条", "封面标题文字", "正文"]


def test_evidence_identity_fail_open_without_object(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    parts = [{"field": "comments", "text": "x"}, {"field": "ocr", "text": "y"}]
    assert ask.locate_excerpts({"id": "nope", "agent_md": "_archive/a/b/derived/agent.md"}, parts) == parts
    assert ask.locate_excerpts({"id": "nope"}, parts) == parts
