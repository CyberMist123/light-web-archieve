"""来源接口：共享代码只认这里，具体来源用到才 import。"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, TypedDict


class SourceError(RuntimeError):
    """输入解析或抓取失败。"""

    code = ""


class NeedsHuman(SourceError):
    """要停车叫人的那一类失败（和"这篇笔记没了"必须分开）。

    后者只是这一条抓不到，批量可以接着跑；这一类接着跑只会把剩下的全刷成失败。
    """


class AccountBlocked(NeedsHuman):
    """**号出事了**：登录态失效 / 撞风控验证码 / 被限流。"""


class ServiceDown(NeedsHuman):
    """**服务出事了**：18060 没在听、MCP 内部错、它那个浏览器起不来。

    2026-09-04 实际发生过：批量跑到第 19 条，MCP 回
    「[launcher] Failed to get the debug url」，后面 7 条全 3 秒失败——
    这种必须当场停车报警，不然就是 Owner 说的"不知不觉挂了"。
    """


class ItemRestricted(SourceError):
    """1011：**只是这一篇**打不开——小红书网页版限制了它（她的浏览器里打开要「验证一下」），读取服务打开详情页、
    页面上没有这篇（读取组件 `[NOTE_RESTRICTED]`）。不是号出事：不停整批、不写熔断；处理见 link_brain/restricted.py。"""

    code = "NOTE_RESTRICTED"


class Parsed(TypedDict, total=False):
    source: str
    source_id: str
    canonical_url: str
    input_url: str
    input_kind: str


@dataclass
class FetchOptions:
    refresh: bool = False
    comment_floors: int | str | None = None
    budget_left: Callable[[], float] | None = None
    progress: Callable[..., None] | None = None
    log: Callable[[str], None] = lambda _m: None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fetched:
    raw_files: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)


class MediaTask(TypedDict, total=False):
    role: str
    index: int
    comment_id: str
    url: str
    stem: str
    kind: str
    headers: dict[str, str]


class Source(Protocol):
    name: str
    version: str
    capabilities: frozenset[str]

    def matches(self, url: str) -> bool: ...
    def find_urls(self, text: str) -> list[str]: ...
    def parse(self, text: str) -> Parsed: ...
    def fetch(self, parsed: Parsed, opts: FetchOptions) -> Fetched: ...
    def normalize(self, fetched: Fetched, parsed: Parsed, *, captured_at: str) -> dict[str, Any]: ...
    def fingerprint(self, source_doc: dict[str, Any]) -> str: ...
    def media_plan(self, source_doc: dict[str, Any], opts: dict[str, Any]) -> list[MediaTask]: ...
    def source_open_url(self, note: dict[str, Any], meta: dict[str, Any]) -> str | None: ...
    def suggested_link_url(self, raw: Any) -> str: ...
    def is_link_only(self, text: str | None) -> bool: ...
    def item_flags(self, obj_dir: Path) -> list[dict[str, str]]: ...
    def comment_gap_text(self, comment: dict[str, Any], missing: int, gap_reasons: dict[str, str] | None,
                         floor_limit: int | None = None, scoped: bool = False) -> str: ...
    def comment_status_text(self, capture: dict[str, Any] | None, comments: list[dict[str, Any]],
                            view: dict[str, Any] | None = None) -> str: ...
    def comment_gap_lines(self, source: dict[str, Any], view: dict[str, Any] | None) -> list[str]: ...
    def restricted_text(self, view: dict[str, Any] | None) -> str: ...
    def comment_view(self, source: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]: ...
    def note_albums(self) -> dict[str, list[str]]: ...
    def action_home(self) -> Path: ...
    def action_lock_holder(self) -> dict[str, Any] | None: ...
    def action_for_route(self, route: str) -> str: ...


_REGISTRY: dict[str, str] = {"xiaohongshu": "link_brain.sources.xiaohongshu"}


def get(name: str) -> Source:
    if name not in _REGISTRY:
        raise SourceError(f"未知来源：{name}")
    return importlib.import_module(_REGISTRY[name])


def names() -> list[str]:
    return list(_REGISTRY)


def detect(text: str) -> list[tuple[Source, str]]:
    found: list[tuple[Source, str]] = []
    seen: set[str] = set()
    for name in names():
        src = get(name)
        for url in src.find_urls(text):
            if url not in seen:
                found.append((src, url))
                seen.add(url)
    return found
