"""r5 补测：索引 AI 的本地半边（摘要/签名/模型输出解析/计费/路径认领；模型调用一概不碰）。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from link_brain import indexai as ia


def test_summary_fallback_and_limit():
    it = {"summary": "  多  空白\n的概要 ", "search_fields": {"body": "正文"}}
    assert ia._summary(it) == "多 空白 的概要"          # 空白折叠
    assert ia._summary(it, 3) == "多 空"                # 截限按字符数
    assert ia._summary({"search_fields": {"body": " b1 b2 "}}) == "b1 b2"   # 没概要用正文
    assert ia._summary({}) == ""
    assert ia.item_sig({"title": "t", "tags": ["a"], "summary": "s"}) == \
        ia.item_sig({"title": "t", "tags": ["a"], "summary": "s"})
    assert ia.item_sig({"title": "t", "tags": ["a"], "summary": "s"}) != \
        ia.item_sig({"title": "t", "tags": ["a"], "summary": "变了"})


def test_item_line_shape():
    line = ia.item_line(2, {"title": "标  题", "tags": ["#做饭", "烤箱", "", "  "], "summary": "概要"})
    assert line == "2. 标 题｜标签：做饭、烤箱｜概要"
    assert ia.item_line(1, {}) == "1. （无标题）｜标签：无｜（没有概要）"
    assert ia.item_line(1, {"title": "t", "search_fields": {"body": "正文正文"}}, summary=4) == \
        "1. t｜标签：无｜正文正文"                      # 概要限长可传参（正文兜底也算）


def test_as_int_strict():
    assert ia._as_int("3") == 3 and ia._as_int(3) == 3 and ia._as_int(" 4 ") == 4
    assert ia._as_int(True) is None                     # 布尔不算数
    assert ia._as_int("3.7") is None and ia._as_int(None) is None and ia._as_int("") is None


def test_rows_parse_model_output_defensively():
    good = '{"r": [{"i": 1, "n": ["a"]}, [1], "x", {"i": 2}]}'
    assert ia._rows(good, "r") == [{"i": 1, "n": ["a"]}, {"i": 2}]   # 非对象条目丢掉
    assert ia._rows('{"r": [{"i": 1}, {"i": 2', "r") == [{"i": 1}]   # 写到一半截断：留下完整的那几条
    assert ia._rows("完全不是 JSON", "r") == []
    assert ia._rows('{"别的": 1}', "r") == []
    assert ia._rows('["整包是个数组"]', "r") == []


def test_meter_counts_tokens_errors_and_yuan():
    m = ia.Meter("unknown-model")
    m.add({"status": "ok", "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
    m.add({"status": "ok", "usage": {"input_tokens": 30, "output_tokens": 20}})   # 旧字段名也能认
    m.add({"status": "error", "error": "炸了"})                                   # 没给 code 用默认码
    assert m.calls == 3 and m.tin == 130 and m.tout == 70
    assert m.errors == [{"code": "TRANSIENT.SERVICE_BUSY", "error": "炸了"}]
    assert m.dump() == {"model": "unknown-model", "calls": 3, "tokens_in": 130, "tokens_out": 70,
                        "yuan": None}              # 价格表查不到只记 token
    m2 = ia.Meter("deepseek-flash")
    m2.add({"status": "ok", "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})
    assert m2.dump()["yuan"] == round(ia.price("deepseek-flash", 1000, 500), 4)   # 按价格表算


def test_resolve_path_tolerates_model_sloppiness():
    table = {"美食/菜谱": NS(path="美食/菜谱"), "美食": NS(path="美食"), "游戏": NS(path="游戏")}
    # 模型常把整行抄回来：——说明、（包括：…）都剥掉再认
    assert ia.resolve_path("美食/菜谱——红烧肉都放这（包括：糖醋排骨）", table).path == "美食/菜谱"
    assert ia.resolve_path(" 游戏  /  菜谱 ", table).path == "美食/菜谱"      # 分隔符 / 空格宽松、唯一末级名
    assert ia.resolve_path("不存在的路径", table) is None                      # 对不上就是 None，不猜
    table2 = {"美食/菜谱": NS(path="美食/菜谱"), "游戏/菜谱": NS(path="游戏/菜谱")}
    assert ia.resolve_path("菜谱", table2) is None                            # 末级名撞了两个 → 不要


def test_direct_members_and_unclassified_and_leftover_due():
    cache = {"items": {"a": {"paths": ["美食/菜谱", "美食"]}, "b": {"paths": ["美食/菜谱"]},
                       "c": {"paths": []}, "d": {"paths": ["没了的节点"]}, "e": {}}}
    present = {"a", "b", "c", "d", "e"}
    assert ia.direct_members(cache, present) == {"美食/菜谱": ["a", "b"], "美食": ["a"], "没了的节点": ["d"]}  # 只按缓存报，不查树在不在
    assert ia.ai_unclassified(cache, present) == ["c"]     # 明确判过「哪类都不是」的（有 paths 键且为空）
    assert ia._leftover_due(cache, present) is True        # 有放不进的且没跑过分组 → 该跑
    cache["leftover"] = {"hash": ia._h(["c"])}
    assert ia._leftover_due(cache, present) is False       # 同一批放不进的已跑过 → 不重跑
    # 只看还在这台机器上的篇：下架的不算
    assert ia.direct_members(cache, {"a"}) == {"美食/菜谱": ["a"], "美食": ["a"]}
    assert ia.ai_unclassified(cache, {"c"}) == ["c"] and ia.ai_unclassified(cache, set()) == []


def test_outline_lines_and_table():
    parsed = NS(walk=lambda: [
        NS(virtual=False, path="美食", name="美食", desc="吃的", hints=["做饭"], tags=["t"], explicit=False, open=True),
        NS(virtual=False, path="美食/菜谱", name="菜谱", desc="", hints=[], tags=[], explicit=True, open=False),
        NS(virtual=True, path="虚拟", name="虚拟", desc="v", hints=[], tags=[], explicit=False, open=False),
    ])
    text, table = ia.outline(parsed)
    assert text == "美食——吃的（包括：做饭）\n美食/菜谱"
    assert set(table) == {"美食", "美食/菜谱"}             # 虚拟节点不进表


def test_group_id_stable():
    assert ia.group_id("美食", "菜谱") == ia.group_id("美食", "菜谱")
    assert ia.group_id("美食", "菜谱") != ia.group_id("美食", "烤箱")
    assert len(ia.group_id("", "名字")) == 10
