"""`python -m link_brain` 的模块入口。"""

from __future__ import annotations

import sys

# Windows 控制台默认 gbk，打印中文文件名/emoji 会 UnicodeEncodeError 崩溃；
# 强制 stdout/stderr 用 utf-8（编码失败的字符用 replace，不阻断输出）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
