"""连接 AI（1009 作者：连几个 MCP 要看好几个地方 → 一个模块，选了哪个客户端就给那个客户端一步）。

本机客户端一键写配置（写前备份、写完报结果、可撤销）：
- Claude Code：`claude mcp add lwa -s user -e … -- <python> -m link_brain mcp`；撤销 = `claude mcp remove lwa -s user`。
  写之前把它的配置文件（`$CLAUDE_CONFIG_DIR/.claude.json`，没设就是家目录下那份）复制一份到 `~/.link-brain/connect-backups/`。
  用户的 Claude Code 配置里别的东西一律不碰（不整份回滚——那份文件 Claude Code 自己一直在写）。
- Claude Desktop：改 `claude_desktop_config.json` 的 `mcpServers.lwa`（Windows `%APPDATA%\\Claude`，macOS
  `~/Library/Application Support/Claude`，`LWA_CLAUDE_DESKTOP_CONFIG` 可指到别处——测试一律指到临时目录）；
  写前备份整份文件；撤销 = 只删 `lwa` 这一项。
网页端（claude.ai / ChatGPT）走远程 MCP（`remote` 子命令），这里只给状态。

CLI（CONVENTIONS §1 形状）：
  python -m link_brain connect status                       每个本机客户端：找没找到、接没接上（只读文件，不改东西）
  python -m link_brain connect add <CLIENTS 里的一个>
  python -m link_brain connect remove <CLIENTS 里的一个>
- Codex：`codex mcp add lwa --env … -- <python> -m link_brain mcp`（配置由 codex 自己写进 ~/.codex/config.toml）；撤销 = `codex mcp remove lwa`。
- Cursor / Gemini CLI / Qwen Code / Kimi Code / Pi / ZCode / Cline / Roo Code：改各自的 JSON 配置文件里 lwa 那一项（FILE_CLIENTS，同 Claude Desktop 的做法）。
- status 另给 apps（本机认出来的，照 Claudian 的找法 + 各家配置目录）和 others（没认出来的），每个带 snippet（它自己格式的设置）和 hint（粘到哪）。
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
CLIENTS = ("claude-code", "claude-desktop", "codex", "cursor", "gemini", "qwen", "kimi", "pi", "zcode", "cline", "roo")
CLIENT_CN = {"claude-code": "Claude Code", "claude-desktop": "Claude Desktop", "codex": "Codex"}
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
    return find_binary("claude")


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
# Codex：`codex mcp add / remove / get`（配置在 ~/.codex/config.toml，由 codex 自己写；我们不碰那份文件）
# --------------------------------------------------------------------------


def codex_exe() -> str | None:
    return find_binary("codex")


def _run_codex(args: list[str], timeout: float = 60) -> tuple[int, str]:
    exe = codex_exe()
    if not exe:
        return 127, "没找到 codex 命令（Codex 没装，或不在常见安装位置）"
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return 124, f"codex {' '.join(args[:2])} 超过 {timeout:.0f} 秒没回来"
    except OSError as exc:
        return 126, f"codex 起不来：{exc}"
    return p.returncode, ((p.stdout or "") + "\n" + (p.stderr or "")).strip()


def _codex_has() -> bool:
    if not codex_exe():
        return False
    rc, _ = _run_codex(["mcp", "get", NAME, "--json"], timeout=20)
    return rc == 0


def _codex_command_text(spec: dict[str, Any]) -> str:
    def q(s: str) -> str:
        return f'"{s}"' if any(ch.isspace() for ch in s) else s
    envs = " ".join(f"--env {k}={q(v)}" for k, v in spec["env"].items())
    return f"codex mcp add {NAME} {envs} -- {q(spec['command'])} " + " ".join(spec["args"])


def add_codex() -> dict[str, Any]:
    spec = server_spec()
    cmd_text = _codex_command_text(spec)
    if not codex_exe():
        return {"ok": False, "client": "codex", "changed": False, "code": "", "manual": True, "command": cmd_text,
                "message": "没找到 codex 命令：装好 Codex 后再点，或把下面这条命令复制到终端运行"}
    if _codex_has():
        return {"ok": True, "client": "codex", "changed": False, "message": "Codex 已经接上了", "command": cmd_text}
    args = ["mcp", "add", NAME]
    for k, v in spec["env"].items():
        args += ["--env", f"{k}={v}"]
    args += ["--", spec["command"], *spec["args"]]
    rc, out = _run_codex(args)
    if rc != 0 or not _codex_has():
        return {"ok": False, "client": "codex", "changed": False, "code": "", "command": cmd_text,
                "message": f"没接上：{(out.splitlines() or ['codex 没说原因'])[-1][:200]}"}
    return {"ok": True, "client": "codex", "changed": True, "command": cmd_text,
            "message": "已接到 Codex：新开一个 Codex 会话后工具名以 lwa 开头"}


def remove_codex() -> dict[str, Any]:
    if not _codex_has():
        return {"ok": True, "client": "codex", "changed": False, "message": "Codex 里本来就没有 lwa"}
    rc, out = _run_codex(["mcp", "remove", NAME])
    if rc != 0 or _codex_has():
        return {"ok": False, "client": "codex", "changed": False, "code": "",
                "message": f"没撤掉：{(out.splitlines() or ['codex 没说原因'])[-1][:200]}"}
    return {"ok": True, "client": "codex", "changed": True, "message": "已从 Codex 撤掉 lwa"}


# --------------------------------------------------------------------------
# 本机装了哪些 AI 应用（1018 作者：照 Claudian 认本机 CLI——它支持 Claude Code / Codex / OpenCode / Pi / Grok Build /
# DeepSeek Harness，按 PATH + 各家常见安装目录找）。只看「装没装、什么版本」，不读它们的对话、不改别的东西。
# 1101 作者：「市面上的 harness 都放上来」——每家照官方文档：用户级配置是 JSON、路径写死在文档里的做一键开关（只改 lwa
# 那一项，写前备份、撤销只删 lwa）；TOML / YAML 或文档没写死路径的给「复制设置」（复制它自己那种格式的片段）。
#   Cursor        ~/.cursor/mcp.json                       mcpServers   cursor.com/docs/context/mcp
#   Gemini CLI    ~/.gemini/settings.json                  mcpServers   gemini-cli docs/tools/mcp-server.md（可带注释 → 读不懂就不改）
#   Qwen Code     ~/.qwen/settings.json                    mcpServers   qwenlm.github.io/qwen-code-docs …/features/mcp
#   Kimi Code     ~/.kimi-code/mcp.json（旧版 ~/.kimi）    mcpServers   kimi.com/code/docs …/customization/mcp.html
#   Pi            ~/.pi/agent/mcp.json                     mcpServers   earendil-works/pi packages/coding-agent/docs/mcp.md
#   ZCode         ~/.zcode/cli/config.json                 mcp.servers  zcode.z.ai/en/docs/mcp-services
#   Cline / Roo   VS Code globalStorage/<扩展>/settings/…  mcpServers   cline core/storage/disk.ts；Roo src/shared/globalFileNames.ts
#   复制设置：OpenCode（mcp 段，type local）· Grok Build（~/.grok/config.toml）· Hermes Agent（~/.hermes/config.yaml mcp_servers）·
#   DeepSeek Harness（~/.dsh/cordis.patch.yml，YAML 补丁）· Windsurf（文档已迁到 Devin Desktop，路径不定）·
#   Trae（全局 mcp.json 的位置文档没写，只有界面里的 Raw Config）· Cherry Studio（存在它自己的数据库里，界面能从 JSON 导入）。
# --------------------------------------------------------------------------

# id, 显示名, 命令名, 一键接入（True）还是只能复制设置（False）；顺序 = 设置页顺序
APPS = (
    ("claude-code", "Claude Code", "claude", True),
    ("claude-desktop", "Claude 桌面版", "", True),
    ("codex", "Codex", "codex", True),
    ("cursor", "Cursor", "", True),
    ("gemini", "Gemini CLI", "gemini", True),
    ("qwen", "Qwen Code", "qwen", True),
    ("kimi", "Kimi Code", "kimi", True),
    ("pi", "Pi", "pi", True),
    ("zcode", "ZCode", "", True),
    ("cline", "Cline", "", True),
    ("roo", "Roo Code", "", True),
    ("opencode", "OpenCode", "opencode", False),
    ("grok", "Grok Build", "grok", False),
    ("hermes", "Hermes Agent", "hermes", False),
    ("deepseek", "DeepSeek Harness", "dsh", False),
    ("windsurf", "Windsurf", "windsurf", False),
    ("trae", "Trae", "", False),
    ("cherry", "Cherry Studio", "", False),
)
APP_NAME = {aid: name for aid, name, _, _ in APPS}


def _home() -> Path:
    return Path.home()


def _vscode_storages() -> list[Path]:
    """VS Code 系编辑器的 globalStorage（Cline / Roo 的设置在 <这里>/<扩展 id>/settings/ 下）。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (_home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = _home() / "Library" / "Application Support"
    else:
        base = _home() / ".config"
    return [base / ed / "User" / "globalStorage" for ed in ("Code", "Code - Insiders", "VSCodium")]


def _ext_settings(*folders: str) -> Path | None:
    """第一个装了这个扩展（它的 settings 目录在）的编辑器里的 settings 目录；扩展目录名大小写两种都认。"""
    for store in _vscode_storages():
        for folder in folders:
            d = store / folder / "settings"
            if d.is_dir():
                return d
    return None


def _kimi_dir() -> Path:
    forced = os.environ.get("KIMI_CODE_HOME")
    if forced:
        return Path(forced)
    new, old = _home() / ".kimi-code", _home() / ".kimi"
    return old if (old.is_dir() and not new.is_dir()) else new


def _pi_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or (_home() / ".pi" / "agent"))


