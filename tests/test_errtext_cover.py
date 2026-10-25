"""errtext 的补充用例（现有 test_errtext.py 只测了一条组展开 + 一条普通异常）。

只断言 link_brain/errtext.py 里能直接读出来的行为：递归展开 `exceptions`、叶子用
`f"{type.__name__}: {exc}"` 拼、组与组之间用 " | "、组名一律不出现。
"""

from link_brain.errtext import errtext


def test_empty_message_leaf_keeps_trailing_space():
    # str(值) 为空时 f-string 照拼：类名 + ": " + 空串
    assert errtext(ValueError("")) == "ValueError: "


def test_nested_three_levels_reaches_leaf():
    g = ExceptionGroup("a", [ExceptionGroup("b", [ExceptionGroup("c", [RuntimeError("deep")])])])
    assert errtext(g) == "RuntimeError: deep"


def test_flat_group_joins_leaves_in_order():
    g = ExceptionGroup("g", [ValueError("a"), KeyError("b")])
    # KeyError 的 str() 自带引号：KeyError('b') 的 str 是 "'b'"
    assert errtext(g) == "ValueError: a | KeyError: 'b'"


def test_base_exception_group_unwraps_the_same_way():
    g = BaseExceptionGroup("bg", [KeyboardInterrupt("stop"), ValueError("v")])
    assert errtext(g) == "KeyboardInterrupt: stop | ValueError: v"


def test_keyboard_interrupt_wrapped_in_group_is_unwrapped():
    # ExceptionGroup 构造器不收 BaseException（会 TypeError），包 KeyboardInterrupt 要用 BaseExceptionGroup
    g = BaseExceptionGroup("eg", [KeyboardInterrupt("ctrl-c")])
    s = errtext(g)
    assert s == "KeyboardInterrupt: ctrl-c"
    assert "eg" not in s
