"""第 0 批：杀树排除读取服务（§6.2）+ 读取服务脱离 Python 进程树（§6.3，0929 事故根治）。

不起真读取服务：进程树用假表测选择规则；真进程只用 python 写的 sleep 小脚本当假 exe。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from link_brain import accounts, enrich, procs

REPO = Path(__file__).resolve().parents[1]
WIN = os.name == "nt"


# --------------------------------------------------------------------------
# 选择规则（纯函数，假进程树）
# --------------------------------------------------------------------------


def P(pid, ppid, name, created=None):
    return {"pid": pid, "ppid": ppid, "name": name, "created": created}


TREE = [
    P(1, 0, "obsidian.exe", 1.0),
    P(10, 1, "python.exe", 10.0),            # 插件起的 python（要杀的根）
    P(11, 10, "python.exe", 11.0),           # enrich 子进程
    P(12, 11, "ocr.exe", 12.0),
    P(20, 10, "link-brain-reader.exe", 20.0),  # 旧拉起方式下读取服务挂在 python 下
    P(21, 20, "chrome.exe", 21.0),
    P(22, 21, "chrome.exe", 22.0),           # chrome 渲染进程（父链里有读取服务）
    P(23, 20, "msedge.exe", 23.0),
    P(30, 10, "chrome.exe", 30.0),           # python 自己起的浏览器（relatedfile 之类）：照杀
    P(40, 10, "cmd.exe", 40.0),
    P(41, 40, "Link-Brain-Reader-x64.exe", 41.0),  # 大小写 / 后缀变体也认
    P(42, 41, "chrome.exe", 42.0),
    P(99, 5, "chrome.exe", 99.0),            # 无关进程
]


def test_kill_selection_skips_reader_and_its_browsers():
    picked = procs.select_kill_pids(TREE, 10)
    assert set(picked) == {10, 11, 12, 30, 40}
    assert picked[-1] == 10, "根最后杀"
    assert picked.index(12) < picked.index(11), "叶子先杀"
    for pid in (20, 21, 22, 23, 41, 42, 99, 1):
        assert pid not in picked


def test_kill_selection_root_is_reader_kills_nothing():
    assert procs.select_kill_pids(TREE, 20) == []
    assert procs.select_kill_pids(TREE, 41) == []


def test_kill_selection_ignores_reused_parent_pid():
    # pid 50 是新进程，复用了已死父进程的 pid；60 比 50 还老，不是它的孩子
    table = [P(50, 1, "python.exe", 500.0), P(60, 50, "important.exe", 100.0), P(61, 50, "child.exe", 501.0)]
    assert set(procs.select_kill_pids(table, 50)) == {50, 61}


def test_kill_selection_unknown_root_still_returns_root_only():
    assert procs.select_kill_pids([], 1234) == [1234]


def test_kill_selection_custom_exclude():
    table = [P(1, 0, "python.exe"), P(2, 1, "fake-reader.exe"), P(3, 2, "chrome.exe"), P(4, 1, "x.exe")]
    assert set(procs.select_kill_pids(table, 1, exclude=("fake-reader",))) == {1, 4}


def test_js_and_python_share_the_same_rule(tmp_path):
    """插件 main.js 的 selectKillPids 和这里同一套规则：同一张假表、同一个答案。"""
    table = TREE + [P(50, 1, "python.exe", 500.0), P(60, 50, "important.exe", 100.0)]
    table_file = tmp_path / "table.json"  # 走文件：命令行里带读取服务的名字会被 conftest 护栏拦下
    table_file.write_text(json.dumps(table), "utf-8")
    node = subprocess.run(["node", "-e", r"""