def _cline_file() -> Path | None:
    d = _ext_settings("saoudrizwan.claude-dev")
    return d / "cline_mcp_settings.json" if d else None


def _roo_file() -> Path | None:
    d = _ext_settings("rooveterinaryinc.roo-cline", "RooVeterinaryInc.roo-cline")
    return d / "mcp_settings.json" if d else None


def _parent(fn):
    def go() -> Path | None:
        p = fn()
        return p.parent if p else None
    return go


# 一键写 JSON 文件的这几家：id → (配置文件（None = 没装）, 认「装了」的目录, servers 在哪个键下)
FILE_CLIENTS: dict[str, tuple[Any, Any, tuple[str, ...]]] = {
    "cursor": (lambda: _home() / ".cursor" / "mcp.json", lambda: _home() / ".cursor", ("mcpServers",)),
    "gemini": (lambda: _home() / ".gemini" / "settings.json", lambda: _home() / ".gemini", ("mcpServers",)),
    "qwen": (lambda: _home() / ".qwen" / "settings.json", lambda: _home() / ".qwen", ("mcpServers",)),
    "kimi": (lambda: _kimi_dir() / "mcp.json", _kimi_dir, ("mcpServers",)),
    "pi": (lambda: _pi_dir() / "mcp.json", _pi_dir, ("mcpServers",)),
    "zcode": (lambda: _home() / ".zcode" / "cli" / "config.json", lambda: _home() / ".zcode", ("mcp", "servers")),
    "cline": (_cline_file, _parent(_cline_file), ("mcpServers",)),
    "roo": (_roo_file, _parent(_roo_file), ("mcpServers",)),
}
# 复制设置时告诉用户粘到哪（一句话）
PASTE_HINT = {
    "claude-code": "复制到终端运行",
    "claude-desktop": "粘进 claude_desktop_config.json（mcpServers）",
    "codex": "粘进 ~/.codex/config.toml",
    "cursor": "粘进 ~/.cursor/mcp.json（mcpServers）",
    "gemini": "粘进 ~/.gemini/settings.json（mcpServers）",
    "qwen": "粘进 ~/.qwen/settings.json（mcpServers）",
    "kimi": "粘进 ~/.kimi-code/mcp.json（mcpServers）",
    "pi": "粘进 ~/.pi/agent/mcp.json（mcpServers）",
    "zcode": "粘进 ~/.zcode/cli/config.json（mcp.servers），或在 ZCode 的 MCP 设置里粘 JSON",
    "cline": "Cline → MCP Servers → Configure，粘进 cline_mcp_settings.json",
    "roo": "Roo Code → MCP 设置 → 编辑全局 MCP，粘进 mcp_settings.json",
    "opencode": "粘进 ~/.config/opencode/opencode.json（mcp 段）",
    "grok": "粘进 ~/.grok/config.toml",
    "hermes": "粘进 ~/.hermes/config.yaml（mcp_servers 段），会话里 /reload-mcp",
    "deepseek": "合并进 ~/.dsh/cordis.patch.yml（别整份覆盖）",
    "windsurf": "Windsurf → MCP 设置 → 编辑 mcp_config.json，粘进去",
    "trae": "Trae → 设置 → MCP → 手动配置 → Raw Config，粘进去",
    "cherry": "Cherry Studio → 设置 → MCP → 添加 → 从 JSON 导入，粘进去",
}


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)   # JSON 字符串的转义是 TOML 基本字符串的子集


