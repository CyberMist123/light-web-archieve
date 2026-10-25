"""crawl 的补充用例（write_status / read_status 已有 test_atomic_write_leftovers.py，这里不重复）。

plan_block 是纯函数；run 的 sleep / run_block / clock / busy 都是参数，全部传假的进去——
不真睡、不起子进程，状态文件落在 conftest 指到的 tmp LINK_BRAIN_HOME。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from link_brain import crawl


class _Clock:
    """每次调用返回当前值再前进 step：让 run 里的计时完全可控。"""

    def __init__(self, step: float = 1.0):
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        v = self.t
        self.t += self.step
        return v


def _args(**kw):
    return SimpleNamespace(hours=kw.get("hours", 0), fav_min=5, comments_min=5)


def test_plan_block_order_and_wrap():
    assert crawl.plan_block(0, last_list_read=None, now=1000.0) == 0
    assert crawl.plan_block(2, last_list_read=None, now=1000.0) == 2
    assert crawl.plan_block(3, last_list_read=None, now=0.0) == 3
    assert crawl.plan_block(4, last_list_read=None, now=0.0) == 0     # 回绕到轮换开头


def test_plan_block_skips_fresh_list_read():
    # 读列表的块要隔 FAV_LIST_GAP_MIN 分钟：刚读过 → 往后挪到 comments；隔够了 → 就跑 fav_new
    assert crawl.plan_block(0, last_list_read=1000.0, now=1000.0 + 60) == 1
    assert crawl.plan_block(0, last_list_read=1000.0, now=1000.0 + crawl.FAV_LIST_GAP_MIN * 60) == 0
    assert crawl.plan_block(0, last_list_read=None, now=1000.0) == 0  # 从没读过 = 可以读


def test_plan_block_all_skipped_falls_back(monkeypatch):
    monkeypatch.setattr(crawl, "ROTATION", [("fav_new", "favorites", []), ("fav_new", "favorites", [])])
    assert crawl.plan_block(0, last_list_read=0.0, now=60.0) == 1     # 全都跳过时取 (i+1) % n


def test_run_stops_on_exit_5(monkeypatch):
    blocks, sleeps = [], []

    def run_block(cmd, block):
        blocks.append((block, cmd))
        return 5
    out = crawl.run(_args(hours=1), sleep=sleeps.append, run_block=run_block, clock=_Clock(step=1), busy=lambda: "")
    assert out == 5
    assert [b for b, _ in blocks] == ["fav_new"]                       # 第一块就被 5 打断
    cmd = blocks[0][1]
    assert cmd[:3] == ["sync-favorites", "--limit", "0"] and "5" in cmd  # {m} 换成了 fav_min
    assert sleeps == []                                                # 直接停，中间没歇
    st = crawl.read_status()
    assert st["state"] == "stopped" and "要你处理" in st["message"]
    assert st["history"] and st["history"][-1]["exit"] == 5


def test_run_busy_waits_then_finishes():
    sleeps = []
    out = crawl.run(_args(hours=0.25), sleep=sleeps.append,
                    run_block=lambda cmd, b: pytest.fail("busy 时不该跑块"),
                    clock=_Clock(step=301), busy=lambda: "夜跑在跑（等待）")
    assert out == 0
    assert sleeps and all(s == 300 for s in sleeps)                    # 每次歇 5 分钟再看
    assert crawl.read_status()["state"] == "done"


def test_run_all_blocks_paused_waits_half_hour(monkeypatch):
    monkeypatch.setattr(crawl.actionlog, "repeat_pause", lambda action, *a, **k: ("上次被拦", None))
    sleeps = []
    out = crawl.run(_args(hours=0.001), sleep=sleeps.append,
                    run_block=lambda cmd, b: pytest.fail("都在暂停期不该跑块"),
                    clock=_Clock(step=1), busy=lambda: "")
    assert out == 0
    assert sleeps and all(s == 1800 for s in sleeps)                   # 半小时后再看
    st = crawl.read_status()
    assert st["state"] == "done"
    assert st["history"] and all("skipped" in h for h in st["history"])   # 跳过记录进 history


def test_run_forces_rest_after_work_min(monkeypatch):
    from link_brain import comment_fill
    monkeypatch.setattr(comment_fill, "WORK_MIN", 30)                  # 干活额度 1800 秒：一块 2000 秒就超
    monkeypatch.setattr(comment_fill, "REST_MIN", 1)
    blocks, sleeps = [], []
    out = crawl.run(_args(hours=1), sleep=sleeps.append,
                    run_block=lambda cmd, b: blocks.append(b) or 0,
                    clock=_Clock(step=2000), busy=lambda: "")
    assert out == 0
    assert blocks == ["fav_new"]                                       # 歇完时间也到了 → done
    assert 60 in sleeps or 60.0 in sleeps                              # REST_MIN 分钟的强制歇
    assert crawl.read_status()["state"] == "done"


def test_run_follows_rotation_and_records_history():
    blocks = []
    out = crawl.run(_args(hours=0.005), sleep=lambda s: None,
                    run_block=lambda cmd, b: blocks.append(b) or 0,
                    clock=_Clock(step=1), busy=lambda: "")
    assert out == 0
    assert blocks[:3] == ["fav_new", "comments", "fav_backlog"]        # 按轮换顺序排班
    st = crawl.read_status()
    assert st["state"] == "done" and len(st["history"]) == len(blocks)
