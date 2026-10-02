"""第 6 批「远程阅读（MCP）」：真起 uvicorn（127.0.0.1 随机端口，进程内线程），用 mcp SDK 的
Streamable HTTP 客户端 + OAuthClientProvider 走完整 OAuth，再调三个只读工具。

覆盖：OAuth 全流程（注册 → 授权 → 口令 → 换令牌 → 调工具）、刷新令牌轮换、错口令 / 锁定、
PKCE / 授权码一次性、Host / Origin、不发 CORS、令牌撤销、每令牌限速、路径越界（.. / 绝对路径 / 反斜杠 /
大小写 / 联接点 / 硬链接）、.obsidian 与 data.json 与 _archive 内部文件读不到、默认文件夹之外读不到 → 加进来能读、
search 只回白名单、访问日志不记查询词。不联网、不碰真库（conftest 已把 vault / 家目录指到 tmp）。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from link_brain import storage
from link_brain.remote import server as rserver
from link_brain.remote import store as rstore
from link_brain.remote.policy import Denied, Policy

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import remote_probe  # noqa: E402

PASS = "correct horse 9"
DOMAIN = "https://lb.example.test"
NOTE = "Web/Xiaohongshu/蒜香鱼片怎么做__abc12345.md"
AGENT = "_archive/xiaohongshu/abc12345/derived/agent.md"
ATT = "_archive/xiaohongshu/abc12345/derived/attachments/7650000000000000001.md"
NOTES = "_archive/xiaohongshu/abc12345/notes.json"
OTHER = "其他资料/蒜香私房笔记.md"
DATA_JSON = ".obsidian/plugins/link-brain-actions/data.json"


def _w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_vault(vault: Path) -> None:
    _w(vault / NOTE, "# 蒜香鱼片怎么做\n\n蒜香鱼片：鱼片先腌十分钟。\n")
    _w(vault / AGENT, "# 蒜香鱼片怎么做（机读版）\n\n" + "蒜香鱼片做法正文。" * 3000 + "\n结尾标记 END-OF-AGENT\n")
    _w(vault / ATT, "# 附件全文\n\n蒜香鱼片配料表\n")
    _w(vault / NOTES, json.dumps({"starred": True, "notes": [{"text": "下次试试"}]}, ensure_ascii=False))
    _w(vault / "_archive/xiaohongshu/abc12345/meta.json", '{"item_id": "xhs-abc12345"}')
    _w(vault / "_archive/xiaohongshu/abc12345/raw/v0001/source.json", '{"secret": "raw"}')
    _w(vault / "_archive/xiaohongshu/abc12345/derived/extracted.json", "{}")
    _w(vault / "_archive/problems.jsonl", '{"key": "x"}\n')
    _w(vault / "_archive/sync-progress.log", "log\n")
    (vault / "_archive/index.db").write_bytes(b"SQLite format 3\x00")
    _w(vault / "_trash/old.md", "删掉的东西 蒜香\n")
    _w(vault / OTHER, "# 蒜香私房笔记\n\n这是另一个文件夹里的蒜香笔记。\n")
    _w(vault / "其他资料/api-key.txt", "sk-should-never-leak\n")
    _w(vault / "其他资料/plain.txt", "蒜香 txt\n")
    _w(vault / ".obsidian/app.json", "{}")
    storage.write_json(vault / "_archive" / "catalog-data.json", {"items": [{
        "id": "xhs-abc12345", "title": "蒜香鱼片怎么做", "url": "https://www.xiaohongshu.com/explore/abc12345",
        "note": NOTE, "agent_md": AGENT, "tags": ["菜谱"], "summary": "蒜香鱼片的做法", "date": "2026-09-01",
        "search_fields": {"body": "蒜香鱼片：鱼片先腌十分钟。", "comments": "", "ocr": "", "attachments": "蒜香鱼片配料表",
                          "transcript": ""},
        "attachment_files": [], "pinyin": ""}]})


def write_settings(vault: Path, port: int, *, enabled=True, folders=("@xhs",), domain=DOMAIN) -> Path:
    p = vault / DATA_JSON
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"textAI": {"apiKey": "sk-in-data-json-should-never-leak"},
            "remote": {"enabled": enabled, "domain": domain, "port": port, "folders": list(folders)}}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    # mtime 精度：保证热重载看得到变化
    t = time.time() + (getattr(write_settings, "_bump", 0))
    write_settings._bump = getattr(write_settings, "_bump", 0) + 2
    os.utime(p, (t, t))
    return p


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Remote:
    def __init__(self, vault: Path, port: int, state: Path, app, srv, thread):
        self.vault, self.port, self.state, self.app, self.srv, self.thread = vault, port, state, app, srv, thread
        self.base = f"http://127.0.0.1:{port}"

    def set_folders(self, folders):
        write_settings(self.vault, self.port, folders=folders)
        self.app.settings._checked = 0   # 跳过 1 秒的 stat 节流
        self.app._policy_key = None

    def run(self, coro):
        return asyncio.run(coro)


@pytest.fixture
def remote(tmp_path):
    import uvicorn
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    port = free_port()
    settings = write_settings(vault, port)
    state = tmp_path / "remote-state"
    app = rserver.build(vault, settings, state, port)
    app.store.set_passphrase(PASS)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False,
                                        lifespan="on", ws="none"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started
    yield Remote(vault, port, state, app, srv, th)
    srv.should_exit = True
    th.join(10)


def _pkce():
    verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def manual_oauth(r: Remote, passphrase=PASS, *, challenge_method="S256"):
    """不经 SDK，手动走一遍，返回 (client_id, verifier, 授权码或批准页响应)。"""
    with httpx.Client(timeout=30, follow_redirects=False) as c:
        reg = c.post(r.base + "/oauth/register", json={"client_name": "手动客户端", "redirect_uris": [remote_probe.CALLBACK]})
        assert reg.status_code == 201, reg.text
        cid = reg.json()["client_id"]
        verifier, challenge = _pkce()
        q = {"response_type": "code", "client_id": cid, "redirect_uri": remote_probe.CALLBACK, "state": "st1",
             "code_challenge": challenge, "code_challenge_method": challenge_method}
        url = r.base + "/oauth/authorize?" + urlencode(q)
        status, params, text = remote_probe.approve(r.base, url, passphrase)
        return cid, verifier, status, params, text


def exchange(r: Remote, cid, verifier, code):
    return httpx.post(r.base + "/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": cid,
                                                     "redirect_uri": remote_probe.CALLBACK, "code_verifier": verifier})


def mcp_post(r: Remote, token, method="tools/list", params=None, headers=None):
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    return httpx.post(r.base + "/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def tool(r: Remote, token, name, args):
    resp = mcp_post(r, token, "tools/call", {"name": name, "arguments": args})
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    return result.get("isError", False), json.loads(result["content"][0]["text"])


# ------------------------------------------------------------------ OAuth 全流程（SDK 客户端）

def test_oauth_full_flow_with_sdk_client_then_three_tools(remote):
    async def go():
        async with remote_probe.oauth_session(remote.base, PASS) as s:
            names = sorted(t.name for t in (await s.list_tools()).tools)
            assert names == ["list", "read", "search"]           # 没有写入 / 执行 / 问答
            for t in (await s.list_tools()).tools:
                assert t.annotations.readOnlyHint is True
            err, roots = await remote_probe.call(s, "list", {})
            assert not err and [e["path"] for e in roots["entries"]] == ["Web/Xiaohongshu", "_archive/xiaohongshu"]
            err, found = await remote_probe.call(s, "search", {"query": "蒜香鱼片"})
            assert not err and found["found"] == 1
            hit = found["results"][0]
            assert (hit["path"], hit["agent_md"], hit["attachments"]) == (NOTE, AGENT, [ATT])
            err, page = await remote_probe.call(s, "read", {"path": AGENT, "max_chars": 1000})
            assert not err and len(page["text"]) == 1000 and page["next_offset"] == 1000
            assert page["total_chars"] > 20000
            err, last = await remote_probe.call(s, "read", {"path": AGENT, "offset": page["total_chars"] - 30})
            assert not err and last["next_offset"] is None and "END-OF-AGENT" in last["text"]
            err, notes = await remote_probe.call(s, "read", {"path": NOTES})
            assert not err and "下次试试" in notes["text"]
    remote.run(go())
    log = (remote.state / "access.log").read_text("utf-8")
    assert '"tool": "oauth.approve"' in log and '"tool": "read"' in log
    assert "蒜香鱼片" not in log.replace("蒜香鱼片怎么做", "")   # 不记查询词（标题出现在路径里不算）
    assert '"tool": "search"' in log


def test_oauth_tokens_persist_across_restart_and_refresh_rotates(remote):
    cid, verifier, status, params, _ = manual_oauth(remote)
    assert status == 302 and params["state"] == "st1"
    tok = exchange(remote, cid, verifier, params["code"])
    assert tok.status_code == 200 and tok.headers.get("cache-control") == "no-store"
    access, refresh = tok.json()["access_token"], tok.json()["refresh_token"]
    # 换一个 store 对象（= 服务重启后从磁盘读），令牌照样认
    again = rstore.AuthStore(remote.state)
    assert again.authenticate(access)["kind"] == "oauth"
    assert access not in (remote.state / "auth.json").read_text("utf-8")   # 只存哈希
    r2 = httpx.post(remote.base + "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": cid})
    assert r2.status_code == 200
    r3 = httpx.post(remote.base + "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": cid})
    assert r3.status_code == 400 and r3.json()["error"] == "invalid_grant"   # 旧刷新令牌用过即废
    assert mcp_post(remote, r2.json()["access_token"]).status_code == 200


def test_wrong_passphrase_rejected_and_locks_after_five(remote):
    _, _, status, params, text = manual_oauth(remote, "wrong-pass")
    assert status == 403 and not params and "口令不对" in text
    for _ in range(4):
        manual_oauth(remote, "wrong-pass")
    _, _, status, _, text = manual_oauth(remote, PASS)          # 连对的也暂时不收
    assert status == 429 and "分钟后再试" in text
    assert "BAD_PASSPHRASE" in (remote.state / "access.log").read_text("utf-8")


def test_browser_form_post_origin(remote):
    """真机 Chrome：批准页提交时带 Origin（同源）或 Origin: null（no-referrer 等情况），都不能被当成跨站拦掉。"""
    with httpx.Client(timeout=30, follow_redirects=False) as c:
        cid = c.post(remote.base + "/oauth/register", json={"redirect_uris": [remote_probe.CALLBACK]}).json()["client_id"]
        for origin in (remote.base, "null"):
            _, ch = _pkce()
            page = c.get(remote.base + "/oauth/authorize?" + urlencode({"response_type": "code", "client_id": cid,
                         "redirect_uri": remote_probe.CALLBACK, "code_challenge": ch, "code_challenge_method": "S256"}))
            assert page.headers["referrer-policy"] == "same-origin" and page.headers["x-frame-options"] == "DENY"
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            import re as _re
            rid = _re.search(r'name="request_id" value="([^"]+)"', page.text).group(1)
            r = c.post(remote.base + "/oauth/approve", data={"request_id": rid, "passphrase": PASS}, headers={"Origin": origin})
            assert r.status_code == 302 and "code=" in r.headers["location"], (origin, r.text)
        r = c.post(remote.base + "/oauth/approve", data={"request_id": "x", "passphrase": PASS}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403


def test_pkce_required_and_code_single_use(remote):
    with httpx.Client(follow_redirects=False) as c:
        cid = c.post(remote.base + "/oauth/register", json={"redirect_uris": [remote_probe.CALLBACK]}).json()["client_id"]
        r = c.get(remote.base + "/oauth/authorize?" + urlencode({"response_type": "code", "client_id": cid,
                                                                  "redirect_uri": remote_probe.CALLBACK, "state": "s"}))
        assert r.status_code == 302 and "error=invalid_request" in r.headers["location"]
    cid, verifier, status, params, _ = manual_oauth(remote)
    assert exchange(remote, cid, "x" * 50, params["code"]).status_code == 400       # 错 verifier
    assert exchange(remote, cid, verifier, params["code"]).status_code == 400       # 授权码已经被上一次拿走了
    cid, verifier, status, params, _ = manual_oauth(remote)
    assert exchange(remote, cid, verifier, params["code"]).status_code == 200
    assert exchange(remote, cid, verifier, params["code"]).status_code == 400       # 一次性


def test_register_rejects_unsafe_redirects(remote):
    for bad in (["http://evil.example/cb"], ["javascript:alert(1)"], ["https://a.example/cb#frag"], []):
        r = httpx.post(remote.base + "/oauth/register", json={"redirect_uris": bad})
        assert r.status_code == 400, bad
    with httpx.Client(follow_redirects=False) as c:
        cid = c.post(remote.base + "/oauth/register", json={"redirect_uris": ["https://ok.example/cb"]}).json()["client_id"]
        _, ch = _pkce()
        r = c.get(remote.base + "/oauth/authorize?" + urlencode({"response_type": "code", "client_id": cid,
                  "redirect_uri": "https://evil.example/cb", "code_challenge": ch, "code_challenge_method": "S256"}))
        assert r.status_code == 400 and "location" not in r.headers           # 不认的回调地址绝不跳


def test_no_passphrase_means_no_oauth(remote):
    remote.app.store.revoke_all()
    def wipe(d):
        d["passphrase"] = None
    remote.app.store._mutate(wipe)
    _, _, status, _, text = manual_oauth(remote)
    assert status == 400 and "还没设口令" in text


# ------------------------------------------------------------------ Host / Origin / CORS / 令牌

def test_host_origin_and_no_cors(remote):
    assert httpx.get(remote.base + "/healthz", headers={"Host": "evil.example"}).status_code == 421
    assert httpx.get(remote.base + "/healthz", headers={"Host": "lb.example.test"}).status_code == 200
    meta = httpx.get(remote.base + "/.well-known/oauth-protected-resource", headers={"Host": "lb.example.test"}).json()
    assert meta["resource"] == DOMAIN + "/mcp"                              # 走域名时元数据给 https 地址
    r = httpx.get(remote.base + "/healthz", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = httpx.Client().request("OPTIONS", remote.base + "/mcp", headers={"Origin": DOMAIN, "Access-Control-Request-Method": "POST"})
    assert r.status_code == 405
    for resp in (r, httpx.get(remote.base + "/healthz"), mcp_post(remote, None)):
        assert not any(k.lower().startswith("access-control-") for k in resp.headers)
    unauth = mcp_post(remote, None)
    assert unauth.status_code == 401 and "resource_metadata=" in unauth.headers["www-authenticate"]


def test_personal_token_works_then_revoked(remote):
    t = remote.app.store.new_personal("Claude 桌面")
    err, data = tool(remote, t["token"], "list", {})
    assert not err
    assert remote.app.store.revoke_personal(t["id"])
    r = mcp_post(remote, t["token"])
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_revoke_all_kills_oauth_and_personal(remote):
    cid, verifier, _, params, _ = manual_oauth(remote)
    tok = exchange(remote, cid, verifier, params["code"]).json()
    p = remote.app.store.new_personal("x")
    assert mcp_post(remote, tok["access_token"]).status_code == 200
    rstore.AuthStore(remote.state).revoke_all()        # 另一个进程（设置页的 CLI）撤销
    assert mcp_post(remote, tok["access_token"]).status_code == 401
    assert mcp_post(remote, p["token"]).status_code == 401
    r = httpx.post(remote.base + "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    assert r.status_code == 400


def test_rate_limit_per_token(remote):
    remote.app.rate = rserver.Window(3, 60)
    a = remote.app.store.new_personal("a")["token"]
    b = remote.app.store.new_personal("b")["token"]
    assert [mcp_post(remote, a).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert mcp_post(remote, b).status_code == 200                      # 别的令牌不受影响


def test_disabled_in_settings_refuses(remote):
    write_settings(remote.vault, remote.port, enabled=False)
    remote.app.settings._checked = 0
    t = remote.app.store.new_personal("x")["token"]
    assert mcp_post(remote, t).status_code == 503


# ------------------------------------------------------------------ 白名单

BAD_PATHS = [
    "../README.md", "Web/Xiaohongshu/../../README.md", "Web/Xiaohongshu/./蒜香鱼片怎么做__abc12345.md",
    "/etc/passwd", "C:/Windows/win.ini", "C:\\Windows\\win.ini", "\\\\server\\share\\x.md",
    "Web\\Xiaohongshu\\蒜香鱼片怎么做__abc12345.md", "Web//Xiaohongshu/蒜香鱼片怎么做__abc12345.md",
    "web/xiaohongshu/蒜香鱼片怎么做__abc12345.md", "Web/Xiaohongshu/蒜香鱼片怎么做__ABC12345.md",
    "Web/Xiaohongshu/蒜香鱼片怎么做__abc12345.md.", "Web/Xiaohongshu/蒜香鱼片怎么做__abc12345.md::$DATA",
    "~/x.md", "",
    DATA_JSON, ".obsidian/app.json", "_archive/index.db", "_archive/problems.jsonl", "_archive/sync-progress.log",
    "_archive/catalog-data.json", "_archive/xiaohongshu/abc12345/meta.json",
    "_archive/xiaohongshu/abc12345/raw/v0001/source.json", "_archive/xiaohongshu/abc12345/derived/extracted.json",
    "_trash/old.md", OTHER, "其他资料/api-key.txt",
]


def test_path_escapes_and_internal_files_denied(remote):
    t = remote.app.store.new_personal("x")["token"]
    for bad in BAD_PATHS:
        err, data = tool(remote, t, "read", {"path": bad})
        assert err and data["error"] in {"INVALID_PATH", "FORBIDDEN", "NOT_SHARED", "NOT_FOUND", "NOT_TEXT"}, (bad, data)
        assert "sk-" not in json.dumps(data)
    for good in (NOTE, AGENT, ATT, NOTES):
        err, _ = tool(remote, t, "read", {"path": good})
        assert not err, good
    for bad_dir in (".obsidian", "_archive/xiaohongshu/abc12345/raw", "_trash", "其他资料", "..", "C:/"):
        err, data = tool(remote, t, "list", {"path": bad_dir})
        assert err, bad_dir
    err, listing = tool(remote, t, "list", {"path": "_archive/xiaohongshu/abc12345"})
    assert not err and sorted(e["path"] for e in listing["entries"]) == [
        "_archive/xiaohongshu/abc12345/derived", NOTES]                    # raw / meta.json 不露
    err, listing = tool(remote, t, "list", {"path": "_archive/xiaohongshu"})
    assert listing["entries"][0].get("title") == "蒜香鱼片怎么做"


@pytest.mark.skipif(sys.platform != "win32", reason="联接点是 Windows 的")
def test_junction_and_hardlink_escapes_denied(remote, tmp_path):
    import _winapi
    outside = tmp_path / "outside"
    _w(outside / "secret.md", "外面的秘密\n")
    _winapi.CreateJunction(str(outside), str(remote.vault / "Web/Xiaohongshu/link"))
    os.link(remote.vault / DATA_JSON, remote.vault / "Web/Xiaohongshu/hard.md")
    t = remote.app.store.new_personal("x")["token"]
    for bad in ("Web/Xiaohongshu/link/secret.md", "Web/Xiaohongshu/hard.md"):
        err, data = tool(remote, t, "read", {"path": bad})
        assert err and data["error"] == "FORBIDDEN", (bad, data)
    err, data = tool(remote, t, "list", {"path": "Web/Xiaohongshu/link"})
    assert err
    err, listing = tool(remote, t, "list", {"path": "Web/Xiaohongshu"})
    assert "Web/Xiaohongshu/link" not in [e["path"] for e in listing["entries"]]


def test_outside_default_unreadable_until_folder_added(remote):
    t = remote.app.store.new_personal("x")["token"]
    err, data = tool(remote, t, "read", {"path": OTHER})
    assert err and data["error"] == "NOT_SHARED"
    err, found = tool(remote, t, "search", {"query": "蒜香"})
    assert not err and [r["path"] for r in found["results"]] == [NOTE]          # search 只回白名单
    remote.set_folders(["@xhs", "其他资料"])
    err, data = tool(remote, t, "read", {"path": OTHER})
    assert not err and "另一个文件夹" in data["text"]
    err, found = tool(remote, t, "search", {"query": "蒜香"})
    paths = [r["path"] for r in found["results"]]
    assert NOTE in paths and OTHER in paths and "其他资料/plain.txt" in paths
    assert "其他资料/api-key.txt" not in paths and not any(p.startswith(("_trash", ".obsidian")) for p in paths)
    err, data = tool(remote, t, "read", {"path": "其他资料/api-key.txt"})
    assert err                                                                    # 像密钥的文件名照样拒
    # 去掉收藏库只留别的文件夹：收藏的机读版也跟着读不到，search 也不再回收藏
    remote.set_folders(["其他资料"])
    err, data = tool(remote, t, "read", {"path": AGENT})
    assert err
    err, found = tool(remote, t, "search", {"query": "蒜香"})
    assert all(r["path"].startswith("其他资料/") for r in found["results"])


def test_settings_folders_are_filtered_by_policy(tmp_path):
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    pol = Policy.build(vault, ["@xhs", ".obsidian", "_archive", "../x", "C:/", "不存在", "其他资料", "其他资料"])
    assert pol.folders == ("@xhs", "其他资料")
    with pytest.raises(Denied):
        pol.resolve_file("Web/Xiaohongshu/" + "a" * 2000 + ".md")


def test_candidate_folders_skip_hidden_and_internal(tmp_path):
    from link_brain.remote.policy import candidate_folders
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    got = candidate_folders(vault)
    assert "其他资料" in got and "Web/Xiaohongshu" in got
    assert not any(g.startswith((".obsidian", "_archive", "_trash")) for g in got)
