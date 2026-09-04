"""`catch`：一整条消息 → 一个 JSON。

用 `tests/fixtures/mcp_raw_sanitized.json`（脱敏样本），monkeypatch `fetch_detail` / `parse_input`，
不碰网络、不碰真 vault。重点验三件事：
stdout **只有一个 JSON**（TG/CMX 端要直接 `json.loads`）、HIT 不联网、消息原文进了留言层。
"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import catch as catch_mod, cli, storage, vision as vision_mod
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"
XHS_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token=FAKE"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fake_parsed(text: str = XHS_URL) -> dict:
    return {
        "note_id": NOTE_ID,
        "xsec_token": "FAKE_TOKEN_FOR_TESTS",
        "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": text,
        "input_kind": "url",
    }


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: fake_parsed(text))
    monkeypatch.setattr(
        vision_mod,
        "run_ocr",
        lambda path, timeout=120: {"status": "ok", "ocr": "test ocr", "error": None},
    )


def only_json(capsys) -> dict:
    """stdout 必须是**恰好一个** JSON，多打一行日志就在这里炸。"""
    out = capsys.readouterr().out
    return json.loads(out)


# --------------------------------------------------------------------------
# 链接检测
# --------------------------------------------------------------------------


def test_find_xhs_urls_filters_hosts_and_dedupes():
    message = (
        "看看这个 https://xhslink.cn/o/2yNuSBjolWo ，还有 https://github.com/foo/bar 不是小红书；"
        f"再来一次 {XHS_URL}。"
    )
    urls = catch_mod.find_xhs_urls(message)
    assert urls == ["https://xhslink.cn/o/2yNuSBjolWo", XHS_URL]

    # 同一条链接出现两次只留一条；结尾中文标点不算进 URL
    assert catch_mod.find_xhs_urls(f"{XHS_URL} {XHS_URL}") == [XHS_URL]
    assert catch_mod.find_xhs_urls("（https://www.xiaohongshu.com/explore/abc123456789abcd）") == [
        "https://www.xiaohongshu.com/explore/abc123456789abcd"
    ]


def test_find_xhs_urls_rejects_lookalike_host():
    assert catch_mod.find_xhs_urls("https://xiaohongshu.com.evil.example/explore/x") == []
    assert catch_mod.find_xhs_urls("https://notxhslink.cn/o/x") == []


# --------------------------------------------------------------------------
# 没有链接：零成本
# --------------------------------------------------------------------------


def test_no_link_returns_found_zero(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise AssertionError("没有链接时不许调 MCP")

    monkeypatch.setattr(xhs, "fetch_detail", boom)

    code = cli.main(["catch", "今天天气不错，晚点聊"])
    assert code == 0
    assert only_json(capsys) == {"found": 0, "items": []}


# --------------------------------------------------------------------------
# 新归档 → 再来一次是 HIT
# --------------------------------------------------------------------------


def test_catch_new_then_hit(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_fetch(*a, **k):
        calls["n"] += 1
        return load_fixture()

    monkeypatch.setattr(xhs, "fetch_detail", fake_fetch)

    message = f"这篇看着不错 {XHS_URL} 帮我存一下"
    code = cli.main(["catch", message, "--origin", "tg", "--actor", "human"])
    assert code == 0
    payload = only_json(capsys)
    assert payload["found"] == 1
    assert calls["n"] == 1

    item = payload["items"][0]
    assert item["item_id"] == f"xhs-{NOTE_ID}"
    assert item["status"] == "new"
    assert item["title"]
    assert item["summary"]
    assert item["url"] == xhs.CANONICAL_FMT.format(note_id=NOTE_ID)
    assert item["kind"] in ("image", "video", "text")
    assert isinstance(item["tags"], list)
    assert item["attachments"]["status"] in ("none", "unavailable", "metadata_only", "downloaded")

    # 路径给绝对路径，调用方 cwd 不确定
    visible = Path(item["visible_note"])
    agent_md = Path(item["agent_md"])
    assert visible.is_absolute() and visible.exists()
    assert agent_md.is_absolute() and agent_md.exists()

    # 消息原文进了留言层 cmt1
    assert "帮我存一下" in visible.read_text(encoding="utf-8")

    # 第二次：HIT，不再调 MCP
    code = cli.main(["catch", f"又发了一次 {XHS_URL}", "--origin", "cmx"])
    assert code == 0
    payload = only_json(capsys)
    assert payload["found"] == 1
    assert payload["items"][0]["status"] == "hit"
    assert calls["n"] == 1


def test_same_note_twice_in_one_message_counts_once(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())

    code = cli.main(["catch", f"{XHS_URL} 和 https://xhslink.cn/o/2yNuSBjolWo 是同一篇"])
    assert code == 0
    payload = only_json(capsys)
    assert payload["found"] == 1


# --------------------------------------------------------------------------
# 抓失败：不炸 JSON，退出码 1
# --------------------------------------------------------------------------


def test_failed_link_reports_error_item(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)

    def boom(text, client=None):
        raise xhs.AdapterError("短链解不出笔记 URL")

    monkeypatch.setattr(xhs, "parse_input", boom)

    code = cli.main(["catch", f"打不开的 {XHS_URL}"])
    assert code == 1
    payload = only_json(capsys)
    assert payload["found"] == 1
    item = payload["items"][0]
    assert item["status"] == "error"
    assert item["item_id"] is None
    assert "短链解不出笔记 URL" in item["error"]


# --------------------------------------------------------------------------
# read --brief --json / search --json
# --------------------------------------------------------------------------


def test_read_brief_json_and_search_json(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    cli.main(["catch", f"存一下 {XHS_URL}"])
    capsys.readouterr()

    assert cli.main(["read", f"xhs-{NOTE_ID}", "--brief", "--json"]) == 0
    item = only_json(capsys)
    assert item["item_id"] == f"xhs-{NOTE_ID}"
    assert "status" not in item  # status 只有 catch 才给
    assert item["visible_note"] and Path(item["visible_note"]).exists()

    assert cli.main(["read", f"xhs-{NOTE_ID}", "--full", "--json"]) == 0
    full = only_json(capsys)
    assert full["markdown"].strip()

    title = load_fixture()["data"]["note"].get("title") or ""
    assert cli.main(["search", title[:4], "--json"]) == 0
    result = only_json(capsys)
    assert result["found"] >= 1
    assert result["items"][0]["item_id"] == f"xhs-{NOTE_ID}"
    assert result["items"][0]["url"]
