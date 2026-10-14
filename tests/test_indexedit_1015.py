"""1015 索引大纲树：目录页改名 / 拖拽挪 / 合并 → 写回 索引.md（格式照旧、只动那几行、可撤销、AI 归类不白花钱）；
第 4 级并进第 3 级只算说明（不再「有 N 处写法要看一眼」）；1–2 篇的细分收进「其他」。"""

from __future__ import annotations

import json

import pytest

from link_brain import cli, indexai, indexedit as ie, indextree as it, posttags
from test_indexai_1011 import ITEMS, OWNER, fake, rows, vault, write_catalog, write_index  # noqa: F401 - fixture

SMALL = (
    "%% 说明 %%\n"
    "\t美食\n"
    "\t\t菜谱\n"
    "\t\t\t锅包肉\n"
    "\t\t\t牛排：煎牛排, 原切\n"
    "\t\t综合\n"
    "\t游戏\n"
    "\t\t塞尔达, 斯普拉遁\n"
    "\t\t宫崎英高\n"
    "\t\t\t血源（魂系）\n"
    "\t\t\t\t黑魂\n"
    "\t工程\n"
    "\t\t前端设计 [wiki]\n"
)


def paths(text):
    return [n.path for n in it.parse(text).walk()]


# ── 纯文本改写 ──

def test_rename_keeps_tags_desc_wiki_and_old_name_as_keyword():
    out = ie.rename_text(SMALL, "美食/菜谱", "食谱")
    assert "\t\t食谱：菜谱\n" in out and "美食/食谱/锅包肉" in paths(out)
    out = ie.rename_text(SMALL, "美食/菜谱/牛排", "牛扒")
    assert "\t\t\t牛扒：煎牛排, 原切\n" in out          # 写了标签的：只换名字
    out = ie.rename_text(SMALL, "游戏/宫崎英高/血源", "血源诅咒")
    assert "血源诅咒（魂系）：血源" in out               # 说明括号原样
    out = ie.rename_text(SMALL, "工程/前端设计", "前端")
    assert "前端：前端设计 [wiki]" in out and it.parse(out).find("工程/前端").wiki
    # 一行几个的：先拆出来，别的不动
    out = ie.rename_text(SMALL, "游戏/斯普拉遁", "喷射战士")
    assert "\t\t塞尔达\n\t\t喷射战士：斯普拉遁\n" in out
    assert out.startswith("%% 说明 %%\n")
    with pytest.raises(ie.EditError):
        ie.rename_text(SMALL, "美食/菜谱", "综合")        # 同级撞名
    with pytest.raises(ie.EditError):
        ie.rename_text(SMALL, "美食/菜谱", "  ")


def test_move_reindents_subtree_and_keeps_format():
    out = ie.move_text(SMALL, "美食/菜谱/牛排", "游戏")
    assert "\t\t牛排：煎牛排, 原切\n" in out and "游戏/牛排" in paths(out) and "美食/菜谱/牛排" not in paths(out)
    out = ie.move_text(SMALL, "工程", "美食")         # 第一级挪进第二级：子节点跟着往里缩
    assert "\t\t工程\n\t\t\t前端设计 [wiki]\n" in out and "美食/工程/前端设计" in paths(out)
    out = ie.move_text(SMALL, "游戏/宫崎英高", "", before="美食")   # 提到第一级、插在最前面
    assert paths(out)[0] == "宫崎英高" and "宫崎英高/血源/黑魂" in paths(out)
    out = ie.move_text(SMALL, "美食/综合", "美食", before="菜谱")    # 同级换顺序
    assert [n.name for n in it.parse(out).find("美食").children] == ["综合", "菜谱"]
    assert not [w for w in it.parse(out).warnings if w.get("level") != "info"]
    with pytest.raises(ie.EditError):
        ie.move_text(SMALL, "美食", "游戏")             # 超过 3 级
    with pytest.raises(ie.EditError):
        ie.move_text(SMALL, "美食", "美食/菜谱")         # 挪进自己下面
    with pytest.raises(ie.EditError):
        ie.move_text(SMALL, "美食/综合", "游戏/宫崎英高/血源")  # 第 3 级下面不能再放


def test_move_space_indented_file_uses_its_unit():
    text = "- 美食\n  - 菜谱\n  - 综合\n- 游戏\n  - 塞尔达\n"
    out = ie.move_text(text, "美食/综合", "游戏")
    assert out == "- 美食\n  - 菜谱\n- 游戏\n  - 塞尔达\n  - 综合\n"


def test_merge_moves_children_adds_tags_and_removes_source():
    out = ie.merge_text(SMALL, "工程", "游戏")
    assert "\t游戏：游戏, 工程\n" in out and "游戏/前端设计" in paths(out) and "工程" not in paths(out)
    out = ie.merge_text(SMALL, "美食/综合", "美食/菜谱")
    assert "综合" in it.parse(out).find("美食/菜谱").tags and "美食/综合" not in paths(out)
    with pytest.raises(ie.EditError):
        ie.merge_text(SMALL, "美食", "美食/菜谱")


