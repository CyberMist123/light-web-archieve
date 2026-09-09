"""收藏目录页（简版）：把库里所有对象重写成一篇可读的分类索引。

设计要点（Owner 2026-09-09 定）：
- **她的手挪永远赢**。每次生成前先读现有目录 md，把「标题 → 分组」吸进 overrides.json；
  重写时优先用 overrides，关键词规则只管新来的。这样自动重写不会冲掉她随手挪的位置。
- 分组清单是 Owner 2026-09-07 拍板的固定清单（可再加）；瀑布流大版（封面图 + 小模型 category）
  另排一档做，见 docs/STATE.md 第 3 条。这里是「找文件」用的简版。
- 纯程序拼，不联网、不花钱：概要读 derived/extracted.json，其余读 meta.json。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage

CATALOG_NAME = "小红书收藏目录.md"
OVERRIDES_NAME = "catalog-overrides.json"
STATE_NAME = "catalog-state.json"

# Owner 2026-09-07 拍板的固定分类清单（+ 09-09 加「吃的」：她收藏里食谱已成一大类）。
# 判定按本列表顺序，先命中先归；「其他」兜底。
CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("记忆系统", "🧠", (
        "记忆", "memory", "上下文", "context", "rag", "遗忘", "memgpt", "mem0", "zep",
        "长期记忆", "向量", "知识库",
    )),
    ("开源项目", "📦", ("开源", "github", "自取", "repo", "仓库")),
    ("AI游戏", "🎮", ("游戏", "玩法", "副本", "剧本杀", "养成")),
    ("笑话", "😂", ("笑话", "沙雕", "搞笑", "离谱", "抽象")),
    ("吃的", "🍚", (
        "美食", "食谱", "菜谱", "做饭", "焖饭", "烘焙", "减脂餐", "下饭", "厨", "外卖",
        "探店", "甜点", "面包", "料理", "空气炸锅", "电饭煲", "早餐", "午餐", "晚餐",
        "食材", "超市", "好吃",
    )),
    ("冲浪(人+AI)", "🏄", ("冲浪", "刷推", "刷x", "reddit", "吃瓜")),
    ("其他AI分享", "🤖", (
        "ai", "claude", "gpt", "人机", "mcp", "prompt", "提示词", "agent", "模型",
        "token", "api", "sdk", "cursor", "codex", "llm", "机", "赛博",
    )),
]
FALLBACK = ("其他", "🗂")
CATEGORY_ORDER = [name for name, _, _ in CATEGORIES] + [FALLBACK[0]]
CATEGORY_ICON = {name: icon for name, icon, _ in CATEGORIES} | {FALLBACK[0]: FALLBACK[1]}

SUMMARY_CHARS = 62

# 可见笔记里的留言层（Lot 5 做完就会有内容；现在多半是空占位，此处先把读法接好）。
COMMENT_BLOCK = re.compile(
    r"<!-- link-brain:comments:start -->(.*?)<!-- link-brain:comments:end -->",
    re.S,
)
COMMENT_LINE = re.compile(r"^>\s*\*\*(?P<who>[^*]+)\*\*[：:]\s*(?P<text>.+)$", re.M)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def classify(title: str, tags: list[str], body: str) -> str:
    """关键词初分：标题 + tags 权重最高，正文只看开头（避免长文里一个 AI 就被吞走）。"""
    haystack = " ".join([title, " ".join(tags), body[:200]]).lower()
    for name, _icon, keywords in CATEGORIES:
        if any(k in haystack for k in keywords):
            return name
    return FALLBACK[0]


def read_existing_groups(catalog_path: Path) -> dict[str, str]:
    """从现有目录 md 里把「标题 → 分组」读回来——这是 Owner 手挪过的位置，必须保住。"""
    if not catalog_path.is_file():
        return {}
    groups: dict[str, str] = {}
    current: str | None = None
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##+\s+(?:[^\w\s]+\s*)?(.+?)(?:（\d+）)?\s*$", line)
        if heading:
            name = heading.group(1).strip()
            current = name if name in CATEGORY_ORDER else None
            continue
        if not current:
            continue
        link = re.search(r"\[\[([^\]|]+)", line)
        if link:
            groups[link.group(1).strip()] = current
    return groups


def load_overrides(vault: Path) -> dict[str, str]:
    data = _load_json(vault / "_archive" / OVERRIDES_NAME)
    return data if isinstance(data, dict) else {}


def load_last_built(vault: Path) -> datetime | None:
    """上次重建目录的时间——🆕 以它为界，而不是硬编码的「最近 N 天」。"""
    data = _load_json(vault / "_archive" / STATE_NAME)
    if isinstance(data, dict):
        return _parse_dt(data.get("last_built"))
    return None


def save_last_built(vault: Path, when: datetime) -> None:
    (vault / "_archive" / STATE_NAME).write_text(
        json.dumps({"last_built": when.isoformat()}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def save_overrides(vault: Path, overrides: dict[str, str]) -> None:
    path = vault / "_archive" / OVERRIDES_NAME
    path.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )


def read_comments(vault: Path, visible_note: str | None) -> list[tuple[str, str]]:
    """读可见笔记的留言层。Lot 5 未落地前基本返回空，接好省得将来再改一遍目录。"""
    if not visible_note:
        return []
    path = vault / visible_note
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    block = COMMENT_BLOCK.search(text)
    if not block:
        return []
    return [(m.group("who").strip(), m.group("text").strip()) for m in COMMENT_LINE.finditer(block.group(1))]


def collect(vault: Path, source: str = "xiaohongshu") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    base = vault / "_archive" / source
    if not base.is_dir():
        return items
    for obj_dir in sorted(base.iterdir()):
        meta = _load_json(obj_dir / "meta.json")
        if not isinstance(meta, dict):
            continue
        extracted = _load_json(obj_dir / "derived" / "extracted.json") or {}
        data = extracted.get("data") if isinstance(extracted, dict) else None
        summary = (data or {}).get("summary") or ""
        raw_dir = obj_dir / "raw" / f"v{meta.get('current_version', 1):04d}"
        source_doc = _load_json(raw_dir / "source.json") or {}
        note = source_doc.get("note") if isinstance(source_doc, dict) else {}
        tags = [str(t) for t in (note or {}).get("tags", [])] or [
            str(t) for t in (data or {}).get("tags", [])
        ]
        visible = meta.get("visible_note")
        items.append(
            {
                "item_id": meta.get("item_id", obj_dir.name),
                "title": meta.get("title") or obj_dir.name,
                "summary": summary,
                "tags": tags,
                "visible": visible,
                "archived": _parse_dt(meta.get("first_archived_at")),
                "attachments": meta.get("attachments_status", "none"),
                "has_attachment_bytes": any((obj_dir / "attachments").glob("*"))
                if (obj_dir / "attachments").is_dir()
                else False,
                "comments": read_comments(vault, visible),
                "body": (note or {}).get("desc", "") or "",
            }
        )
    return items


def _clip(text: str, limit: int = SUMMARY_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _line(item: dict[str, Any], since: datetime | None) -> str:
    stem = Path(item["visible"]).stem if item["visible"] else item["title"]
    bits = [f"- [[{stem}]]"]
    if item["summary"]:
        bits.append(f"— {_clip(item['summary'])}")
    meta_bits: list[str] = []
    archived = item["archived"]
    if archived:
        meta_bits.append(archived.strftime("%m-%d"))
        if since and archived > since:
            meta_bits.append("🆕")
    if item["attachments"] == "metadata_only" and not item["has_attachment_bytes"]:
        meta_bits.append("📎待补")
    elif item["has_attachment_bytes"]:
        meta_bits.append("📎")
    if item["comments"]:
        who, text = item["comments"][-1]
        meta_bits.append(f"💬{len(item['comments'])} {who}：{_clip(text, 24)}")
    if item["tags"]:
        meta_bits.append(" ".join(f"#{t.replace(' ', '')}" for t in item["tags"][:3]))
    if meta_bits:
        bits.append("· " + " · ".join(meta_bits))
    return " ".join(bits)


def build(vault: Path | None = None, *, source: str = "xiaohongshu") -> tuple[Path, int, int]:
    vault = vault or storage.vault_root()
    catalog_path = vault / CATALOG_NAME
    now = datetime.now().astimezone()
    since = load_last_built(vault)

    # 1) 先把现有目录里的分组吸进 overrides——她手挪的永远优先于关键词规则
    overrides = load_overrides(vault)
    overrides.update(read_existing_groups(catalog_path))

    items = collect(vault, source)
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in CATEGORY_ORDER}
    fresh = 0
    for item in items:
        stem = Path(item["visible"]).stem if item["visible"] else item["title"]
        group = overrides.get(stem) or classify(item["title"], item["tags"], item["body"])
        if group not in grouped:
            group = FALLBACK[0]
        grouped[group].append(item)
        overrides.setdefault(stem, group)
        if since and item["archived"] and item["archived"] > since:
            fresh += 1

    since_text = (
        f"上次重建（{since.strftime('%m-%d %H:%M')}）以来新增 **{fresh}** 篇"
        if since
        else "首次自动重建"
    )
    lines: list[str] = [
        "# 📌 小红书收藏 · 分类目录",
        "",
        f"共 **{len(items)}** 篇 · {since_text} · 本页最后更新 **{now.strftime('%Y-%m-%d %H:%M')}**",
        "",
        "> 每晚 04:00 同步完自动重写；也可以在左边栏点「重建目录」手动跑一次。"
        "**分组随手挪，下次重写会保住你挪过的位置**（记在 `_archive/catalog-overrides.json`）。",
        "",
    ]
    for name in CATEGORY_ORDER:
        bucket = grouped[name]
        if not bucket:
            continue
        bucket.sort(key=lambda it: it["archived"] or datetime.min.replace(tzinfo=now.tzinfo), reverse=True)
        lines.append(f"## {CATEGORY_ICON[name]} {name}（{len(bucket)}）")
        lines.append("")
        lines.extend(_line(item, since) for item in bucket)
        lines.append("")

    catalog_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    save_overrides(vault, overrides)
    save_last_built(vault, now)
    return catalog_path, len(items), fresh


def run(args) -> int:
    path, total, fresh = build()
    print(f"目录已重写：{path}（{total} 篇，新增 {fresh} 篇）")
    return 0
