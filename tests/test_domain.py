"""第二波 PR①（1025）：规则收进 domain.py——身份 id、在库判断、收藏口径、meta 字段归属、重抓合并。

domain 只判断、不碰文件、不 import 任何 link_brain 模块（`test_domain_imports_nothing_from_link_brain` 守着）。
修前红的两条：`test_tg_share_counts_as_fable`（修前 TG 发来的是「聊天分享」）、`test_refetch_keeps_downloaded_attachments`
（第一波已修，这里随 merge_meta 一起搬过来守着）。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from link_brain import domain
from link_brain.domain import Lookup, Owner, Presence, Probe

ROOT = Path(__file__).resolve().parents[1]


# ---- 纯函数：不 import 任何 link_brain 模块 --------------------------------------------------------


def test_domain_imports_nothing_from_link_brain():
    tree = ast.parse((ROOT / "link_brain" / "domain.py").read_text("utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.startswith("link_brain")]
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").startswith("link_brain"):
                bad.append(f"from {'.' * node.level}{node.module or ''} import …")
    assert bad == [], f"domain 只许 import 标准库：{bad}"


# ---- 身份 -----------------------------------------------------------------------------------------


def test_item_id_round_trip_and_short_id():
    assert domain.item_id("xiaohongshu", "6512ab") == "xhs-6512ab"
    assert domain.parse_item_id("xhs-6512ab") == ("xiaohongshu", "6512ab")
    assert domain.parse_item_id("xhs-a-b") == ("xiaohongshu", "a-b")   # id 里带横线只切第一刀
    assert domain.short_id("xhs-6512ab") == "6512ab" and domain.short_id("6512ab") == "6512ab"
    assert domain.short_id(" xhs-1 ") == "1"
    assert domain.short_id("xhs-") == ""          # 和原来 removeprefix 的结果一样，别拼出 xhs-xhs-


@pytest.mark.parametrize("text", ["", "xhs-", "bili-1", "6512ab", None, "https://x/y"])
def test_parse_item_id_rejects_unknown_shapes(text):
    assert domain.parse_item_id(text) is None


def test_item_id_refuses_to_guess():
    with pytest.raises(ValueError):
        domain.item_id("bilibili", "1")
    with pytest.raises(ValueError):
        domain.item_id("xiaohongshu", "")
    with pytest.raises(ValueError):
        domain.item_id("xiaohongshu", None)


# ---- 在库 / 已删 / 新帖 ----------------------------------------------------------------------------


@pytest.mark.parametrize("probe, expect", [
    (Probe(in_index=False, has_meta=False, tombstoned=False), Lookup(Presence.NEW)),
    (Probe(in_index=True, has_meta=False, tombstoned=False), Lookup(Presence.NEW)),                 # 索引是旧的
    (Probe(in_index=True, has_meta=True, tombstoned=False), Lookup(Presence.IN_LIBRARY)),
    (Probe(in_index=False, has_meta=True, tombstoned=False), Lookup(Presence.IN_LIBRARY, needs_reindex=True)),
    (Probe(in_index=False, has_meta=False, tombstoned=False, complete_versions=(1,)), Lookup(Presence.ORPHAN)),
    (Probe(in_index=True, has_meta=True, tombstoned=True, complete_versions=(1, 2)), Lookup(Presence.DELETED)),  # 墓碑最优先
])
def test_lookup_states_and_priority(probe, expect):
    assert domain.lookup(probe) == expect


def test_needs_fetch():
    assert domain.needs_fetch(Lookup(Presence.NEW), refresh=False) is True
    assert domain.needs_fetch(Lookup(Presence.IN_LIBRARY), refresh=False) is False
    assert domain.needs_fetch(Lookup(Presence.IN_LIBRARY), refresh=True) is True
    assert domain.needs_fetch(Lookup(Presence.DELETED), refresh=True) is False     # 删了就是删了，refresh 也不拉回
    assert domain.needs_fetch(Lookup(Presence.ORPHAN), refresh=True) is False      # 收编，不联网


def test_write_decision():
    assert domain.write_decision(None, "a", committed=False) == "write"
    assert domain.write_decision("a", "a", committed=False) == "write"
    assert domain.write_decision("a", "a", committed=True) == "touch"
    assert domain.write_decision("a", "b", committed=True) == "write"


# ---- 收藏口径（1023 她定）---------------------------------------------------------------------------


def test_is_favorite_any_account_and_legacy_ingest_kind():
    assert domain.is_favorite({"favorited_by": [{"user_id": "u1"}]}) is True
    assert domain.is_favorite({"favorited_by": [{"nickname": "n"}], "ingest_kind": "shared"}) is True
    assert domain.is_favorite({"ingest_kind": "favorite"}) is True            # 老数据兜底
    assert domain.is_favorite({"ingest_kind": "shared", "favorited_by": []}) is False
    assert domain.is_favorite({}) is False


def test_account_key_prefers_user_id():
    assert domain.account_key({"user_id": "u", "nickname": "n"}) == "u"
    assert domain.account_key({"nickname": "n"}) == "n"
    assert domain.account_key({"user_id": "", "nickname": ""}) == ""


def test_tg_share_counts_as_fable():
    """修前：origin=tg 的人工分享记成「聊天分享」单独一组；修后并进 fable，via 记 tg。"""
    meta = {"origin": "tg", "actor": "human", "ingest_kind": "shared"}
    assert domain.collected_by(meta) == domain.FABLE
    assert domain.via(meta) == "tg"
    assert domain.via({"origin": "tg", "actor": "ai:fable"}) == ""


def test_collected_by_rules():
    assert domain.collected_by({"origin": "cli", "actor": "human", "ingest_kind": "favorite"}) == ""
    assert domain.collected_by({"origin": "cli", "actor": "human", "ingest_kind": "shared"}) == ""   # 网页导入 = 我的收藏
    assert domain.collected_by({"origin": "tg", "actor": "ai:fable"}) == "fable"
    assert domain.collected_by({"origin": "cc", "actor": "ai:cc", "project": "ai群聊"}) == "ai群聊"
    assert domain.collected_by({"origin": "cli", "actor": "ai:gpt"}) == "gpt"
    assert domain.collected_by({"actor": "robot"}) == "robot"
    assert domain.collected_by({"origin": "tg", "actor": "human", "favorited_by": [{"user_id": "u"}]}) == ""   # 后来她收藏了


def test_clean_project():
    assert domain.clean_project("  ai 群聊 ") == "ai 群聊"
    assert domain.clean_project("a/b\\c") == "a-b-c"
    assert len(domain.clean_project("x" * 100)) == 40


# ---- meta 字段归属 + 重抓合并 ---------------------------------------------------------------------------


def test_field_owner_table_is_consistent():
    assert domain.FETCH_OWNED == domain.keys_owned_by(Owner.FETCH)
    assert {"title", "versions", "current_version", "item_id"} <= domain.FETCH_OWNED
    assert domain.FIELD_OWNER["attachments_status"] is Owner.ATTACH and "attachments_status" not in domain.FETCH_OWNED
    assert domain.FIELD_OWNER["favorited_by"] is Owner.SYNC
    assert domain.FIELD_OWNER["ingest_kind"] is Owner.ENTRY     # 第一次怎么进来的，重抓不覆盖
    assert domain.FIELD_OWNER["space"] is Owner.ENTRY and domain.space_of({}) == "knowledge"
    assert "comment_load" not in domain.FIELD_OWNER   # 不是 meta 字段（在 source.json.capture）


def test_merge_meta_fetch_owned_fields_win_and_others_kept():
    old = {"title": "旧", "versions": [1], "project": "graph", "favorited_by": [{"user_id": "u"}], "note": None}
    fetched = {"title": "新", "versions": [1, 2], "note": "n"}
    merged = domain.merge_meta(old, fetched)
    assert merged["title"] == "新" and merged["versions"] == [1, 2]
    assert merged["project"] == "graph" and merged["favorited_by"] == [{"user_id": "u"}]
    assert merged["note"] == "n"                                   # 旧的是 None 才用新的
    assert domain.merge_meta(None, fetched) == fetched


def test_merge_meta_empty_title_falls_back_to_old():
    assert domain.merge_meta({"title": "视频兜底标题"}, {"title": ""})["title"] == "视频兜底标题"
    assert domain.merge_meta({"title": "旧"}, {"title": "新"})["title"] == "新"


def test_refetch_keeps_downloaded_attachments():
    assert domain.merge_meta({"attachments_status": "downloaded"}, {"attachments_status": "metadata_only"})["attachments_status"] == "downloaded"
    assert domain.merge_meta({"attachments_status": "downloaded"}, {"attachments_status": "none"})["attachments_status"] == "none"
    assert domain.merge_meta({"attachments_status": "metadata_only"}, {"attachments_status": "downloaded"})["attachments_status"] == "downloaded"
    assert domain.merge_meta({"attachments_status": "downloaded"}, {})["attachments_status"] == "downloaded"
    assert domain.merge_meta(None, {"attachments_status": "metadata_only"})["attachments_status"] == "metadata_only"


def test_ingest_and_provenance_forward_to_domain():
    from link_brain import ingest, provenance
    assert ingest.merge_meta is domain.merge_meta and ingest.FETCH_OWNED is domain.FETCH_OWNED
    assert provenance.collected_by is domain.collected_by and provenance.clean_project is domain.clean_project
