"""10-03：目录重建只在 Dataview 没装 / 没开 JS 查询时才提示（她已经装了还每次刷新都弹）。"""

import json

from link_brain import catalog, doctor, storage


def _obs(tmp_path, enabled, js):
    obs = tmp_path / ".obsidian"
    (obs / "plugins" / "dataview").mkdir(parents=True)
    (obs / "community-plugins.json").write_text(json.dumps(enabled), encoding="utf-8")
    (obs / "plugins" / "dataview" / "data.json").write_text(json.dumps({"enableDataviewJs": js}), encoding="utf-8")
    return obs


def test_dataview_ready(tmp_path):
    assert doctor.dataview_ready(_obs(tmp_path, ["dataview"], True))


def test_dataview_not_ready_when_js_off(tmp_path):
    assert not doctor.dataview_ready(_obs(tmp_path, ["dataview"], False))


def test_dataview_not_ready_when_missing(tmp_path):
    assert not doctor.dataview_ready(tmp_path / ".obsidian")


def test_catalog_hint_only_when_dataview_missing(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(catalog, "build", lambda: (tmp_path / "x.md", 0, tmp_path / "d.json"))
    monkeypatch.setattr(storage, "vault_root", lambda: tmp_path)
    _obs(tmp_path, ["dataview"], True)
    catalog.run(type("A", (), {})())
    assert "Dataview" not in capsys.readouterr().out
    (tmp_path / ".obsidian" / "plugins" / "dataview" / "data.json").write_text('{"enableDataviewJs": false}', encoding="utf-8")
    catalog.run(type("A", (), {})())
    assert "Dataview" in capsys.readouterr().out
