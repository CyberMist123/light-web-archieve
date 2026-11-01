"""1101：命令行 `tool` 和 MCP 同一张工具表、同一张开放名单（给终端里的 AI 用）。"""

import json
from pathlib import Path

from link_brain import ai_config, cli, mcp_tools


def _data(vault: Path, data: dict) -> None:
    p = vault / ".obsidian" / "plugins" / ai_config.PLUGIN_ID / "data.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_tool_lists_same_tools_as_mcp(capsys):
    assert cli.main(["tool"]) == 0
    out = capsys.readouterr().out
    for t in mcp_tools.TOOLS:
        assert f"- {t['name']}：" in out


def test_tool_calls_mcp_handler_with_kv_args(monkeypatch, capsys):
    seen = {}
    monkeypatch.setitem(mcp_tools.HANDLERS, "recent", lambda ctx, a: seen.update(ctx=ctx, args=a) or {"ok": 1})
    assert cli.main(["tool", "recent", "days=3", "limit=2", "--compact"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": 1}
    assert seen["args"] == {"days": 3, "limit": 2} and seen["ctx"].who == "命令行"
    assert cli.main(["tool", "recent", '{"days": 5}']) == 0
    assert seen["args"] == {"days": 5}


def test_tool_respects_open_folders(capsys, tmp_path):
    import os
    _data(Path(os.environ["LINK_BRAIN_VAULT"]), {"remote": {"folders": []}})
    assert cli.main(["tool", "recent"]) == 2
    assert "NOT_OPEN" in capsys.readouterr().out


def test_tool_unknown_and_bad_args(capsys):
    assert cli.main(["tool", "nope"]) == 2
    assert cli.main(["tool", "recent", "days"]) == 2
    assert "UNKNOWN_TOOL" in capsys.readouterr().err