def test_merge_same_name_children_recursively():
    text = "A\n\tx\n\t\tp\nB\n\tx\n\t\tq\n"
    out = ie.merge_text(text, "A", "B")
    assert paths(out) == ["B", "B/x", "B/x/q", "B/x/p"] and not it.parse(out).warnings


# ── 写盘 + 路径跟着改 + 撤销 ──

def test_edit_rename_remaps_overrides_and_ai_cache_no_rebilling(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    indexai.run(vault)
    indexai.assign(["xhs-0006"], "move", "游戏/游戏推荐", vault)
    before = rows(it.load(vault, fresh=False))
    calls = len(fake.calls)
    r = ie.edit("rename", "游戏/游戏", name="单机", vault=vault)
    assert r["ok"] and r["path"] == "游戏/单机" and r["undo"]
    data = it.load(vault, fresh=False)
    new = rows(data)
    assert sorted(new["游戏/单机/宫崎英高"]["items"]) == sorted(before["游戏/游戏/宫崎英高"]["items"])
    assert data["assign"]["xhs-0006"] == ["游戏/游戏推荐"]
    est = indexai.estimate(vault)
    assert est["pending"] == 0 and not est["changed"], est      # 改名不重判、不花钱
    assert len(fake.calls) == calls
    text = (vault / "索引.md").read_text(encoding="utf-8")
    assert "\t\t单机：游戏\n" in text and text.startswith("%%\n写法说明\n%%")
    assert list((vault / "_archive" / "index-history").glob("索引-*-rename.txt"))
    # 撤销
    u = ie.edit("undo", r["undo"], vault=vault)
    assert u["ok"] and (vault / "索引.md").read_text(encoding="utf-8") == OWNER
    assert "游戏/游戏/宫崎英高" in rows(it.load(vault, fresh=False))


def test_edit_move_and_merge_paths_and_undo_refuses_after_hand_edit(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    indexai.run(vault)
    before = rows(it.load(vault, fresh=False))
    r = ie.edit("move", "美食/菜谱", to="", vault=vault)
    assert r["ok"] and r["path"] == "菜谱"
    new = rows(it.load(vault, fresh=False))
    assert sorted(new["菜谱/锅包肉"]["items"]) == sorted(before["美食/菜谱/锅包肉"]["items"])
    m = ie.edit("merge", "游戏/游戏推荐", to="游戏/游戏", vault=vault)
    assert m["ok"]
    new = rows(it.load(vault, fresh=False))
    assert "游戏/游戏推荐" not in new
    assert set(before["游戏/游戏推荐"]["items"]) <= set(new["游戏/游戏"]["items"])
    # 她在编辑器里又改了 → 不撤
    p = vault / "索引.md"
    p.write_text(p.read_text(encoding="utf-8") + "\t新加\n", encoding="utf-8")
    u = ie.edit("undo", m["undo"], vault=vault)
    assert not u["ok"] and "又改过" in u["message"]
    bad = ie.edit("move", "美食", to="游戏/游戏", vault=vault)
    assert not bad["ok"] and bad["code"] == "PERMANENT.STEP_ARGS"
    assert not ie.edit("rename", "没有这个", name="x", vault=vault)["ok"]


def test_cli_index_edit(vault, fake, capsys):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    code = cli.main(["index", "edit", "--op", "rename", "--path", "同人/瓶邪", "--name", "盗笔"])
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and j["ok"] and "盗笔" in j["message"] and j["undo"]
    code = cli.main(["index", "edit", "--op", "move", "--path", "同人", "--to", "美食/菜谱"])
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 2 and not j["ok"] and "3 级" in j["message"]


# ── 写法提示：第 4 级并进第 3 级 = 说明，不算要看一眼 ──

def test_fourth_level_is_info_not_warning():
    p = it.parse(OWNER)
    assert p.warnings and all(w.get("level") == "info" for w in p.warnings if "第 4 级" in w["text"])
    assert it.real_warnings(p.warnings) == []
    p2 = it.parse("A\nA\n")
    assert len(it.real_warnings(p2.warnings)) == 1


# ── 细分：1–2 篇的收进「其他」 ──

def test_small_facets_fold_into_other():
    class N:
        def __init__(self, name):
            self.name, self.children, self.hints, self.path, self.virtual = name, [], [], name, False

    n = N("职业")

    class P:
        def walk(self):
            return [n]

    ids = [f"i{k}" for k in range(8)]

    class R:
        total = {id(n): set(ids)}
        order = {i: k for k, i in enumerate(ids)}

    posts = {i: {"tags": []} for i in ids}
    for i in ids[:4]:
        posts[i]["tags"].append("法务")
    posts["i4"]["tags"].append("大厂法务")
    posts["i5"]["tags"].append("大厂法务")
    posts["i6"]["tags"].append("米哈游")
    d = {"posts": {i: {"human_add": p["tags"]} for i, p in posts.items()}}
    out = posttags.node_facets(P(), R(), d)["职业"]
    assert [f["name"] for f in out] == ["法务", "其他"]
    assert out[-1]["other"] and out[-1]["items"] == ["i4", "i5", "i6"]
