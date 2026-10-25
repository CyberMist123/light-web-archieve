"""C4（TEST-MAP ①「单篇导入（catch / MCP / CLI）、从快照恢复、改来源…」一行的后半段）：
恢复快照、改来源之后都会 `catalog.mark_dirty(理由)` + `catalog.ensure_fresh(wait_s=30)`。

两个名字在 restore.run / provenance.relabel 里是函数内 `from .catalog import …`，
所以 patch `link_brain.catalog` 模块上的名字就生效（换成本任务要的记录用的假函数）。
造数照现有测试抄：改来源走 test_catch 的 catch fixture + cli relabel；恢复快照走
tests.test_render 的 setup_env + ingest（图片下不来退出 2，笔记照样写出来）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from link_brain import catalog as catalog_mod, cli, render as render_mod, restore, storage
from link_brain.adapters import xiaohongshu as xhs
from test_catch import NOTE_ID, XHS_URL, load_fixture, setup_env as catch_env


def _spies(monkeypatch) -> dict:
    calls: dict = {"dirty": [], "fresh": []}
    monkeypatch.setattr(catalog_mod, "mark_dirty", lambda why="入库": calls["dirty"].append(why))
    monkeypatch.setattr(catalog_mod, "ensure_fresh", lambda **kw: calls["fresh"].append(kw))
    return calls


def test_relabel_marks_dirty_with_reason_and_ensures_fresh(tmp_path, monkeypatch, capsys):
    catch_env(tmp_path, monkeypatch)
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    assert cli.main(["catch", XHS_URL, "--origin", "tg", "--actor", "human"]) == 0
    capsys.readouterr()
    calls = _spies(monkeypatch)
    assert cli.main(["relabel", NOTE_ID, "--origin", "cc", "--actor", "ai:cc", "--project", "ai群聊"]) == 0
    capsys.readouterr()
    assert calls["dirty"] == ["改来源"]
    assert calls["fresh"] == [{"wait_s": 30}]


def test_restore_marks_dirty_with_reason_and_ensures_fresh(tmp_path, monkeypatch, capsys):
    from tests.test_render import _get_item_id, setup_env as render_env
    render_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])   # 图片下不来退出 2，笔记照样写出来
    item_id, _source, _source_id = _get_item_id(tmp_path)
    meta = storage.read_json(storage.object_dir(_source, _source_id) / "meta.json")
    vis = storage.vault_root() / meta["visible_note"]
    # 把正文层挖掉，恢复才有事可做（照 test_restore_1009 的做法）
    text = vis.read_text(encoding="utf-8")
    s, e = text.find(render_mod.CONTENT_START), text.find(render_mod.CONTENT_END) + len(render_mod.CONTENT_END)
    vis.write_text(text[:s] + text[e:], encoding="utf-8")

    calls = _spies(monkeypatch)
    code = restore.run(SimpleNamespace(scan=False, list=False, undo=False, target=item_id,
                                       path=None, dry_run=False))
    assert code == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True
    assert calls["dirty"] == ["恢复快照"]
    assert calls["fresh"] == [{"wait_s": 30}]


def test_restore_dry_run_does_not_touch_catalog(tmp_path, monkeypatch, capsys):
    from tests.test_render import _get_item_id, setup_env as render_env
    render_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, _source, _source_id = _get_item_id(tmp_path)
    calls = _spies(monkeypatch)
    code = restore.run(SimpleNamespace(scan=False, list=False, undo=False, target=item_id,
                                       path=None, dry_run=True))
    assert code == 0
    capsys.readouterr()
    assert calls["dirty"] == [] and calls["fresh"] == []      # dry_run 只看不写，目录也不动
