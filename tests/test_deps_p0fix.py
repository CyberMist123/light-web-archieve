"""1024 第一波返修（复审 python 中1 / 中2）：配置的 Python 路径找不到要如实报、相对路径按程序目录解析；
缺第三方包的码不再和「未安装读取组件」撞车。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from link_brain import deps, problems, storage


def _plugin_data(vault: Path, data: dict) -> None:
    p = vault / ".obsidian" / "plugins" / "link-brain-actions" / "data.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _vault():
    v = storage.vault_root()
    v.mkdir(parents=True, exist_ok=True)
    return v


def test_relative_python_path_resolves_against_program_dir(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    exe = repo / ".venv" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(deps, "_repo_root", lambda: repo)
    _plugin_data(_vault(), {"pythonPath": ".venv\Scripts\python.exe" if os.name == "nt" else ".venv/Scripts/python.exe"})
    monkeypatch.chdir(tmp_path)  # 当前目录不是程序目录（命令行从别处跑 sync-schedule）
    assert Path(deps.python_exe()) == exe, "修前：按当前目录解析，写进计划任务的是 <当前目录>\.venv\…"


def test_missing_configured_python_raises(tmp_path):
    _plugin_data(_vault(), {"pythonPath": str(tmp_path / "nope" / "python.exe")})
    with pytest.raises(deps.PythonNotFound) as ei:
        deps.python_exe()
    assert "找不到" in str(ei.value) and "nope" in str(ei.value)


def test_nightly_registration_refuses_missing_python(tmp_path, monkeypatch):
    from link_brain import sync_schedule
    calls = []
    monkeypatch.setattr(sync_schedule, "_ps", lambda cmd: (calls.append(cmd), (True, "ok"))[1])
    vault = tmp_path / "v"
    vault.mkdir()
    _plugin_data(vault, {"pythonPath": str(tmp_path / "nope" / "python.exe")})
    out = sync_schedule.install_nightly("04:00", str(vault), platform="win32")
    assert out["ok"] is False and "找不到" in out["message"]
    assert not calls, "修前：把不存在的 exe 注册进计划任务，报「已开启」，每晚都起不来"


def test_remote_registration_refuses_missing_python(tmp_path, monkeypatch):
    from link_brain.remote import task
    calls = []
    monkeypatch.setattr(task, "_ps", lambda cmd: (calls.append(cmd), (True, "ok"))[1])
    monkeypatch.setattr(task, "supported", lambda: True)
    vault = _vault()
    _plugin_data(vault, {"pythonPath": str(tmp_path / "nope" / "python.exe")})
    out = task.register(str(vault), str(tmp_path / "state"))
    assert out["ok"] is False and "找不到" in out["message"]
    assert not calls


def test_doctor_says_configured_python_missing(tmp_path):
    from link_brain import doctor
    _plugin_data(_vault(), {"pythonPath": str(tmp_path / "nope" / "python.exe")})
    info = doctor.python_checks()
    assert info["scheduled"] == "" and "找不到" in info.get("scheduled_error", "")


def test_missing_dependency_code_is_not_an_account_code():
    exc = deps.MissingDependency("jieba", "切词")
    sub = problems.subcode(exc.code)
    assert sub not in problems.ACCOUNT_CODES, "修前：NOT_INSTALLED = 未安装读取组件，登记会让所有用号的任务停车"
    assert exc.code in problems.STATE_REGISTRY
    row = problems.report_blocked("ask", exc.code, exc.message)
    assert row["step"] == "ask" and problems.category(row) != "account"


def test_understand_question_does_not_swallow_missing_dependency(monkeypatch):
    """python 低3：缺 jieba 时问题理解不能悄悄退成 {"goal":"ask"}，要明确报出来。"""
    from link_brain import ask, ask_intent

    def boom(*a, **k):
        raise deps.MissingDependency("jieba", "切词")

    monkeypatch.setattr(ask_intent, "understand", boom)
    with pytest.raises(deps.MissingDependency):
        ask.understand_question("辣椒酱怎么做", [], llm_out={}, skills_list=[])


def test_cli_ask_missing_dependency_prints_json(monkeypatch, capsys):
    """python 低4：CLI ask 缺依赖时 stdout 给结果 JSON（带码和人话），不是 traceback。"""
    from types import SimpleNamespace
    from link_brain import ask

    def boom(*a, **k):
        raise deps.MissingDependency("jieba", "切词")

    monkeypatch.setattr(ask, "answer", boom)
    code = ask.run(SimpleNamespace(question="辣椒酱", include=None))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code != 0 and out["status"] == "error" and out["code"] == deps.CODE and "缺依赖 jieba" in out["markdown"]
