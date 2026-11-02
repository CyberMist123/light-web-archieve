"""读取组件下载（第 5 批，Python 侧）：`python -m link_brain reader install --url <发布包> --sha256 <hex>`。

读取组件 = link-brain-reader（读收藏 / 评论 / 附件的本机服务）+ relatedfile（游客浏览器探附件，可选）。
预编译件由 GitHub Release 发（`.github/workflows/reader-release.yml`，标签 `reader-v<版本>`），插件引导里「下载读取组件」
调这条命令、不带参数 = 用 `release_pair()` 给的那一对：环境变量 `LINK_BRAIN_READER_URL` + `LINK_BRAIN_READER_SHA256`
→ `~/.link-brain/config.json` 的 `reader_release_url` + `reader_release_sha256` → 内置的 RELEASE_URL / RELEASE_SHA256（1102：
允许覆盖，方便自建镜像 / 装测试版）。地址和校验和**成对**用：只给了 --url 或只给了 --sha256 的，另一半不拿内置的凑
（不然换了地址还拿旧包的校验和去比，只会报校验和不对、说不清原因）；覆盖也一样，哪一层只给一半就当没给。**没有 sha256 一律不装。**

流程（1102 起走 `setup/fetch.py` 那套，和 CapsWriter / OCR 模型同一份实现）：下载到 `~/.link-brain/downloads/<文件>.part`
（可续传、分块报进度、GitHub 地址先试配置的镜像）→ 下完整算 sha256，对上了才改成正式文件名 → 是 zip 就解压到临时目录
（拒绝绝对路径 / `..` / 盘符，防 zip-slip），不是 zip 就当单个 exe → 逐个挪进 `~/.link-brain/bin/`
（`accounts.bin_dir()`，找组件时第一个看的目录）。读取服务正在跑、exe 被占着时如实报「先停掉读取服务」。

输出（CONVENTIONS §1）：stdout 最后一行 JSON `{ok, code, message, installed, bin_dir, sha256}`，失败时 stderr 最后一行是原因。
故障码：下载失败 TRANSIENT.NETWORK · 校验和不对 PERMANENT.CHECKSUM_MISMATCH · 包里没有组件 / 解不开 PERMANENT.BAD_PACKAGE ·
磁盘满 PERMANENT.DISK_FULL · 文件被占用 TRANSIENT.SERVICE_BUSY · 没给地址 / 校验和 SKIPPED.NOT_CONFIGURED。
不登记问题记录（这是用户点的操作，结果当场告诉他）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

# 发新版读取组件：跑发布工作流 → 把 Release 说明里的地址和 sha256 填到这里（同一个提交改 CHANGELOG）
RELEASE_URL = "https://github.com/CyberMist123/light-web-archieve/releases/download/reader-v0.2.0/link-brain-reader-windows-amd64.zip"
RELEASE_SHA256 = "aa4f9d78a56d58a2a2ecc33ec65c9aaba9291faae1cfbd0eef11f68911ee2c28"
ENV_URL, ENV_SHA256 = "LINK_BRAIN_READER_URL", "LINK_BRAIN_READER_SHA256"
CONFIG_URL, CONFIG_SHA256 = "reader_release_url", "reader_release_sha256"
KNOWN_NAMES = ("link-brain-reader.exe", "link-brain-reader", "relatedfile.exe", "relatedfile")
DOWNLOAD_TIMEOUT_S = 600
MAX_BYTES = 512 * 1024 * 1024

Emit = Callable[[dict[str, Any]], None]


class InstallError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _home() -> Path:
    from ... import storage
    return storage.link_brain_home()


def _bin_dir() -> Path:
    from . import accounts
    return accounts.bin_dir()


def _fetch():
    from ...setup import fetch
    return fetch


def _is_sha(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def release_pair() -> tuple[str, str]:
    """不带参数时用哪一对 (url, sha256)：环境变量 → config.json → 内置。每一层都要地址和校验和齐全才算，缺一半就看下一层。"""
    from ... import storage
    env_url, env_sha = (os.environ.get(ENV_URL) or "").strip(), (os.environ.get(ENV_SHA256) or "").strip().lower()
    if env_url and _is_sha(env_sha):
        return env_url, env_sha
    cfg = storage.user_config()
    cfg_url, cfg_sha = str(cfg.get(CONFIG_URL) or "").strip(), str(cfg.get(CONFIG_SHA256) or "").strip().lower()
    if cfg_url and _is_sha(cfg_sha):
        return cfg_url, cfg_sha
    return RELEASE_URL, RELEASE_SHA256


def release_configured() -> bool:
    url, sha = release_pair()
    return bool(url.strip()) and _is_sha(sha.strip().lower())


def download(url: str, dest: Path, on_progress=None) -> Path:
    """下到 dest（经 setup.fetch：先写 .part、能续、GitHub 地址先试镜像），下完改名成 dest。不校验——install 走 fetch_verified。"""
    fetch = _fetch()
    try:
        part = fetch.download(url, dest, on_progress=on_progress, max_bytes=MAX_BYTES)
        os.replace(part, dest)
    except fetch.SetupError as exc:
        raise InstallError(exc.code, exc.message) from exc
    return dest


def sha256_of(path: Path) -> str:
    return _fetch().sha256_of(path)


def _safe_member(name: str) -> PurePosixPath | None:
    """zip 成员名 → 相对路径；绝对路径、盘符、`..` 一律拒（抛）。目录项返回 None。（真身在 fetch.safe_rel）"""
    fetch = _fetch()
    try:
        return fetch.safe_rel(name)
    except fetch.SetupError as exc:
        raise InstallError(exc.code, exc.message) from exc


def unpack(pkg: Path, staging: Path, url: str, on_progress=None) -> list[Path]:
    """zip → 解到 staging（保持相对路径，经 fetch.unzip 防 zip-slip）；单个文件 → 按 url 末尾的文件名放进 staging。返回放进去的文件。"""
    fetch = _fetch()
    if zipfile.is_zipfile(pkg):
        try:
            fetch.unzip(pkg, staging, on_progress=on_progress)
        except fetch.SetupError as exc:
            raise InstallError(exc.code, exc.message) from exc
        return sorted(p for p in staging.rglob("*") if p.is_file())
    name = PurePosixPath(unquote(urlsplit(url).path)).name or pkg.name
    target = staging / name
    shutil.copyfile(pkg, target)
    return [target]


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


def install(url: str | None = None, sha256: str | None = None, *, emit: Emit | None = None) -> dict[str, Any]:
    """emit（可选）：setup install 的进度事件（component=reader，phase 下载 / 校验 / 解压），形状同 setup.common.progress。"""
    from ...setup.common import mb, progress
    if url is None and sha256 is None:  # 都没给：用配置 / 内置的一对；只给一半的不拿内置的凑
        url, sha256 = release_pair()
    url = (url or "").strip()
    want = (sha256 or "").strip().lower()
    bin_dir = _bin_dir()
    base = {"installed": [], "bin_dir": str(bin_dir), "sha256": want}
    fetch = _fetch()
    try:
        if not url:
            raise InstallError("SKIPPED.NOT_CONFIGURED", "还没有读取组件的发布地址：用 --url 给下载地址")
        if not _is_sha(want):
            raise InstallError("SKIPPED.NOT_CONFIGURED", "要给发布包的 sha256（64 位十六进制），没有校验和不安装")
        downloads = _home() / "downloads"
        name = PurePosixPath(unquote(urlsplit(url).path)).name or "reader-package"
        pkg = downloads / name
        try:
            got = fetch.fetch_verified(
                url, pkg, sha256=want, size=None,
                on_download=lambda d, t: progress(emit, "reader", "下载", d, t, f"{name} {mb(d)} MB" + (f" / {mb(t)} MB" if t else "")),
                on_verify=lambda d, t: progress(emit, "reader", "校验", d, t, f"核对 {name} 的 sha256"))
        except fetch.SetupError as exc:
            raise InstallError(exc.code, exc.message) from exc
        pkg = got["path"]
        staging = Path(tempfile.mkdtemp(prefix="reader-", dir=str(_home())))
        try:
            progress(emit, "reader", "解压", None, None, f"解开 {name}")
            files = unpack(pkg, staging, url, on_progress=lambda d, t: progress(emit, "reader", "解压", d, t, ""))
            # 只装认得的组件（包里的说明文件等一并放进 bin 无妨，但至少要有一个组件）
            exes = [f for f in files if f.name.lower() in KNOWN_NAMES]
            if not exes:
                raise InstallError("PERMANENT.BAD_PACKAGE",
                                   "包里没有读取组件（link-brain-reader / relatedfile），没安装")
            bin_dir.mkdir(parents=True, exist_ok=True)
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
        from . import adapter as xhs
        related = xhs.relatedfile_exe()
    except Exception:  # noqa: BLE001
        related = None
    return {"ok": True, "code": "", "message": "读取组件已就位" if reader else "还没装读取组件",
            "reader": reader, "relatedfile": related if related and Path(related).is_file() else None,
            "bin_dir": str(accounts.bin_dir()), "tool_dir": str(accounts.tool_dir()),
            # 插件引导看这个决定「下载读取组件」能不能点：发布地址和校验和都配好了才算（环境变量 / config.json / 内置）
            "release_configured": release_configured()}


def add_parser(sub) -> None:
    p = sub.add_parser("reader", help="读取组件：install 下载并校验 / status 看装没装（不启动、不联网）")
    rsub = p.add_subparsers(dest="reader_command", metavar="<install|status>")
    pi = rsub.add_parser("install", help="下载发布包（可续传、可配镜像）、校验 sha256、解压到 ~/.link-brain/bin")
    pi.add_argument("--url", help="发布包下载地址（https / file://）")
    pi.add_argument("--sha256", help="发布包的 sha256（必填，除非程序里已内置 / 配置里给了）")
    rsub.add_parser("status", help="看读取组件装在哪")


def run(args) -> int:
    from ...read import dump_json
    cmd = getattr(args, "reader_command", None)
    if cmd == "install":
        out = install(args.url, args.sha256)
        if not out["ok"]:
            print(out["message"], file=sys.stderr)
        dump_json(out)
        return 0 if out["ok"] else 1
    dump_json(status())
    return 0
