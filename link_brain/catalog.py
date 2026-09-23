"""收藏目录页（封面瀑布流版）。

Owner 2026-09-15 拍板改法（推翻 09-07 的「小模型 category 分文件夹」）：
- **组织轴是 tag，不是文件夹**。文件夹分类一条笔记只能进一个夹子、丢多维信息，且
  移文件是破坏性的（E2N 就得靠「只在子目录移、不删正文」自保）。tag 不动文件、随便加减，
  天生贴合她「加减 tag」的习惯，也给以后的模糊搜索留好轴。tag 数据本来就在每篇 frontmatter 里
  （Lot 4 归一 + 合并 + 她手写），这里直接拿来当筛选轴。
- 页面 = 无标签封面墙 + 本地模糊检索；右键卡片编辑后台标签。
- 硬约束 #8「不做 Obsidian 插件」：页面靠 **Dataview 的 dataviewjs**（用户装的社区插件，不是我们自研）
  渲染——它能渲染真·Obsidian 链接（绕开「裸 HTML 的 a href 打不开本地笔记」那个坑）、能跑 JS、
  样式由 JS 自注入（不依赖她手动开 CSS snippet）。
- Python 这侧只做**数据管线**：纯程序拼，不联网、不花钱——概要读 derived/extracted.json，
  封面取 manifest 第一张成功图，tag 读可见笔记 frontmatter，其余读 meta.json，
  全部落 `_archive/catalog-data.json`；md 页面里那段 dataviewjs 读它来渲染。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pypinyin import lazy_pinyin

from . import storage

CATALOG_NAME = "小红书收藏目录.md"
DATA_NAME = "catalog-data.json"
STATE_NAME = "catalog-state.json"

SUMMARY_CHARS = 90

# 顶部筛选条的「大类」（小红书发现页那种 tab；Owner 2026-09-15：别堆几百个 tag，大类即可）。
# 只用于**筛选展示**——底层数据仍是每篇的全 tag（卡片照显），大类靠关键词命中 tag 得来，一篇可属多类。
# 顺序即 tab 顺序；关键词大小写不敏感、子串匹配 tag。
BIG_CATS: list[tuple[str, tuple[str, ...]]] = [
    ("人机恋", ("人机恋", "ai伴侣", "ai陪伴", "情感计算", "陪伴", "人机交互")),
    ("AI·模型", ("claude", "gpt", "chatgpt", "deepseek", "gemini", "大模型", "人工智能",
                 "llm", "codex", "模型", "ai", "赛博")),
    ("记忆", ("记忆", "memory", "知识库", "rag", "上下文")),
    ("提示词", ("提示词", "prompt", "咒语")),
    ("开源·编程", ("开源", "github", "编程", "代码", "coding", "vibecoding", "前端",
                   "独立开发", "部署", "sdk", "开发")),
    ("AI工具", ("mcp", "语音", "通话", "小手机", "聊天", "airp", "agent", "唤醒", "工具")),
    ("AI游戏", ("游戏", "game", "迪斯科", "roguelike", "副本", "养成")),
    ("吃的", ("食", "菜", "饭", "餐", "辅食", "料理", "美食", "烘焙", "减脂", "懒人",
              "超市", "厨", "吃", "家常", "烹", "coles", "wws")),
    ("留学·澳洲", ("澳洲", "悉尼", "留学", "留子", "unsw", "usyd", "sydney", "法学",
                   "法律", "llb", "墨尔本", "澳大利亚")),
    ("追文·同人", ("瓶邪", "盗墓", "铁三角", "张起灵", "吴邪", "同人", "雨村", "捡手机文学")),
    ("笑话", ("笑话", "沙雕", "黑色幽默", "抽象", "搞笑", "离谱")),
]
OTHER_CAT = "其他"

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def effective_big_cats() -> list[tuple[str, tuple[str, ...]]]:
    """大类清单：Owner 在插件设置里编辑过就用她的（data.json 的 `catalogCats`），否则用内置 BIG_CATS。

    她的格式是 `[{"name": "人机恋", "keywords": ["人机恋","ai伴侣"]}, ...]`（设置页那个可编辑文本框解析出来的）。
    改完要重跑 `catalog` 才生效（这个函数只在重建目录时读一次）。fail-open：读不动就用内置。
    """
    try:
        from . import ai_config

        raw = ai_config.load().get("catalogCats")
    except Exception:  # noqa: BLE001 - 配置读不动绝不挡住目录重建
        raw = None
    if isinstance(raw, list) and raw:
        out: list[tuple[str, tuple[str, ...]]] = []
        for entry in raw:
            if isinstance(entry, dict) and str(entry.get("name") or "").strip():
                kws = tuple(str(k).strip().lower() for k in (entry.get("keywords") or []) if str(k).strip())
                out.append((str(entry["name"]).strip(), kws))
        if out:
            return out
    return BIG_CATS


def _cats(tags: list[str], big_cats: list[tuple[str, tuple[str, ...]]]) -> list[str]:
    hay = " ".join(tags).lower()
    hits = [name for name, kws in big_cats if any(k in hay for k in kws)]
    return hits or [OTHER_CAT]


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


def _note_tags(vault: Path, visible: str | None) -> list[str]:
    """从可见笔记 frontmatter 读 tags——那是归一 + 小模型 + Owner 手写合并后最全的一份。"""
    if not visible:
        return []
    path = vault / visible
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return []
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return []
    raw = fm.get("tags") if isinstance(fm, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for t in raw:
        t = str(t).strip().lstrip("#").strip()
        if t and t not in out:
            out.append(t)
    return out


def _cover(obj_dir: Path, source: str, source_id: str, version: int) -> str | None:
    """封面 = manifest 里第一张下成功的图片，返回 vault 相对路径（供 getResourcePath）。"""
    raw_dir = obj_dir / "raw" / f"v{version:04d}"
    manifest = _load_json(raw_dir / "manifest.json")
    if isinstance(manifest, dict):
        for media in manifest.get("media", []):
            if not isinstance(media, dict):
                continue
            if media.get("download_status") != "ok":
                continue
            if not str(media.get("mime", "")).startswith("image"):
                continue
            file = media.get("file")
            if file:
                return f"_archive/{source}/{source_id}/{file}"
    # 兜底：直接扫 assets 第一张
    assets = raw_dir / "assets"
    if assets.is_dir():
        for p in sorted(assets.iterdir()):
            if p.suffix.lower() in {".webp", ".jpg", ".jpeg", ".png", ".gif"}:
                return f"_archive/{source}/{source_id}/raw/v{version:04d}/assets/{p.name}"
    return None


def _clip(text: str, limit: int = SUMMARY_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _last_comment(vault: Path, visible: str | None) -> tuple[int, dict[str, str] | None]:
    if not visible:
        return 0, None
    path = vault / visible
    if not path.is_file():
        return 0, None
    try:
        from . import comments as comments_mod

        rows = [c for c in comments_mod.read_comments(path) if c.text]
    except (OSError, ValueError, ImportError):
        return 0, None
    if not rows:
        return 0, None
    try:
        who = comments_mod.display_name(rows[-1].actor)
    except Exception:
        who = "留言"
    return len(rows), {"who": who, "text": _clip(rows[-1].text, 40)}


def _attachment_badge(obj_dir: Path, meta: dict[str, Any]) -> str:
    from .attachments import inventory
    report = inventory(obj_dir, meta)
    if report["missing"]:
        return "待补"
    return "downloaded" if report["files"] else "none"


def collect(vault: Path, source: str = "xiaohongshu") -> list[dict[str, Any]]:
    from .render import parse_frontmatter, source_open_url

    items: list[dict[str, Any]] = []
    big_cats = effective_big_cats()
    base = vault / "_archive" / source
    if not base.is_dir():
        return items
    for obj_dir in sorted(base.iterdir()):
        meta = _load_json(obj_dir / "meta.json")
        if not isinstance(meta, dict):
            continue
        source_id = obj_dir.name
        version = int(meta.get("current_version", 1) or 1)
        extracted = _load_json(obj_dir / "derived" / "extracted.json") or {}
        data = extracted.get("data") if isinstance(extracted, dict) else None
        summary = (data or {}).get("summary") or ""
        visible = meta.get("visible_note")
        tags = _note_tags(vault, visible)
        visible_text = (vault / visible).read_text(encoding='utf-8') if visible and (vault / visible).is_file() else None
        if not tags and 'tags' not in parse_frontmatter(visible_text):
            # 没渲染出可见笔记时退回 source.json / extracted 的 tag
            source_doc = _load_json(obj_dir / "raw" / f"v{version:04d}" / "source.json") or {}
            note = source_doc.get("note") if isinstance(source_doc, dict) else {}
            tags = [str(t).strip() for t in (note or {}).get("tags", []) if str(t).strip()]
            if not tags and isinstance(data, dict):
                tags = [str(t).strip() for t in data.get("tags", []) if str(t).strip()]
        comment_count, last_comment = _last_comment(vault, visible)
        source_doc = _load_json(obj_dir / 'raw' / f'v{version:04d}' / 'source.json') or {}
        note = source_doc.get('note') or {}
        observed_links = list(dict.fromkeys(
            url.rstrip('。，、；：！？）)]}') for url in re.findall(
                r'https?://[^\s<>"\\]+', json.dumps(source_doc, ensure_ascii=False)
            )
        ))
        from .attachments import inventory
        from .llm import comment_labels
        report = inventory(obj_dir, meta)
        vision = _load_json(obj_dir / "derived" / "vision.json") or {}
        transcript = _load_json(obj_dir / "derived/transcript.json") or {}
        search_fields = {
            "transcript": str(transcript.get("text") or ""),
            "body": str(note.get("body") or ""),
            "comments": "\n".join(str(c.get("text") or "") for _, c in comment_labels(source_doc.get("comments") or [])),
            "ocr": "\n".join(str(im.get("ocr") or "") for im in vision.get("images", []) if im.get("status") == "ok"),
            "attachments": "\n\n".join(p.read_text(encoding="utf-8") for p in sorted((obj_dir / "derived" / "attachments").glob("*.md"))),
        }
        archived = _parse_dt(meta.get("first_archived_at"))
        items.append(
            {
                "id": meta.get("item_id", source_id),
                "title": meta.get("title") or source_id,
                "note": visible,
                "notes_path": f"_archive/{source}/{source_id}/notes.json",
                "starred": bool((_load_json(obj_dir / "notes.json") or {}).get("starred")),
                "cover": _cover(obj_dir, source, source_id, version),
                "summary": _clip(summary),
                "search_text": "\n".join(search_fields.values()),
                "search_fields": search_fields,
                "agent_md": f"_archive/{source}/{source_id}/derived/agent.md",
                "attachment_files": report["files"],
                "attachment_missing": report["missing"],
                "attachment_errors": report["errors"],
                "author": (note.get('author') or {}).get('nickname', ''),
                "source": source,
                "url": source_open_url(note, meta),
                "github_urls": [url for url in observed_links if re.match(r'https?://github\.com/', url, re.I)],
                "suggested_links": (data or {}).get('links_worth_opening', []),
                "likes": (note.get('engagement') or {}).get('liked'),
                "pinyin": ''.join(lazy_pinyin(' '.join([str(meta.get('title') or ''), summary, *tags]))).lower(),
                "tags": tags,
                "cats": _cats(tags, big_cats),
                "kind": meta.get("kind", "image"),
                "date": archived.strftime("%Y-%m-%d") if archived else "",
                "ts": archived.isoformat() if archived else "",
                "comments": comment_count,
                "last_comment": last_comment,
                "attachment": _attachment_badge(obj_dir, meta),
            }
        )
    # 新→旧
    items.sort(key=lambda it: it.get("ts") or "", reverse=True)
    return items


# ── dataviewjs 页面（样式自注入，不依赖 CSS snippet；读 catalog-data.json 渲染） ──
# 页面脚本独立保存，生成时嵌入笔记，Dataview 无需另读脚本。
_DATAVIEWJS = "```dataviewjs\n" + (Path(__file__).parent / "assets" / "catalog-search.js").read_text(encoding="utf-8") + '\n' + (Path(__file__).parent / "assets" / "catalog-view.js").read_text(encoding="utf-8") + "\n```"
# 收藏搜索页 = 极简对话版（chat-view.js），跟浏览目录页分开（Owner 2026-09-17）。
_CHATJS = "```dataviewjs\n" + (Path(__file__).parent / "assets" / "catalog-search.js").read_text(encoding="utf-8") + '\n' + (Path(__file__).parent / "assets" / "chat-view.js").read_text(encoding="utf-8") + "\n```"
_PAGE_HEADER = "---\ncssclasses: [lb-catalog]\n---\n\n"
_CHAT_HEADER = "---\ncssclasses: [lb-chatpage]\n---\n\n"


def library_pages(vault):
    defaults = {"catalog": CATALOG_NAME, "chat": "收藏搜索.md", "starred": "星标收藏.md"}
    pages = dict(defaults)
    for file in vault.glob("*.md"):
        text = file.read_text(encoding="utf-8")
        role = next((key for key in defaults if f"lb-page: {key}\n" in text[:300]), None)
        if not role and "```dataviewjs" in text:
            if "cssclasses: [lb-chatpage]" in text[:150]:
                role = "chat"
            elif "cssclasses: [lb-catalog]" in text[:150]:
                role = "starred" if "const starredPage = true;" in text else "catalog"
        if role:
            pages[role] = file.name
    return pages


def build(vault: Path | None = None, *, source: str = "xiaohongshu") -> tuple[Path, int, Path]:
    vault = vault or storage.vault_root()
    now = datetime.now().astimezone()
    items = collect(vault, source)
    pages = library_pages(vault)

    data_path = vault / "_archive" / DATA_NAME
    data_path.parent.mkdir(parents=True, exist_ok=True)
    from .retrieval import ALIASES
    cats_order = [name for name, _ in effective_big_cats()] + [OTHER_CAT]
    present = {c for it in items for c in it["cats"]}
    cats_order = [c for c in cats_order if c in present]
    data_path.write_text(
        json.dumps(
            {
                "built_at": now.isoformat(),
                "pages": pages,
                "count": len(items),
                "cats_order": cats_order,
                "cats": [{"name": name, "keywords": list(kws)} for name, kws in effective_big_cats()],
                "aliases": ALIASES,
                "items": items,
                "pinyin_chars": {c: lazy_pinyin(c)[0] for c in set(''.join(str(it['title']) + ' '.join(it['tags']) + it['summary'] for it in items)) if '\u4e00' <= c <= '\u9fff'},
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    catalog_path = vault / pages["catalog"]
    catalog_path.write_text(_PAGE_HEADER.replace("---\n", "---\nlb-page: catalog\n", 1) + _DATAVIEWJS + "\n", encoding="utf-8")

    (vault / pages["chat"]).write_text(_CHAT_HEADER.replace("---\n", "---\nlb-page: chat\n", 1) + _CHATJS + "\n", encoding="utf-8")

    starred_js = _DATAVIEWJS.replace("const simplePage = false;", "const simplePage = true;").replace("const starredPage = false;", "const starredPage = true;")
    (vault / pages["starred"]).write_text(_PAGE_HEADER.replace("---\n", "---\nlb-page: starred\n", 1) + starred_js + "\n", encoding="utf-8")

    # 部署笔记底部批注块用的共享脚本（每篇笔记的 bootstrap 会 adapter.read 它）
    (vault / "_archive" / "annotate-view.js").write_text(
        (Path(__file__).parent / "assets" / "annotate-view.js").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    (vault / "_archive" / STATE_NAME).write_text(
        json.dumps({"last_built": now.isoformat()}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    from .remove import publish_trash
    publish_trash(vault)
    return catalog_path, len(items), data_path


def dump_cats_text() -> str:
    """把当前生效的大类导成「名称: 关键词1, 关键词2」逐行文本，给设置页那个可编辑文本框预填。"""
    return "\n".join(f"{name}: {', '.join(kws)}" for name, kws in effective_big_cats())


def run(args) -> int:
    if getattr(args, "print_cats", False):
        # 机器可读：设置页「载入当前大类」按钮读这份
        from .read import dump_json

        dump_json({"text": dump_cats_text()})
        return 0
    path, total, data_path = build()
    print(f"目录已重写：{path}（{total} 篇）")
    print(f"数据：{data_path}")
    print("提示：OB 需装 Dataview 插件并打开「Enable JavaScript Queries」，页面才会渲染。")
    return 0
