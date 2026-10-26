"""1026 她：追问时命令行模型能上网（搜猫图这种最基本的）；别的调用照旧不能联网，Bash / 写文件始终禁。"""
import json

from link_brain import ask, text_stream


def test_default_still_denies_web():
    cmd = text_stream.harden_command(["claude", "-p"])
    denied = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert "WebFetch" in denied and "WebSearch" in denied and "--allowedTools" not in cmd
    assert "--search" not in text_stream.harden_command(["codex", "exec", "-"])
    perm = json.loads(text_stream.cli_env(["opencode", "run"])["OPENCODE_PERMISSION"])
    assert perm.get("webfetch") == "deny" and perm.get("websearch") == "deny"


def test_web_opens_only_search_and_fetch():
    cmd = text_stream.harden_command(["claude", "-p", "--disallowedTools", "Bash,WebFetch"], web=True)
    denied = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert "WebFetch" not in denied and "WebSearch" not in denied
    assert {"Bash", "Write", "Edit", "PowerShell"} <= set(denied)
    assert cmd[cmd.index("--allowedTools") + 1] == "WebFetch,WebSearch"
    assert text_stream.harden_command(["codex", "exec", "-"], web=True)[:3] == ["codex", "--search", "exec"]
    perm = json.loads(text_stream.cli_env(["opencode", "run"], web=True)["OPENCODE_PERMISSION"])
    assert "webfetch" not in perm and "websearch" not in perm and perm["bash"] == "deny"


def test_chat_follow_turns_web_on_for_cli_models_only(monkeypatch):
    seen = []
    monkeypatch.setattr(ask, "_text_ai_missing", lambda s: "")
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: seen.append((text_stream.WEB_TOOLS.get(), "上网" in p)) or {"status": "ok", "text": "好"})
    monkeypatch.setattr(ask.ai_config, "with_model", lambda cfg, m: {"textAI": {"mode": "cli" if m == "cli" else "http"}})
    ask.answer("找张猫图", [], mode="chat", model="cli")
    ask.answer("找张猫图", [], mode="chat", model="api")
    assert seen == [(True, True), (False, False)]
    assert text_stream.WEB_TOOLS.get() is False   # 用完复位
