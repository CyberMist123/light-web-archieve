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
from .ocrtext import clean_ocr
from .retrieval import pinyin_text

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
    return _cover_info(obj_dir, source, source_id, version)[0]


def _cover_info(obj_dir: Path, source: str, source_id: str, version: int) -> tuple[str | None, int | None, int | None]:
    """(封面路径, 宽, 高)。宽高来自 manifest（下载时 Pillow 读出的），目录页拿它先给卡片占位：
    图片懒加载时版面不跳、返回目录时滚动位置一次到位（第 2 批，CONVENTIONS §5.3）；拿不到就是 None。"""
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
                w, h = media.get("width"), media.get("height")
                ok = isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0
                return f"_archive/{source}/{source_id}/{file}", (w if ok else None), (h if ok else None)
    # 兜底：直接扫 assets 第一张
    assets = raw_dir / "assets"
    if assets.is_dir():
        for p in sorted(assets.iterdir()):
            if p.suffix.lower() in {".webp", ".jpg", ".jpeg", ".png", ".gif"}:
                return f"_archive/{source}/{source_id}/raw/v{version:04d}/assets/{p.name}", None, None
    return None, None, None


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


def _attachment_badge(obj_dir: Path, meta: dict[str, Any], report: dict[str, Any] | None = None) -> str:
    """待补 = 有文件编号、字节还没下；线索 = 只是正文提到「附件」、找不到文件（0929 Owner：不算待补，灰显写原因）。"""
    from .attachments import inventory
    report = report or inventory(obj_dir, meta)
    lost = [f for f in report["files"] if not f["downloaded"]]
    if lost:
        return "线索" if all(not f.get("doc_id") for f in lost) else "待补"
    return "downloaded" if report["files"] else "none"


def _attachment_reason(obj_dir: Path, meta: dict[str, Any], badge: str) -> str:
    if badge != "线索":
        return ""
    web = _load_json(obj_dir / "raw" / f"v{int(meta.get('current_version', 1) or 1):04d}" / "web_raw.json") or {}
    recheck = _load_json(obj_dir / "derived" / "web_recheck.json") or {}
    why = (recheck.get("error") if isinstance(recheck, dict) else None) or (web.get("error") if isinstance(web, dict) else None)
    return "正文提到附件，但笔记页里没找到文件" + (f"（{_clip(str(why), 60)}）" if why else "（页面上确实没挂文件）")


def _problem(code: str, reason: str | None, action: str | None = None, next_at: str | None = None) -> dict[str, str]:
    from . import problems
    shown = problems.describe(code, reason, next_at)
    cls = shown["code"].split(".", 1)[0]
    return {"code": shown["code"], "label": shown["label"], "hover": shown["hover"], "group": shown["group"],
            "action": action or problems.DEFAULT_ACTION.get(cls, "retry_later")}


