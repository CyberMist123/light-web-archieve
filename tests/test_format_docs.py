"""docs/FORMAT.md 里每个 json 代码块都必须能被 json.loads 解析。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FORMAT_MD = Path(__file__).resolve().parent.parent / "docs" / "FORMAT.md"
BLOCK_RE = re.compile(r"```json\n(.*?)```", re.DOTALL)


def _blocks():
    return BLOCK_RE.findall(FORMAT_MD.read_text(encoding="utf-8"))


def test_has_json_blocks():
    assert len(_blocks()) >= 4


@pytest.mark.parametrize("idx", range(len(_blocks())))
def test_json_block_parses(idx):
    json.loads(_blocks()[idx])