def snippet(app_id: str, spec: dict[str, Any] | None = None) -> str:
    """这个应用自己那种格式的一段设置（复制设置用）。"""
    spec = spec or server_spec()
    cmd, args, env = spec["command"], spec["args"], spec["env"]

    def flow(v: Any) -> str:   # YAML 认 JSON 的流式写法
        return json.dumps(v, ensure_ascii=False)
    if app_id == "claude-code":
        return _cc_command_text(spec)
    if app_id in ("codex", "grok"):
        envs = ", ".join(f"{k} = {_toml_str(v)}" for k, v in env.items())
        return (f"[mcp_servers.{NAME}]\ncommand = {_toml_str(cmd)}\nargs = [{', '.join(_toml_str(a) for a in args)}]\n"
                f"env = {{ {envs} }}\n")
    if app_id == "opencode":
        return json.dumps({"mcp": {NAME: {"type": "local", "command": [cmd, *args], "environment": env, "enabled": True}}},
                          ensure_ascii=False, indent=2)
    if app_id == "zcode":
        return json.dumps({"mcp": {"servers": {NAME: spec}}}, ensure_ascii=False, indent=2)
    if app_id == "hermes":
        return f"mcp_servers:\n  {NAME}:\n    command: {flow(cmd)}\n    args: {flow(args)}\n    env: {flow(env)}\n"
    if app_id == "deepseek":
        cfg = {"serverName": NAME, "transport": "stdio", "command": cmd, "args": args, "env": env}
        return f"- insert:\n    - id: mcp-{NAME}\n      name: '@deepseek-ai/dsh-mcp-client'\n      config: {flow(cfg)}\n"
    return json.dumps({"mcpServers": {NAME: spec}}, ensure_ascii=False, indent=2)


