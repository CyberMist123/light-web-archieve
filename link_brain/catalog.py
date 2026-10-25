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
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pypinyin import lazy_pinyin

from . import storage
from .provenance import collected_by
from .note import annotation_text
from .ocrtext import clean_ocr
from .retrieval import pinyin_text

CATALOG_NAME = "小红书收藏目录.md"
DATA_NAME = "catalog-data.json"
# 1015：检索全文（search_fields）和整音节拼音占了 catalog-data 九成（15.8MB 里 14MB），目录首开不需要——
# 拆进这份，按 id 存；页面第一次真搜索时才读（catalog-search.js ensureSearchIndex），Python 读方经 merge_search_index 并回。
SEARCH_NAME = "catalog-search-index.json"
SEARCH_KEYS = ("search_fields", "pinyin")
STATE_NAME = "catalog-state.json"
# 1023 ARCH-AUDIT 第 1 批：目录的输入（meta / 标签 / 专辑 / 回收站…）变了就记一笔「待重建」，
# 统一由 ensure_fresh 重建；build 写完且期间没人再记，才清掉。文件在 = 目录数据落后于库。
DIRTY_NAME = "catalog-dirty.json"
# 1025 开源前 P0：catalog-data 的格式版本号（插件 ↔ 后端握手）。页面脚本 lb-page-lib.js 里的 CATALOG_SCHEMA 必须和它相等
# （tests/test_catalog.py::test_build_writes_schema_and_page_lib_agrees 守着）。字段改了页面读不懂时 +1：
# 页面读到对不上的数据，说一句「重建目录 / 更新插件」而不是崩或者画错。
CATALOG_SCHEMA = 1

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


# 1008（L6·B2）：卡片角标要减去她隐藏的 (item_id, 细分码)，接口那一侧的码以 ai-health 为准。
# 这两份是全库共用的：一次 catalog build 只读一回（按两个文件的 mtime 缓存），不在每篇里各读一遍 problems.jsonl。
_CTX: dict[str, Any] = {"key": None, "val": None}
# 卡片上的接口码来自哪份对象文件 → 那个能力在 ai-health.json 里的名字
_API_CAP = {"vision": "visionAI", "extracted": "summaryAI"}


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _ai_off() -> set[str]:
    """「开始」页没勾的 AI 能力（轻量版 = 两个都没勾）：{'summaryAI', 'visionAI'} 的子集。读不到设置 = 都开着（照旧出标）。"""
    try:
        from . import providers
        return {cap for cap in ("summaryAI", "visionAI") if providers.setup_off_reason(cap)}
    except Exception:  # noqa: BLE001
        return set()


def _problem_context() -> dict[str, Any]:
    """{hidden: {(item_id, 细分码)}, ai_open: {能力名}, api_codes: set, ai_off: {能力名}}。读不动就当没有（fail-open：照旧出标）。"""
    from . import ai_config, ai_health, problems
    key = (str(storage.archive_root()), _mtime(problems.path()), _mtime(problems.pending_dir()),  # 旁路的行（等不到锁时写的）也算
           _mtime(storage.archive_root() / ai_health.FILE_NAME),
           _mtime(ai_config.data_json_path()))
    if _CTX["key"] != key:
        try:
            hidden = problems.dismissed_pairs()
        except Exception:  # noqa: BLE001
            hidden = set()
        try:
            ai_open = set(ai_health._load())
        except Exception:  # noqa: BLE001
            ai_open = set()
        _CTX.update(key=key, val={"hidden": hidden, "ai_open": ai_open, "api_codes": set(ai_health.API_CODES),
                                  "ai_off": _ai_off()})
    return _CTX["val"]


