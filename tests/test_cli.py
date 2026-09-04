"""Lot 0 冒烟：CLI 能构建、6+ 个子命令都在、--help 不炸。"""

from __future__ import annotations

import pytest

from link_brain.cli import build_parser, main

EXPECTED = {"ingest", "read", "search", "sync-favorites", "inbox", "resolve", "comment"}


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


def test_unimplemented_subcommand_returns_3():
    assert main(["inbox", "--for", "fable"]) == 3
