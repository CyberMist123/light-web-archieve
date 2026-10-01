"""不可信文本 → Markdown 清洗（1001 审计 C-2 / ui-1）。

收藏正文、评论、识图结果、附件全文、AI 回答都来自别人（或被别人内容影响的模型），
而 vault 里 Dataview 的 JS 是开着的：`dataviewjs` 代码块、行内 `$=` 查询都会以 Obsidian 的
Node 权限执行。凡是把这类文本写成 .md 或交给 MarkdownRenderer 的出口，都先过 `neutralize`：

- 代码围栏（``` 或 ~~~，任意缩进 / 引用 / 列表里）的语言名含 dataview（大小写不限、
  `{.dataviewjs}` 这类变体）→ 换成 text：照样显示代码，只是不再交给 Dataview 执行；
- Dataview 查的是每个 <code> 元素 trim 后的文字是否以行内前缀开头（本库设置 `=` / `$=`，
  且 inlineQueriesInCodeblocks=true，围栏代码块也算）：行内代码开头、每行行首的 `=` / `$=`
  前面插一个零宽空格（JS 的 trim 不吃它），视觉上不变；
- 原样 HTML 的 <code> 标签（allowHtml 开着）在标签名前插零宽空格，变成普通文字。

我们自己的目录页 / 回收站页里的 dataviewjs 来自 link_brain/assets，不经过这里。
`obsidian-plugins/link-brain-actions/main.js` 的 `neutralizeMarkdown` 是同一套规则的 JS 版
（`renderMarkdownInto` 统一过它；chat-view.js 的导出也调它），两边共用
tests/fixtures/mdsafe_cases.json（tests/test_mdsafe.py · tests/test_mdsafe.cjs）。改规则两边一起改。
"""
from __future__ import annotations

import re

ZWSP = "​"

_FENCE = re.compile(r"(`{3,}|~{3,})([^\n`]*)")
_DATAVIEW_WORD = re.compile(r"dataview(?:js)?", re.I)
_INLINE_OPEN = re.compile(r"(`+)(?=[ \t]*\$?=)")
_LINE_START = re.compile(r"(?m)^([ \t>]*)(?=\$?=)")
_HTML_CODE = re.compile(r"<(?=code[\s>/])", re.I)


def _fence(m: re.Match) -> str:
    info = m.group(2)
    if "dataview" not in info.lower():
        return m.group(0)
    return m.group(1) + _DATAVIEW_WORD.sub("text", info)


def neutralize(text: str | None) -> str:
    """把不可信 Markdown 里会被 Dataview 当代码执行的形态打断；幂等，正常文字视觉上不变。"""
    if not text:
        return text or ""
    text = _FENCE.sub(_fence, str(text))
    text = _INLINE_OPEN.sub(lambda m: m.group(1) + ZWSP, text)
    text = _LINE_START.sub(lambda m: m.group(1) + ZWSP, text)
    return _HTML_CODE.sub("<" + ZWSP, text)
