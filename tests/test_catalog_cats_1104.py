"""1104：新库不预设作者个人分类。

data.json 的 `catalogCats` 非空有效就照用；否则 `catalogCatsPreset: "none"` = 不预设分类，内容进「未归类 / 其他」；
缺这个键（含老库存着的 catalogCats: []）回退内置 BIG_CATS。已有 索引.md 的不重建。全部走 tmp vault，不联网。
"""

from __future__ import annotations

import json

import pytest

from link_brain import ai_config, catalog, indextree, storage
from tests.test_catalog import _make_object


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "_archive").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(storage.ENV_VAULT, str(v))
    monkeypatch.delenv("LINK_BRAIN_OBSIDIAN_DIR", raising=False)
    return v


def _settings(vault, data):
    plugin = vault / ".obsidian" / "plugins" / ai_config.PLUGIN_ID
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _two_objects(vault):
    _make_object(vault, "c1", title="做菜", tags=["家常菜", "美食"], summary="x", stem="做菜")
    _make_object(vault, "c2", title="claude 记忆", tags=["claude", "记忆系统"], summary="x", stem="记忆")


def _data(vault):
    return json.loads((vault / "_archive" / "catalog-data.json").read_text(encoding="utf-8"))


def test_ai_config_reads_preset(vault):
    assert ai_config.load().get("catalogCatsPreset") == ""        # 没有 data.json
    _settings(vault, {"catalogCats": []})
    got = ai_config.load()
    assert got.get("catalogCats") == [] and got.get("catalogCatsPreset") == ""
    _settings(vault, {"catalogCats": [], "catalogCatsPreset": "none"})
    assert ai_config.load().get("catalogCatsPreset") == "none"


@pytest.mark.parametrize("data", [{}, {"catalogCats": []}, {"catalogCats": [], "catalogCatsPreset": "builtin"},
                                  {"catalogCats": [{"name": " "}]}],
                         ids=["no-key", "old-empty-list", "other-preset", "all-invalid"])
def test_old_libraries_keep_builtin(vault, data):
    _settings(vault, data)
    assert catalog.effective_big_cats() == catalog.BIG_CATS


def test_preset_none_means_no_preset_cats(vault):
    _settings(vault, {"catalogCats": [], "catalogCatsPreset": "none"})
    assert catalog.effective_big_cats() == []
    _two_objects(vault)
    _, total, _ = catalog.build(vault)
    data = _data(vault)
    assert total == 2
    assert data["cats"] == []
    assert data["cats_order"] == [indextree.UNCLASSIFIED]
    assert all(it["cats"] == [indextree.UNCLASSIFIED] for it in data["items"])
    # 首建的 索引.md 里没有作者的分类
    text = (vault / "索引.md").read_text(encoding="utf-8")
    assert not any(f"- {name}" in text for name, _ in catalog.BIG_CATS)
    assert data["index"]["migrated"] is True
    # 再建一次不崩、不重写
    catalog.build(vault)
    assert (vault / "索引.md").read_text(encoding="utf-8") == text
    assert catalog.dump_cats_text() == ""


def test_preset_none_when_index_breaks_falls_to_other(vault, monkeypatch):
    _settings(vault, {"catalogCatsPreset": "none"})
    _two_objects(vault)
    monkeypatch.setattr(indextree, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("坏了")))
    catalog.build(vault)
    data = _data(vault)
    assert data["index"] is None
    assert data["cats_order"] == [catalog.OTHER_CAT]
    assert all(it["cats"] == [catalog.OTHER_CAT] for it in data["items"])


def test_custom_list_wins_over_preset(vault):
    _settings(vault, {"catalogCats": [{"name": "吃喝", "keywords": ["菜"]}], "catalogCatsPreset": "none"})
    assert catalog.effective_big_cats() == [("吃喝", ("菜",))]
    _two_objects(vault)
    catalog.build(vault)
    assert _data(vault)["cats_order"] == ["吃喝", indextree.UNCLASSIFIED]


def test_existing_index_not_rebuilt_with_preset_none(vault):
    _settings(vault, {"catalogCats": [], "catalogCatsPreset": "none"})
    (vault / "索引.md").write_text("- 我的分类：家常菜\n", encoding="utf-8")
    _two_objects(vault)
    catalog.build(vault)
    assert (vault / "索引.md").read_text(encoding="utf-8") == "- 我的分类：家常菜\n"
    assert _data(vault)["cats_order"] == ["我的分类", indextree.UNCLASSIFIED]
