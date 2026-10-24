"""1024 第 1 波 p0-catalog：构建目录不联网、不花钱。

- catalog.build 不再顺手拉起 AI 归类 / 起草（挪到夜跑 `index catch-up` 那一步）；
- 主题向量按主题文本缓存在 _archive/topic-vectors.json：build 只读缓存，缺了退回关键词口径并标「主题向量待更新」；
- 夜跑判「收藏同步在不在跑」时列不出进程 = 当它在跑（失败即关）。
"""

from __future__ import annotations

import json
import socket
import sys

import pytest

from link_brain import catalog, indexai, indextree, nightly, semantic, storage, topics
from link_brain.nightly import Nightly, Step
from tests.test_catalog import _make_object


def _vec(text):
    # 确定性假向量：数「记忆 / 鱼」，末位常数防零向量
    return [float(text.count("记忆")), float(text.count("鱼")), 1.0]


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    monkeypatch.setenv(storage.ENV_VAULT, str(v))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("LINK_BRAIN_MODELS_DIR", str(tmp_path / "no-keys"))
    semantic._MATRIX_CACHE.update(stamp=None, data=None)
    semantic._QUERY_VEC_CACHE.clear()
    _make_object(v, "a1", title="长期记忆方案", tags=["记忆"], summary="讲记忆", stem="长期记忆方案")
    _make_object(v, "b2", title="鱼片菜谱", tags=["菜谱"], summary="讲鱼", stem="鱼片菜谱")
    topics.save([{"id": "t1", "name": "记忆", "keywords": ["记忆", "memory"], "created": ""},
                 {"id": "t2", "name": "吃鱼", "keywords": ["鱼片"], "created": ""}], v)
    return v


@pytest.fixture
def embed_calls(monkeypatch):
    calls: list[list[str]] = []

    def fake(texts, cfg, timeout):
        calls.append(list(texts))
        return [_vec(t) for t in texts]
    monkeypatch.setattr(semantic, "_post_embeddings", fake)
    return calls


def _with_semantic_db(vault):
    catalog.build()          # 先有 catalog-data，embed 才有东西切
    assert semantic.run_embed()["status"] == "ok"
    semantic._QUERY_VEC_CACHE.clear()


def _no_spawn(monkeypatch):
    spawned: list[str] = []
    monkeypatch.setattr(indexai, "spawn", lambda v: spawned.append("classify") or "queued")
    monkeypatch.setattr(indextree, "spawn_draft", lambda v: spawned.append("draft") or "queued")
    monkeypatch.setattr(indextree, "maybe_classify", lambda *a, **k: spawned.append("maybe_classify") or "queued")
    monkeypatch.setattr(indextree, "maybe_auto_draft", lambda *a, **k: spawned.append("maybe_auto_draft") or "queued")
    return spawned


def _items(vault):
    return {it["id"]: it for it in json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))["items"]}


def test_build_calls_no_embedding_no_spawn_no_network(vault, embed_calls, monkeypatch):
    _with_semantic_db(vault)
    spawned = _no_spawn(monkeypatch)
    before = len(embed_calls)

    def no_net(*a, **k):
        raise AssertionError("catalog.build 不许联网")
    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    catalog.build()
    assert len(embed_calls) == before, "build 里调了 embedding"
    assert spawned == []


def test_first_migration_build_spawns_nothing(vault, monkeypatch):
    spawned = _no_spawn(monkeypatch)
    catalog.build()          # 第一次：迁移出 索引.md
    assert (vault / indextree.index_rel()).exists()
    assert spawned == []
    assert indextree._state(vault).get("auto_draft_pending")   # 起草这件事记下来，交给夜跑


def test_build_twice_same_payload(vault, embed_calls):
    _with_semantic_db(vault)
    topics.refresh_vectors(vault)
    catalog.build()
    a = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))
    catalog.build()
    b = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))
    assert catalog._same_content(a, b)


def test_topic_cache_hit_matches_live_vectors(vault, embed_calls):
    _with_semantic_db(vault)
    tl = topics.load(vault)
    live = topics._semantic_scores(tl, live=True)            # 旧口径：当场取向量
    assert live
    assert topics.refresh_vectors(vault)["fetched"] == 2
    n = len(embed_calls)
    cached = topics._semantic_scores(tl, live=False)         # build 口径：只读缓存
    assert len(embed_calls) == n
    assert cached == live
    catalog.build()
    data = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))
    assert data.get("topics_vectors_pending") == []
    assert _items(vault)["xhs-a1"]["topics"] == ["记忆"]
    # 再补一次：缓存都在，不再取
    assert topics.refresh_vectors(vault)["fetched"] == 0 and len(embed_calls) == n


def test_topic_cache_missing_falls_back_to_keywords(vault, embed_calls):
    _with_semantic_db(vault)
    catalog.build()          # 没跑过 refresh_vectors：缓存不在
    data = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))
    assert data["topics_vectors_pending"] == ["记忆", "吃鱼"]
    items = _items(vault)
    assert items["xhs-a1"]["topics"] == ["记忆"] and items["xhs-b2"]["topics"] == ["吃鱼"]   # 关键词口径


def test_topic_cache_stale_after_keyword_change(vault, embed_calls):
    _with_semantic_db(vault)
    topics.refresh_vectors(vault)
    tl = topics.load(vault)
    tl[0]["keywords"] = ["记忆", "长期记忆"]                  # 主题文本变了：旧向量作废
    topics.save(tl, vault)
    catalog.build()
    data = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))
    assert data["topics_vectors_pending"] == ["记忆"]