const fs=require('fs'),vm=require('vm');
const ctx={module:{exports:{}},require:n=>n==='obsidian'?{Plugin:class{},PluginSettingTab:class{},Modal:class{}}:n==='child_process'?{spawn(){throw Error('no spawn in test')}}:require(n)};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8')+';module.exports.selectKillPids=selectKillPids;',ctx);
const table=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
process.stdout.write(JSON.stringify([10,20,41,50].map(r=>ctx.module.exports.selectKillPids(table,r))));
""", str(table_file)], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert node.returncode == 0, node.stderr
    js = json.loads(node.stdout)
    assert js == [procs.select_kill_pids(table, r) for r in (10, 20, 41, 50)]


# --------------------------------------------------------------------------
# cmd 中转的命令行
# --------------------------------------------------------------------------


def test_detached_command_line_quotes_specials_and_keeps_args():
    line = procs.detached_command_line([r"C:\Program Files\lb\link-brain-reader.exe", "-port", "127.0.0.1:18061"])
    assert line == r'cmd.exe /d /c start "" /b "C:\Program Files\lb\link-brain-reader.exe" -port 127.0.0.1:18061'
    assert procs.detached_command_line(["a&b", "x"]).endswith('"a&b" x')
    with pytest.raises(ValueError):
        procs.detached_command_line(['bad"quote'])


# --------------------------------------------------------------------------
# 真进程：假 exe（python sleep 脚本）
# --------------------------------------------------------------------------

LAUNCHER = r"""
import os, sys, time
sys.path.insert(0, sys.argv[1])
from link_brain import procs
pid = procs.spawn_detached([sys.executable, "-c", "import time; time.sleep(60)"], cwd=sys.argv[2],
                           env={**os.environ, "LB_FAKE_READER": "1"}, log_path=os.path.join(sys.argv[2], "fake.log"))
print(pid, flush=True)
time.sleep(float(sys.argv[3]))
"""


def _alive(pid):
    return any(p["pid"] == pid for p in procs.process_table())


@pytest.mark.skipif(not WIN, reason="Windows 进程树语义")
def test_detached_child_survives_parent_kill_tree_and_parent_exit(tmp_path):
    parent = subprocess.Popen([sys.executable, "-c", LAUNCHER, str(REPO), str(tmp_path), "30"],
                              stdout=subprocess.PIPE, text=True)
    fake = None
    try:
        line = parent.stdout.readline().strip()
        assert line.isdigit(), f"拉起方没报 pid：{line!r}"
        fake = int(line)
        table = procs.process_table()
        me = next(p for p in table if p["pid"] == fake)
        assert me["ppid"] != parent.pid, "假读取服务不应挂在 python 下"
        assert procs.parent_alive(fake, table) is None, "中转 cmd 应已退出"
        # 父 python 的整棵树里没有它
        assert fake not in procs.select_kill_pids(table, parent.pid)
        # 真杀父 python 的树（不带任何排除）：假读取服务照样活着
        killed = procs.kill_tree(parent.pid, exclude=())
        assert parent.pid in killed and fake not in killed
        parent.wait(timeout=10)
        time.sleep(0.5)
        assert _alive(fake), "父进程树被杀后假读取服务应还在"
    finally:
        if parent.poll() is None:
            parent.kill()
        if fake:
            procs._terminate(fake)
            procs.wait_gone(fake)


@pytest.mark.skipif(not WIN, reason="Windows 进程树语义")
def test_detached_child_keeps_env_cwd_args_and_log(tmp_path):
    script = tmp_path / "fake_reader.py"
    script.write_text("import os, sys, time\n"
                      "print('up', os.environ.get('XHS_PROFILE_DIR'), os.getcwd(), sys.argv[1:], flush=True)\n"
                      "time.sleep(30)\n", encoding="utf-8")
    log = tmp_path / "reader.log"
    pid = procs.spawn_detached([sys.executable, str(script), "-port", "127.0.0.1:18999"], cwd=tmp_path,
                               env={**os.environ, "XHS_PROFILE_DIR": str(tmp_path / "prof")}, log_path=log)
    try:
        assert pid and _alive(pid)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and "up" not in log.read_text("utf-8", errors="replace"):
            time.sleep(0.1)
        text = log.read_text("utf-8", errors="replace")
        assert str(tmp_path / "prof") in text and str(tmp_path) in text
        assert "['-port', '127.0.0.1:18999']" in text
        assert procs.parent_alive(pid) is None
    finally:
        procs._terminate(pid)
        procs.wait_gone(pid)


@pytest.mark.skipif(not WIN, reason="Windows 进程树语义")
def test_kill_tree_live_skips_excluded_image_subtree(tmp_path):
    """真进程树：python 根 → 「读取服务」(按名字排除) → 它的孩子；根 → 普通孩子。只杀根和普通孩子。"""
    code = r"""
