"""旧路径转发（第二波 PR③）：真身在 link_brain/sources/xiaohongshu/adapter.py。

用 sys.modules 别名而不是 import *：旧路径和新路径是同一个模块对象，monkeypatch 打哪边都打到真身。
全仓不再从这里 import 后删掉。
"""
import sys

from ..sources.xiaohongshu import adapter as _real

sys.modules[__name__] = _real
