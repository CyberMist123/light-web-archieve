"""第 0 批：命令行模型（codex / claude）超时整棵杀（CONVENTIONS §6.6）。用 python 小脚本当假模型，不起真 CLI。"""

from __future__ import annotations

import sys
import threading
import time

from link_brain import procs, text_stream

SLOW_CLI = r"""
import subprocess, sys, time
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print("kid", kid.pid, flush=True)
time.sleep(60)
"""


def test_cli_call_times_out_and_kills_the_whole_tree():
    deltas = []
    t0 = time.monotonic()
    res = text_stream.cli_call("指令", "正文", {"command": [sys.executable, "-c", SLOW_CLI], "timeoutSec": 2},
                               on_delta=deltas.append)
    took = time.monotonic() - t0
    assert res["status"] == "failed" and res["code"] == "TRANSIENT.STEP_TIMEOUT" and "2 秒" in res["error"]
    assert took < 20
    kid = int(deltas[0].split()[1])
    assert procs.wait_gone(kid, timeout=10), "命令行模型起的子进程也要一起结束"


def test_cli_call_default_timeout_is_180_seconds(monkeypatch):
    seen = []
    real = text_stream._watch_cli

    def spy(proc, limit, *rest):
        seen.append(limit)
        return real(proc, limit, *rest)

    monkeypatch.setattr(text_stream, "_watch_cli", spy)
    res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", "print('答')"]})
    assert res["status"] == "ok" and res["text"] == "答" and seen == [180.0]
    res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", "print('答')"], "timeoutSec": 30})
    assert seen[-1] == 30.0


def test_cli_call_stop_kills_the_whole_tree_and_returns_cancelled():
    """第 3 批「停止」：CANCEL 里的 Event 一 set，命令行模型连同它的子进程整棵结束，返回 cancelled + 已生成的半截。"""
    ev = threading.Event()
    deltas = []
    token = text_stream.CANCEL.set(ev)
    try:
        threading.Timer(1.0, ev.set).start()
        t0 = time.monotonic()
        res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", SLOW_CLI], "timeoutSec": 60},
                                   on_delta=deltas.append)
    finally:
        text_stream.CANCEL.reset(token)
    assert res["status"] == "cancelled" and res["text"].startswith("kid ")
    assert time.monotonic() - t0 < 20
    kid = int(deltas[0].split()[1])
    assert procs.wait_gone(kid, timeout=10), "停止后命令行模型起的子进程也要一起结束"


def test_call_returns_cancelled_before_starting_when_already_stopped():
    ev = threading.Event()
    ev.set()
    token = text_stream.CANCEL.set(ev)
    try:
        res = text_stream.call("i", "t", {"mode": "cli", "command": [sys.executable, "-c", "print('不该跑')"]})
    finally:
        text_stream.CANCEL.reset(token)
    assert res["status"] == "cancelled"


def test_cli_call_normal_failure_unchanged():
    res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", "import sys; sys.stderr.write('坏了\\n'); sys.exit(3)"]})
    assert res["status"] == "failed" and "坏了" in res["error"] and res["code"] != "TRANSIENT.STEP_TIMEOUT"


# 第 3 批验收②④：模型自己答完退出了，但它起的子进程还活着、还拿着输出管道。
# 旧版读循环要等子进程睡完（300 秒）才结束、插件 150 秒先超时；超时 / 停止时模型已退出，看门狗也不收子进程。
EXITING_CLI = """
import subprocess, sys
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print("kid", kid.pid, flush=True)
print("答完", flush=True)
"""


def test_cli_call_model_exits_but_child_holds_pipe_finishes_and_child_is_gone():
    deltas = []
    t0 = time.monotonic()
    res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", EXITING_CLI], "timeoutSec": 60},
                               on_delta=deltas.append)
    assert res["status"] == "ok" and "答完" in res["text"]
    assert time.monotonic() - t0 < 15, "模型退出后不该等遗留子进程睡完"
    kid = int(deltas[0].split()[1])
    assert procs.wait_gone(kid, timeout=10), "模型退出后留下的子进程要结束"


def test_cli_call_stop_after_model_exited_still_kills_orphan(monkeypatch):
    monkeypatch.setattr(text_stream, "CLI_EXIT_GRACE", 30.0)  # 让「停止」先于退出收尾到达
    ev = threading.Event()
    deltas = []
    token = text_stream.CANCEL.set(ev)
    try:
        threading.Timer(2.0, ev.set).start()
        t0 = time.monotonic()
        res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", EXITING_CLI], "timeoutSec": 60},
                                   on_delta=deltas.append)
    finally:
        text_stream.CANCEL.reset(token)
    assert res["status"] == "cancelled" and time.monotonic() - t0 < 15
    kid = int(deltas[0].split()[1])
    assert procs.wait_gone(kid, timeout=10), "停止时模型已退出：它留下的子进程也要结束"


def test_kill_leftovers_ignores_reused_pid_and_reader():
    table = [{"pid": 10, "ppid": 1, "name": "python.exe", "created": 100.0},
             {"pid": 20, "ppid": 10, "name": "link-brain-reader.exe", "created": 101.0},
             {"pid": 30, "ppid": 77, "name": "python.exe", "created": 500.0},
             {"pid": 40, "ppid": 99, "name": "python.exe", "created": 300.0},
             {"pid": 50, "ppid": 99, "name": "python.exe", "created": 150.0}]
    killed = []
    import link_brain.procs as P
    orig_table, orig_term = P.process_table, P._terminate
    P.process_table, P._terminate = (lambda: table), (lambda pid: killed.append(pid) or True)
    try:
        # 99 已退出（born=200）：40 是它的孤儿；50 比 99 还早 = 父 pid 复用，不认
        # 30 在 known 里但创建时间对不上 = pid 复用，不杀；读取服务 20 即使记过也不杀
        assert P.kill_leftovers(99, 200.0, {30: 300.0, 20: 101.0}) == [40]
        assert P.kill_leftovers(99, 200.0, {30: 500.0}) == [30, 40]
    finally:
        P.process_table, P._terminate = orig_table, orig_term
