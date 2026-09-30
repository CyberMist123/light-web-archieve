"""测试永远不许联网、不许碰真库、不许起本机的小红书组件。

`ingest` 现在会去笔记网页版探一次附件元数据（`xhs.fetch_related_file`）。
这里 autouse 地把它换成"没探到"，让所有测试确定性地走正文线索那条回退路径；
要测探测成功的行为，在用例里自己 monkeypatch 覆盖掉。

1001（审计 G-2/G-3）：
- 每个用例的 vault 和 ~/.link-brain 都指到 tmp（以前没设 LINK_BRAIN_VAULT，跑一次就往真库写假进度和每日计数）；
- relatedfile.exe 指到不存在的路径（real_web_probe 用例以前真起过游客浏览器开小红书）；
- 最后一道保险：测试里 subprocess 调到 ~/.xiaohongshu-mcp 下任何 exe、或 httpx 连到读取服务端口 /
  小红书域名，直接报错，而不是悄悄跑出去。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest

from link_brain import semantic
from link_brain.adapters import xiaohongshu as xhs

# 在任何用例改 Path.home 之前记下真的家目录（不写死用户名：这是公开仓）
_XHS_TOOL_DIR = os.path.normcase(str(Path.home() / ".xiaohongshu-mcp"))
_READER_PORTS = {18060, 18061, 18062}
_XHS_HOSTS = ("xiaohongshu.com", "rednote.com", "xhslink.com", "xhslink.cn", "xhscdn.com")


def _argv_parts(args) -> list[str]:
    if isinstance(args, (str, bytes, os.PathLike)):
        return [os.fsdecode(args)]
    return [os.fsdecode(a) for a in args if isinstance(a, (str, bytes, os.PathLike))]


def _touches_xhs_tools(args) -> bool:
    for part in _argv_parts(args):
        low = os.path.normcase(part.strip('"'))
        if _XHS_TOOL_DIR in low and ".exe" in low:
            return True
        # accounts.restart_reader 用 powershell 按进程名结束读取服务和它的浏览器：测试里走到这一步就是在杀本机真服务
        if "link-brain-reader" in low:
            return True
    return False


_RealPopen = subprocess.Popen


class _GuardedPopen(_RealPopen):
    def __init__(self, args, *a, **kw):
        if _touches_xhs_tools(args):
            raise RuntimeError(f"测试不许起本机小红书组件：{_argv_parts(args)[:2]}")
        super().__init__(args, *a, **kw)


_real_handle_request = httpx.HTTPTransport.handle_request
_real_handle_async_request = httpx.AsyncHTTPTransport.handle_async_request


def _forbidden(request) -> bool:
    host = (request.url.host or "").lower()
    return (host in ("127.0.0.1", "localhost", "::1") and request.url.port in _READER_PORTS) or any(
        host == h or host.endswith("." + h) for h in _XHS_HOSTS)


def _guarded_handle_request(self, request):
    if _forbidden(request):
        raise RuntimeError(f"测试不许连读取服务 / 小红书：{request.url}")
    return _real_handle_request(self, request)


async def _guarded_handle_async_request(self, request):
    if _forbidden(request):  # MCP 客户端（streamablehttp）走的是异步传输
        raise RuntimeError(f"测试不许连读取服务 / 小红书：{request.url}")
    return await _real_handle_async_request(self, request)


@pytest.fixture(autouse=True)
def no_real_xhs_processes_or_hosts(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _guarded_handle_request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _guarded_handle_async_request)
    # real_web_probe 用例也只许走到「缺 relatedfile.exe」这一步
    monkeypatch.setattr(xhs, "RELATEDFILE_EXE", str(tmp_path / "no-such-relatedfile.exe"))
    # 小模型（概要）默认不真调：要测的用例自己 monkeypatch llm.call_media_text
    from link_brain import llm as llm_mod
    monkeypatch.setattr(llm_mod, "call_media_text",
                        lambda *a, **k: {"status": "failed", "text": None, "error": "测试环境不调模型"})
    # 附件 / 补查的「像人一样歇」测试里不等
    from link_brain import attachments as att_mod
    monkeypatch.setattr(att_mod, "PACE_SECONDS", (0.0, 0.0))
    monkeypatch.setattr(att_mod, "PROBE_GAP_SECONDS", (0.0, 0.0))


@pytest.fixture(autouse=True)
def isolated_vault_and_home(monkeypatch, tmp_path):
    """G-2：vault / ~/.link-brain 一律进 tmp；需要自己目录的用例再 setenv 覆盖即可。"""
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "lbhome"))
    monkeypatch.delenv("LINK_BRAIN_ALERT_CMD", raising=False)
    # 读取服务的账号目录（熔断文件 risk-hold.json 住这里）也指到 tmp，别读到本机真号的状态
    monkeypatch.setenv("XHS_PROFILE_DIR", str(tmp_path / "xhs-profile"))
    # 读取服务默认「没装、没在跑」：要测它的用例自己 monkeypatch accounts.api / httpx.request
    monkeypatch.setenv("LINK_BRAIN_XHS_EXE", str(tmp_path / "no-such-reader.exe"))
    from link_brain import accounts

    def reader_not_running(*a, **k):
        raise httpx.ConnectError("测试环境没有读取服务")
    monkeypatch.setattr(accounts.httpx, "request", reader_not_running)
    monkeypatch.delenv("LINK_BRAIN_XHS_ENDPOINT", raising=False)
    # 开页间隔 / 抓取后歇息：测试里不等
    monkeypatch.setenv("LWA_OPEN_GAP", "0,0")
    monkeypatch.setenv("LWA_FETCH_REST", "0,0")
    # 0929：同步里的识图/概要平时开子进程限时；测试里就地跑，好让 monkeypatch 生效
    monkeypatch.setenv("LINK_BRAIN_RENDER_INPROC", "1")


@pytest.fixture(autouse=True)
def no_embedding_http(request, monkeypatch):
    """本机 vault 可能已有 semantic.db + 真 key：测试一律掐断 embedding HTTP。

    掐断后语义层按设计 fail-open 退纯词法，正好等于「没配 embedding」的行为；
    要测语义命中的用例（tests/test_semantic.py）自己 monkeypatch mock provider 覆盖。
    """
    if "real_embeddings" in request.keywords:
        return
    def refuse(*args, **kwargs):
        raise RuntimeError("测试环境不联网")
    monkeypatch.setattr(semantic, "_post_embeddings", refuse)


@pytest.fixture(autouse=True)
def isolated_answer_cache(monkeypatch, tmp_path):
    """ask 成功就会往 answers.json 记一条：测试一律写进 tmp，绝不碰本机真实 vault。"""
    from link_brain import answer_cache
    path = tmp_path / "answer-cache" / "answers.json"
    monkeypatch.setattr(answer_cache, "index_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def isolated_sync_status(monkeypatch, tmp_path):
    from link_brain import sync_state
    monkeypatch.setattr(sync_state, 'path', lambda: tmp_path / 'sync-status.json')


@pytest.fixture(autouse=True)
def no_web_probe(request, monkeypatch):
    if "real_web_probe" in request.keywords:
        return  # 这些用例自己 monkeypatch httpx，测的就是探测函数本身
    monkeypatch.setattr(
        xhs,
        "fetch_related_file",
        lambda note_id, xsec_token, **kw: {
            "ok": False,
            "related_file": None,
            "url": xhs.CANONICAL_FMT.format(note_id=note_id),
            "error": "测试环境不联网",
        },
    )
    # 0929：游客探测失败后会用登录号再看一次——测试里同样不联网
    from link_brain import attachments as att_mod
    monkeypatch.setattr(att_mod, "_probe_logged_in",
                        lambda note_id, token: {"ok": False, "error": "测试环境不联网"})
