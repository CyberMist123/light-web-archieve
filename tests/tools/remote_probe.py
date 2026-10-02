"""远程阅读的 MCP 客户端探针：用 mcp SDK 的 Streamable HTTP 客户端 + OAuthClientProvider 走一遍
「动态注册 → 授权 → 批准页输口令 → 换令牌 → 调工具」。pytest（tests/test_remote_mcp.py）和真机验收共用。

真机（只在 127.0.0.1）：
    python tests/tools/remote_probe.py http://127.0.0.1:<端口> --query "关键词"
口令从环境变量 LB_REMOTE_PASSPHRASE 读（不进命令行参数）。只读：只调 list / search / read。
打印的是摘要（条数、路径、字数），不打印正文。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import sys
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

CALLBACK = "http://127.0.0.1:9/lb-probe-callback"   # 不需要真有人监听：批准页的 302 我们自己截下来


class MemoryStorage:
    def __init__(self):
        self.tokens = None
        self.client_info = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, info):
        self.client_info = info


def approve(base: str, authorize_url: str, passphrase: str) -> tuple[int, dict[str, str], str]:
    """打开批准页、填口令提交；返回 (状态码, 回调参数, 页面文字)。"""
    with httpx.Client(timeout=30, follow_redirects=False) as c:
        page = c.get(authorize_url)
        m = re.search(r'name="request_id" value="([^"]+)"', page.text)
        if page.status_code != 200 or not m:
            return page.status_code, {}, page.text
        r = c.post(base + "/oauth/approve", data={"request_id": m.group(1), "passphrase": passphrase})
        if r.status_code != 302:
            return r.status_code, {}, r.text
        q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
        return 302, q, ""


@contextlib.asynccontextmanager
async def oauth_session(base: str, passphrase: str, *, storage: MemoryStorage | None = None, client_name: str = "lb-probe"):
    from mcp import ClientSession
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.auth import OAuthClientMetadata

    storage = storage or MemoryStorage()
    holder: dict[str, Any] = {}

    async def redirect_handler(url: str) -> None:
        status, params, text = await asyncio.to_thread(approve, base, url, passphrase)
        if status != 302 or "code" not in params:
            raise RuntimeError(f"批准没通过：HTTP {status}")
        holder.update(params)

    async def callback_handler():
        return holder["code"], holder.get("state")

    provider = OAuthClientProvider(
        server_url=base + "/mcp",
        client_metadata=OAuthClientMetadata(client_name=client_name, redirect_uris=[CALLBACK],
                                            grant_types=["authorization_code", "refresh_token"],
                                            response_types=["code"], token_endpoint_auth_method="none"),
        storage=storage, redirect_handler=redirect_handler, callback_handler=callback_handler)
    async with httpx.AsyncClient(auth=provider, timeout=60) as client:
        async with streamable_http_client(base + "/mcp", http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


@contextlib.asynccontextmanager
async def token_session(base: str, token: str):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        async with streamable_http_client(base + "/mcp", http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def call(session, name: str, args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """调一个工具 → (isError, 解析后的 JSON)。"""
    res = await session.call_tool(name, args)
    text = "".join(getattr(c, "text", "") for c in res.content)
    try:
        data = json.loads(text)
    except ValueError:
        data = {"raw": text}
    return bool(res.isError), data


async def _main(base: str, query: str) -> int:
    passphrase = os.environ.get("LB_REMOTE_PASSPHRASE", "")
    if not passphrase:
        print("要设环境变量 LB_REMOTE_PASSPHRASE", file=sys.stderr)
        return 2
    async with oauth_session(base, passphrase) as s:
        tools = sorted(t.name for t in (await s.list_tools()).tools)
        print("tools:", tools)
        err, roots = await call(s, "list", {})
        print("list roots:", err, [e["path"] for e in roots.get("entries", [])])
        err, listing = await call(s, "list", {"path": "Web/Xiaohongshu", "limit": 3})
        print("list Web/Xiaohongshu:", err, "total", listing.get("total"), [e["path"] for e in listing.get("entries", [])])
        err, found = await call(s, "search", {"query": query, "limit": 5})
        print("search:", err, "found", found.get("found"))
        for r in found.get("results", []):
            print("  -", r.get("title"), "|", r.get("path"), "|", r.get("agent_md"), "| attachments", len(r.get("attachments") or []))
        first = next((r for r in found.get("results", []) if r.get("agent_md")), None)
        if first:
            err, page = await call(s, "read", {"path": first["agent_md"], "max_chars": 2000})
            print("read agent_md:", err, "total_chars", page.get("total_chars"), "next_offset", page.get("next_offset"))
            if page.get("next_offset"):
                err, page2 = await call(s, "read", {"path": first["agent_md"], "offset": page["next_offset"], "max_chars": 2000})
                print("read page 2:", err, "offset", page2.get("offset"))
        for bad in (".obsidian/plugins/link-brain-actions/data.json", "_archive/index.db", "_archive/problems.jsonl",
                    "../README.md", "Web/Xiaohongshu/../../README.md", "C:/Windows/win.ini", "web/xiaohongshu"):
            err, data = await call(s, "read", {"path": bad})
            print("read", bad, "->", "denied" if err else "ALLOWED!", data.get("error"))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="http://127.0.0.1:<端口>")
    ap.add_argument("--query", default="教程")
    a = ap.parse_args()
    sys.exit(asyncio.run(_main(a.base.rstrip("/"), a.query)))
