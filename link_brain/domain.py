"""规则（第二波 PR①，1025）：身份 id、在库 / 已删 / 新帖的判断、是不是收藏、算谁收的、meta 字段归谁管、重抓时怎么合并 meta。

只判断、不碰文件：不读写文件、不连库、不看环境变量、不看时间，**不 import 任何 link_brain 模块**（`tests/test_domain.py` 守着）。
需要的事实（在不在索引、有没有墓碑、meta 内容）由调用方查好传进来；同样的输入永远给同样的输出。
存储、来源、页面都调它，它不调任何人。以后加网页 / B 站：`PREFIX` 加一行，别的规则直接复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# 身份
# ---------------------------------------------------------------------------

PREFIX: dict[str, str] = {"xiaohongshu": "xhs"}      # 来源 → item_id 前缀；加来源各加一行
_SOURCE_OF = {v: k for k, v in PREFIX.items()}


def item_id(source: str, source_id: Any) -> str:
    """("xiaohongshu", "6512…") → "xhs-6512…"。未知来源 / 空 id → ValueError（不猜）。"""
    sid = str(source_id or "").strip()
    if source not in PREFIX:
        raise ValueError(f"未知来源：{source!r}")
    if not sid:
        raise ValueError(f"{source} 的 source_id 为空")
    return f"{PREFIX[source]}-{sid}"


def parse_item_id(text: Any) -> tuple[str, str] | None:
    """"xhs-6512…" → ("xiaohongshu", "6512…")；不是 <已知前缀>-<id> 的形状 → None（调用方再当链接解析）。"""
    s = str(text or "").strip()
    prefix, sep, rest = s.partition("-")
    if not sep or not rest or prefix not in _SOURCE_OF:
        return None
    return _SOURCE_OF[prefix], rest


def short_id(item_id_or_id: Any) -> str:
    """去掉任何已知前缀（给 MCP / 远程 / 页面显示用）；本来就没前缀的原样返回。"""
    s = str(item_id_or_id or "").strip()
    parsed = parse_item_id(s)
    return parsed[1] if parsed else s


# ---------------------------------------------------------------------------
# 在库 / 已删 / 新帖
# ---------------------------------------------------------------------------


class Presence(str, Enum):
    NEW = "new"                # 没收过（或只剩暂存残渣）→ 要联网抓
    IN_LIBRARY = "in_library"  # 在库 → 不联网（除非 refresh）
    DELETED = "deleted"        # 她删过、在墓碑里 → 不抓、不拉回
    ORPHAN = "orphan"          # 有完整 RAW 版本、没 meta（上次崩在发布和提交之间）→ 不联网，收编


@dataclass(frozen=True)
class Probe:
    """存储层查好的事实（PR④ 的 storage.probe_object 填；这里只消费）。"""
    in_index: bool                              # index.db objects 表有这行
    has_meta: bool                              # 对象目录里有 meta.json
    tombstoned: bool                            # 墓碑（tombstones.jsonl 为准，index.db 表是缓存）
    complete_versions: tuple[int, ...] = ()     # raw/ 下带 manifest.json 的 vNNNN


@dataclass(frozen=True)
class Lookup:
    state: Presence
    needs_reindex: bool = False   # meta 在、索引没有（崩在提交之后、写索引之前）→ 从磁盘补索引，不联网


def lookup(p: Probe) -> Lookup:
    """优先级：墓碑 > meta > 完整版本 > 新帖。她删了就是删了，对象目录还在也一样。"""
    if p.tombstoned:
        return Lookup(Presence.DELETED)
    if p.has_meta:
        return Lookup(Presence.IN_LIBRARY, needs_reindex=not p.in_index)
    if p.complete_versions:
        return Lookup(Presence.ORPHAN)
    return Lookup(Presence.NEW)   # in_index 但没 meta = 索引是旧的，交给调用方删行


def needs_fetch(lk: Lookup, *, refresh: bool) -> bool:
    if lk.state is Presence.NEW:
        return True
    if lk.state is Presence.IN_LIBRARY:
        return bool(refresh)
    return False   # DELETED / ORPHAN


def write_decision(prior_fp: str | None, new_fp: str, *, committed: bool) -> str:
    """"write"（新版本）/ "touch"（只更新 last_checked_at）。没提交过的 → write；指纹相同 → touch。"""
    if not committed or not prior_fp:
        return "write"
    return "touch" if prior_fp == new_fp else "write"


# ---------------------------------------------------------------------------
# 收藏口径（1023 她定：多个号的收藏、网页导入 = 我的收藏；TG 发来的 = Fable）
# ---------------------------------------------------------------------------

FABLE = "fable"
HUMAN = "human"


def account_key(acc: Mapping[str, Any]) -> str:
    """号的身份：user_id 优先，没有退昵称；都没有 → ""（ARCH-AUDIT §1：按 user_id 认号）。"""
    return str(acc.get("user_id") or acc.get("nickname") or "").strip()


def is_favorite(meta: Mapping[str, Any]) -> bool:
    """任何一个号收藏过 = 是收藏（favorited_by 非空）。
    兼容：老数据 ingest_kind == "favorite" 且没 favorited_by 也算（补标迁移做完前不能缩数）。"""
    return bool(meta.get("favorited_by")) or meta.get("ingest_kind") == "favorite"


def collected_by(meta: Mapping[str, Any]) -> str:
    """谁收的（目录「来源」分组键）：
    - ""      = 我的收藏：是收藏；或 actor=human 且不是 TG 发来的（插件导入网址 / CLI / 电脑上自己导入 = 网页导入）
    - "fable" = TG 发来的（origin=tg，1023 她定；原来叫「聊天分享」）和 Fable 自己收的（actor=ai:fable）
    - 项目名  = CC / GPT 带 --project 收的；没项目名 → actor 冒号后的名字
    """
    if is_favorite(meta):
        return ""
    actor = str(meta.get("actor") or HUMAN)
    if actor == HUMAN:
        return FABLE if meta.get("origin") == "tg" else ""
    project = str(meta.get("project") or "").strip()
    if project:
        return project
    return actor.split(":", 1)[1].strip() if ":" in actor else actor


def via(meta: Mapping[str, Any]) -> str:
    """并进 fable 组之后还分得清：她在 TG 发给 Fable 的 → "tg"；其余 → ""。"""
    return "tg" if collected_by(meta) == FABLE and str(meta.get("actor") or HUMAN) == HUMAN else ""


def clean_project(value: Any) -> str:
    """项目名进目录当分组名：去空白、限长，不许带路径分隔符。"""
    text = " ".join(str(value or "").split())[:40]
    return text.replace("/", "-").replace("\\", "-")


# ---------------------------------------------------------------------------
# meta 字段归属（谁写、重抓时怎么办；表同步在 docs/FORMAT.md §2）
# ---------------------------------------------------------------------------


class Owner(str, Enum):
    FETCH = "fetch"      # 抓取算出来的：每次重抓取新值
    ENTRY = "entry"      # 第一次入库时由入口写：之后重抓不覆盖
    RENDER = "render"    # 渲染 / 可见笔记写
    SYNC = "sync"        # 收藏同步写
    ATTACH = "attach"    # 附件模块写
    OWNER = "owner"      # 她本人改（relabel / 钉文件名 / 改来源）


FIELD_OWNER: dict[str, Owner] = {
    **{k: Owner.FETCH for k in (
        "schema_version", "item_id", "source", "source_id", "canonical_url", "input_url", "kind", "title", "author",
        "published_at", "last_checked_at", "current_version", "versions", "images_complete", "comments_complete",
        "comment_load", "tool_versions")},
    **{k: Owner.ENTRY for k in ("first_archived_at", "origin", "actor", "ingest_kind", "note", "project",
                                 "space")},   # space：预留（不写 = knowledge），以后加影音库不用迁移
    "visible_note": Owner.RENDER,
    "visible_note_pinned": Owner.OWNER,
    "favorited_by": Owner.SYNC,
    "attachments_status": Owner.ATTACH,
}

FETCH_OWNED = frozenset(k for k, o in FIELD_OWNER.items() if o is Owner.FETCH)

DEFAULT_SPACE = "knowledge"


def keys_owned_by(owner: Owner) -> frozenset[str]:
    """给守卫 / 写 meta 的模块用：每个模块只许动自己那几个键。"""
    return frozenset(k for k, o in FIELD_OWNER.items() if o is owner)


def space_of(meta: Mapping[str, Any]) -> str:
    return str(meta.get("space") or DEFAULT_SPACE)


def merge_meta(old: Mapping[str, Any] | None, fetched: Mapping[str, Any]) -> dict[str, Any]:
    """旧 meta + 这次抓取重建的 meta → 要写回的 meta（第一波车 1 的实现原样挪来；在 storage.update_json 的锁里调）。

    FETCH 的键取抓回来的；抓回来没标题时沿用旧标题（render 给视频收藏起的兜底标题）。
    其余键旧的有值就保留，旧的没有（或是 None）才用这次的（第一次入库 = 全收）。
    attachments_status 归 ATTACH：抓取只看得到附件元数据，重抓不许把「已下载」降回「只有元数据」；别的变化照抓到的走。
    """
    merged = dict(fetched)
    for key, value in (old or {}).items():
        if key in FETCH_OWNED and key in fetched:
            continue
        if value is None and fetched.get(key) is not None:
            continue
        merged[key] = value
    if not merged.get("title") and (old or {}).get("title"):
        merged["title"] = old["title"]
    if fetched.get("attachments_status") is not None:
        merged["attachments_status"] = fetched["attachments_status"]
        if (old or {}).get("attachments_status") == "downloaded" and fetched.get("attachments_status") == "metadata_only":
            merged["attachments_status"] = "downloaded"
    return merged
