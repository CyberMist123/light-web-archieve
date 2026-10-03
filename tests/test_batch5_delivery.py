"""第 5 批 B1（单插件交付的 Python 侧）：夜跑进包、计划任务注册、vault 解耦、组件目录可配、读取组件下载。

夜跑用假子命令（`python -c …`）替换步骤表：不起任何真 link_brain 子命令、不联网、不碰小红书组件。
计划任务只验生成的 PowerShell / cron / launchd 文本，`_ps` 一律换成假的，不真注册。
"""

from __future__ import annotations

import hashlib
import http.server
import json
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from link_brain import accounts, cli, nightly, problems, procs, reader_install, storage, sync_schedule
from link_brain.adapters import xiaohongshu as xhs
from link_brain.nightly import Nightly, Step

PY = sys.executable


def _py(code: str) -> list[str]:
    return [PY, "-c", code]


def _open(step_name: str) -> list[dict]:
    return [r for r in problems.load(include_resolved=False) if r["step"] == "nightly." + nightly.step_slug(step_name)]


def _all(step_name: str) -> list[dict]:
    return [r for r in problems.load(include_resolved=True) if r["step"] == "nightly." + nightly.step_slug(step_name)]


@pytest.fixture
def job_factory(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir(exist_ok=True)
    sleeps: list[float] = []

    def make(steps, **kw):
        kw.setdefault("log_path", tmp_path / "nightly.log")
        kw.setdefault("sleep", lambda s: sleeps.append(s))
        job = Nightly(steps=steps, workdir=tmp_path, **kw)
        job.sleeps = sleeps
        return job
    # 默认没有正在跑的同步
    monkeypatch.setattr(Nightly, "running_sync", lambda self: None)
    return make


# ---------------------------------------------------------------- vault 解耦


def test_vault_root_env_then_user_config_then_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "from-env"))
    assert storage.vault_root() == (tmp_path / "from-env").resolve()

    monkeypatch.delenv("LINK_BRAIN_VAULT")
    assert storage.vault_root() == storage.repo_root() / "vault"  # 没配置：旧默认，作者本机不变

    cfg = storage.user_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"vault": str(tmp_path / "from-config")}), "utf-8")
    assert storage.vault_root() == (tmp_path / "from-config").resolve()

    cfg.write_text("{坏的 json", "utf-8")  # 读不动 = 没配置（fail-open）
    assert storage.vault_root() == storage.repo_root() / "vault"


def test_console_script_entry_point_declared():
    text = (storage.repo_root() / "pyproject.toml").read_text("utf-8")
    assert 'link-brain = "link_brain.cli:main"' in text


# ---------------------------------------------------------------- 组件目录可配


def test_tool_dir_env_config_default(tmp_path, monkeypatch):
    monkeypatch.delenv("LINK_BRAIN_XHS_TOOL_DIR", raising=False)
    assert accounts.tool_dir() == Path.home() / ".xiaohongshu-mcp"
    cfg = storage.user_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"xhs_tool_dir": str(tmp_path / "cfg-tools")}), "utf-8")
    assert accounts.tool_dir() == tmp_path / "cfg-tools"
    monkeypatch.setenv("LINK_BRAIN_XHS_TOOL_DIR", str(tmp_path / "env-tools"))
    assert accounts.tool_dir() == tmp_path / "env-tools"


def test_executable_and_relatedfile_search_bin_dir_first(tmp_path, monkeypatch):
    monkeypatch.delenv("LINK_BRAIN_XHS_EXE", raising=False)
    monkeypatch.setenv("LINK_BRAIN_XHS_TOOL_DIR", str(tmp_path / "tools"))
    monkeypatch.setattr(xhs, "RELATEDFILE_EXE", "")
    (tmp_path / "tools").mkdir()
    for d in (accounts.bin_dir(), tmp_path / "tools"):
        d.mkdir(parents=True, exist_ok=True)
        (d / "link-brain-reader.exe").write_bytes(b"x")
        (d / "relatedfile.exe").write_bytes(b"x")
    assert Path(accounts.executable("LINK_BRAIN_XHS_EXE", ("link-brain-reader.exe",))) == accounts.bin_dir() / "link-brain-reader.exe"
    assert Path(xhs.relatedfile_exe()) == accounts.bin_dir() / "relatedfile.exe"
    (accounts.bin_dir() / "relatedfile.exe").unlink()
    assert Path(xhs.relatedfile_exe()) == tmp_path / "tools" / "relatedfile.exe"
    monkeypatch.setattr(xhs, "RELATEDFILE_EXE", str(tmp_path / "explicit.exe"))
    assert xhs.relatedfile_exe() == str(tmp_path / "explicit.exe")


