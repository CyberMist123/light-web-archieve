"""vault 路径解析 + RAW 版本管理。

RAW 不可变：`raw/v0001/` 一旦写完就不再打开写。任何修正写 `v0002`。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import ARCHIVE_DIRNAME, INDEX_DB_NAME, VAULT_DIRNAME, VISIBLE_SUBDIR

ENV_VAULT = "LINK_BRAIN_VAULT"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def vault_root() -> Path:
    """vault 根目录。可用环境变量 LINK_BRAIN_VAULT 覆盖（测试用）。"""
    override = os.environ.get(ENV_VAULT)
    if override:
        return Path(override).resolve()
    return repo_root() / VAULT_DIRNAME


def archive_root() -> Path:
    return vault_root() / ARCHIVE_DIRNAME


def index_db_path() -> Path:
    return archive_root() / INDEX_DB_NAME


def visible_dir() -> Path:
    return vault_root().joinpath(*VISIBLE_SUBDIR)


def object_dir(source: str, source_id: str) -> Path:
    """`vault/_archive/<source>/<source_id>/`"""
    return archive_root() / source / source_id


def raw_dir(source: str, source_id: str, version: int) -> Path:
    return object_dir(source, source_id) / "raw" / version_name(version)


def derived_dir(source: str, source_id: str) -> Path:
    return object_dir(source, source_id) / "derived"


def version_name(version: int) -> str:
    return f"v{version:04d}"


def existing_versions(source: str, source_id: str) -> list[int]:
    base = object_dir(source, source_id) / "raw"
    if not base.is_dir():
        return []
    out = []
    for child in base.iterdir():
        if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
            out.append(int(child.name[1:]))
    return sorted(out)


def next_version(source: str, source_id: str) -> int:
    versions = existing_versions(source, source_id)
    return (versions[-1] + 1) if versions else 1


def ensure_raw_dir(source: str, source_id: str, version: int) -> Path:
    """创建 raw/vNNNN/assets/ 并返回 raw 版本目录。已存在则拒绝（RAW 不可变）。"""
    target = raw_dir(source, source_id, version)
    if target.exists():
        raise FileExistsError(f"RAW 版本已存在，不可覆写: {target}")
    (target / "assets").mkdir(parents=True)
    return target


def write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
