"""测试永远不许联网。

`ingest` 现在会去笔记网页版探一次附件元数据（`xhs.fetch_related_file`）。
这里 autouse 地把它换成"没探到"，让所有测试确定性地走正文线索那条回退路径；
要测探测成功的行为，在用例里自己 monkeypatch 覆盖掉。
"""

from __future__ import annotations

import pytest

from link_brain.adapters import xiaohongshu as xhs


@pytest.fixture(autouse=True)
def no_web_probe(request, monkeypatch):
    if "real_web_probe" in request.keywords:
        return  # 这些用例自己 monkeypatch httpx，测的就是探测函数本身
    monkeypatch.setattr(
        xhs,
        "fetch_related_file",
        lambda note_id, xsec_token, **kw: {
            "ok": False,
            "related_file": None,
            "url": xhs.CANONICAL_FMT.format(note_id=note_id),
            "error": "测试环境不联网",
        },
    )
