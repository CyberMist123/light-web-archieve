"""r5 补测：来源接口层（纯注册表 + 异常分层 + 数据类，不出网、不起进程）。"""
from __future__ import annotations

import pytest

from link_brain import sources
from link_brain.sources import FetchOptions, Fetched


def test_error_hierarchy_separates_batch_stop_from_single_note():
    assert sources.SourceError.code == "" and isinstance(sources.NeedsHuman("x"), sources.SourceError)
    # 号 / 服务出事 = 要停车叫人
    assert issubclass(sources.AccountBlocked, sources.NeedsHuman)
    assert issubclass(sources.ServiceDown, sources.NeedsHuman)
    # 1011 单篇受限：只是这一篇，绝不能误判成停车类
    exc = sources.ItemRestricted("这篇打不开")
    assert isinstance(exc, sources.SourceError) and not isinstance(exc, sources.NeedsHuman)
    assert exc.code == "NOTE_RESTRICTED"


def test_fetch_options_defaults_are_isolated():
    a, b = FetchOptions(), FetchOptions()
    assert a.refresh is False and a.comment_floors is None and a.budget_left is None and a.progress is None
    assert a.log("whatever") is None  # 默认 log 是安静的无操作
    assert a.extra == {} and a.extra is not b.extra  # default_factory：各实例各一份


def test_fetched_context_default():
    f1, f2 = Fetched(raw_files={"mcp_raw.json": {}}), Fetched(raw_files={})
    assert f1.context == {} and f1.context is not f2.context


def test_get_returns_registered_module_and_rejects_unknown():
    assert sources.names() == ["xiaohongshu"]
    mod = sources.get("xiaohongshu")
    assert mod.name == "xiaohongshu" and mod.version == "xiaohongshu/1"
    assert "favorites_sync" in mod.capabilities and isinstance(mod.capabilities, frozenset)
    with pytest.raises(sources.SourceError, match="未知来源"):
        sources.get("no_such_source")


def test_detect_pulls_xhs_urls_in_order_and_dedups_exact():
    text = ("看 https://www.xiaohongshu.com/explore/6512abc123def456abc123de?x=1"
            " 和 https://github.com/a/b 不认"
            " 重复 https://www.xiaohongshu.com/explore/6512abc123def456abc123de?x=1"
            " 变体 https://www.xiaohongshu.com/explore/6512abc123def456abc123de。")
    found = sources.detect(text)
    # 顺序保留、整串精确去重；?x=1 与去掉参数的是两条不同链接；非小红书域名不收；句尾标点被剥掉
    assert [(s.name, u) for s, u in found] == [
        ("xiaohongshu", "https://www.xiaohongshu.com/explore/6512abc123def456abc123de?x=1"),
        ("xiaohongshu", "https://www.xiaohongshu.com/explore/6512abc123def456abc123de"),
    ]
    assert sources.detect("没有任何链接") == [] and sources.detect("") == []
