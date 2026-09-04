"""ingest 流水线：链接 -> adapter -> 不可变 RAW。

Lot 0 只占位；Lot 1 接上小红书 adapter。
"""

from __future__ import annotations

import sys


def run(args) -> int:
    print("`ingest` 尚未实现（Lot 0 占位）。当前进度见 docs/STATE.md。", file=sys.stderr)
    return 3
