"""路径白名单：远程客户端能读到什么，全在这里定。

三道防护（照「只读根」的做法），任何一道不过就拒：
1. **规范形**：只收 vault 内的相对路径，`/` 分隔、逐段干净——拒绝空串、NUL、`\\`、`:`（盘符 / 备用数据流）、
   开头 `/`、空段、`.` / `..`、段尾的点或空格（Windows 会悄悄去掉）、设备名（CON / NUL …）。
   不做「帮你改对」：大小写 / 斜杠变体一律拒，客户端用 list / search 给出的原样路径。
2. **规则**（只看字符串）：
   - 永远禁止：任何以 `.` 开头的段（`.obsidian/**`、`.git`、`.env` …）、`_trash/**`、
     `_archive/**` 里除下面三种以外的一切（数据库、日志、problems.jsonl、catalog-data.json、raw、meta.json …）。
   - `@xhs`（小红书收藏库）开放：`Web/Xiaohongshu/**` 的笔记 + 每篇 `_archive/xiaohongshu/<id>/` 下的
     `derived/agent.md`（机读版）、`derived/attachments/*.md`（附件全文）、`notes.json`（批注）。
   - 用户加的文件夹：它下面的文本文件。
   - 只读文本：`.md` / `.markdown` / `.txt`（外加上面那一个 notes.json）；`.txt` 文件名像密钥的也拒。
3. **文件系统**：`lstat` 必须是普通文件（不是符号链接 / 联接点）、只有一个硬链接；
   `realpath` 的结果必须和「vault 真路径 + 规范形」**逐字相等**——父目录里藏着链接 / 联接点、
   大小写不同、8.3 短名，都会让两者对不上而被拒。
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import XHS

XHS_VISIBLE = "Web/Xiaohongshu"
XHS_ARCHIVE = "_archive/xiaohongshu"
INTERNAL_TOP = {"_archive", "_trash"}
TEXT_EXT = {".md", ".markdown", ".txt"}
MAX_READ_BYTES = 30 * 1024 * 1024

_ID = r"[A-Za-z0-9_-]{1,64}"
_ARCHIVE_FILE = re.compile(rf"^_archive/xiaohongshu/{_ID}/(derived/agent\.md|derived/attachments/[^/]+\.md|notes\.json)$")
_ARCHIVE_DIR = re.compile(rf"^_archive(/xiaohongshu(/{_ID}(/derived(/attachments)?)?)?)?$")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)
_SECRETISH = re.compile(r"(api[-_ ]?key|secret|passw|token|credential|cookie|密码|密钥|口令)", re.I)


class Denied(Exception):
    """路径不给读。code 是给客户端看的短码，message 是一句人话（不回显任何路径以外的东西）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical(rel: object, *, allow_root: bool = False) -> str:
    """第一道：只认规范形，返回原样字符串；不合格抛 Denied。"""
    if not isinstance(rel, str):
        raise Denied("INVALID_PATH", "路径要是字符串")
    if rel == "":
        if allow_root:
            return ""
        raise Denied("INVALID_PATH", "路径不能为空")
    if len(rel) > 1024 or "\x00" in rel:
        raise Denied("INVALID_PATH", "路径不合法")
    if "\\" in rel:
        raise Denied("INVALID_PATH", "路径用 / 分隔，照 list / search 给出的原样写")
    if ":" in rel or rel.startswith("/") or rel.startswith("~"):
        raise Denied("INVALID_PATH", "只收 vault 里的相对路径，不收绝对路径")
    for seg in rel.split("/"):
        if seg in ("", ".", ".."):
            raise Denied("INVALID_PATH", "路径里不能有空段、. 或 ..")
        if seg != seg.strip() or seg.endswith("."):
            raise Denied("INVALID_PATH", "路径段不能以空格或点结尾")
        if _RESERVED.match(seg) or any(ord(ch) < 32 for ch in seg):
            raise Denied("INVALID_PATH", "路径不合法")
    return rel


