"""从本机 Obsidian 的 asar 包里只读抽出 app.css（批次 D 测试架：tests/_obsidian_shell.cjs 的可选真 CSS）。

    python tests/tools/obsidian_css.py [--asar <obsidian-x.y.z.asar>] [--out <文件>] [--check]

- 只读：打开 asar 读头部和 app.css 那一段字节，不解包、不改任何文件、不起 Obsidian。
- 默认 asar = %APPDATA%/obsidian 下版本号最大的 obsidian-*.asar（macOS / Linux 走各自的配置目录）。
- 默认产物 = 系统临时目录/lwa-obsidian-css/app-<版本>.css（**绝不进仓**：app.css 是 Obsidian 的版权内容）。
- 用法：设 LWA_OBSIDIAN_APP_CSS=<产物路径> 后跑页面测试，外壳会把它注入在手写子集前面。
- --check：只打印测试架依赖的几条规则在不在（C1 的 :hover overflow:hidden / contain:paint），不写文件。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

# 测试架手写子集依赖的规则（tests/_obsidian_shell.cjs 里每条都注明出处版本；Obsidian 升级后跑 --check 复核）
CHECKS = {
    "cm-embed-block:hover overflow:hidden": re.compile(
        r"\.markdown-source-view\.mod-cm6\s+\.cm-embed-block:not\([^)]*\):hover\s*\{[^}]*overflow:\s*hidden"),
    "cm-content > [contenteditable=false] contain:paint": re.compile(
        r"\.cm-content\s*>\s*\[contenteditable=false\]\s*\{[^}]*contain:\s*paint"),
}


def default_asar() -> Path | None:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "")) / "obsidian"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "obsidian"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "obsidian"
    found = sorted(base.glob("obsidian-*.asar"), key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", p.stem)])
    return found[-1] if found else None


def read_entry(asar: Path, name: str) -> bytes:
    """按 asar 头部（Chromium pickle：4 | headerSize | payloadSize | jsonLen | json）找到文件那一段，只读取出。"""
    with asar.open("rb") as f:
        head = f.read(16)
        if len(head) < 16:
            raise ValueError("不是 asar 文件（太短）")
        _, header_size, _, json_len = struct.unpack("<4I", head)
        header = json.loads(f.read(json_len).decode("utf-8"))
        node = header
        for part in name.split("/"):
            node = node.get("files", {}).get(part)
            if node is None:
                raise FileNotFoundError(f"asar 里没有 {name}")
        if node.get("unpacked"):
            raise FileNotFoundError(f"{name} 在 .asar.unpacked 里，不在包内")
        f.seek(8 + header_size + int(node["offset"]))
        return f.read(int(node["size"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--asar", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    asar = a.asar or default_asar()
    if not asar or not asar.exists():
        print("没找到 Obsidian 的 asar（用 --asar 指定）", file=sys.stderr)
        return 2
    css = read_entry(asar, "app.css").decode("utf-8", errors="replace")
    version = asar.stem.replace("obsidian-", "")
    found = {k: bool(rx.search(css)) for k, rx in CHECKS.items()}
    if a.check:
        print(json.dumps({"ok": all(found.values()), "version": version, "rules": found}, ensure_ascii=False))
        return 0 if all(found.values()) else 1
    out = a.out or Path(tempfile.gettempdir()) / "lwa-obsidian-css" / f"app-{version}.css"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(css, encoding="utf-8")
    print(json.dumps({"ok": True, "version": version, "path": str(out), "bytes": len(css), "rules": found}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