def item_problems(obj_dir: Path, report: dict[str, Any], vision: dict[str, Any], transcript: dict[str, Any],
                  extracted: dict[str, Any]) -> list[dict[str, str]]:
    """这一篇眼下的问题（CONVENTIONS §3.4）：只从各对象文件推出，**不读 problems.jsonl**；文案只从登记表取。

    [{code, label, hover, group, action}]，每个码一条（同一篇几张图 / 几份附件同码只列一次，原因取第一条）。
    来源：attachments.json 的 conversion_failed · attachment-state.json 的下载错误 · transcript.json ·
    vision.json（第一层识图接口故障 / 第二层精细识别放弃）· extracted.json（概要失败）· enrich-state.json（连着失败暂时放弃）。
    SKIPPED（没配置 / 关了）不算问题，不列。"""
    out: dict[str, dict[str, str]] = {}

    def add(code, reason, action=None, next_at=None):
        if not code:
            return
        try:
            row = _problem(code, reason, action, next_at)
        except Exception:  # noqa: BLE001 - 坏码不拖垮目录重建
            return
        if row["code"].startswith("SKIPPED."):
            return
        out.setdefault(row["code"], row)

    att = _load_json(obj_dir / "attachments.json") or {}
    for rec in (att.get("files") or []) if isinstance(att, dict) else []:
        failed = rec.get("conversion_failed") if isinstance(rec, dict) else None
        if not isinstance(failed, dict) or failed.get("sha256") != rec.get("sha256"):
            continue  # 换了文件：旧失败作废
        code = failed.get("code") or "PERMANENT.CONVERSION_FAILED"  # 旧记录没有码（当时只有加密 / 损坏才会落）
        name = rec.get("name") or rec.get("file") or "附件"
        add(code, f"{name}：{failed.get('note') or '转换失败'}",
            "gave_up" if str(code).startswith("PERMANENT.") else "retry_later", failed.get("next_at"))
    for err in report.get("errors") or []:
        if isinstance(err, dict) and err.get("error"):
            add("TRANSIENT.DOWNLOAD_FAILED", str(err["error"])[:200])
    status = transcript.get("status") if isinstance(transcript, dict) else None
    if status == "no_speech":
        add("PERMANENT.NO_SPEECH", "视频里没听出人声（背景音乐 / 环境声）")
    elif status == "no_audio":
        add("PERMANENT.NO_AUDIO", "视频没有音轨")
    elif status == "failed":
        add(transcript.get("code") or "TRANSIENT.SERVICE_BUSY", transcript.get("error") or "语音识别失败",
            "retry_later", transcript.get("retry_after"))
    for im in (vision.get("images") or []) if isinstance(vision, dict) else []:
        visual = im.get("visual") or {}
        if visual.get("status") not in (None, "ok") and visual.get("code"):
            add(visual["code"], visual.get("error") or "识图失败")
        ref = im.get("refine") or {}
        if ref.get("status") == "failed":
            add("PERMANENT.MODEL_OUTPUT_INVALID", f"精细识别：{ref.get('error') or '结果不合格'}")
    state = _load_json(obj_dir / "enrich-state.json") or {}
    from .enrich import MAX_FAILS
    if isinstance(state, dict) and int(state.get("fails") or 0) >= MAX_FAILS:
        add("TRANSIENT.RETRY_EXHAUSTED", f"识图 / 概要连着 {state.get('fails')} 次没补成：{state.get('last_error') or ''}",
            "gave_up", state.get("retry_after"))
    elif isinstance(extracted, dict) and extracted.get("status") == "failed":
        add(extracted.get("code") or "TRANSIENT.SERVICE_BUSY", f"概要没生成：{extracted.get('error') or ''}")
    return list(out.values())


def _image_search_text(image: dict[str, Any]) -> str:
    """一张图进检索的文字：本地 OCR 原文 + 识图结果。第二层精细识图（refined）成功时替代第一层 visual，
    与机读版 agent.md 的取法一致（render.py image_lines）；只读已有的 vision.json，不调识图模型。"""
    refined = image.get("refined") or {}
    visual = image.get("visual") or {}
    seen = refined.get("text") if refined.get("status") == "ok" else visual.get("text") if visual.get("status") == "ok" else ""
    return "\n".join(filter(None, [clean_ocr(image.get("ocr")), str(seen or "")]))


# 拼音表：查询词里的汉字靠它转整音节（同音错字找回）。库里出现过的字 + GB2312 一级常用字（3755 个），
# 这样语音输入打出的「西尼」这类库里没出现过的同音字也查得到读音。
def _common_hanzi() -> set[str]:
    out = set()
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return out