@dataclass(frozen=True)
class Policy:
    root: Path              # vault 真路径（realpath 过）
    folders: tuple[str, ...]

    @classmethod
    def build(cls, vault: str | os.PathLike, folders: Iterable[str]) -> "Policy":
        root = Path(os.path.realpath(vault))
        keep: list[str] = []
        for f in folders:
            if f == XHS:
                keep.append(XHS)
                continue
            try:
                keep.append(check_folder(root, f))
            except Denied:
                continue
        return cls(root=root, folders=tuple(dict.fromkeys(keep)))

    @property
    def xhs(self) -> bool:
        return XHS in self.folders

    @property
    def user_folders(self) -> tuple[str, ...]:
        return tuple(f for f in self.folders if f != XHS)

    def roots(self) -> list[str]:
        """开放的根（list 不给路径时列它们）。"""
        out: list[str] = []
        if self.xhs:
            out += [XHS_VISIBLE, XHS_ARCHIVE]
        out += [f for f in self.user_folders if f not in out]
        return out

    # —— 第二道：只看字符串 ——
    def file_rule(self, rel: str) -> None:
        segs = rel.split("/")
        if any(s.startswith(".") for s in segs):
            raise Denied("FORBIDDEN", "隐藏目录和文件（.obsidian 等）永远不开放")
        if segs[0] == "_archive":
            if self.xhs and _ARCHIVE_FILE.match(rel):
                return
            raise Denied("FORBIDDEN", "_archive 里只开放每篇的机读版、附件全文和批注")
        if segs[0] in INTERNAL_TOP:
            raise Denied("FORBIDDEN", "这个目录是程序内部状态，不开放")
        ext = os.path.splitext(segs[-1])[1].lower()
        if ext not in TEXT_EXT:
            raise Denied("NOT_TEXT", "只开放文本文件（.md / .markdown / .txt）")
        if ext == ".txt" and _SECRETISH.search(segs[-1]):
            raise Denied("FORBIDDEN", "文件名像密钥 / 口令文件，不开放")
        if self.xhs and rel.startswith(XHS_VISIBLE + "/"):
            return
        if any(rel.startswith(f + "/") for f in self.user_folders):
            return
        raise Denied("NOT_SHARED", "不在开放的文件夹里")

    def dir_rule(self, rel: str) -> bool:
        """这个目录能不能在 list 里出现 / 被列（祖先目录也算，只露出通往开放文件夹的那一支）。"""
        if rel == "":
            return True
        segs = rel.split("/")
        if any(s.startswith(".") for s in segs):
            return False
        if segs[0] == "_archive":
            return self.xhs and bool(_ARCHIVE_DIR.match(rel))
        if segs[0] in INTERNAL_TOP:
            return False
        for root in ([XHS_VISIBLE] if self.xhs else []) + list(self.user_folders):
            if rel == root or rel.startswith(root + "/") or root.startswith(rel + "/"):
                return True
        return False

    def inside_open_dir(self, rel: str) -> bool:
        """rel 本身在某个开放文件夹之内（而不只是它的祖先）。"""
        if self.xhs and (rel == XHS_VISIBLE or rel.startswith(XHS_VISIBLE + "/")):
            return True
        if self.xhs and _ARCHIVE_DIR.match(rel) and rel.startswith(XHS_ARCHIVE):
            return True
        return any(rel == f or rel.startswith(f + "/") for f in self.user_folders)

    # —— 第三道：文件系统 ——
    def _real_ok(self, rel: str, want_dir: bool) -> Path:
        cand = self.root.joinpath(*rel.split("/")) if rel else self.root
        try:
            st = os.lstat(cand)
        except OSError:
            raise Denied("NOT_FOUND", "没有这个文件") from None
        if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
            raise Denied("FORBIDDEN", "不跟随链接")
        if want_dir and not stat.S_ISDIR(st.st_mode):
            raise Denied("NOT_FOUND", "不是文件夹")
        if not want_dir:
            if not stat.S_ISREG(st.st_mode):
                raise Denied("NOT_FOUND", "不是普通文件")
            if getattr(st, "st_nlink", 1) > 1:
                raise Denied("FORBIDDEN", "不读有多个硬链接的文件")
        try:
            real = os.path.realpath(cand, strict=True)
        except (OSError, ValueError):
            raise Denied("NOT_FOUND", "没有这个文件") from None
        expected = str(cand)
        if real != expected:
            # 大小写变体、8.3 短名、父目录里的链接 / 联接点：真路径和规范形对不上
            raise Denied("FORBIDDEN", "路径和磁盘上的真实路径不一致（大小写 / 链接），照 list 给出的原样写")
        return cand

    def resolve_file(self, rel: object) -> Path:
        rel = canonical(rel)
        self.file_rule(rel)
        return self._real_ok(rel, want_dir=False)

    def resolve_dir(self, rel: object) -> tuple[str, Path]:
        rel = canonical(rel, allow_root=True)
        if not self.dir_rule(rel):
            raise Denied("NOT_SHARED", "不在开放的文件夹里")
        return rel, self._real_ok(rel, want_dir=True)

    def allowed_file(self, rel: str) -> bool:
        """搜索结果过滤用：规范形 + 规则（不碰磁盘）。"""
        try:
            canonical(rel)
            self.file_rule(rel)
            return True
        except Denied:
            return False


