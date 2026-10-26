"""1027 样式集：唯一源 link_brain/assets/lb-tokens.css + lb-page-lib.js 的 lb-theme 段，副本逐字相同；约定的变量名一个不少。

副本怎么来：python tools/sync_tokens.py（--check 只查）。行为（applyTheme 换算、页面 / 插件两边结果一样）在 tests/test_tokens_1027.cjs。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import sync_tokens  # noqa: E402

# 两位同事（目录编排 / 设置页）按这些名字取用：只许加，不许改名
REQUIRED = [
    "--lb-font-title", "--lb-font-serif", "--lb-font-num", "--lb-font-body",
    "--lb-fs-display", "--lb-fs-h1", "--lb-fs-h2", "--lb-fs-body", "--lb-fs-small", "--lb-fs-micro", "--lb-fs-num-lg", "--lb-fs-num",
    "--lb-ink", "--lb-muted", "--lb-faint", "--lb-line", "--lb-surface", "--lb-soft", "--lb-accent", "--lb-warn", "--lb-danger",
    "--lb-space-1", "--lb-space-2", "--lb-space-3", "--lb-space-4", "--lb-space-5", "--lb-space-6",
    "--lb-radius", "--lb-radius-pill", "--lb-ctl-h", "--lb-scale", "--lb-gap",
]
CLASSES = [".lb-btn", ".lb-btn-pill", ".lb-input", ".lb-label", ".lb-num", ".lb-kicker"]


def _defs(css: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--lb-[\w-]+)\s*:\s*([^;}]+)[;}]", css)}


def test_copies_identical_to_source():
    assert sync_tokens.sync(check=True) == [], "副本和源不一致：改源（lb-tokens.css / lb-page-lib.js 的 lb-theme 段）后跑 python tools/sync_tokens.py"
    for name, (_, copies) in sync_tokens.BLOCKS.items():
        want = sync_tokens.source_block(name)
        for p in copies:
            assert sync_tokens.copy_block(name, p) == want, f"{p.name} 里的 {name} 段和源不一样"


def test_token_source_is_one_block_and_template_safe():
    src = sync_tokens.read(sync_tokens.TOKENS_SRC).strip()
    assert src == sync_tokens.source_block("lb-tokens"), "lb-tokens.css 整份就是一块（标记外不放东西，副本才能原样拷）"
    for bad in ("`", "${", "\\"):
        assert bad not in src, f"lb-tokens.css 里不许有 {bad!r}（它原样放进 lb-page-lib.js 的模板字符串）"


def test_required_names_defined():
    css = sync_tokens.source_block("lb-tokens")
    defs = _defs(css)
    missing = [n for n in REQUIRED if n not in defs]
    assert not missing, f"约定的变量没定义：{missing}"
    for c in CLASSES:
        assert re.search(re.escape(c) + r"(?![\w-])", css), f"共用类 {c} 没定义"
    assert defs["--lb-fs-body"] == "calc(13.5px * var(--lb-scale,1))"
    assert defs["--lb-fs-small"] == "calc(12px * var(--lb-scale,1))"
    assert defs["--lb-fs-micro"] == "calc(11px * var(--lb-scale,1))"
    assert [defs[f"--lb-space-{i}"] for i in range(1, 7)] == ["4px", "8px", "12px", "16px", "24px", "32px"]
    assert defs["--lb-radius"] == "8px" and defs["--lb-radius-pill"] == "999px" and defs["--lb-ctl-h"] == "34px" and defs["--lb-scale"] == "1"
    # 黑白：强调色就是墨色，颜色全走 Obsidian 主题变量（深浅色跟着走），不写死色值
    assert defs["--lb-accent"] == defs["--lb-ink"] == "var(--text-normal)"
    for n in ("--lb-ink", "--lb-muted", "--lb-faint", "--lb-line", "--lb-surface", "--lb-soft"):
        assert defs[n].startswith("var(--"), n


def test_brand_stack_is_the_title_token():
    lib = sync_tokens.read(sync_tokens.ASSETS / "lb-page-lib.js")
    stack = re.search(r"const BRAND_FONT_STACK = '([^']+)'", lib).group(1)
    assert _defs(sync_tokens.source_block("lb-tokens"))["--lb-font-title-base"] == stack, "BRAND_FONT_STACK 和 --lb-font-title-base 同一串"


def test_scaled_tokens_redeclared_on_page_roots():
    """字号 / 颜色写在 body,.lb-page-host,.lb-scope 上：页面根上改了 --lb-scale 能就地重算；她能改的五个只在 body 给默认值。"""
    css = sync_tokens.source_block("lb-tokens")
    scoped = re.search(r"body,\.lb-page-host,\.lb-scope\{([^}]*)\}", css).group(1)
    assert "--lb-fs-body:" in scoped and "--lb-ink:" in scoped
    for n in ("--lb-font-title:", "--lb-font-body:", "--lb-font-num:", "--lb-scale:", "--lb-gap:"):
        assert n not in scoped, f"{n} 不能在页面根上重新给默认值（会盖掉 body 上的设置）"


def test_note_page_has_no_colliding_local_names():
    """笔记页自己的间距 / 圆角 / 线 / 底色改叫 --lbn-*，不和样式集同名不同值。"""
    for p in (sync_tokens.ASSETS / "link-brain.css",):
        text = sync_tokens.read(p)
        outside = sync_tokens.block_rx("lb-tokens").sub("", text)
        for n in ("--lb-gap", "--lb-radius", "--lb-line", "--lb-surface", "--lb-muted", "--lb-faint"):
            assert not re.search(re.escape(n) + r"\s*:", outside), f"{p.name} 在样式集外又定义了 {n}"
