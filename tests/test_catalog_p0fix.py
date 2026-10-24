"""1024 第一波返修（复审 catalog）：列不出进程那条问题第二晚正常就消，面板不和「夜跑自己出错」混；
目录构建出异常时主题待更新也清掉。"""

from __future__ import annotations

import sys
from datetime import datetime

from link_brain import nightly, problems, repair, storage, sync_state
from link_brain.nightly import Nightly, Step


def test_enum_failure_registers_own_step_and_next_night_resolves(tmp_path, monkeypatch):
    storage.write_json(sync_state.path(), {"state": "running", "pid": 4242,
                                           "updated_at": datetime.now().astimezone().isoformat()})
    monkeypatch.setattr(nightly.procs, "process_table", lambda: (_ for _ in ()).throw(OSError("拒绝访问")))
    job = Nightly(steps=[], log_path=tmp_path / "n.log", workdir=tmp_path, sleep=lambda s: None)
    assert job.run()["ran"] is False
    [row] = problems.load(include_resolved=False)
    assert row["step"] == "nightly.sync-check", "修前：登记在 nightly.run，和真正的「夜跑自己出错」混成一条"
    plan = repair.plan(row)
    assert "夜跑自己出错" not in str(plan)

    # 第二晚：进程表正常、没在跑的同步 → 夜跑起来了，这条自动消
    monkeypatch.setattr(Nightly, "running_sync", lambda self: None)
    job2 = Nightly(steps=[Step("catalog", [], 1, argv=[sys.executable, "-c", "print('ok')"], reserve_min=0)],
                   log_path=tmp_path / "n2.log", workdir=tmp_path, sleep=lambda s: None)
    job2.run()
    assert not [r for r in problems.load(include_resolved=False) if r["step"] == "nightly.sync-check"]


# ---------------------------------------------------------------- catalog 低2 / 低3

import json  # noqa: E402

from link_brain import catalog, topics  # noqa: E402
from test_catalog_offline_p0 import _items, _with_semantic_db, embed_calls, vault  # noqa: E402,F401 - fixture


def test_wrong_dimension_cached_vector_is_pending_and_refetched(vault, embed_calls):
    """catalog 低2：semantic.db 换了维度、缓存里旧向量对不上：只把这个主题当待更新，别的主题照样按语义；夜里能补回来。"""
    _with_semantic_db(vault)
    topics.refresh_vectors(vault)
    p = topics.vectors_path(vault)
    raw = json.loads(p.read_text("utf-8"))
    first = next(iter(raw["vectors"]))
    raw["vectors"][first] = raw["vectors"][first][:2]       # 维度不对
    p.write_text(json.dumps(raw, ensure_ascii=False), "utf-8")
    pending: list[str] = []
    scores = topics._semantic_scores(topics.load(vault), live=False, pending=pending, vault=vault)
    assert scores is not None, "修前：一个主题维度不对就 return None，所有主题都退关键词，也不标待更新"
    assert pending == ["记忆"] and "t2" in scores
    assert topics.refresh_vectors(vault)["fetched"] == 1, "修前：文本在缓存里就不重取，永远补不回来"
    assert len(json.loads(p.read_text("utf-8"))["vectors"][first]) == 3


def test_build_clears_topics_pending_when_memberships_fail(vault, embed_calls, monkeypatch):
    """catalog 低3：语义部分已经追加了待更新、后面又抛错：topics 清空了，待更新也要清，前后对得上。"""
    def half(items, topic_list, *, pending=None, **k):
        pending.append("记忆")
        raise RuntimeError("关键词部分坏了")

    monkeypatch.setattr(topics, "memberships", half)
    catalog.build()
    data = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))
    assert data["topics_vectors_pending"] == []