def _servers_at(data: dict[str, Any], keys: tuple[str, ...], create: bool = False) -> dict[str, Any] | None:
    cur: Any = data
    for k in keys:
        nxt = cur.get(k) if isinstance(cur, dict) else None
        if not isinstance(nxt, dict):
            if not create:
                return None
            nxt = cur[k] = {}
        cur = nxt
    return cur


def file_client_has(app_id: str) -> bool:
    path = FILE_CLIENTS[app_id][0]()
    if not path:
        return False
    servers = _servers_at(_read_json(path) or {}, FILE_CLIENTS[app_id][2])
    return bool(servers and isinstance(servers.get(NAME), dict))


def _file_installed(app_id: str) -> bool:
    d = FILE_CLIENTS[app_id][1]()
    return bool(d) and Path(d).is_dir()


def add_file_client(app_id: str) -> dict[str, Any]:
    name = APP_NAME[app_id]
    path, _, keys = FILE_CLIENTS[app_id]
    path = path()
    manual = {"ok": False, "client": app_id, "changed": False, "code": "", "manual": True, "command": snippet(app_id)}
    if not path or not _file_installed(app_id):
        return {**manual, "message": f"没找到 {name} 的配置目录：装好并打开过一次 {name} 再点，或复制设置自己粘"}
    try:
        data = _read_json(path, strict=True) or {}
    except BadConfig as exc:
        return {**manual, "message": f"{name} 的配置文件读不懂（可能带注释），没敢改：复制设置自己粘（{exc}）"}
    spec = server_spec()
    servers = _servers_at(data, keys, create=True)
    if servers.get(NAME) == spec:
        return {"ok": True, "client": app_id, "changed": False, "message": f"{name} 已经接上了"}
    backup = _backup(path, app_id)
    servers[NAME] = spec
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "client": app_id, "changed": True, "backup": backup, "config": str(path),
            "message": f"已写进 {name} 的 MCP 配置：重开 {name}（或新开会话）后工具名以 lwa 开头"}


