"""读取组件下载（第 5 批，Python 侧）：`python -m link_brain reader install --url <发布包> --sha256 <hex>`。

读取组件 = link-brain-reader（读收藏 / 评论 / 附件的本机服务）+ relatedfile（游客浏览器探附件，可选）。
以后由 GitHub Release 发预编译件，插件里「下载读取组件」调这条命令。发布地址还没定：留 RELEASE_URL /
RELEASE_SHA256 两个常量（空 = 必须用参数给）。**没有 sha256 一律不装。**

流程：下载到 `~/.link-brain/downloads/`（http(s) 或 file://）→ 校验 sha256 → 是 zip 就解压到临时目录
（拒绝绝对路径 / `..` / 盘符，防 zip-slip），不是 zip 就当单个 exe → 逐个挪进 `~/.link-brain/bin/`
（`accounts.bin_dir()`，找组件时第一个看的目录）。读取服务正在跑、exe 被占着时如实报「先停掉读取服务」。

输出（CONVENTIONS §1）：stdout 最后一行 JSON `{ok, code, message, installed, bin_dir, sha256}`，失败时 stderr 最后一行是原因。
故障码：下载失败 TRANSIENT.NETWORK · 校验和不对 PERMANENT.CHECKSUM_MISMATCH · 包里没有组件 / 解不开 PERMANENT.BAD_PACKAGE ·
文件被占用 TRANSIENT.SERVICE_BUSY · 没给地址 / 校验和 SKIPPED.NOT_CONFIGURED。不登记问题记录（这是用户点的操作，结果当场告诉他）。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

RELEASE_URL = ""      # 发布后填：读取组件发布包的下载地址
RELEASE_SHA256 = ""   # 发布后填：这个包的 sha256
KNOWN_NAMES = ("link-brain-reader.exe", "link-brain-reader", "relatedfile.exe", "relatedfile")
DOWNLOAD_TIMEOUT_S = 600
MAX_BYTES = 512 * 1024 * 1024


class InstallError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _home() -> Path:
    from . import storage
    return storage.link_brain_home()


def _bin_dir() -> Path:
    from . import accounts
    return accounts.bin_dir()


def download(url: str, dest: Path) -> Path:
    """http(s) 用 httpx 流式下载；file:// 直接复制（测试 / 离线包用）。先写 .part 再改名。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    parts = urlsplit(url)
    try:
        if parts.scheme == "file":
            src = Path(url2pathname(unquote(parts.path)))
            if parts.netloc and parts.netloc not in ("", "localhost"):
                src = Path(f"//{parts.netloc}{url2pathname(unquote(parts.path))}")
            shutil.copyfile(src, part)
        elif parts.scheme in ("http", "https"):
            import httpx
            total = 0
            with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(DOWNLOAD_TIMEOUT_S, connect=20)) as resp:
                if resp.status_code >= 400:
                    raise InstallError("TRANSIENT.NETWORK", f"下载失败：HTTP {resp.status_code}")
                with open(part, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise InstallError("PERMANENT.BAD_PACKAGE", "下载的文件太大，不像读取组件")
                        fh.write(chunk)
        else:
            raise InstallError("SKIPPED.NOT_CONFIGURED", f"不认识的下载地址：{url}（只支持 https / http / file）")
        os.replace(part, dest)
    except InstallError:
        _unlink(part)
        raise
    except Exception as exc:  # noqa: BLE001 - 网络 / 磁盘各种错都归「下载失败」
        _unlink(part)
        raise InstallError("TRANSIENT.NETWORK", f"下载失败：{type(exc).__name__}: {exc}") from exc
    return dest


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_member(name: str) -> PurePosixPath | None:
    """zip 成员名 → 相对路径；绝对路径、盘符、`..` 一律拒（None）。目录项返回 None。"""
    norm = name.replace("\\", "/")
    if not norm or norm.endswith("/"):
        return None
    p = PurePosixPath(norm)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts) or ":" in norm:
        raise InstallError("PERMANENT.BAD_PACKAGE", f"包里有不安全的路径：{name}")
    return p


