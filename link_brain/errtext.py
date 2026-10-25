"""异常 → 一行人话（1012）。

`f"{type(exc).__name__}: {exc}"` 遇到 ExceptionGroup 只剩「unhandled errors in a TaskGroup (1 sub-exception)」，
真因丢了（1001 验证码、1011 三篇抓取失败都栽在这）。全库把异常写成文字一律走 `errtext(exc)`；
tests/test_guards.py 的「手拼异常文字」规则守着别再手写那个 f-string。
"""
from __future__ import annotations


def errtext(exc: BaseException) -> str:
    subs = getattr(exc, "exceptions", None)
    if subs:
        return " | ".join(errtext(sub) for sub in subs)
    return f"{type(exc).__name__}: {exc}"
