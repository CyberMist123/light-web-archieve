"""10-31 个人 Wiki 进检索：personal_wiki_search（search / get）、MCP pwiki、问收藏把 Wiki 命中放进提示词。
全部合成数据、隔离 vault；模型一律 mock，不联网。"""
from __future__ import annotations

from pathlib import Path

import pytest

from link_brain import ask, personal_wiki as pw, personal_wiki_search as pws, storage
from link_brain import mcp_tools as mt
from link_brain.remote.policy import Denied, Policy

from test_ask_ui2_1004 import _setup


PAGES = [
    ("pw-aaaaaaaaaaaa01", "住宿偏好", ["travel"], "住酒店优先选离地铁近的，安静比便宜重要。\n\n不住青旅。"),
    ("pw-aaaaaaaaaaaa02", "辣椒酱清单", ["food"], "## 我的结论\n\n超市里那款蒜蓉辣椒酱最好吃，配面条。\n\n- [ ] 试一下老干妈新款"),
    ("pw-aaaaaaaaaaaa03", "机场交通", ["travel"], "到市区我习惯坐机场快线，比打车稳。参考 [交通攻略 0](lwa:t0)。"),
]


def write_pages(vault: Path, pages=PAGES) -> Path:
    root = vault / pw.DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    for pid, title, tags, body in pages:
        text = pw.render_page({"id": pid, "title": title, "role": "page", "tags": tags, "created": "2026-10-30T10:00:00+08:00",
                               "updated": "2026-10-30T10:00:00+08:00", "body": body, "extra": []})
        (root / pw.file_name_for(title, pid)).write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "_archive").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(storage.ENV_VAULT, str(v))
    return v


# ---------------------------------------------------------------- search / get

def test_search_hits_title_tag_and_body_with_snippet(vault):
    write_pages(vault)
    rows = pws.search("住宿", storage.vault_root())
    assert rows and rows[0]["title"] == "住宿偏好" and rows[0]["file"].endswith(".md")
    assert set(rows[0]) >= {"id", "title", "tags", "snippet", "score", "file"}
    # 正文命中：摘要在命中附近
    rows = pws.search("蒜蓉辣椒酱", storage.vault_root())
    assert rows[0]["id"] == "pw-aaaaaaaaaaaa02" and "蒜蓉辣椒酱" in rows[0]["snippet"] and len(rows[0]["snippet"]) <= pws.SNIPPET_CHARS + 2
    # 长问句（中文不分词）：靠 2 字片段 + 最长连续片段，过问收藏的门槛
    rows = pws.search("澳洲有什么好吃的超市辣椒酱推荐", storage.vault_root(), min_score=pws.ASK_MIN_SCORE)
    assert [r["title"] for r in rows][:1] == ["辣椒酱清单"]
    # 标签原样出现在问句里
    assert pws.search("travel 有哪些", storage.vault_root())[0]["tags"] == ["travel"]


def test_search_misses_and_noise_words_do_not_match(vault):
    write_pages(vault)
    assert pws.search("量子计算", storage.vault_root()) == []
    assert pws.search("", storage.vault_root()) == [] and pws.search("   ", storage.vault_root()) == []
    assert pws.search("什么怎么", storage.vault_root()) == []        # 全是虚词片段
    # 问收藏门槛：只沾到一两个字的不要
    assert pws.search("周末去哪里爬山", storage.vault_root(), min_score=pws.ASK_MIN_SCORE) == []


def test_search_works_without_index_and_without_wiki_dir(vault):
    assert pws.search("住宿", storage.vault_root()) == [] and pws.list_pages(storage.vault_root()) == [] and pws.get("住宿偏好", storage.vault_root()) is None
    write_pages(vault)
    assert not pw.index_path(vault).exists()      # 索引缺了：现扫目录
    assert pws.search("住宿", storage.vault_root())[0]["title"] == "住宿偏好"
    # Obsidian 里新建、没有文件头的页也认
    (vault / pw.DIR_NAME / "露营装备.md").write_text("帐篷要买双层的。\n", encoding="utf-8")
    hit = pws.search("帐篷", storage.vault_root())[0]
    assert hit["title"] == "露营装备" and hit["id"].startswith("pf-")


def test_get_by_id_or_title(vault):
    write_pages(vault)
    page = pws.get("pw-aaaaaaaaaaaa03", storage.vault_root())
    assert page["title"] == "机场交通" and "机场快线" in page["body"] and page["tags"] == ["travel"]
    assert pws.get("辣椒酱清单", storage.vault_root())["id"] == "pw-aaaaaaaaaaaa02"
    assert pws.get("不存在的页", storage.vault_root()) is None and pws.get("", storage.vault_root()) is None


