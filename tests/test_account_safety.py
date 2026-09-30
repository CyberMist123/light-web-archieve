"""1001 护号：风险码、熔断、跨进程账号锁、开页间隔、登录检查三态、卡死判定。

读取服务一律是假的（按路由应答的 httpx.request），MCP 也是假的；不开浏览器、不联网。
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

from link_brain import accounts, cli, favorites, sync_state
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"


class Reader:
    """假的读取服务：按路径应答；值可以是 dict / httpx.Response / 异常 / 可调用。"""

    def __init__(self, monkeypatch, routes):
        self.routes, self.calls = routes, []
        monkeypatch.setattr(accounts.httpx, "request", self)

    def __call__(self, method, url, json=None, timeout=None):
        route = urlsplit(url).path
        self.calls.append(route)
        value = self.routes.get(route, httpx.Response(404, json={"error": "no route"}))
        if callable(value) and not isinstance(value, httpx.Response):
            value = value()
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=value)


def _fav(note_id):
    return {"note_id": note_id, "xsec_token": "T",
            "url": f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token=T&xsec_source=pc_feed"}


def _args(**kw):
    base = dict(limit=0, origin="cli", actor="human", verbose=False, extract=False, budget_min=0, wait_lock_min=0)
    base.update(kw)
    return SimpleNamespace(**base)


def _json_out(capsys):
    return json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------
# accounts.api：断线 / 熔断码
# --------------------------------------------------------------------------


@pytest.mark.parametrize("error", [httpx.ReadError("10054 远程主机强迫关闭了一个现有的连接"),
                                   httpx.RemoteProtocolError("peer closed connection"),
                                   httpx.ConnectError("refused")])
def test_transport_errors_become_disconnected(monkeypatch, error):
    Reader(monkeypatch, {"/api/v1/attachments/download": error})
    with pytest.raises(accounts.ReaderError) as err:
        accounts.api("POST", "/api/v1/attachments/download")
    assert err.value.code == "DISCONNECTED" and not err.value.needs_human


def test_423_is_risk_hold_and_needs_human(monkeypatch):
    hold = {"code": "ACCOUNT_RISK", "since": "2026-10-01T04:02:21+08:00", "detail": "/website-login/error"}
    Reader(monkeypatch, {"/api/v1/favorites": httpx.Response(423, json={"code": "RISK_HOLD", "hold": hold}),
                         "/api/v1/notes/related-file": httpx.Response(423, json={})})
    with pytest.raises(accounts.ReaderError) as err:
        accounts.api("GET", "/api/v1/favorites")
    assert err.value.code == "RISK_HOLD" and err.value.needs_human and err.value.hold == hold
    with pytest.raises(accounts.ReaderError) as err:
        accounts.api("POST", "/api/v1/notes/related-file")
    assert err.value.code == "RISK_HOLD"
    for code in ("RISK_HOLD", "ACCOUNT_RISK"):
        assert accounts.SOLUTIONS[code][2]  # 每个码都有人话下一步


def test_risk_markers_are_blocked():
    for text in ("获取Feed详情失败: [ACCOUNT_RISK] 跳到了 /website-login/error",
                 "[RISK_HOLD] 熔断中", "[NOT_LOGGED_IN] guest", "[CAPTCHA_REQUIRED] x",
                 "navigated to https://www.xiaohongshu.com/website-login/captcha?x=1"):
        assert xhs.looks_blocked(text), text
    assert xhs.risk_code("[RISK_HOLD] x") == "RISK_HOLD"
    assert xhs.risk_code("…/website-login/error…") == "ACCOUNT_RISK"
    assert not xhs.looks_blocked("笔记不存在或已被删除")


# --------------------------------------------------------------------------
# B-1：MCP 报风险码被 anyio 包进 ExceptionGroup，也要认成「号出事」并整批停车
# --------------------------------------------------------------------------


def _fake_mcp(monkeypatch, texts, calls):
    import anyio
    import mcp
    from mcp.client import streamable_http

    @contextlib.asynccontextmanager
    async def fake_client(endpoint, timeout=None, sse_read_timeout=None):
        async with anyio.create_task_group():  # 和真的 streamablehttp_client 一样：里面抛的会被包成 ExceptionGroup
            yield (None, None, None)

    class FakeSession:
        def __init__(self, reader, writer):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            return None

        async def call_tool(self, tool, arguments):
            calls.append(arguments.get("feed_id"))
            return SimpleNamespace(isError=True, content=[SimpleNamespace(text=texts.pop(0) if texts else "x")])

    monkeypatch.setattr(streamable_http, "streamablehttp_client", fake_client)
    monkeypatch.setattr(mcp, "ClientSession", FakeSession)


def test_call_tool_unwraps_exception_group(monkeypatch):
    Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "lock": None}})
    calls = []
    _fake_mcp(monkeypatch, ["获取Feed详情失败: [ACCOUNT_RISK] 页面被跳到 /website-login/error"], calls)
    with pytest.raises(xhs.AccountBlockedError) as err:
        xhs.call_tool("get_feed_detail", {"feed_id": "a"})
    assert err.value.code == "ACCOUNT_RISK"
    # 普通「笔记没了」也要原样出来（不是 unhandled errors in a TaskGroup）
    _fake_mcp(monkeypatch, ["笔记不存在"], calls)
    with pytest.raises(xhs.AdapterError) as err:
        xhs.call_tool("get_feed_detail", {"feed_id": "b"})
    assert "笔记不存在" in str(err.value) and not isinstance(err.value, xhs.NeedsHumanError)


def test_sync_stops_at_first_risk_page_through_real_mcp_path(tmp_path, monkeypatch, capsys):
    ids = ["aaaaaaaaaaaaaaaa0001", "aaaaaaaaaaaaaaaa0002", "aaaaaaaaaaaaaaaa0003"]
    reader = Reader(monkeypatch, {
        "/api/v1/login/session": {"state": "idle", "risk_hold": None, "lock": None},
        "/api/v1/favorites": {"nickname": "alice", "items": [_fav(i) for i in ids]},
    })
    calls, alerts = [], []
    _fake_mcp(monkeypatch, ["获取Feed详情失败: 笔记不可访问: [CAPTCHA_REQUIRED] 请完成安全验证"] * 3, calls)
    monkeypatch.setattr(favorites.alert_mod, "alert", lambda *a, **k: alerts.append(a))
    code = favorites.run(_args())
    out = _json_out(capsys)
    assert code == 5
    assert calls == [ids[0]]  # 撞验证就停：后面两篇一页都没开
    assert out["items"][-1]["status"] == "blocked" and out["items"][-1]["code"] == "CAPTCHA_REQUIRED"
    assert sync_state.load()["state"] == "blocked"
    assert reader.calls.count("/api/v1/favorites") == 1 and alerts


# --------------------------------------------------------------------------
# B-3：熔断中一页不开
# --------------------------------------------------------------------------


HOLD = {"code": "ACCOUNT_RISK", "since": "2026-10-01T04:02:21+08:00", "detail": "/website-login/error"}


def test_sync_under_risk_hold_opens_nothing(monkeypatch, capsys):
    reader = Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": HOLD, "lock": None}})
    alerts = []
    monkeypatch.setattr(favorites.alert_mod, "alert", lambda *a, **k: alerts.append(a))
    code = cli.main(["sync-favorites", "--limit", "0", "--wait-lock-min", "0"])
    out = _json_out(capsys)
    assert code == 5 and out["code"] == "RISK_HOLD"
    assert reader.calls == ["/api/v1/login/session"]  # 没读收藏、没开笔记
    status = sync_state.load()
    assert status["state"] == "blocked" and status["code"] == "RISK_HOLD"
    assert not accounts.lock_path().exists() and len(alerts) == 1


def test_hold_file_is_honoured_when_reader_is_down(monkeypatch, tmp_path, capsys):
    """服务没起（或起不来）时直接读熔断文件：重启服务后熔断仍然有效。"""
    profile = accounts.profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "risk-hold.json").write_text(json.dumps(HOLD), "utf-8")
    monkeypatch.setattr(favorites.alert_mod, "alert", lambda *a, **k: None)
    assert favorites.run(_args()) == 5
    assert _json_out(capsys)["code"] == "RISK_HOLD"


def test_attachments_under_hold_exit_5_without_download(monkeypatch, capsys):
    reader = Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": HOLD}})
    assert cli.main(["attachments", "--all"]) == 5
    assert cli.main(["attachments", "--recheck", "--limit", "20"]) == 5
    assert set(reader.calls) == {"/api/v1/login/session"}


# --------------------------------------------------------------------------
# B-6：跨进程账号锁
# --------------------------------------------------------------------------


HOLDER = r"""
import sys, time
from link_brain import accounts
with accounts.account_session(sys.argv[1]):
    print("held", flush=True)
    time.sleep(float(sys.argv[2]))
