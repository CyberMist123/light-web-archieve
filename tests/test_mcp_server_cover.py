"""r5 补测：手写 MCP stdio server 的协议层（假 stdin/stdout 全内存，不起进程、不出网）。"""
from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace as NS

from link_brain import mcp_server, mcp_tools
from link_brain.remote.policy import Denied


def _run_lines(monkeypatch, lines):
    """喂几行消息，收 (解析后的响应列表, stdout 原始字节)。"""
    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", NS(buffer=out, write=lambda s: None, flush=lambda: None))
    stdin = io.BytesIO("".join(line + "\n" for line in lines).encode("utf-8"))
    rc = mcp_server.run(stdin=stdin)
    assert rc == 0
    raw = out.getvalue().decode("utf-8")
    return [json.loads(ln) for ln in raw.splitlines() if ln.strip()], raw


def test_initialize_handshake(monkeypatch):
    (resp, raw) = _run_lines(monkeypatch, ['{"jsonrpc":"2.0","id":1,"method":"initialize"}'])
    resp = resp[0]
    assert resp["id"] == 1 and resp["jsonrpc"] == "2.0"
    assert resp["result"] == {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "light-web-archieve", "version": "0.2.0"}}
    assert "\n" in raw and raw.count("\n") == 1          # stdout 只有协议消息，一行一条


def test_tools_list_current_names_only(monkeypatch):
    resp, _ = _run_lines(monkeypatch, ['{"id":7,"method":"tools/list"}'])
    resp = resp[0]
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == [t["name"] for t in mcp_tools.TOOLS]
    for must in ("search", "ask", "read", "history", "skills"):
        assert must in names
    assert "lb_search" not in names and "lb_selection" not in names   # 旧名字不再列出


def test_unknown_method_and_notifications(monkeypatch):
    resp, _ = _run_lines(monkeypatch, [
        '{"id":2,"method":"别的方法"}',
        '{"method":"notifications/initialized"}',      # 通知：不回
        '{"method":"initialized"}',
        '{"method":"未知且无id"}',                      # 无 id 视为通知：静默
        '',
        '   ',
    ])
    assert len(resp) == 1
    assert resp[0]["id"] == 2 and resp[0]["error"]["code"] == -32601


def test_bad_json_and_non_object(monkeypatch):
    resp, _ = _run_lines(monkeypatch, ["{不是json", "[1,2]", '"一个字符串"'])
    assert [r["error"]["code"] for r in resp] == [-32700, -32600, -32600]
    assert all(r["id"] is None for r in resp)           # 坏消息按规范用 null id，进程不崩


def test_unknown_tool_rejected(monkeypatch):
    resp, _ = _run_lines(monkeypatch,
                         ['{"id":3,"method":"tools/call","params":{"name":"不存在的工具","arguments":{}}}'])
    resp = resp[0]
    assert resp["id"] == 3 and resp["error"]["code"] == -32602


def test_history_tool_offline_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    resp, _ = _run_lines(monkeypatch, ['{"id":4,"method":"tools/call","params":{"name":"history","arguments":{}}}'])
    resp = resp[0]
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["total_lines"] == 0 and payload["note"] == "还没有搜索历史"
    # 参数不是对象时当空参数用（协议层兜底）
    resp2, _ = _run_lines(monkeypatch, ['{"id":5,"method":"tools/call","params":{"name":"history"}}'])
    resp2 = resp2[0]
    assert resp2["result"]["isError"] is False


def test_tool_crash_wrapped_and_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    calls = {"report": [], "resolve": []}
    from link_brain import problems
    monkeypatch.setattr(problems, "report", lambda step, code, msg: calls["report"].append((step, code)))
    monkeypatch.setattr(problems, "resolve", lambda step, iid, code: calls["resolve"].append(code))

    def boom(ctx, name, args):
        raise ValueError("业务炸了")

    monkeypatch.setattr(mcp_tools, "call", boom)
    resp, _ = _run_lines(monkeypatch, ['{"id":1,"method":"tools/call","params":{"name":"search","arguments":{}}}'])
    resp = resp[0]
    assert resp["result"]["isError"] is True                       # 业务异常包成 tool result，不是协议 error
    assert "已记进问题记录" in resp["result"]["content"][0]["text"]
    assert calls["report"] == [("mcp", "TRANSIENT.STEP_CRASHED")]

    # 恢复正常后：崩溃标只解决一次；再崩才再报
    monkeypatch.setattr(mcp_tools, "call", lambda ctx, name, args: {"status": "ok"})
    _run_lines(monkeypatch, ['{"id":2,"method":"tools/call","params":{"name":"search"}}'])
    assert calls["resolve"] == ["TRANSIENT.STEP_CRASHED"]
    _run_lines(monkeypatch, ['{"id":3,"method":"tools/call","params":{"name":"search"}}'])
    assert calls["resolve"] == ["TRANSIENT.STEP_CRASHED"]         # 第二次成功不重复 resolve
    monkeypatch.setattr(mcp_tools, "call", boom)
    _run_lines(monkeypatch, ['{"id":4,"method":"tools/call","params":{"name":"search"}}'])
    assert len(calls["report"]) == 2


def test_denied_is_tool_result_not_protocol_error(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))

    def denied(ctx, name, args):
        raise Denied("NOT_OPEN", "收藏库没有开放给你")

    monkeypatch.setattr(mcp_tools, "call", denied)
    resp, _ = _run_lines(monkeypatch, ['{"id":9,"method":"tools/call","params":{"name":"recent"}}'])
    resp = resp[0]
    assert "error" not in resp                                   # 拒绝是正常返回
    assert resp["result"]["isError"] is True
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload == {"status": "error", "error": "NOT_OPEN", "message": "收藏库没有开放给你"}
