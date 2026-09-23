"""测试永远不许联网。

`ingest` 现在会去笔记网页版探一次附件元数据（`xhs.fetch_related_file`）。
这里 autouse 地把它换成"没探到"，让所有测试确定性地走正文线索那条回退路径；
要测探测成功的行为，在用例里自己 monkeypatch 覆盖掉。
"""

from __future__ import annotations

import pytest

from link_brain import semantic
from link_brain.adapters import xiaohongshu as xhs


@pytest.fixture(autouse=True)
def no_embedding_http(request, monkeypatch):
    """本机 vault 可能已有 semantic.db + 真 key：测试一律掐断 embedding HTTP。

    掐断后语义层按设计 fail-open 退纯词法，正好等于「没配 embedding」的行为；
    要测语义命中的用例（tests/test_semantic.py）自己 monkeypatch mock provider 覆盖。
    """
    if "real_embeddings" in request.keywords:
        return
    def refuse(*args, **kwargs):
        raise RuntimeError("测试环境不联网")
    monkeypatch.setattr(semantic, "_post_embeddings", refuse)


@pytest.fixture(autouse=True)
def isolated_answer_cache(monkeypatch, tmp_path):
    """ask 成功就会往 answers.json 记一条：测试一律写进 tmp，绝不碰本机真实 vault。"""
    from link_brain import answer_cache
    path = tmp_path / "answer-cache" / "answers.json"
    monkeypatch.setattr(answer_cache, "index_path", lambda: path)
    return path


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
