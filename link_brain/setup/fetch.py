"""下载（可续传、边下边报进度）+ sha256 校验 + 安全解压。给 `setup install` 用。

- 下载先写 `<文件>.part`：中断（Ctrl+C / 插件结束进程树）后再装，按 `.part` 已有的字节数发 Range 续上；
  服务器不认 Range（回 200）就从头下。下完整才校验，校验过了才改名成正式文件名——正式文件名在 = 完整且校验过。
- file:// 也支持（测试 / 离线包），同样能续。
- 解压：拒绝绝对路径 / `..` / 盘符（防 zip-slip）；没打 UTF-8 标记的成员名按 GBK 还原（CapsWriter 的包里
  中文文件名是 GBK 编码，按 zip 默认的 cp437 解会变乱码）。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from .common import SetupError

CHUNK = 1 << 20
CONNECT_TIMEOUT_S = 20
READ_TIMEOUT_S = 120
REPORT_EVERY = 4 << 20  # 进度事件至少隔 4 MB 发一次，别把插件淹了

Progress = Callable[[int, int | None], None]


def _file_source(url: str) -> Path:
    parts = urlsplit(url)
    src = Path(url2pathname(unquote(parts.path)))
    if parts.netloc and parts.netloc not in ("", "localhost"):
        src = Path(f"//{parts.netloc}{url2pathname(unquote(parts.path))}")
    return src


def download(url: str, dest: Path, *, expected_size: int | None = None, on_progress: Progress | None = None,
             max_bytes: int | None = None) -> Path:
    """下到 dest（先写 dest.part，能续）。返回 dest。不校验——校验由调用方在改名前做（见 fetch_verified）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if expected_size and have > expected_size:
        part.unlink()
        have = 0
    scheme = urlsplit(url).scheme
    last = [0]

    def report(done: int, total: int | None, force: bool = False) -> None:
        if on_progress and (force or done - last[0] >= REPORT_EVERY):
            last[0] = done
            on_progress(done, total)

    try:
        if scheme == "file":
            src = _file_source(url)
            total = src.stat().st_size
            if have > total:
                have = 0
            with open(src, "rb") as fin, open(part, "ab" if have else "wb") as fout:
                fin.seek(have)
                done = have
                report(done, total, True)
                for chunk in iter(lambda: fin.read(CHUNK), b""):
                    fout.write(chunk)
                    done += len(chunk)
                    report(done, total)
            report(done, total, True)
        elif scheme in ("http", "https"):
            import httpx
            headers = {"Range": f"bytes={have}-"} if have else {}
            timeout = httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
            with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=timeout) as resp:
                if resp.status_code == 416 and expected_size and have == expected_size:
                    report(have, expected_size, True)  # 已经下全了，只差改名
                elif resp.status_code >= 400:
                    raise SetupError("TRANSIENT.NETWORK", f"下载失败：HTTP {resp.status_code}（{_short(url)}）")
                else:
                    resumed = resp.status_code == 206 and have > 0
                    if not resumed:
                        have = 0
                    length = resp.headers.get("content-length")
                    total = (have + int(length)) if length and length.isdigit() else expected_size
                    done = have
                    report(done, total, True)
                    with open(part, "ab" if resumed else "wb") as fout:
                        for chunk in resp.iter_bytes(CHUNK):
                            fout.write(chunk)
                            done += len(chunk)
                            if max_bytes and done > max_bytes:
                                raise SetupError("PERMANENT.BAD_PACKAGE", f"下载的文件比预期大得多，停了：{_short(url)}")
                            report(done, total)
                    report(done, total, True)
        else:
            raise SetupError("SKIPPED.NOT_CONFIGURED", f"不认识的下载地址：{url}（只支持 https / http / file）")
    except SetupError:
        raise
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:  # ENOSPC
            raise SetupError("PERMANENT.DISK_FULL", "磁盘满了，下载停在半截（已下的部分留着，腾出空间后再装会接着下）") from exc
        raise SetupError("TRANSIENT.NETWORK", f"下载中断：{type(exc).__name__}: {exc}（已下的部分留着，再装会接着下）") from exc
    except Exception as exc:  # noqa: BLE001 - httpx 各种网络错都归「下载失败」，.part 留着续
        raise SetupError("TRANSIENT.NETWORK", f"下载中断：{type(exc).__name__}: {exc}（已下的部分留着，再装会接着下）") from exc
    return part


