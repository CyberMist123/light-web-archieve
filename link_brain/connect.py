"""连接 AI（1009 她：连几个 MCP 要看好几个地方 → 一个模块，选了哪个客户端就给那个客户端一步）。

本机客户端一键写配置（写前备份、写完报结果、可撤销）：
- Claude Code：`claude mcp add lwa -s user -e … -- <python> -m link_brain mcp`；撤销 = `claude mcp remove lwa -s user`。
  写之前把它的配置文件（`$CLAUDE_CONFIG_DIR/.claude.json`，没设就是家目录下那份）复制一份到 `~/.link-brain/connect-backups/`。
  她的 Claude Code 配置里别的东西一律不碰（不整份回滚——那份文件 Claude Code 自己一直在写）。
- Claude Desktop：改 `claude_desktop_config.json` 的 `mcpServers.lwa`（Windows `%APPDATA%\\Claude`，macOS
  `~/Library/Application Support/Claude`，`LWA_CLAUDE_DESKTOP_CONFIG` 可指到别处——测试一律指到临时目录）；
  写前备份整份文件；撤销 = 只删 `lwa` 这一项。
网页端（claude.ai / ChatGPT）走远程 MCP（`remote` 子命令），这里只给状态。

CLI（CONVENTIONS §1 形状）：
  python -m link_brain connect status                       每个本机客户端：找没找到、接没接上（只读文件，不改东西）
  python -m link_brain connect add <claude-code|claude-desktop>
  python -m link_brain connect remove <claude-code|claude-desktop>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage

NAME = "lwa"
CLIENTS = ("claude-code", "claude-desktop")
CLIENT_CN = {"claude-code": "Claude Code", "claude-desktop": "Claude Desktop"}
ENV_DESKTOP = "LWA_CLAUDE_DESKTOP_CONFIG"
ENV_CLAUDE_EXE = "LWA_CLAUDE_EXE"


# --------------------------------------------------------------------------
# 本机 MCP 服务的启动命令（和插件「测试 MCP」同一条）
# --------------------------------------------------------------------------


def server_spec() -> dict[str, Any]:
    """{command, args, env}：用现在这个 Python 起 `-m link_brain mcp`；PYTHONPATH 指到程序目录（从任何目录起都找得到），
    LINK_BRAIN_VAULT 钉成现在这个收藏库。"""
    root = str(Path(__file__).resolve().parent.parent)
    env = {"LINK_BRAIN_VAULT": str(storage.vault_root()), "PYTHONIOENCODING": "utf-8", "PYTHONPATH": root}
    return {"command": sys.executable, "args": ["-m", "link_brain", "mcp"], "env": env}


def backups_dir() -> Path:
    return storage.link_brain_home() / "connect-backups"


def _backup(path: Path, tag: str) -> str | None:
    if not path.is_file():
        return None
    dest = backups_dir() / f"{tag}-{datetime.now():%Y%m%d-%H%M%S}{path.suffix or '.json'}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return str(dest)


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------


def claude_code_config() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(base) / ".claude.json" if base else Path.home() / ".claude.json"


def claude_exe() -> str | None:
    forced = os.environ.get(ENV_CLAUDE_EXE)
    if forced:
        return forced if Path(forced).exists() else None
    found = shutil.which("claude")
    if found:
        return found
    for cand in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if cand.exists():
            return str(cand)
    return None


class BadConfig(ValueError):
    """配置文件在、但不是合法的 JSON 对象：不敢改。"""


def _read_json(path: Path, *, strict: bool = False) -> dict[str, Any] | None:
    """没有文件 → None；读不了 / 不是 JSON 对象 → strict 时抛 BadConfig，否则当空的。"""
    try:
        text = path.read_text("utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        if strict:
            raise BadConfig(f"读不了 {path}：{exc}") from exc
        return {}
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        if strict:
            raise BadConfig(f"{path} 不是合法 JSON") from exc
        return {}
    if not isinstance(data, dict):
        if strict:
            raise BadConfig(f"{path} 不是 JSON 对象")
        return {}
    return data


def _claude_code_has() -> dict[str, Any] | None:
    data = _read_json(claude_code_config()) or {}
    servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
    return servers.get(NAME) if isinstance(servers.get(NAME), dict) else None


def _run_claude(args: list[str], timeout: float = 90) -> tuple[int, str]:
    exe = claude_exe()
    if not exe:
        return 127, "没找到 claude 命令（Claude Code 没装，或不在 PATH 里）"
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return 124, f"claude {' '.join(args[:2])} 超过 {timeout:.0f} 秒没回来"
    except OSError as exc:
        return 126, f"claude 起不来：{exc}"
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    return p.returncode, out


def _cc_command_text(spec: dict[str, Any]) -> str:
    def q(s: str) -> str:
        return f'"{s}"' if any(ch.isspace() for ch in s) else s
    envs = " ".join(f"-e {k}={q(v)}" for k, v in spec["env"].items())
    return f"claude mcp add {NAME} -s user {envs} -- {q(spec['command'])} " + " ".join(spec["args"])


def add_claude_code() -> dict[str, Any]:
    spec = server_spec()
    cmd_text = _cc_command_text(spec)
    if _claude_code_has():
        return {"ok": True, "client": "claude-code", "changed": False, "message": "Claude Code 已经接上了（用户级配置里有 lwa）",
                "command": cmd_text}
    if not claude_exe():
        return {"ok": False, "client": "claude-code", "changed": False, "code": "", "manual": True, "command": cmd_text,
                "message": "没找到 claude 命令：装好 Claude Code 后再点，或把下面这条命令复制到终端运行"}
    backup = _backup(claude_code_config(), "claude-code")
    args = ["mcp", "add", NAME, "-s", "user"]
    for k, v in spec["env"].items():
        args += ["-e", f"{k}={v}"]
    args += ["--", spec["command"], *spec["args"]]
    rc, out = _run_claude(args)
    if rc != 0 or not _claude_code_has():
        return {"ok": False, "client": "claude-code", "changed": False, "code": "", "backup": backup, "command": cmd_text,
                "message": f"没接上：{(out.splitlines() or ['claude 没说原因'])[-1][:200]}"}
    return {"ok": True, "client": "claude-code", "changed": True, "backup": backup, "command": cmd_text,
            "config": str(claude_code_config()),
            "message": "已接到 Claude Code（用户级，所有项目都能用）：重开 Claude Code 后工具名以 lwa 开头"}


def remove_claude_code() -> dict[str, Any]:
    if not _claude_code_has():
        return {"ok": True, "client": "claude-code", "changed": False, "message": "Claude Code 里本来就没有 lwa"}
    backup = _backup(claude_code_config(), "claude-code")
    rc, out = _run_claude(["mcp", "remove", NAME, "-s", "user"])
    if rc != 0 or _claude_code_has():
        return {"ok": False, "client": "claude-code", "changed": False, "code": "", "backup": backup,
                "message": f"没撤掉：{(out.splitlines() or ['claude 没说原因'])[-1][:200]}"}
    return {"ok": True, "client": "claude-code", "changed": True, "backup": backup, "message": "已从 Claude Code 撤掉 lwa"}


# --------------------------------------------------------------------------
# Claude Desktop
# --------------------------------------------------------------------------


def claude_desktop_config() -> Path:
    forced = os.environ.get(ENV_DESKTOP)
    if forced:
        return Path(forced)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _desktop_installed(path: Path) -> bool:
    return path.parent.is_dir()


def add_claude_desktop() -> dict[str, Any]:
    path = claude_desktop_config()
    if not _desktop_installed(path):
        return {"ok": False, "client": "claude-desktop", "changed": False, "code": "", "manual": True,
                "message": "没找到 Claude Desktop 的配置目录：装好并打开过一次 Claude Desktop 再点"}
    try:
        data = _read_json(path, strict=True) or {}
    except BadConfig as exc:
        return {"ok": False, "client": "claude-desktop", "changed": False, "code": "",
                "message": f"Claude Desktop 的配置文件读不懂，没敢改（{exc}）"}
    servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
    spec = server_spec()
    if servers.get(NAME) == spec:
        return {"ok": True, "client": "claude-desktop", "changed": False, "message": "Claude Desktop 已经接上了"}
    backup = _backup(path, "claude-desktop")
    servers[NAME] = spec
    data["mcpServers"] = servers
    storage.atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "client": "claude-desktop", "changed": True, "backup": backup, "config": str(path),
            "message": "已写进 Claude Desktop 的配置：完全退出 Claude Desktop（托盘里也退）再打开就能用"}


def remove_claude_desktop() -> dict[str, Any]:
    path = claude_desktop_config()
    try:
        data = _read_json(path, strict=True) or {}
    except BadConfig as exc:
        return {"ok": False, "client": "claude-desktop", "changed": False, "code": "",
                "message": f"Claude Desktop 的配置文件读不懂，没敢改（{exc}）"}
    servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
    if NAME not in servers:
        return {"ok": True, "client": "claude-desktop", "changed": False, "message": "Claude Desktop 里本来就没有 lwa"}
    backup = _backup(path, "claude-desktop")
    servers.pop(NAME, None)
    data["mcpServers"] = servers
    storage.atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "client": "claude-desktop", "changed": True, "backup": backup,
            "message": "已从 Claude Desktop 撤掉 lwa（重开 Claude Desktop 生效）"}


# --------------------------------------------------------------------------
# 状态 / CLI
# --------------------------------------------------------------------------


def status() -> dict[str, Any]:
    cc = claude_code_config()
    desk = claude_desktop_config()
    clients = {
        "claude-code": {"name": CLIENT_CN["claude-code"], "installed": bool(claude_exe()), "connected": bool(_claude_code_has()),
                        "command": _cc_command_text(server_spec())},
        "claude-desktop": {"name": CLIENT_CN["claude-desktop"], "installed": _desktop_installed(desk),
                           "connected": NAME in (((_read_json(desk) or {}).get("mcpServers")) or {})},
    }
    spec = server_spec()
    return {"ok": True, "code": "", "message": "", "name": NAME, "clients": clients, "server": spec,
            "json": json.dumps({"mcpServers": {NAME: spec}}, ensure_ascii=False, indent=2),
            "config_paths": {"claude-code": str(cc), "claude-desktop": str(desk)}}


def add_parser(sub) -> None:
    p = sub.add_parser("connect", help="连接 AI：把收藏库接给本机的 Claude Code / Claude Desktop（写前备份、可撤销）")
    csub = p.add_subparsers(dest="connect_command", metavar="<status|add|remove>")
    csub.add_parser("status", help="各本机客户端接没接上（只读）")
    for name in ("add", "remove"):
        q = csub.add_parser(name, help="接上" if name == "add" else "撤掉")
        q.add_argument("client", choices=CLIENTS)


def run(args) -> int:
    from .read import dump_json, outcome
    cmd = getattr(args, "connect_command", None)
    if cmd == "status" or not cmd:
        dump_json(status())
        return 0
    fn = {("add", "claude-code"): add_claude_code, ("remove", "claude-code"): remove_claude_code,
          ("add", "claude-desktop"): add_claude_desktop, ("remove", "claude-desktop"): remove_claude_desktop}[(cmd, args.client)]
    try:
        out = fn()
    except OSError as exc:
        out = {"ok": False, "client": args.client, "changed": False, "code": "", "message": f"没写上：{exc}"}
    if not out.get("ok"):
        print(out.get("message"), file=sys.stderr)
    dump_json(outcome(out, ok=bool(out.get("ok")), message=out.get("message") or "", code=out.get("code") or ""))
    return 0 if out.get("ok") else 1
