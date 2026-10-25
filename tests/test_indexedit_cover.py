"""indexedit 的补充用例（现有 test_indexedit_1015.py 已盖改名换标签 / 挪动重缩进 / 合并递归 / 撤销被手改挡下）。

这里只补错误路径和早退分支：纯文本函数直接喂 SMALL 文本断言 EditError；入口的参数校验在碰盘之前返回。
"""

from __future__ import annotations

import pytest

from link_brain import indexedit as ie, indextree as it

SMALL = (
    "%% 说明 %%\n"
    "\t美食\n"
    "\t\t菜谱\n"
    "\t\t\t锅包肉\n"
    "\t\t综合\n"
    "\t游戏\n"
    "\t\t塞尔达\n"
    "\t\t宫崎英高\n"
    "\t\t\t血源（魂系）\n"
    "\t\t\t\t黑魂\n"
    "\t工程\n"
)

TWO_B = "\tA\n\t\tB\n\tC\n\t\tB\n"   # A 和 C 下面各有一个 B


def test_rename_missing_path_raises():
    with pytest.raises(ie.EditError, match="索引里没有"):
        ie.rename_text(SMALL, "美食/不存在", "随便")


def test_rename_to_same_name_returns_text_unchanged():
    assert ie.rename_text(SMALL, "美食/菜谱", "菜谱") == SMALL


def test_move_into_missing_parent_raises():
    with pytest.raises(ie.EditError, match="索引里没有"):
        ie.move_text(SMALL, "美食/菜谱", "没有这个分类")


def test_move_onto_same_name_sibling_raises():
    with pytest.raises(ie.EditError, match="已经有「B」了"):
        ie.move_text(TWO_B, "A/B", "C")


def test_move_before_self_returns_text_unchanged():
    assert ie.move_text(SMALL, "美食/综合", "美食", before="美食/综合") == SMALL


def test_merge_error_paths():
    with pytest.raises(ie.EditError, match="不能并进它自己$"):
        ie.merge_text(SMALL, "美食", "美食")
    with pytest.raises(ie.EditError, match="不能并进它自己下面的子类"):
        ie.merge_text(SMALL, "美食", "美食/菜谱")
    with pytest.raises(ie.EditError, match="索引里没有"):
        ie.merge_text(SMALL, "美食", "没有这个分类")
    with pytest.raises(ie.EditError, match="超过"):
        # dst 在第 3 级、src「游戏」高 3 级：并过去会超过 MAX_DEPTH
        assert it.MAX_DEPTH == 3
        ie.merge_text(SMALL, "游戏", "美食/菜谱/锅包肉")


def test_undo_unknown_uid_refuses(tmp_path):
    out = ie.undo("no-such-uid", tmp_path)
    assert out["ok"] is False and out["code"] == ie.ARGS and "太早" in out["message"]


def test_edit_entry_validates_op_and_path_before_touching_disk(tmp_path):
    out = ie.edit("bogus", "美食", vault=tmp_path)
    assert out["ok"] is False and out["code"] == ie.ARGS and "不认识的操作" in out["message"]
    out = ie.edit("rename", "", vault=tmp_path)
    assert out["ok"] is False and out["code"] == ie.ARGS and "没说改哪个分类" in out["message"]
