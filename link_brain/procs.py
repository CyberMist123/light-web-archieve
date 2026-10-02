"""进程：杀树（带排除）与「脱离进程树」拉起（CONVENTIONS §6.2 / §6.3）。

为什么有这个模块（0929 事故）：插件超时 / 换号打断时用 `taskkill /T` 杀 Python 的整棵进程树，
读取服务 link-brain-reader 正好是那个 Python 拉起的子进程，连同它的浏览器一起被杀，号被弄成游客。

两道保险：
1. `spawn_detached`：读取服务经短命中转 `cmd /c start "" /b <exe> …` 拉起，中转进程马上退出，
   读取服务的父进程是一个已经不存在的 pid，不再是任何 Python 的子孙。
2. `kill_tree`：只沿 ParentProcessId 往下找；映像名 `link-brain-reader*` 的进程和它下面的整棵子树
   （chrome* / msedge* 浏览器就在这里）一律跳过；其余逐个结束。禁止直接 `taskkill /T`。

插件 main.js 的 `killTree` 用同一套选择规则（`selectKillPids`），两边改一处改两处。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

# 映像名前缀（不区分大小写）：命中的进程和它的整棵子树都不杀
READER_IMAGE_PREFIXES = ("link-brain-reader",)
# 读取服务名下的浏览器：父链里有读取服务就不杀（已被「整棵子树跳过」覆盖，单列出来便于对照约定）
BROWSER_IMAGE_PREFIXES = ("chrome", "msedge")

Proc = dict[str, Any]  # {pid, ppid, name, created(秒，可为 None)}


def _matches(name: str, prefixes: Iterable[str]) -> bool:
    low = (name or "").lower()
    return any(low.startswith(p.lower()) for p in prefixes)


def select_kill_pids(table: Sequence[Proc], root: int, exclude: Iterable[str] = READER_IMAGE_PREFIXES) -> list[int]:
    """纯函数：给一张进程表和根 pid，返回要结束的 pid（叶子在前，根在最后）。

    - 父子关系按 ppid；子进程的创建时间早于父进程时不认（pid 被复用，不是真的子进程）。
    - 映像名命中 exclude 前缀的：它本身和它下面的整棵子树都跳过（比约定「跳过它和父链里含它的
      chrome*/msedge*」更保守：读取服务名下任何进程都不碰）。
    - 根本身命中 exclude：什么都不杀。
    """
    exclude = tuple(exclude or ())
    by_pid = {int(p["pid"]): p for p in table}
    children: dict[int, list[Proc]] = {}
    for p in table:
        pid, ppid = int(p["pid"]), int(p.get("ppid") or 0)
        if pid == ppid or ppid not in by_pid:
            continue
        parent = by_pid[ppid]
        pc, cc = parent.get("created"), p.get("created")
        if pc is not None and cc is not None and cc < pc:
            continue  # pid 复用：这个「父进程」比孩子还年轻
        children.setdefault(ppid, []).append(p)
    root = int(root)
    root_proc = by_pid.get(root)
    if root_proc is not None and _matches(root_proc.get("name", ""), exclude):
        return []
    order: list[int] = [root]
    seen = {root}
    queue = [root]
    while queue:
        cur = queue.pop(0)
        for child in children.get(cur, []):
            cpid = int(child["pid"])
            if cpid in seen:
                continue
            seen.add(cpid)
            if _matches(child.get("name", ""), exclude):
                continue  # 读取服务：它和它下面的浏览器整棵不碰
            order.append(cpid)
            queue.append(cpid)
    return list(reversed(order))


# --------------------------------------------------------------------------
# 进程表
# --------------------------------------------------------------------------


def _win_process_table() -> list[Proc]:
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4

    def created(pid: int) -> float | None:
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
                return None
            ticks = (c.hi << 32) | c.lo
            return ticks / 1e7 - 11644473600.0
        finally:
            k32.CloseHandle(h)

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot 失败")
    out: list[Proc] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            out.append({"pid": pid, "ppid": int(entry.th32ParentProcessID), "name": entry.szExeFile,
                        "created": created(pid) if pid else None})
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _posix_process_table() -> list[Proc]:
    res = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=15)
    out: list[Proc] = []
    for line in res.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            out.append({"pid": int(parts[0]), "ppid": int(parts[1]), "name": os.path.basename(parts[2]),
                        "created": None})
    return out


def process_table() -> list[Proc]:
    """当前全部进程：[{pid, ppid, name, created}]。"""
    return _win_process_table() if os.name == "nt" else _posix_process_table()


def children_of(pid: int, table: Sequence[Proc] | None = None) -> list[Proc]:
    table = process_table() if table is None else table
    return [p for p in table if int(p.get("ppid") or 0) == int(pid) and int(p["pid"]) != int(pid)]


def _terminate(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if not h:
            return False
        try:
            return bool(k32.TerminateProcess(h, 1))
        finally:
            k32.CloseHandle(h)
    import signal
    try:
        os.kill(int(pid), signal.SIGKILL)
        return True
    except OSError:
        return False


def kill_tree(pid: int, exclude: Iterable[str] = READER_IMAGE_PREFIXES) -> list[int]:
    """结束 pid 和它的子孙（跳过读取服务及其浏览器）。返回实际结束掉的 pid 列表。

    枚举进程表失败时只结束 pid 本身——宁可漏杀几个子进程，也不冒险整棵连读取服务一起带走。"""
    try:
        targets = select_kill_pids(process_table(), pid, exclude)
    except Exception as exc:  # noqa: BLE001
        print(f"[procs] 枚举进程失败（{type(exc).__name__}: {exc}），只结束 {pid} 本身", file=sys.stderr)
        targets = [int(pid)]
    killed = [p for p in targets if _terminate(p)]
    return killed


# --------------------------------------------------------------------------
# 脱离进程树拉起
# --------------------------------------------------------------------------

_CMD_SPECIAL = re.compile(r'[\s&|<>^(),;=!]')


def _cmd_quote(arg: str) -> str:
    """给 cmd.exe 的 start 用：有空白或 cmd 特殊字符就整段加双引号（引号内 & | < > ^ 都按字面）。"""
    arg = str(arg)
    if '"' in arg:
        raise ValueError(f"参数里不能有双引号：{arg!r}")
    return f'"{arg}"' if (not arg or _CMD_SPECIAL.search(arg)) else arg


def detached_command_line(argv: Sequence[str]) -> str:
    """`cmd.exe /d /c start "" /b <argv…>`：start /b 不开新窗口，cmd 立刻退出。"""
    if not argv:
        raise ValueError("argv 不能为空")
    return 'cmd.exe /d /c start "" /b ' + " ".join(_cmd_quote(a) for a in argv)


def spawn_detached(argv: Sequence[str], *, cwd: str | os.PathLike | None = None, env: dict | None = None,
                   log_path: str | os.PathLike | None = None, wait_s: float = 15.0) -> int | None:
    """拉起一个长驻进程，并保证它不是调用方（任何 Python）的子孙。返回新进程 pid（找不到时 None）。

    Windows：经 `cmd /c start "" /b` 中转，等中转的 cmd 退出后返回；新进程的父 pid 是那个已退出的 cmd。
    其它平台：`sh -c '"$0" "$@" &'`，sh 退出后新进程被 init 收养。
    stdout / stderr 追加进 log_path（没给就丢掉）。参数、环境变量、工作目录原样透传，不做任何改写。
    """
    argv = [str(a) for a in argv]
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL  # noqa: SIM115 - Popen 后立刻关
    try:
        if os.name == "nt":
            # 中转 cmd 用隐藏控制台（CREATE_NO_WINDOW），不用 DETACHED_PROCESS：没有控制台时 start /b 拉起的
            # 进程拿不到 cmd 的标准句柄，读取服务的日志就写不进 reader.log 了（实测）。新进程组：Ctrl+C 不串过来。
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            shim = subprocess.Popen(detached_command_line(argv), cwd=cwd, env=env, stdout=out, stderr=out,
                                    stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
        else:
            shim = subprocess.Popen(["/bin/sh", "-c", '"$0" "$@" &', *argv], cwd=cwd, env=env, stdout=out,
                                    stderr=out, stdin=subprocess.DEVNULL, close_fds=True,
                                    start_new_session=True)
    finally:
        if log_path:
            out.close()
    try:
        shim.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        print(f"[procs] 中转进程 {wait_s:.0f} 秒没退出（pid={shim.pid}）", file=sys.stderr)
    try:
        table = process_table()
    except Exception:  # noqa: BLE001
        return None
    name = Path(argv[0]).name.lower()
    kids = [p for p in children_of(shim.pid, table)
            if os.name != "nt" or (p.get("name") or "").lower() not in ("conhost.exe",)]
    exact = [p for p in kids if (p.get("name") or "").lower() == name]
    pick = (exact or kids)
    return int(pick[0]["pid"]) if pick else None


def parent_alive(pid: int, table: Sequence[Proc] | None = None) -> dict[str, Any] | None:
    """pid 的父进程还在不在：在 → {pid, name}；父进程已退出（或 pid 不存在）→ None。只读，诊断用。"""
    table = process_table() if table is None else table
    by_pid = {int(p["pid"]): p for p in table}
    me = by_pid.get(int(pid))
    if not me:
        return None
    parent = by_pid.get(int(me.get("ppid") or 0))
    if not parent:
        return None
    pc, mc = parent.get("created"), me.get("created")
    if pc is not None and mc is not None and mc < pc:
        return None  # 父 pid 已被别的进程复用
    return {"pid": int(parent["pid"]), "name": parent.get("name")}


def wait_gone(pid: int, timeout: float = 5.0) -> bool:
    """等 pid 退出（测试 / 收尾用）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(int(p["pid"]) == int(pid) for p in process_table()):
            return True
        time.sleep(0.1)
    return False
