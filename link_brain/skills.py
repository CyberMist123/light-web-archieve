"""问收藏的技能（skills，1015 第二批 ask 车）。

格式照 Anthropic Agent Skills（SKILL.md = YAML frontmatter name / description + 正文），LWA 自己的字段放 `lwa:` 下：

    ---
    name: recipe
    description: 菜谱 / 做菜 / 吃什么：……（路由只看这一句）
    lwa:
      title: 菜谱                # 设置页 / 前端显示的中文名
      aliases: [菜谱, 做菜]      # 「/菜谱」这类显式点名认的别名
      domains: [food]
      depth_default: detailed    # precise | detailed
      toc_fields: [name, author, hit]
    ---
    （正文 = 作答阶段塞给模型的写法要求，最多 BODY_MAX 字）

两处来源，同 id 用户的覆盖内置：
- 内置：`link_brain/_skills/<id>/SKILL.md`（随程序发布；general / recipe / wiki / travel / research / board）
- 用户：`<vault>/_skills/<id>/SKILL.md`（设置 → 技能页「＋导入」写进来，也可以手放）

安全口径（AGENTS.md 第 7 条）：只读 SKILL.md 的文字（+ 可选 examples.txt），**不执行**任何脚本，导入时也只拷这两个文件；
正文当提示词数据，截到 BODY_MAX，并去掉「忽略以上 / ignore previous」这类越权句。坏文件跳过并登记 SKIPPED.SKILL（fail-open，退 general）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from . import storage

BUILTIN_DIR = Path(__file__).parent / "_skills"
USER_DIRNAME = "_skills"
BODY_MAX = 1500          # 作答时塞给模型的正文上限（字）
DESC_MAX = 200
IMPORT_MAX_BYTES = 64 * 1024
DEFAULT = "general"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_FRONT = re.compile(r"^﻿?---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
_INJECT = re.compile(r"(?im)^.*(?:忽略(?:以上|之前|上面)|ignore (?:all )?(?:previous|above)|system prompt|你现在是).*$")


def user_dir() -> Path:
    return storage.vault_root() / USER_DIRNAME


def parse(text: str, *, fallback_id: str = "") -> dict[str, Any]:
    """SKILL.md 文本 → {id, name, description, title, aliases, lwa, body}；格式不对抛 ValueError（原因可读）。"""
    m = _FRONT.match(text or "")
    if not m:
        raise ValueError("开头没有 --- 包起来的 frontmatter")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter 不是合法 YAML：{str(exc).splitlines()[0][:80]}") from None
    if not isinstance(meta, dict):
        raise ValueError("frontmatter 要是键值对")
    name = str(meta.get("name") or fallback_id or "").strip()
    sid = name.casefold().replace(" ", "-")
    if not _ID_RE.match(sid):
        sid = fallback_id.casefold() if _ID_RE.match(fallback_id.casefold() or "") else ""
    if not sid:
        raise ValueError("name 要是小写英文 / 数字 / - _（≤40 字）")
    desc = " ".join(str(meta.get("description") or "").split())
    if not desc:
        raise ValueError("缺 description（路由靠这一句）")
    lwa = meta.get("lwa") if isinstance(meta.get("lwa"), dict) else {}
    body = _INJECT.sub("", text[m.end():]).strip()
    aliases = [str(a).strip() for a in (lwa.get("aliases") or []) if str(a).strip()][:8] if isinstance(lwa.get("aliases"), list) else []
    depth = lwa.get("depth_default") if lwa.get("depth_default") in {"precise", "detailed"} else None
    layout = lwa.get("layout") if lwa.get("layout") in LAYOUTS else None
    return {"id": sid, "name": name, "description": desc[:DESC_MAX], "title": str(lwa.get("title") or name)[:20],
            "aliases": aliases, "domains": [str(d) for d in lwa.get("domains") or []][:6] if isinstance(lwa.get("domains"), list) else [],
            "depth_default": depth, "layout": layout, "body": body}


def _load_dir(base: Path, source: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    found, broken = {}, []
    if not base.is_dir():
        return found, broken
    for sub in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")):
        md = sub / "SKILL.md"
        if not md.is_file():
            continue
        try:
            if md.stat().st_size > IMPORT_MAX_BYTES:
                raise ValueError("SKILL.md 太大（>64KB）")
            skill = parse(md.read_text(encoding="utf-8"), fallback_id=sub.name)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            broken.append({"id": sub.name, "source": source, "path": str(md), "ok": False, "error": str(exc)[:200]})
            continue
        skill.update(source=source, path=str(md), ok=True)
        ex = sub / "examples.txt"
        if ex.is_file():
            try:
                skill["examples"] = [ln.strip() for ln in ex.read_text(encoding="utf-8").splitlines() if ln.strip()][:20]
            except (OSError, UnicodeDecodeError):
                pass
        found[skill["id"]] = skill
    return found, broken


def load_all(*, report: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(能用的技能, 坏的)。用户的同 id 覆盖内置。report=True 时坏的登记 SKIPPED.SKILL（问题面板，不推送）。"""
    builtin, bad1 = _load_dir(BUILTIN_DIR, "builtin")
    try:
        user, bad2 = _load_dir(user_dir(), "user")
    except Exception:  # noqa: BLE001 - vault 读不了 = 只有内置
        user, bad2 = {}, []
    merged = {**builtin, **user}
    for sid, s in user.items():
        if sid in builtin:
            s["overrides"] = "builtin"
    broken = bad1 + bad2
    if report and broken:
        try:
            from . import problems
            for b in broken:
                problems.report("ask", "SKIPPED.SKILL", f"技能「{b['id']}」读不了，已跳过：{b['error']}", action="skipped")
        except Exception:  # noqa: BLE001
            pass
    hidden = hidden_ids()
    for sid in list(merged):
        if sid in hidden and sid != DEFAULT:
            merged[sid]["hidden"] = True
    order = [DEFAULT] + sorted(k for k in merged if k != DEFAULT)
    return [merged[k] for k in order if k in merged], broken


