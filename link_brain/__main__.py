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

if __name__ == "__main__":
    # 10-31：个人 Wiki 的写盘命令走轻入口（只载 personal_wiki，0.3 秒；整套 cli 要 1.5 秒，每次保存页面就锁这么久）
    if sys.argv[1:2] == ["pwiki"] and sys.argv[2:3] in (["plan"], ["fill"]):   # 按用户的思路搭框架（出计划 / 按节检索补材料）：wiki_plan 自己接
        from .wiki_plan import main as wiki_plan_main
        sys.exit(wiki_plan_main(sys.argv[2:]))
    if sys.argv[1:3] == ["pwiki", "ai"]:   # 让 AI 改（只回建议）：wiki_ai 自己接，personal_wiki 不 import 它
        from .wiki_ai import main as wiki_ai_main
        sys.exit(wiki_ai_main(sys.argv[3:]))
    if sys.argv[1:2] == ["pwiki"]:
        from .personal_wiki import main_fast
        sys.exit(main_fast(sys.argv[2:]))
    from .cli import main
    sys.exit(main())