def pinyin_chars(items: list[dict[str, Any]]) -> dict[str, str]:
    corpus = set("".join(str(it.get("title") or "") + " ".join(it.get("tags") or []) + str(it.get("summary") or "") for it in items))
    return {c: lazy_pinyin(c)[0] for c in sorted(corpus | _common_hanzi()) if "\u4e00" <= c <= "\u9fff"}


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
            "transcript": "\n".join(filter(None, [str(transcript.get("text") or ""),
                                                  str((transcript.get("screen") or {}).get("text") or "")])),
            "body": str(note.get("body") or ""),
            "comments": "\n".join(str(c.get("text") or "") for _, c in comment_labels(source_doc.get("comments") or [])),
            # 图片文字 + 识图结果（表格 Markdown / 图片描述）一起进检索；精细识图（第二层 refined）成功就用它替代第一层
            "ocr": "\n".join(filter(None, (_image_search_text(im) for im in vision.get("images", []) if im.get("status") == "ok"))),
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
                "starred_at": (_load_json(obj_dir / "notes.json") or {}).get("starred_at"),
                **dict(zip(("cover", "cover_w", "cover_h"), _cover_info(obj_dir, source, source_id, version))),
                "summary": _clip(summary),
                # 1001 审计 ui-4：不再另存拼好的 search_text（与 search_fields 全文重复，占了一半体积）；
                # 读方（retrieval.fields / 目录页 itemText / semantic）都以 search_fields 为准
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
                # 整音节、空格分隔（标点处「/」断开）：搜索只认整音节，见 retrieval.pinyin_match / catalog-search.js
                "pinyin": pinyin_text(str(meta.get('title') or ''), summary, *tags),
                "tags": tags,
                "cats": _cats(tags, big_cats),
                "kind": meta.get("kind", "image"),
                "date": archived.strftime("%Y-%m-%d") if archived else "",
                "ts": archived.isoformat() if archived else "",
                "comments": comment_count,
                "last_comment": last_comment,
                "attachment": (badge := _attachment_badge(obj_dir, meta, report)),
                "attachment_reason": _attachment_reason(obj_dir, meta, badge),
                # 第 4 批：卡片悬停的问题原因（label / hover 已从 problems 登记表取好；attachment_reason 照留）
                "problems": item_problems(obj_dir, report, vision, transcript, extracted),
                # 收藏来自哪个号（0926）：同步时写进 meta.favorited_by，供按账号筛选
                "accounts": [a.get("nickname") or a.get("user_id") for a in (meta.get("favorited_by") or [])
                             if isinstance(a, dict)],
            }
        )
    # 新→旧
    items.sort(key=lambda it: it.get("ts") or "", reverse=True)
    return items


# ── dataviewjs 页面（样式自注入，不依赖 CSS snippet；读 catalog-data.json 渲染） ──
# 页面脚本独立保存，生成时嵌入笔记，Dataview 无需另读脚本。
_ASSETS = Path(__file__).parent / "assets"
# 第 2 批：三张页和批注块共用的前导（CONVENTIONS §5：仓根 / 插件 / 页面状态 / 数据版本与缓存 / 旧 DOM 复用 / 计时），内联在最前面
_PAGE_LIB = (_ASSETS / "lb-page-lib.js").read_text(encoding="utf-8")
_DATAVIEWJS = "```dataviewjs\n" + _PAGE_LIB + "\n" + (_ASSETS / "catalog-search.js").read_text(encoding="utf-8") + '\n' + (_ASSETS / "catalog-view.js").read_text(encoding="utf-8") + "\n```"
# 收藏搜索页 = 极简对话版（chat-view.js），跟浏览目录页分开（Owner 2026-09-17）。
_CHATJS = "```dataviewjs\n" + _PAGE_LIB + "\n" + (_ASSETS / "catalog-search.js").read_text(encoding="utf-8") + '\n' + (_ASSETS / "chat-view.js").read_text(encoding="utf-8") + "\n```"
_PAGE_HEADER = "---\ncssclasses: [lb-catalog]\n---\n\n"
_CHAT_HEADER = "---\ncssclasses: [lb-chatpage]\n---\n\n"


def library_pages(vault):
    defaults = {"catalog": CATALOG_NAME, "chat": "收藏搜索.md", "starred": "星标收藏.md", "trash": "回收站.md"}
    pages = dict(defaults)
    for file in vault.glob("*.md"):
        text = file.read_text(encoding="utf-8")
        role = next((key for key in defaults if f"lb-page: {key}\n" in text[:300]), None)
        if not role and "```dataviewjs" in text:
            if "cssclasses: [lb-chatpage]" in text[:150]:
                role = "chat"
            elif "cssclasses: [lb-catalog]" in text[:150]:
                role = "starred" if "const starredPage = true;" in text else "catalog"
            elif "_archive/trash-data.json" in text:
                role = "trash"  # 第 3 批以前的回收站页没有页头标记
        if role:
            pages[role] = file.name
    return pages


def _state_registry() -> dict[str, dict[str, str]]:
    from . import problems
    return problems.registry_for_js()