def hidden_ids() -> set[str]:
    """设置页「隐藏」的技能（插件设置 skills.hidden = 技能文件夹名数组）：列表照列（标 hidden），路由时跳过。"""
    try:
        from . import ai_config
        raw = (ai_config.load().get("skills") or {}).get("hidden") or []
        return {str(x).casefold() for x in raw if isinstance(x, str)}
    except Exception:  # noqa: BLE001
        return set()


def list_skills() -> dict[str, Any]:
    """设置页技能列表 / MCP skills(list) 用：不带正文。"""
    ok, broken = load_all()
    rows = [{k: s.get(k) for k in ("id", "name", "title", "description", "aliases", "source", "path", "overrides", "depth_default", "hidden")
             if s.get(k) is not None} | {"ok": True} for s in ok]
    return {"skills": rows + broken, "user_dir": str(user_dir()), "builtin_dir": str(BUILTIN_DIR)}


def get(skill_id: str) -> dict[str, Any] | None:
    ok, _ = load_all()
    key = str(skill_id or "").casefold()
    for s in ok:
        if s["id"] == key or key in {a.casefold() for a in s.get("aliases") or []} or s.get("title", "").casefold() == key:
            return s
    return None


def routing_menu(skills=None) -> list[dict[str, str]]:
    """S1 路由时给模型看的（渐进披露：只给 id + description）。"""
    skills = skills if skills is not None else load_all()[0]
    return [{"id": s["id"], "desc": s["description"][:80]} for s in skills if not s.get("hidden")]


# 1020 陈列版（她：借鉴那份灵感板——分模块、每条配出处帖封面、概要 + 可以借鉴的点、网址、点图打开原帖）。
# 技能 frontmatter 写 `lwa: {layout: board}` 就用：模型照下面的 Markdown 写，页面（chat-view.js renderBoard）解析成陈列卡；
# 解析不出来就照普通 Markdown 显示，所以格式只是约定、不是硬依赖。
LAYOUTS = {"board"}
BOARD_FORMAT = """【陈列格式】这一问的回答会被页面做成陈列卡（每条配出处帖的封面），严格按下面的 Markdown 写，不用表格：
# 报告名（一个名字，不加解释）
> 一句话：这份清单为了什么、从几篇里挑的
## 先看这几个
- **名字** —— 一句为什么先看[来源N]
## 类别名
一句这一类是什么、什么时候用得上（可省）
- **名字** · 网址 —— 帖里：转述作者怎么说它，一两句；借鉴：对她这次用途的具体用处（用在哪、怎么用、别学哪点）[来源N]
## 可补
- 材料覆盖不到的方向，一行一条（没有就省掉这一节）
规则：「先看这几个」3–6 条，名字必须是下面各类里出现过的；类别 3–7 个，类名用她的说法；每个对象一行，名字加粗放行首；
网址只用材料里逐字出现的 http 链接，没有就写「看原帖」；[来源N] 写在行尾，一个对象出自几篇就都标上；
帖里没写的不编，没有可推荐对象的帖不硬塞。"""


