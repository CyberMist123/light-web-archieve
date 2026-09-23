"""Lot D：答案缓存。全部 mock（call_text / 查询向量），不打真网、不碰真实 vault。

conftest 的 isolated_answer_cache 已把 answers.json 指到 tmp。
"""
from __future__ import annotations

import json
import os

import pytest

from link_brain import answer_cache as ac
from link_brain import ask, storage
from link_brain.ask import query_terms

ITEMS = [
    {"id": "a", "title": "AI 会做梦吗", "note": "Web/a.md", "summary": "大模型做梦与梦境",
     "search_text": "大模型做梦与梦境生成的讨论，记忆整理。", "tags": ["AI", "记忆"],
     "url": "https://www.xiaohongshu.com/explore/a", "ts": "2026-09-10T00:00:00+08:00"},
    {"id": "c", "title": "梦的记忆整理", "note": "Web/c.md", "summary": "把梦写进记忆库",
     "search_text": "做梦之后把梦写进记忆库，dream journal。", "tags": ["记忆", "AI"],
     "url": "https://www.xiaohongshu.com/explore/c", "ts": "2026-09-11T00:00:00+08:00"},
    {"id": "b", "title": "本周菜谱", "note": "Web/b.md", "summary": "十分钟快手菜",
     "search_text": "十分钟快手菜，减脂餐。", "tags": ["吃的"],
     "url": "https://www.xiaohongshu.com/explore/b", "ts": "2026-09-12T00:00:00+08:00"},
]

Q_OLD = "AI 做梦和记忆"
Q_NEW = "AI 的做梦与记忆"      # 换个连接词的同一问：cache_terms Jaccard = 1.0
Q_OTHER = "减脂餐怎么做"


@pytest.fixture(autouse=True)
def fake_index(monkeypatch):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))


@pytest.fixture
def model(monkeypatch):
    seen = []
    def fake(prompt, text, settings):
        seen.append(text)
        return {"status": "ok", "text": "结论：做梦是离线整理。[来源1]\n细节……"}
    monkeypatch.setattr(ask, "call_text", fake)
    return seen


def _seed(ts, item_ids=("a",), question=Q_OLD, **extra):
    entry = {"id": "seed", "ts": ts, "question": question, "terms": query_terms(question),
             "item_ids": list(item_ids), "item_titles": ["旧标题"] * len(item_ids),
             "export_path": None, "first_line": "上次的结论。", **extra}
    ac.index_path().parent.mkdir(parents=True, exist_ok=True)
    ac.index_path().write_text(json.dumps({"version": 1, "entries": [entry]}, ensure_ascii=False), encoding="utf-8")
    return entry


# ---------------------------------------------------------------- 阈值钉住

@pytest.mark.parametrize("a,b", [
    ("睡不好怎么办", "晚上睡不好怎么改善"),
    ("怎么学英语口语", "英语口语怎么练"),
    ("推荐几个 AI 记忆层项目", "AI记忆层有哪些项目推荐"),
    ("Claude Code 有哪些好用的插件", "Claude Code 插件推荐"),
    (Q_OLD, Q_NEW),
])
def test_term_threshold_hits_paraphrases(a, b):
    entries = [{"ts": "2026-09-01T00:00:00+08:00", "question": a, "terms": query_terms(a), "item_ids": []}]
    hit = ac.lookup(b, query_terms(b), entries)
    assert hit and hit["match"]["method"] == "terms" and hit["match"]["score"] >= ac.TERM_THRESHOLD


@pytest.mark.parametrize("a,b", [
    ("上海周末去哪玩", "上海周末遛娃去哪"),
    ("AI 会做梦吗", "AI 做梦的记忆"),
    ("推荐几个 AI 记忆层项目", "推荐几个减脂餐做法"),
    ("猫粮推荐", "狗粮推荐"),
    ("AI 记忆层", "AI 编程工具"),
])
def test_term_threshold_misses_different_questions(a, b):
    entries = [{"ts": "2026-09-01T00:00:00+08:00", "question": a, "terms": query_terms(a), "item_ids": []}]
    assert ac.lookup(b, query_terms(b), entries) is None


def test_semantic_threshold_and_vector_overrides_terms():
    qvec = {"model": "m", "v": [1.0, 0.0, 0.0]}
    near = {"model": "m", "b64": ac._encode_vec([0.9, 0.3, 0.0])}   # cos≈0.949
    far = {"model": "m", "b64": ac._encode_vec([0.6, 0.8, 0.0])}    # cos=0.6
    base = {"ts": "2026-09-01T00:00:00+08:00", "item_ids": []}
    hit = ac.lookup("完全不同的字", ["完全", "不同"], [{**base, "question": "x", "terms": ["毫无", "交集"], "vec": near}], qvec)
    assert hit["match"]["method"] == "semantic" and hit["match"]["score"] >= ac.SEM_THRESHOLD
    # 有可比向量但余弦不够：即便词完全一样也不命中（以向量为准）
    same_words = {**base, "question": Q_OLD, "terms": query_terms(Q_OLD), "vec": far}
    assert ac.lookup(Q_OLD, query_terms(Q_OLD), [same_words], qvec) is None
    # 模型不同 / 维度不同的向量不可比，退回词法
    other_model = {**same_words, "vec": {"model": "other", "b64": near["b64"]}}
    assert ac.lookup(Q_OLD, query_terms(Q_OLD), [other_model], qvec)["match"]["method"] == "terms"
    assert ac.cosine([1, 0], [1, 0, 0]) == 0.0