import subprocess, sys, time
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
excl = subprocess.Popen([sys.executable, "-c", "import subprocess,sys,time; g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(g.pid, flush=True); time.sleep(60)"], stdout=subprocess.PIPE, text=True)
grand = excl.stdout.readline().strip()
print(kid.pid, excl.pid, grand, flush=True)
time.sleep(60)
"""
    root = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    pids = []
    try:
        kid, excl, grand = (int(x) for x in root.stdout.readline().split())
        pids = [kid, excl, grand]
        real = procs.process_table
        # 把「excl」那个 python 的映像名改成读取服务的名字（真进程，只是表里换个名）
        def renamed():
            return [{**p, "name": "link-brain-reader.exe"} if p["pid"] == excl else p for p in real()]
        procs.process_table = renamed
        try:
            killed = procs.kill_tree(root.pid)
        finally:
            procs.process_table = real
        assert set(killed) == {root.pid, kid}
        root.wait(timeout=10)
        assert procs.wait_gone(kid)
        assert _alive(excl) and _alive(grand), "读取服务和它的子进程（浏览器）不许被带走"
    finally:
        if root.poll() is None:
            root.kill()
        for pid in pids:
            procs._terminate(pid)


def test_enrich_kill_tree_goes_through_procs(monkeypatch):
    seen = []
    monkeypatch.setattr(procs, "kill_tree", lambda pid, exclude=procs.READER_IMAGE_PREFIXES: seen.append(pid) or [pid])
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        enrich.kill_tree(proc)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert seen == [proc.pid]


def test_no_taskkill_tree_left_in_code():
    """§6.2：禁止直接 taskkill /T（Python 和插件都算）。"""
    hits = []
    for root in (REPO / "link_brain", REPO / "obsidian-plugins"):
        for f in root.rglob("*"):
            if f.suffix in (".py", ".js") and f.is_file():
                text = f.read_text("utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    # 只认真正的调用：'taskkill' 和 '/T' 两个字面参数出现在同一行（注释里提到不算）
                    if re.search(r"""['"]taskkill(\.exe)?['"]""", line, re.I) and re.search(r"""['"]/T['"]""", line):
                        hits.append(f"{f.relative_to(REPO)}:{i}")
    assert hits == []


# --------------------------------------------------------------------------
# ensure_reader：只改拉起方式；健康探测和单例守卫不变
# --------------------------------------------------------------------------


class _Api:
    """假读取服务：前 n 次 /login/session 连不上，之后应答。"""

    def __init__(self, down_for: int):
        self.calls = []
        self.down_for = down_for

    def __call__(self, method, route, *, timeout=45, body=None):
        self.calls.append((method, route, timeout))
        if len(self.calls) <= self.down_for:
            raise accounts.ReaderError("DISCONNECTED")
        return {"state": "idle"}


def _fake_exe(tmp_path, monkeypatch):
    exe = tmp_path / "fake-lbr.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("LINK_BRAIN_XHS_EXE", str(exe))
    return exe


