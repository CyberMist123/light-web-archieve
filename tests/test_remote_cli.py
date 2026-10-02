"""第 6 批「远程阅读」：配置 / 命令行 / 计划任务（假 PowerShell）/ 独立进程起停。

- 计划任务的注册 / 移除只断言生成的 PowerShell（不真注册：测试不许动本机计划任务）。
- 独立进程：真起 `python -m link_brain remote serve` 子进程（它不依赖 Obsidian / 插件进程），
  用访问令牌调工具；把设置里的开关关掉 → 它自己退出并写 status.json。
"""

from __future__ import annotations

import io
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from link_brain import cli, problems
from link_brain.remote import config as rconfig
from link_brain.remote import server as rserver
from link_brain.remote import store as rstore
from link_brain.remote import task as rtask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_remote_mcp import AGENT, DATA_JSON, free_port, make_vault, write_settings  # noqa: E402


def run_cli(capsys, argv, stdin: bytes | None = None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8"))
    code = cli.main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1]) if out else None


# ------------------------------------------------------------------ 配置

def test_config_normalize():
    cfg, probs = rconfig.normalize({"enabled": True, "domain": "https://LB.Example.com/", "port": "18080",
                                    "folders": ["@xhs", "其他资料", "其他资料", "", 3]})
    assert cfg == {"enabled": True, "domain": "https://lb.example.com", "port": 18080, "folders": ["@xhs", "其他资料"]}
    assert probs == []
    for bad in ("http://a.example.com", "https://a.example.com/mcp", "https://a.example.com:8443", "https://user@x.com",
                "https://bad_host"):
        cfg, probs = rconfig.normalize({"domain": bad})
        assert cfg["domain"] == "" and probs, bad
    cfg, probs = rconfig.normalize({"port": 80, "enabled": "yes"})
    assert cfg["port"] == rconfig.DEFAULTS["port"] and probs and cfg["enabled"] is False


def test_defaults_match_plugin_remote_ui():
    js = (ROOT / "obsidian-plugins/link-brain-actions/remote-ui.js").read_text("utf-8")
    m = re.search(r"const REMOTE_DEFAULTS = (\{.*?\});", js)
    assert m, "remote-ui.js 里要有 const REMOTE_DEFAULTS = {...};"
    assert json.loads(m.group(1)) == rconfig.DEFAULTS


def test_secrets_never_in_data_json_shape():
    assert set(rconfig.DEFAULTS) == {"enabled", "domain", "port", "folders"}   # 口令 / 令牌不进 data.json


# ------------------------------------------------------------------ 口令 / 令牌（CLI）

def test_passphrase_via_stdin_and_tokens(capsys, monkeypatch, tmp_path):
    code, out = run_cli(capsys, ["remote", "passphrase"], json.dumps({"passphrase": "short"}).encode(), monkeypatch)
    assert code == 1 and not out["ok"] and "至少" in out["message"]
    code, out = run_cli(capsys, ["remote", "passphrase"], json.dumps({"passphrase": "长一点的口令 ok"}).encode(), monkeypatch)
    assert code == 0 and out["ok"]
    st = rstore.AuthStore()
    assert st.check_passphrase("长一点的口令 ok") and not st.check_passphrase("长一点的口令 OK")
    raw = (rstore.state_dir() / "auth.json").read_text("utf-8")
    assert "长一点的口令" not in raw
    assert str(rstore.state_dir()).startswith(os.environ["LINK_BRAIN_HOME"])      # 在 ~/.link-brain/remote，不在 vault
    code, out = run_cli(capsys, ["remote", "token", "new", "--label", "Claude 桌面"])
    assert code == 0 and out["token"].startswith("lbr_p_") and out["id"].startswith("pt_")
    assert out["token"] not in (rstore.state_dir() / "auth.json").read_text("utf-8")
    assert rstore.AuthStore().authenticate(out["token"])["label"] == "Claude 桌面"
    code, out2 = run_cli(capsys, ["remote", "token", "revoke", out["id"]])
    assert code == 0 and rstore.AuthStore().authenticate(out["token"]) is None
    code, out3 = run_cli(capsys, ["remote", "token", "revoke", out["id"]])
    assert code == 1 and not out3["ok"]
    code, out4 = run_cli(capsys, ["remote", "revoke-all"])
    assert code == 0 and out4["ok"] and rstore.AuthStore().passphrase_set()     # 口令保留


