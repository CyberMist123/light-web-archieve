"""1024 第 1 波 p0-runtime：MCP / 问答 worker 崩了 → 回人话原因（errtext）+ 问题记录一条；目录读不出来明说。"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from link_brain import mcp_server, mcp_tools, problems, serve
from link_brain.remote.policy import Denied

from test_batch3_feedback import _Stdin


def _boom_group(*a, **k):
    # ExceptionGroup：只写类名会丢掉真因（errtext 那一节的老坑）
    raise ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("索引坏了")])


def _rows(step):
    return [r for r in problems.load() if r["step"] == step]


def test_mcp_tool_crash_returns_reason_and_reports(monkeypatch, capsys):
    monkeypatch.setattr(mcp_tools, "call", _boom_group)
    monkeypatch.setattr(mcp_server, "_ctx", lambda: None)
    mcp_server._dispatch({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                          "params": {"name": "search", "arguments": {"query": "鱼"}}})
    reply = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert reply["result"]["isError"] is True
    body = json.loads(reply["result"]["content"][0]["text"])
    assert "索引坏了" in body["message"]
    [row] = _rows("mcp")
    assert row["code"] == "TRANSIENT.STEP_CRASHED" and "索引坏了" in row["reason"]


def test_mcp_dispatch_crash_uses_errtext_and_reports(monkeypatch, capsys):
    monkeypatch.setitem(mcp_server._METHODS, "tools/list", lambda rid, params: _boom_group())
    mcp_server._dispatch({"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}})
    reply = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert reply["error"]["code"] == -32603 and "索引坏了" in reply["error"]["message"]
    assert _rows("mcp"), "协议层崩溃也要登记"


def test_catalog_unreadable_is_an_explicit_error_not_empty(monkeypatch):
    import link_brain.ask as ask_mod

    def broken():
        raise OSError("catalog-data.json 被占用")
    monkeypatch.setattr(ask_mod, "load_items", broken)
    with pytest.raises(Denied) as got:
        mcp_tools._items()
    assert got.value.code == "CATALOG_UNREADABLE" and "被占用" in got.value.message


def test_answer_worker_crash_reports_problem(monkeypatch, capsys):
    monkeypatch.setattr(serve.ask, "answer", _boom_group)
    monkeypatch.setattr(serve, "_warm", lambda: None)
    stdin, out = _Stdin(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", out)
    worker = threading.Thread(target=serve.run, args=(SimpleNamespace(),), daemon=True)
    worker.start()
    stdin.put({"id": "9", "question": "随便"})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and '"type": "result"' not in out.getvalue():
        time.sleep(0.05)
    stdin.put(None)
    worker.join(5)
    events = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    result = next(e["result"] for e in events if e["type"] == "result")
    assert "索引坏了" in result["markdown"], "原因要写真因，不能只有 ExceptionGroup 的类名"
    [row] = _rows("ask")
    assert row["code"] == "TRANSIENT.STEP_CRASHED" and "索引坏了" in row["reason"]