def item_problems(obj_dir: Path, report: dict[str, Any], vision: dict[str, Any], transcript: dict[str, Any],
                  extracted: dict[str, Any]) -> list[dict[str, str]]:
    """这一篇眼下的问题（CONVENTIONS §3.4）：只从各对象文件推出，**不读 problems.jsonl**；文案只从登记表取。

    [{code, label, hover, group, action}]，每个码一条（同一篇几张图 / 几份附件同码只列一次，原因取第一条）。
    来源：attachments.json 的 conversion_failed · attachment-state.json 的下载错误 · transcript.json ·
    vision.json（第一层识图接口故障；1017 起第二层精细识别放弃不再出标）· extracted.json（概要失败）· enrich-state.json（连着失败暂时放弃）。
    SKIPPED（没配置 / 关了）不算问题，不列。

    1008：她在问题面板隐藏了的 (item_id, 细分码) 不出标；接口那一侧的码（key 失效 / 欠费 / 断网 / 限流 / 5xx / 服务忙）
    只在 ai-health.json 里这个能力确实还开着时才照原码出标，否则降成灰色「待补识图 / 概要」（这篇确实还缺，照实显示）；
    补查判定「原帖打不开」的（derived/web_recheck.json 的 gone）出「原帖已删除」标（只上卡片、不进问题列表）。"""
    out: dict[str, dict[str, str]] = {}
    ctx = _problem_context()
    item_id = str(report.get("item_id") or "")

    def add(code, reason, action=None, next_at=None, cap=None):
        if not code:
            return
        caps = cap if isinstance(cap, tuple) else ((cap,) if cap else ())
        if caps and all(c in ctx.get("ai_off", ()) for c in caps):
            return  # 1009 她：轻量版（没勾 AI）本来就不做识图 / 概要，卡片上什么都不标
        if cap and str(code) in ctx["api_codes"] and not (set(caps) & ctx["ai_open"]):
            # 1009 她：当时接口出错、接口现在已经好了的——后台静默补（状态栏一行进度），不上卡片角标
            # （1008 的灰色「待补识图 / 概要」撤掉；接口还坏着的照原码出，问题面板里那一条照旧）
            return
        try:
            row = _problem(code, reason, action, next_at)
        except Exception:  # noqa: BLE001 - 坏码不拖垮目录重建
            return
        if row["code"].startswith("SKIPPED."):
            return
        if (item_id, row["code"].split(".", 1)[1]) in ctx["hidden"]:
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
    # 10-04 她定：「视频里没人说话」不上卡片（连画面字幕也没读到的也不标）——问题面板里有就够了（videos.py 照旧记进 problems.jsonl）
    # 10-04 20:00 她定：「视频没有音轨」（no_audio）同样不上卡片，问题面板照旧
    if status == "failed":
        add(transcript.get("code") or "TRANSIENT.SERVICE_BUSY", transcript.get("error") or "语音识别失败",
            "retry_later", transcript.get("retry_after"))
    for im in (vision.get("images") or []) if isinstance(vision, dict) else []:
        visual = im.get("visual") or {}
        if visual.get("status") not in (None, "ok") and visual.get("code"):
            add(visual["code"], visual.get("error") or "识图失败", cap=_API_CAP["vision"])
        # 1017 作者裁决：精细识别没过、退回第一层的不是故障——不上卡片角标、不进问题面板，机读版里标「识图存疑」
    state = _load_json(obj_dir / "enrich-state.json") or {}
    from .enrich import MAX_FAILS
    if isinstance(state, dict) and int(state.get("fails") or 0) >= MAX_FAILS:
        add("TRANSIENT.RETRY_EXHAUSTED", f"识图 / 概要连着 {state.get('fails')} 次没补成：{state.get('last_error') or ''}",
            "gave_up", state.get("retry_after"), cap=(_API_CAP["vision"], _API_CAP["extracted"]))
    elif isinstance(extracted, dict) and extracted.get("status") == "failed":
        add(extracted.get("code") or "TRANSIENT.SERVICE_BUSY", f"概要没生成：{extracted.get('error') or ''}",
            cap=_API_CAP["extracted"])
    mark = _load_json(obj_dir / "derived" / "web_recheck.json") or {}
    if isinstance(mark, dict) and mark.get("gone"):
        add("PERMANENT.NOTE_GONE", "原帖打不开（可能已删或仅作者可见），本地存档还在")
    restricted = _load_json(obj_dir / "derived" / "restricted.json") or {}
    from .restricted import confirmed as _restricted_confirmed
    if isinstance(restricted, dict) and _restricted_confirmed(restricted) and not (isinstance(mark, dict) and mark.get("gone")):
        # 1017 她：「这些帖子是真的不见了」——隔天还打不开 = 原帖不在了：和 NOTE_GONE 同一个安静角标，不叫她去验证
        add("PERMANENT.NOTE_GONE", "原帖打不开了（多半删了或仅作者可见），本地存档还在")
    return list(out.values())


def _flat_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """一级评论 + 它的楼中楼，按楼层顺序摊平（顺序同 llm.comment_labels；目录只要原文，不要给模型的短编号）。"""
    out: list[dict[str, Any]] = []
    for c in comments or []:
        out.append(c)
        out.extend(c.get("sub_comments") or [])
    return out


def _is_comment_image(image: dict[str, Any]) -> bool:
    """评论区的图（资产名 comment-<评论id>-<n>.*）；正文图是 image-NNN.*。"""
    return bool(re.search(r"(^|/)comment-[0-9a-f]+-\d+\.", str(image.get("asset") or "")))