def test_profile_legacy_dir_follows_tool_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("XHS_PROFILE_DIR", raising=False)
    monkeypatch.setenv("LINK_BRAIN_XHS_TOOL_DIR", str(tmp_path / "tools"))
    assert accounts.profile_dir() == accounts.home() / "xhs-profile"
    legacy = tmp_path / "tools" / "data" / "xhs" / "momo-profile"
    legacy.mkdir(parents=True)
    assert accounts.profile_dir() == legacy


# ---------------------------------------------------------------- 读取组件下载


def _zip(path: Path, members: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reader_install_from_file_url(tmp_path):
    pkg = tmp_path / "reader-win64.zip"
    sha = _zip(pkg, {"link-brain-reader.exe": b"reader", "relatedfile.exe": b"rf", "LICENSE": b"Apache-2.0"})
    out = reader_install.install(pkg.as_uri(), sha)
    assert out["ok"] is True, out
    assert (accounts.bin_dir() / "link-brain-reader.exe").read_bytes() == b"reader"
    assert (accounts.bin_dir() / "relatedfile.exe").read_bytes() == b"rf"
    assert not list((storage.link_brain_home() / "downloads").glob("*"))  # 下载的包装完删掉
    assert not list(storage.link_brain_home().glob("reader-*"))           # 临时解压目录也删掉


def test_reader_install_checksum_mismatch_installs_nothing(tmp_path):
    pkg = tmp_path / "reader.zip"
    _zip(pkg, {"link-brain-reader.exe": b"reader"})
    out = reader_install.install(pkg.as_uri(), "0" * 64)
    assert out["ok"] is False and out["code"] == "PERMANENT.CHECKSUM_MISMATCH"
    assert not (accounts.bin_dir() / "link-brain-reader.exe").exists()


def test_reader_install_requires_sha_and_url(tmp_path):
    assert reader_install.install(None, "a" * 64)["code"] == "SKIPPED.NOT_CONFIGURED"
    assert reader_install.install((tmp_path / "x.zip").as_uri(), None)["code"] == "SKIPPED.NOT_CONFIGURED"
    assert reader_install.install((tmp_path / "x.zip").as_uri(), "xyz")["code"] == "SKIPPED.NOT_CONFIGURED"


def test_reader_install_rejects_zip_slip_and_empty_package(tmp_path):
    bad = tmp_path / "bad.zip"
    sha = _zip(bad, {"../evil.exe": b"x", "link-brain-reader.exe": b"r"})
    out = reader_install.install(bad.as_uri(), sha)
    assert out["ok"] is False and out["code"] == "PERMANENT.BAD_PACKAGE"
    assert not (tmp_path / "evil.exe").exists() and not (storage.link_brain_home() / "evil.exe").exists()

    empty = tmp_path / "docs.zip"
    sha = _zip(empty, {"README.md": b"hi"})
    out = reader_install.install(empty.as_uri(), sha)
    assert out["ok"] is False and out["code"] == "PERMANENT.BAD_PACKAGE"


def test_reader_install_download_failure_is_transient(tmp_path):
    out = reader_install.install((tmp_path / "missing.zip").as_uri(), "a" * 64)
    assert out["ok"] is False and out["code"] == "TRANSIENT.NETWORK"


def test_reader_install_over_local_http_and_cli_shape(tmp_path, capsys):
    root = tmp_path / "srv"
    root.mkdir()
    sha = _zip(root / "pkg.zip", {"link-brain-reader.exe": b"reader-http"})

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/pkg.zip"
        rc = cli.main(["reader", "install", "--url", url, "--sha256", sha])
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert rc == 0 and out["ok"] is True
        assert (accounts.bin_dir() / "link-brain-reader.exe").read_bytes() == b"reader-http"

        rc = cli.main(["reader", "install", "--url", url.replace("pkg.zip", "nope.zip"), "--sha256", sha])
        cap = capsys.readouterr()
        out = json.loads(cap.out.strip().splitlines()[-1])
        assert rc == 1 and out["ok"] is False and out["code"] == "TRANSIENT.NETWORK"
        assert "下载失败" in cap.err.strip().splitlines()[-1]
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- 计划任务（只验生成的命令）


def test_install_script_has_required_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("LINK_BRAIN_NIGHTLY_TASK", raising=False)
    calls = []
    monkeypatch.setattr(sync_schedule, "_ps", lambda cmd: (calls.append(cmd), (True, "ok"))[1])
    vault = tmp_path / "my vault"
    vault.mkdir()
    out = sync_schedule.install_nightly("22:30", str(vault), platform="win32")
    assert out["ok"] is True and out["task"] == "LinkBrainNightly" and out["time"] == "22:30"
    script = calls[0]
    assert "Register-ScheduledTask -TaskName 'LinkBrainNightly'" in script
    assert "-Daily -At ([datetime]::Today.AddHours(22).AddMinutes(30))" in script
    assert "-StartWhenAvailable" in script                      # 错过就尽快补跑
    assert "-ExecutionTimeLimit (New-TimeSpan -Hours 7)" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "-LogonType Interactive -RunLevel Limited" in script  # 不要管理员
    assert "XhsFavSync" not in script
    # 动作：当前解释器（有 pythonw 用 pythonw）-m link_brain nightly --vault "<带空格的路径>"
    assert f"-Execute '{sync_schedule.nightly_python()}'" in script
    assert f'-m link_brain nightly --vault "{vault.resolve()}"' in script
    assert "obsidian" not in script.lower().split("-description")[0]  # 动作不依赖 Obsidian


def test_install_quotes_single_quotes_for_powershell(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sync_schedule, "_ps", lambda cmd: (calls.append(cmd), (True, "ok"))[1])
    vault = tmp_path / "it's"
    vault.mkdir()
    assert sync_schedule.install_nightly("04:00", str(vault), platform="win32")["ok"]
    assert "it''s" in calls[0]


def test_install_refuses_legacy_task_name_and_bad_input(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_schedule, "_ps", lambda cmd: pytest.fail("不该调 PowerShell"))
    monkeypatch.setenv("LINK_BRAIN_NIGHTLY_TASK", "XhsFavSync")
    assert sync_schedule.install_nightly("04:00", str(tmp_path), platform="win32")["ok"] is False
    assert sync_schedule.uninstall_nightly(platform="win32")["ok"] is False
    monkeypatch.delenv("LINK_BRAIN_NIGHTLY_TASK")
    assert "时间格式不对" in sync_schedule.install_nightly("25:00", str(tmp_path), platform="win32")["message"]
    assert "收藏库不存在" in sync_schedule.install_nightly("04:00", str(tmp_path / "nope"), platform="win32")["message"]


def test_install_on_mac_linux_prints_cron_and_launchd(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_schedule, "_ps", lambda cmd: pytest.fail("不该调 PowerShell"))
    out = sync_schedule.install_nightly("4:15AM", str(tmp_path), platform="linux")
    assert out["ok"] is False and out["code"] == "SKIPPED.NOT_CONFIGURED"
    assert out["cron"].startswith("15 4 * * * ") and "-m link_brain nightly --vault" in out["cron"]
    assert "<key>Hour</key><integer>4</integer>" in out["launchd"]
    assert "<key>Minute</key><integer>15</integer>" in out["launchd"]


def test_uninstall_and_cli_dispatch(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(sync_schedule, "_ps", lambda cmd: (calls.append(cmd), (True, "ok"))[1])
    monkeypatch.setattr(sys, "platform", "win32")
    rc = cli.main(["sync-schedule", "--uninstall"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and out["ok"] and "Unregister-ScheduledTask -TaskName 'LinkBrainNightly'" in calls[-1]
    assert "Stop-ScheduledTask" not in calls[-1]  # 正在跑的那一趟不停在半路
    (tmp_path / "vault").mkdir(exist_ok=True)
    rc = cli.main(["sync-schedule", "--install", "--at", "03:05"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and out["vault"] == str(storage.vault_root())
    assert "AddHours(3).AddMinutes(5)" in calls[-1]


# ---------------------------------------------------------------- 夜跑


def test_dry_run_prints_plan_and_runs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(nightly.subprocess, "Popen", lambda *a, **k: pytest.fail("dry-run 不许起子进程"))
    rc = cli.main(["nightly", "--dry-run"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and [s["name"] for s in out["steps"]][:2] == ["sync-favorites", "catalog"]
    assert out["steps"][0]["account"] is True and out["steps"][0]["timeout_min"] == 170
    assert out["steps"][-2]["step"] == "nightly.catalog-final"
    assert out["budget_min"] == nightly.BUDGET_MIN


def test_step_slug_matches_old_script():
    assert nightly.step_slug("attachments --all") == "attachments-all"
    assert nightly.step_slug("catalog（收尾）") == "catalog-final"
    assert nightly.step_slug("vision --refine") == "vision-refine"


def test_timeout_kills_tree_but_spares_reader_and_moves_on(job_factory, monkeypatch):
    seen = {}
    real = procs.kill_tree

    def spy(pid, exclude=procs.READER_IMAGE_PREFIXES):
        seen["exclude"] = tuple(exclude)
        return real(pid, exclude)
    monkeypatch.setattr(nightly.procs, "kill_tree", spy)
    code = ("import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
            "print(c.pid, flush=True); time.sleep(60)")
    job = job_factory([Step("slow", [], 0.04, argv=_py(code), reserve_min=0),
                       Step("after", [], 1, argv=_py("print('after ran')"), reserve_min=0)])
    out = job.run()
    log = job.log_path.read_text("utf-8")
    grandchild = int(next(ln for ln in log.splitlines() if ln.split("  ")[-1].strip().isdigit()).split("  ")[-1])
    assert procs.wait_gone(grandchild, 5), "超时后孙进程也要被结束"
    assert "link-brain-reader" in seen["exclude"]
    assert "after ran" in log and nightly.END_MARK in log
    assert [r["code"] for r in _open("slow")] == ["TRANSIENT.STEP_TIMEOUT"]
    assert out["exit"] == 1


def test_exit5_skips_later_account_steps(job_factory):
    job = job_factory([Step("sync-favorites", [], 1, account=True, argv=_py("raise SystemExit(5)"), reserve_min=0),
                       Step("attachments --all", [], 1, account=True, argv=_py("print('should not run')"), reserve_min=0),
                       Step("catalog", [], 1, argv=_py("print('offline ran')"), reserve_min=0)])
    out = job.run()
    log = job.log_path.read_text("utf-8")
    assert "should not run" not in log and "offline ran" in log
    assert "[attachments --all] 跳过（碰号）" in log
    assert out["exit"] == 5
    assert job.sleeps == []  # exit 5 不重试


def test_sync_exit1_retries_once_and_resolves(job_factory, tmp_path):
    counter = tmp_path / "count.txt"
    code = (f"import pathlib;p=pathlib.Path(r'{counter}');n=int(p.read_text() if p.exists() else 0)+1;"
            "p.write_text(str(n));raise SystemExit(1 if n==1 else 0)")
    job = job_factory([Step("sync-favorites", [], 1, account=True, argv=_py(code), reserve_min=0)])
    out = job.run()
    assert counter.read_text() == "2"
    assert job.sleeps == [nightly.SYNC_RETRY_WAIT_MIN * 60]
    assert _open("sync-favorites") == [] and _all("sync-favorites")  # 第一次登记过，重试成功后已解决
    assert out["exit"] == 0 and out["problems"] == []
    assert "再试一次成功" in job.log_path.read_text("utf-8")


def test_sync_exit1_no_retry_when_budget_short(job_factory):
    job = job_factory([Step("sync-favorites", [], 1, account=True, argv=_py("raise SystemExit(1)"), reserve_min=0)],
                      budget_min=30)
    out = job.run()
    assert job.sleeps == [] and out["exit"] == 1
    assert "剩的时间不够再试一次" in job.log_path.read_text("utf-8")


def test_exit6_registers_account_busy(job_factory):
    job = job_factory([Step("sync-favorites", [], 1, account=True, argv=_py("raise SystemExit(6)"), reserve_min=0)])
    out = job.run()
    assert [r["code"] for r in _open("sync-favorites")] == ["TRANSIENT.ACCOUNT_BUSY"]
    assert job.sleeps == [] and out["exit"] == 1


def test_budget_exhausted_skips_and_registers(job_factory):
    job = job_factory([Step("catalog", [], 1, argv=_py("print('ran')"), reserve_min=0),
                       Step("embed", [], 1, argv=_py("print('embed ran')"), reserve_min=100)], budget_min=50)
    out = job.run()
    log = job.log_path.read_text("utf-8")
    assert "embed ran" not in log and "[embed] 跳过：今晚总时间用完了" in log
    assert [r["code"] for r in _open("embed")] == ["TRANSIENT.STEP_TIMEOUT"]
    assert out["exit"] == 1


def test_unfinished_last_night_registered(job_factory):
    job = job_factory([Step("catalog", [], 1, argv=_py("pass"), reserve_min=0)])
    job.log_path.write_text(f"2026-10-02 04:00:00  {nightly.START_MARK}\r\n2026-10-02 05:00:00  === embed 开始 ===\r\n",
                            "utf-8")
    job.run()
    rows = _open("run")
    assert [r["code"] for r in rows] == ["TRANSIENT.INTERRUPTED"]
    assert "embed 开始" in rows[0]["reason"]
    # 这一晚走完了：下一晚不再报
    assert job.unfinished_last_night() is None


def test_success_resolves_previous_problem(job_factory):
    problems.report("nightly.catalog", "TRANSIENT.STEP_CRASHED", "昨晚 catalog 出错")
    assert _open("catalog")
    job = job_factory([Step("catalog", [], 1, argv=_py("print('ok')"), reserve_min=0)])
    out = job.run()
    assert _open("catalog") == [] and out["exit"] == 0


def test_crash_and_usage_error_classified(job_factory):
    job = job_factory([Step("enrich --pending", [], 1, argv=_py("raise RuntimeError('boom')"), reserve_min=0),
                       Step("videos --transcribe", [], 1,
                            argv=_py("import sys; print('x: error: unrecognized arguments: --y', file=sys.stderr); sys.exit(2)"),
                            reserve_min=0)])
    job.run()
    assert [r["code"] for r in _open("enrich --pending")] == ["TRANSIENT.STEP_CRASHED"]
    assert [r["code"] for r in _open("videos --transcribe")] == ["PERMANENT.STEP_ARGS"]


def test_running_sync_skips_night_and_flags_stuck(job_factory, monkeypatch):
    job = job_factory([Step("catalog", [], 1, argv=_py("print('should not run')"), reserve_min=0)])
    monkeypatch.setattr(Nightly, "running_sync", lambda self: {"pid": 4242, "idle_min": 300})
    out = job.run()
    assert out["ran"] is False and out["exit"] == 0
    assert "should not run" not in job.log_path.read_text("utf-8")
    assert [r["code"] for r in _open("run")] == ["NEEDS_HUMAN.SYNC_STUCK"]


def test_running_sync_detection_reads_status_and_guards_pid_reuse(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    from link_brain import sync_state
    monkeypatch.setattr(sync_state, "path", lambda: tmp_path / "sync-status.json")
    updated = datetime.now().astimezone() - timedelta(minutes=10)
    storage.write_json(sync_state.path(), {"state": "running", "pid": 4242, "updated_at": updated.isoformat()})
    job = Nightly(steps=[], log_path=tmp_path / "n.log", workdir=tmp_path)
    table = [{"pid": 4242, "ppid": 1, "name": "python.exe", "created": updated.timestamp() - 60}]
    monkeypatch.setattr(nightly.procs, "process_table", lambda: table)
    got = job.running_sync()
    assert got["pid"] == 4242 and 9 < got["idle_min"] < 11
    table[0]["created"] = updated.timestamp() + 600  # 比状态还晚起：pid 被复用了
    assert job.running_sync() is None
    table[0].update(created=updated.timestamp() - 60, name="notepad.exe")
    assert job.running_sync() is None


def test_audit_missing_gives_exit2(job_factory):
    payload = json.dumps({"missing": 3, "unconfirmed": 1, "unprobed": 0}, indent=2).replace("\n", "\\n")
    job = job_factory([Step(nightly.AUDIT_STEP, [], 1, argv=_py(f"print('{payload}')"), reserve_min=0, quiet_stdout=True)])
    out = job.run()
    log = job.log_path.read_text("utf-8")
    assert out["exit"] == 2 and "未下载 2 个文件，另有 1 条附件线索待确认" in log
    assert '"missing"' not in log  # quiet_stdout：大 JSON 不进日志


def test_refine_keys_from_config_cmd_only_for_that_step(job_factory, monkeypatch, tmp_path):
    monkeypatch.delenv("LWA_GEMINI_KEYS", raising=False)
    monkeypatch.setattr(nightly.Nightly, "_keys_env_name", lambda self: "LWA_GEMINI_KEYS")
    cfg = storage.user_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    keycmd = f'"{PY}" -c "print(\'k-one,k-two\')"'
    cfg.write_text(json.dumps({"gemini_keys_cmd": keycmd}), "utf-8")
    show = "import os; print('KEYS=' + str(len([k for k in os.environ.get('LWA_GEMINI_KEYS','').split(',') if k])))"
    job = job_factory([Step("catalog", [], 1, argv=_py(show), reserve_min=0),
                       Step(nightly.REFINE_STEP, [], 1, argv=_py(show), reserve_min=0)])
    job.run()
    log = job.log_path.read_text("utf-8")
    assert "免费 key 可用 2 个" in log
    assert log.count("KEYS=0") == 1 and log.count("KEYS=2") == 1  # 只注入精细识图那一步
    assert "k-one" not in log and "k-two" not in log               # key 不进日志


def test_refine_keys_cmd_timeout_registers_and_runs_anyway(job_factory, monkeypatch):
    monkeypatch.delenv("LWA_GEMINI_KEYS", raising=False)
    monkeypatch.setattr(nightly.Nightly, "_keys_env_name", lambda self: "LWA_GEMINI_KEYS")
    monkeypatch.setenv("LWA_GEMINI_KEYS_CMD", f'"{PY}" -c "import time; time.sleep(30)"')
    job = job_factory([Step(nightly.REFINE_STEP, [], 1, argv=_py("print('refine ran')"), reserve_min=0)],
                      secret_timeout_sec=1)
    job.run()
    assert "refine ran" in job.log_path.read_text("utf-8")
    # 记在单独的一步：精细识图没 key 照样成功，不能顺手把「取 key 失败」标成已解决
    assert [r["code"] for r in _open(nightly.KEYS_STEP)] == ["TRANSIENT.SECRET_TIMEOUT"]


def test_children_get_pinned_vault_and_log_is_live(job_factory, tmp_path):
    job = job_factory([Step("catalog", [], 1, argv=_py("import os; print('VAULT=' + os.environ['LINK_BRAIN_VAULT'])"),
                            reserve_min=0)])
    job.run()
    assert f"VAULT={storage.vault_root()}" in job.log_path.read_text("utf-8")


def test_second_concurrent_nightly_exits_6(monkeypatch, capsys, tmp_path):
    import subprocess
    monkeypatch.setattr(Nightly, "run", lambda self: pytest.fail("锁被占着时不该跑"))
    holder = subprocess.Popen(
        [PY, "-c", "import sys,time; from link_brain import storage\n"
                   "with storage.file_lock('nightly', wait_s=0, owner='nightly'):\n"
                   "    print('held', flush=True); time.sleep(30)"],
        cwd=str(storage.repo_root()), stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        rc = cli.main(["nightly", "--log", str(tmp_path / "n.log")])
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert rc == 6 and out["ok"] is False and out["ran"] is False
    finally:
        holder.kill()
        holder.wait(10)


# —— 第 5 批 B2（插件侧接线）配合的两处 Python 改动 ——

def test_reader_status_says_whether_release_is_configured(monkeypatch):
    """插件引导靠 release_configured 决定「下载读取组件」能不能点；测试版发布地址为空 = False。"""
    monkeypatch.setattr(reader_install, "RELEASE_URL", "")
    monkeypatch.setattr(reader_install, "RELEASE_SHA256", "")
    assert reader_install.status()["release_configured"] is False
    monkeypatch.setattr(reader_install, "RELEASE_URL", "https://example.invalid/reader.zip")
    assert reader_install.status()["release_configured"] is False, "没有校验和不算配好"
    monkeypatch.setattr(reader_install, "RELEASE_SHA256", "a" * 64)
    assert reader_install.status()["release_configured"] is True


def test_doctor_plugin_files_match_plugin_dir_and_dataview_required(tmp_path):
    from link_brain import doctor
    plugin_dir = Path(__file__).resolve().parent.parent / "obsidian-plugins" / "link-brain-actions"
    for name in doctor.PLUGIN_FILES:
        assert (plugin_dir / name).is_file(), f"doctor 要求的 {name} 不在插件目录里"
    assert "media-nav.js" in doctor.PLUGIN_FILES and "onboarding-ui.js" in doctor.PLUGIN_FILES
    assert "setup-ui.js" in doctor.PLUGIN_FILES, "第 7 批「开始」页向导"
    rows = {r["id"]: r for r in doctor.diagnose(obsidian_dir=str(tmp_path / ".obsidian"), only="local")["checks"]}
    assert rows["dataview"]["state"] == "missing" and rows["dataview"]["optional"] is False, "Dataview 首版是必装依赖"
    assert rows["obsidian"]["message"] == "未安装"
