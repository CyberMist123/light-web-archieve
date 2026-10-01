"""1001 审计 ingest/note-9、ui/ui-6：批注不互相冲掉、坏文件不 fail-open 写回。

Python 一侧（`note` CLI，Fable / 插件 ⭐ 走这条）直接测；前端 annotate-view.js 的合并逻辑在
tests/test_annotate_merge.cjs 里用 node 跑生产那份脚本，这里包一层让 pytest 也跑到它。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from link_brain import cli, note, storage

from test_attachments import _ids, setup_env


@pytest.fixture
def obj(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _ids()
    return item_id, note.notes_path(source, source_id)


def test_corrupt_notes_file_is_not_overwritten(obj, capsys):
    item_id, path = obj
    broken = '{"starred": false, "annotations": [{"ts": "2026-09-0'
    path.write_text(broken, encoding="utf-8")

    assert cli.main(["note", "star", item_id]) == 1
    assert cli.main(["note", "add", item_id, "新批注"]) == 1
    assert path.read_text(encoding="utf-8") == broken, "读坏了绝不拿空数据写回去"
    out = capsys.readouterr()
    assert '"status": "corrupt"' in out.out and "读不了" in out.err


def test_cli_annotation_gets_id_and_keeps_tombstones(obj):
    item_id, path = obj
    storage.write_json(path, {"starred": True, "annotations": [{"id": "a1", "ts": "t", "text": "前端写的"}],
                              "deleted": ["ts:t0|删掉的"], "draft": "草稿"})
    assert cli.main(["note", "add", item_id, "Fable 写的"]) == 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert [a["text"] for a in doc["annotations"]] == ["前端写的", "Fable 写的"]
    assert doc["annotations"][1]["id"].startswith("a")
    assert doc["deleted"] == ["ts:t0|删掉的"] and doc["draft"] == "草稿" and doc["starred"] is True


def test_missing_notes_file_is_still_empty(obj):
    item_id, path = obj
    assert not path.exists()
    assert note.list_notes(item_id)["annotations"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="本机没装 node")
def test_annotate_view_merges_concurrent_views():
    script = Path(__file__).parent / "test_annotate_merge.cjs"
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout
