"""Lot 1：输入解析、归一化、缺内容 gate。

用脱敏 fixture（`tests/fixtures/mcp_raw_sanitized.json`，内容全部编造），不碰网络、
不碰任何已写好的 `raw/v0001`。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from link_brain import cli, ingest, storage
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"
REAL_URL = (
    "https://www.xiaohongshu.com/discovery/item/6a49b7ff000000001502522c"
    "?xsec_source=app_share&type=normal&xsec_token=ABC123%3D&author_share=1"
)


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- 输入解析 -------------------------------------------------------------


def test_plain_url_parses():
    parsed = xhs.parse_input(REAL_URL)
    assert parsed["note_id"] == "6a49b7ff000000001502522c"
    assert parsed["xsec_token"] == "ABC123%3D"
    assert parsed["input_kind"] == "url"
    assert parsed["canonical_url"].endswith("/explore/6a49b7ff000000001502522c")


def test_share_text_parses_to_same_note_id():
    share = f"66 复制打开小红书，看看【P模式全攻略】 {REAL_URL} 快来看吧！"
    parsed = xhs.parse_input(share)
    assert parsed["note_id"] == "6a49b7ff000000001502522c"
    assert parsed["input_kind"] == "share_text"


def test_shortlink_classified_and_resolved(monkeypatch):
    monkeypatch.setattr(xhs, "resolve_shortlink", lambda url, client=None: REAL_URL)
    parsed = xhs.parse_input("https://xhslink.cn/o/2yNuSBjolWo")
    assert parsed["input_kind"] == "shortlink"
    assert parsed["note_id"] == "6a49b7ff000000001502522c"


def test_input_without_url_raises():
    with pytest.raises(xhs.AdapterError):
        xhs.parse_input("这里没有链接")


# --- 归一化 ---------------------------------------------------------------


def _normalized():
    parsed = {
        "note_id": NOTE_ID,
        "xsec_token": "FAKE_TOKEN_FOR_TESTS",
        "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": "https://example.invalid/share",
        "input_kind": "url",
    }
    return xhs.normalize(load_fixture(), parsed, captured_at="2026-09-04T15:00:00+10:00")


def test_normalize_shape():
    source = _normalized()
    note = source["note"]
    assert note["kind"] == "image"
    assert note["hashtags"] == ["测试", "样例"]
    assert [link["url"] for link in note["links"]] == ["https://example.com/a"]
    assert note["attachments"][0]["status"] == "unavailable"
    assert source["capture"]["comments_complete"] is True


def test_normalize_sub_comments():
    comments = _normalized()["comments"]
    assert len(comments) == 1
    assert comments[0]["floor"] == 1
    assert comments[0]["sub_comment_count"] == 1
    assert comments[0]["sub_comments"][0]["floor"] == 2
    assert comments[0]["sub_comments_complete"] is True


# --- 缺内容 gate ----------------------------------------------------------


def test_missing_image_triggers_gate(tmp_path, monkeypatch):
    """坏 URL fixture → images_complete:false + 退出码 2，且不动真 vault。"""
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(
        xhs, "parse_input",
        lambda text, client=None: {
            "note_id": NOTE_ID,
            "xsec_token": "FAKE_TOKEN_FOR_TESTS",
            "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
            "input_url": text,
            "input_kind": "url",
        },
    )
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())

    code = cli.main(["ingest", "https://example.invalid/share"])
    assert code == ingest.EXIT_MISSING_CONTENT

    raw = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "raw" / "v0001"
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["images_complete"] is False
    assert manifest["images_ok"] == 0
    assert manifest["media"][0]["error"]
    assert manifest["media"][0]["file"] is None
    # 主体照常归档
    assert (raw / "source.json").exists() and (raw / "mcp_raw.json").exists()
    meta = json.loads((raw.parent.parent / "meta.json").read_text(encoding="utf-8"))
    assert meta["attachments_status"] == "unavailable"


def test_raw_version_is_immutable(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    storage.ensure_raw_dir("xiaohongshu", NOTE_ID, 1)
    with pytest.raises(FileExistsError):
        storage.ensure_raw_dir("xiaohongshu", NOTE_ID, 1)
    assert storage.next_version("xiaohongshu", NOTE_ID) == 2


# --------------------------------------------------------------------------
# 附件：网页探测（MCP 不返回 relatedFile）
# --------------------------------------------------------------------------

REAL_RELATED_FILE = {
    "name": "p模式教程-机教版.pdf",
    "docId": "7658854832003020032",
    "icon": "https://fe-platform.xhscdn.com/platform/xxx",
    "bizExtra": '{"download_num":644,"page_num":19,"view_num":1468}',
}


def _probe(ok, related=None, error=None):
    return {"ok": ok, "related_file": related, "url": "https://example.invalid/note", "error": error}


def test_web_probe_gives_real_attachment_metadata():
    body = "给小机看的版本在文件～"
    out = xhs._attachments(body, _probe(True, REAL_RELATED_FILE))
    assert len(out) == 1
    a = out[0]
    assert a["name"] == "p模式教程-机教版.pdf"
    assert a["doc_id"] == "7658854832003020032"
    assert a["url"] == "https://www.xiaohongshu.com/file/7658854832003020032"
    assert (a["page_num"], a["download_num"], a["view_num"]) == (19, 644, 1468)
    assert a["status"] == "metadata_only"  # 字节要登录才拿得到
    assert a["hint"] == body  # 正文线索仍保留


def test_web_probe_says_no_file_kills_false_positive():
    """正文提到"文件"但页面上没挂附件 → 不再误报出一条 unavailable。"""
    out = xhs._attachments("详细的在文件里说了", _probe(True, None))
    assert out == []


def test_web_probe_failure_falls_back_to_body_hint():
    out = xhs._attachments("给小机看的版本在文件～", _probe(False, error="连不上"))
    assert len(out) == 1 and out[0]["status"] == "unavailable"
    assert "连不上" in out[0]["reason"]


@pytest.mark.real_web_probe
def test_probe_treats_missing_note_as_failure(monkeypatch):
    """页面 200 但状态里没有这条笔记时不能当作"没有附件"。"""
    class FakeResp:
        text = '<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{}}}</script>'
        def raise_for_status(self):
            return None

    monkeypatch.setattr(xhs.httpx, "get", lambda *a, **k: FakeResp())
    result = xhs.fetch_related_file("deadbeef", "tok")
    assert result["ok"] is False and "没有这条笔记" in result["error"]


@pytest.mark.real_web_probe
def test_probe_reads_related_file_from_initial_state(monkeypatch):
    state = json.dumps({"note": {"noteDetailMap": {"n1": {"note": {"relatedFile": REAL_RELATED_FILE}}}}},
                       ensure_ascii=False)

    class FakeResp:
        text = f"<script>window.__INITIAL_STATE__={state};</script>"
        def raise_for_status(self):
            return None

    monkeypatch.setattr(xhs.httpx, "get", lambda *a, **k: FakeResp())
    result = xhs.fetch_related_file("n1", "tok")
    assert result["ok"] is True
    assert result["related_file"]["docId"] == "7658854832003020032"


def test_attachments_status_reflects_metadata_only(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(
        xhs, "parse_input",
        lambda text, client=None: {
            "note_id": NOTE_ID,
            "xsec_token": "FAKE_TOKEN_FOR_TESTS",
            "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
            "input_url": text,
            "input_kind": "url",
        },
    )
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    monkeypatch.setattr(xhs, "fetch_related_file", lambda *a, **k: _probe(True, REAL_RELATED_FILE))

    cli.main(["ingest", "https://example.invalid/share"])
    meta = json.loads(
        (tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["attachments_status"] == "metadata_only"
    raw = tmp_path / "_archive" / "xiaohongshu" / NOTE_ID / "raw" / "v0001"
    assert json.loads((raw / "web_raw.json").read_text(encoding="utf-8"))["ok"] is True
