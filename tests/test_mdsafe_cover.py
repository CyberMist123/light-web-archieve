"""mdsafe 的补充用例（test_mdsafe.py + 14 条共享 fixture 已盖主流清洗形态和四条端到端入口）。

这里只钉 fixture 没碰到的角落：空值 / 非字符串输入的分支、未闭合围栏、4+ 个反引号 / 波浪线的长围栏、
`dataview` 作为更长单词一部分出现的 info 串、行首前缀在引用行 / 缩进行里的插入位置、
`<code` 后面不是空白斜杠尖角号时不误伤。全部是纯函数，断言都先在解释器里核过。
"""

from __future__ import annotations

from link_brain import mdsafe

ZWSP = mdsafe.ZWSP


def test_falsy_inputs_return_empty_string():
    assert mdsafe.neutralize("") == ""
    assert mdsafe.neutralize(None) == ""
    assert mdsafe.neutralize(False) == ""          # falsy 走 `text or ""`，不是 str() 那条


def test_non_string_input_is_str_coerced():
    assert mdsafe.neutralize(123) == "123"          # truthy 非 str：str() 了再洗


def test_unclosed_fence_info_is_still_replaced():
    # 围栏没闭合也算围栏：info 串照样换成 text，内容原样保留
    assert mdsafe.neutralize("```dataviewjs\nx") == "```text\nx"
    assert mdsafe.neutralize("~~~dataview\ny") == "~~~text\ny"


def test_longer_fence_runs_are_recognized():
    assert mdsafe.neutralize("````dataviewjs\nx\n````") == "````text\nx\n````"
    assert mdsafe.neutralize("~~~~dataview\ny\n~~~~") == "~~~~text\ny\n~~~~"


def test_dataview_inside_longer_info_word():
    # 判定用的是子串 "dataview" in info.lower()，替换只动 dataview(js) 这个词，前缀后缀留着
    assert mdsafe.neutralize("```mydataviewjs\nx\n```") == "```mytext\nx\n```"
    assert mdsafe.neutralize("```xDataview y\nx\n```") == "```xtext y\nx\n```"


def test_line_start_prefix_insertion_positions():
    # 引用行 / 缩进 + 引用：零宽空格插在引导符号之后、= 之前；行首 == 也命中（规则只看 $?= 前缀）
    assert mdsafe.neutralize("> $= dv.page()") == f"> {ZWSP}$= dv.page()"
    assert mdsafe.neutralize("  > = this.x") == f"  > {ZWSP}= this.x"
    assert mdsafe.neutralize("== 标题") == f"{ZWSP}== 标题"


def test_html_code_tag_negative():
    # <code 后面得是空白 / 斜杠 / 尖角号才算标签：<codex、光秃秃的 <code 不动
    assert mdsafe.neutralize("<codex>a</codex> and <code") == "<codex>a</codex> and <code"


def test_plain_fence_content_equal_signs_midline_untouched():
    text = "```python\nx = 1 == 2\nif a == b:\n    pass\n```"
    assert mdsafe.neutralize(text) == text          # = 在行中间不碰；只有行首 $?= 才插
