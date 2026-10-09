"""10-10 节点 wiki + MCP 的 index / wiki / guide。模型一律 mock；不联网、只写 tmp vault。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import cli, indextree as it, mcp_tools as mt, storage, wiki
from link_brain.remote.policy import Denied, Policy


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "_archive").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(storage.ENV_VAULT, str(v))
    return v


def note(vault: Path, n: int, title: str, tags, body: str):
    sid = f"n{n:07d}"
    agent = f"_archive/xiaohongshu/{sid}/derived/agent.md"
    p = vault / agent
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {title}\n\n## 原文\n\n{body}\n", encoding="utf-8")
    return {"id": f"xhs-{sid}", "title": title, "tags": tags, "date": "2026-10-0" + str(n % 9 + 1),
            "summary": f"{title}的概要。第二句。", "agent_md": agent, "note": f"Web/Xiaohongshu/{title}.md",
            "url": f"https://www.xiaohongshu.com/explore/{sid}"}


def setup_library(vault, extra=()):
    items = [note(vault, 1, "效率工具合集", ["效率"], "推荐 Raycast：https://www.raycast.com 很好用。"),
             note(vault, 2, "纯吐槽", ["效率"], "今天好累。"),
             note(vault, 3, "做饭", ["家常菜"], "红烧肉。"), *extra]
    storage.write_json(vault / "_archive" / "catalog-data.json", {"built_at": "2026-10-10T01:00:00+11:00", "items": items})
    (vault / "索引.md").write_text("- 工具：效率 [wiki]\n- 美食：家常菜\n", encoding="utf-8")
    return items


def fake_ai(monkeypatch, calls):
    from link_brain import providers, text_stream
    monkeypatch.setattr(providers, "resolve", lambda cap, settings=None: {"mode": "http", "model": "deepseek-v4-flash",
                                                                          "endpoint": "x", "timeoutSec": 10, "apiKey": "k"})

    def call(instruction, text, cfg, on_delta=None, *, cap="textAI"):
        calls.append((instruction[:12], text))
        if "定稿" in instruction:
            return {"status": "ok", "text": json.dumps({"purpose": "以后找效率工具时看", "groups": [
                {"category": "启动器", "desc": "最常用", "items": ["o1"]}], "top": [{"id": "o1", "why": "先装这个"}],
                "merge": []}, ensure_ascii=False), "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        return {"status": "ok", "usage": {"prompt_tokens": 1000, "completion_tokens": 200}, "text": json.dumps({
            "objects": [
                {"name": "Raycast", "url": "https://www.raycast.com", "praise": "作者说很好用", "use": "替代系统搜索",
                 "kind": "启动器", "sources": ["#1"]},
                {"name": "编出来的", "url": "https://made-up.example.org", "praise": "x", "use": "y", "kind": "工具",
                 "sources": ["#1", "#99"]},
                {"name": "没出处", "url": "", "praise": "x", "use": "y", "kind": "工具", "sources": ["#99"]},
            ],
            "no_pick": [{"source": "#2", "reason": "只是吐槽"}]}, ensure_ascii=False)}
    monkeypatch.setattr(text_stream, "call", call)


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# ── wiki ──

def test_wiki_without_ai_is_skipped_and_points_to_mcp(vault, capsys):
    setup_library(vault)
    code, out = run_cli(capsys, "wiki", "build", "工具", "--estimate")
    assert code == 2 and out["ok"] is False and out["code"] == "SKIPPED.NOT_CONFIGURED"
    assert "MCP" in out["message"] and "guide" in out["message"]
    assert not (vault / "wiki").exists()


def test_wiki_estimate_does_not_call_model(vault, monkeypatch, capsys):
    setup_library(vault)
    calls = []
    fake_ai(monkeypatch, calls)
    code, out = run_cli(capsys, "wiki", "build", "工具", "--estimate")
    assert code == 0 and out["ok"] and calls == []
    assert out["items"] == 2 and out["calls"] == 2 and out["tokens_in"] > 0 and "token" in out["message"]
    assert out["file"] == "wiki/工具.md" and not (vault / "wiki").exists()


def test_wiki_build_writes_page_drops_unverified_links_and_tracks_new_items(vault, monkeypatch, capsys):
    items = setup_library(vault)
    agent_before = (vault / items[0]["agent_md"]).read_bytes()
    calls = []
    fake_ai(monkeypatch, calls)
    code, out = run_cli(capsys, "wiki", "build", "工具")
    assert code == 0 and out["ok"] and out["objects"] == 2 and out["file"] == "wiki/工具.md"
    page = (vault / "wiki" / "工具.md").read_text(encoding="utf-8")
    assert "> 基于 2 篇，生成于" in page and "之后没有新增" in page
    assert "**Raycast** · <https://www.raycast.com>（帖内给出）" in page
    assert "made-up.example.org" not in page and "没出处" not in page          # 不编链接、对象必须有出处
    assert "## 先看这几个" in page and "## 启动器" in page and "先装这个" in page
    assert "## 附：读过但没有可推荐对象的帖" in page and "只是吐槽" in page
    assert "[[纯吐槽|纯吐槽]]（xhs-n0000002）" in page
    assert (vault / items[0]["agent_md"]).read_bytes() == agent_before         # 原料一个字不动
    meta = wiki.load_meta(vault)["工具"]
    assert sorted(meta["based_ids"]) == ["xhs-n0000001", "xhs-n0000002"]
    data = json.loads((vault / "_archive" / "index-data.json").read_text(encoding="utf-8"))
    assert data["wiki"]["工具"]["exists"] and data["wiki"]["工具"]["new_since"] == 0
    # 之后这个节点又收进一篇：重算索引时页头那行跟着变
    new = note(vault, 4, "又一个工具", ["效率"], "x")
    storage.write_json(vault / "_archive" / "catalog-data.json",
                       {"built_at": "2026-10-11T01:00:00+11:00", "items": items + [new]})
    it.build(vault)
    page = (vault / "wiki" / "工具.md").read_text(encoding="utf-8")
    assert "> 基于 2 篇，生成于" in page and "之后新增 1 篇" in page
    # 重新生成：旧版进历史
    run_cli(capsys, "wiki", "build", "工具")
    assert list((vault / "_archive" / wiki.HISTORY_DIR).glob("*.txt"))


def test_wiki_build_unknown_node_and_empty_node(vault, monkeypatch, capsys):
    setup_library(vault)
    fake_ai(monkeypatch, [])
    code, out = run_cli(capsys, "wiki", "build", "没有这个")
    assert code == 2 and "索引里没有" in out["message"]
    (vault / "索引.md").write_text("- 空的：不存在的标签 [wiki]\n", encoding="utf-8")
    code, out = run_cli(capsys, "wiki", "build", "空的")
    assert code == 2 and "一篇都没收" in out["message"]


def test_wiki_all_batches_failed_writes_nothing(vault, monkeypatch, capsys):
    setup_library(vault)
    fake_ai(monkeypatch, [])
    from link_brain import text_stream
    monkeypatch.setattr(text_stream, "call", lambda *a, **k: {"status": "failed", "code": "NEEDS_HUMAN.AUTH_FAILED",
                                                              "error": "key 被拒"})
    code, out = run_cli(capsys, "wiki", "build", "工具")
    assert code == 1 and out["code"] == "NEEDS_HUMAN.AUTH_FAILED" and "key 被拒" in out["message"]
    assert not (vault / "wiki").exists()


def test_wiki_rel_sanitizes_segments():
    assert wiki.wiki_rel("旅游/成都") == "wiki/旅游/成都.md"
    assert wiki.wiki_rel('a:b/CON/x?y') == "wiki/a_b/_CON/x_y.md"


# ── MCP ──

def ctx(vault, folders=("@xhs",), local=False):
    return mt.Ctx(policy=Policy.build(vault, list(folders)), local=local, who="测试")


def test_mcp_index_tree_node_and_unclassified(vault):
    setup_library(vault)
    (vault / "索引.md").write_text("- 工具：效率 [wiki]\n  - 启动器\n- 美食：家常菜\n- 空\n", encoding="utf-8")
    tree = mt.call(ctx(vault), "index", {})
    paths = {n["path"]: n for n in tree["nodes"]}
    assert paths["工具"]["count"] == 2 and paths["工具"]["wiki"] is True and paths["工具"]["wiki_page"] is False
    assert tree["unclassified"] == 0 and tree["total"] == 3
    node = mt.call(ctx(vault), "index", {"path": "工具", "limit": 1})
    assert node["count"] == 2 and len(node["items"]) == 1 and node["next_offset"] == 1
    assert set(node["items"][0]) == {"id", "title", "date", "summary"} and not node["items"][0]["id"].startswith("xhs-")
    assert node["children"] == [{"path": "工具/启动器", "count": 0}]
    (vault / "索引.md").write_text("- 美食：家常菜\n", encoding="utf-8")       # 改了：MCP 当场重算
    unc = mt.call(ctx(vault), "index", {"path": "unclassified"})
    assert unc["path"] == it.UNCLASSIFIED and unc["count"] == 2
    with pytest.raises(Denied) as e:
        mt.call(ctx(vault), "index", {"path": "不存在"})
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(Denied):
        mt.call(ctx(vault, folders=("其他资料",)), "index", {})


def test_mcp_wiki_and_guide(vault, monkeypatch):
    setup_library(vault)
    listing = mt.call(ctx(vault), "wiki", {})
    assert listing["pages"] == [{"path": "工具", "file": None, "exists": False, "marked": True, "based": 0,
                                 "new_since": 0, "generated_at": None}]
    assert mt.call(ctx(vault), "wiki", {"path": "工具"})["exists"] is False
    fake_ai(monkeypatch, [])
    assert wiki.build("工具", vault)["ok"]
    page = mt.call(ctx(vault), "wiki", {"path": "工具", "max_chars": 20})
    assert page["exists"] and page["file"] == "wiki/工具.md" and len(page["text"]) == 20 and page["next_offset"] == 20
    local = mt.call(ctx(vault, local=True), "wiki", {"path": "工具"})
    assert Path(local["file"]).is_absolute()
    g = mt.call(ctx(vault, folders=()), "guide", {})
    assert "先看这几个" in g["text"] and "7 类左右" in g["text"]


def test_guide_doc_has_no_private_traces():
    text = wiki.method_text()
    assert text and "C:\\Users" not in text and "claude.ai/artifact" not in text and "workdesk" not in text
    for field in ("名字", "链接", "核实", "出自", "帖里", "借鉴"):
        assert field in text
