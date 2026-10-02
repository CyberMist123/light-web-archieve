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

    class FakeTimer:
        def __init__(self, limit, fn):
            seen.append(limit)
            self.daemon = False

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(threading, "Timer", FakeTimer)
    res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", "print('答')"]})
    assert res["status"] == "ok" and res["text"] == "答" and seen == [180.0]
    res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", "print('答')"], "timeoutSec": 30})
    assert seen[-1] == 30.0


def test_cli_call_normal_failure_unchanged():
    res = text_stream.cli_call("i", "t", {"command": [sys.executable, "-c", "import sys; sys.stderr.write('坏了\\n'); sys.exit(3)"]})
    assert res["status"] == "failed" and "坏了" in res["error"] and "code" not in res
