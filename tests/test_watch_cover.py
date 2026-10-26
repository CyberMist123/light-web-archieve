"""watch 的补充用例：只测 _age 和 render 这两个纯函数（snapshot / run 会碰本机文件和终端，不盖）。

render 用假 snapshot 喂、color=False 断言关键文字；now 用固定的带时区时刻，不依赖机器时钟。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from link_brain import watch as w

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone(timedelta(hours=11)))


def _snap(**over):
    base = {"now": NOW, "hold": {}, "sub": {}, "strikes": {}, "crawl": {}, "fill": {}, "sync": {}, "rows": []}
    base.update(over)
    return base


def test_age_buckets_and_bad_input():
    ago = lambda secs: (NOW - timedelta(seconds=secs)).isoformat()
    assert w._age(ago(30), NOW) == "30s 前"
    assert w._age(ago(119), NOW) == "119s 前"          # 2 分钟以下是秒
    assert w._age(ago(120), NOW) == "2 分钟前"
    assert w._age(ago(119 * 60), NOW) == "119 分钟前"
    assert w._age(ago(120 * 60), NOW) == "2 小时前"    # 2 小时起按小时
    assert w._age(ago(26 * 3600), NOW) == "26 小时前"
    assert w._age("not-a-ts", NOW) == ""               # 认不出的时间戳出空串
    assert w._age(None, NOW) == ""


def test_age_naive_timestamp_treated_as_local():
    local = NOW.astimezone()                            # 固定时刻换算到本机时区
    naive = local.replace(tzinfo=None, microsecond=0)
    assert w._age(naive.isoformat(), NOW) == "0s 前"    # 无时区的时间戳按本地时区补
    assert w._age((naive - timedelta(minutes=5)).isoformat(), NOW) == "5 分钟前"


def test_render_healthy_screen():
    out = w.render(_snap(), color=False)
    assert "LWA 实时进度  10-26 12:00:00" in out
    assert "（只读本机文件，不碰号；Ctrl+C 退出）" in out
    assert "号：正常" in out
    assert "楼中楼：这一小时已展开 0 次" in out
    assert "（24 小时内没有用号记录）" in out
    assert "交替抓取" not in out and "补评论" not in out and "收藏同步" not in out   # 空段整段不出现
    assert "\x1b" not in out                            # color=False 一点 ANSI 码都不带
    assert "\x1b[1m" in w.render(_snap())               # 默认 color=True 带加粗码


def test_render_hold_states():
    out = w.render(_snap(hold={"code": "XHS_RATE_LIMITED", "strikes": 2, "until": "2026-10-26T15:30:00"}),
                   color=False)
    assert "号：限频冷却中（第 2 次），冷却到 10-26 15:30，到点自己试，不用管" in out
    out = w.render(_snap(hold={"code": "ACCOUNT_RISK", "since": "2026-10-26T10:00:00", "detail": "x" * 200}),
                   color=False)
    assert "号：熔断中 ACCOUNT_RISK（自 10-26 10:00）——要你处理：" + "x" * 80 in out
    assert "x" * 81 not in out                          # detail 截到 80 字


def test_render_sub_clicks_within_hour_and_strikes():
    clicks = [(NOW - timedelta(minutes=30)).isoformat(), (NOW - timedelta(minutes=59)).isoformat(),
              (NOW - timedelta(minutes=61)).isoformat(), "bad"]     # 一小时外和坏时间戳都不算
    out = w.render(_snap(sub={"clicks": clicks}, strikes={"strikes": 3, "last": "2026-10-25T09:05:00"}),
                   color=False)
    assert "楼中楼：这一小时已展开 2 次 · 24h 内限频 3 次（最后 10-25 09:05）" in out


def test_render_crawl_fill_sync_sections():
    snap = _snap(
        crawl={"state": "跑着", "message": "第 3 轮", "updated_at": (NOW - timedelta(minutes=10)).isoformat(),
               "history": [{"minutes": 9},                       # 没 block 的历史行不进「最近」
                           {"block": "b1", "minutes": 5}, {"block": "b2", "skipped": True}]},
        fill={"state": "done", "message": "m" * 100, "done": 7,
              "updated_at": (NOW - timedelta(hours=2)).isoformat()},
        sync={"label": "增量", "state": "", "message": "n" * 80, "live": {"done": 3, "total": 9}},
    )
    out = w.render(snap, color=False)
    assert "交替抓取  跑着 · 第 3 轮  10 分钟前" in out
    assert "最近：b1(5分) → b2(跳过)" in out
    assert "补评论  done · " + "m" * 70 + "  已补齐 7 · 2 小时前" in out
    assert "m" * 71 not in out                            # 补评论 message 截 70
    assert "收藏同步  增量 3/9 · " + "n" * 60 in out
    assert "n" * 61 not in out                            # 同步 message 截 60


def test_render_usage_counts_pause_and_recent_rows():
    ts = "2026-10-26T{}+11:00"
    rows = [
        {"action": "note", "ok": True, "ts": ts.format("11:30:00"), "item": "abcdefgh12345678",
         "trigger": "auto", "secs": 3, "sub_clicks": 2},
        {"action": "note", "ok": False, "ts": ts.format("11:00:00"), "code": "ACCOUNT_RISK"},
        {"action": "note", "ok": False, "ts": ts.format("11:30:00"), "code": "XHS_RATE_LIMITED",
         "error_code": 1001, "reject": "xhs"},
        {"action": "favorites", "ok": False, "ts": ts.format("11:10:00"), "code": "SOME"},
    ]
    out = w.render(_snap(rows=rows), color=False)
    assert "24 小时用号  读收藏列表 ok0 错1  开笔记 ok1 拦2" in out      # 按动作名排序；拦/错只在非零时出现
    assert "暂停：「开笔记」72 小时内被小红书拦了 2 次（1001、ACCOUNT_RISK），暂停到 10-27 11:30" in out  # codes 取 error_code 或 code
    assert "[auto] 开笔记 12345678" in out and "ok 3s 楼中楼点 2" in out   # ok 行：耗时 + 楼中楼点击
    assert "XHS_RATE_LIMITED 1001 @xhs" in out                             # 被拦行：code + error_code + 降级处
