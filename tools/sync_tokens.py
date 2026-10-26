"""样式集（1027）：把唯一源拷到各个副本里。改了源就跑一次：python tools/sync_tokens.py（--check 只检查不写）。

两块：
- CSS 变量 + 共用类：源 link_brain/assets/lb-tokens.css（整份就是一块 /* lb-tokens:begin ... lb-tokens:end */），
  副本在 lb-page-lib.js 的 LB_SHARED_CSS（页面自己注入 head，手机上没有插件也有）、插件 styles.css（设置页）、
  link-brain.css 和它的逐字副本 note.css（笔记页的 CSS 片段，手机上也加载）。
- 她的「Aa 样式」→ 行内变量的那段 JS：源在 lb-page-lib.js 的 /* lb-theme:begin ... lb-theme:end */，
  副本在插件 lb-theme.js（设置页 / 插件侧用同一套换算）。
副本里只替换标记之间那一段，标记外面的东西不动。tests/test_tokens_1027.py 锁住逐字相同。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "link_brain" / "assets"
PLUGIN = ROOT / "obsidian-plugins" / "link-brain-actions"

TOKENS_SRC = ASSETS / "lb-tokens.css"
TOKENS_COPIES = [ASSETS / "lb-page-lib.js", PLUGIN / "styles.css", ASSETS / "link-brain.css", PLUGIN / "note.css"]
THEME_SRC = ASSETS / "lb-page-lib.js"
THEME_COPIES = [PLUGIN / "lb-theme.js"]

BLOCKS = {
    "lb-tokens": (TOKENS_SRC, TOKENS_COPIES),
    "lb-theme": (THEME_SRC, THEME_COPIES),
}


def block_rx(name: str) -> re.Pattern:
    return re.compile(r"/\* " + re.escape(name) + r":begin[\s\S]*?" + re.escape(name) + r":end \*/")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def source_block(name: str) -> str:
    src, _ = BLOCKS[name]
    m = block_rx(name).search(read(src))
    if not m:
        raise SystemExit(f"{src.relative_to(ROOT)} 里没有 {name}:begin / {name}:end 标记")
    return m.group(0)


def copy_block(name: str, path: Path) -> str | None:
    m = block_rx(name).search(read(path))
    return m.group(0) if m else None


def sync(check: bool = False) -> list[str]:
    """返回不一致（check）或这次改写了的文件。"""
    out: list[str] = []
    for name, (_, copies) in BLOCKS.items():
        want = source_block(name)
        if name == "lb-tokens" and ("`" in want or "${" in want or "\\" in want):
            raise SystemExit("lb-tokens.css 里不许有反引号、${ 或反斜杠（它要原样放进 lb-page-lib.js 的模板字符串）")
        for p in copies:
            text = read(p)
            m = block_rx(name).search(text)
            if not m:
                raise SystemExit(f"{p.relative_to(ROOT)} 里没有 {name} 标记：先手工放一对空标记占位")
            if m.group(0) == want:
                continue
            out.append(p.relative_to(ROOT).as_posix())
            if not check:
                p.write_text(text[: m.start()] + want + text[m.end():], encoding="utf-8", newline="\n")
    return out


if __name__ == "__main__":
    check = "--check" in sys.argv[1:]
    changed = sync(check=check)
    if check:
        print("不一致：" + "、".join(changed) if changed else "四份 lb-tokens + lb-theme 副本都和源一致")
        sys.exit(1 if changed else 0)
    print("已同步：" + "、".join(changed) if changed else "都已是最新，没写文件")
