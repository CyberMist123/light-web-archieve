"""依赖清单的唯一来源（1102）：pyproject 的 dependencies / optional-dependencies，经已装包的元数据读。

以前三处各写一份（pyproject、setup/components 的 CORE_REQS / OCR_REQS、doctor 的 KEY_DEPS），漂移到
`setup check core` 说 ready 而 B 站下载报 `No module named yt_dlp`。现在：
- `requirements(extra)`：这个 extra（"" = 核心）在当前解释器上适用的依赖说明（环境标记已按 python_version 算过）；
  装了包就读 `importlib.metadata.requires("link-brain")`，源码目录直接跑（没 pip install）读不到元数据时退回 FALLBACK。
- FALLBACK 必须和 pyproject 逐字一致，tests/test_guards.py 核。
- `missing_text(extra, purpose)`：缺某个 extra 时给用户的那一句（「要用 X，先装 `uv pip install link-brain[ocr]`」）。

本模块只导标准库、不 import 本包任何模块（doctor 缺依赖时也要能跑；也别把它卷进 tests/test_guards.py 守着的 import 环）。
"""
from __future__ import annotations

import re
import sys
from importlib import metadata

DIST = "link-brain"
EXTRAS = ("ocr", "bilibili", "docs")          # 用户装得到的功能包（full / dev 是它们的合集，不单列）
META_EXTRAS = ("full", "dev")

# 和 pyproject.toml 逐字一致（含环境标记）；元数据读不到时用这份
FALLBACK: dict[str, tuple[str, ...]] = {
    "": ("mcp>=1.27,<2", "httpx>=0.27", "pyyaml>=6.0", "pillow>=10.0", "pypinyin>=0.55", "jieba>=0.42.1",
         "rapidfuzz>=3.0", "qrcode>=7.0", "numpy>=1.26", "websockets>=12"),
    "ocr": ("rapidocr>=3.10", "onnxruntime>=1.17; python_version < '3.13'",
            "onnxruntime>=1.20; python_version == '3.13'", "onnxruntime>=1.24.1; python_version >= '3.14'"),
    "bilibili": ("yt-dlp>=2025.1", "imageio-ffmpeg>=0.5"),
    "docs": ("pypdfium2>=4.30", "python-docx>=1.1"),
    "full": ("link-brain[ocr,bilibili,docs]",),
    "dev": ("link-brain[full]", "pytest>=8.0"),
}

# 发行名 → import 名（元数据里没有这层对应；没列的两者相同、`-` 换 `_`）
IMPORT_NAMES = {"pyyaml": "yaml", "pillow": "PIL", "python-docx": "docx", "yt-dlp": "yt_dlp", "imageio-ffmpeg": "imageio_ffmpeg"}

# 每个包干什么（doctor 的「关键依赖」那一列、缺了时的提示）
PURPOSES = {
    "mcp": "连读取组件、接其他 AI", "httpx": "调 AI 接口、读取组件", "pyyaml": "笔记元数据", "pillow": "图片",
    "pypinyin": "拼音搜索、目录", "jieba": "问答 / 搜索切词", "rapidfuzz": "模糊匹配", "qrcode": "B 站扫码登录的二维码",
    "numpy": "语义检索", "websockets": "本机语音识别",
    "rapidocr": "本地认字", "onnxruntime": "本地认字",
    "yt-dlp": "B 站下载",
    "imageio-ffmpeg": "B 站合并 / 校验视频（随带 ffmpeg）",
    "pypdfium2": "PDF 附件", "python-docx": "Word 附件",
}
# 每个 extra 是给哪个功能的（缺了时「要用 X」里的 X）
EXTRA_PURPOSES = {"ocr": "本地 OCR", "bilibili": "B 站下载", "docs": "PDF / Word 附件转文字"}

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[([^\]]*)\])?")
_EXTRA_RE = re.compile(r"""\bextra\s*==\s*['"]([^'"]+)['"]""")
_PYVER_RE = re.compile(r"""python_version\s*(==|!=|<=|>=|<|>)\s*['"]([0-9.]+)['"]""")
_VERSION_TAIL_RE = re.compile(r"\s*;\s*(.*)$")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dist_name(spec: str) -> str:
    """'onnxruntime>=1.20; python_version == "3.13"' → 'onnxruntime'（原拼写）。"""
    m = _NAME_RE.match(spec)
    return m.group(1) if m else spec.strip()


def _self_extras(spec: str) -> list[str] | None:
    """'link-brain[ocr,bilibili]' → ['ocr', 'bilibili']；不是自引用 → None。"""
    m = _NAME_RE.match(spec)
    if not m or norm(m.group(1)) != DIST:
        return None
    return [x.strip() for x in (m.group(3) or "").split(",") if x.strip()]


def _split_marker(spec: str) -> tuple[str, str]:
    """'a>=1; m' → ('a>=1', 'm')。"""
    m = _VERSION_TAIL_RE.search(spec)
    return (spec[: m.start()].strip(), m.group(1).strip()) if m else (spec.strip(), "")


