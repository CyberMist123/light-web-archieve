"""MCP 轻目录（1018）：search 不给 query = 按入库时间翻目录；added_on / added_since / added_until / tag 硬过滤（筛空就是空）；
每行带 tags、source_url；没概要退回正文开头。"""
from __future__ import annotations

import json
from pathlib import Path

from link_brain import ask, retrieval, storage


def _obj(vault: Path, sid: str) -> str:
    obj = vault / "_archive" / "xiaohongshu" / sid
    (obj / "raw" / "v0001").mkdir(parents=True)
    (obj / "derived").mkdir(parents=True)
    (obj / "meta.json").write_text(json.dumps({"current_version": 1}), encoding="utf-8")
    note = {"title": "x", "body": "正文", "author": {"user_id": "u0", "nickname": "作者"}}
    (obj / "raw" / "v0001" / "source.json").write_text(json.dumps({"note": note, "comments": []}, ensure_ascii=False), encoding="utf-8")
    (obj / "derived" / "agent.md").write_text("# x", encoding="utf-8")
    return f"_archive/xiaohongshu/{sid}/derived/agent.md"


def _ctx(monkeypatch):
    from link_brain import mcp_tools as mt
    from link_brain.remote.policy import Policy
    vault = storage.vault_root()
    items = [
        {"id": "xhs-aaa", "title": "向女性游戏玩家推荐一个播客", "author": "甲", "date": "2026-10-18", "ts": "2026-10-18T21:00:00+11:00",
         "published": "2023-09-24", "kind": "image", "summary": "", "tags": ["独立游戏", "播客推荐"], "hashtags": ["#女性主义"],
         "url": "https://www.xiaohongshu.com/explore/aaa", "agent_md": _obj(vault, "aaa"), "note": None,
         "search_fields": {"body": "女性独立游戏设计师从女性主义视角分析游戏" * 10}},
        {"id": "xhs-bbb", "title": "火锅蘸料", "author": "乙", "date": "2026-10-17", "ts": "2026-10-17T09:00:00+11:00",
         "published": "2026-10-18", "kind": "image", "summary": "麻酱加蒜泥。后面不要。", "tags": ["火锅"],
         "url": "https://www.xiaohongshu.com/explore/bbb", "agent_md": _obj(vault, "bbb"), "note": None,
         "search_fields": {"body": "火锅"}},
    ]
    monkeypatch.setattr(ask, "load_items", lambda: items)
    monkeypatch.setattr(mt, "_items", lambda: items)
    monkeypatch.setattr(retrieval, "semantic_hits", lambda *a, **k: None)
    monkeypatch.setattr(retrieval, "semantic_deep", lambda *a, **k: None)
    return mt, mt.Ctx(policy=Policy.build(vault, ["@xhs"]), local=False, who="测试")


def test_browse_without_query_lists_newest_first_with_tags_and_url(monkeypatch):
    mt, c = _ctx(monkeypatch)
    res = mt.search(c, {"detail": "brief", "limit": 50})
    assert [r["id"] for r in res["results"]] == ["aaa", "bbb"] and res["found"] == 2
    a = res["results"][0]
    assert a["tags"] == ["独立游戏", "播客推荐", "女性主义"] and a["source_url"].endswith("/aaa") and "hits" not in a
    assert a["summary"].startswith("女性独立游戏设计师") and len(a["summary"]) <= 121   # 没概要 → 正文开头，≤120 字
    assert res["results"][1]["summary"] == "麻酱加蒜泥。"


def test_added_on_is_archive_day_not_publish_day_and_strict(monkeypatch):
    mt, c = _ctx(monkeypatch)
    # bbb 发帖日是 10-18、入库是 10-17：added_on 只认入库
    assert [r["id"] for r in mt.search(c, {"added_on": "2026-10-18"})["results"]] == ["aaa"]
    assert [r["id"] for r in mt.search(c, {"added_since": "2026-10-17", "added_until": "2026-10-17"})["results"]] == ["bbb"]
    empty = mt.search(c, {"added_on": "2026-01-01"})
    assert empty["found"] == 0 and empty["results"] == [] and "入库" in empty["note"]   # 筛空不退回全库


def test_cli_browse_lines_and_offset(monkeypatch, capsys):
    import argparse
    mt, _ = _ctx(monkeypatch)
    ns = argparse.Namespace(query="", date=None, since="2026-10-01", until=None, tag=None, limit=1, offset=0, json=False)
    assert mt.run_browse(ns) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("aaa｜2026-10-18｜向女性游戏玩家推荐一个播客｜#独立游戏 #播客推荐 #女性主义｜女性独立游戏设计师")
    assert out[-1] == "共 2 篇，下一页 --offset 1"
    ns.tag, ns.since = "露营", None
    assert mt.run_browse(ns) == 0 and "相近" in capsys.readouterr().out


def test_tag_filter_exact_then_contains_and_suggests(monkeypatch):
    mt, c = _ctx(monkeypatch)
    assert [r["id"] for r in mt.search(c, {"tag": "#女性主义"})["results"]] == ["aaa"]   # hashtag 也算，# 不计
    assert [r["id"] for r in mt.search(c, {"tag": "播客"})["results"]] == ["aaa"]        # 整词没有 → 包含
    miss = mt.search(c, {"tag": "露营"})
    assert miss["found"] == 0 and "火锅" in miss["note"]
    assert [r["id"] for r in mt.search(c, {"query": "火锅", "tag": "火锅"})["results"]] == ["bbb"]