def _short(url: str) -> str:
    return PurePosixPath(unquote(urlsplit(url).path)).name or url


def sha256_of(path: Path, on_progress: Progress | None = None) -> str:
    h = hashlib.sha256()
    total = path.stat().st_size
    done, last = 0, 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
            done += len(chunk)
            if on_progress and (done - last >= REPORT_EVERY * 4 or done == total):
                last = done
                on_progress(done, total)
    return h.hexdigest()


def fetch_verified(url: str, dest: Path, *, sha256: str | None, size: int | None,
                   on_download: Progress | None = None, on_verify: Progress | None = None) -> dict:
    """下载 + 校验，过了才把 .part 改名成 dest。dest 已在（上回下好校验过）就只再核一遍校验和。

    sha256 有就严格比对；没有（官方没给）就只核大小并把算出来的 sha256 记在返回里。返回 {path, sha256, verified}。"""
    want = (sha256 or "").strip().lower()
    if dest.exists():
        got = sha256_of(dest, on_verify)
        if (want and got == want) or (not want and (not size or dest.stat().st_size == size)):
            return {"path": dest, "sha256": got, "verified": bool(want), "reused": True}
        dest.unlink()  # 坏的 / 不是这一版：删了重下
    part = download(url, dest, expected_size=size, on_progress=on_download,
                    max_bytes=(size * 2 + (64 << 20)) if size else None)
    if size and part.stat().st_size != size:
        got_size = part.stat().st_size
        part.unlink()
        raise SetupError("PERMANENT.CHECKSUM_MISMATCH",
                         f"下载的大小不对（{got_size} 字节，应为 {size}），已删掉重来：{_short(url)}")
    got = sha256_of(part, on_verify)
    if want and got != want:
        part.unlink()
        raise SetupError("PERMANENT.CHECKSUM_MISMATCH",
                         f"校验和对不上（下载到的是 {got[:12]}…，应为 {want[:12]}…），已删掉，没安装：{_short(url)}")
    os.replace(part, dest)
    return {"path": dest, "sha256": got, "verified": bool(want), "reused": False}


# --------------------------------------------------------------------------
# 解压
# --------------------------------------------------------------------------

def member_name(info: zipfile.ZipInfo) -> str:
    """zip 成员名：有 UTF-8 标记照用；没有的（Windows 资源管理器 / 7-Zip 打的中文名）按 GBK 还原，还原不了照旧。"""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def safe_rel(name: str) -> PurePosixPath | None:
    norm = name.replace("\\", "/")
    if not norm or norm.endswith("/"):
        return None
    p = PurePosixPath(norm)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts) or ":" in norm:
        raise SetupError("PERMANENT.BAD_PACKAGE", f"包里有不安全的路径：{name}")
    return p


def unzip(pkg: Path, target: Path, *, strip: str = "", on_progress: Progress | None = None) -> int:
    """解到 target。strip：去掉成员名开头这一层目录（如 'CapsWriter-Offline/'），不在这层下的成员照原样放。
    返回解出的文件数。"""
    try:
        zf = zipfile.ZipFile(pkg)
    except (zipfile.BadZipFile, OSError) as exc:
        raise SetupError("PERMANENT.BAD_PACKAGE", f"不是能解开的 zip：{pkg.name}（{type(exc).__name__}）") from exc
    count = 0
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        total = sum(i.file_size for i in infos)
        done = last = 0
        for info in infos:
            name = member_name(info)
            if strip and name.replace("\\", "/").startswith(strip):
                name = name.replace("\\", "/")[len(strip):]
            rel = safe_rel(name)
            if rel is None:
                continue
            out = target.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
            except (zipfile.BadZipFile, OSError, EOFError) as exc:
                if getattr(exc, "errno", None) == 28:
                    raise SetupError("PERMANENT.DISK_FULL", "磁盘满了，解压没做完（已清掉半截）") from exc
                raise SetupError("PERMANENT.BAD_PACKAGE", f"解压失败：{name}（{type(exc).__name__}: {exc}）") from exc
            count += 1
            done += info.file_size
            if on_progress and (done - last >= REPORT_EVERY * 8 or done == total):
                last = done
                on_progress(done, total)
    return count
