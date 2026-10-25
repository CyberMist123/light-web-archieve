"""errtext 本身的单测。手拼异常文字的仓库扫描（原来在这里的 BASELINE）1025 合进 tests/test_guards.py 的「手拼异常文字」规则。"""

from link_brain.errtext import errtext


def test_errtext_unwraps_groups():
    g = ExceptionGroup("outer", [KeyError("noteCard"), ExceptionGroup("in", [TimeoutError("slow")])])
    s = errtext(g)
    assert "TaskGroup" not in s and "outer" not in s
    assert "KeyError: 'noteCard'" in s and "TimeoutError: slow" in s
    assert errtext(ValueError("x")) == "ValueError: x"