def _pyver_tuple(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.split(".") if x.isdigit())


def marker_applies(marker: str, version: tuple[int, int] | None = None) -> bool:
    """只算 python_version 的比较（pyproject 里就只有这一种标记），`and` 连接；看不懂的子句一律当成立。
    比较按 (major, minor) 元组，和 PEP 440 对 '3.13' 这种两段版本的结果一致。"""
    ver = version or (sys.version_info.major, sys.version_info.minor)
    for clause in re.split(r"\band\b", marker):
        clause = clause.strip()
        if not clause or _EXTRA_RE.search(clause):
            continue
        m = _PYVER_RE.search(clause)
        if not m:
            continue
        op, want = m.group(1), _pyver_tuple(m.group(2))
        have = tuple(ver[: len(want)])
        ok = {"==": have == want, "!=": have != want, "<=": have <= want, ">=": have >= want,
              "<": have < want, ">": have > want}[op]
        if not ok:
            return False
    return True


def _raw_by_extra(reqs: list[str]) -> dict[str, list[str]]:
    """元数据的 Requires-Dist 行 → {extra: [带其余标记的依赖说明]}。setuptools 把 extra 并进标记：
    'onnxruntime>=1.20; python_version == "3.13" and extra == "ocr"'。"""
    out: dict[str, list[str]] = {"": []}
    for raw in reqs:
        spec, marker = _split_marker(raw)
        m = _EXTRA_RE.search(marker)
        extra = m.group(1) if m else ""
        rest = _EXTRA_RE.sub("", marker)
        rest = re.sub(r"^\s*and\s+|\s+and\s*$", "", rest).strip()
        rest = re.sub(r"\s+and\s+and\s+", " and ", rest)
        out.setdefault(extra, []).append(f"{spec}; {rest}" if rest else spec)
    return out


def raw_requirements(dist: str = DIST) -> tuple[dict[str, list[str]], str]:
    """({extra: [依赖说明]}, 来源 'metadata' | 'fallback')。"""
    try:
        reqs = metadata.requires(dist)
    except metadata.PackageNotFoundError:
        reqs = None
    if reqs is None:
        return {k: list(v) for k, v in FALLBACK.items()}, "fallback"
    return _raw_by_extra(reqs), "metadata"


def requirements(extra: str = "", *, version: tuple[int, int] | None = None, _seen: set[str] | None = None) -> list[str]:
    """这个 extra 在当前 Python 上适用的依赖说明（不带标记；自引用的 extra 展开）。"""
    table, _src = raw_requirements()
    seen = _seen if _seen is not None else set()
    if extra in seen:
        return []
    seen.add(extra)
    out: list[str] = []
    for raw in table.get(extra, []):
        spec, marker = _split_marker(raw)
        if marker and not marker_applies(marker, version):
            continue
        subs = _self_extras(spec)
        if subs is not None:
            for sub in subs:
                out += requirements(sub, version=version, _seen=seen)
            continue
        out.append(spec)
    return out


def dist_names(*extras: str, version: tuple[int, int] | None = None) -> list[str]:
    """这些 extra（"" = 核心）要的发行名，去重保序。"""
    out: list[str] = []
    for extra in extras or ("",):
        for spec in requirements(extra, version=version):
            name = dist_name(spec)
            if norm(name) not in {norm(x) for x in out}:
                out.append(name)
    return out


def import_name(dist: str) -> str:
    return IMPORT_NAMES.get(norm(dist), norm(dist).replace("-", "_"))


def import_map(extra: str = "") -> dict[str, str]:
    """{发行名: import 名}。"""
    return {d: import_name(d) for d in dist_names(extra)}


def spec_map(extra: str = "") -> dict[str, str]:
    """{发行名: 当前 Python 适用的那条依赖说明}（给 pip install 用）。同一个包几条标记只会剩一条。"""
    out: dict[str, str] = {}
    for spec in requirements(extra):
        out[dist_name(spec)] = spec
    return out


def extra_of(dist: str) -> str:
    """这个包属于哪个 extra（"" = 核心；都不是 → None）。"""
    key = norm(dist)
    for extra in ("", *EXTRAS):
        if key in {norm(x) for x in dist_names(extra)}:
            return extra
    return None  # type: ignore[return-value]


def purpose(dist: str) -> str:
    return PURPOSES.get(norm(dist), "")


def install_hint(extra: str = "") -> str:
    """装上这个 extra 的那条命令。"""
    return f"uv pip install {DIST}[{extra}]" if extra else f"uv pip install {DIST}"


def missing_text(extra: str, purpose_text: str = "") -> str:
    """缺某个功能包时给用户的一句话：「要用 X，先装 `uv pip install link-brain[xxx]`」。"""
    what = purpose_text or EXTRA_PURPOSES.get(extra) or extra
    gap = " " if re.match(r"[A-Za-z0-9]", what) else ""   # 中英文之间留一格：「要用 B 站下载」「要用本地 OCR」
    return f"要用{gap}{what}，先装 `{install_hint(extra)}`"