def remove_file_client(app_id: str) -> dict[str, Any]:
    name = APP_NAME[app_id]
    path = FILE_CLIENTS[app_id][0]()
    try:
        data = (_read_json(path, strict=True) if path else None) or {}
    except BadConfig as exc:
        return {"ok": False, "client": app_id, "changed": False, "code": "", "message": f"{name} 的配置文件读不懂，没敢改（{exc}）"}
    servers = _servers_at(data, FILE_CLIENTS[app_id][2])
    if not servers or NAME not in servers:
        return {"ok": True, "client": app_id, "changed": False, "message": f"{name} 里本来就没有 lwa"}
    backup = _backup(path, app_id)
    servers.pop(NAME, None)
    storage.atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "client": app_id, "changed": True, "backup": backup, "message": f"已从 {name} 撤掉 lwa（重开 {name} 生效）"}


def _dir_installed(app_id: str) -> bool:
    """没有命令行、或命令行不在 PATH 时，看它自己的目录在不在（只认官方文档里写了的目录）。"""
    if app_id in FILE_CLIENTS:
        return _file_installed(app_id)
    if app_id == "deepseek":   # 桌面版装在这（Claudian DeepSeekInstallation.ts）；配置目录 DSH_HOME 默认 ~/.dsh
        local = os.environ.get("LOCALAPPDATA")
        return bool(local and (Path(local) / "Programs" / "DeepSeek Harness").is_dir()) or (_home() / ".dsh").is_dir()
    if app_id in ("hermes", "grok"):
        return (_home() / f".{app_id}").is_dir()
    return False


def _extra_bin_dirs() -> list[Path]:
    """PATH 之外常见的命令行安装目录（Obsidian 从开始菜单启动时 PATH 常常不全）。
    清单逐条照 Claudian src/core/process/env.ts 的 getExtraBinaryPaths（MIT，github.com/YishenTu/claudian），
    外加 Codex 独立安装包的目录（~/.codex/packages/standalone/current/bin）。"""
    home = Path.home()
    env = os.environ.get
    out: list[Path] = []
    if os.name == "nt":
        appdata, local = env("APPDATA"), env("LOCALAPPDATA")
        pf, pf86, pd = env("ProgramFiles") or r"C:\Program Files", env("ProgramFiles(x86)") or r"C:\Program Files (x86)", env("ProgramData") or r"C:\ProgramData"
        if appdata:
            out.append(Path(appdata) / "npm")
        if local:
            out += [Path(local) / "Programs" / "nodejs", Path(local) / "Programs" / "node"]
        out += [Path(pf) / "nodejs", Path(pf86) / "nodejs"]
        if env("NVM_SYMLINK"):
            out.append(Path(env("NVM_SYMLINK")))
        out.append(Path(env("NVM_HOME")) if env("NVM_HOME") else Path(appdata or home) / "nvm")
        out.append(Path(env("VOLTA_HOME")) / "bin" if env("VOLTA_HOME") else home / ".volta" / "bin")
        out += [Path(r) / "aliases" / "default" for r in (env("FNM_DIR"), appdata and str(Path(appdata) / "fnm"), local and str(Path(local) / "fnm")) if r]
        out.append(Path(env("ChocolateyInstall")) / "bin" if env("ChocolateyInstall") else Path(pd) / "chocolatey" / "bin")
        scoop = Path(env("SCOOP")) if env("SCOOP") else home / "scoop"
        out += [scoop / "shims", scoop / "apps" / "nodejs" / "current" / "bin", scoop / "apps" / "nodejs" / "current"]
        out.append(Path(pf) / "Docker" / "Docker" / "resources" / "bin")
        out += [home / "bin", home / ".local" / "bin", home / ".bun" / "bin", home / ".opencode" / "bin"]
        if local:
            out.append(Path(local) / "mise" / "shims")
    else:
        out += [Path("/usr/local/bin"), Path("/opt/homebrew/bin"), Path("/usr/bin"), Path("/bin")]
        if env("VOLTA_HOME"):
            out.append(Path(env("VOLTA_HOME")) / "bin")
        asdf = env("ASDF_DATA_DIR") or env("ASDF_DIR")
        if asdf:
            out += [Path(asdf) / "shims", Path(asdf) / "bin"]
        out += [home / "bin", home / ".local" / "bin", home / ".bun" / "bin", home / ".opencode" / "bin", home / ".docker" / "bin",
                home / ".npm-global" / "bin", home / ".volta" / "bin", home / ".asdf" / "shims", home / ".asdf" / "bin",
                home / ".local" / "share" / "mise" / "shims"]
        if env("NVM_BIN"):
            out.append(Path(env("NVM_BIN")))
    if env("npm_config_prefix"):
        out.append(Path(env("npm_config_prefix")) if os.name == "nt" else Path(env("npm_config_prefix")) / "bin")
    out.append(home / ".codex" / "packages" / "standalone" / "current" / "bin")
    return out