# ---------------------------------------------------------------- 新增材料筛选

def test_newer_items_strictly_after_cache_ts():
    items = [{"id": "old", "ts": "2026-09-10T00:00:00+08:00"},
             {"id": "equal", "ts": "2026-09-10T12:00:00+08:00"},
             {"id": "new", "ts": "2026-09-11T00:00:00+08:00"},
             {"id": "tz", "ts": "2026-09-10T05:00:00+00:00"},   # = 13:00+08:00，晚于缓存
             {"id": "nots", "ts": ""}, {"id": "bad", "ts": "昨天"}, {"id": "missing"}]
    got = [it["id"] for it in ac.newer_items(items, "2026-09-10T12:00:00+08:00")]
    assert got == ["new", "tz"]
    assert ac.newer_items(items, "坏时间") == []


# ---------------------------------------------------------------- 三态：未命中 / 命中 / 索引损坏

def test_miss_records_entry_and_prompt_unchanged(model):
    r = ask.answer(Q_OTHER)
    assert r["status"] == "ok" and not r["markdown"].startswith("> 以前问过")
    assert "answer_cache" not in r and "以前问过类似问题" not in model[0]
    entries = ac.load()
    assert len(entries) == 1
    e = entries[0]
    assert e["question"] == Q_OTHER and e["item_ids"] == ["b"] and e["export_path"] is None
    assert e["first_line"] == "结论：做梦是离线整理。[来源1]" and e["terms"] == query_terms(Q_OTHER)
    assert "vec" not in e   # 没语义层就不存向量


def test_hit_injects_previous_question_and_new_material(model):
    _seed("2026-09-10T12:00:00+08:00", item_ids=["a"])
    deltas = []
    r = ask.answer(Q_NEW, on_delta=deltas.append)
    ids = [s["id"] for s in r["sources"]]
    assert set(ids) == {"a", "c"}
    cit_c = next(s["citation"] for s in r["sources"] if s["id"] == "c")
    assert r["markdown"].splitlines()[0] == "> 以前问过类似问题（2026-09-10），本次结合 1 条新材料"
    assert r["markdown"].split("\n\n", 1)[1].startswith("结论：")
    assert deltas[0].startswith("> 以前问过类似问题（2026-09-10）")
    ctx = model[0]
    assert "【以前问过类似问题——仅供对照，不是事实来源】" in ctx
    assert f"上次问题（2026-09-10）：{Q_OLD}" in ctx
    assert "当时用的收藏：《AI 会做梦吗》" in ctx          # 用当前标题，不用存档旧标题
    assert f"此后新增的相关收藏（已在下方原始材料中）：《梦的记忆整理》[来源{cit_c}]" in ctx
    assert "上次回答开头：上次的结论。" in ctx
    assert ctx.index("【以前问过类似问题") < ctx.index("【原始材料】")
    assert r["answer_cache"]["question"] == Q_OLD
    # 本次也追加记录（第二条），可供下次命中
    assert [e["question"] for e in ac.load()] == [Q_OLD, Q_NEW]


def test_hit_without_new_material_says_conclusion_reused(model):
    _seed("2026-09-20T00:00:00+08:00", item_ids=["a", "c"])
    r = ask.answer(Q_NEW)
    assert r["markdown"].splitlines()[0] == "> 以前问过类似问题（2026-09-20），此后没有新增相关收藏，结论沿用"
    assert "此后新增的相关收藏：无" in model[0]


def test_removed_item_falls_back_to_stored_title(model):
    _seed("2026-09-20T00:00:00+08:00", item_ids=["gone"])
    ask.answer(Q_NEW)
    assert "当时用的收藏：《旧标题》" in model[0]


@pytest.mark.parametrize("content", ["{坏json", "[]", '{"entries": "x"}', '{"entries": [{"question": 1}, {"ts": "x"}]}', ""])
def test_corrupt_index_behaves_as_fresh_and_is_set_aside(model, content):
    baseline_dir = ac.index_path().parent
    baseline_dir.mkdir(parents=True, exist_ok=True)
    ac.index_path().write_text(content, encoding="utf-8")
    assert ac.load() == []
    r = ask.answer(Q_NEW)
    assert r["status"] == "ok" and not r["markdown"].startswith("> 以前问过")
    assert "以前问过类似问题" not in model[0]
    assert [e["question"] for e in ac.load()] == [Q_NEW]


