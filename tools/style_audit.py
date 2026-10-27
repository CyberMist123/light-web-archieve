"""样式审计（1027b，她：「全部的设计样式给我一个统一的模版，上次混乱太多了」）。

模版 = docs/style-guide.html（只用 link_brain/assets/lb-tokens.css 里的名字）。这里把页面 / 插件里**没按模版来**的地方一条条列出来：
  A 字体  第二、三套字：衬线（--lb-font-serif / --f-serif）、Cormorant 数字（--lb-font-num / --f-latin）、斜体、手写字体名
  B 字号  写死的 px 字号（没走 --lb-fs-* / --fs-*）
  C 颜色  写死的 #hex / rgb()（封面配色、阴影等确实要的也会列出来，由人判断）
只读、不改文件。lb-tokens:begin…end 之间（样式集本身）和 @font-face 不算。

用法：python tools/style_audit.py            → 打印汇总
      python tools/style_audit.py --md FILE  → 写成 Markdown 清单（file:line + 那一段）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "link_brain/assets/catalog-view.js",
    "link_brain/assets/chat-view.js",
    "link_brain/assets/trash-view.js",
    "link_brain/assets/annotate-view.js",
    "link_brain/assets/lb-page-lib.js",
    "link_brain/assets/link-brain.css",
    "link_brain/assets/link-brain-native-media.css",
    "obsidian-plugins/link-brain-actions/styles.css",
]

FONT_RX = re.compile(r"var\(--(?:lb-font-serif|f-serif|lb-font-num|f-latin)\)|\bitalic\b|font-family:\s*[\"']?(?:Georgia|Cormorant|Noto Serif|Songti|SimSun|STSong|Times)")
SIZE_RX = re.compile(r"font(?:-size)?:[^;}{`]*?(?<![\w.-])(\d+(?:\.\d+)?)px")
COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")
CAT = {"A": "字体（第二、三套字 / 斜体）", "B": "字号（写死 px）", "C": "颜色（写死）"}


def scan(path: Path) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    skip = False
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "lb-tokens:begin" in line:
            skip = True
        if skip:
            if "lb-tokens:end" in line:
                skip = False
            continue
        s = line.strip()
        if s.startswith("//") or "@font-face" in line or "font-style:${" in line:
            continue
        for cat, rx in (("A", FONT_RX), ("B", SIZE_RX), ("C", COLOR_RX)):
            for m in rx.finditer(line):
                if cat == "C" and not re.search(r"[:{,(\s]", line[max(0, m.start() - 1):m.start()] or " "):
                    continue
                a = max(0, m.start() - 50)
                out.append((cat, i, line[a:m.end() + 30].strip()))
                break   # 一行一类只记一次
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--md", help="写成 Markdown 清单到这个文件")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8')   # Windows 控制台默认 GBK
    except Exception:  # noqa: BLE001
        pass
    rows = {f: scan(ROOT / f) for f in FILES if (ROOT / f).exists()}
    print("文件".ljust(52), "A 字体  B 字号  C 颜色")
    for f, hits in rows.items():
        n = {c: sum(1 for h in hits if h[0] == c) for c in CAT}
        print(f.ljust(52), f"{n['A']:>6} {n['B']:>7} {n['C']:>7}")
    if args.md:
        lines = ["# 样式偏差清单（tools/style_audit.py 生成，别手改）", "",
                 "模版见 `docs/style-guide.html`。每一条 = 一处没按模版来；**先列不改**，她定了再按类一批批换。",
                 "注意：目录页边栏四块（RECENT / SYNC / TOKEN / OVERVIEW）和设置页在 1027b 已经把 serif / 数字字体变量改指正文字，",
                 "那里的 A 类条目页面上已经是正文字了（这里按源码列，换的时候顺手删掉旧写法）。", ""]
        for cat, title in CAT.items():
            total = sum(1 for hits in rows.values() for h in hits if h[0] == cat)
            lines += [f"## {cat} {title} · {total} 处", ""]
            for f, hits in rows.items():
                mine = [h for h in hits if h[0] == cat]
                if not mine:
                    continue
                lines.append(f"### `{f}`（{len(mine)}）")
                lines.append("")
                for _, ln, snip in mine:
                    lines.append(f"- [{f}:{ln}]({'../' + f}#L{ln}) `{snip.replace('`', 'ˋ')[:110]}`")
                lines.append("")
        Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("写好了：", args.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
