"""第 4 批（CONVENTIONS §2.6）：推送只有一个出口——alert._alert 模块私有，仓内只有 problems.py 调它。

扫 link_brain/ 全部源码：除 alert.py 自己和 problems.py 外，不许出现 `alert_mod` / `alert._alert(` / `alert.alert(` /
`from .alert import` / `import alert`；alert 模块也不再有公开的 `alert` 函数（防止有人又把它当公共出口）。
"""

from __future__ import annotations

import re
from pathlib import Path

from link_brain import alert as alert_mod

ROOT = Path(__file__).resolve().parents[1] / "link_brain"
ALLOWED = {"alert.py", "problems.py"}
FORBIDDEN = re.compile(
    r"\balert_mod\b|\balert\._alert\s*\(|\balert\.alert\s*\(|from\s+\.+\s*alert\s+import|"
    r"from\s+\.+\s+import\s+[^\n]*\balert\b|import\s+link_brain\.alert|from\s+link_brain\s+import\s+[^\n]*\balert\b"
    r"|from\s+link_brain\.alert\s+import"
)


def offenders(root: Path = ROOT) -> list[str]:
    hits = []
    for f in sorted(root.rglob("*.py")):
        if f.name in ALLOWED and f.parent == root:
            continue
        for n, line in enumerate(f.read_text("utf-8", errors="replace").splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{f.relative_to(root.parent)}:{n}: {line.strip()}")
    return hits


def test_only_problems_calls_the_push_exit():
    assert offenders() == [], "这些地方绕过 problems.report 直接报警了：\n" + "\n".join(offenders())


def test_alert_module_has_no_public_alert_function():
    assert not hasattr(alert_mod, "alert"), "alert.alert 应该是模块私有（_alert），只给 problems._push 用"
    assert callable(alert_mod._alert)


def test_problems_is_the_one_caller():
    text = (ROOT / "problems.py").read_text("utf-8")
    assert "alert_mod._alert(" in text


def test_the_scanner_catches_direct_calls(tmp_path):
    pkg = tmp_path / "link_brain"
    pkg.mkdir()
    (pkg / "x.py").write_text("from . import alert as alert_mod\nalert_mod._alert('k', 't', 'b')\n", "utf-8")
    (pkg / "y.py").write_text("from .alert import _alert\n", "utf-8")
    (pkg / "problems.py").write_text("from . import alert as alert_mod\n", "utf-8")
    hits = offenders(pkg)
    assert len(hits) == 3 and not any("problems.py" in h for h in hits)