def test_corrupt_prompt_equals_empty_index_prompt(monkeypatch, model):
    ask.answer(Q_OTHER)                      # 空索引 → 基线
    ac.index_path().write_text("{坏", encoding="utf-8")
    ask.answer(Q_OTHER)                      # 坏索引
    assert model[0] == model[1]
    assert ac.index_path().with_name("answers.json.corrupt").read_text(encoding="utf-8") == "{坏"


def test_followup_with_history_does_not_consult_cache(model):
    _seed("2026-09-10T12:00:00+08:00")
    r = ask.answer(Q_NEW, history=[{"role": "user", "content": "你好"}, {"role": "assistant", "content": "嗨"}])
    assert not r["markdown"].startswith("> 以前问过") and "以前问过类似问题" not in model[0]


def test_model_failure_is_not_recorded(monkeypatch):
    monkeypatch.setattr(ask, "call_text", lambda *a: {"status": "failed", "error": "boom"})
    assert ask.answer(Q_NEW)["status"] == "error"
    assert ac.load() == []


def test_lookup_exception_is_fail_open(monkeypatch, model):
    _seed("2026-09-10T12:00:00+08:00")
    monkeypatch.setattr(ac, "term_overlap", lambda *a: 1 / 0)
    r = ask.answer(Q_NEW)
    assert r["status"] == "ok" and "以前问过类似问题" not in model[0]


# ---------------------------------------------------------------- 语义路径 + 向量落盘

def test_semantic_vector_is_stored_and_used(monkeypatch, model):
    vectors = {Q_OLD: [1.0, 0.1, 0.0], "梦境是怎么来的": [0.95, 0.2, 0.0]}
    monkeypatch.setattr(ac, "question_vector", lambda q: {"model": "m", "v": vectors[q]} if q in vectors else None)
    ask.answer(Q_OLD)
    stored = ac.load()[0]
    assert stored["vec"]["model"] == "m" and ac._decode_vec(stored["vec"]["b64"]) == pytest.approx(vectors[Q_OLD])
    raw = json.loads(ac.index_path().read_text(encoding="utf-8"))["entries"][0]["vec"]
    assert isinstance(raw["b64"], str)       # 紧凑存储，不是千维 float 列表
    r = ask.answer("梦境是怎么来的")           # 词毫无重叠，只能靠向量命中
    assert r["markdown"].startswith("> 以前问过类似问题") and r["answer_cache"]["match"]["method"] == "semantic"


def test_question_vector_none_without_semantic_db(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path / "v"))
    assert ac.question_vector("任何问题") is None


# ---------------------------------------------------------------- 原子写 + 导出回填

def test_atomic_write_failure_keeps_old_file(monkeypatch):
    _seed("2026-09-10T12:00:00+08:00")
    before = ac.index_path().read_text(encoding="utf-8")
    monkeypatch.setattr(ac.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    assert ac.record("q", ["q"], [], "a") is None
    assert ac.index_path().read_text(encoding="utf-8") == before
    assert [p.name for p in ac.index_path().parent.iterdir()] == ["answers.json"]


def test_attach_export_picks_nearest_same_question(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    ac.record(Q_OLD, [], [], "一", ts="2026-09-10T10:00:00+08:00")
    ac.record(Q_OLD, [], [], "二", ts="2026-09-12T10:00:00+08:00")
    ac.record("别的", [], [], "三", ts="2026-09-12T10:00:01+08:00")
    target = tmp_path / "收藏导出" / "x.zip"
    assert ac.attach_export(Q_OLD, "2026-09-10T02:00:05Z", target)
    assert [e["export_path"] for e in ac.load()] == ["收藏导出/x.zip", None, None]
    assert ac.attach_export(Q_OLD, "unknown", tmp_path / "收藏导出" / "y.zip")
    assert [e["export_path"] for e in ac.load()] == ["收藏导出/x.zip", "收藏导出/y.zip", None]
    assert not ac.attach_export(Q_OLD, "2026-01-01T00:00:00Z", target)   # 太远不认
    assert not ac.attach_export("没问过", None, target)


def test_export_bundle_backfills_answer_index(tmp_path, monkeypatch):
    from tests.test_export_bundle import fixture
    from link_brain.export_bundle import export_bundle
    fixture(tmp_path, monkeypatch)
    ac.record("做梦机制", [], [{"id": "example", "title": "测试资料"}], "本轮回答", ts="2026-09-23T02:00:00+10:00")
    result = export_bundle(["example"], False, "本轮回答", "做梦机制", "2026-09-23T02:00:03+10:00")
    assert ac.load()[0]["export_path"] == os.path.relpath(result["path"], tmp_path).replace(os.sep, "/")
    # 索引坏了导出照常
    ac.index_path().write_text("{坏", encoding="utf-8")
    assert export_bundle(["example"], False, "本轮回答", "做梦机制", "2026-09-23T02:00:03+10:00")["path"]


def test_probe_cli_runs_without_network(capsys):
    _seed("2026-09-10T12:00:00+08:00")
    assert ac._main(["probe", Q_NEW]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["semantic"] is False and out["hit"]["question"] == Q_OLD
    assert ac._main(["list"]) == 0
