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
