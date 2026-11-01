"""1101 设置打通：收藏库在子文件夹时后端也读得到插件设置；关了「开放收藏库」本机 MCP 也不再开回来。"""

import json
from pathlib import Path

from link_brain import ai_config, mcp_tools

REL = Path(".obsidian") / "plugins" / ai_config.PLUGIN_ID / "data.json"


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_data_json_found_when_collection_is_vault_subfolder(tmp_path, monkeypatch):
    obsidian = tmp_path / "MyVault"
    sub = obsidian / "收藏"
    sub.mkdir(parents=True)
    want = _write(obsidian / REL, {"sync": {"perRunLimit": 7}})
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(sub))
    monkeypatch.delenv("LINK_BRAIN_OBSIDIAN_DIR", raising=False)
    assert ai_config.data_json_path() == want          # 计划任务 / 命令行：往上找
    monkeypatch.setenv("LINK_BRAIN_OBSIDIAN_DIR", str(obsidian / ".obsidian"))
    assert ai_config.data_json_path() == want          # 插件拉起：用它传来的 configDir
    assert ai_config.load()["sync"]["perRunLimit"] == 7


def test_data_json_defaults_to_own_obsidian_when_nothing_found(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "v"))
    monkeypatch.delenv("LINK_BRAIN_OBSIDIAN_DIR", raising=False)
    assert ai_config.data_json_path() == (tmp_path / "v").resolve() / REL


def test_local_policy_empty_folders_opens_nothing(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(vault))
    monkeypatch.delenv("LINK_BRAIN_OBSIDIAN_DIR", raising=False)
    _write(vault / REL, {"remote": {"folders": []}})
    assert list(mcp_tools.local_policy().folders) == []
    _write(vault / REL, {"remote": {}})                 # 没设过：默认只开收藏库
    assert list(mcp_tools.local_policy().folders) == ["@xhs"]