def test_ensure_reader_running_service_is_not_spawned_again(monkeypatch, tmp_path):
    _fake_exe(tmp_path, monkeypatch)
    api = _Api(down_for=0)
    monkeypatch.setattr(accounts, "api", api)
    spawned = []
    monkeypatch.setattr(procs, "spawn_detached", lambda *a, **k: spawned.append((a, k)))
    assert accounts.ensure_reader() == {"state": "idle"}
    assert spawned == [] and api.calls == [("GET", "/api/v1/login/session", 5)]


def test_ensure_reader_spawns_detached_with_unchanged_args_env_cwd(monkeypatch, tmp_path):
    exe = _fake_exe(tmp_path, monkeypatch)
    monkeypatch.setenv("XHS_PROFILE_DIR", str(tmp_path / "profile"))
    api = _Api(down_for=2)
    monkeypatch.setattr(accounts, "api", api)
    monkeypatch.setattr(accounts.time, "sleep", lambda s: None)
    spawned = []
    monkeypatch.setattr(procs, "spawn_detached", lambda argv, **k: spawned.append((list(argv), k)) or 4242)
    popen = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: popen.append(a))  # 不许再直接 Popen 读取服务
    assert accounts.ensure_reader() == {"state": "idle"}
    assert popen == []
    assert len(spawned) == 1
    argv, kw = spawned[0]
    assert argv == [str(exe), "-port", "127.0.0.1:18061"]
    assert Path(kw["cwd"]) == accounts.home()
    assert kw["env"]["XHS_PROFILE_DIR"] == str(tmp_path / "profile")
    assert Path(kw["log_path"]) == accounts.home() / "reader.log"
    # 探测：先 5 秒探一次，拉起后每秒 3 秒超时轮询直到应答
    assert api.calls[0] == ("GET", "/api/v1/login/session", 5)
    assert api.calls[1:] == [("GET", "/api/v1/login/session", 3)] * 2


def test_ensure_reader_custom_port_and_remote_and_missing(monkeypatch, tmp_path):
    _fake_exe(tmp_path, monkeypatch)
    monkeypatch.setattr(accounts, "api", _Api(down_for=1))
    monkeypatch.setattr(accounts.time, "sleep", lambda s: None)
    spawned = []
    monkeypatch.setattr(procs, "spawn_detached", lambda argv, **k: spawned.append(list(argv)))
    monkeypatch.setenv("LINK_BRAIN_XHS_ENDPOINT", "http://127.0.0.1:18999/mcp")
    accounts.ensure_reader()
    assert spawned[-1][1:] == ["-port", "127.0.0.1:18999"]
    # 远程地址不代管
    monkeypatch.setattr(accounts, "api", _Api(down_for=99))
    monkeypatch.setenv("LINK_BRAIN_XHS_ENDPOINT", "http://10.0.0.5:18061/mcp")
    with pytest.raises(accounts.ReaderError) as exc:
        accounts.ensure_reader()
    assert exc.value.code == "DISCONNECTED" and len(spawned) == 1
    # 没装
    monkeypatch.setenv("LINK_BRAIN_XHS_ENDPOINT", "http://127.0.0.1:18061/mcp")
    monkeypatch.setenv("LINK_BRAIN_XHS_EXE", str(tmp_path / "none.exe"))
    with pytest.raises(accounts.ReaderError) as exc:
        accounts.ensure_reader()
    assert exc.value.code == "NOT_INSTALLED" and len(spawned) == 1


def test_ensure_reader_gives_up_after_wait(monkeypatch, tmp_path):
    _fake_exe(tmp_path, monkeypatch)
    monkeypatch.setattr(accounts, "api", _Api(down_for=10_000))
    monkeypatch.setattr(procs, "spawn_detached", lambda argv, **k: None)
    clock = iter(range(0, 10_000, 5))
    monkeypatch.setattr(accounts.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(accounts.time, "sleep", lambda s: None)
    with pytest.raises(accounts.ReaderError) as exc:
        accounts.ensure_reader(wait=20)
    assert exc.value.code == "DISCONNECTED" and "reader.log" in exc.value.detail
