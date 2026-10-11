"""手写 MCP stdio server（不依赖 `mcp` 包，不起 HTTP）。

协议：JSON-RPC 2.0 over stdio，一行一条消息（newline-delimited JSON），
对齐 MCP 规范 2024-11-05（`initialize` / `initialized` / `tools/list` / `tools/call`）。
参考 https://modelcontextprotocol.io/specification/2024-11-05 的 stdio transport：
- 每条消息是一个 JSON-RPC 请求/响应/通知，占一行，用 `\n` 分隔；
- server 的 stdout **只能**写协议消息，任何日志/打印都必须走 stderr。

工具（10-09 起）：定义只有一份，在 `mcp_tools.py`，和远程 `remote serve` 共用——
search / ask / read / image / files / topics / selections / recent / history / index / wiki / guide。
旧名字 lb_search / lb_retrieve / lb_ask / lb_selections / lb_selection 不再列出，但照样能调。
白名单同远程（插件 data.json 的 remote.folders）；本机返回绝对路径。

fail-open：vault 为空、catalog 缺失、依赖缺失时，被转发的函数本身已经是空结果而不是异常
（见 `ask.load_items` / `retrieval.search` / `retrieval.retrieve_payload`）；这里只负责协议层
的异常兜底，绝不让一次调用失败拖垮整个常驻进程。
"""
from __future__ import annotations
from .errtext import errtext

import json
import sys
import traceback
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "light-web-archieve"
SERVER_VERSION = "0.2.0"

# 10-09：工具定义只有一份，在 mcp_tools.py（远程 remote serve 用的同一份）；这里只管 stdio 协议。
from . import mcp_tools  # noqa: E402

TOOLS = mcp_tools.TOOLS
_POLICY: dict[str, Any] = {}


def _ctx() -> "mcp_tools.Ctx":
    import time
    now = time.monotonic()
    if not _POLICY or now - _POLICY["at"] > 5:   # 设置里改了开放的文件夹：5 秒内生效
        _POLICY.update(at=now, policy=mcp_tools.local_policy())
    return mcp_tools.Ctx(policy=_POLICY["policy"], local=True, who="本机")


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
    from .remote.policy import Denied
    if name not in mcp_tools.HANDLERS and name not in mcp_tools.LEGACY:
        _error(request_id, -32602, f"未知 tool：{name}")
        return
    try:
        payload = mcp_tools.call(_ctx(), name, arguments)
    except Denied as d:
        _result(request_id, {"content": [{"type": "text", "text": json.dumps(
            {"status": "error", "error": d.code, "message": d.message}, ensure_ascii=False)}], "isError": True})
        return
    except Exception as exc:  # 任何业务异常都不许崩进程，包成 tool result isError
        _log(f"[mcp_server] tool {name} raised: {exc}")
        _log(traceback.format_exc())
        _result(request_id, {
            "content": [{"type": "text", "text": json.dumps(
                {"status": "error", "error": errtext(exc)}, ensure_ascii=False)}],
            "isError": True,
        })
        return
    images = payload.pop("_images", None) if isinstance(payload, dict) else None
    content = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
    import base64
    content += [{"type": "image", "data": base64.b64encode(img["data"]).decode("ascii"), "mimeType": img["mime"]}
                for img in images or []]
    _result(request_id, {
        "content": content,
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
