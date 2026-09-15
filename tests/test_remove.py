"""删除收藏 remove.py + URL 尾巴粘中文 + 链接-only 附言不留 cmt1 的网络无关单测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import cli, index as index_mod, remove, render, storage
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fake_parsed(text="https://example.invalid/share"):
    return {
        "note_id": NOTE_ID,
        "xsec_token": "FAKE_TOKEN",
        "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": text,
        "input_kind": "url",
        "resolved_url": text,
    }


def test_delete_removes_object_and_index(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _fake_parsed(text))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _fixture())
    cli.main(["ingest", "https://example.invalid/share"])

    conn = index_mod.connect()
    row = index_mod.find_object(conn, xhs.SOURCE, NOTE_ID)
    item_id = row["item_id"]
    conn.close()

    obj_dir = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID
    assert obj_dir.is_dir()

    out = remove.delete_items([item_id])
    assert out["deleted"] == 1
    assert not obj_dir.exists()
    conn = index_mod.connect()
    assert index_mod.get_object(conn, item_id) is None
    conn.close()


def test_delete_missing_id(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    index_mod.connect().close()  # 建库
    out = remove.delete_items(["nope"])
    assert out["deleted"] == 0
    assert out["results"][0]["status"] == "missing"


def test_url_regex_stops_at_cjk():
    # 分享文案把中文直接粘在链接尾巴：URL 应在中文处截断，别把「增加的内容」吞进来
    text = "https://www.rednote.com/discovery/item/6aa?xsec_token=TK&xsec_source=pc_share增加的内容"
    urls = xhs.URL_RE.findall(text)
    assert urls == ["https://www.rednote.com/discovery/item/6aa?xsec_token=TK&xsec_source=pc_share"]


def test_catch_finds_cjk_glued_url():
    from link_brain import catch
    url = "https://www.rednote.com/discovery/item/6aa?xsec_token=TK&xsec_source=pc_share"
    found = catch.find_xhs_urls(f"22 【标题】😆 {url}增加的内容")
    assert found == [url]


def test_link_only_note_makes_no_comment():
    # 附言只有分享链接（+小红书模板句）→ 不生成 cmt1 留言
    assert render._is_link_only("https://xhslink.cn/o/95Xgs4DPq02") is True
    assert render._is_link_only("先复制这段文字，再进【小红书】查看完整笔记 https://xhslink.cn/o/abc") is True
    assert render._is_link_only("这篇讲的记忆分层很有用 https://xhslink.cn/o/abc") is False
    block = render.render_comments_block("https://xhslink.cn/o/95Xgs4DPq02", [])
    assert "cmt1" not in block
    block2 = render.render_comments_block("真有意思 https://xhslink.cn/o/abc", [])
    assert "cmt1" in block2
