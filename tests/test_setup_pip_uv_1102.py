"""1102 托管模式：补装 Python 依赖（components._pip_install）。

- 有 ~/.link-brain/bin/uv（插件「一键装好」放的）→ `uv pip install --python <当前解释器> …`（uv 建的 venv 没有 pip）；
- 没有 uv 但有 pip → `python -m pip install …`；两个都没有 → SKIPPED.NOT_CONFIGURED，一句话说 uv 从哪来（设置页「一键装好」）；
- 失败按输出分类：装不上的包 / Python 版本不符 → PERMANENT.BAD_PACKAGE；连不上 → TRANSIENT.NETWORK。
不起真进程：subprocess.Popen 换成记账的假进程。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from link_brain import problems
from link_brain.setup import common, components


class _FakeProc:
    def __init__(self, lines: list[str], code: int):
        self.stdout = iter(ln + "\n" for ln in lines)
        self._code = code
        self.pid = 4242

    def wait(self, timeout=None):
        return self._code


@pytest.fixture
def popen(monkeypatch):
    calls: list[list[str]] = []
    plan = {"lines": ["Collecting jieba", "Successfully installed jieba-0.42.1"], "code": 0}

    def fake(cmd, **kw):
        calls.append(list(cmd))
        return _FakeProc(plan["lines"], plan["code"])

    monkeypatch.setattr(components.subprocess, "Popen", fake)
    return {"calls": calls, "plan": plan}


def _uv() -> Path:
    exe = Path(os.environ["LINK_BRAIN_HOME"]) / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    return exe


def test_uses_managed_uv_when_present(popen):
    uv = _uv()
    events = []
    components._pip_install("core", ["jieba>=0.42.1"], events.append)
    assert popen["calls"] == [[str(uv), "pip", "install", "--python", sys.executable, "jieba>=0.42.1"]]
    assert events[0]["text"].startswith("uv pip install"), "进度里说的是真在跑的命令"


def test_falls_back_to_pip_without_uv(popen, monkeypatch):
    assert components.managed_uv() is None
    monkeypatch.setattr(components, "_has", lambda m: m == "pip")
    components._pip_install("core", ["jieba>=0.42.1"], None)
    assert popen["calls"] == [[sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "jieba>=0.42.1"]]


def test_neither_uv_nor_pip_says_where_uv_comes_from(popen, monkeypatch):
    monkeypatch.setattr(components, "_has", lambda m: False)
    with pytest.raises(common.SetupError) as e:
        components._pip_install("core", ["jieba"], None)
    assert e.value.code == "SKIPPED.NOT_CONFIGURED"
    assert "一键装好" in e.value.message and "uv" in e.value.message, "修前：只说「用 uv tool install 重装」，没说 uv 从哪来"
    assert popen["calls"] == []


@pytest.mark.parametrize("tail,code", [
    (["  ERROR: Failed building wheel for onnxruntime", "ERROR: Could not build wheels"], "PERMANENT.BAD_PACKAGE"),
    (["ERROR: No matching distribution found for rapidocr>=3.9"], "PERMANENT.BAD_PACKAGE"),
    (["ERROR: Package 'mcp' requires a different Python: 3.9.2 not in '>=3.10'"], "PERMANENT.BAD_PACKAGE"),
    (["requests.exceptions.ConnectionError: HTTPSConnectionPool(host='pypi.org')"], "TRANSIENT.NETWORK"),
    (["ReadTimeoutError: HTTPSConnectionPool(host='files.pythonhosted.org', port=443): Read timed out."], "TRANSIENT.NETWORK"),
    (["ProxyError: Cannot connect to proxy."], "TRANSIENT.NETWORK"),
    (["something odd happened"], "TRANSIENT.NETWORK"),
])
def test_failure_classified_by_output(popen, tail, code):
    _uv()
    popen["plan"].update(lines=tail, code=1)
    with pytest.raises(common.SetupError) as e:
        components._pip_install("ocr", ["rapidocr>=3.9"], None)
    assert e.value.code == code
    assert tail[-1].strip() in e.value.message, "最后一行原样带给人看"
    assert problems.classify(code) in ("PERMANENT", "TRANSIENT")
    assert code in problems.STATE_REGISTRY, "新用到的码都在登记表里"


def test_install_core_result_carries_classified_code(popen, monkeypatch):
    """走 components.install：失败码照原样进结果 JSON（CONVENTIONS §1 的 {ok, code, message}）。"""
    _uv()
    monkeypatch.setattr(components, "_has", lambda m: m == "pip")   # 假装缺所有核心依赖
    popen["plan"].update(lines=["ERROR: No matching distribution found for numpy>=1.26"], code=1)
    out = components.install("core", None)
    assert out["ok"] is False and out["code"] == "PERMANENT.BAD_PACKAGE"
    assert "numpy" in out["message"]