def highlight_text(visible_text: str | None, notes_doc: dict[str, Any] | None = None) -> str:
    """她划的重点（1015 第二批进检索）：可见笔记里的 <mark> / ==x== + notes.json 的 highlights（[{text}] 或 [str]，
    带 deleted 的不算）。一条一行；读不出 = 空（fail-open）。"""
    out: list[str] = []
    try:
        from .render import collect_highlights, existing_content_layer
        layer = existing_content_layer(visible_text) if visible_text else None
        out.extend(collect_highlights(layer if layer is not None else visible_text))
    except Exception:  # noqa: BLE001 - 重点只是检索加成
        pass
    raw = notes_doc.get("highlights") if isinstance(notes_doc, dict) else None
    for h in raw if isinstance(raw, list) else []:
        text = h.get("text") if isinstance(h, dict) and not h.get("deleted") else h if isinstance(h, str) else ""
        text = str(text or "").strip()
        if text and text not in out:
            out.append(text)
    return "\n".join(out)


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
    try:   # 1019 专辑：她在小红书里给收藏分的组（albums sync 读来的），和标签分开
        from . import albums as albums_mod
        album_map = albums_mod.note_albums() if source == "xiaohongshu" else {}
    except Exception:  # noqa: BLE001 - 读不到就当没有专辑
        album_map = {}
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
        report = inventory(obj_dir, meta)
        vision = _load_json(obj_dir / "derived" / "vision.json") or {}
        transcript = _load_json(obj_dir / "derived/transcript.json") or {}
        notes_doc = _load_json(obj_dir / "notes.json")
        notes_doc = notes_doc if isinstance(notes_doc, dict) else {}
        ok_images = [im for im in vision.get("images", []) if im.get("status") == "ok"]
        search_fields = {
            # 1015 第二批 ask：视频文字稿 / 画面文字各成一路（结果标来源类型）；评论区的图单列 comment_ocr（不和正文图混）
            "transcript": str(transcript.get("text") or ""),
            "screen": str((transcript.get("screen") or {}).get("text") or ""),
            "body": str(note.get("body") or ""),
            # 评论只放原文进检索：评论者昵称不进（昵称「不是鱼露是鲈鱼」会被当成内容命中）；说话人由问收藏证据阶段另挂
            "comments": "\n".join(str(c.get("text") or "") for c in _flat_comments(source_doc.get("comments") or [])),
            # 图片文字 + 识图结果（表格 Markdown / 图片描述）一起进检索；精细识图（第二层 refined）成功就用它替代第一层
            "ocr": "\n".join(filter(None, (_image_search_text(im) for im in ok_images if not _is_comment_image(im)))),
            "comment_ocr": "\n".join(filter(None, (_image_search_text(im) for im in ok_images if _is_comment_image(im)))),
            "attachments": "\n\n".join(p.read_text(encoding="utf-8") for p in sorted((obj_dir / "derived" / "attachments").glob("*.md"))),
            # 第 10 批：她自己的批注进检索（词法 + 语义）；问收藏另按 notes.json 的修改时间现读，不必等重建目录
            "notes": annotation_text(notes_doc),
            # 1015 第二批 ask：她划的重点进检索（和批注同权）
            "highlights": highlight_text(visible_text, notes_doc),
        }
        # 新加的三路空着就不写（catalog-data 体积不涨）；老字段照旧总在
        search_fields = {k: v for k, v in search_fields.items() if v or k not in ("screen", "comment_ocr", "highlights")}
        archived = _parse_dt(meta.get("first_archived_at"))
        items.append(
            {
                "id": meta.get("item_id", source_id),
                "title": meta.get("title") or source_id,
                "note": visible,
                "notes_path": f"_archive/{source}/{source_id}/notes.json",
                "starred": bool(notes_doc.get("starred")),
                "starred_at": notes_doc.get("starred_at"),
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
                "albums": album_map.get(source_id, []),
                # 批次 D · N9：原帖话题（正文里显示的那一串 #）；目录「#x」筛选看 tags ∪ hashtags（她改过的 tags 可能删掉了某个）
                "hashtags": [str(t).strip().lstrip('#') for t in (note.get('hashtags') or []) if str(t).strip().lstrip('#')][:30],
                "cats": _cats(tags, big_cats),
                "kind": meta.get("kind", "image"),
                "date": archived.strftime("%Y-%m-%d") if archived else "",
                # 1015 第二批：发帖日期（她说「2024 年存的」多半指那年的帖子；date 是入库日期）
                "published": str(note.get("published_at") or "")[:10],
                "ts": archived.isoformat() if archived else "",
                "comments": comment_count,
                "last_comment": last_comment,
                "attachment": (badge := _attachment_badge(obj_dir, meta, report)),
                "attachment_reason": _attachment_reason(obj_dir, meta, badge),
                # 第 4 批：卡片悬停的问题原因（label / hover 已从 problems 登记表取好；attachment_reason 照留）
                "problems": item_problems(obj_dir, report, vision, transcript, extracted),
                # 1020 谁收的：""=她自己的收藏；聊天分享 / fable / 项目名（provenance.py）。目录默认只看 ""
                "src": collected_by(meta),
                # 收藏来自哪个号（0926）：同步时写进 meta.favorited_by，供按账号筛选
                "accounts": [a.get("nickname") or a.get("user_id") for a in (meta.get("favorited_by") or [])
                             if isinstance(a, dict)],
            }
        )
    # 新→旧
    items.sort(key=lambda it: it.get("ts") or "", reverse=True)
    return items


