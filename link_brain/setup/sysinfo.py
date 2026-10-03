"""只读量本机：目录占用（跟着目录联接走）、Python 包占用、进程内存 / 程序路径、端口通不通。不改任何东西。"""
from __future__ import annotations

import os
import re
import socket
from importlib import metadata
from pathlib import Path
from typing import Any


def dir_bytes(path: str | os.PathLike, *, follow_links: bool = True, limit_files: int = 200_000) -> int:
    """目录里所有文件的字节数。目录联接 / 符号链接默认跟进（CapsWriter 的模型常是联接到别的盘），同一目标只算一次。"""
    total, seen, count = 0, set(), 0
    stack = [Path(path)]
    while stack:
        cur = stack.pop()
        try:
            real = os.path.realpath(cur)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=follow_links):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=follow_links):
                            total += entry.stat(follow_symlinks=follow_links).st_size
                            count += 1
                            if count >= limit_files:
                                return total
                    except OSError:
                        continue
        except OSError:
            continue
    return total


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_names(dist_name: str) -> list[str]:
    """一个已装包的直接依赖名（跳过只在 extra 里的）。"""
    try:
        reqs = metadata.requires(dist_name) or []
    except metadata.PackageNotFoundError:
        return []
    out = []
    for r in reqs:
        if "extra ==" in r.replace("'", '"').replace('extra=="', 'extra == "'):
            continue
        m = _REQ_NAME.match(r)
        if m:
            out.append(m.group(1))
    return out


def dist_bytes(names: list[str], *, exclude: set[str] | None = None, transitive: bool = True) -> tuple[int, list[str]]:
    """这些包（含传递依赖）装在磁盘上的字节数；返回 (字节, 没装的包名)。按 RECORD 列的文件逐个 stat。"""
    exclude = {_norm(x) for x in (exclude or set())}
    seen: set[str] = set()
    missing: list[str] = []
    total = 0
    queue = list(names)
    while queue:
        name = queue.pop()
        key = _norm(name)
        if key in seen or key in exclude:
            continue
        seen.add(key)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        for f in dist.files or []:
            try:
                total += os.path.getsize(dist.locate_file(f))
            except OSError:
                continue
        if transitive:
            queue.extend(requirement_names(name))
    return total, missing


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


# --------------------------------------------------------------------------
# 进程（Windows：ctypes 只读查询；别的平台没有就返回空）
# --------------------------------------------------------------------------

def processes_named(name: str) -> list[dict[str, Any]]:
    """[{pid, exe, peak_ws, ws, private}]：按映像名找进程，只读（不结束、不注入）。"""
    try:
        from .. import procs
        table = procs.process_table()
    except Exception:  # noqa: BLE001 - 列不出进程就当没有
        return []
    low = name.lower()
    out = []
    for p in table:
        if (p.get("name") or "").lower() != low:
            continue
        info = {"pid": int(p["pid"]), "exe": None, "peak_ws": None, "ws": None, "private": None}
        info.update(_win_proc_info(int(p["pid"])) if os.name == "nt" else {})
        out.append(info)
    return out


def _win_proc_info(pid: int) -> dict[str, Any]:
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    out: dict[str, Any] = {}
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ（GetProcessMemoryInfo 要 QUERY(_LIMITED)_INFORMATION 即可）
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid) or k32.OpenProcess(0x1000, False, pid)
    if not h:
        return out
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            out["exe"] = buf.value
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        try:
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            fn = psapi.GetProcessMemoryInfo
        except (OSError, AttributeError):
            fn = getattr(k32, "K32GetProcessMemoryInfo", None)
        if fn is not None:
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if fn(h, ctypes.byref(pmc), pmc.cb):
                out.update(peak_ws=int(pmc.PeakWorkingSetSize), ws=int(pmc.WorkingSetSize),
                           private=int(pmc.PrivateUsage))
    finally:
        k32.CloseHandle(h)
    return out
