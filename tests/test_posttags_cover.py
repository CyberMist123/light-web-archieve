"""r5 补测：帖子细分标签（纯函数 + tmp vault 落盘；模型调用不打桩不触发——只测无模型的路径）。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from link_brain import posttags as pt


def test_clean_name_rules():
    assert pt.clean("空气炸锅") == "空气炸锅"
    assert pt.clean("  Vibe Coding ") == "Vibe Coding"
    assert pt.clean("做饭 ") == "做饭"                       # 2 个字起步
    assert pt.clean("买") == "" and pt.clean("a") == ""      # 太短
    assert pt.clean("九个字的标签名字哦") == ""               # 中文上限 8 字，超长整个不要（不截）
    assert pt.clean("abcdefghijklmnopq") == ""               # 英文上限 16 字符
    assert pt.clean("教程") == "" and pt.clean("好物分享") == ""  # 空词表
    assert pt.clean("A/B：C，D") == "A B C D"                # 会弄坏写法的符号换成空格


def test_final_tags_human_wins():
    p = {"ai": ["牛排", "做梦"], "human_add": ["牛排", "悉尼"], "human_remove": ["做梦"]}
    assert pt.final_tags(p) == ["牛排", "悉尼"]      # ai + 她加的，去重、按序；她去掉的永远赢
    assert pt.final_tags({}) == []
    assert pt.final_tags({"ai": ["a"], "human_remove": ["A"]}) == []  # 去掉按 key 比，大小写不敏感


def test_vocab_canon_alias_and_top():
    d = {"version": 1, "vocab": {"空气炸锅": {"aliases": ["气炸锅"]}}, "posts": {}}
    voc = pt.Vocab(d)
    assert voc.canon("气炸锅") == "空气炸锅"           # 别名归到规范名
    assert voc.canon("全新名字") == "全新名字" and "全新名字" in d["vocab"]  # 没见过就收进词表
    assert pt.Vocab({"vocab": {}, "posts": {}}).canon("查无此词", add=False) == ""  # 不许新增时查不到就是空
    d2 = {"vocab": {}, "posts": {"a": {"ai": ["牛排", "做梦"]}, "b": {"ai": ["牛排"]}, "c": {"human_add": ["牛排"]}}}
    assert pt.Vocab(d2).top(5) == ["牛排", "做梦"]      # 按篇数排


def test_load_save_stamp_roundtrip(tmp_path):
    assert pt.load(tmp_path) == {"version": 1, "vocab": {}, "posts": {}}   # 没有文件 = 空库
    assert pt.stamp(tmp_path) == ""
    d = {"version": 1, "vocab": {"做饭": {"aliases": []}}, "posts": {"i1": {"ai": ["做饭"]}}}
    pt.save(d, tmp_path)
    assert pt.load(tmp_path)["posts"]["i1"]["ai"] == ["做饭"]
    assert pt.stamp(tmp_path) != ""
    (tmp_path / "_archive" / pt.DATA_NAME).write_text("{坏 json", encoding="utf-8")
    assert pt.load(tmp_path)["posts"] == {}          # 读不了回空库，不抛


def test_edit_add_remove_records_history(tmp_path):
    r = pt.edit(["i1"], "add", "空气炸锅", vault=tmp_path)
    assert r["ok"] is True and r["undo"].startswith("t:") and r["tag"] == "空气炸锅"
    d = pt.load(tmp_path)
    assert d["posts"]["i1"]["human_add"] == ["空气炸锅"] and pt.final_tags(d["posts"]["i1"]) == ["空气炸锅"]
    rows = pt.history(tmp_path, item="i1")
    assert len(rows) == 1 and rows[0]["who"] == "human" and rows[0]["op"] == "add"
    assert rows[0]["before"] == [] and rows[0]["after"] == ["空气炸锅"]
    # 参数不齐 / 空词名：拒绝并说明
    bad = pt.edit([], "add", "做饭", vault=tmp_path)
    assert bad["ok"] is False and bad["code"] == "PERMANENT.STEP_ARGS"
    assert pt.edit(["i1"], "add", "教程", vault=tmp_path)["ok"] is False
    # 去掉：记 human_remove，AI 打的同名也压掉
    pt.edit(["i1"], "remove", "空气炸锅", vault=tmp_path)
    d = pt.load(tmp_path)
    assert d["posts"]["i1"]["human_add"] == [] and d["posts"]["i1"]["human_remove"] == ["空气炸锅"]


def test_restore_by_undo_id_reverts_that_step(tmp_path):
    u1 = pt.edit(["i1"], "add", "做饭", vault=tmp_path)["undo"]
    u2 = pt.edit(["i1"], "add", "牛排", vault=tmp_path)["undo"]
    assert pt.final_tags(pt.load(tmp_path)["posts"]["i1"]) == ["做饭", "牛排"]
    # 恢复第二步：回到只有「做饭」
    assert pt.restore(u2, vault=tmp_path)["ok"] is True
    assert pt.final_tags(pt.load(tmp_path)["posts"]["i1"]) == ["做饭"]
    rows = pt.history(tmp_path, item="i1")
    assert rows[-1]["op"] == "restore" and rows[-1]["who"] == "human" and rows[-1]["after"] == ["做饭"]
    # 历史里没有的号：恢复不了
    assert pt.restore("t:deadbeef", vault=tmp_path)["ok"] is False


def test_pending_only_new_or_changed():
    d = {"version": 1, "vocab": {}, "posts": {}}
    items = [{"id": "a", "title": "t", "tags": [], "summary": "s"}, {"id": "b", "title": "t2", "tags": [], "summary": "s2"}]
    assert pt.pending(items, d) == ["a", "b"]        # 都是新的
    from link_brain.indexai import item_sig
    d["posts"] = {"a": {"sig": item_sig(items[0])}}
    assert pt.pending(items, d) == ["b"]             # 没变的不再打
    items[1]["summary"] = "内容变了"
    d["posts"]["b"] = {"sig": item_sig({"id": "b", "title": "t2", "tags": [], "summary": "s2"})}
    assert pt.pending(items, d) == ["b"]             # 内容变了的重打


def test_local_tags_falls_back_to_own_tags():
    it = {"tags": ["做饭", "教程", "买", "空气炸锅", "牛排", "悉尼", "做梦", "情绪", "换窗", "拌面", "减脂", "烤箱", "咖啡", "蛋糕", "面包"]}
    out = pt.local_tags(it)
    assert out == ["做饭", "空气炸锅", "牛排", "悉尼", "做梦", "情绪"]  # 清洗后最多 6 个
    assert pt.local_tags({}) == []


def test_node_facets_top_other_and_ban():
    n1 = NS(virtual=False, name="做饭", path="/做饭", children=[], hints=["灶具"])
    n2 = NS(virtual=True, name="虚拟", path="/虚拟", children=[], hints=[])
    parsed = NS(walk=lambda: [n1, n2])
    result = NS(order={"i1": 2, "i2": 1, "i3": 3, "i4": 0}, total={id(n1): {"i1", "i2", "i3", "i4"}, id(n2): {"i1"}})
    d = {"posts": {"i1": {"ai": ["空气炸锅", "灶具"]}, "i2": {"ai": ["空气炸锅"]},
                   "i3": {"ai": ["空气炸锅", "牛排"]}, "i4": {"ai": ["牛排"]}}}
    out = pt.node_facets(parsed, result, d)
    assert list(out) == ["/做饭"]                     # 虚拟节点不列
    assert out["/做饭"] == [
        {"name": "空气炸锅", "count": 3, "items": ["i2", "i1", "i3"]},   # ≥3 篇单列；items 按目录顺序
        {"name": "其他", "count": 2, "items": ["i4", "i3"], "other": True},  # 不足 3 篇的收进「其他」
    ]   # 节点名「做饭」和 hint「灶具」不算细分
