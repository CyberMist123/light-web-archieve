"""10-04 选集：目录页存的 `_archive/selections.json` → 本地 MCP（lb_selections / lb_selection）和远程阅读（selections /
read_selection）按名字只读取回。合成数据，conftest 已把 vault 指到 tmp；不联网、不调模型。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from link_brain import selections, storage
from link_brain.remote import tools as rtools
from link_brain.remote.policy import Denied, Policy

from test_mcp_server import _call_tool, _client

A_NOTE = "Web/Xiaohongshu/图数据库入门__aaa.md"
A_AGENT = "_archive/xiaohongshu/aaa/derived/agent.md"
B_AGENT = "_archive/xiaohongshu/bbb/derived/agent.md"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make(vault: Path, rows=None) -> Path:
    _w(vault / A_NOTE, "# 图数据库入门\n")
    _w(vault / A_AGENT, "# 图数据库入门（机读版）\n\n" + "图数据库正文。" * 3000)
    _w(vault / B_AGENT, "# 知识图谱怎么画（机读版）\n\n短正文")
    storage.write_json(vault / "_archive" / "catalog-data.json", {"items": [
        {"id": "xhs-aaa", "title": "图数据库入门", "url": "https://example.test/a", "note": A_NOTE, "agent_md": A_AGENT,
         "tags": ["graph"], "summary": "s", "search_fields": {}},
        {"id": "xhs-bbb", "title": "知识图谱怎么画", "url": "https://example.test/b", "note": None, "agent_md": B_AGENT,
         "tags": ["graph"], "summary": "", "search_fields": {}},
    ]})
    storage.write_json(vault / "_archive" / "selections.json", {"selections": rows if rows is not None else [
        {"name": "graph1004", "ids": ["xhs-aaa", "xhs-bbb", "xhs-gone"], "created_at": "2026-10-04T15:00:00+10:00"},
        {"name": "旧的一组", "ids": ["xhs-bbb"], "created_at": "2026-10-01T09:00:00+10:00"},
        {"name": "坏的", "ids": []},
        "垃圾",
    ]})
    return vault


@pytest.fixture
def vault():
    return make(Path(os.environ[storage.ENV_VAULT]))


def test_load_and_find_by_loose_name(vault):
    rows = selections.load()
    assert [r["name"] for r in rows] == ["graph1004", "旧的一组"]   # 新的在前；空 / 坏条目丢掉
    assert selections.find("Graph 1004", rows)[0]["name"] == "graph1004"
    assert selections.find("「graph1004」", rows)[0]["name"] == "graph1004"
    assert selections.find("graph", rows)[0]["name"] == "graph1004"     # 唯一包含
    assert selections.find("没有这个", rows) == (None, [])


def test_missing_or_broken_file_is_empty(vault):
    (vault / "_archive" / "selections.json").write_text("{坏", encoding="utf-8")
    assert selections.load() == []
    assert selections.list_selections()["count"] == 0


def test_list_gives_names_times_and_titles(vault):
    out = selections.list_selections()
    first = out["selections"][0]
    assert first["name"] == "graph1004" and first["created_at"].startswith("2026-10-04") and first["count"] == 3
    assert first["titles"][:2] == ["图数据库入门", "知识图谱怎么画"] and "已不在库里" in first["titles"][2]


def test_local_mcp_tools(vault, tmp_path):
    client = _client(tmp_path, vault)
    try:
        client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {t["name"] for t in client.recv()["result"]["tools"]}
        assert {"lb_selections", "lb_selection"} <= names
        result, listed = _call_tool(client, "lb_selections", {}, 3)
        assert result["isError"] is False and listed["selections"][0]["titles"][0] == "图数据库入门"
        result, got = _call_tool(client, "lb_selection", {"name": "graph 1004"}, 4)
        assert result["isError"] is False and got["name"] == "graph1004" and got["count"] == 2
        a, b = got["items"]
        assert a["title"] == "图数据库入门" and a["source_url"] == "https://example.test/a"
        assert Path(a["agent_md"]) == vault / A_AGENT and Path(a["visible_note"]) == vault / A_NOTE
        assert a["truncated"] is True and len(a["text"]) == selections.TEXT_PER_ITEM and a["text_total_chars"] > 8000
        assert b["text"].endswith("短正文") and b["truncated"] is False and b["visible_note"] is None
        assert got["missing"] == ["xhs-gone"]
        result, bad = _call_tool(client, "lb_selection", {"name": "不存在"}, 5)
        assert result["isError"] is True and "graph1004" in bad["available"]
        result, empty = _call_tool(client, "lb_selection", {}, 6)
        assert result["isError"] is True
    finally:
        client.close()


def test_remote_tools_follow_policy(vault):
    pol = Policy.build(vault, ["@xhs"])
    assert {"selections", "read_selection"} <= rtools.NAMES and all(
        t["annotations"]["readOnlyHint"] for t in rtools.TOOLS)
    listed = rtools.HANDLERS["selections"](pol, {})
    assert listed["selections"][0]["name"] == "graph1004"
    got = rtools.HANDLERS["read_selection"](pol, {"name": "GRAPH1004"})
    a, b = got["items"]
    assert (a["path"], a["agent_md"]) == (A_NOTE, A_AGENT)            # 相对路径，过白名单
    assert a["truncated"] is True and len(a["text"]) == selections.TEXT_PER_ITEM
    assert b["path"] is None and b["text"].endswith("短正文")
    json.dumps(got, ensure_ascii=False)                                # 可 JSON 化
    with pytest.raises(Denied) as e:
        rtools.HANDLERS["read_selection"](pol, {"name": "不存在"})
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(Denied):
        rtools.HANDLERS["read_selection"](pol, {})
    # 没开放小红书收藏库：选集也读不到
    closed = Policy.build(vault, [])
    with pytest.raises(Denied):
        rtools.HANDLERS["selections"](closed, {})
    with pytest.raises(Denied):
        rtools.HANDLERS["read_selection"](closed, {"name": "graph1004"})


def test_text_budget_caps_total(vault, monkeypatch):
    monkeypatch.setattr(selections, "TEXT_TOTAL", 9000)
    got = selections.get_selection("graph1004", paths=lambda it: {}, read_text=selections.read_agent)
    a, b = got["items"]
    assert len(a["text"]) == 8000 and len(b["text"]) <= 1000