# Claudian 的服务商 id（它设置里 providerConfigs 的键）← 这边的应用 id
CLAUDIAN_ID = {"claude-code": "claude", "codex": "codex", "opencode": "opencode", "pi": "pi", "grok": "grok", "deepseek": "deepseek"}


def claudian_paths() -> dict[str, str]:
    """Claudian 里手填过的命令路径（<库>/.claudian/claudian-settings.json 的 providerConfigs.<id>.cliPathsByHost / cliPath）：
    两边认同一个程序。只读这几格，文件不在 / 读不懂就当没填。"""
    try:
        data = _read_json(storage.vault_root() / ".claudian" / "claudian-settings.json") or {}
    except Exception:  # noqa: BLE001 — 没有库 / 读不了都当没填
        return {}
    out: dict[str, str] = {}
    for aid, cid in CLAUDIAN_ID.items():
        cfg = (data.get("providerConfigs") or {}).get(cid) or {}
        cands = [*((cfg.get("cliPathsByHost") or {}).values() if isinstance(cfg.get("cliPathsByHost"), dict) else []), cfg.get("cliPath")]
        hit = next((str(c).strip().strip('"') for c in cands if c and Path(str(c).strip().strip('"')).is_file()), "")
        if hit:
            out[aid] = hit
    return out


def find_binary(name: str, app_id: str = "", *, claudian: dict[str, str] | None = None) -> str | None:
    if not name:
        return None
    if name == "claude":
        forced = os.environ.get(ENV_CLAUDE_EXE)
        if forced:
            return forced if Path(forced).exists() else None
    picked = (claudian_paths() if claudian is None else claudian).get(app_id or {v: k for k, v in CLAUDIAN_ID.items()}.get(name, name) or "")
    if picked:
        return picked
    found = shutil.which(name)
    if found:
        return found
    exts = [".exe", ".cmd", ".bat", ""] if os.name == "nt" else [""]
    for d in _extra_bin_dirs():
        for ext in exts:
            cand = d / (name + ext)
            if cand.is_file():
                return str(cand)
    return None


def _version(exe: str) -> str:
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return ""
    import re
    m = re.search(r"\d+\.\d+(?:\.\d+)?", (p.stdout or "") + " " + (p.stderr or ""))
    return m.group(0) if m else ""


def _connected(aid: str, desk: Path) -> bool:
    if aid == "claude-code":
        return bool(_claude_code_has())
    if aid == "claude-desktop":
        return NAME in (((_read_json(desk) or {}).get("mcpServers")) or {})
    if aid == "codex":
        return _codex_has()
    if aid in FILE_CLIENTS:
        return file_client_has(aid)
    return False   # 复制设置的那几家：不去读它们的配置，如实不标「已接入」


