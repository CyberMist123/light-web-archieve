"""`python -m link_brain remote <子命令>`——设置页经 runPy 调这些（CONVENTIONS §1：stdout 只有最后一行 JSON，
顶层带 ok / code / message；人话进 stderr）。

    serve        起服务（计划任务调它；macOS / Linux 手动调它）
    status       状态：开关 / 计划任务 / 健康检查 / 出错原因 / 口令设了没 / 令牌 / 最近访问
    enable       注册计划任务并启动（Windows）；先要在设置里把开关打开（data.json remote.enabled=true）
    disable      停止并删除计划任务
    restart      重启（改端口后）
    passphrase   设 / 改口令：stdin 收 {"passphrase": "..."}（不走命令行参数，免得进进程列表）
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
    p = sub.add_parser("remote", help="远程阅读（只读 MCP over HTTP，自备域名）：起服务 / 状态 / 口令 / 令牌")
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
    for q in (rs.add_parser("passphrase", help='设 / 改口令：stdin 收 {"passphrase": "..."}'),
              rs.add_parser("revoke-all", help="撤销全部访问（OAuth 客户端和所有令牌；口令保留）")):
        q.add_argument("--state-dir", default=None, help="口令 / 令牌目录（默认 ~/.link-brain/remote）")
    pt = rs.add_parser("token", help="给其他客户端的访问令牌")
    ts = pt.add_subparsers(dest="token_command")
    tn = ts.add_parser("new", help="生成一个（明文只显示这一次）")
    tn.add_argument("--label", default="", help="备注，比如「Claude 桌面」")
    tr = ts.add_parser("revoke", help="撤销一个")
    tr.add_argument("id")
    for q in (tn, tr):
        q.add_argument("--state-dir", default=None, help="口令 / 令牌目录（默认 ~/.link-brain/remote）")
    rs.add_parser("folders", help="列出可以开放的文件夹（设置页「添加文件夹」用）")


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
        warnings.append("没填域名：现在只有本机能连")
    if auth["corrupt"]:
        warnings.append("口令 / 令牌文件损坏：所有令牌都不认了。点「撤销全部访问」重建，再重设口令")
    return {"ok": True, "code": "", "message": message, "state": state, "enabled": cfg["enabled"],
            "domain": cfg["domain"], "port": cfg["port"], "folders": cfg["folders"],
            "url": (cfg["domain"] + "/mcp") if cfg["domain"] else f"http://127.0.0.1:{cfg['port']}/mcp",
            "health": health, "task": tstate, "service": srv, "auth": auth, "warnings": warnings,
            "recent": store_mod.recent_access(20, sdir)}


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
        try:
            data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
            _store(state_dir).set_passphrase(data.get("passphrase"))
        except ValueError as exc:
            return _out({"ok": False, "code": "", "message": str(exc)})
        return _out({"ok": True, "message": "口令已保存（已连上的客户端不受影响；要让它们重新授权，点「撤销全部访问」）"})
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
        from .policy import candidate_folders
        return _out({"ok": True, "folders": candidate_folders(_vault())})
    return _out({"ok": False, "message": f"未知子命令：{cmd}"})