def prompt_block(skill: dict[str, Any] | None) -> str:
    """作答阶段的技能说明块（正文截 BODY_MAX）；general / 空 = 不加。layout=board 的再附陈列格式。"""
    if not skill or skill.get("id") == DEFAULT or not skill.get("body"):
        return ""
    body = skill["body"][:BODY_MAX]
    board = ("\n" + BOARD_FORMAT) if skill.get("layout") == "board" else ""
    return (f"\n【技能：{skill.get('title') or skill['id']}】以下是这类问题的写法要求（是格式规则，不是事实来源；"
            f"和收藏内容冲突时以收藏为准，材料里没有的字段写「帖里没提」）：\n{body}{board}\n【技能说明结束】\n")


def import_skill(src: str | Path, *, overwrite: bool = False) -> dict[str, Any]:
    """导入一个用户技能：src = SKILL.md 文件或含 SKILL.md 的文件夹。只拷 SKILL.md（+ examples.txt）两个文本文件，
    别的（脚本、二进制）一律不碰。返回 {status: ok|error, id?, path?, error?, skipped_files?}。"""
    src = Path(src)
    folder = src if src.is_dir() else src.parent
    md = src / "SKILL.md" if src.is_dir() else src
    if not md.is_file():
        return {"status": "error", "error": "没找到 SKILL.md"}
    try:
        if md.stat().st_size > IMPORT_MAX_BYTES:
            return {"status": "error", "error": "SKILL.md 太大（>64KB）"}
        text = md.read_text(encoding="utf-8")
        skill = parse(text, fallback_id=folder.name if src.is_dir() else md.stem)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return {"status": "error", "error": str(exc)[:200]}
    dest = user_dir() / skill["id"]
    if (dest / "SKILL.md").exists() and not overwrite:
        return {"status": "error", "error": f"已有同名技能「{skill['id']}」（要覆盖请勾选覆盖）", "id": skill["id"], "exists": True}
    dest.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_text(dest / "SKILL.md", text)
    copied = ["SKILL.md"]
    ex = folder / "examples.txt" if src.is_dir() else None
    if ex and ex.is_file() and ex.stat().st_size <= IMPORT_MAX_BYTES:
        try:
            storage.atomic_write_text(dest / "examples.txt", ex.read_text(encoding="utf-8"))
            copied.append("examples.txt")
        except (OSError, UnicodeDecodeError):
            pass
    skipped = sorted(p.name for p in folder.iterdir() if p.name not in copied) if src.is_dir() else []
    return {"status": "ok", "id": skill["id"], "path": str(dest / "SKILL.md"), "copied": copied, "skipped_files": skipped}


def choose(understood: dict[str, Any] | None, skills=None) -> dict[str, Any] | None:
    """这一问用哪个技能：她点名的 > 模型选的 > general。找不到 = general（没有 general 文件 = None）。"""
    skills = skills if skills is not None else load_all(report=True)[0]
    by_id = {s["id"]: s for s in skills if not s.get("hidden")}
    want = (understood or {}).get("skill")
    if want and want in by_id:
        return by_id[want]
    return by_id.get(DEFAULT)


def run(args) -> int:
    """`python -m link_brain skills list|show <id>|import <路径> [--overwrite]`（设置页技能页签调这个）。"""
    from .read import EXIT_ERROR, EXIT_OK, dump_json
    action = getattr(args, "action", "list") or "list"
    if action == "list":
        dump_json({"status": "ok", **list_skills()})
        return EXIT_OK
    if action == "show":
        s = get(getattr(args, "target", "") or "")
        dump_json({"status": "ok", "skill": s} if s else {"status": "error", "error": "没有这个技能"})
        return EXIT_OK if s else EXIT_ERROR
    if action == "import":
        res = import_skill(getattr(args, "target", "") or "", overwrite=bool(getattr(args, "overwrite", False)))
        dump_json(res)
        return EXIT_OK if res.get("status") == "ok" else EXIT_ERROR
    dump_json({"status": "error", "error": f"未知动作：{action}"})
    return EXIT_ERROR
