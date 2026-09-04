"""把 source.json 渲染成 Obsidian 可见 md + derived/agent.md。纯模板拼接，不经过模型。Lot 3 实现。

Lot 0 占位模块：只声明未实现异常，实现时按 docs/FORMAT.md 补。
"""

from __future__ import annotations


class NotYetImplemented(NotImplementedError):
    """该 Lot 尚未实现时抛出；CLI 捕获后打印友好提示。"""


def not_implemented(what: str) -> NotYetImplemented:
    return NotYetImplemented(what + " 尚未实现（见 docs/STATE.md 的 current_lot）")
