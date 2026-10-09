"""`python -m link_brain remote <子命令>`——设置页经 runPy 调这些（CONVENTIONS §1：stdout 只有最后一行 JSON，
顶层带 ok / code / message；人话进 stderr）。

    serve        起服务（计划任务调它；macOS / Linux 手动调它）
    status       状态：开关 / 计划任务 / 健康检查 / 出错原因 / 口令设了没 / 令牌 / 最近访问
    enable       注册计划任务并启动（Windows）；先要在设置里把开关打开（data.json remote.enabled=true）
    disable      停止并删除计划任务
    restart      重启（改端口后）
    passphrase   设 / 改口令：stdin 收 {"passphrase": "..."}（不走命令行参数，免得进进程列表）
                 --generate 随机生成一个并保存（回传明文，设置页拿去复制）；--reveal 取回现在的口令（DPAPI 副本）
    client revoke <id>  吊销一个已连接的 OAuth 客户端
    probe        测公网：GET https://<域名>/.well-known/oauth-authorization-server，看 issuer 对不对
    token new [--label 名字] / token revoke <id>
    revoke-all   撤销全部访问（OAuth 客户端 + 全部令牌；口令保留）
    folders      「添加文件夹」的候选（vault 里现有的、可以开放的文件夹）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def add_parser(sub) -> None:
    p = sub.add_parser("remote", help="远程 MCP（LWA MCP over HTTP，自备域名）：起服务 / 状态 / 口令 / 令牌")
    rs = p.add_subparsers(dest="remote_command")
    ps = rs.add_parser("serve", help="起服务（只监听 127.0.0.1；端口、域名、文件夹读插件 data.json 的 remote 段）")
    for q in (ps,):
        q.add_argument("--vault", default=None, help="vault 路径（默认同其他命令）")
        q.add_argument("--state-dir", default=None, help="口令 / 令牌 / 日志目录（默认 ~/.link-brain/remote）")
        q.add_argument("--settings", default=None, help="另指一份 data.json（开发 / 验收用）")
    for name, desc in (("status", "看状态"), ("enable", "注册计划任务并启动（Windows）"), ("disable", "停止并删除计划任务"),
                       ("restart", "重启服务")):
        q = rs.add_parser(name, help=desc)
        q.add_argument("--settings", default=None, help="另指一份 data.json（开发 / 验收用）")
        q.add_argument("--state-dir", default=None, help="口令 / 令牌 / 日志目录（默认 ~/.link-brain/remote）")
    pp = rs.add_parser("passphrase", help='设 / 改口令：stdin 收 {"passphrase": "..."}')
    g = pp.add_mutually_exclusive_group()
    g.add_argument("--generate", action="store_true", help="随机生成一个并保存，回传明文")
    g.add_argument("--reveal", action="store_true", help="取回现在的口令（Windows DPAPI 副本）")
    pc = rs.add_parser("client", help="已连接的 OAuth 客户端")
    pcs = pc.add_subparsers(dest="client_command")
    pcr = pcs.add_parser("revoke", help="吊销一个")
    pcr.add_argument("id")
    for q in (pp, rs.add_parser("revoke-all", help="撤销全部访问（OAuth 客户端和所有令牌；口令保留）"), pcr):
        q.add_argument("--state-dir", default=None, help="口令 / 令牌目录（默认 ~/.link-brain/remote）")
    pr = rs.add_parser("probe", help="测公网：请求 https://<域名>/.well-known/oauth-authorization-server")
    pr.add_argument("--settings", default=None, help="另指一份 data.json（开发 / 验收用）")
    pt = rs.add_parser("token", help="给其他客户端的访问令牌")
    ts = pt.add_subparsers(dest="token_command")
    tn = ts.add_parser("new", help="生成一个（明文只显示这一次）")
    tn.add_argument("--label", default="", help="备注，比如「Claude 桌面」")
    tr = ts.add_parser("revoke", help="撤销一个")
    tr.add_argument("id")
    for q in (tn, tr):
        q.add_argument("--state-dir", default=None, help="口令 / 令牌目录（默认 ~/.link-brain/remote）")
    pf = rs.add_parser("folders", help="列出可以开放的文件夹（设置页勾选列表用：库内一二级 + 已配置的库外文件夹）")
    pf.add_argument("--settings", default=None, help="另指一份 data.json（开发 / 验收用）")
    pf.add_argument("--check", default=None, help="只检查这一个本机路径能不能开放")


def _out(payload: dict[str, Any]) -> int:
    from ..read import dump_json
    payload.setdefault("code", "")
    payload.setdefault("message", "")
    dump_json(payload)
    if not payload.get("ok"):
        print(payload.get("message") or "失败", file=sys.stderr)
        return 1
    return 0


def _vault() -> str:
    from .. import storage
    return str(storage.vault_root())


def _store(state_dir=None):
    from .store import AuthStore
    return AuthStore(state_dir)


def status(settings_path=None, state_dir=None) -> dict[str, Any]:
    from . import config as cfg_mod, task, store as store_mod
    from .server import probe_health
    sdir = Path(state_dir) if state_dir else store_mod.state_dir()
    cfg, problems = cfg_mod.load(settings_path)
    health = probe_health(cfg["port"], timeout=1.0)
    srv = store_mod.read_status(sdir)
    tstate = task.state() if cfg["enabled"] or task.supported() else {}
    auth = _store(sdir).summary()
    if health and health.get("enabled") is not False:
        state, message = "running", f"运行中（127.0.0.1:{cfg['port']}）"
    elif not cfg["enabled"]:
        state, message = "stopped", "已停"
        if tstate.get("registered"):
            message = "已停（但计划任务还在：点一次「停用」清掉）"
    else:
        state = "error"
        if srv.get("state") == "error" and srv.get("message"):
            message = srv["message"]
        elif tstate.get("supported") and tstate.get("registered") is False:
            message = "开关开着，但计划任务没注册：点「启用」"
        elif srv.get("state") == "stopped" and srv.get("message"):
            message = f"没在运行：{srv['message']}"
        else:
            message = "没在运行（计划任务每 5 分钟会再拉起一次）"
    warnings: list[str] = list(problems)
    if cfg["enabled"] and not auth["passphrase_set"]:
        warnings.append("还没设口令：GPT 网页版这类走 OAuth 的客户端连不上（访问令牌照常能用）")
    if cfg["enabled"] and not cfg["domain"]:
        warnings.append("没填域名：现在只有本机能连（填了域名并接好隧道，claude.ai / ChatGPT 才连得上）")
    if auth["corrupt"]:
        warnings.append("口令 / 令牌文件损坏：所有令牌都不认了。点「撤销全部访问」重建，再重设口令")
    return {"ok": True, "code": "", "message": message, "state": state, "enabled": cfg["enabled"],
            "domain": cfg["domain"], "port": cfg["port"], "folders": cfg["folders"],
            "url": (cfg["domain"] + "/mcp") if cfg["domain"] else f"http://127.0.0.1:{cfg['port']}/mcp",
            "health": health, "task": tstate, "service": srv, "auth": auth, "warnings": warnings,
            "settings_path": str(cfg_mod.settings_path(settings_path)), "stdio": stdio_config(),
            "recent": store_mod.recent_access(20, sdir)}


def stdio_config() -> dict[str, Any]:
    """本机 Claude Code / Claude 桌面走 stdio 的配置片段（不经网络、不要口令）。"""
    from .. import storage
    repo = str(storage.repo_root())
    exe = sys.executable
    entry = {"command": exe, "args": ["-m", "link_brain", "mcp"], "env": {"PYTHONPATH": repo, "PYTHONUTF8": "1"}}
    q = (lambda a: '"' + a + '"' if " " in a else a)
    return {"json": json.dumps({"mcpServers": {"lwa": entry}}, ensure_ascii=False, indent=2),
            "claude_code": f"claude mcp add --scope user lwa -e PYTHONPATH={q(repo)} -e PYTHONUTF8=1 -- {q(exe)} -m link_brain mcp"}


def probe(settings_path=None, timeout: float = 10.0) -> dict[str, Any]:
    """从公网那一侧绕回来测一次：域名 → 隧道 → 本机服务。只读一个公开的元数据地址，不带任何凭据。"""
    from . import config as cfg_mod
    cfg, _ = cfg_mod.load(settings_path)
    if not cfg["domain"]:
        return {"ok": False, "code": "NO_DOMAIN", "message": "还没填域名"}
    url = cfg["domain"] + "/.well-known/oauth-authorization-server"
    import time as _t
    import httpx
    t0 = _t.monotonic()
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=False)
    except httpx.HTTPError as exc:
        return {"ok": False, "code": "NETWORK", "url": url, "message": f"公网不通：{type(exc).__name__}（域名解析 / 隧道没起来？）"}
    ms = int((_t.monotonic() - t0) * 1000)
    try:
        issuer = r.json().get("issuer") if r.status_code == 200 else None
    except ValueError:
        issuer = None
    if r.status_code == 200 and issuer == cfg["domain"]:
        return {"ok": True, "url": url, "ms": ms, "message": f"公网通了（{ms} ms）：域名 → 隧道 → 本机服务一路正常"}
    if r.status_code == 200:
        return {"ok": False, "code": "WRONG_ISSUER", "url": url, "message": f"能连上，但回的不是这个服务（issuer={issuer!r}）：隧道是不是指错了端口？"}
    hint = {502: "隧道通了但本机服务没在跑（或端口不对）", 503: "服务在，但设置里关着", 530: "Cloudflare 找不到隧道（cloudflared 没在跑？）",
            403: "被拒：域名没登记进设置，或被防火墙 / WAF 拦了", 404: "隧道指向了别的服务"}.get(r.status_code, "")
    return {"ok": False, "code": f"HTTP_{r.status_code}", "url": url, "message": f"公网返回 {r.status_code}" + (f"：{hint}" if hint else "")}


def folders_payload(settings_path=None, check: str | None = None) -> dict[str, Any]:
    from . import config as cfg_mod
    from .policy import Denied, candidate_folders, check_external, check_folder, is_external
    vault = _vault()
    if check is not None:
        try:
            if is_external(check):
                real = check_external(vault, check)
                return {"ok": True, "path": real, "external": True, "message": "可以开放"}
            return {"ok": True, "path": check_folder(vault, check.replace("\\", "/").strip("/")), "external": False, "message": "可以开放"}
        except Denied as exc:
            return {"ok": False, "code": exc.code, "message": exc.message}
    cfg, _ = cfg_mod.load(settings_path)
    externals = []
    for f in cfg["folders"]:
        if is_external(f):
            try:
                check_external(vault, f)
                externals.append({"path": f, "ok": True, "message": ""})
            except Denied as exc:
                externals.append({"path": f, "ok": False, "message": exc.message})
    return {"ok": True, "vault": vault, "folders": candidate_folders(vault, max_depth=2), "externals": externals}


def run(args) -> int:
    cmd = getattr(args, "remote_command", None)
    settings_path = getattr(args, "settings", None)
    state_dir = getattr(args, "state_dir", None)
    if cmd == "serve":
        from .server import serve
        return serve(args.vault or _vault(), settings_path, state_dir)
    if cmd == "status" or cmd is None:
        return _out(status(settings_path, state_dir))
    if cmd == "enable":
        from . import config as cfg_mod, task, store as store_mod
        cfg, _ = cfg_mod.load(settings_path)
        if not cfg["enabled"]:
            return _out({"ok": False, "code": "SKIPPED.DISABLED", "message": "设置里的开关还是关着的"})
        sdir = str(Path(state_dir) if state_dir else store_mod.state_dir())
        settings_arg = str(cfg_mod.settings_path(settings_path)) if (settings_path or os.environ.get(cfg_mod.ENV_SETTINGS)) else None
        return _out(task.register(_vault(), sdir, settings_arg))
    if cmd == "disable":
        from . import task
        from .server import probe_health
        from . import config as cfg_mod
        res = task.unregister()
        if res.get("ok"):
            cfg, _ = cfg_mod.load(settings_path)
            # 计划任务停掉后服务应该已经没了；还在应答（比如手动起的）就如实说
            if probe_health(cfg["port"], timeout=1.0):
                res["message"] += "；但端口上还有一个远程阅读服务在应答（可能是手动启动的），它看到开关关了会在几秒内自己退出"
        return _out(res)
    if cmd == "restart":
        from . import task
        return _out(task.restart())
    if cmd == "passphrase":
        st = _store(state_dir)
        if getattr(args, "reveal", False):
            value = st.reveal_passphrase()
            if value is None:
                why = ("还没设口令" if not st.passphrase_set() else
                       "取不回来：这个口令是在加密副本功能之前设的（或不是 Windows）。点「随机生成」或「修改口令」重设一次，以后就能复制了")
                return _out({"ok": False, "code": "NO_COPY", "message": why})
            return _out({"ok": True, "passphrase": value, "message": "已取回口令"})
        try:
            if getattr(args, "generate", False):
                value = st.generate_passphrase()
            else:
                value = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}").get("passphrase")
            st.set_passphrase(value)
        except ValueError as exc:
            return _out({"ok": False, "code": "", "message": str(exc)})
        out = {"ok": True, "message": "口令已保存（已连上的客户端不受影响；要让它们重新授权，到「已连接的客户端」里吊销）"}
        if getattr(args, "generate", False):
            out["passphrase"] = value
        return _out(out)
    if cmd == "client":
        if getattr(args, "client_command", None) != "revoke":
            return _out({"ok": False, "message": "要 client revoke <id>"})
        ok = _store(state_dir).revoke_client(args.id)
        return _out({"ok": ok, "message": "已吊销这个客户端（它要重新授权才能再连）" if ok else "没有这个客户端（可能已经吊销了）"})
    if cmd == "probe":
        return _out(probe(settings_path))
    if cmd == "token":
        st = _store(state_dir)
        if args.token_command == "new":
            try:
                t = st.new_personal(args.label)
            except ValueError as exc:
                return _out({"ok": False, "message": str(exc)})
            return _out({"ok": True, "message": "已生成（只显示这一次，请现在复制）", **t})
        if args.token_command == "revoke":
            ok = st.revoke_personal(args.id)
            return _out({"ok": ok, "message": "已撤销" if ok else "没有这个令牌（可能已经撤销了）"})
        return _out({"ok": False, "message": "要 token new 或 token revoke <id>"})
    if cmd == "revoke-all":
        counts = _store(state_dir).revoke_all()
        return _out({"ok": True, "message": f"已撤销全部访问：{counts['clients']} 个 OAuth 客户端、{counts['personal']} 个访问令牌",
                     **counts})
    if cmd == "folders":
        return _out(folders_payload(settings_path, getattr(args, "check", None)))
    return _out({"ok": False, "message": f"未知子命令：{cmd}"})