def unpack(pkg: Path, staging: Path, url: str) -> list[Path]:
    """zip → 解到 staging（保持相对路径）；单个文件 → 按 url 末尾的文件名放进 staging。返回放进去的文件。"""
    out: list[Path] = []
    if zipfile.is_zipfile(pkg):
        try:
            with zipfile.ZipFile(pkg) as zf:
                for info in zf.infolist():
                    rel = _safe_member(info.filename)
                    if rel is None:
                        continue
                    target = staging.joinpath(*rel.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    out.append(target)
        except (zipfile.BadZipFile, OSError) as exc:
            raise InstallError("PERMANENT.BAD_PACKAGE", f"解压失败：{type(exc).__name__}: {exc}") from exc
    else:
        name = PurePosixPath(unquote(urlsplit(url).path)).name or pkg.name
        target = staging / name
        shutil.copyfile(pkg, target)
        out.append(target)
    return out


def install(url: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    url = (url or RELEASE_URL or "").strip()
    want = (sha256 or RELEASE_SHA256 or "").strip().lower()
    bin_dir = _bin_dir()
    base = {"installed": [], "bin_dir": str(bin_dir), "sha256": want}
    try:
        if not url:
            raise InstallError("SKIPPED.NOT_CONFIGURED", "还没有读取组件的发布地址：用 --url 给下载地址")
        if len(want) != 64 or any(c not in "0123456789abcdef" for c in want):
            raise InstallError("SKIPPED.NOT_CONFIGURED", "要给发布包的 sha256（64 位十六进制），没有校验和不安装")
        downloads = _home() / "downloads"
        name = PurePosixPath(unquote(urlsplit(url).path)).name or "reader-package"
        pkg = download(url, downloads / name)
        got = sha256_of(pkg)
        if got != want:
            _unlink(pkg)
            raise InstallError("PERMANENT.CHECKSUM_MISMATCH",
                               f"校验和对不上（下载到的是 {got[:12]}…，应为 {want[:12]}…），已删掉下载的文件，没安装")
        bin_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="reader-", dir=str(_home())))
        try:
            files = unpack(pkg, staging, url)
            # 只装认得的组件（包里的说明文件等一并放进 bin 无妨，但至少要有一个组件）
            exes = [f for f in files if f.name.lower() in KNOWN_NAMES]
            if not exes:
                raise InstallError("PERMANENT.BAD_PACKAGE",
                                   "包里没有读取组件（link-brain-reader / relatedfile），没安装")
            installed = []
            for f in files:
                dest = bin_dir / f.name  # 拍平：组件按文件名找
                try:
                    os.replace(f, dest)
                except PermissionError as exc:
                    raise InstallError("TRANSIENT.SERVICE_BUSY",
                                       f"{dest.name} 正被占用（读取服务还在跑？）：先在设置里停掉读取服务或重启电脑再装") from exc
                if os.name != "nt" and dest.name.lower() in KNOWN_NAMES:
                    dest.chmod(dest.stat().st_mode | 0o111)
                installed.append(str(dest))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        _unlink(pkg)
        return {"ok": True, "code": "", "message": f"读取组件已装好（{len(installed)} 个文件）", **base,
                "installed": installed}
    except InstallError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message, **base}


def status() -> dict[str, Any]:
    """组件找得到没有（不启动、不联网）。"""
    from . import accounts
    reader = accounts.reader_exe()
    try:
        from .adapters import xiaohongshu as xhs
        related = xhs.relatedfile_exe()
    except Exception:  # noqa: BLE001
        related = None
    return {"ok": True, "code": "", "message": "读取组件已就位" if reader else "还没装读取组件",
            "reader": reader, "relatedfile": related if related and Path(related).is_file() else None,
            "bin_dir": str(accounts.bin_dir()), "tool_dir": str(accounts.tool_dir()),
            # 插件引导看这个决定「下载读取组件」能不能点：发布地址和校验和都内置了才算（测试版两个都空）
            "release_configured": bool(RELEASE_URL.strip() and len(RELEASE_SHA256.strip()) == 64)}


def add_parser(sub) -> None:
    p = sub.add_parser("reader", help="读取组件：install 下载并校验 / status 看装没装（不启动、不联网）")
    rsub = p.add_subparsers(dest="reader_command", metavar="<install|status>")
    pi = rsub.add_parser("install", help="下载发布包、校验 sha256、解压到 ~/.link-brain/bin")
    pi.add_argument("--url", help="发布包下载地址（https / file://）")
    pi.add_argument("--sha256", help="发布包的 sha256（必填，除非程序里已内置）")
    rsub.add_parser("status", help="看读取组件装在哪")


def run(args) -> int:
    from .read import dump_json
    cmd = getattr(args, "reader_command", None)
    if cmd == "install":
        out = install(args.url, args.sha256)
        if not out["ok"]:
            print(out["message"], file=sys.stderr)
        dump_json(out)
        return 0 if out["ok"] else 1
    dump_json(status())
    return 0
