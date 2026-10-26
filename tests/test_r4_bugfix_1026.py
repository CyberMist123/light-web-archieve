"""1026 zcode 第四轮报的三处小 bug：修前红、修后绿。"""
from __future__ import annotations

import json

import pytest

from link_brain import comment_fill, mention, providers, rerank, storage
from link_brain.setup import components, pipeline


def test_pipeline_comments_stage_failed_when_worker_not_started(monkeypatch, tmp_path):
    # setup/pipeline.py：spawn_worker 回 ok=False 时，「补评论」这一步不能标成功、总结果也不能算成功
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setattr(components, "check", lambda targets: {"results": []})
    monkeypatch.setattr(pipeline, "selected", lambda: list(pipeline.LIGHT))
    monkeypatch.setattr(providers, "resolve", lambda cap: None)
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": False, "message": "起不来"})
    monkeypatch.setattr(comment_fill, "survey", lambda: {"pending": 0, "missing": 0})
    result = pipeline.run(lambda ev: None, child=lambda args, **kw: (0, False), account_check=lambda: ("", ""))
    row = {r["id"]: r for r in result["stages"]}["comments"]
    assert row["state"] == "failed"
    assert "没拉起来" in row["text"]
    assert not result["ok"]


@pytest.mark.parametrize("raw", ['"abc"', "[1]", "3"])
def test_mention_pending_skips_non_object_meta(tmp_path, monkeypatch, raw):
    # mention.py：meta.json 是合法 JSON 但不是对象时，当它没有 meta（回退 前缀-来源id），不让整个 pending 崩
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    d = tmp_path / "vault" / storage.ARCHIVE_DIRNAME / "xiaohongshu" / "abc"
    d.mkdir(parents=True)
    (d / "notes.json").write_text(json.dumps({"annotations": [
        {"id": "m1", "ts": "2026-10-25T10:00:00Z", "text": "@Fable", "to_fable": True}]}), encoding="utf-8")
    (d / "meta.json").write_text(raw, encoding="utf-8")
    assert [r["item_id"] for r in mention.pending()] == ["xhs-abc"]


@pytest.mark.parametrize("data", [{"output": "字符串"}, {"output": [1]}, {"output": {"results": "x"}}])
def test_rerank_scores_odd_output_raises_rerank_error(data):
    # rerank.py：output 不是对象时也要抛 RerankError（调用方只接这个来回退），不能漏出 AttributeError
    with pytest.raises(rerank.RerankError):
        rerank._scores(data, 2)


def test_ask_turns_latest_for_who_compares_instants_not_strings(tmp_path, monkeypatch):
    # ask_turns.py：+10:00 与 +11:00 混着时，字符串大的不一定是更晚的那轮
    from datetime import datetime
    from link_brain import ask_turns
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_ASK_TURNS", str(tmp_path / "turns.json"))
    # 01:55+10:00 = 15:55Z（更晚）；02:50+11:00 = 15:50Z（更早，但字符串更大）
    (tmp_path / "turns.json").write_text(json.dumps({"turns": {   # record() 会把 ts 改成现在，这里直接写表
        "late": {"who": "w", "ts": "2026-10-05T01:55:00+10:00"},
        "early": {"who": "w", "ts": "2026-10-05T02:50:00+11:00"}}}), encoding="utf-8")
    now = datetime.fromisoformat("2026-10-05T03:00:00+11:00")
    assert ask_turns.latest_for_who("w", now=now)["turn_id"] == "late"