def test_corrupt_auth_file_fails_closed(tmp_path):
    d = rstore.state_dir()
    d.mkdir(parents=True)
    (d / "auth.json").write_text("{not json", encoding="utf-8")
    st = rstore.AuthStore()
    assert st.authenticate("lbr_p_whatever") is None and st.summary()["corrupt"]
    st.revoke_all()                                         # 「撤销全部访问」把坏文件重建
    assert not rstore.AuthStore().summary()["corrupt"]


# ------------------------------------------------------------------ 计划任务（假 PowerShell）

@pytest.fixture
def fake_ps(monkeypatch):
    calls: list[str] = []
    replies: list[tuple[bool, str]] = []

    def ps(cmd):
        calls.append(cmd)
        return replies.pop(0) if replies else (True, "ok")
    monkeypatch.setattr(rtask, "_ps", ps)
    monkeypatch.setattr(rtask, "supported", lambda: True)
    return calls, replies


def test_enable_registers_logon_task_with_watchdog(capsys, fake_ps):
    calls, _ = fake_ps
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    write_settings(vault, 18071, enabled=False)
    code, out = run_cli(capsys, ["remote", "enable"])
    assert code == 1 and out["code"] == "SKIPPED.DISABLED" and calls == []        # 开关没开不注册
    write_settings(vault, 18071, enabled=True)
    code, out = run_cli(capsys, ["remote", "enable"])
    assert code == 0 and out["ok"], out
    script = calls[-1]
    assert "Register-ScheduledTask -TaskName 'LinkBrainRemote'" in script
    assert "-AtLogOn" in script and "-RepetitionInterval (New-TimeSpan -Minutes 5)" in script
    assert "-MultipleInstances IgnoreNew" in script and "-RunLevel Limited" in script and "-LogonType Interactive" in script
    assert "Start-ScheduledTask -TaskName 'LinkBrainRemote'" in script
    assert "-m link_brain remote serve --vault" in script and "--state-dir" in script
    assert "--settings" not in script                                         # 默认读 vault 里插件的 data.json
    assert re.search(r"pythonw?\.exe", script, re.I)
    assert f"-WorkingDirectory '{ROOT}'" in script


def test_disable_unregisters(capsys, fake_ps):
    calls, replies = fake_ps
    replies.append((True, "ok"))
    code, out = run_cli(capsys, ["remote", "disable"])
    assert code == 0 and out["message"].startswith("已停止并删除")
    assert "Stop-ScheduledTask -TaskName 'LinkBrainRemote'" in calls[-1]
    assert "Unregister-ScheduledTask -TaskName 'LinkBrainRemote' -Confirm:$false" in calls[-1]
    replies.append((True, "none"))
    code, out = run_cli(capsys, ["remote", "disable"])
    assert code == 0 and "本来就没有" in out["message"]


def test_register_failure_goes_to_problems(capsys, fake_ps):
    calls, replies = fake_ps
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    write_settings(vault, 18071, enabled=True)
    replies.append((False, "Access is denied."))
    code, out = run_cli(capsys, ["remote", "enable"])
    assert code == 1 and out["code"] == "PERMANENT.REMOTE_TASK_FAILED" and "command" in out
    rows = [r for r in problems.load() if r.get("step") == "remote"]
    assert rows and rows[0]["code"] == "PERMANENT.REMOTE_TASK_FAILED"
    code, out = run_cli(capsys, ["remote", "enable"])                       # 再点一次成功 → 那条自动解决
    assert code == 0
    assert not [r for r in problems.load() if r.get("step") == "remote"]