# ── dataviewjs 页面（样式自注入，不依赖 CSS snippet；读 catalog-data.json 渲染） ──
_ASSETS = Path(__file__).parent / "assets"
# 第 2 批：三张页和批注块共用的前导（CONVENTIONS §5：仓根 / 插件 / 页面状态 / 数据版本与缓存 / 旧 DOM 复用 / 计时），内联在最前面
_PAGE_LIB = (_ASSETS / "lb-page-lib.js").read_text(encoding="utf-8")
# 目录页 / 已收藏页的整段脚本（前导 + 搜索 + 页面，约 210KB）
_CATALOG_SCRIPT = _PAGE_LIB + "\n" + (_ASSETS / "catalog-search.js").read_text(encoding="utf-8") + "\n" + (_ASSETS / "catalog-view.js").read_text(encoding="utf-8") + "\n"
_STARRED_SCRIPT = _CATALOG_SCRIPT.replace("const simplePage = false;", "const simplePage = true;").replace("const starredPage = false;", "const starredPage = true;")
# 1017 目录页首开：以前这 210KB 直接烤进 md 的 dataviewjs 块——每次打开，Obsidian 要把它当 Markdown 解析（阅读视图一遍、
# 同一标签页里藏着的编辑视图一遍，编辑视图还按 JavaScript 逐行着色 3400 行），Dataview 再在自己的模块作用域里 direct eval
# 两遍（阅读视图 + 藏着的编辑视图），页面代码里每个全局名字都走动态作用域查找（同一段代码比普通函数慢约四成）。
# 现在 md 里只放一小段引导：脚本存 _archive/catalog-page.js / starred-page.js（和批注块的 _archive/annotate-view.js 同一个做法，
# 手机同步过去照样能用）；引导按 Obsidian 文件索引里的 mtime:size 认版本，编译好的函数挂在 globalThis 上（同一版本只编译一次）。
CATALOG_SCRIPT_NAME = "catalog-page.js"
STARRED_SCRIPT_NAME = "starred-page.js"
_BOOTSTRAP = (_ASSETS / "page-bootstrap.js").read_text(encoding="utf-8")
# 1021 目录页改版：标题 / 数字字体（Cinzel、Cormorant Garamond Italic 拉丁子集 + OFL 许可证）随包发，重建目录时拷到
# _archive/fonts/（和页面脚本同一个产物目录，手机同步过去照样能显示）；页面用 getResourcePath 拼 @font-face，离线可用、不连 Google Fonts。
_FONTS = _ASSETS / "fonts"
FONTS_DIR = "fonts"


def publish_fonts(vault: Path) -> list[str]:
    """把 assets/fonts/ 拷进 _archive/fonts/（内容一样就不写，免得每次重建都让同步盘搬一遍）。返回这次写了的文件名。

    字体只是外观：拷失败不影响目录重建（页面退回系统衬线字体）。"""
    written: list[str] = []
    dest = vault / "_archive" / FONTS_DIR
    for src in sorted(_FONTS.glob("*")) if _FONTS.is_dir() else []:
        if not src.is_file() or src.suffix.lower() not in (".woff2", ".txt"):
            continue
        try:
            blob = src.read_bytes()
            out = dest / src.name
            try:
                if out.read_bytes() == blob:
                    continue
            except OSError:
                pass
            dest.mkdir(parents=True, exist_ok=True)
            storage.atomic_write_bytes(out, blob)
            written.append(src.name)
        except OSError:
            continue
    return written


def _page_bootstrap(script_name: str) -> str:
    """md 里那一小段 dataviewjs（assets/page-bootstrap.js）：找仓根 → 读（或复用编译好的）_archive/<script_name> → 照原样跑。"""
    return "```dataviewjs\n" + _BOOTSTRAP.replace("__LB_SCRIPT__", script_name).rstrip("\n") + "\n```"


_DATAVIEWJS = _page_bootstrap(CATALOG_SCRIPT_NAME)
# 收藏搜索页 = 极简对话版（chat-view.js），跟浏览目录页分开（Owner 2026-09-17）。
# 1019：问收藏页也走引导（以前 247KB 烤在 md 里，每次切过去 Obsidian 先解析约 290ms 才开跑——perf-log 实测）
CHAT_SCRIPT_NAME = "chat-page.js"
_CHAT_SCRIPT = _PAGE_LIB + "\n" + (_ASSETS / "catalog-search.js").read_text(encoding="utf-8") + "\n" + (_ASSETS / "chat-view.js").read_text(encoding="utf-8") + "\n"
_CHATJS = _page_bootstrap(CHAT_SCRIPT_NAME)
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
                role = "starred" if ("const starredPage = true;" in text or STARRED_SCRIPT_NAME in text) else "catalog"
            elif "_archive/trash-data.json" in text:
                role = "trash"  # 第 3 批以前的回收站页没有页头标记
        if role:
            pages[role] = file.name
    return pages


