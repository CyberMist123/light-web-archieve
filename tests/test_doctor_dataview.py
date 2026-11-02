"""1102：Dataview 从「必装」降为「不需要」——目录页等是 ```lb-page 块，由 LWA 插件自己显示（page-host.js）。

以前（10-03）这里测「目录重建只在 Dataview 没装 / 没开 JS 查询时提示」；现在 doctor、setup plan / check、
目录重建都不再提 Dataview，老设置里残留的 `dataview` 功能 id 当退役项静默忽略。"""

import json

from link_brain import catalog, doctor, storage
from link_brain.setup import components, pipeline


def test_catalog_never_mentions_dataview(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(catalog, "build", lambda: (tmp_path / "x.md", 0, tmp_path / "d.json"))
    monkeypatch.setattr(storage, "vault_root", lambda: tmp_path)
    catalog.run(type("A", (), {})())
    out = capsys.readouterr().out
    assert "Dataview" not in out
    assert "dataview_hint" not in json.loads(out.strip().splitlines()[-1])


def test_doctor_has_no_dataview_row(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "vault_root", lambda: tmp_path)
    rows = doctor.diagnose(obsidian_dir=str(tmp_path / ".obsidian"), only="local")["checks"]
    assert rows and all(r["id"] != "dataview" for r in rows)
    assert not hasattr(doctor, "dataview_ready")


def test_setup_has_no_dataview_component():
    assert "dataview" not in components.IDS
    assert all("dataview" not in ids for ids in components.PRESETS.values())
    assert "dataview" not in pipeline.LIGHT
    assert "dataview" not in pipeline.NEEDS_YOU_TEXT


def test_retired_dataview_id_is_ignored(monkeypatch):
    # 老设置的 setup.selected 里还有 dataview：check 不报「不认识」、只问它时什么也不查；install 直接算成
    monkeypatch.setattr(components, "evaluate", lambda ids: {i: {"row": {"item_id": i, "status": "ready", "code": ""}} for i in ids})
    res = components.check(["dataview"])
    assert res["ok"] and res["results"] == []
    res = components.check(["core", "dataview"])
    assert res["ok"] and [r["item_id"] for r in res["results"]] == ["core"]
    out = components.install("dataview")
    assert out["ok"] and "不再需要" in out["message"]
