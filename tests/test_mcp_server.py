"""Lot C 验收：子进程级测试，真起 `python -m link_brain.mcp_server`，
走 MCP stdio 握手（initialize / tools/list / tools/call），对临时 vault fixture
校验 lb_search / lb_retrieve 的返回结构；坏 JSON 输入不许崩进程。

不打真网、不调模型：lb_ask 只在 tools/list 里存在即可（真正跑它会调文本模型）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from link_brain import storage


def _make_vault(tmp_path):
    """最小 catalog-data.json fixture，照 tests/test_stream_retrieval.py 的写法。"""
    vault = tmp_path / "vault"
    (vault / "_archive").mkdir(parents=True)
    storage.write_json(vault / "_archive" / "catalog-data.json", {
        "items": [
            {
                "id": "xhs-abc12345",
                "title": "蒜香鱼片怎么做",
                "url": "https://www.xiaohongshu.com/explore/abc12345",
                "note": "Web/Xiaohongshu/蒜香鱼片怎么做__abc12345.md",
                "tags": ["菜谱"],
                "cats": ["美食"],
                "summary": "蒜香鱼片的做法",
                "date": "2026-09-01",
                "search_fields": {"body": "蒜香鱼片做法：先腌制十分钟，再下锅煎至两面金黄。" * 3},
            },
        ],
    })
    return vault


class _McpClient:
    """包一层子进程通信：一行一条 JSON-RPC 消息，带超时读取。"""

    def __init__(self, env):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "link_brain.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(storage.repo_root()), env=env, text=False, bufsize=0,
        )

    def send_raw(self, line: str) -> None:
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def send(self, message: dict) -> None:
        self.send_raw(json.dumps(message, ensure_ascii=False))

    def recv(self) -> dict:
        raw = self.proc.stdout.readline()
        if not raw:
            err = self.proc.stderr.read().decode("utf-8", "replace")
            raise AssertionError(f"server closed stdout without reply; stderr=\n{err}")
        return json.loads(raw.decode("utf-8"))

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


def _client(tmp_path, vault) -> _McpClient:
    env = dict(os.environ)
    env[storage.ENV_VAULT] = str(vault)
    env["PYTHONIOENCODING"] = "utf-8"
    client = _McpClient(env)
    client.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"},
    }})
    reply = client.recv()
    assert reply["id"] == 1
    assert reply["result"]["protocolVersion"]
    assert "tools" in reply["result"]["capabilities"]
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return client


def _call_tool(client, name, arguments, req_id):
    client.send({"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                 "params": {"name": name, "arguments": arguments}})
    reply = client.recv()
    assert reply["id"] == req_id
    assert "result" in reply, reply
    result = reply["result"]
    assert result["content"][0]["type"] == "text"
    payload = json.loads(result["content"][0]["text"])
    return result, payload


def test_initialize_tools_list_and_lb_search_lb_retrieve(tmp_path):
    vault = _make_vault(tmp_path)
    client = _client(tmp_path, vault)
    try:
        client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        reply = client.recv()
        names = {t["name"] for t in reply["result"]["tools"]}
        assert names == {"lb_search", "lb_retrieve", "lb_ask"}
        for tool in reply["result"]["tools"]:
            assert "description" in tool and "inputSchema" in tool
        ask_tool = next(t for t in reply["result"]["tools"] if t["name"] == "lb_ask")
        assert "模型" in ask_tool["description"]

        result, payload = _call_tool(client, "lb_search", {"query": "鱼片"}, 3)
        assert result["isError"] is False
        assert payload["status"] == "ok"
        assert payload["found"] >= 1
        assert payload["results"][0]["item_id"] == "xhs-abc12345"

        result, payload = _call_tool(client, "lb_retrieve", {"question": "蒜香鱼片怎么做", "top_k": 5}, 4)
        assert result["isError"] is False
        assert payload["status"] == "ok"
        assert payload["model_called"] is False
        assert payload["results"][0]["item_id"] == "xhs-abc12345"
        assert payload["results"][0]["excerpts"]
    finally:
        client.close()


def test_empty_vault_is_fail_open(tmp_path):
    vault = tmp_path / "vault"
    (vault / "_archive").mkdir(parents=True)
    client = _client(tmp_path, vault)
    try:
        result, payload = _call_tool(client, "lb_search", {"query": "任何东西"}, 2)
        assert result["isError"] is False
        assert payload["status"] == "ok"
        assert payload["found"] == 0

        result, payload = _call_tool(client, "lb_retrieve", {"question": "任何问题"}, 3)
        assert result["isError"] is False
        assert payload["results"] == []
    finally:
        client.close()


def test_missing_required_argument_returns_tool_error_not_crash(tmp_path):
    vault = _make_vault(tmp_path)
    client = _client(tmp_path, vault)
    try:
        client.send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                     "params": {"name": "lb_search", "arguments": {}}})
        reply = client.recv()
        payload = json.loads(reply["result"]["content"][0]["text"])
        assert payload["status"] == "error"

        # 进程仍然活着、还能正常应答下一个请求
        result, payload = _call_tool(client, "lb_search", {"query": "鱼片"}, 6)
        assert payload["status"] == "ok"
    finally:
        client.close()


def test_unknown_tool_and_unknown_method_return_jsonrpc_error(tmp_path):
    vault = _make_vault(tmp_path)
    client = _client(tmp_path, vault)
    try:
        client.send({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                     "params": {"name": "lb_nonexistent", "arguments": {}}})
        reply = client.recv()
        assert "error" in reply and reply["id"] == 7

        client.send({"jsonrpc": "2.0", "id": 8, "method": "not/a/method", "params": {}})
        reply = client.recv()
        assert "error" in reply and reply["id"] == 8

        # 之后仍能正常工作
        result, payload = _call_tool(client, "lb_search", {"query": "鱼片"}, 9)
        assert payload["status"] == "ok"
    finally:
        client.close()


def test_bad_json_line_does_not_crash_process(tmp_path):
    vault = _make_vault(tmp_path)
    client = _client(tmp_path, vault)
    try:
        client.send_raw("这不是 JSON { 也不闭合")
        client.send({"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}})
        # 第一行坏 JSON 应该产出一条 parse error，第二行是正常 tools/list 回应；
        # 逐条读取直到拿到 id=10 的那条，保证进程没有因为坏输入退出。
        seen = []
        for _ in range(5):
            reply = client.recv()
            seen.append(reply)
            if reply.get("id") == 10:
                break
        assert any(r.get("id") == 10 and "result" in r for r in seen)
        assert client.proc.poll() is None
    finally:
        client.close()
