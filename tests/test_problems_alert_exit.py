"""第 4 批（CONVENTIONS §2.6）：推送只有一个出口——alert._alert 模块私有，仓内只有 problems.py 调它。

源码扫描（除 alert.py / problems.py 外不许碰 alert）1025 合进 tests/test_guards.py 的「绕过 problems 直接报警」规则；
这里只留 alert 模块本身的两条断言：没有公开的 `alert` 函数（防止有人又把它当公共出口）、problems 是那个唯一的调用者。
"""

from __future__ import annotations

from pathlib import Path

from link_brain import alert as alert_mod

ROOT = Path(__file__).resolve().parents[1] / "link_brain"


def test_alert_module_has_no_public_alert_function():
    assert not hasattr(alert_mod, "alert"), "alert.alert 应该是模块私有（_alert），只给 problems._push 用"
    assert callable(alert_mod._alert)


def test_problems_is_the_one_caller():
    text = (ROOT / "problems.py").read_text("utf-8")
    assert "alert_mod._alert(" in text