def test_topic_cache_corrupt_file_build_ok(vault, embed_calls):
    _with_semantic_db(vault)
    (vault / "_archive" / topics.VECTORS_NAME).write_text("{坏的", encoding="utf-8")
    catalog.build()
    assert _items(vault)["xhs-a1"]["topics"] == ["记忆"]


def test_no_semantic_db_nothing_pending(vault):
    catalog.build()
    data = json.loads((vault / "_archive" / catalog.DATA_NAME).read_text("utf-8"))
    assert data["topics_vectors_pending"] == []


# ---------------------------------------------------------------- 夜跑那一步


def test_catch_up_does_what_build_used_to(vault, embed_calls, monkeypatch):
    _with_semantic_db(vault)
    ran: list[str] = []
    monkeypatch.setattr(indextree, "should_auto_draft", lambda v, n: True)
    monkeypatch.setattr(indextree, "draft", lambda v=None, **kw: ran.append(("draft", kw.get("auto"))) or {"ok": True, "message": ""})
    monkeypatch.setattr(indextree, "classify_gate", lambda data: "")
    monkeypatch.setattr(indexai, "run", lambda v=None, **kw: ran.append(("classify", kw.get("auto"))) or {"ok": True, "message": "归好了"})
    monkeypatch.setattr(indexai, "spawn", lambda v: pytest.fail("夜跑那一步就地跑，不另起后台"))
    r = indextree.catch_up(vault)
    assert r["ok"] and r["topics"]["fetched"] == 2
    assert ran == [("draft", True), ("classify", True)]
    assert not indextree._state(vault).get("auto_draft_pending")
    # 第二晚：起草已经做过，不再起草
    ran.clear()
    indextree.catch_up(vault)
    assert ran == [("classify", True)]


def test_catch_up_classify_skipped_when_gate_says_no(vault, monkeypatch):
    catalog.build()
    monkeypatch.setattr(indexai, "run", lambda *a, **k: pytest.fail("没配模型 / 没活 / 超上限就不跑"))
    r = indextree.catch_up(vault)
    assert r["ok"] and r["classify"]["skipped"]


def test_catch_up_reports_failure_honestly(vault, monkeypatch):
    catalog.build()
    monkeypatch.setattr(indextree, "classify_gate", lambda data: "")
    monkeypatch.setattr(indexai, "run", lambda v=None, **kw: {"ok": False, "code": "TRANSIENT.SERVICE_BUSY", "message": "接口忙"})
    r = indextree.catch_up(vault)
    assert not r["ok"] and r["code"] == "TRANSIENT.SERVICE_BUSY"


def test_nightly_has_catch_up_step_between_catalogs():
    names = [s.name for s in nightly.default_steps()]
    i = names.index(nightly.CATCH_UP_STEP)
    assert names.index("catalog") < i < names.index("catalog（收尾）")
    step = nightly.default_steps()[i]
    assert step.args == ["index", "catch-up"] and not step.account and step.timeout_min > 0


def test_catch_up_step_failure_does_not_block_later_steps(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir(exist_ok=True)
    monkeypatch.setattr(Nightly, "running_sync", lambda self: None)
    py = sys.executable
    job = Nightly(steps=[Step(nightly.CATCH_UP_STEP, [], 1, argv=[py, "-c", "import sys; sys.exit(1)"], reserve_min=0),
                         Step("catalog（收尾）", [], 1, argv=[py, "-c", "print('final-ran')"], reserve_min=0)],
                  log_path=tmp_path / "n.log", workdir=tmp_path, sleep=lambda s: None)
    job.run()
    log = (tmp_path / "n.log").read_text("utf-8")
    assert "final-ran" in log
    assert len(job.problems) == 1        # 这一步的失败照实登记，但没挡住后面


def test_nightly_process_enum_failure_counts_as_running(tmp_path, monkeypatch):
    from datetime import datetime
    from link_brain import sync_state
    storage.write_json(sync_state.path(), {"state": "running", "pid": 4242,
                                           "updated_at": datetime.now().astimezone().isoformat()})
    job = Nightly(steps=[], log_path=tmp_path / "n.log", workdir=tmp_path)

    def boom():
        raise RuntimeError("列不出进程")
    monkeypatch.setattr(nightly.procs, "process_table", boom)
    got = job.running_sync()
    assert got is not None and got["pid"] == 4242
    monkeypatch.setattr(nightly.procs, "process_table", lambda: (_ for _ in ()).throw(OSError("拒绝访问")))
    assert job.running_sync() is not None


def test_nightly_enum_failure_skips_night_and_says_so(tmp_path, monkeypatch):
    from datetime import datetime
    from link_brain import problems, sync_state
    storage.write_json(sync_state.path(), {"state": "running", "pid": 4242,
                                           "updated_at": datetime.now().astimezone().isoformat()})
    monkeypatch.setattr(nightly.procs, "process_table", lambda: (_ for _ in ()).throw(OSError("拒绝访问")))
    job = Nightly(steps=[Step("catalog", [], 1, argv=[sys.executable, "-c", "print('should not run')"], reserve_min=0)],
                  log_path=tmp_path / "n.log", workdir=tmp_path, sleep=lambda s: None)
    out = job.run()
    assert out["ran"] is False
    log = (tmp_path / "n.log").read_text("utf-8")
    assert "should not run" not in log and "列不出进程" in log
    assert [r["step"] for r in problems.load(include_resolved=False)] == ["nightly.sync-check"]  # 1024 返修：单独一个 step


def test_catalog_module_does_not_import_llm():
    src = (storage.repo_root() / "link_brain" / "catalog.py").read_text("utf-8")
    assert "from .llm import" not in src and "import llm" not in src
