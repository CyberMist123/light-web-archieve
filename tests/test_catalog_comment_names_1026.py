"""1026 她：评论里 @ 的人名、「回复 某某：」不进检索（「喵喵」搜出一堆只是 @ 了叫喵喵的人的帖子）。"""
from link_brain.catalog import _comment_search_text


def test_at_names_and_reply_prefix_are_dropped():
    assert _comment_search_text("铲小毛孩 @明明明明明 @momo 有小猫喜欢看的吗 @喵喵酱 [色色R]好可爱") == "铲小毛孩 有小猫喜欢看的吗 [色色R]好可爱"
    assert _comment_search_text("回复 喵喵酱：哈哈 好的") == "哈哈 好的"
    assert "喵喵" not in _comment_search_text("@喵喵 你看这个")


def test_content_is_kept():
    assert _comment_search_text("小猫咪喵喵叫") == "小猫咪喵喵叫"
    assert _comment_search_text("邮箱 a@b.com 不算人名") == "邮箱 a@b.com 不算人名"
    assert _comment_search_text(None) == ""