def test_non_windows_gives_manual_command(capsys, monkeypatch):
    monkeypatch.setattr(rtask, "supported", lambda: False)
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    write_settings(vault, 18071, enabled=True)
    code, out = run_cli(capsys, ["remote", "enable"])
    assert code == 1 and out["code"] == "SKIPPED.NOT_CONFIGURED"
    assert out["command"].startswith("python -m link_brain remote serve --vault")


def test_status_shapes(capsys, fake_ps):
    calls, replies = fake_ps
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    port = free_port()
    write_settings(vault, port, enabled=False)
    replies.append((True, "none"))
    code, out = run_cli(capsys, ["remote", "status"])
    assert code == 0 and out["state"] == "stopped" and out["message"] == "已停"
    assert out["url"] == "https://lb.example.test/mcp" and out["folders"] == ["@xhs"]
    write_settings(vault, port, enabled=True)
    replies.append((True, "none"))
    code, out = run_cli(capsys, ["remote", "status"])
    assert out["state"] == "error" and "计划任务没注册" in out["message"]
    assert any("还没设口令" in w for w in out["warnings"])
    rstore.write_status({"state": "error", "code": "NEEDS_HUMAN.PORT_IN_USE", "message": f"端口 {port} 被别的程序占着：到设置里换一个端口"})
    replies.append((True, "Ready|2026-10-02T10:00:00|0|pythonw.exe|-m link_brain remote serve"))
    code, out = run_cli(capsys, ["remote", "status"])
    assert out["state"] == "error" and "被别的程序占着" in out["message"] and out["task"]["registered"]


# ------------------------------------------------------------------ serve 本体

def test_serve_disabled_exits_cleanly(tmp_path):
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    write_settings(vault, free_port(), enabled=False)
    assert rserver.serve(vault, None, tmp_path / "st", setup_logging=False) == 0
    st = rstore.read_status(tmp_path / "st")
    assert st["state"] == "stopped" and st["code"] == "SKIPPED.DISABLED"


def test_serve_port_in_use_reports_needs_human(tmp_path):
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    port = free_port()
    write_settings(vault, port, enabled=True)
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        assert rserver.serve(vault, None, tmp_path / "st", setup_logging=False) == 1
    finally:
        blocker.close()
    st = rstore.read_status(tmp_path / "st")
    assert st["state"] == "error" and st["code"] == "NEEDS_HUMAN.PORT_IN_USE"
    rows = [r for r in problems.load() if r.get("step") == "remote"]
    assert rows and rows[0]["code"] == "NEEDS_HUMAN.PORT_IN_USE"


def test_standalone_process_serves_and_stops_itself_when_disabled(tmp_path):
    """服务是独立进程（计划任务 / 手动起），不挂在 Obsidian 下：这里直接起子进程验证它自己能应答、能自己退。"""
    vault = Path(os.environ["LINK_BRAIN_VAULT"])
    make_vault(vault)
    port = free_port()
    settings = write_settings(vault, port, enabled=True)
    sdir = tmp_path / "st"
    token = rstore.AuthStore(sdir).new_personal("独立进程")["token"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-m", "link_brain", "remote", "serve", "--vault", str(vault),
                             "--state-dir", str(sdir)], cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(150):
            if rserver.probe_health(port, 0.5):
                break
            time.sleep(0.2)
        health = rserver.probe_health(port)
        assert health and health["pid"] == proc.pid
        r = httpx.post(f"http://127.0.0.1:{port}/mcp", headers={"Authorization": "Bearer " + token,
                       "Accept": "application/json, text/event-stream"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read", "arguments": {"path": AGENT, "max_chars": 50}}})
        assert r.status_code == 200 and not r.json()["result"]["isError"]
        assert rstore.read_status(sdir)["state"] == "running"
        write_settings(vault, port, enabled=False)          # 设置页关掉开关 → 服务看到后自己退
        assert proc.wait(timeout=20) == 0
        st = rstore.read_status(sdir)
        assert st["state"] == "stopped" and "关了" in st["message"]
        assert (sdir / "server.log").exists()
    finally:
        if proc.poll() is None:
            proc.kill()
