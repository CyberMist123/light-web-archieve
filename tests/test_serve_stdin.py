"""第 3 批验收④的真根因：Windows 上问答 worker 的读线程挂着同步读标准输入时，别的线程载 DLL（预热 import numpy）
会被堵在 DLL 初始化里、攥着加载锁，新线程起不来，命令行模型拿不到提示词，第一问空等到超时。
serve._private_stdin 让读线程读一份复制的句柄、进程标准输入换成 NUL。这里用子进程真跑：读线程挂着、父进程不写，
另起线程 import numpy 再起一个新线程，必须很快完成。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PROBE = r"""
import sys, threading, time
sys.path.insert(0, sys.argv[1])
from link_brain import serve
stdin = serve._private_stdin() if sys.argv[2] == 'private' else sys.stdin
threading.Thread(target=lambda: [None for _ in stdin], daemon=True).start()
time.sleep(0.5)
t0 = time.time()
def load():
    import numpy  # noqa: F401 - 有原生 DLL 的包
loader = threading.Thread(target=load); loader.start(); loader.join()
t = threading.Thread(target=lambda: None); t.start(); t.join()
print('ok', round(time.time() - t0, 1), flush=True)
"""


def _probe(mode, timeout=30):
    """读线程挂着（父进程留着管道不写），返回子进程打印的那行；timeout 秒没出 = None。"""
    import threading
    proc = subprocess.Popen([sys.executable, '-c', PROBE, str(ROOT), mode], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    got = []
    reader = threading.Thread(target=lambda: got.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    proc.kill()
    proc.wait(10)
    return got[0] if got else None


@pytest.mark.skipif(os.name != 'nt', reason='只有 Windows 的同步管道读会堵 DLL 初始化')
def test_private_stdin_keeps_dll_loads_and_thread_starts_unblocked():
    pytest.importorskip('numpy')
    line = _probe('private')
    assert line and line.startswith('ok'), '读线程挂着时 import numpy + 起新线程必须完成（不再等标准输入来一行）'


def test_private_stdin_falls_back_when_stdin_has_no_fd(monkeypatch):
    import io
    from link_brain import serve
    fake = io.StringIO('{"id": "1"}\n')
    monkeypatch.setattr(sys, 'stdin', fake)
    assert serve._private_stdin() is fake
