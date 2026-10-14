"""1015 设置页「定时同步」：每次同步最多收几篇（perRunLimit）、补评论节奏（commentFillGap）。

入口是真的（favorites 同步循环 / comment_fill.survey），网络那一侧用 test_night_sync 的假读取服务。"""
from __future__ import annotations

from datetime import timedelta

from link_brain import ai_config, comment_fill, sync_state

from test_account_safety import _fav
from test_night_sync import _ids, _run, env, summary_model_configured  # noqa: F401 - pytest 夹具


def _with_sync(monkeypatch, **sync):
    settings = ai_config._deep_merge(ai_config.DEFAULTS, {"sync": sync, "textAI": {
        "mode": "http", "endpoint": "https://llm.example.invalid/v1/chat/completions", "model": "fake-model"}})
    monkeypatch.setattr(ai_config, "load", lambda: settings)


def test_per_run_limit_rules():
    f = ai_config.per_run_limit
    assert [f(None), f(""), f("abc"), f(-2), f(0), f(True)] == [0] * 6, "空 / 乱填 / 0 = 不限"
    assert [f(5), f("12")] == [5, 12]


def test_fill_gap_only_slower_choices():
    g = ai_config.comment_fill_gap
    assert [g(45), g("90"), g(180)] == [45, 90, 180]
    assert [g(10), g(None), g("x"), g(60)] == [45, 45, 45, 45], "比 45 分钟密 / 不在选项里的一律 45"


def test_sync_options_carry_new_keys_with_defaults(monkeypatch):
    _with_sync(monkeypatch)
    opts = ai_config.sync_options()
    assert opts["perRunLimit"] == 0 and opts["commentFillGap"] == 45 and opts["dailyNewLimit"] == 50
    _with_sync(monkeypatch, perRunLimit="3", commentFillGap=5)
    opts = ai_config.sync_options()
    assert opts["perRunLimit"] == 3 and opts["commentFillGap"] == 45


def test_per_run_limit_stops_this_run_and_says_next_sync(env, monkeypatch, capsys):
    _with_sync(monkeypatch, perRunLimit=2, dailyNewLimit=50)
    env.favs = [_fav(i) for i in _ids(5)]
    code, out = _run(capsys)
    assert code == 0 and env.fetched == _ids(2), "这次只收 2 篇"
    assert out["deferred"] == 3 and out["deferred_reason"] == "run_limit" and out["run_limit"] == 2
    assert sync_state.load()["message"] == "这次收满 2 篇，还有 3 篇下次同步接着收"


def test_per_run_zero_is_unlimited(env, monkeypatch, capsys):
    _with_sync(monkeypatch, perRunLimit=0, dailyNewLimit=50)
    env.favs = [_fav(i) for i in _ids(3)]
    code, out = _run(capsys)
    assert code == 0 and env.fetched == _ids(3) and not out.get("deferred")


def test_fill_gap_setting_slows_cooling(monkeypatch):
    _with_sync(monkeypatch, commentFillGap=180)
    assert comment_fill.fill_gap_min() == 180
    _with_sync(monkeypatch, commentFillGap=1)
    assert comment_fill.fill_gap_min() == comment_fill.FILL_GAP_MIN, "不许比默认更密"
    monkeypatch.setattr(ai_config, "sync_options", lambda: (_ for _ in ()).throw(ValueError("坏设置")))
    assert comment_fill.fill_gap_min() == comment_fill.FILL_GAP_MIN, "设置坏了按默认"


def test_survey_uses_configured_gap(monkeypatch):
    now = comment_fill._now()
    src = {"note": {"title": "t"}, "comments": []}
    monkeypatch.setattr(comment_fill, "_objects", lambda: [("xiaohongshu", "abc")])
    monkeypatch.setattr(comment_fill, "current_source", lambda k, i: ({}, src))
    monkeypatch.setattr(comment_fill, "load_state", lambda k, i: {})
    monkeypatch.setattr(comment_fill, "scope", lambda s, f, st=None: {"missing": 3, "more_floors": False})
    monkeypatch.setattr(comment_fill, "plan_fill", lambda sc: ("expand", [1]))
    monkeypatch.setattr(comment_fill, "is_stuck", lambda st, f: False)
    monkeypatch.setattr(comment_fill, "last_open", lambda s, st: now - timedelta(minutes=100))
    from link_brain import restricted
    monkeypatch.setattr(restricted, "is_restricted", lambda sid: False)
    _with_sync(monkeypatch, commentFillGap=45)
    assert len(comment_fill.survey(floors=10, now=now)["ready"]) == 1, "隔了 100 分钟 > 45：能续"
    _with_sync(monkeypatch, commentFillGap=180)
    sv = comment_fill.survey(floors=10, now=now)
    assert not sv["ready"] and len(sv["cooling"]) == 1, "调成 3 小时：100 分钟前开过的还在冷却"
