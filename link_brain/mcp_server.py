"""手写 MCP stdio server（不依赖 `mcp` 包，不起 HTTP）。

协议：JSON-RPC 2.0 over stdio，一行一条消息（newline-delimited JSON），
对齐 MCP 规范 2024-11-05（`initialize` / `initialized` / `tools/list` / `tools/call`）。
参考 https://modelcontextprotocol.io/specification/2024-11-05 的 stdio transport：
- 每条消息是一个 JSON-RPC 请求/响应/通知，占一行，用 `\n` 分隔；
- server 的 stdout **只能**写协议消息，任何日志/打印都必须走 stderr。

三个 tool：
- `lb_search`：关键词检索（轻，词法），转发 `retrieval.search`。
- `lb_retrieve`：问题→材料+出处，走 BM25/hybrid 排序，**不调用模型**，转发 `retrieval.retrieve_payload`。
- `lb_ask`：完整问答，会调用配置好的文本模型（产生模型用量），转发 `ask.answer`。

fail-open：vault 为空、catalog 缺失、依赖缺失时，被转发的函数本身已经是空结果而不是异常
（见 `ask.load_items` / `retrieval.search` / `retrieval.retrieve_payload`）；这里只负责协议层
的异常兜底，绝不让一次调用失败拖垮整个常驻进程。
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "light-web-archieve"
SERVER_VERSION = "0.1.0"

TOOLS = [
    {
        "name": "lb_search",
        "description": (
            "关键词检索小红书收藏库（轻量、纯词法，不调用模型）。"
            "适合已经知道关键词、想要快速定位条目的场景。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，可以是 `#标签` 或普通词组"},
                "limit": {"type": "integer", "description": "最多返回条数，默认 20", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lb_retrieve",
        "description": (
            "针对一个问题检索材料与出处（BM25/混合排序 + 原文摘录），**不调用模型**，"
            "适合需要证据链但想自己组织答案的场景。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "自然语言问题"},
                "top_k": {"type": "integer", "description": "最多返回条目数，默认 8", "default": 8},
            },
            "required": ["question"],
        },
    },
    {
        "name": "lb_ask",
        "description": (
            "完整问答：检索材料后调用已配置的文本模型生成带引用的回答。"
            "**会产生一次模型调用/用量**，不确定是否需要模型时优先用 lb_retrieve。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "自然语言问题"},
            },
            "required": ["question"],
        },
    },
]


def _tool_lb_search(args: dict[str, Any]) -> dict[str, Any]:
    from . import retrieval

    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"status": "error", "error": "query 不能为空"}
    limit = args.get("limit", 20)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    return retrieval.search(query, limit)


def _tool_lb_retrieve(args: dict[str, Any]) -> dict[str, Any]:
    from . import retrieval

    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return {"status": "error", "error": "question 不能为空"}
    top_k = args.get("top_k", 8)
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 8
    return retrieval.retrieve_payload(question, top_k)


def _tool_lb_ask(args: dict[str, Any]) -> dict[str, Any]:
    from . import ask

    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return {"status": "error", "error": "question 不能为空"}
    return ask.answer(question)


_HANDLERS = {
    "lb_search": _tool_lb_search,
    "lb_retrieve": _tool_lb_retrieve,
    "lb_ask": _tool_lb_ask,
}


def _log(*parts: Any) -> None:
    print(*parts, file=sys.stderr, flush=True)


def _write(payload: dict[str, Any]) -> None:
    """stdout 只发协议 JSON；按 UTF-8 字节直写，绕开 Windows 控制台 GBK 编码坑
    （做法照 `read.dump_json`：小红书标题里到处是 emoji，`print()` 在 GBK 控制台会崩）。
    """
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(line)
        sys.stdout.flush()
        return
    buffer.write(line.encode("utf-8"))
    buffer.flush()


def _result(request_id: Any, result: Any) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _handle_initialize(request_id: Any, params: dict[str, Any]) -> None:
    _result(request_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    })


def _handle_tools_list(request_id: Any, params: dict[str, Any]) -> None:
    _result(request_id, {"tools": TOOLS})


def _handle_tools_call(request_id: Any, params: dict[str, Any]) -> None:
    name = params.get("name") if isinstance(params, dict) else None
    arguments = params.get("arguments") if isinstance(params, dict) else None
    if not isinstance(arguments, dict):
        arguments = {}
    handler = _HANDLERS.get(name)
    if handler is None:
        _error(request_id, -32602, f"未知 tool：{name}")
        return
    try:
        payload = handler(arguments)
    except Exception as exc:  # 任何业务异常都不许崩进程，包成 tool result isError
        _log(f"[mcp_server] tool {name} raised: {exc}")
        _log(traceback.format_exc())
        _result(request_id, {
            "content": [{"type": "text", "text": json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)}],
            "isError": True,
        })
        return
    _result(request_id, {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": bool(isinstance(payload, dict) and payload.get("status") == "error"),
    })


_METHODS = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}

# 通知（无 id，不需要响应），目前只需要能安静吞掉，不报「未知方法」
_NOTIFICATIONS = {"notifications/initialized", "initialized"}


def _dispatch(message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method in _NOTIFICATIONS:
        return  # 通知不回复
    if request_id is None:
        # 没有 id 的请求视为通知，静默忽略未知方法
        return
    handler = _METHODS.get(method)
    if handler is None:
        _error(request_id, -32601, f"未知方法：{method}")
        return
    try:
        handler(request_id, params)
    except Exception as exc:
        _log(f"[mcp_server] dispatch {method} failed: {exc}")
        _log(traceback.format_exc())
        _error(request_id, -32603, f"内部错误：{type(exc).__name__}")


def run(stdin=None, stdout=None) -> int:
    # 入站同样按 UTF-8 字节读：Windows 子进程的文本 stdin 默认 GBK 解码，
    # 客户端发的 UTF-8 中文会乱码/UnicodeDecodeError（与出站 _write 同一坑）。
    stdin = stdin or getattr(sys.stdin, "buffer", sys.stdin)
    _log(f"[mcp_server] {SERVER_NAME} {SERVER_VERSION} ready, protocol {PROTOCOL_VERSION}")
    for line in stdin:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except (ValueError, TypeError) as exc:
            # 坏 JSON：按 JSON-RPC 规范这本该没有 id，用 null；绝不崩进程
            _log(f"[mcp_server] bad json: {exc}")
            _error(None, -32700, "Parse error")
            continue
        if not isinstance(message, dict):
            _error(None, -32600, "Invalid Request")
            continue
        _dispatch(message)
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
