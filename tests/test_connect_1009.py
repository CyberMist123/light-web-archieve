"""1009 她：「连接 AI」一个模块——本机客户端一键写配置（写前备份、写完报结果、可撤销）。

测试一律用临时配置路径（CLAUDE_CONFIG_DIR / LWA_CLAUDE_DESKTOP_CONFIG 指到 tmp），绝不碰真的 Claude Code / Claude Desktop 配置。
真跑 claude 命令的那条默认跳过（LWA_TEST_REAL_CLAUDE=1 才跑，也只写临时目录）。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from link_brain import cli, connect


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    desk = tmp_path / "AppData" / "Claude" / "claude_desktop_config.json"
    monkeypatch.setenv(connect.ENV_DESKTOP, str(desk))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    (tmp_path / "cc").mkdir()
    real_home_cc = Path.home() / ".claude.json"
    before = real_home_cc.stat().st_mtime_ns if real_home_cc.exists() else None
    yield tmp_path, desk
    after = real_home_cc.stat().st_mtime_ns if real_home_cc.exists() else None
    assert before == after, "测试碰了真的 ~/.claude.json"


def _out(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_desktop_add_backup_keep_others_and_undo(sandbox, capsys):
    tmp, desk = sandbox
    desk.parent.mkdir(parents=True)
    desk.write_text(json.dumps({"preferences": {"x": 1}, "mcpServers": {"other": {"command": "node"}}}), "utf-8")
    assert cli.main(["connect", "add", "claude-desktop"]) == 0
    out = _out(capsys)
    assert out["ok"] is True and out["changed"] is True and "Claude Desktop" in out["message"]
    data = json.loads(desk.read_text("utf-8"))
    assert data["preferences"] == {"x": 1} and "other" in data["mcpServers"]
    spec = data["mcpServers"]["lwa"]
    assert spec["args"] == ["-m", "link_brain", "mcp"] and spec["env"]["LINK_BRAIN_VAULT"] and spec["env"]["PYTHONPATH"]
    assert Path(out["backup"]).is_file()  # 写前备份
    assert cli.main(["connect", "add", "claude-desktop"]) == 0 and _out(capsys)["changed"] is False
    st = connect.status()
    assert st["clients"]["claude-desktop"]["connected"] is True
    assert cli.main(["connect", "remove", "claude-desktop"]) == 0 and _out(capsys)["changed"] is True
    data = json.loads(desk.read_text("utf-8"))
    assert "lwa" not in data["mcpServers"] and "other" in data["mcpServers"] and data["preferences"] == {"x": 1}


def test_desktop_refuses_bad_json_and_missing_install(sandbox, capsys):
    tmp, desk = sandbox
    assert cli.main(["connect", "add", "claude-desktop"]) == 1
    assert "没找到 Claude Desktop" in _out(capsys)["message"]
    desk.parent.mkdir(parents=True)
    desk.write_text("{这不是 JSON", "utf-8")
    assert cli.main(["connect", "add", "claude-desktop"]) == 1
    assert "没敢改" in _out(capsys)["message"]
    assert desk.read_text("utf-8") == "{这不是 JSON"
    desk.write_text("", "utf-8")  # 空文件可以写
    assert cli.main(["connect", "add", "claude-desktop"]) == 0


def test_claude_code_add_uses_user_scope_and_undo(sandbox, capsys, monkeypatch):
    tmp, _ = sandbox
    cfg = tmp / "cc" / ".claude.json"
    cfg.write_text(json.dumps({"projects": {"x": {}}, "mcpServers": {}}), "utf-8")
    calls = []

    def fake(args, timeout=90):
        calls.append(list(args))
        data = json.loads(cfg.read_text("utf-8"))
        if args[:2] == ["mcp", "add"]:
            cut = args.index("--")
            env = dict(a.split("=", 1) for a in args[5:cut] if a != "-e")
            data["mcpServers"][args[2]] = {"type": "stdio", "command": args[cut + 1], "args": args[cut + 2:], "env": env}
        else:
            data["mcpServers"].pop(args[2], None)
        cfg.write_text(json.dumps(data), "utf-8")
        return 0, "ok"
    monkeypatch.setattr(connect, "_run_claude", fake)
    monkeypatch.setattr(connect, "claude_exe", lambda: "claude")
    assert cli.main(["connect", "add", "claude-code"]) == 0
    out = _out(capsys)
    assert out["ok"] and out["changed"] and Path(out["backup"]).is_file()
    add = calls[0]
    assert add[:5] == ["mcp", "add", "lwa", "-s", "user"] and add[add.index("--") + 2:] == ["-m", "link_brain", "mcp"]
    assert any(a.startswith("LINK_BRAIN_VAULT=") for a in add)
    assert connect.status()["clients"]["claude-code"]["connected"] is True
    assert cli.main(["connect", "add", "claude-code"]) == 0 and _out(capsys)["changed"] is False and len(calls) == 1
    assert cli.main(["connect", "remove", "claude-code"]) == 0 and _out(capsys)["changed"] is True
    assert calls[-1] == ["mcp", "remove", "lwa", "-s", "user"]
    assert json.loads(cfg.read_text("utf-8"))["projects"] == {"x": {}}  # 别的东西一律不碰


def test_claude_code_missing_cli_gives_command_to_copy(sandbox, capsys, monkeypatch):
    monkeypatch.setattr(connect, "claude_exe", lambda: None)
    assert cli.main(["connect", "add", "claude-code"]) == 1
    out = _out(capsys)
    assert out["manual"] is True and out["command"].startswith("claude mcp add lwa -s user -e ")


@pytest.mark.skipif(os.environ.get("LWA_TEST_REAL_CLAUDE") != "1", reason="真跑 claude 命令：LWA_TEST_REAL_CLAUDE=1 才跑（也只写临时目录）")
def test_real_claude_cli_writes_only_temp_config(sandbox, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.main(["connect", "add", "claude-code"]) == 0
    data = json.loads((tmp_path / "cc" / ".claude.json").read_text("utf-8"))
    assert data["mcpServers"]["lwa"]["args"] == ["-m", "link_brain", "mcp"]
    assert cli.main(["connect", "remove", "claude-code"]) == 0