"""


@contextlib.contextmanager
def _other_process_holds_lock(owner="sync-favorites", seconds=30):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, owner, str(seconds)], stdout=subprocess.PIPE,
                            text=True, env=env)
    try:
        assert proc.stdout.readline().strip() == "held"
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_lock_is_exclusive_across_processes_and_released():
    with _other_process_holds_lock():
        holder = accounts.lock_holder()
        assert holder and holder["owner"] == "sync-favorites" and holder["pid"] != os.getpid()
        with pytest.raises(accounts.AccountBusyError):
            with accounts.account_session("catch", wait_s=0):
                pass
    # 那个进程被杀（没来得及放锁）= pid 死了 → 陈旧锁，可以接管
    with accounts.account_session("catch", wait_s=0):
        info = json.loads(accounts.lock_path().read_text("utf-8"))
        assert info["pid"] == os.getpid() and info["owner"] == "catch" and info["heartbeat"]
        with accounts.account_session("nested", wait_s=0):  # 同进程可重入
            pass
        assert accounts.lock_path().exists()
    assert not accounts.lock_path().exists()


def test_lock_with_stale_heartbeat_is_taken_over():
    path = accounts.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old = time.time() - 11 * 60
    path.write_text(json.dumps({"pid": os.getppid(), "owner": "old", "started": "x",
                                "heartbeat": "2026-10-01T00:00:00+08:00", "heartbeat_ts": old}), "utf-8")
    assert accounts.lock_holder() is None
    with accounts.account_session("sync-favorites", wait_s=0):
        assert json.loads(path.read_text("utf-8"))["owner"] == "sync-favorites"


def test_sync_waits_for_lock_then_gives_up_with_exit_6_and_leaves_status_alone(monkeypatch, capsys):
    Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None}})
    sync_state.record("running", message="正在同步收藏")
    before = sync_state.path().read_text("utf-8")
    with _other_process_holds_lock():
        code = cli.main(["sync-favorites", "--wait-lock-min", "0.01"])
    out = _json_out(capsys)
    assert code == 6 and out["code"] == "ACCOUNT_BUSY"
    assert sync_state.path().read_text("utf-8") == before  # 正在跑的那一趟的状态没被冲掉


# --------------------------------------------------------------------------
# 开页间隔：跨进程共用 last-open.txt
# --------------------------------------------------------------------------


def test_pace_keeps_gap_between_account_page_opens(monkeypatch):
    monkeypatch.setenv("LWA_OPEN_GAP", "20,40")
    slept = []
    monkeypatch.setattr(accounts.time, "sleep", slept.append)
    assert accounts.pace() == 0  # 第一次：之前没开过页
    stamp = accounts.home() / "last-open.txt"
    assert float(stamp.read_text("utf-8")) == pytest.approx(time.time(), abs=5)
    accounts.pace()
    assert len(slept) == 1 and 15 <= slept[0] <= 40
    assert not list(stamp.parent.glob("last-open.txt.*.tmp"))  # 原子写，不留半截


# --------------------------------------------------------------------------
# B-7：login --status 三态 + 熔断；忙 / 锁被占时不开浏览器
# --------------------------------------------------------------------------


def _status(capsys):
    code = cli.main(["login", "--status", "--json"])
    return code, _json_out(capsys)


def test_login_status_logged_in(monkeypatch, capsys):
    reader = Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "lock": None},
                                  "/api/v1/login/status": {"is_logged_in": True, "username": "alice", "user_id": "u"}})
    code, out = _status(capsys)
    assert code == 0 and out["login_state"] == "logged_in" and out["state"] == "ready"
    assert "/api/v1/login/status" in reader.calls


def test_login_status_guest(monkeypatch, capsys):
    accounts.save({"nickname": "alice"})
    Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "lock": None},
                         "/api/v1/login/status": {"is_logged_in": False}})
    code, out = _status(capsys)
    assert code == 3 and out["login_state"] == "guest" and out["action"] == "login"


def test_login_status_risk_hold_does_not_open_browser(monkeypatch, capsys):
    reader = Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": HOLD, "lock": None}})
    code, out = _status(capsys)
    assert code == 5 and out["login_state"] == "risk_hold" and out["code"] == "RISK_HOLD"
    assert out["action"] == "login"  # 撞的是登录异常页 → 扫码
    assert reader.calls == ["/api/v1/login/session"]


@pytest.mark.parametrize("session", [
    {"state": "idle", "risk_hold": None, "lock": {"owner": "favorites", "since": "x", "held_s": 40}},
    {"state": "waiting", "risk_hold": None, "lock": None},
])
def test_login_status_busy_is_unknown_not_guest(monkeypatch, capsys, session):
    reader = Reader(monkeypatch, {"/api/v1/login/session": session})
    code, out = _status(capsys)
    assert code == 4 and out["login_state"] == "unknown"
    assert "/api/v1/login/status" not in reader.calls


def test_login_status_with_account_lock_taken_is_unknown(monkeypatch, capsys):
    reader = Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "lock": None},
                                  "/api/v1/login/status": {"is_logged_in": False}})
    with _other_process_holds_lock():
        code, out = _status(capsys)
    assert code == 4 and out["login_state"] == "unknown" and out["code"] == "ACCOUNT_BUSY"
    assert "/api/v1/login/status" not in reader.calls


def test_login_status_timeout_or_down_is_unknown(monkeypatch, capsys):
    Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle", "risk_hold": None, "lock": None},
                         "/api/v1/login/status": httpx.ReadTimeout("slow")})
    monkeypatch.setattr(accounts, "restart_reader", lambda: (_ for _ in ()).throw(accounts.ReaderError("BUSY")))
    code, out = _status(capsys)
    assert code == 4 and out["login_state"] == "unknown"
    # 服务根本不在（conftest 默认）：也是查不清
    monkeypatch.setattr(accounts.httpx, "request", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("x")))
    code, out = _status(capsys)
    assert code == 4 and out["login_state"] == "unknown"


# --------------------------------------------------------------------------
# A-3：restart_reader 只在锁占太久时才算卡死
# --------------------------------------------------------------------------


def _restart_env(monkeypatch, held):
    Reader(monkeypatch, {"/api/v1/login/session": {"state": "idle",
                                                   "lock": None if held is None else {"owner": "favorites", "held_s": held}}})
    killed = []
    monkeypatch.setattr(accounts.subprocess, "run", lambda *a, **k: killed.append(a))
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: {"state": "idle"})
    monkeypatch.setattr(accounts.time, "sleep", lambda s: None)
    return killed


@pytest.mark.skipif(os.name != "nt", reason="只在 Windows 上代管重启")
@pytest.mark.parametrize("held", [None, 30, 900])
def test_restart_reader_leaves_a_busy_reader_alone(monkeypatch, held):
    killed = _restart_env(monkeypatch, held)
    with pytest.raises(accounts.ReaderError) as err:
        accounts.restart_reader()
    assert err.value.code == "BUSY" and not killed


@pytest.mark.skipif(os.name != "nt", reason="只在 Windows 上代管重启")
def test_restart_reader_restarts_a_stuck_one(monkeypatch):
    monkeypatch.setenv("XHS_LOCK_MAX_S", "900")
    killed = _restart_env(monkeypatch, 961)
    accounts.restart_reader()
    assert len(killed) == 1