# ---------------------------------------------------------------- MCP pwiki

def ctx(vault, folders=("@xhs",), local=False):
    return mt.Ctx(policy=Policy.build(vault, list(folders)), local=local, who="测试")


def test_mcp_pwiki_registered_and_described():
    assert "pwiki" in mt.NAMES and "pwiki" in mt.HANDLERS
    tool = next(t for t in mt.TOOLS if t["name"] == "pwiki")
    assert "优先于收藏原文" in tool["description"] and tool["annotations"]["readOnlyHint"] is True
    assert tool["inputSchema"]["additionalProperties"] is False


def test_mcp_pwiki_list_search_and_read(vault):
    write_pages(vault)
    c = ctx(vault)
    listed = mt.call(c, "pwiki", {})
    assert listed["count"] == 3 and {p["title"] for p in listed["pages"]} == {"住宿偏好", "辣椒酱清单", "机场交通"}
    assert set(listed["pages"][0]) == {"id", "title", "role", "tags", "lead", "updated"}
    found = mt.call(c, "pwiki", {"query": "辣椒酱"})
    assert found["found"] >= 1 and found["results"][0]["title"] == "辣椒酱清单"
    assert found["results"][0]["file"].startswith("PersonalWiki/")   # 远程：不露本机路径
    page = mt.call(c, "pwiki", {"id": "pw-aaaaaaaaaaaa01"})
    assert page["title"] == "住宿偏好" and "安静比便宜重要" in page["text"] and page["next_offset"] is None
    part = mt.call(c, "pwiki", {"id": "住宿偏好", "max_chars": 5})
    assert len(part["text"]) == 5 and part["next_offset"] == 5
    local = mt.call(ctx(vault, local=True), "pwiki", {"id": "住宿偏好"})
    assert Path(local["file"]).is_absolute()
    with pytest.raises(Denied) as e:
        mt.call(c, "pwiki", {"id": "没有这页"})
    assert e.value.code == "NOT_FOUND"


def test_mcp_pwiki_needs_open_library(vault):
    write_pages(vault)
    with pytest.raises(Denied) as e:
        mt.call(ctx(vault, folders=()), "pwiki", {})
    assert e.value.code == "NOT_OPEN"
    assert mt.call(ctx(vault, folders=("PersonalWiki",)), "pwiki", {})["count"] == 3
    assert mt.call(ctx(vault), "pwiki", {"query": "量子计算"})["found"] == 0


# ---------------------------------------------------------------- 问收藏注入

def test_ask_puts_wiki_block_before_evidence_and_returns_wiki(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    write_pages(tmp_path)
    r = ask.answer("机场到市区怎么走")
    _prompt, material = seen[-1]
    assert "【她的 Wiki" in material and "《机场交通》" in material and "机场快线" in material
    assert material.index("【她的 Wiki") < material.index("【证据】")
    assert r["status"] == "ok" and r["wiki"] == [{"id": "pw-aaaaaaaaaaaa03", "title": "机场交通"}]
    # 来源编号不动：Wiki 不进 sources
    assert all(not str(s.get("id", "")).startswith("pw-") for s in r["sources"])


def test_ask_without_wiki_hit_or_switched_off_is_unchanged(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    r = ask.answer("机场到市区怎么走")          # 没有 PersonalWiki 目录
    assert "【她的 Wiki" not in seen[-1][1] and "wiki" not in r
    write_pages(tmp_path)
    monkeypatch.setattr(ask.ai_config, "load",
                        lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {"retrieval": {"personalWiki": False}}))
    r = ask.answer("机场到市区怎么走")
    assert "【她的 Wiki" not in seen[-1][1] and "wiki" not in r and r["status"] == "ok"


def test_ask_wiki_error_does_not_break_answer(monkeypatch, tmp_path):
    seen = _setup(monkeypatch, tmp_path)
    write_pages(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("Wiki 读坏了")
    monkeypatch.setattr(pws, "search", boom)
    r = ask.answer("机场到市区怎么走")
    assert r["status"] == "ok" and "wiki" not in r and "【她的 Wiki" not in seen[-1][1] and "【证据】" in seen[-1][1]


def test_with_wiki_block_falls_back_to_append():
    out = ask.with_wiki_block("没有证据段的文字", [{"id": "x", "title": "T", "tags": ["a"], "text": "正文"}])
    assert out.startswith("没有证据段的文字") and "《T》 #a\n正文" in out
