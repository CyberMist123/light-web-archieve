"""1101 作者：「市面上的 harness 都放上来」——Cursor / Gemini CLI / Qwen Code / Kimi / Pi / ZCode / Cline / Roo 一键写 JSON 配置，
OpenCode / Grok / Hermes / DeepSeek Harness / Windsurf / Trae / Cherry Studio 复制各自格式的设置。

家目录、VS Code 目录、PATH 全换成临时目录——不碰真的 AI 应用配置。
"""

from __future__ import annotations

import json
import tomllib

import pytest
import yaml

from link_brain import cli, connect


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(connect, "_home", lambda: h)
    monkeypatch.setattr(connect, "_vscode_storages", lambda: [tmp_path / "Code" / "User" / "globalStorage"])
    monkeypatch.setattr(connect, "_extra_bin_dirs", lambda: [])
    monkeypatch.setattr(connect, "claudian_paths", lambda: {})
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv(connect.ENV_DESKTOP, str(tmp_path / "nodesk" / "Claude" / "claude_desktop_config.json"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    for k in ("KIMI_CODE_HOME", "PI_CODING_AGENT_DIR", "CODEX_HOME", connect.ENV_CLAUDE_EXE):
        monkeypatch.delenv(k, raising=False)
    return h


def _out(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_every_app_has_a_snippet_that_parses():
    spec = {"command": "C:\\Py\\python.exe", "args": ["-m", "link_brain", "mcp"], "env": {"LINK_BRAIN_VAULT": "D:\\库 a\\vault"}}
    for aid, *_ in connect.APPS:
        text = connect.snippet(aid, spec)
        assert connect.PASTE_HINT[aid], aid
        if aid == "claude-code":
            assert text.startswith("claude mcp add lwa ")
        elif aid in ("codex", "grok"):
            got = tomllib.loads(text)["mcp_servers"]["lwa"]
            assert got["command"] == spec["command"] and got["env"] == spec["env"]
        elif aid == "hermes":
            assert yaml.safe_load(text)["mcp_servers"]["lwa"]["args"] == spec["args"]
        elif aid == "deepseek":
            cfg = yaml.safe_load(text)[0]["insert"][0]
            assert cfg["name"] == "@deepseek-ai/dsh-mcp-client" and cfg["config"]["transport"] == "stdio"
        elif aid == "opencode":
            got = json.loads(text)["mcp"]["lwa"]
            assert got["type"] == "local" and got["command"] == [spec["command"], *spec["args"]] and got["environment"] == spec["env"]
        elif aid == "zcode":
            assert json.loads(text)["mcp"]["servers"]["lwa"] == spec
        else:
            assert json.loads(text)["mcpServers"]["lwa"] == spec


@pytest.mark.parametrize("aid,rel,keys", [
    ("cursor", ".cursor/mcp.json", ("mcpServers",)),
    ("gemini", ".gemini/settings.json", ("mcpServers",)),
    ("qwen", ".qwen/settings.json", ("mcpServers",)),
    ("kimi", ".kimi-code/mcp.json", ("mcpServers",)),
    ("pi", ".pi/agent/mcp.json", ("mcpServers",)),
    ("zcode", ".zcode/cli/config.json", ("mcp", "servers")),
])
def test_file_client_add_keeps_others_backs_up_and_undo(home, capsys, aid, rel, keys):
    path = home / rel
    # 没装（目录不在）：不建目录，给复制设置
    res = connect.add_file_client(aid)
    assert res["ok"] is False and res["manual"] and res["command"] and not path.parent.exists()
    path.parent.mkdir(parents=True)
    before = {"theme": "dark"}
    cur = before
    for k in keys:
        cur = cur.setdefault(k, {})
    cur["other"] = {"command": "x"}
    path.write_text(json.dumps(before), "utf-8")
    assert cli.main(["connect", "add", aid]) == 0
    out = _out(capsys)
    assert out["ok"] and out["changed"] and out["backup"]
    data = json.loads(path.read_text("utf-8"))
    servers = data
    for k in keys:
        servers = servers[k]
    assert data["theme"] == "dark" and servers["other"] == {"command": "x"}
    assert servers["lwa"]["args"] == ["-m", "link_brain", "mcp"] and "LINK_BRAIN_VAULT" in servers["lwa"]["env"]
    assert connect.file_client_has(aid)
    assert connect.add_file_client(aid)["changed"] is False          # 再点一次不重复写
    assert cli.main(["connect", "remove", aid]) == 0
    data = json.loads(path.read_text("utf-8"))
    servers = data
    for k in keys:
        servers = servers[k]
    assert "lwa" not in servers and servers["other"] == {"command": "x"} and data["theme"] == "dark"


def test_config_with_comments_is_not_touched(home):
    """Gemini / Qwen 的 settings.json 允许注释——读不懂就不改，给复制设置。"""
    path = home / ".gemini" / "settings.json"
    path.parent.mkdir(parents=True)
    text = '{\n  // 我的注释\n  "theme": "dark"\n}\n'
    path.write_text(text, "utf-8")
    res = connect.add_file_client("gemini")
    assert res["ok"] is False and res["manual"] and "注释" in res["message"]
    assert json.loads(res["command"])["mcpServers"]["lwa"]
    assert path.read_text("utf-8") == text


def test_kimi_old_dir_and_cline_roo_in_vscode(home, tmp_path):
    (home / ".kimi").mkdir()
    assert connect.FILE_CLIENTS["kimi"][0]() == home / ".kimi" / "mcp.json"   # 只有旧版目录时写旧版
    (home / ".kimi-code").mkdir()
    assert connect.FILE_CLIENTS["kimi"][0]() == home / ".kimi-code" / "mcp.json"
    store = tmp_path / "Code" / "User" / "globalStorage"
    assert connect._cline_file() is None and connect.add_file_client("cline")["manual"]
    (store / "saoudrizwan.claude-dev" / "settings").mkdir(parents=True)
    (store / "RooVeterinaryInc.roo-cline" / "settings").mkdir(parents=True)
    assert connect.add_file_client("cline")["changed"]
    assert json.loads((store / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json").read_text("utf-8"))["mcpServers"]["lwa"]
    assert connect.add_file_client("roo")["changed"]
    assert connect.file_client_has("roo")


def test_status_lists_installed_and_others_with_snippets(home, tmp_path, monkeypatch):
    (home / ".cursor").mkdir()
    (home / ".hermes").mkdir()
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"lwa": {"command": "x"}}}), "utf-8")
    monkeypatch.setattr(connect, "_version", lambda exe: "9.9")
    st = connect.status()
    assert [a["id"] for a in st["apps"]] == ["cursor", "hermes"]
    cursor, hermes = st["apps"]
    assert cursor["oneclick"] and cursor["connected"] and hermes["oneclick"] is False and hermes["connected"] is False
    assert "mcp_servers:" in hermes["snippet"] and "config.yaml" in hermes["hint"]
    others = [a["id"] for a in st["others"]]
    assert "cursor" not in others and {"trae", "cherry", "windsurf", "opencode", "deepseek"} <= set(others)
    assert all(a["snippet"] and a["hint"] for a in st["others"])
    assert st["not_installed"] == [a["name"] for a in st["others"]]
