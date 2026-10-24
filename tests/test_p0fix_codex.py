"""1025 第一波返修第二趟（Codex 整树审查的 4 条「中」）。"""

from __future__ import annotations

import copy
import json

from link_brain import cli, comment_fill, index as index_mod
from link_brain.adapters import xiaohongshu as xhs
from test_tomb_p0_1024 import (ITEM_ID, NOTE_ID, _fixture, _ingested, _normalize, _parsed,  # noqa: F401
                               vault)


# ---------------------------------------------------------------------------
# 1. 判重要看续读状态：楼回复数涨了 / 读没读到底 / 缺口变了，都得存新版本
# ---------------------------------------------------------------------------


def test_hash_sees_resume_state_changes():
    a = _normalize()
    a["capture"]["comment_load"] = {"seconds": 1.0, "has_more": True, "gaps": []}
    base = index_mod.normalized_source_sha256(a)
    for mutate in (
        lambda s: s["comments"][0].__setitem__("sub_comment_count", 9),                 # 楼回复数涨了、没展开
        lambda s: s["capture"]["comment_load"].__setitem__("has_more", False),          # 读到底了
        lambda s: s["capture"].__setitem__("comments_complete", not s["capture"]["comments_complete"]),
        lambda s: s["capture"]["comment_load"].__setitem__(
            "gaps", [{"comment_id": "c0001", "reason": "count_mismatch", "missing": 3}]),  # 缺口变成读不回来的
    ):
        b = copy.deepcopy(a)
        mutate(b)
        assert index_mod.normalized_source_sha256(b) != base


def test_hash_ignores_volatile_comment_load_fields():
    a = _normalize()
    a["capture"]["comment_load"] = {"seconds": 1.0, "has_more": True, "fill_last_at": "2026-10-01T00:00:00+00:00",
                                    "fill_attempts": 1, "gaps": [{"comment_id": "c0001", "reason": "budget", "missing": 1}]}
    b = copy.deepcopy(a)
    b["capture"]["comment_load"].update(seconds=77.0, fill_last_at="2026-10-25T00:00:00+00:00", fill_attempts=5)
    b["capture"]["comments_cursor"] = "another-cursor"
    b["capture"]["comment_load"]["gaps"][0]["reason"] = "cap"  # 都还能续，只是这次停的原因不同
    assert index_mod.normalized_source_sha256(a) == index_mod.normalized_source_sha256(b)


def test_refresh_saves_new_reply_gap(vault, monkeypatch):
    """重抓时第 1 楼回复从 1 涨到 6，但额度不够没展开：要存新版本，续读才排得上这楼。"""
    obj = _ingested(vault)
    raw = _fixture()
    raw["data"]["comments"]["list"][0]["subCommentCount"] = "6"
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: raw)
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: _parsed("https://other.invalid/x", "FAKE_TOKEN_B"))
    assert cli.main(["ingest", "https://other.invalid/x", "--refresh"]) in (0, 2)
    assert (obj / "raw" / "v0002").exists(), "修前：判重说没变化，新缺口没存"
    source = json.loads((obj / "raw" / "v0002" / "source.json").read_text(encoding="utf-8"))
    assert comment_fill.scope(source, 50)["missing"] == 5


# ---------------------------------------------------------------------------
# 2. 删 A 时顺带续删完的旧 pending B，也要从目录里摘掉
# ---------------------------------------------------------------------------


def test_delete_also_drops_finished_pending_from_catalog(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from link_brain import catalog, remove, storage
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    conn = index_mod.connect()
    conn.execute("INSERT INTO tombstones (source, source_id, item_id, deleted_at, trash_dir, state) "
                 "VALUES ('xiaohongshu', 'b', 'b', '2026-10-24T00:00:00+00:00', '_trash/b', 'pending')")
    conn.commit()
    conn.close()
    data = tmp_path / "_archive" / catalog.DATA_NAME
    data.write_text(json.dumps({"count": 3, "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}), "utf-8")
    monkeypatch.setattr(remove, "delete_item", lambda conn, i: {"item_id": i, "status": "deleted"})
    monkeypatch.setattr(remove, "publish_trash", lambda *a, **k: None)
    built = []
    monkeypatch.setattr(catalog, "build", lambda *a, **k: built.append(1))
    assert remove.run(SimpleNamespace(command="delete", item_ids=["a"])) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert [r["item_id"] for r in out["finished"]] == ["b"]
    got = json.loads(data.read_text("utf-8"))
    assert [i["id"] for i in got["items"]] == ["c"], "修前：b 续删完了却还留在目录里"
    assert built == []
