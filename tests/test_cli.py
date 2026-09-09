"""Lot 0 冒烟：CLI 能构建、6+ 个子命令都在、--help 不炸。"""

from __future__ import annotations

import pytest

from link_brain.cli import build_parser, main

EXPECTED = {"ingest", "read", "search", "sync-favorites", "inbox", "resolve", "comment", "catalog"}


def _subcommands():
    parser = build_parser()
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        if hasattr(action, "choices") and action.choices:
            return set(action.choices)
    return set()


def test_all_subcommands_registered():
    assert EXPECTED <= _subcommands()


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_inbox_runs():
    # 2026-09-09 Lot 5 落地后，inbox 不再是「未实现返回 3」的占位；空收件箱正常返回 0。
    assert main(["inbox", "--for", "nobody-such-actor"]) == 0
