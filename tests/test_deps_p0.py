"""P0 1024（BUGS-1024 根因）：缺依赖说人话 + 解释器只认一处。

- jieba 缺失（sys.modules 置 None 模拟）：切词各处统一抛 deps.MissingDependency（NEEDS_HUMAN.NOT_INSTALLED + 人话），
  不再有的崩成裸 ModuleNotFoundError、有的悄悄退化；MCP search / ask 返回的错误里带码和人话。
- 计划任务 / 后台补评论注册的命令行用 deps.python_exe()：插件 data.json 的 pythonPath > 程序目录 .venv > 当前解释器，绝对路径。
- doctor 缺依赖时照样跑完，列出缺什么。
不起真进程、不注册真计划任务（_ps 换成记账）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from link_brain import deps, storage


@pytest.fixture
def no_jieba(monkeypatch):
    monkeypatch.setitem(sys.modules, "jieba", None)   # import jieba → ImportError


def _assert_missing(exc_info, name="jieba"):
    exc = exc_info.value
    assert isinstance(exc, deps.MissingDependency)
    assert exc.code == "NEEDS_HUMAN.NOT_INSTALLED"
    assert f"缺依赖 {name}" in exc.message and ".venv" in exc.message and f"pip install {name}" in exc.message
    assert "NEEDS_HUMAN.NOT_INSTALLED" in str(exc)


# ------------------------------------------------------------------ deps.require

def test_require_returns_module_and_raises_coded_error(monkeypatch):
    assert deps.require("json") is json
    monkeypatch.setitem(sys.modules, "no_such_pkg_p0", None)
    with pytest.raises(deps.MissingDependency) as ei:
        deps.require("no_such_pkg_p0", "测试")
    assert ei.value.code == "NEEDS_HUMAN.NOT_INSTALLED" and "测试" in ei.value.message


# ------------------------------------------------------------------ jieba 各处一致明确报错

def test_ask_query_terms_reports_missing_jieba(no_jieba):
    from link_brain import ask
    for fn in (ask.query_terms, ask.query_terms_legacy):
        with pytest.raises(deps.MissingDependency) as ei:
            fn("辣椒酱怎么做")
        _assert_missing(ei)
    with pytest.raises(deps.MissingDependency) as ei:
        ask.core_words({"core": "辣椒酱"}, [])
    _assert_missing(ei)


def test_recall_core_feedback_terms_reports_missing_jieba(no_jieba):
    from link_brain import recall_core
    with pytest.raises(deps.MissingDependency) as ei:
        recall_core.feedback_terms([], [{"title": "辣椒酱做法"}], ["辣椒"])
    _assert_missing(ei)


def test_answer_check_tokens_no_silent_fallback(no_jieba):
    from link_brain import answer_check
    with pytest.raises(deps.MissingDependency) as ei:
        answer_check._tokens("味玉汁的做法")
    _assert_missing(ei)


def test_ask_intent_common_word_no_silent_fallback(no_jieba):
    from link_brain import ask_intent
    with pytest.raises(deps.MissingDependency) as ei:
        ask_intent._is_common_word("随便")
    _assert_missing(ei)


def _catalog():
    vault = storage.vault_root()
    (vault / "_archive").mkdir(parents=True, exist_ok=True)
    storage.write_json(vault / "_archive" / "catalog-data.json", {"items": [{
        "id": "xhs-abc12345", "title": "蒜香鱼片怎么做", "url": "https://example.invalid/abc12345",
        "note": "Web/Xiaohongshu/蒜香鱼片怎么做__abc12345.md", "tags": ["菜谱"], "cats": ["美食"],
        "summary": "蒜香鱼片的做法", "date": "2026-09-01",
        "search_fields": {"body": "蒜香鱼片做法：先腌制十分钟，再下锅煎至两面金黄。"}}]})


def _call_tool(monkeypatch, name, arguments):
    from link_brain import mcp_server
    out = []
    monkeypatch.setattr(mcp_server, "_write", out.append)
    mcp_server._POLICY.clear()
    mcp_server._handle_tools_call(1, {"name": name, "arguments": arguments})
    assert len(out) == 1
    result = out[0]["result"]
    return result, json.loads(result["content"][0]["text"])


@pytest.mark.parametrize("name,arguments", [("search", {"query": "蒜香鱼片"}), ("ask", {"question": "蒜香鱼片怎么做"})])
def test_mcp_search_and_ask_report_not_installed(monkeypatch, no_jieba, name, arguments):
    _catalog()
    result, payload = _call_tool(monkeypatch, name, arguments)
    assert result["isError"] is True
    text = json.dumps(payload, ensure_ascii=False)
    assert "NOT_INSTALLED" in text and "缺依赖 jieba" in text
    assert "ModuleNotFoundError" not in text and "ImportError" not in text


# ------------------------------------------------------------------ 解释器：一处配置，注册写绝对路径

def _plugin_data(vault: Path, data: dict) -> None:
    p = vault / ".obsidian" / "plugins" / "link-brain-actions" / "data.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _fake_python(tmp_path, name="py311") -> Path:
    exe = tmp_path / name / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    (exe.parent / "pythonw.exe").write_text("")
    return exe


def test_python_exe_order(tmp_path, monkeypatch):
    vault = storage.vault_root()
    vault.mkdir(parents=True, exist_ok=True)
    # 没配、没 .venv → 当前解释器（绝对路径）
    monkeypatch.setattr(deps, "venv_python", lambda root=None: tmp_path / "no-venv" / "python.exe")
    assert deps.python_exe() == str(Path(sys.executable).absolute())
    # 有 .venv → 它
    venv = _fake_python(tmp_path, "venv")
    monkeypatch.setattr(deps, "venv_python", lambda root=None: venv)
    assert deps.python_exe() == str(venv)
    assert deps.python_exe(windowless=True) == str(venv.with_name("pythonw.exe"))
    # 插件配了 → 配的（优先于 .venv）
    own = _fake_python(tmp_path)
    _plugin_data(vault, {"pythonPath": f' "{own}" '})
    assert deps.python_exe() == str(own)
    # 坏 data.json → 按默认找，不崩
    (vault / ".obsidian" / "plugins" / "link-brain-actions" / "data.json").write_text("{坏", encoding="utf-8")
    assert deps.python_exe() == str(venv)


def test_nightly_registration_uses_configured_python(tmp_path, monkeypatch):
    from link_brain import sync_schedule
    calls = []
    monkeypatch.setattr(sync_schedule, "_ps", lambda cmd: (calls.append(cmd), (True, "ok"))[1])
    vault = tmp_path / "my vault"
    vault.mkdir()
    own = _fake_python(tmp_path)
    _plugin_data(vault, {"pythonPath": str(own)})
    out = sync_schedule.install_nightly("04:00", str(vault), platform="win32")
    assert out["ok"] is True
    assert f"-Execute '{own.with_name('pythonw.exe')}'" in calls[0]
    assert sys.executable not in calls[0] or str(own.parent) in sys.executable


def test_nightly_cron_uses_configured_python(tmp_path):
    from link_brain import sync_schedule
    vault = tmp_path / "v"
    vault.mkdir()
    own = _fake_python(tmp_path)
    _plugin_data(vault, {"pythonPath": str(own)})
    out = sync_schedule.install_nightly("04:00", str(vault), platform="linux")
    assert str(own) in out["cron"]


def test_remote_task_registration_uses_configured_python(tmp_path, monkeypatch):
    from link_brain.remote import task
    calls = []
    monkeypatch.setattr(task, "_ps", lambda cmd: (calls.append(cmd), (True, "ok"))[1])
    monkeypatch.setattr(task, "supported", lambda: True)
    vault = storage.vault_root()
    vault.mkdir(parents=True, exist_ok=True)
    own = _fake_python(tmp_path)
    _plugin_data(vault, {"pythonPath": str(own)})
    out = task.register(str(vault), str(tmp_path / "state"))
    assert out["ok"] is True
    assert f"-Execute '{own.with_name('pythonw.exe')}'" in calls[0]
    assert task.manual_command(str(vault), str(tmp_path / "state")).startswith(f'"{own}"' if " " in str(own) else str(own))


def test_comment_fill_worker_uses_configured_python(tmp_path, monkeypatch):
    from link_brain import comment_fill, procs
    seen = {}
    monkeypatch.setattr(procs, "spawn_detached", lambda argv, **kw: (seen.setdefault("argv", argv), 4321)[1])
    monkeypatch.setattr(comment_fill, "read_status", lambda: {})
    vault = storage.vault_root()
    vault.mkdir(parents=True, exist_ok=True)
    own = _fake_python(tmp_path)
    _plugin_data(vault, {"pythonPath": str(own)})
    out = comment_fill.spawn_worker()
    assert out["started"] is True
    assert seen["argv"][0] == str(own)


# ------------------------------------------------------------------ doctor

def test_doctor_reports_interpreter_and_missing_deps(monkeypatch, capsys):
    from link_brain import doctor
    monkeypatch.setitem(sys.modules, "jieba", None)
    monkeypatch.setitem(sys.modules, "pypinyin", None)
    info = doctor.python_checks()
    assert info["executable"] == sys.executable
    assert info["version"].startswith(".".join(map(str, sys.version_info[:2])))
    by = {d["name"]: d for d in info["deps"]}
    assert by["jieba"]["ok"] is False and "问答" in by["jieba"]["purpose"]
    assert by["pypinyin"]["ok"] is False
    for name in ("httpx", "pyyaml", "rapidocr", "pillow"):
        assert name in by, name
    assert {"jieba", "pypinyin"} <= set(info["missing"])
    assert info["scheduled"]   # 计划任务会用的解释器也报出来


def test_doctor_runs_when_deps_missing(tmp_path):
    """子进程：jieba / pypinyin / httpx / yaml / rapidocr 全导不进来，doctor 照样导入、跑完、列出缺什么。"""
    import os
    import subprocess
    code = ("import sys, argparse\n"
            "for n in ('jieba', 'pypinyin', 'httpx', 'yaml', 'rapidocr'): sys.modules[n] = None\n"
            "from link_brain import doctor\n"
            "sys.exit(doctor.run(argparse.Namespace(obsidian_dir=None, json=True, only=None)))\n")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(storage.repo_root()), env=env,
                          capture_output=True, timeout=120)
    assert proc.returncode in (0, 1), proc.stderr.decode("utf-8", "replace")
    result = json.loads(proc.stdout.decode("utf-8").strip().splitlines()[-1])
    row = next(r for r in result["checks"] if r["id"] == "python")
    assert row["state"] == "error"
    for name in ("jieba", "pypinyin", "httpx", "pyyaml", "rapidocr"):
        assert name in row["message"]
    assert sys.executable in row["message"] or "python" in row["message"].lower()
    assert "pip install" in row["next_step"] and ".venv" in row["next_step"]
    deps_rows = {d["name"]: d for d in result["python"]["deps"]}
    assert deps_rows["jieba"]["ok"] is False and deps_rows["pillow"]["ok"] is True
