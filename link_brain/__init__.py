"""link_brain — light-web-archieve 的归档基座。

V1 只处理小红书。设计约束见 docs/TASKBOOK.md，数据格式见 docs/FORMAT.md。
"""

from __future__ import annotations


def _read_version() -> str:
    """版本号只有一个来源：`pyproject.toml` 的 `[project].version`（1102）。

    装成 wheel / `pip install -e .` 之后它在包元数据里，`importlib.metadata` 直接读；
    没装（直接 `PYTHONPATH=仓库 python -m link_brain` 跑源码）就退回读仓库根的 pyproject.toml；
    两样都读不到返回 "0"——不编一个像真的数字，doctor / 报错里看到 "0" 就知道是没装好。
    插件 manifest.json 的 version 是手抄的副本，tests/test_guards.py 守着两处相等。
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("link-brain")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    try:
        import tomllib
        from pathlib import Path
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as fh:
            v = tomllib.load(fh).get("project", {}).get("version")
        if isinstance(v, str) and v.strip():
            return v.strip()
    except (OSError, ValueError, ImportError):
        pass
    return "0"


__version__ = _read_version()

# vault 布局常量（唯一真相；其余模块从这里取）
VAULT_DIRNAME = "vault"
ARCHIVE_DIRNAME = "_archive"
VISIBLE_SUBDIR = ("Web", "Xiaohongshu")
INDEX_DB_NAME = "index.db"
RAW_VERSION_PREFIX = "v"