@storage.locked("catalog-build", wait_s=120)  # CONVENTIONS §6.4：remove / attachments / topics / 插件都会调
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
    # 星标主题（Lot E）：只是展示分组，写进 catalog-data 给目录页 chip 用，不进检索字段。
    # fail-open：topics.json 缺/坏或算隶属出错 = 没有主题，页面与没这功能时一致。
    try:
        from . import topics as topics_mod

        topic_list = topics_mod.load(vault)
        member = topics_mod.memberships(items, topic_list) if topic_list else {}
    except Exception:  # noqa: BLE001
        topic_list, member = [], {}
    for it in items:
        it["topics"] = member.get(str(it.get("id")), [])
    storage.atomic_write_text(
        data_path,
        json.dumps(
            {
                "built_at": now.isoformat(),
                "pages": pages,
                "count": len(items),
                "cats_order": cats_order,
                "cats": [{"name": name, "keywords": list(kws)} for name, kws in effective_big_cats()],
                "topics": [t["name"] for t in topic_list],
                "aliases": ALIASES,
                "items": items,
                "pinyin_chars": pinyin_chars(items),
                # 第 4 批：状态文案唯一源（CONVENTIONS §3.1），页面只从这里取 label / hover，不自己写
                "state_registry": _state_registry(),
            },
            ensure_ascii=False,
            indent=1,
        ),
    )

    catalog_path = vault / pages["catalog"]
    storage.atomic_write_text(catalog_path, _PAGE_HEADER.replace("---\n", "---\nlb-page: catalog\n", 1) + _DATAVIEWJS + "\n")

    storage.atomic_write_text(vault / pages["chat"], _CHAT_HEADER.replace("---\n", "---\nlb-page: chat\n", 1) + _CHATJS + "\n")

    starred_js = _DATAVIEWJS.replace("const simplePage = false;", "const simplePage = true;").replace("const starredPage = false;", "const starredPage = true;")
    storage.atomic_write_text(vault / pages["starred"], _PAGE_HEADER.replace("---\n", "---\nlb-page: starred\n", 1) + starred_js + "\n")

    # 部署笔记底部批注块用的共享脚本（每篇笔记的 bootstrap 会 adapter.read 它）；前面拼上共享前导。
    # 每篇笔记里烤死的 bootstrap（render._annotate_block）不动：改它要重渲全部笔记，它只负责找仓根、载入这份脚本。
    storage.atomic_write_text(
        vault / "_archive" / "annotate-view.js",
        _PAGE_LIB + "\n" + (_ASSETS / "annotate-view.js").read_text(encoding="utf-8"),
    )

    storage.atomic_write_text(
        vault / "_archive" / STATE_NAME,
        json.dumps({"last_built": now.isoformat()}, ensure_ascii=False, indent=1),
    )
    from .remove import publish_trash
    publish_trash(vault)
    try:  # 第 4 批：顺手核一次同步进程（running 但进程已死 → 落盘 INTERRUPTED，页面不再自己判 pid）
        from . import sync_state
        sync_state.current()
    except Exception:  # noqa: BLE001
        pass
    return catalog_path, len(items), data_path


PATCHABLE = frozenset({"starred", "starred_at"})


def patch_items(updates: dict[str, dict[str, Any]], vault: Path | None = None, *, wait_s: float = 5) -> int:
    """把几篇的少量字段（星标）就地改进 catalog-data.json，不整份重建（第 2 批，CONVENTIONS §5.6）：
    目录页以 catalog-data 的 starred 为准，不再每次打开读几百份 notes.json。

    和 build 抢同一把锁；拿不到（正在重建）就跳过——重建本身会从 notes.json 读到最新星标。
    文件不在 / 读坏了也跳过（fail-open，星标本身已经写进 notes.json）。返回改了几篇。"""
    vault = vault or storage.vault_root()
    data_path = vault / "_archive" / DATA_NAME
    if not updates or not data_path.exists():
        return 0
    try:
        with storage.file_lock("catalog-build", wait_s=wait_s, owner="catalog.patch_items"):
            data = json.loads(data_path.read_text(encoding="utf-8"))
            changed = 0
            for it in data.get("items") or []:
                fields = updates.get(str(it.get("id")))
                if not fields:
                    continue
                for key, value in fields.items():
                    if key in PATCHABLE and it.get(key) != value:
                        it[key] = value
                        changed += 1
            if changed:
                storage.atomic_write_text(data_path, json.dumps(data, ensure_ascii=False, indent=1))
            return changed
    except (storage.LockBusy, OSError, ValueError):
        return 0


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
