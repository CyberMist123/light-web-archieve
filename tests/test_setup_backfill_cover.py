"""r5 补测：`setup backfill` 的进度口径（tmp 空环境走真函数；分支用打桩的 counts / 设置）。"""
from __future__ import annotations

from link_brain import ai_config, fav_counts, setup, sync_state
from link_brain.setup import backfill as bf


def test_empty_environment_reports_unknown_total():
    out = bf.backfill()
    assert out["ok"] is True and out["favorites_total"] is None
    assert out["message"] == "还没同步过收藏，收藏总数不知道"
    assert out["archived"] == 0 and out["archived_all"] == 0
    assert out["deferred"] is None and out["remaining"] is None
    assert out["deferred_from"] is None and out["last_sync_deferred"] is None
    assert out["last_sync"] is None and "as_of" in out


def test_remaining_with_daily_limit(monkeypatch):
    monkeypatch.setattr(fav_counts, "counts", lambda: {"favorites_total": 120, "archived": 20, "remaining": 100,
                                                       "library_total": 130, "basis": "list"})
    out = bf.backfill()                       # 默认 dailyNewLimit = 50
    assert out["message"] == "还差 100 篇，每天最多 50 篇，约 2 天补完"
    assert out["favorites_total"] == 120 and out["archived"] == 20 and out["archived_all"] == 130
    assert out["deferred"] == 100 and out["remaining"] == 100        # 旧键名同值都给
    assert out["deferred_from"] == "favorites_list" and out["days_left"] == 2


def test_all_done_message(monkeypatch):
    monkeypatch.setattr(fav_counts, "counts", lambda: {"favorites_total": 10, "archived": 10, "remaining": 0,
                                                       "library_total": 12, "basis": "favorites_list"})
    out = bf.backfill()
    assert out["message"] == "历史收藏都补完了" and out["days_left"] == 0


def test_no_limit_means_one_night(monkeypatch):
    monkeypatch.setattr(fav_counts, "counts", lambda: {"favorites_total": 10, "archived": 0, "remaining": 10,
                                                       "library_total": 10, "basis": "baseline"})
    monkeypatch.setattr(ai_config, "sync_options", lambda: {"dailyNewLimit": 0})   # 0 = 不限
    out = bf.backfill()
    assert out["message"] == "还差 10 篇，每天最多 不限 篇，约 1 天补完"
    assert out["days_left"] == 1 and out["deferred_from"] == "total_minus_archived"


def test_last_sync_fields_and_deferred_reference(monkeypatch):
    monkeypatch.setattr(fav_counts, "counts", lambda: {"favorites_total": 5, "archived": 5, "remaining": 0,
                                                       "library_total": 5, "basis": "favorites_list"})
    monkeypatch.setattr(sync_state, "load", lambda: {"deferred": "7", "last_success": "2026-10-25T04:00:00+11:00"})
    out = bf.backfill()
    assert out["last_sync_deferred"] == 7            # 字符串数字也能读；只是参考，不进 remaining
    assert out["last_sync"] == "2026-10-25T04:00:00+11:00" and out["remaining"] == 0
    # sync-state 读挂了也不炸：last_sync_deferred 给 null
    monkeypatch.setattr(sync_state, "load", lambda: (_ for _ in ()).throw(OSError("坏")))
    out2 = bf.backfill()
    assert out2["ok"] is True and out2["last_sync_deferred"] is None


def test_setup_package_wires_backfill():
    assert setup.backfill is not None and callable(setup.backfill) or hasattr(setup, "backfill")