_LINK_TAGS = {0xA000000C, 0xA0000003}   # IO_REPARSE_TAG_SYMLINK / IO_REPARSE_TAG_MOUNT_POINT（联接点）


def _is_reparse(st: os.stat_result) -> bool:
    """符号链接 / 联接点。云盘占位文件（OneDrive 等）也是重解析点但不是链接，不拦——真跳走了第三道 realpath 也会拦。"""
    attrs = getattr(st, "st_file_attributes", 0) or 0
    if not attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        return False
    tag = getattr(st, "st_reparse_tag", None)
    return tag is None or tag in _LINK_TAGS


def check_folder(root: str | os.PathLike, rel: object) -> str:
    """用户在设置里加的文件夹：规范形、不是内部 / 隐藏目录、真实存在、不是链接（含父目录）。返回规范形。"""
    rel = canonical(rel)
    segs = rel.split("/")
    if any(s.startswith(".") for s in segs):
        raise Denied("FORBIDDEN", "隐藏目录（.obsidian 等）不能开放")
    if segs[0] in INTERNAL_TOP:
        raise Denied("FORBIDDEN", "_archive / _trash 是程序内部目录，不能整个开放")
    root = Path(os.path.realpath(root))
    probe = Policy(root=root, folders=(rel,))
    probe._real_ok(rel, want_dir=True)
    return rel


def candidate_folders(root: str | os.PathLike, *, max_depth: int = 3, limit: int = 500) -> list[str]:
    """设置页「添加文件夹」的候选：vault 里现有的文件夹（不含隐藏 / 内部目录、不跟链接），按路径排序。"""
    root = Path(os.path.realpath(root))
    out: list[str] = []
    stack: list[tuple[str, int]] = [("", 0)]
    while stack and len(out) < limit:
        rel, depth = stack.pop()
        base = root.joinpath(*rel.split("/")) if rel else root
        try:
            entries = sorted(os.scandir(base), key=lambda e: e.name, reverse=True)
        except OSError:
            continue
        for e in entries:
            name = e.name
            if name.startswith(".") or (not rel and name in INTERNAL_TOP):
                continue
            try:
                if e.is_symlink() or not e.is_dir(follow_symlinks=False) or _is_reparse(e.stat(follow_symlinks=False)):
                    continue
            except OSError:
                continue
            child = f"{rel}/{name}" if rel else name
            try:
                canonical(child)
            except Denied:
                continue
            out.append(child)
            if depth + 1 < max_depth:
                stack.append((child, depth + 1))
    return sorted(out)[:limit]
