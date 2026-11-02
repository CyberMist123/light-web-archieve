"""1102 发布地基：`version` 子命令、`__version__` 的来源与退路、装成 wheel 后没有仓库目录也读得到的三处。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import link_brain
from link_brain import cli, problems, wiki
from link_brain.sources.xiaohongshu import accounts

ROOT = Path(__file__).resolve().parents[1]


def test_version_command_outputs_one_json_line(capsys):
    assert cli.main(["version"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1, out
    data = json.loads(out[0])
    assert data["ok"] is True and data["code"] == "" and data["message"]
    assert data["version"] == link_brain.__version__
    assert data["python"] == "%d.%d.%d" % sys.version_info[:3]
    assert data["executable"] == sys.executable


def test_dunder_version_falls_back_to_pyproject(monkeypatch):
    """包元数据读不到（没 pip install 直接跑源码）→ 读 pyproject.toml；再读不到 → "0"，不编数字。"""
    import importlib.metadata as md

    def missing(_name):
        raise md.PackageNotFoundError("link-brain")
    monkeypatch.setattr(md, "version", missing)
    import tomllib
    assert link_brain._read_version() == tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    monkeypatch.setattr(Path, "open", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no pyproject")))
    assert link_brain._read_version() == "0"


def test_plugin_version_without_repo_uses_package_version(monkeypatch, tmp_path):
    monkeypatch.setattr(problems.storage, "repo_root", lambda: tmp_path)   # 没有 obsidian-plugins/ 的安装
    assert problems._plugin_version() == link_brain.__version__
    manifest = tmp_path / "obsidian-plugins" / "link-brain-actions" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"version": "9.9.9"}), "utf-8")
    assert problems._plugin_version() == "9.9.9"


def test_method_doc_ships_inside_package():
    p = wiki.method_path()
    assert p.is_file() and p.parent.name == "assets" and p.parent.parent == Path(link_brain.__file__).parent
    assert "深度报告" in (wiki.method_text() or "")
    assert not (ROOT / "docs" / "deep-report.md").read_text("utf-8").count("## 1. 广召回"), "docs/ 里只留指路牌，方法全文只在 assets/"


def test_tool_roots_skips_missing_repo_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(accounts.storage, "repo_root", lambda: tmp_path)
    roots = accounts.tool_roots()
    assert tmp_path / "tools" not in roots and roots[0] == accounts.bin_dir() and roots[-1] == accounts.tool_dir()
    (tmp_path / "tools").mkdir()
    assert accounts.tool_roots()[1] == tmp_path / "tools"
