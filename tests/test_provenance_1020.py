"""1020「谁收的」：目录默认只看她自己的收藏；聊天分享 / fable / 项目各自分组（provenance.py）。"""

from __future__ import annotations

import json

from link_brain import catalog as catalog_mod, cli, index as index_mod, storage
from link_brain.adapters import xiaohongshu as xhs
from link_brain.provenance import CHAT_SHARE, collected_by

from test_catch import NOTE_ID, XHS_URL, load_fixture, only_json, setup_env


def test_collected_by_rules():
    assert collected_by({"origin": "cli", "actor": "human", "ingest_kind": "favorite"}) == ""
    assert collected_by({"origin": "cli", "actor": "human", "ingest_kind": "shared"}) == ""   # 她自己在电脑上导入
    assert collected_by({"origin": "tg", "actor": "human", "ingest_kind": "shared"}) == CHAT_SHARE
    assert collected_by({"origin": "tg", "actor": "ai:fable"}) == "fable"
    assert collected_by({"origin": "cc", "actor": "ai:cc", "project": "ai群聊"}) == "ai群聊"
    assert collected_by({"origin": "cli", "actor": "ai:gpt"}) == "gpt"
    # 后来她自己收藏了：回主收藏
    assert collected_by({"origin": "tg", "actor": "human", "favorited_by": [{"user_id": "u"}]}) == ""


def _meta():
    return storage.read_json(storage.object_dir(xhs.SOURCE, NOTE_ID) / "meta.json")


def test_catch_project_lands_in_meta_and_catalog(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    assert cli.main(["catch", XHS_URL, "--origin", "cc", "--actor", "ai:cc", "--project", " ai群聊 "]) == 0
    assert only_json(capsys)["items"][0]["status"] == "new"
    assert _meta()["project"] == "ai群聊"
    rows = catalog_mod.collect(storage.vault_root())
    assert [r["src"] for r in rows] == ["ai群聊"]


def test_hit_does_not_relabel(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    cli.main(["catch", XHS_URL, "--origin", "tg", "--actor", "human"])
    capsys.readouterr()
    cli.main(["catch", XHS_URL, "--origin", "cc", "--actor", "ai:cc", "--project", "graph"])
    capsys.readouterr()
    assert "project" not in _meta() and collected_by(_meta()) == CHAT_SHARE


def test_relabel_updates_meta_and_index(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    cli.main(["catch", XHS_URL, "--origin", "tg", "--actor", "human"])
    capsys.readouterr()
    assert cli.main(["relabel", NOTE_ID, "--actor", "ai:cc", "--origin", "cc", "--project", "ai群聊"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["items"][0]["src"] == "ai群聊"
    meta = _meta()
    assert (meta["origin"], meta["actor"], meta["project"]) == ("cc", "ai:cc", "ai群聊")
    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT origin, actor FROM relations WHERE item_id = ?", (meta["item_id"],)).fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in rows] == [("cc", "ai:cc")]
    assert cli.main(["relabel", "nope0000000000000000dead"]) == 1
