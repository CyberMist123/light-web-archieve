"""places 的补充用例（test_ask_b3_r3.py 已盖 place_of / expand_variants / query_places 主路径、
boost 的无地名 no-op、_TABLE 空的 fail-open，以及经 ask.recall 的端到端）。

这里直接钉单元：table() 的解析 / 坏文件三分支 / 坏行过滤（用假 Path 换掉文件读，不动 assets 里那份数据）、
query_places 的序列入参和同行去重、_best_field 的字段权重取舍、facet_score 的地名门槛和下级打折、
route / boost 的直接调用（pool 是 item 字典列表，不改动入参）。全部纯内存，不出网。
"""

from __future__ import annotations

import pytest

import link_brain.retrieval  # noqa: F401 - 先载入，别让下面的补丁连累它的模块级初始化
from link_brain import places
from link_brain.retrieval import WEIGHTS


def _fake_places_file(monkeypatch, *, exc=None, text=""):
    class P:
        def __init__(self, *_a):
            pass
        def __truediv__(self, _other):
            return self
        @property
        def parent(self):
            return self
        def read_text(self, **_kw):
            if exc is not None:
                raise exc
            return text
    monkeypatch.setattr(places, "Path", P)


def _item(i, title, body="", tags=()):
    return {"id": i, "title": title, "tags": list(tags), "summary": "", "note": f"Web/{i}.md", "url": "",
            "search_fields": {"body": body}}


def test_table_parses_bundled_file_and_normalizes_names(monkeypatch):
    monkeypatch.setattr(places, "_TABLE", None)          # 强制从包里真表重读
    rows = places.table()
    assert rows and isinstance(rows, list)
    au = next(r for r in rows if "澳洲" in r["names"])
    assert "悉尼" in au["children"] and "sydney" in au["children"]   # 大写英文 norm 成小写
    assert all(n == n.lower().strip() for r in rows for n in r["names"])   # 入表都过 norm


def test_table_fail_open_on_unreadable_or_bad_json(monkeypatch):
    monkeypatch.setattr(places, "_TABLE", None)
    _fake_places_file(monkeypatch, exc=OSError("文件没了"))
    assert places.table() == []
    monkeypatch.setattr(places, "_TABLE", None)
    _fake_places_file(monkeypatch, text="{{不是 json")
    assert places.table() == []                          # ValueError 分支
    monkeypatch.setattr(places, "_TABLE", None)
    _fake_places_file(monkeypatch, text='"光一个字符串"')
    assert places.table() == []                          # raw.get AttributeError 分支


def test_table_drops_bad_rows_and_blank_names(monkeypatch):
    import json
    monkeypatch.setattr(places, "_TABLE", None)
    _fake_places_file(monkeypatch, text=json.dumps({"places": [
        "junk",                                             # 不是 dict → 整行扔
        {"names": ["澳洲", "  "], "children": ["悉尼", " "]},   # 空白名 / 空白下级被滤掉
        {"names": []},                                      # 没 names → 扔
        {"children": ["x"]},                                # 只写下级没写名 → 扔
    ]}))
    assert places.table() == [{"names": ["澳洲"], "children": ["悉尼"]}]


def test_place_of_and_query_places_normalization(monkeypatch):
    monkeypatch.setattr(places, "_TABLE", None)          # 确保真表在
    assert places.place_of("AUSTRALIA") is not None       # norm：NFKC + casefold
    assert places.place_of("") is None and places.place_of(None) is None
    assert len(places.query_places(["澳洲", "澳大利亚"])) == 1        # 同一行两种叫法 → 一行
    got = [r["names"][0] for r in places.query_places(("日本", "澳洲"))]
    assert got == ["澳洲", "日本"]                          # 多国按表序去重
    assert places.query_places("") == [] and places.query_places([]) == []


def test_best_field_picks_highest_weight():
    assert places._best_field({"title": "澳洲 零食", "body": "澳洲"}, ["澳洲"]) == WEIGHTS["title"]
    assert places._best_field({"body": "澳洲"}, ["澳洲"]) == WEIGHTS["body"]
    assert places._best_field({"自定义字段": "澳洲"}, ["澳洲"]) == 1     # 表外字段默认权重 1
    assert places._best_field({"title": ""}, ["澳洲"]) == 0            # 空文本不算命中
    assert places._best_field({"title": "别的"}, ["澳洲"]) == 0


def test_facet_score_place_gate_child_discount_and_other_terms():
    row = places.place_of("澳洲")
    assert places.facet_score({"title": "好吃"}, [row], [(["好吃"], 0.5)]) == 0.0   # 没沾地名 → 0
    assert places.facet_score({"title": "澳洲 零食"}, [row], []) == pytest.approx(
        places.PLACE_SHARE * WEIGHTS["title"])                                     # 写明上级 = 字段权重
    assert places.facet_score({"title": "悉尼 自助"}, [row], []) == pytest.approx(
        places.PLACE_SHARE * places.CHILD_FACTOR * WEIGHTS["title"])               # 只写下级 = 八折
    assert places.facet_score({"title": "澳洲", "body": "好吃"}, [row], [(["好吃"], 0.5)]) == pytest.approx(
        places.PLACE_SHARE * WEIGHTS["title"] + 0.5 * WEIGHTS["body"])             # 其余核心词按份量加


def test_route_returns_child_mentions_only():
    items = [
        _item("tasty", "澳洲这个真的太好吃了", "好吃"),
        _item("syd", "悉尼女生这家自助", "chatswood 好吃"),
        _item("cs", "潮汕太好吃了", "好吃"),
    ]
    assert places.route(items, [places.place_of("澳洲")]) == ["syd"]   # 只有写下级地名的进这一路
    assert places.route(items, []) == []
    assert places.route(items, [{"names": ["x"], "children": []}]) == []


def test_boost_reorders_head_only_and_never_mutates_pool():
    tasty = _item("tasty", "澳洲这个真的太好吃了", "好吃")
    syd = _item("syd", "悉尼女生这家自助", "chatswood 好吃")
    cs = _item("cs", "潮汕太好吃了", "好吃")
    fillers = [_item(f"f{i}", f"日常记录 {i}", "学习") for i in range(5)]
    items = [tasty, syd, cs] + fillers
    pool = [cs, tasty, syd] + fillers
    out = places.boost(pool, ["好吃"], items, question="澳洲好吃的")
    assert [it["id"] for it in out] == ["tasty", "syd", "cs"] + [f"f{i}" for i in range(5)]
    assert [it["id"] for it in pool] == ["cs", "tasty", "syd"] + [f"f{i}" for i in range(5)]   # 入参不动

    one = [cs]
    assert places.boost(one, ["好吃"], items, question="澳洲好吃的") is one         # 池子 <2 原对象返回

    bulk = [_item(f"b{i}", f"bulk {i}", "bulk") for i in range(50)]
    big_pool = [cs] + bulk + [tasty, syd]        # head 里没有一个沾地名 / 核心词
    big_items = [tasty, syd, cs] + bulk
    assert places.boost(big_pool, ["好吃"], big_items, question="澳洲好吃的") is big_pool   # 全零分 → 原样
