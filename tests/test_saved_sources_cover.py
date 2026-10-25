"""saved_sources 的补充用例（现有 test_ask_ui2_1004.py 只碰到 load 的 fail-open、strength 的强命中和 merge 的最简插入）。

只断言 link_brain/saved_sources.py 里能直接读出的行为。注意：这个模块读的是单份
`_archive/chat-archive.json`（JSON，不是 jsonl），「最后一行截在汉字中间」的 jsonl 惯例在这里不适用。
"""

from __future__ import annotations

import json

from link_brain import saved_sources, storage


def _write_archive(tmp_path, entries) -> None:
    arch = tmp_path / "_archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "chat-archive.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")


def test_load_builds_items_and_caches_by_mtime(monkeypatch, tmp_path):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _write_archive(tmp_path, [
        {"id": "n1", "kind": "note", "title": "", "content": "第一行\n第二行"},
        {"id": "r1", "kind": "report", "title": "报告", "content": "正文"},
        "不是字典的条目",
        {"id": "", "content": "没有 id"},
        {"id": "e", "content": 123},
    ])
    items = saved_sources.load()
    assert [it["id"] for it in items] == ["saved:n1", "saved:r1"]   # 坏条目跳过
    n1 = items[0]
    assert n1["saved_kind"] == "note"
    assert n1["title"] == "第一行"                                   # 无标题取正文第一行前 80 字
    assert n1["search_fields"]["saved"] == "第一行\n第二行"
    assert items[1]["saved_kind"] == "report" and items[1]["title"] == "报告"
    assert saved_sources.load() is items                            # 文件没变 → 回缓存（同一对象）


def test_load_fail_open_when_entries_shape_is_wrong(monkeypatch, tmp_path):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    arch = tmp_path / "_archive"
    arch.mkdir()
    p = arch / "chat-archive.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")          # JSON 是 list 不是 dict
    assert saved_sources.load() == []
    p.write_text('{"entries": "不是列表"}', encoding="utf-8")   # entries 不是 list
    assert saved_sources.load() == []


def test_is_saved():
    assert saved_sources.is_saved({"source_kind": "saved"})
    assert not saved_sources.is_saved({"source_kind": "note_image"})
    assert not saved_sources.is_saved({})
    assert not saved_sources.is_saved(None)


def test_strength_weak_generic_and_empty():
    note = saved_sources._item({"id": "a", "kind": "note", "content": "做梦是1"})
    # 只中一部分词（2 个 focused 中 1 个）→ 弱命中 1
    assert saved_sources.strength("做梦 外卖 推荐", note, ["做梦", "外卖"]) == 1
    # 泛词不进分母：只剩「做梦」一个 focused 且命中 → 强命中 2
    assert saved_sources.strength("做梦 外卖 推荐", note, ["ai", "做梦"]) == 2
    # 全是泛词 → 没有 focused → 0
    assert saved_sources.strength("ai 系统", note, ["ai", "系统"]) == 0
    # 空问题 / 空 haystack → 0
    assert saved_sources.strength("", note, ["做梦"]) == 0
    assert saved_sources.strength("做梦", {"id": "saved:x"}, ["做梦"]) == 0


def test_matching_strong_before_weak_regardless_of_saved_order():
    a = saved_sources._item({"id": "a", "content": "做梦是1"})
    b = saved_sources._item({"id": "b", "content": "旅游攻略里提到做梦"})
    # haystack 是「标题+正文」拼的：无标题时标题取正文第一行，所以 a 的 hay 是正文重复两遍——
    # 问题里要连着包含两遍才算整句包含（强命中 2）
    q = "她说 做梦是1 做梦是1 然后笑了"
    hits = saved_sources.matching(q, [b, a], ["做梦", "外卖"])
    assert [(s, it["id"]) for s, it in hits] == [(2, "saved:a"), (1, "saved:b")]   # 强在前；b 只中 1/2 个词是弱


def test_merge_caps_strong_and_weak_and_slot():
    q, terms = "关键词是abc", ["关键词", "外卖"]
    strongs = [saved_sources._item({"id": f"s{i}", "content": "关键词是abc"}) for i in range(4)]
    weaks = [saved_sources._item({"id": f"w{i}", "content": f"这里有关键词{i}"}) for i in range(6)]
    fillers = [{"id": f"f{i}"} for i in range(10)]
    out = saved_sources.merge(q, fillers, strongs + weaks, terms, after=0)
    ids = [m["id"] for m in out]
    assert ids[:3] == ["saved:s0", "saved:s1", "saved:s2"]      # FRONT_MAX=3：第 4 条强命中进不来
    assert "saved:s3" not in ids
    assert len(ids) == 3 + 10 + 5                               # WEAK_MAX=5：6 条弱命中只进 5 条
    assert ids[8:13] == [f"saved:w{i}" for i in range(5)]       # 弱命中插在 WEAK_SLOT=8 之后
    assert ids[13:] == [f"f{i}" for i in range(5, 10)]


def test_merge_dedup_excluded_and_fail_open():
    note = saved_sources._item({"id": "a", "content": "关键词是abc"})
    q, terms = "关键词是abc", ["关键词", "外卖"]
    already = [{"id": "saved:a", "already": True}]
    assert saved_sources.merge(q, already, [note], terms, after=0) == already   # 已在候选里不重复
    assert saved_sources.merge(q, [], [note], terms, excluded={"saved:a"}) == []
    assert saved_sources.merge(q, None, [note], terms) is None                  # matches 不是列表 → 原样返回
