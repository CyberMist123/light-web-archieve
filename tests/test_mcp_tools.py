"""10-09 LWA 专属 MCP：一份工具定义（link_brain/mcp_tools.py），本机 stdio 与远程共用。

每个工具一条以上：search（紧凑字段 + 搜索历史 md）· ask（透传、不真调模型）· read（id / 链接 / part / raw 清单）·
image · files（白名单、越界拒）· topics（增改删 + 钉文章）· selections（暗号解析边界 + 存）· recent · history；
并发写（暗号、主题、搜索历史）不丢不坏；stdio 真入口每个工具调一次。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from link_brain import mcp_tools as mt
from link_brain import storage, topics as tmod
from link_brain.remote.policy import Denied, Policy

from test_mcp_server import _call_tool, _client
from test_remote_mcp import AGENT, ATT, NOTE, OTHER, make_vault

IDS = ["abc12345", "bbb22222", "ccc33333"]


def _now_iso(days_ago: float = 0) -> str:
    return (datetime.now().astimezone() - timedelta(days=days_ago)).isoformat(timespec="seconds")


@pytest.fixture
def vault(monkeypatch):
    v = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(v)
    data = storage.read_json(v / "_archive" / "catalog-data.json")
    first = data["items"][0]
    first["ts"] = _now_iso(1)
    for sid, title, ago in (("bbb22222", "番茄炒蛋", 3), ("ccc33333", "很久以前的帖子", 40)):
        data["items"].append({**first, "id": "xhs-" + sid, "title": title, "note": None,
                              "agent_md": f"_archive/xiaohongshu/{sid}/derived/agent.md",
                              "summary": f"{title}的概要。第二句不要。", "date": _now_iso(ago)[:10], "ts": _now_iso(ago),
                              "search_fields": {"body": title}})
        (v / f"_archive/xiaohongshu/{sid}/derived").mkdir(parents=True, exist_ok=True)
        (v / f"_archive/xiaohongshu/{sid}/derived/agent.md").write_text(
            f"# {title}\n\n## 概要\n\n{title}概要\n\n## 原文\n\n正文\n\n## 评论\n\n- 评论一\n", encoding="utf-8")
    storage.write_json(v / "_archive" / "catalog-data.json", data)
    monkeypatch.setattr(mt, "rebuild_catalog_async", lambda: "queued")
    return v


def ctx(vault, folders=("@xhs",), local=False):
    return mt.Ctx(policy=Policy.build(vault, list(folders)), local=local, who="测试")


# ---------------------------------------------------------------- 定义

def test_one_definition_schema_is_strict():
    names = [t["name"] for t in mt.TOOLS]
    assert names == ["search", "ask", "read", "image", "files", "topics", "selections", "recent", "history"]
    for t in mt.TOOLS:
        s = t["inputSchema"]
        assert s["type"] == "object" and s["additionalProperties"] is False and t["description"]
        for req in s.get("required", []):
            assert req in s["properties"]
    assert "花模型钱" in next(t for t in mt.TOOLS if t["name"] == "ask")["description"]
    from link_brain import mcp_server
    assert mcp_server.TOOLS is mt.TOOLS          # 本机和远程同一份


# ---------------------------------------------------------------- search + 历史

def test_search_compact_and_history(vault):
    c = ctx(vault)
    res = mt.search(c, {"query": "蒜香鱼片"})
    assert res["found"] == 1 and res["next_offset"] is None
    assert res["results"][0] == {"id": "abc12345", "title": "蒜香鱼片怎么做", "summary": "蒜香鱼片的做法",
                                 "date": "2026-09-01", "agent_md": AGENT}
    mt.search(c, {"query": "番茄"})
    mt.search(c, {"query": "番茄", "offset": 5})   # 续页不记
    text = mt.history_path().read_text("utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    assert text.count(f"## {today}") == 1
    lines = [l for l in text.splitlines() if l.startswith("- ")]
    assert len(lines) == 2 and "蒜香鱼片 · 测试 · 命中 1：蒜香鱼片怎么做" in lines[0]
    with pytest.raises(Denied):
        mt.search(c, {"query": "  "})


def test_history_new_day_gets_new_section_and_tail(vault):
    mt.record_search("旧的", ["A"], 1, "本机", now=datetime(2026, 1, 1, 9, 0).astimezone())
    mt.record_search("新的", [], 0, "本机", now=datetime(2026, 1, 2, 9, 0).astimezone())
    text = mt.history_path().read_text("utf-8")
    assert "## 2026-01-01" in text and "## 2026-01-02" in text and text.index("旧的") < text.index("## 2026-01-02")
    tail = mt.history(ctx(vault), {"lines": 1})
    assert tail["text"].startswith("## 2026-01-02") and "新的" in tail["text"]
    assert mt.history(ctx(vault), {"lines": 3})["total_lines"] > 3


def test_local_paths_are_absolute(vault):
    res = mt.search(ctx(vault, local=True), {"query": "蒜香鱼片"})
    assert Path(res["results"][0]["agent_md"]) == vault / AGENT


# ---------------------------------------------------------------- ask

def test_ask_passes_through(vault, monkeypatch):
    from link_brain import ask
    seen = []
    monkeypatch.setattr(ask, "answer", lambda q: seen.append(q) or {"status": "ok", "answer": "答"})
    assert mt.ask(ctx(vault), {"question": "鱼片怎么腌"})["answer"] == "答" and seen == ["鱼片怎么腌"]
    with pytest.raises(Denied):
        mt.ask(ctx(vault, folders=("其他资料",)), {"question": "x"})


# ---------------------------------------------------------------- read / image

def test_read_by_id_url_and_part(vault):
    c = ctx(vault)
    out = mt.read(c, {"id": "xhs-abc12345", "max_chars": 50})
    assert out["title"] == "蒜香鱼片怎么做" and out["agent_md"] == AGENT and out["next_offset"] == 50
    assert "raw/v0001/source.json" in out["raw_files"] and Path(out["raw_dir"]).is_dir()
    assert any(p.startswith("附件全文") for p in out["parts"])
    by_url = mt.read(c, {"id": "https://www.xiaohongshu.com/explore/bbb22222?xsec_token=x", "part": "评论"})
    assert by_url["id"] == "bbb22222" and by_url["text"].startswith("## 评论") and "原文" not in by_url["text"]
    with pytest.raises(Denied) as e:
        mt.read(c, {"id": "bbb22222", "part": "不存在的段"})
    assert "概要" in e.value.message
    with pytest.raises(Denied):
        mt.read(c, {"id": "nope0000"})
    with pytest.raises(Denied):
        mt.read(ctx(vault, folders=("其他资料",)), {"id": "abc12345"})
    assert mt.read(c, {"path": NOTE})["text"].startswith("# 蒜香鱼片")   # 旧客户端 read(path)


def test_image_denies_non_assets(vault):
    for bad in ("", "../x.png", AGENT, "C:/Windows/x.png"):
        with pytest.raises(Denied):
            mt.image(ctx(vault), {"path": bad})


# ---------------------------------------------------------------- files

def test_files_list_read_and_escapes(vault):
    c = ctx(vault, folders=("@xhs", "其他资料"))
    roots = mt.files(c, {})
    assert roots["kind"] == "dir" and "其他资料" in [e["path"] for e in roots["entries"]]
    assert mt.files(c, {"path": "其他资料"})["kind"] == "dir"
    assert "另一个文件夹" in mt.files(c, {"path": OTHER})["text"]
    for bad in ("../outside.md", "其他资料/../_archive/index.db", ".obsidian/app.json", "_trash/old.md",
                "C:/Windows/win.ini", "/etc/passwd", "其他资料\\plain.txt", "其他资料/api-key.txt"):
        with pytest.raises(Denied):
            mt.files(c, {"path": bad})
    with pytest.raises(Denied):
        mt.files(ctx(vault), {"path": OTHER})              # 没开放就读不到
    lc = ctx(vault, folders=("@xhs", "其他资料"), local=True)
    assert "另一个文件夹" in mt.files(lc, {"path": str(vault / OTHER)})["text"]   # 本机可写绝对路径
    with pytest.raises(Denied):
        mt.files(lc, {"path": str(vault.parent / "elsewhere.md")})


# ---------------------------------------------------------------- topics

def test_topics_crud_and_sources(vault, monkeypatch):
    c = ctx(vault)
    monkeypatch.setattr(tmod, "expand_keywords", lambda name: ["长期记忆", "RAG"])
    made = mt.topics(c, {"action": "create", "name": "AI 记忆"})
    assert made["keywords_from"] == "model" and made["created"]["keywords"] == ["AI 记忆", "长期记忆", "RAG"]
    assert made["catalog"] == "queued"
    with pytest.raises(Denied):
        mt.topics(c, {"action": "create", "name": "AI 记忆"})
    mt.topics(c, {"action": "create", "name": "菜谱", "keywords": ["鱼片"], "add_sources": ["bbb22222"]})
    up = mt.topics(c, {"action": "update", "topic": "AI 记忆", "new_name": "记忆层",
                       "add_keywords": ["memory"], "remove_keywords": ["rag"], "add_sources": ["xhs-abc12345"]})
    assert up["updated"]["name"] == "记忆层" and up["updated"]["keywords"] == ["AI 记忆", "长期记忆", "memory"]
    got = mt.topics(c, {"action": "get", "topic": "t1"})["topic"]
    assert got["sources"] == [{"id": "abc12345", "title": "蒜香鱼片怎么做"}] and [i["id"] for i in got["items"]] == ["abc12345"]
    mt.topics(c, {"action": "update", "topic": "t1", "remove_sources": ["abc12345"]})
    assert mt.topics(c, {"action": "get", "topic": "t1"})["topic"]["sources"] == []
    with pytest.raises(Denied):
        mt.topics(c, {"action": "update", "topic": "t1", "add_sources": ["nope0000"]})
    with pytest.raises(Denied):
        mt.topics(c, {"action": "update", "topic": "t1"})
    # 钉住的文章进目录隶属
    member = tmod.memberships(storage.read_json(vault / "_archive/catalog-data.json")["items"], tmod.load(),
                              semantic_scores=None)
    assert "菜谱" in member["xhs-bbb22222"]
    assert mt.topics(c, {"action": "delete", "topic": "菜谱"})["deleted"]["name"] == "菜谱"
    assert [t["name"] for t in mt.topics(c, {})["topics"]] == ["记忆层"]


# ---------------------------------------------------------------- selections（暗号）

def _seed_selections(vault, n):
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = [{"name": f"组{i}", "ids": ["xhs-abc12345"], "created_at": (base + timedelta(hours=i)).isoformat()}
            for i in range(1, n + 1)]
    storage.write_json(vault / "_archive/selections.json", {"selections": list(reversed(rows)), "extra": 1})


def test_selection_ref_parsing(vault):
    _seed_selections(vault, 12)
    rows = mt.numbered_selections()
    assert [r["no"] for r in rows][:3] == [12, 11, 10]
    pick = lambda ref: [r["no"] for r in mt.resolve_selection_ref(ref, rows)[0]]  # noqa: E731
    assert pick("latest") == [12] and pick("最新") == [12] and pick("暗号 最新") == [12]
    assert pick("2") == [2] and pick("暗号2") == [2] and pick("#7") == [7] and pick("2号") == [2]
    assert pick("3,4,5") == [3, 4, 5] and pick("3，4、5") == [3, 4, 5] and pick("3 4 5") == [3, 4, 5]
    assert pick("345") == [3, 4, 5]
    assert pick("12") == [12]                 # 有 12 号：精确优先，不拆成 1、2
    assert pick("112") == [1, 2]              # 没有 112 号：拆开（重复的 1 只取一次）
    assert pick("190") == []                  # 0 号不存在，不瞎拆
    assert pick("3,40") == []
    assert pick("组7") == [7] and pick("组 7") == [7]
    assert pick("不存在") == []


def test_selection_exact_name_beats_number(vault):
    _seed_selections(vault, 3)
    doc = storage.read_json(vault / "_archive/selections.json")
    doc["selections"].insert(0, {"name": "2", "ids": ["xhs-bbb22222"], "created_at": "2026-10-05T00:00:00.000Z"})
    storage.write_json(vault / "_archive/selections.json", doc)
    rows = mt.numbered_selections()
    assert [r["name"] for r in mt.resolve_selection_ref("2", rows)[0]] == ["2"]


def test_selections_save_list_get(vault):
    c = ctx(vault)
    _seed_selections(vault, 2)
    saved = mt.selections(c, {"action": "save", "ids": ["abc12345", "https://www.xiaohongshu.com/explore/bbb22222"]})
    assert saved["saved"] == {"no": 3, "name": "暗号3", "count": 2, "created_at": saved["saved"]["created_at"]}
    named = mt.selections(c, {"action": "save", "ids": ["ccc33333"], "name": "老帖子"})["saved"]
    assert named["no"] == 4
    with pytest.raises(Denied):
        mt.selections(c, {"action": "save", "ids": ["ccc33333"], "name": "老帖子"})
    mt.selections(c, {"action": "save", "ids": ["abc12345"], "name": "老帖子", "overwrite": True})
    with pytest.raises(Denied):
        mt.selections(c, {"action": "save", "ids": ["nope0000"]})
    listed = mt.selections(c, {"action": "list"})
    assert [s["name"] for s in listed["selections"]][:2] == ["老帖子", "暗号3"] and listed["count"] == 4
    got = mt.selections(c, {"action": "get", "ref": "最新"})["selections"]
    assert got[0]["name"] == "老帖子" and got[0]["items"][0]["agent_md"] == AGENT
    multi = mt.selections(c, {"action": "get", "ref": "13"})["selections"]   # 没有 13 号 → 1、3
    assert [g["no"] for g in multi] == [1, 3]
    assert [i["title"] for i in multi[1]["items"]] == ["蒜香鱼片怎么做", "番茄炒蛋"]
    doc = storage.read_json(vault / "_archive/selections.json")
    assert doc["extra"] == 1                                         # 别的键原样保留
    assert doc["selections"][0]["created_at"].endswith("Z")          # 和页面写的格式一致
    with pytest.raises(Denied) as e:
        mt.selections(c, {"action": "get", "ref": "99"})
    assert "老帖子" in e.value.message


# ---------------------------------------------------------------- 并发写

def test_concurrent_writes_do_not_lose_or_corrupt(vault):
    c = ctx(vault)
    errors = []

    def save(i):
        try:
            mt.selections(c, {"action": "save", "ids": ["abc12345"], "name": f"并发{i}"})
            mt.record_search(f"查询{i}", ["t"], 1, "线程")
            mt.topics(c, {"action": "create", "name": f"主题{i}", "keywords": ["词"]})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors
    names = {r["name"] for r in storage.read_json(vault / "_archive/selections.json")["selections"]}
    assert names == {f"并发{i}" for i in range(12)}
    assert len([l for l in mt.history_path().read_text("utf-8").splitlines() if l.startswith("- ")]) == 12
    assert len(tmod.load()) == 12 and len({t["id"] for t in tmod.load()}) == 12
    assert not list((vault / "_archive").glob("*.tmp"))


def test_write_guard_reports_busy_when_other_process_holds(vault):
    with storage.file_lock("selections"):
        # 同进程可重入：模拟别的进程占着 = 换一个假的锁持有者
        pass
    lock = storage.locks_dir() / "selections.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    import time
    lock.write_text(json.dumps({"pid": 4, "owner": "插件", "heartbeat_ts": time.time()}), encoding="utf-8")
    old = mt.LOCK_WAIT
    mt.LOCK_WAIT = 0.3
    try:
        with pytest.raises(Denied) as e:
            mt.selections(ctx(vault), {"action": "save", "ids": ["abc12345"]})
        assert e.value.code == "BUSY"
    finally:
        mt.LOCK_WAIT = old
        lock.unlink()


# ---------------------------------------------------------------- recent

def test_recent_days_and_limit(vault):
    out = mt.recent(ctx(vault), {"days": 7})
    assert [i["id"] for i in out["items"]] == ["abc12345", "bbb22222"]
    assert out["items"][1]["summary"] == "番茄炒蛋的概要。"
    assert [i["id"] for i in mt.recent(ctx(vault), {"days": 60, "limit": 1})["items"]] == ["abc12345"]
    assert mt.recent(ctx(vault), {"days": 60})["found"] == 3


# ---------------------------------------------------------------- stdio 真入口：每个工具一次

def test_stdio_every_tool_once(vault, tmp_path, monkeypatch):
    client = _client(tmp_path, vault)
    try:
        r, p = _call_tool(client, "search", {"query": "蒜香鱼片"}, 2)
        assert not r["isError"] and Path(p["results"][0]["agent_md"]) == vault / AGENT
        r, p = _call_tool(client, "read", {"id": "abc12345", "part": "附件"}, 3)
        assert not r["isError"] and "配料表" in p["text"]
        r, p = _call_tool(client, "files", {}, 4)
        assert not r["isError"] and p["kind"] == "dir"
        r, p = _call_tool(client, "files", {"path": "../x.md"}, 5)
        assert r["isError"] and p["error"] == "INVALID_PATH"
        r, p = _call_tool(client, "topics", {"action": "list"}, 6)
        assert not r["isError"] and p["topics"] == []
        r, p = _call_tool(client, "selections", {"action": "save", "ids": ["abc12345"], "name": "stdio"}, 7)
        assert not r["isError"] and p["saved"]["no"] == 1
        r, p = _call_tool(client, "selections", {"action": "get", "ref": "1"}, 8)
        assert not r["isError"] and p["selections"][0]["items"][0]["title"] == "蒜香鱼片怎么做"
        r, p = _call_tool(client, "recent", {"days": 5}, 9)
        assert not r["isError"] and p["found"] == 2
        r, p = _call_tool(client, "history", {}, 10)
        assert not r["isError"] and "蒜香鱼片" in p["text"]
        r, p = _call_tool(client, "image", {"path": "../x.png"}, 11)
        assert r["isError"]
        r, p = _call_tool(client, "ask", {"question": ""}, 12)   # 空问题：不调模型，直接拒
        assert r["isError"] and p["error"] == "INVALID_ARGUMENT"
    finally:
        client.close()
