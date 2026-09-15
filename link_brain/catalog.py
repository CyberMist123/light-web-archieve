"""收藏目录页（封面瀑布流版）。

Owner 2026-09-15 拍板改法（推翻 09-07 的「小模型 category 分文件夹」）：
- **组织轴是 tag，不是文件夹**。文件夹分类一条笔记只能进一个夹子、丢多维信息，且
  移文件是破坏性的（E2N 就得靠「只在子目录移、不删正文」自保）。tag 不动文件、随便加减，
  天生贴合她「加减 tag」的习惯，也给以后的模糊搜索留好轴。tag 数据本来就在每篇 frontmatter 里
  （Lot 4 归一 + 合并 + 她手写），这里直接拿来当筛选轴。
- 页面 = 封面卡片墙（抄小红书发现页那种瀑布流），点标签**加/减**筛选（绿=要、红划掉=排除）+ 搜索框。
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


def _cats(tags: list[str]) -> list[str]:
    hay = " ".join(tags).lower()
    hits = [name for name, kws in BIG_CATS if any(k in hay for k in kws)]
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
    status = meta.get("attachments_status", "none")
    has_bytes = (obj_dir / "attachments").is_dir() and any(
        (obj_dir / "attachments").glob("*")
    )
    if has_bytes:
        return "downloaded"
    if status == "metadata_only":
        return "待补"
    return "none"


def collect(vault: Path, source: str = "xiaohongshu") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
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
        if not tags:
            # 没渲染出可见笔记时退回 source.json / extracted 的 tag
            source_doc = _load_json(obj_dir / "raw" / f"v{version:04d}" / "source.json") or {}
            note = source_doc.get("note") if isinstance(source_doc, dict) else {}
            tags = [str(t).strip() for t in (note or {}).get("tags", []) if str(t).strip()]
            if not tags and isinstance(data, dict):
                tags = [str(t).strip() for t in data.get("tags", []) if str(t).strip()]
        comment_count, last_comment = _last_comment(vault, visible)
        archived = _parse_dt(meta.get("first_archived_at"))
        items.append(
            {
                "id": meta.get("item_id", source_id),
                "title": meta.get("title") or source_id,
                "note": visible,
                "cover": _cover(obj_dir, source, source_id, version),
                "summary": _clip(summary),
                "tags": tags,
                "cats": _cats(tags),
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
# 顶部大类 tab（小红书发现页那种）+「或」筛选（选多类 = 命中任一）+ 搜索；卡片墙铺满、放大。
_DATAVIEWJS = r"""```dataviewjs
const DATA_PATH = "_archive/catalog-data.json";
const root = dv.container;

const style = document.createElement("style");
style.textContent = `
/* 目录页铺满：解除 Obsidian 可读行宽的限制（只作用于挂了 lb-catalog 的页） */
.markdown-preview-view.lb-catalog .markdown-preview-sizer,
.markdown-source-view.lb-catalog .cm-sizer,
.markdown-source-view.lb-catalog .cm-contentContainer{max-width:none!important;width:100%!important;}
.lbc-wrap{--lbc-gap:14px;}
.lbc-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:.1em 0 .55em;}
.lbc-title{font-size:1.35em;font-weight:700;}
.lbc-sub{color:var(--text-muted);font-size:.82em;}
.lbc-search{width:100%;box-sizing:border-box;padding:8px 13px;border-radius:10px;border:1px solid var(--background-modifier-border);background:var(--background-primary);color:var(--text-normal);margin-bottom:.6em;font-size:.95em;}
.lbc-tabs{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:.9em;align-items:center;}
.lbc-tab{cursor:pointer;user-select:none;font-size:.9em;line-height:1;padding:8px 15px;border-radius:999px;background:var(--background-secondary);color:var(--text-muted);transition:all .12s;white-space:nowrap;}
.lbc-tab:hover{color:var(--text-normal);}
.lbc-tab.on{background:var(--interactive-accent);color:var(--text-on-accent);font-weight:600;}
.lbc-grid{column-gap:var(--lbc-gap);column-width:clamp(220px,19vw,300px);}
.lbc-card{break-inside:avoid;margin:0 0 var(--lbc-gap);border-radius:14px;overflow:hidden;background:var(--background-secondary);border:1px solid var(--background-modifier-border);cursor:pointer;transition:transform .12s,box-shadow .12s;}
.lbc-card:hover{transform:translateY(-3px);box-shadow:0 6px 18px rgba(0,0,0,.2);}
.lbc-cover{display:block;width:100%;height:auto;background:var(--background-modifier-hover);}
.lbc-nocover{aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;color:var(--text-faint);font-size:2.4em;background:var(--background-modifier-hover);}
.lbc-body{padding:10px 12px 12px;}
.lbc-ctitle{font-weight:600;font-size:1em;line-height:1.32;margin-bottom:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbc-csum{color:var(--text-muted);font-size:.83em;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:6px;}
.lbc-ctags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:5px;}
.lbc-ctag{font-size:.72em;color:var(--text-accent);background:var(--background-modifier-hover);padding:2px 7px;border-radius:6px;}
.lbc-cmeta{font-size:.74em;color:var(--text-faint);display:flex;flex-wrap:wrap;gap:8px;}
.lbc-empty{color:var(--text-muted);padding:2em 0;text-align:center;}
`;
root.appendChild(style);

let data;
try {
  data = JSON.parse(await app.vault.adapter.read(DATA_PATH));
} catch (e) {
  root.createEl("div", {text: "读不到目录数据（" + DATA_PATH + "）——先跑一次 `python -m link_brain catalog`。"});
  return;
}
const items = data.items || [];
const catsOrder = data.cats_order || [];
const wrap = root.createEl("div", {cls: "lbc-wrap"});
const head = wrap.createEl("div", {cls: "lbc-head"});
head.createEl("span", {cls: "lbc-title", text: "📌 小红书收藏"});
const sub = head.createEl("span", {cls: "lbc-sub"});

const search = wrap.createEl("input", {cls: "lbc-search"});
search.type = "text";
search.placeholder = "搜标题 / 概要…";

const sel = new Set();  // 选中的大类；空 = 全部。多选 = 或（命中任一即显示）
const tabBar = wrap.createEl("div", {cls: "lbc-tabs"});
const grid = wrap.createEl("div", {cls: "lbc-grid"});

function renderTabs() {
  tabBar.empty();
  const all = tabBar.createEl("span", {cls: "lbc-tab", text: "全部"});
  if (!sel.size) all.addClass("on");
  all.onclick = () => {sel.clear(); renderTabs(); renderCards();};
  for (const c of catsOrder) {
    const t = tabBar.createEl("span", {cls: "lbc-tab", text: c});
    if (sel.has(c)) t.addClass("on");
    t.onclick = () => {sel.has(c) ? sel.delete(c) : sel.add(c); renderTabs(); renderCards();};
  }
}

function match(it) {
  if (sel.size) {
    const cats = it.cats || [];
    if (!cats.some((c) => sel.has(c))) return false;  // 或：命中任一大类
  }
  const q = search.value.trim().toLowerCase();
  if (q) {
    const hay = ((it.title || "") + " " + (it.summary || "") + " " + (it.tags || []).join(" ")).toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function renderCards() {
  grid.empty();
  const shown = items.filter(match);
  sub.setText(`共 ${items.length} 篇` + (shown.length !== items.length ? ` · 筛出 ${shown.length}` : "") + ` · 更新 ${(data.built_at || "").slice(0, 16).replace("T", " ")}`);
  if (!shown.length) {
    grid.createEl("div", {cls: "lbc-empty", text: "没有符合的收藏"});
    return;
  }
  for (const it of shown) {
    const card = grid.createEl("div", {cls: "lbc-card"});
    if (it.cover) {
      const img = card.createEl("img", {cls: "lbc-cover"});
      img.loading = "lazy";
      try {img.src = app.vault.adapter.getResourcePath(it.cover);} catch (e) {}
    } else {
      card.createEl("div", {cls: "lbc-nocover", text: it.kind === "video" ? "🎬" : "📄"});
    }
    const body = card.createEl("div", {cls: "lbc-body"});
    body.createEl("div", {cls: "lbc-ctitle", text: it.title || "（无题）"});
    if (it.summary) body.createEl("div", {cls: "lbc-csum", text: it.summary});
    if ((it.tags || []).length) {
      const tb = body.createEl("div", {cls: "lbc-ctags"});
      for (const t of it.tags.slice(0, 4)) tb.createEl("span", {cls: "lbc-ctag", text: "#" + t});
    }
    const meta = body.createEl("div", {cls: "lbc-cmeta"});
    if (it.date) meta.createEl("span", {text: it.date});
    if (it.kind === "video") meta.createEl("span", {text: "🎬"});
    if (it.attachment && it.attachment !== "none") meta.createEl("span", {text: it.attachment === "downloaded" ? "📎" : "📎待补"});
    if (it.comments) meta.createEl("span", {text: "💬" + it.comments});
    card.onclick = () => {if (it.note) app.workspace.openLinkText(it.note, "", false);};
  }
}

search.oninput = () => renderCards();
renderTabs();
renderCards();
```"""

_PAGE_HEADER = (
    "---\n"
    "cssclasses: [lb-catalog]\n"
    "---\n"
    "> [!tip] 封面瀑布流目录：点标签**加/减**筛（绿=要、红划掉=排除），支持搜索、点卡片开笔记。\n"
    "> 需 **Dataview** 插件并在其设置里打开 **Enable JavaScript Queries**。每晚同步后自动重写。\n"
    "\n"
)


def build(vault: Path | None = None, *, source: str = "xiaohongshu") -> tuple[Path, int, Path]:
    vault = vault or storage.vault_root()
    now = datetime.now().astimezone()
    items = collect(vault, source)

    data_path = vault / "_archive" / DATA_NAME
    data_path.parent.mkdir(parents=True, exist_ok=True)
    cats_order = [name for name, _ in BIG_CATS] + [OTHER_CAT]
    present = {c for it in items for c in it["cats"]}
    cats_order = [c for c in cats_order if c in present]
    data_path.write_text(
        json.dumps(
            {
                "built_at": now.isoformat(),
                "count": len(items),
                "cats_order": cats_order,
                "items": items,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    catalog_path = vault / CATALOG_NAME
    catalog_path.write_text(_PAGE_HEADER + _DATAVIEWJS + "\n", encoding="utf-8")

    (vault / "_archive" / STATE_NAME).write_text(
        json.dumps({"last_built": now.isoformat()}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return catalog_path, len(items), data_path


def run(args) -> int:
    path, total, data_path = build()
    print(f"目录已重写：{path}（{total} 篇）")
    print(f"数据：{data_path}")
    print("提示：OB 需装 Dataview 插件并打开「Enable JavaScript Queries」，页面才会渲染。")
    return 0
