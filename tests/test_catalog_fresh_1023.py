"""ARCH-AUDIT 第 1 批：目录跟上库（待重建记号 + ensure_fresh）、内容没变不重写（不刷屏）、篇数一个口径。"""

from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

from link_brain import catalog, storage
from tests.test_catalog import _make_object


def _vault(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    return tmp_path


def _ids(vault):
    data = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text(encoding="utf-8"))
    return {it["id"] for it in data["items"]}


def test_rebuild_without_changes_touches_no_file(tmp_path, monkeypatch):
    """刷屏根因：每次重建都重写页面 md / 脚本 / catalog-data → Dataview 整页重画。内容没变时一个都不许动。"""
    vault = _vault(tmp_path, monkeypatch)
    _make_object(vault, "a1", title="一篇", tags=["AI"], summary="概要", stem="一篇")
    catalog.build()
    catalog.build()   # 第一次建会迁移出 索引.md（index.migrated 只在那一次为真），从第二次起比
    skip = {catalog.STATE_NAME, "index-data.json"}   # 状态文件本来就记核对时间；索引树另有自己的短路
    before = {p: p.stat().st_mtime_ns for p in vault.rglob("*")
              if p.is_file() and p.name not in skip and "index-history" not in p.parts}
    time.sleep(0.05)
    catalog.build()
    changed = [str(p.relative_to(vault)) for p, m in before.items() if p.exists() and p.stat().st_mtime_ns != m]
    assert changed == []


def test_mark_dirty_then_ensure_fresh_builds_and_clears(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    _make_object(vault, "a1", title="一篇", tags=[], summary="", stem="一篇")
    catalog.build()
    assert catalog.ensure_fresh() == "clean"
    _make_object(vault, "a2", title="同步中断时进来的", tags=[], summary="", stem="二篇")
    catalog.mark_dirty("入库")
    assert catalog.dirty_state() is not None
    assert catalog.ensure_fresh() == "built"
    assert "xhs-a2" in _ids(vault)
    assert catalog.dirty_state() is None


def test_dirty_marked_during_build_survives(tmp_path, monkeypatch):
    """重建途中又有新改动：清记号时看 seq，不把新的那笔一起清掉。"""
    vault = _vault(tmp_path, monkeypatch)
    catalog.mark_dirty("入库")
    real_collect = catalog.collect

    def collect_and_mark(*a, **kw):
        out = real_collect(*a, **kw)
        catalog.mark_dirty("又来一篇")
        return out
    monkeypatch.setattr(catalog, "collect", collect_and_mark)
    catalog.build()
    assert catalog.dirty_state() is not None


def test_upsert_object_marks_dirty(tmp_path, monkeypatch):
    """所有入库路径（同步 / catch / MCP / 视频）都经 index.upsert_object → 统一在这里记待重建。"""
    import inspect
    from link_brain import index
    src = inspect.getsource(index.upsert_object)
    assert "mark_dirty" in src


def test_sync_run_refreshes_catalog_even_when_it_fails(tmp_path, monkeypatch):
    """BUGS #3：手动同步中断（抛错）后目录没重建 → 今日新增筛不到。"""
    from link_brain import favorites
    vault = _vault(tmp_path, monkeypatch)
    _make_object(vault, "s1", title="中断前已入库", tags=[], summary="", stem="中断前")
    catalog.mark_dirty("入库")

    def boom(args):
        raise RuntimeError("读取服务断了")
    monkeypatch.setattr(favorites, "_run", boom)
    try:
        favorites.run(SimpleNamespace())
    except RuntimeError:
        pass
    assert "xhs-s1" in _ids(vault)
    assert catalog.dirty_state() is None


def test_catch_refreshes_unless_deferred(tmp_path, monkeypatch):
    from link_brain import catch
    vault = _vault(tmp_path, monkeypatch)
    _make_object(vault, "c1", title="TG 发来的", tags=[], summary="", stem="TG")
    catalog.mark_dirty("入库")
    monkeypatch.setattr(catch, "catch_message", lambda *a, **kw: {"items": [{"status": "new", "item_id": "xhs-c1"}]})
    monkeypatch.setattr(catch, "_log_import", lambda payload: None)
    args = SimpleNamespace(message="x", origin="tg", actor="human", project=None, verbose=False,
                           extract=False, refresh=False, wait_lock_min=0)
    monkeypatch.setenv("LINK_BRAIN_DEFER_CATALOG", "1")
    catch.run(args)
    assert catalog.dirty_state() is not None          # 插件批量导入：等最后统一建
    monkeypatch.delenv("LINK_BRAIN_DEFER_CATALOG")
    catch.run(args)
    assert "xhs-c1" in _ids(vault) and catalog.dirty_state() is None


def test_counts_single_source(tmp_path, monkeypatch):
    """1403 / 1437：两张页的篇数都来自同一份 catalog-data；counts 写明「全部 / 我的收藏 / 其它来源」。"""
    vault = _vault(tmp_path, monkeypatch)
    _make_object(vault, "m1", title="我收的", tags=[], summary="", stem="我收的")
    _make_object(vault, "t1", title="TG 分享", tags=[], summary="", stem="TG分享")
    meta = vault / "_archive" / "xiaohongshu" / "t1" / "meta.json"
    m = json.loads(meta.read_text(encoding="utf-8"))
    m.update(origin="tg", actor="human")
    meta.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    _, _, data_path = catalog.build()
    data = json.loads(data_path.read_text(encoding="utf-8"))
    c = data["counts"]
    assert c["all"] == len(data["items"]) == data["count"] == 2
    assert c["mine"] + sum(c["by_src"].values()) == c["all"]
    assert c["mine"] == sum(1 for it in data["items"] if not it.get("src"))


def test_catalog_if_dirty_cli(tmp_path, monkeypatch, capsys):
    vault = _vault(tmp_path, monkeypatch)
    catalog.run(SimpleNamespace(print_cats=False, if_dirty=True))
    assert json.loads(capsys.readouterr().out)["state"] == "clean"
    assert not (vault / "_archive" / catalog.DATA_NAME).exists()   # 没有待重建就不碰任何文件
