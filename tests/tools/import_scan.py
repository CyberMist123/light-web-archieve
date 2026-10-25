"""import 契约扫描（第二波 PR③）：不装 import-linter，用 AST 算 `.importlinter` 里每条契约的违规边。

只查直接 import（对应 .importlinter 里每条契约的 allow_indirect_imports = True）。每条 import 都算，含函数里的延迟 import；`importlib` 字符串导入不算；
`from X import y` 里 y 是子模块就记成到 X.y 的边。旧路径转发文件（`sys.modules` 别名）不进图，
import 它们的边记到真身上（`link_brain.accounts` → `link_brain.sources.xiaohongshu.accounts`）。

用法：
    python tests/tools/import_scan.py          # 打印每条契约现在的违规边（ignore_imports 格式，排好序）
    python tests/tools/import_scan.py --cycle  # 打印最大环的模块数
守卫在 tests/test_guards.py（test_import_contract / test_import_cycle_size）。
"""
from __future__ import annotations

import ast
import configparser
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "link_brain"
CONFIG = ROOT / ".importlinter"
XHS = "link_brain.sources.xiaohongshu"

# 旧路径 → 真身（PR③ 搬家后的转发文件）。全仓不再从旧路径 import 后，转发文件和这张表一起删。
ALIASES = {
    **{f"link_brain.{m}": f"{XHS}.{m}" for m in (
        "accounts", "favorites", "fav_counts", "comment_fill", "restricted",
        "albums", "night_captcha", "reader_install")},
    "link_brain.adapters.xiaohongshu": f"{XHS}.adapter",
}


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def all_modules() -> dict[str, Path]:
    return {module_name(p): p for p in sorted(PKG.rglob("*.py")) if "__pycache__" not in p.parts}


def _canon(name: str) -> str:
    for old, new in ALIASES.items():
        if name == old or name.startswith(old + "."):
            return new + name[len(old):]
    return name


def edges() -> set[tuple[str, str]]:
    """(importer, imported)，只含 link_brain 内部、去掉自环；转发文件不当 importer。"""
    mods = all_modules()
    out: set[tuple[str, str]] = set()
    for name, path in mods.items():
        if name in ALIASES:
            continue
        is_pkg = path.name == "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = name.split(".") if is_pkg else name.split(".")[:-1]
                    base = base[: len(base) - (node.level - 1)]
                    prefix = ".".join(base + ([node.module] if node.module else []))
                else:
                    prefix = node.module or ""
                for a in node.names:
                    sub = f"{prefix}.{a.name}"
                    targets.append(sub if (sub in mods or sub in ALIASES) else prefix)
            for t in targets:
                if not (t == "link_brain" or t.startswith("link_brain.")):
                    continue
                t = _canon(t)
                if t != name:
                    out.add((name, t))
    return out


def _within(mod: str, pkg: str) -> bool:
    return mod == pkg or mod.startswith(pkg + ".")


def _lines(v: str) -> list[str]:
    return [x.split("#", 1)[0].strip() for x in v.splitlines() if x.split("#", 1)[0].strip()]


def contracts() -> dict[str, dict]:
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONFIG, encoding="utf-8")
    out = {}
    for sec in cp.sections():
        if not sec.startswith("importlinter:contract:"):
            continue
        c = cp[sec]
        out[sec.split(":", 2)[2]] = {
            "name": c.get("name", ""),
            "source": _lines(c.get("source_modules", "")),
            "forbidden": _lines(c.get("forbidden_modules", "")),
            "ignore": {tuple(p.strip() for p in x.split("->")) for x in _lines(c.get("ignore_imports", ""))},
        }
    return out


def violations(contract: dict, graph: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """forbidden 契约：source（含子模块）→ forbidden（含子模块）的边。
    forbidden 在 source 包里面（如接口包 vs 它下面的小红书包）时，forbidden 包自己内部的边不算。"""
    bad = set()
    for a, b in graph:
        for s in contract["source"]:
            if not _within(a, s):
                continue
            for f in contract["forbidden"]:
                if _within(b, f) and not (_within(a, f) and not _within(s, f)):
                    bad.add((a, b))
    return bad


def largest_cycle(graph: set[tuple[str, str]]) -> int:
    adj: dict[str, list[str]] = {}
    for a, b in graph:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, [])
    index, low, stack, on, best = {}, {}, [], set(), 0
    counter = [0]
    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))

    def strong(v):
        nonlocal best
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in adj[v]:
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            size = 0
            while True:
                w = stack.pop()
                on.discard(w)
                size += 1
                if w == v:
                    break
            best = max(best, size)

    for v in adj:
        if v not in index:
            strong(v)
    return best


def main(argv: list[str]) -> int:
    g = edges()
    if "--cycle" in argv:
        print(largest_cycle(g))
        return 0
    for key, c in contracts().items():
        print(f"[{key}] {c['name']}")
        for a, b in sorted(violations(c, g)):
            print(f"    {a} -> {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