def _scan() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(装了的, 没认出来的)。装了 = 命令找得到，或它自己的配置目录在（Claude 桌面版、Cursor、Cline 这些）。
    结果不在这边缓存：照 Claudian（CachedProviderCLIResolver）在插件那边记住，设置页开着期间只问一次，接 / 断之后作废。"""
    from concurrent.futures import ThreadPoolExecutor
    desk = claude_desktop_config()
    via = claudian_paths()
    found = {aid: exe for aid, _, binary, _ in APPS if binary and (exe := find_binary(binary, aid, claudian=via))}
    spec = server_spec()
    have, rest = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = {aid: pool.submit(_version, exe) for aid, exe in found.items()}
        connected = {aid: pool.submit(_connected, aid, desk) for aid, *_ in APPS}
    for aid, name, _binary, oneclick in APPS:
        installed = bool(found.get(aid)) or (_desktop_installed(desk) if aid == "claude-desktop" else _dir_installed(aid))
        base = {"id": aid, "name": name, "oneclick": oneclick, "snippet": snippet(aid, spec), "hint": PASTE_HINT.get(aid, "")}
        if not installed:
            rest.append(base)
            continue
        have.append({**base, "installed": True, "path": found.get(aid) or "", "via": "claudian" if aid in via else "auto",
                     "version": versions[aid].result() if aid in versions else "", "connected": bool(connected[aid].result())})
    return have, rest


def apps() -> list[dict[str, Any]]:
    """[{id, name, installed, version, oneclick, connected, path, via, snippet, hint}]——只列这台电脑上装了的，顺序固定。
    via = "claudian"（用的是 Claudian 里手填的路径）或 "auto"（自动检测）。"""
    return _scan()[0]


# --------------------------------------------------------------------------
# 状态 / CLI
# --------------------------------------------------------------------------


def status() -> dict[str, Any]:
    cc = claude_code_config()
    desk = claude_desktop_config()
    have, rest = _scan()
    by = {a["id"]: a for a in have}
    clients = {
        "claude-code": {"name": CLIENT_CN["claude-code"], "installed": "claude-code" in by,
                        "connected": bool(by.get("claude-code", {}).get("connected")) or bool(_claude_code_has()),
                        "command": _cc_command_text(server_spec())},
        "claude-desktop": {"name": CLIENT_CN["claude-desktop"], "installed": _desktop_installed(desk),
                           "connected": NAME in (((_read_json(desk) or {}).get("mcpServers")) or {})},
    }
    spec = server_spec()
    return {"ok": True, "code": "", "message": "", "name": NAME, "clients": clients, "server": spec, "apps": have,
            "others": rest, "not_installed": [a["name"] for a in rest],
            "json": json.dumps({"mcpServers": {NAME: spec}}, ensure_ascii=False, indent=2),
            "config_paths": {"claude-code": str(cc), "claude-desktop": str(desk)}}


def add_parser(sub) -> None:
    p = sub.add_parser("connect", help="连接 AI：把收藏库接给本机的 AI 应用（Claude Code / Codex / Cursor / Gemini CLI …，写前备份、可撤销）")
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
          ("add", "claude-desktop"): add_claude_desktop, ("remove", "claude-desktop"): remove_claude_desktop,
          ("add", "codex"): add_codex, ("remove", "codex"): remove_codex}.get((cmd, args.client))
    if fn is None:   # 写 JSON 文件的那几家（FILE_CLIENTS）
        client = args.client
        fn = (lambda: add_file_client(client)) if cmd == "add" else (lambda: remove_file_client(client))
    try:
        out = fn()
    except OSError as exc:
        out = {"ok": False, "client": args.client, "changed": False, "code": "", "message": f"没写上：{exc}"}
    if not out.get("ok"):
        print(out.get("message"), file=sys.stderr)
    dump_json(outcome(out, ok=bool(out.get("ok")), message=out.get("message") or "", code=out.get("code") or ""))
    return 0 if out.get("ok") else 1
