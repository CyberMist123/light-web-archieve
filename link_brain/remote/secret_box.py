"""口令的「可取回副本」：Windows DPAPI（当前用户）加密后存本机，供设置页「复制口令」用。

- 只在 Windows 上有：CryptProtectData / CryptUnprotectData（ctypes，不装任何包），密钥绑定当前 Windows 用户，
  拷到别的机器 / 别的用户下解不开。
- 文件：状态目录（默认 ~/.link-brain/remote）下的 passphrase.dpapi，内容是 base64 的密文；不进 data.json、不进仓库。
- 验证口令仍然只走 auth.json 里的 scrypt 哈希；这份副本丢了 / 坏了只影响「复制口令」，不影响授权。
- 非 Windows：不存副本（supported() = False），复制口令会如实说「这台电脑不支持，请重设」。
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

FILE_NAME = "passphrase.dpapi"
_ENTROPY = b"link-brain-remote-passphrase"


def supported() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data: bytes) -> _Blob:
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _call(fn, data: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        src, ent, out = _blob(data), _blob(_ENTROPY), _Blob()
        ok = getattr(crypt32, fn)(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out))  # UI_FORBIDDEN
        if not ok:
            raise OSError(f"{fn} 失败（{ctypes.GetLastError()}）")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)

    def protect(data: bytes) -> bytes:
        return _call("CryptProtectData", data)

    def unprotect(data: bytes) -> bytes:
        return _call("CryptUnprotectData", data)
else:  # pragma: no cover - 非 Windows
    def protect(data: bytes) -> bytes:
        raise OSError("只有 Windows 支持")

    def unprotect(data: bytes) -> bytes:
        raise OSError("只有 Windows 支持")


def path(directory: Path) -> Path:
    return Path(directory) / FILE_NAME


def save(directory: Path, passphrase: str) -> bool:
    """存副本；不支持 / 失败 → 删掉旧副本（免得留着和新口令对不上的旧值）并返回 False。"""
    p = path(directory)
    if not supported():
        p.unlink(missing_ok=True)
        return False
    try:
        blob = base64.b64encode(protect(passphrase.encode("utf-8"))).decode("ascii")
        tmp = p.with_suffix(".tmp")
        tmp.write_text(blob, encoding="ascii")
        os.replace(tmp, p)
        return True
    except OSError:
        p.unlink(missing_ok=True)
        return False


def load(directory: Path) -> str | None:
    try:
        return unprotect(base64.b64decode(path(directory).read_text(encoding="ascii"))).decode("utf-8")
    except (OSError, ValueError):
        return None


def clear(directory: Path) -> None:
    path(directory).unlink(missing_ok=True)
