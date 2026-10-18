"""1018 她：「知识库接入 AI」照 Claudian 认本机装了的 AI 应用；一键接入扩到 Codex。

全用假命令 / 假目录：PATH 指到临时目录，常见安装目录换成空列表，codex 的调用换成记录器——不碰真的 Codex / Claude 配置。
"""

from __future__ import annotations

import json
import os

import pytest

from link_brain import cli, connect


@pytest.fixture
def fake_bins(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setattr(connect, "_extra_bin_dirs", lambda: [tmp_path / "extra"])
    monkeypatch.setenv(connect.ENV_DESKTOP, str(tmp_path / "nodesk" / "Claude" / "claude_desktop_config.json"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    monkeypatch.delenv(connect.ENV_CLAUDE_EXE, raising=False)
    monkeypatch.setattr(connect, "_version", lambda exe: "1.2.3")

    def make(name: str, where=bindir):
        where.mkdir(parents=True, exist_ok=True)
        f = where / (name + (".cmd" if os.name == "nt" else ""))
        f.write_text("@echo off\n" if os.name == "nt" else "#!/bin/sh\n", "utf-8")
        f.chmod(0o755)
        return f
    return tmp_path, make


def test_apps_lists_only_installed_in_fixed_order(fake_bins, monkeypatch):
    tmp, make = fake_bins
    make("opencode")
    make("codex", tmp / "extra")            # 不在 PATH、在常见安装目录里也认
    monkeypatch.setattr(connect, "_codex_has", lambda: True)
    got = connect.apps()
    assert [a["id"] for a in got] == ["codex", "opencode"]
    codex, opencode = got
    assert codex == {"id": "codex", "name": "Codex", "installed": True, "oneclick": True, "version": "1.2.3", "connected": True}
    assert opencode["oneclick"] is False and opencode["connected"] is False


def test_status_names_what_is_not_installed(fake_bins, monkeypatch):
    tmp, make = fake_bins
    make("pi")
    monkeypatch.setattr(connect, "_codex_has", lambda: False)
    st = connect.status()
    assert [a["id"] for a in st["apps"]] == ["pi"]
    assert "Pi" not in st["not_installed"] and "Codex" in st["not_installed"] and "OpenCode" in st["not_installed"]


def test_codex_add_runs_codex_mcp_add_with_env_and_remove(fake_bins, monkeypatch, capsys):
    tmp, make = fake_bins
    make("codex")
    calls, state = [], {"has": False}

    def fake_run(args, timeout=60):
        calls.append(args)
        if args[:2] == ["mcp", "get"]:
            return (0 if state["has"] else 1), ""
        if args[:2] == ["mcp", "add"]:
            state["has"] = True
        if args[:2] == ["mcp", "remove"]:
            state["has"] = False
        return 0, "ok"
    monkeypatch.setattr(connect, "_run_codex", fake_run)
    assert cli.main(["connect", "add", "codex"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] and out["changed"]
    add = next(a for a in calls if a[:2] == ["mcp", "add"])
    assert add[2] == "lwa" and "--env" in add and any(x.startswith("LINK_BRAIN_VAULT=") for x in add)
    assert add[add.index("--") + 1:][-3:] == ["-m", "link_brain", "mcp"]
    # 再点一次：已经接上，不重复写
    assert connect.add_codex()["changed"] is False
    assert cli.main(["connect", "remove", "codex"]) == 0
    assert state["has"] is False


def test_codex_missing_gives_copyable_command(fake_bins):
    res = connect.add_codex()
    assert res["ok"] is False and res["manual"] and res["command"].startswith("codex mcp add lwa ")