def split_search(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """(去掉检索字段的 items 浅拷贝, {id: {search_fields, pinyin}})。传进来的 items 不改。"""
    slim, index = [], {}
    for it in items:
        index[str(it.get("id"))] = {k: it[k] for k in SEARCH_KEYS if k in it}
        slim.append({k: v for k, v in it.items() if k not in SEARCH_KEYS})
    return slim, index


_SEARCH_CACHE: dict[str, Any] = {"stamp": None, "items": None}


def load_search_index(vault: Path | None = None) -> dict[str, dict[str, Any]]:
    """{id: {search_fields, pinyin}}；没有 / 读坏了 = {}（fail-open：读方退回没有全文的老样子）。按 mtime 缓存。"""
    path = (vault or storage.vault_root()) / "_archive" / SEARCH_NAME
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
        if _SEARCH_CACHE["stamp"] == stamp:
            return _SEARCH_CACHE["items"]
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    got = raw.get("items") if isinstance(raw, dict) and isinstance(raw.get("items"), dict) else {}
    _SEARCH_CACHE.update(stamp=stamp, items=got)
    return got


def merge_search_index(items: list[dict[str, Any]], vault: Path | None = None) -> list[dict[str, Any]]:
    """就地把检索字段并回 catalog-data 的 items（已经带着的不动：旧格式整份数据照旧能用）。返回 items。"""
    if not any(isinstance(it, dict) and "search_fields" not in it for it in items):
        return items
    index = load_search_index(vault)
    if not index:
        return items
    for it in items:
        if isinstance(it, dict) and "search_fields" not in it:
            extra = index.get(str(it.get("id")))
            if isinstance(extra, dict):
                for k in SEARCH_KEYS:
                    if k in extra:
                        it[k] = extra[k]
    return items


def _state_registry() -> dict[str, dict[str, str]]:
    from . import problems
    return problems.registry_for_js()


def _counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    """篇数唯一口径（ARCH-AUDIT §7）：all = 目录里全部（回收站的已经不在 items 里）；mine = 来源为「我的收藏」（src 空）；
    by_src = 其它来源各几篇（聊天分享 / Fable / 项目名…）。"""
    by_src: dict[str, int] = {}
    for it in items:
        src = it.get("src") if isinstance(it.get("src"), str) else ""
        if src:
            by_src[src] = by_src.get(src, 0) + 1
    return {"all": len(items), "mine": len(items) - sum(by_src.values()), "by_src": by_src}


def _write_if_changed(path: Path, text: str) -> bool:
    """内容一样就不写（1023：每次重建都重写页面 md → Obsidian 当文件改了 → Dataview 整页重画 = 刷屏）。"""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    storage.atomic_write_text(path, text)
    return True


def _same_content(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """两份 catalog-data 除了生成时间以外是不是一样（built_at、index.generated_at 每次都变，不算内容）。"""
    def strip(d: dict[str, Any]) -> dict[str, Any]:
        d = dict(d)
        d.pop("built_at", None)
        if isinstance(d.get("index"), dict):
            d["index"] = {k: v for k, v in d["index"].items() if k != "generated_at"}
        return d
    return strip(a) == strip(b)


def mark_dirty(reason: str, vault: Path | None = None) -> None:
    """目录的输入变了：记一笔待重建（fail-open，记不上只是等下一次重建）。"""
    try:
        path = (vault or storage.vault_root()) / "_archive" / DIRTY_NAME
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        reasons = [r for r in (old.get("reasons") or []) if r != reason][-19:] + [reason]
        path.parent.mkdir(parents=True, exist_ok=True)
        storage.atomic_write_text(path, json.dumps({
            "since": old.get("since") or datetime.now().astimezone().isoformat(),
            "seq": int(old.get("seq") or 0) + 1, "reasons": reasons}, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


def dirty_state(vault: Path | None = None) -> dict[str, Any] | None:
    try:
        return json.loads(((vault or storage.vault_root()) / "_archive" / DIRTY_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ensure_fresh(vault: Path | None = None, *, wait_s: float = 0) -> str:
    """有待重建就重建。返回 "clean"（本来就新）/ "built" / "busy"（别人正在建，记号留着等它或下一次）/ "failed"。"""
    vault = vault or storage.vault_root()
    if dirty_state(vault) is None:
        return "clean"
    try:
        with storage.file_lock("catalog-build", wait_s=wait_s, owner="catalog.ensure_fresh"):
            if dirty_state(vault) is None:     # 等锁期间别人建完了
                return "clean"
            build(vault)
        return "built"
    except storage.LockBusy:
        return "busy"
    except Exception as exc:  # noqa: BLE001 - 目录重建失败不挡调用方（同步 / 导入已经成功了）
        import sys
        print(f"[catalog] 待重建没建成（{type(exc).__name__}: {exc}），下次再试", file=sys.stderr)
        return "failed"


def _clear_dirty(vault: Path, seen: dict[str, Any] | None) -> None:
    """build 开始时看到的那份记号没被更新过才删（建的过程中又有新改动 → 留着，下一次再建）。"""
    if seen is None:
        return
    path = vault / "_archive" / DIRTY_NAME
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("seq") == seen.get("seq"):
            path.unlink()
    except (OSError, ValueError):
        pass


@storage.locked("catalog-build", wait_s=120)  # CONVENTIONS §6.4：remove / attachments / topics / 插件都会调
def build(vault: Path | None = None, *, source: str = "xiaohongshu") -> tuple[Path, int, Path]:
    vault = vault or storage.vault_root()
    now = datetime.now().astimezone()
    dirty_seen = dirty_state(vault)
    items = collect(vault, source)
    pages = library_pages(vault)

    data_path = vault / "_archive" / DATA_NAME
    data_path.parent.mkdir(parents=True, exist_ok=True)
    from .retrieval import ALIASES
    cats_order = [name for name, _ in effective_big_cats()] + [OTHER_CAT]
    present = {c for it in items for c in it["cats"]}
    cats_order = [c for c in cats_order if c in present]
    # 10-10 索引树：目录页顶部分类 = 索引.md 的第一级，每篇的 cats = 它所在的第一级节点（没归进任何节点 = 未归类）。
    # 解析 / 归类只在 indextree（第一次没有 索引.md 时按上面这套关键词迁移出一版，第一天和今天分得一样）。
    # fail-open：索引算不出来就照旧按关键词分。
    index_info = None
    try:
        from . import indextree
        idx = indextree.build(vault, items=items, catalog_built_at=now.isoformat(), force=True, auto_draft=False)
        per = indextree.item_cats(idx["_parsed"], idx["_result"])
        for it in items:
            it["cats"] = per.get(str(it.get("id")), [indextree.UNCLASSIFIED])
        cats_order = list(idx["cats_order"])
        index_info = {"file": idx["file"], "generated_at": idx["generated_at"], "roots": idx["roots"],
                      "unclassified": idx["unclassified"]["count"], "migrated": bool(idx.get("migrated"))}
        LAST_INDEX.clear(); LAST_INDEX.update(index_info, warnings=len(indextree.real_warnings(idx.get("warnings"))))
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"[catalog] 索引没算出来，顶部分类先照旧按关键词分：{type(exc).__name__}: {exc}", file=sys.stderr)
    # 星标主题（Lot E）：只是展示分组，写进 catalog-data 给目录页 chip 用，不进检索字段。
    # fail-open：topics.json 缺/坏或算隶属出错 = 没有主题，页面与没这功能时一致。
    # p0-catalog：主题向量只读 _archive/topic-vectors.json（夜跑 index catch-up 补），build 不联网；
    # 缓存里没有的主题这次按关键词算，名字记进 topics_vectors_pending（= 主题向量待更新）。
    topics_pending: list[str] = []
    try:
        from . import topics as topics_mod

        topic_list = topics_mod.load(vault)
        member = topics_mod.memberships(items, topic_list, live=False,
                                         pending=topics_pending, vault=vault) if topic_list else {}
    except Exception:  # noqa: BLE001
        topic_list, member = [], {}
        topics_pending.clear()  # 主题整个没算出来：不留半截的「待更新」，和 topics: [] 对得上
    if topics_pending:
        import sys
        print(f"[catalog] 主题向量待更新（这次按关键词算）：{'、'.join(topics_pending)}——夜跑 index catch-up 会补", file=sys.stderr)
    for it in items:
        it["topics"] = member.get(str(it.get("id")), [])
    # 1022 Collection+ 第 4 段 A：边栏「Token 费用 · 本月」= 账本 _archive/usage/YYYY-MM.jsonl 按现价折算；
    # fail-open：账本缺 / 价格表坏 = None，页面显示「—」。
    try:
        from . import usage as usage_mod
        usage_month = usage_mod.month_summary(now=now)
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"[catalog] 本月用量没算出来（{type(exc).__name__}: {exc}），边栏费用显示「—」", file=sys.stderr)
        usage_month = None
    slim_items, search_index = split_search(items)
    payload = {
        "schema": CATALOG_SCHEMA,
        "built_at": now.isoformat(),
        "pages": pages,
        "count": len(items),
        # 1023：篇数唯一口径——两张页显示篇数都读这里（以前目录页按「我的收藏」过滤后数、问收藏页数全部）
        "counts": _counts(items),
        "cats_order": cats_order,
        "cats": [{"name": name, "keywords": list(kws)} for name, kws in effective_big_cats()],
        # 10-10：cats_order / items[].cats 来自索引树时带上它（页面的二级小标签、索引图读 _archive/index-data.json）
        "index": index_info,
        "topics": [t["name"] for t in topic_list],
        "topics_vectors_pending": topics_pending,
        "usage_month": usage_month,
        "aliases": ALIASES,
        "items": slim_items,
        "search_index": SEARCH_NAME,
        "pinyin_chars": pinyin_chars(items),
        # 第 4 批：状态文案唯一源（CONVENTIONS §3.1），页面只从这里取 label / hover，不自己写
        "state_registry": _state_registry(),
    }
    try:
        old_payload = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old_payload = None
    # 1023：内容没变就不动 catalog-data（它的 mtime 就是页面的版本号，一变页面就整面更新）；
    # 「核对过」的时间记在 catalog-state.checked_at，页面判「数据较旧」时一起看。
    changed = not (isinstance(old_payload, dict) and _same_content(old_payload, payload)
                   and (vault / "_archive" / SEARCH_NAME).exists())
    if changed:
        # 先写检索索引再写目录数据：页面看到新目录时索引已经是新的（按 id 并，差一拍也只是少几篇的全文）
        storage.atomic_write_text(
            vault / "_archive" / SEARCH_NAME,
            json.dumps({"built_at": now.isoformat(), "items": search_index}, ensure_ascii=False, separators=(",", ":")),
        )
        storage.atomic_write_text(data_path, json.dumps(payload, ensure_ascii=False, indent=1))

    catalog_path = vault / pages["catalog"]
    # 先写脚本再写页：页面载入时脚本已经是新的
    _write_if_changed(vault / "_archive" / CATALOG_SCRIPT_NAME, _CATALOG_SCRIPT)
    _write_if_changed(vault / "_archive" / STARRED_SCRIPT_NAME, _STARRED_SCRIPT)
    _write_if_changed(vault / "_archive" / CHAT_SCRIPT_NAME, _CHAT_SCRIPT)
    publish_fonts(vault)
    _write_if_changed(catalog_path, _PAGE_HEADER.replace("---\n", "---\nlb-page: catalog\n", 1) + _DATAVIEWJS + "\n")

    _write_if_changed(vault / pages["chat"], _CHAT_HEADER.replace("---\n", "---\nlb-page: chat\n", 1) + _CHATJS + "\n")

    _write_if_changed(vault / pages["starred"], _PAGE_HEADER.replace("---\n", "---\nlb-page: starred\n", 1) + _page_bootstrap(STARRED_SCRIPT_NAME) + "\n")

    # 部署笔记底部批注块用的共享脚本（每篇笔记的 bootstrap 会 adapter.read 它）；前面拼上共享前导。
    # 每篇笔记里烤死的 bootstrap（render._annotate_block）不动：改它要重渲全部笔记，它只负责找仓根、载入这份脚本。
    _write_if_changed(
        vault / "_archive" / "annotate-view.js",
        _PAGE_LIB + "\n" + (_ASSETS / "annotate-view.js").read_text(encoding="utf-8"),
    )

    storage.atomic_write_text(
        vault / "_archive" / STATE_NAME,
        json.dumps({"last_built": (now.isoformat() if changed else (old_payload or {}).get("built_at") or now.isoformat()),
                    "checked_at": now.isoformat()}, ensure_ascii=False, indent=1),
    )
    _clear_dirty(vault, dirty_seen)
    from .remove import publish_trash
    publish_trash(vault)
    if index_info and index_info.get("migrated"):
        # 第一次迁移出 索引.md：起草草稿要花钱，build 不做——只记一笔，交给夜跑 index catch-up（p0-catalog）
        try:
            from . import indextree
            indextree.queue_auto_draft(vault)
        except Exception as exc:  # noqa: BLE001
            import sys
            from .errtext import errtext
            print(f"[catalog] 「待起草索引草稿」没记上：{errtext(exc)}", file=sys.stderr)
    # 10-11 起 build 写完会后台拉起 AI 按内容归类；p0-catalog 起挪到夜跑 index catch-up（手动：index classify）
    try:  # 第 4 批：顺手核一次同步进程（running 但进程已死 → 落盘 INTERRUPTED，页面不再自己判 pid）
        from . import sync_state
        sync_state.current()
    except Exception:  # noqa: BLE001
        pass
    return catalog_path, len(items), data_path


PATCHABLE = frozenset({"starred", "starred_at"})
LAST_INDEX: dict[str, Any] = {}   # 上一次 build 算出的索引摘要（run() 拼提示用）


def file_stat(path: Path) -> dict[str, int]:
    """写者报回的「写完那一刻」的 stat（CONVENTIONS §5.10）：mtime 用毫秒、四舍五入（和 Obsidian 的 Math.round(mtimeMs) 同口径）。"""
    st = os.stat(path)
    return {"mtime": int(round(st.st_mtime_ns / 1e6)), "size": int(st.st_size)}


def patch_items(updates: dict[str, dict[str, Any]], vault: Path | None = None, *, wait_s: float = 5,
                report: dict[str, Any] | None = None) -> int:
    """把几篇的少量字段（星标）就地改进 catalog-data.json，不整份重建（第 2 批，CONVENTIONS §5.6）：
    目录页以 catalog-data 的 starred 为准，不再每次打开读几百份 notes.json。

    和 build 抢同一把锁；拿不到（正在重建）就跳过——重建本身会从 notes.json 读到最新星标。
    文件不在 / 读坏了也跳过（fail-open，星标本身已经写进 notes.json）。返回改了几篇。
    report（批次 D，CM3）：给了就在锁里写完立刻 os.stat，填 report['catalog_stat'] = {mtime, size}（页面 LB.data.adopt 的 written）。"""
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
                if report is not None:
                    report["catalog_stat"] = file_stat(data_path)
            return changed
    except (storage.LockBusy, OSError, ValueError):
        return 0


def drop_items(item_ids: list[str], vault: Path | None = None, *, wait_s: float = 5) -> bool:
    """删除后把这几篇就地摘出 catalog-data.json，不整份重建（1019 她：删 5 篇要好几秒——整份重建冷跑十几秒）。
    和 build / patch_items 抢同一把锁；拿不到、文件不在或读坏了返回 False，调用方退回整份重建。"""
    vault = vault or storage.vault_root()
    data_path = vault / "_archive" / DATA_NAME
    gone = {str(i) for i in item_ids if i}
    if not gone or not data_path.exists():
        return False
    try:
        with storage.file_lock("catalog-build", wait_s=wait_s, owner="catalog.drop_items"):
            data = json.loads(data_path.read_text(encoding="utf-8"))
            items = data.get("items")
            if not isinstance(items, list):
                return False
            data["items"] = [it for it in items if str(it.get("id")) not in gone]
            data["count"] = len(data["items"])
            storage.atomic_write_text(data_path, json.dumps(data, ensure_ascii=False, indent=1))
        return True
    except (storage.LockBusy, OSError, ValueError):
        return False


def dump_cats_text() -> str:
    """把当前生效的大类导成「名称: 关键词1, 关键词2」逐行文本，给设置页那个可编辑文本框预填。"""
    return "\n".join(f"{name}: {', '.join(kws)}" for name, kws in effective_big_cats())


def run(args) -> int:
    if getattr(args, "print_cats", False):
        # 机器可读：设置页「载入当前大类」按钮读这份
        from .read import dump_json

        dump_json({"text": dump_cats_text(), 'ok': True, 'code': '', 'message': '已载入当前分类'})
        return 0
    if getattr(args, "if_dirty", False):
        # 1023：插件启动 / 打开目录页时调：没有待重建就秒回，不碰任何文件
        from .read import dump_json
        state = ensure_fresh(wait_s=0)
        dump_json({"ok": state != "failed", "code": "", "state": state,
                   "message": {"clean": "目录已是最新", "built": "目录已跟上", "busy": "目录正在别处重建"}.get(state, "目录没重建成")})
        return 0
    path, total, data_path = build()
    import sys
    from .read import dump_json
    print(f"目录已重写：{path}（{total} 篇）", file=sys.stderr)
    print(f"数据：{data_path}", file=sys.stderr)
    result = {'ok': True, 'code': '', 'message': f'目录已刷新（{total} 篇）', 'total': total, 'path': str(path), 'data': str(data_path)}
    if LAST_INDEX:
        result['index'] = dict(LAST_INDEX)
        if LAST_INDEX.get('migrated'):
            result['message'] += f"；第一次建了 {LAST_INDEX.get('file')}（按原来的分类，顶部分类不变）"
        elif LAST_INDEX.get('warnings'):
            result['message'] += f"；{LAST_INDEX.get('file')} 有 {LAST_INDEX['warnings']} 处写法要看一眼（目录页「索引」里有）"
    # 只在真没装 / 没开 JS 查询时提示（10-03 她：已经装了还每次刷新目录都弹这句）
    from .doctor import dataview_ready
    if not dataview_ready(storage.vault_root() / ".obsidian"):
        result['dataview_hint'] = 'Dataview 的 JS 查询没开，页面显示不出来'
        result['message'] += '；提示：' + result['dataview_hint']
    dump_json(result)
    return 0
