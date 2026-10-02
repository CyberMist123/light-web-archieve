"""1001：命令行模型收权（C-1）、自定义模型的 key 不串（C-3）、报警出口兜底（E-3）、测试护栏（G-2/G-3）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from link_brain import ai_config, alert as alert_mod, storage, text_stream
from link_brain.adapters import xiaohongshu as xhs


# --------------------------------------------------------------------------
# C-1：问收藏选 Sonnet / Codex 时，命令一律收权（她 data.json 里存的旧命令也兜住）
# --------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, argv):
        self.argv = argv
        self.stdin = self
        self.stdout = iter(["答案\n"])

    def write(self, text):
        pass

    def close(self):
        pass

    def wait(self):
        return 0


def _run_model(monkeypatch, settings, name):
    seen = []

    def fake_popen(argv, **kw):
        seen.append(list(argv))
        return _FakeProc(argv)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    cfg = ai_config.with_model(settings, name)["textAI"]
    out = text_stream.call("说明", "材料", cfg)
    assert out["status"] == "ok"
    return seen[0]


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_old_sonnet_command_in_data_json_is_locked_down(monkeypatch):
    settings = {**ai_config.DEFAULTS, "models": [{"name": "Sonnet", "mode": "cli", "command": "claude -p --model sonnet"}]}
    argv = _run_model(monkeypatch, settings, "Sonnet")
    assert _flag(argv, "--permission-mode") == "default"
    denied = set(_flag(argv, "--disallowedTools").split(","))
    assert {"Bash", "PowerShell", "Write", "Edit", "WebFetch"} <= denied
    assert "--strict-mcp-config" in argv


def test_dangerous_claude_flags_are_overridden_not_duplicated(monkeypatch):
    cmd = ("claude -p --permission-mode bypassPermissions --dangerously-skip-permissions "
           "--disallowedTools Bash --strict-mcp-config")
    settings = {**ai_config.DEFAULTS, "models": [{"name": "X", "mode": "cli", "command": cmd}]}
    argv = _run_model(monkeypatch, settings, "X")
    assert argv.count("--permission-mode") == 1 and _flag(argv, "--permission-mode") == "default"
    assert "--dangerously-skip-permissions" not in argv
    assert argv.count("--disallowedTools") == 1 and "Write" in _flag(argv, "--disallowedTools")
    assert argv.count("--strict-mcp-config") == 1


def test_default_sonnet_command_is_already_locked_down(monkeypatch):
    argv = _run_model(monkeypatch, ai_config.DEFAULTS, "Sonnet")
    assert argv.count("--permission-mode") == 1 and argv.count("--disallowedTools") == 1


@pytest.mark.parametrize("cmd", ["codex exec --skip-git-repo-check -c model_reasoning_effort=low -",
                                 "codex exec -s danger-full-access -",
                                 "codex exec --sandbox=workspace-write -",
                                 "codex exec --dangerously-bypass-approvals-and-sandbox -s read-only -"])
def test_codex_is_always_read_only(monkeypatch, cmd):
    settings = {**ai_config.DEFAULTS, "models": [{"name": "C", "mode": "cli", "command": cmd}]}
    argv = _run_model(monkeypatch, settings, "C")
    modes = [argv[i + 1] for i, t in enumerate(argv) if t in ("-s", "--sandbox")] + \
            [t.split("=", 1)[1] for t in argv if t.startswith("--sandbox=")]
    assert modes == ["read-only"]
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert argv[-1] == "-"  # 占位的 stdin 提示词还在最后


# --------------------------------------------------------------------------
# C-3：新加的 HTTP 模型带自己的 key，发出去的必须是它自己的
# --------------------------------------------------------------------------


class _Stream:
    def __init__(self, sink, url, headers):
        sink.append((url, headers))
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
        yield "data: [DONE]"


def _send(monkeypatch, settings, name):
    sent = []
    monkeypatch.setattr(text_stream._CLIENT, "stream",
                        lambda method, url, headers=None, json=None, **kw: _Stream(sent, url, headers))
    cfg = ai_config.with_model(settings, name)["textAI"]
    assert text_stream.call("说明", "材料", cfg)["status"] == "ok"
    return sent[0]


def _settings(tmp_path, *models):
    keyfile = tmp_path / "deepseek.csv"
    keyfile.write_text("apiKey,DS-KEY-FROM-FILE\n", encoding="utf-8")
    return {**ai_config.DEFAULTS,
            "textAI": {"mode": "http", "endpoint": "https://api.deepseek.com/chat/completions", "apiKey": "",
                       "model": "deepseek-v4-flash",
                       "keyFile": str(keyfile), "keyField": "apiKey"},
            "models": list(models)}


def test_new_http_model_sends_its_own_key(tmp_path, monkeypatch):
    settings = _settings(tmp_path, {"name": "Gemini", "mode": "http", "apiKey": "GEMINI-OWN",
                                    "endpoint": "https://generativelanguage.example/v1/chat/completions"})
    url, headers = _send(monkeypatch, settings, "Gemini")
    assert headers["Authorization"] == "Bearer GEMINI-OWN" and "deepseek" not in url


def test_other_endpoint_without_key_does_not_get_deepseek_key(tmp_path, monkeypatch):
    settings = _settings(tmp_path, {"name": "Other", "mode": "http", "endpoint": "https://other.example/v1/chat"})
    _, headers = _send(monkeypatch, settings, "Other")
    assert "Authorization" not in headers


def test_deepseek_entry_still_uses_the_key_file(tmp_path, monkeypatch):
    settings = _settings(tmp_path, {"name": "DeepSeek", "mode": "http",
                                    "endpoint": "https://api.deepseek.com/chat/completions", "apiKey": ""})
    _, headers = _send(monkeypatch, settings, "DeepSeek")
    assert headers["Authorization"] == "Bearer DS-KEY-FROM-FILE"


# --------------------------------------------------------------------------
# E-3：没设环境变量时，报警走 ~/.link-brain/alert-cmd.txt
# --------------------------------------------------------------------------


def _catcher(tmp_path):
    out = tmp_path / "got.json"
    script = tmp_path / "catch_alert.py"
    script.write_text("import sys, pathlib\n"
                      f"pathlib.Path({str(out)!r}).write_bytes(sys.stdin.buffer.read())\n", encoding="utf-8")
    return out, f'"{sys.executable}" "{script}"'


def test_alert_uses_command_file_when_env_is_unset(tmp_path, monkeypatch, capsys):
    out, command = _catcher(tmp_path)
    home = Path(os.environ["LINK_BRAIN_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "alert-cmd.txt").write_text("# 报警出口\n\n" + command + "\n", encoding="utf-8")
    assert alert_mod.alert(alert_mod.KIND_ACCOUNT, "号要人处理", "详情") is True
    assert json.loads(out.read_text("utf-8"))["title"] == "号要人处理"
    assert "号要人处理" in capsys.readouterr().err


def test_env_command_wins_and_missing_file_means_stderr_only(tmp_path, monkeypatch, capsys):
    assert alert_mod.alert_command() == ""
    assert alert_mod.alert("normal", "只打 stderr", "x") is False
    assert "只打 stderr" in capsys.readouterr().err
    out, command = _catcher(tmp_path)
    monkeypatch.setenv(alert_mod.ENV_ALERT_CMD, command)
    home = Path(os.environ["LINK_BRAIN_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "alert-cmd.txt").write_text("definitely-not-a-real-command-xyz\n", encoding="utf-8")
    assert alert_mod.alert("normal", "环境变量优先", "x") is True
    assert json.loads(out.read_text("utf-8"))["title"] == "环境变量优先"


_HOME_PATH = __import__("re").compile(r"[A-Za-z]:[\\/]Users[\\/](?!<|%|\{)[^\\/\s]+[\\/]", __import__("re").I)


def test_no_private_default_paths_in_public_modules():
    root = Path(__file__).resolve().parents[1] / "link_brain"
    for name in ("alert.py", "accounts.py", "enrich.py", "favorites.py", "catch.py"):
        assert not _HOME_PATH.search((root / name).read_text(encoding="utf-8")), name
    assert not _HOME_PATH.search((root / "adapters" / "xiaohongshu.py").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# G-2 / G-3：测试护栏本身
# --------------------------------------------------------------------------


def test_tests_run_in_a_temp_vault_and_home(tmp_path):
    assert storage.vault_root() == (tmp_path / "vault").resolve()
    assert Path(os.environ["LINK_BRAIN_HOME"]) == tmp_path / "lbhome"
    assert not Path(xhs.RELATEDFILE_EXE).exists()


def test_guard_refuses_local_xiaohongshu_executables():
    exe = str(Path.home() / ".xiaohongshu-mcp" / "link-brain-reader.exe")
    with pytest.raises(RuntimeError, match="不许起本机小红书组件"):
        subprocess.run([exe, "-h"], capture_output=True)


def test_guard_refuses_commands_naming_the_reader():
    """restart_reader 按进程名结束读取服务：测试里要是走到那一步，护栏先拦下（这里用无害的 echo 验护栏本身）。"""
    with pytest.raises(RuntimeError, match="不许起本机小红书组件"):
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Write-Output 'link-brain-reader.exe'"],
                       capture_output=True)


@pytest.mark.real_web_probe
def test_real_web_probe_cannot_start_a_browser(monkeypatch):
    """real_web_probe 用例绕开了 conftest 的探测替身，但仍然走不到 relatedfile.exe。"""
    out = xhs._probe_related_file_via_browser("0000000000000000deadbeef", None, timeout=5)
    assert out["ok"] is False and "缺 relatedfile.exe" in out["error"]
