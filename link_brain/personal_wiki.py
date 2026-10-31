"""个人 Wiki（10-29 第一批后端）：用户自己写的知识页，和「问收藏」平级的独立页面背后的存储。

设计见 design-1028-wiki（不进仓）：页面长相以 prototype.design.html 为准、交互以 prototype.html 为准；这里只管数据。

- 一页 = `vault/PersonalWiki/<标题>.md`，正文是**唯一主副本**；文件头只放少量字段（id · title · role · index_tag · order · tags · created · updated）。
  `id` 稳定，改名只换文件名；Obsidian 里直接打开 / 改也照样是普通 Markdown。
- 文件夹（大类）= 一页 `role: topic` + 一个标签（`index_tag`）；页面带几个文件夹标签就出现在几个文件夹里，只维护一份。
  `order` 记在文件夹页上：目录里拖出来的顺序。
- 收藏引用只存 `[标题](lwa:<item_id>)`；`[[页面]]` 照认，但界面不提示（用户不用双链）。
- 历史：每次保存在 `PersonalWiki/.history/<id>/` 留一份整页快照 + `log.json` 一条记录。连着打字 2 分钟内合成一次自动快照；
  手动「保存版本」、恢复、新建、外部编辑各自单独一条。**不用 Git**：发布标准 P8「不需要 Git」。
  Obsidian 里直接改过的（文件和最后一版快照对不上）在下次保存 / 建索引时记一条「外部编辑」，不猜是谁改的。
- 删除 = 挪进 `PersonalWiki/.trash/`，历史留着。
- 索引 `_archive/wiki-index.json` 从正文派生、随时可重建（目录、关系、引用、标题大纲、待办都在里面），页面 / MCP / 问收藏读它。
- 只有这个模块写 PersonalWiki（单 writer），写盘一律 `storage.*` 原子写 + `personal-wiki` 文件锁。

插件消费的 CLI：`python -m link_brain pwiki <list|get|create|save|history|version|restore|delete|index|import|trash|undelete|ai>`，
stdout 最后一行一个 JSON（`read.outcome` 外形），退出码 0 成功 / 1 失败 / 2 参数不对或找不到。
"""
from __future__ import annotations

import difflib
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage
from .errtext import errtext
from .wiki_page import (CITE_RE, DIR_NAME, FENCE_RE, FIELD_ORDER, HEAD_RE, ROLES, TAG_RE, TASK_RE, WL_RE,  # noqa: F401 - 照旧从这里能拿
                        _RESERVED, _clean_tag, _derived_id, _plain, _scalar, _strip_code, _valid_id, content_hash, derive,
                        lead_of, parse_page, scan_dir)

HISTORY_DIR = ".history"
TRASH_DIR = ".trash"
INDEX_NAME = "wiki-index.json"
LOCK_NAME = "personal-wiki"
LOCK_WAIT_S = 15
MERGE_S = 120            # 连着打字：2 分钟内的自动快照合成一条
KEEP_VERSIONS = 200      # 每页最多留几版（最早的「初始 / 新建」那版不删）
SCHEMA = 1
KINDS = ("create", "auto", "manual", "restore", "external", "import", "ai", "rename")

_BAD_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')


class WikiError(Exception):
    """用户操作的可预期失败：code 给插件判断，str 是一句给人看的话。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ── 路径 ──────────────────────────────────────────────────────────────
def wiki_dir(vault: Path | None = None) -> Path:
    return (vault or storage.vault_root()) / DIR_NAME


def index_path(vault: Path | None = None) -> Path:
    return (vault or storage.vault_root()) / storage.ARCHIVE_DIRNAME / INDEX_NAME


def _history_dir(root: Path, page_id: str) -> Path:
    return root / HISTORY_DIR / _safe_id(page_id)


def _safe_id(page_id: str) -> str:
    pid = str(page_id or "").strip()
    if not _valid_id(pid):
        raise WikiError("BAD_ARGS", f"页面 id 不对：{pid or '（空）'}")
    return pid


def new_id() -> str:
    return "pw-" + format(int(time.time() * 1000), "x") + secrets.token_hex(2)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


# ── 文件头 + 正文 ─────────────────────────────────────────────────────
def _yaml_str(s: str) -> str:
    """Obsidian 按 YAML 读文件头：开头是 # [ { 之类、或含 ': ' 的标题要加引号（JSON 字符串就是合法 YAML）。"""
    if not s or re.search(r'^[\s#\[\]{}&*!|>\'"%@`,?:-]|: | #|[\n\r]|\s$', s):
        return json.dumps(s, ensure_ascii=False)
    return s


def render_page(page: dict[str, Any]) -> str:
    lines = ["---", f"id: {page['id']}", f"title: {_yaml_str(page['title'])}", f"role: {page.get('role') or 'page'}"]
    if page.get("index_tag"):
        lines.append(f"index_tag: {_yaml_str(page['index_tag'])}")
    if page.get("order"):
        lines.append("order: " + json.dumps(list(page["order"]), ensure_ascii=False))
    lines.append("tags: " + json.dumps(list(page.get("tags") or []), ensure_ascii=False))
    for k in ("created", "updated"):
        if page.get(k):
            lines.append(f"{k}: {page[k]}")
    lines += list(page.get("extra") or [])
    lines.append("---")
    body = str(page.get("body") or "").replace("\r\n", "\n").strip("\n")
    return "\n".join(lines) + "\n\n" + (body + "\n" if body else "")


def file_name_for(title: str, page_id: str) -> str:
    name = _BAD_NAME.sub("-", title).strip(" .-")[:80].strip(" .-") or page_id
    if _RESERVED.match(name):
        name = "_" + name   # 标题叫 CON / COM1 这类：Windows 上不能当文件名
    return name + ".md"


# ── 扫描 ──────────────────────────────────────────────────────────────
def scan(vault: Path | None = None) -> dict[str, dict[str, Any]]:
    """id → {page, path, hash}。只看 PersonalWiki 顶层的 .md（.history / .trash 不算）；解析在 wiki_page.scan_dir。"""
    return scan_dir(wiki_dir(vault))


def _find(entries: dict[str, dict[str, Any]], page_id: str) -> dict[str, Any]:
    e = entries.get(_safe_id(page_id))
    if not e:
        raise WikiError("NOT_FOUND", "找不到这一页（可能被删了或改名后还没刷新）")
    return e


def _title_taken(entries: dict[str, dict[str, Any]], title: str, except_id: str = "") -> bool:
    t = title.strip().lower()
    return any(pid != except_id and e["page"]["title"].strip().lower() == t for pid, e in entries.items())


def _free_path(root: Path, title: str, page_id: str, current: Path | None = None) -> Path:
    base = file_name_for(title, page_id)
    path = root / base
    n = 2
    while path.exists() and (current is None or path.resolve() != current.resolve()):
        path = root / f"{base[:-3]} ({n}).md"
        n += 1
    return path


# ── 历史 ──────────────────────────────────────────────────────────────
def _load_log(root: Path, page_id: str) -> list[dict[str, Any]]:
    try:
        data = storage.read_json(_history_dir(root, page_id) / "log.json")
    except (OSError, ValueError):
        return []
    return [v for v in (data.get("versions") if isinstance(data, dict) else data) or [] if isinstance(v, dict)]


def _save_log(root: Path, page_id: str, versions: list[dict[str, Any]]) -> None:
    storage.write_json(_history_dir(root, page_id) / "log.json", {"schema": SCHEMA, "id": page_id, "versions": versions})


def _snapshot(root: Path, page_id: str, text: str, kind: str, note: str = "") -> dict[str, Any]:
    """记一版。kind=auto 且上一版也是 auto、在 MERGE_S 内：覆盖上一版（连着打字合成一条）。返回这一版的记录。"""
    hdir = _history_dir(root, page_id)
    versions = _load_log(root, page_id)
    h = content_hash(text)
    now = time.time()
    last = versions[-1] if versions else None
    if last and last.get("hash") == h and kind in ("auto", "external"):
        return last
    if last and kind == "auto" and last.get("kind") == "auto" and now - float(last.get("ts") or 0) < MERGE_S:
        storage.atomic_write_text(hdir / last["file"], text)
        last.update(ts=now, at=_now(), hash=h)
        _save_log(root, page_id, versions)
        return last
    rec = {"ver": (int(last["ver"]) + 1) if last else 1, "file": f"{_stamp()}-{kind}.md", "ts": now, "at": _now(),
           "kind": kind, "note": str(note or "")[:200], "hash": h}
    storage.atomic_write_text(hdir / rec["file"], text)
    versions.append(rec)
    if len(versions) > KEEP_VERSIONS:   # 留第一版 + 最近的
        drop = versions[1:len(versions) - KEEP_VERSIONS + 1]
        versions = versions[:1] + versions[len(versions) - KEEP_VERSIONS + 1:]
        for d in drop:
            try:
                (hdir / d["file"]).unlink()
            except OSError:
                pass
    _save_log(root, page_id, versions)
    return rec


def _catch_external(root: Path, entry: dict[str, Any]) -> None:
    """文件和最后一版快照对不上 = 在 Obsidian 里（或别处）直接改过：先记一条「外部编辑」，后面的保存才有对照。"""
    versions = _load_log(root, entry["page"]["id"])
    text = entry["path"].read_text(encoding="utf-8")   # 现读：比对和记下来的是同一份
    if versions and versions[-1].get("hash") == content_hash(text):
        return
    _snapshot(root, entry["page"]["id"], text, "external" if versions else "import",
              "在别处改过（Obsidian 等）" if versions else "第一次收进历史")


def _diff_count(a: str, b: str) -> tuple[int, int]:
    add = rem = 0
    for line in difflib.ndiff(a.split("\n"), b.split("\n")):
        if line.startswith("+ "):
            add += 1
        elif line.startswith("- "):
            rem += 1
    return add, rem


# ── 读 ────────────────────────────────────────────────────────────────
def _public(entry: dict[str, Any], *, body: bool = True) -> dict[str, Any]:
    p = dict(entry["page"])
    p.pop("extra", None)
    if not body:
        p.pop("body", None)
    p["file"] = entry["path"].name
    p["hash"] = entry["hash"]
    return p


def list_pages(vault: Path | None = None) -> list[dict[str, Any]]:
    return [_public(e, body=False) for e in scan(vault).values()]


def get_page(page_id: str, vault: Path | None = None) -> dict[str, Any]:
    return _public(_find(scan(vault), page_id))


# ── 写（全部在锁里） ──────────────────────────────────────────────────
def _ensure_fresh(root: Path, entry: dict[str, Any]) -> None:
    """写盘前再读一次磁盘：文件锁管不住 Obsidian，扫描之后它可能刚改过这页。改过就先把它那版记进历史、拒绝覆盖。"""
    try:
        text = entry["path"].read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WikiError("CONFLICT", "这页刚被挪走或删了，先重新打开") from exc
    if content_hash(text) != entry["hash"]:
        if entry["page"].get("adopted") is not False:
            _snapshot(root, entry["page"]["id"], text, "external", "在别处改过（Obsidian 等）")
        raise WikiError("CONFLICT", "这页刚在别处改过（Obsidian 里），先重新打开再改")


def _write(root: Path, entry_or_none: dict[str, Any] | None, page: dict[str, Any], kind: str, note: str) -> dict[str, Any]:
    text = render_page(page)
    old_path = entry_or_none["path"] if entry_or_none else None
    if entry_or_none:
        _ensure_fresh(root, entry_or_none)
    path = _free_path(root, page["title"], page["id"], current=old_path)
    if old_path and old_path.resolve() != path.resolve():
        # 改名：先把文件整个挪到新名字（一步，不会出现两份同 id 的文件），再写新内容。
        # 挪不动（Obsidian / 同步盘占着）就什么都没变，如实报失败。
        for attempt in range(5):
            try:
                os.replace(old_path, path)
                break
            except FileNotFoundError as exc:
                raise WikiError("CONFLICT", "这页刚被挪走或删了，先重新打开") from exc
            except OSError as exc:
                if attempt == 4:
                    raise WikiError("WRITE_FAILED", f"改名没成功（文件被占用），内容还在，可重试：{errtext(exc)}") from exc
                time.sleep(0.1 * (attempt + 1))
    storage.atomic_write_text(path, text)
    ver = _snapshot(root, page["id"], text, kind, note)
    return {"page": page, "path": path, "hash": content_hash(text), "version": ver}


def create_page(title: str, *, role: str = "page", folder: str = "", tags: list[str] | None = None, body: str = "",
                prompts: bool = False, page_id: str = "", vault: Path | None = None) -> dict[str, Any]:
    """新建一页。role=topic = 新文件夹（index_tag 默认用标题）。folder = 放进哪个文件夹（那个文件夹的 index_tag）。"""
    title = str(title or "").strip()
    if not title:
        raise WikiError("BAD_ARGS", "标题不能是空的")
    if role not in ROLES:
        raise WikiError("BAD_ARGS", f"不认识的页面类型：{role}")
    root = wiki_dir(vault)
    with storage.file_lock(LOCK_NAME, wait_s=LOCK_WAIT_S):
        entries = scan(vault)
        if _title_taken(entries, title):
            raise WikiError("TITLE_TAKEN", f"已经有一页叫「{title}」了")
        pid = _safe_id(page_id) if page_id else new_id()
        if pid in entries:
            raise WikiError("TITLE_TAKEN", f"页面 id 已存在：{pid}")
        all_tags = [t for t in (_clean_tag(x) for x in (tags or [])) if t]
        index_tag = ""
        if role == "topic":
            index_tag = _clean_tag(title) or pid
            all_tags = [index_tag] + [t for t in all_tags if t != index_tag]
        elif folder:
            f = _clean_tag(folder)
            if f and f not in all_tags:
                all_tags.insert(0, f)
        if prompts and not body:
            body = "为什么关注：\n\n## 当前理解\n\n## 当前判断与选择\n\n## 想继续弄明白的事\n- [ ] \n\n## 值得参考的内容\n"
        now = _now()
        page = {"id": pid, "title": title, "role": role, "index_tag": index_tag, "order": [], "tags": all_tags,
                "created": now, "updated": now, "body": body, "extra": []}
        res = _write(root, None, page, "create", "新建")
        if role == "page" and folder:
            _append_order(root, scan(vault), _clean_tag(folder), pid)
    return _result(res)


def _append_order(root: Path, entries: dict[str, dict[str, Any]], tag: str, pid: str) -> None:
    """10-31：新页排到文件夹顺序末尾（以前不进 order，按修改时间排在已排好的后面，改一下内容就换位置）。
    文件夹页正在 Obsidian 里改着（对不上）就算了，页面照样建好。"""
    for e in entries.values():
        fp = e["page"]
        if fp.get("role") != "topic" or fp.get("index_tag") != tag or pid in (fp.get("order") or []):
            continue
        try:
            page = dict(fp)
            page.pop("adopted", None)
            page["order"] = [*(fp.get("order") or []), pid]
            _write(root, e, page, "auto", "新页排进来")
        except (WikiError, OSError):
            pass
        return


def save_page(page_id: str, *, title: str | None = None, tags: list[str] | None = None, body: str | None = None,
              order: list[str] | None = None, base_hash: str = "", kind: str = "auto", note: str = "",
              vault: Path | None = None) -> dict[str, Any]:
    """改一页（只改传了的字段）。base_hash = 页面打开 / 上次保存时拿到的 hash：和磁盘对不上 = 期间别处改过，拒绝覆盖（CONFLICT）。"""
    if kind not in KINDS:
        raise WikiError("BAD_ARGS", f"不认识的保存类型：{kind}")
    for name, val in (("title", title), ("body", body), ("note", note), ("base_hash", base_hash)):
        if val is not None and not isinstance(val, str):
            raise WikiError("BAD_ARGS", f"{name} 要是一段文字")
    for name, val in (("tags", tags), ("order", order)):   # "travel" 当成列表会被拆成单个字
        if val is not None and not (isinstance(val, list) and all(isinstance(x, str) for x in val)):
            raise WikiError("BAD_ARGS", f"{name} 要是一组文字（列表）")
    root = wiki_dir(vault)
    with storage.file_lock(LOCK_NAME, wait_s=LOCK_WAIT_S):
        entries = scan(vault)
        entry = _find(entries, page_id)
        if base_hash and base_hash != entry["hash"]:
            raise WikiError("CONFLICT", "这页在别处改过了（另一个窗口或 Obsidian 里），先重新打开再改")
        _catch_external(root, entry)
        adopting = entry["page"].get("adopted") is False   # Obsidian 里新建、文件里还没写 id：这次一定要写进去
        page = dict(entry["page"])
        page.pop("adopted", None)
        if title is not None:
            t = str(title).strip()
            if not t:
                raise WikiError("BAD_ARGS", "标题不能是空的")
            if _title_taken(entries, t, except_id=page["id"]):
                raise WikiError("TITLE_TAKEN", f"已经有一页叫「{t}」了")
            page["title"] = t
        if tags is not None:
            page["tags"] = list(dict.fromkeys(t for t in (_clean_tag(x) for x in tags) if t))
            if page["role"] == "topic" and page["index_tag"] and page["index_tag"] not in page["tags"]:
                page["tags"].insert(0, page["index_tag"])
        if body is not None:
            page["body"] = str(body)
        if order is not None:
            page["order"] = [str(x) for x in order if _valid_id(str(x))]
        page["created"] = page.get("created") or _now()
        new_text = render_page({**page, "updated": entry["page"].get("updated")})
        if content_hash(new_text) == content_hash(render_page(entry["page"])) and kind == "auto" and not adopting:
            return _result({"page": page, "path": entry["path"], "hash": entry["hash"], "version": None}, changed=False)
        page["updated"] = _now()
        res = _write(root, entry, page, kind, note)
    return _result(res)


def history(page_id: str, vault: Path | None = None) -> list[dict[str, Any]]:
    """版本列表，新→旧：{ver, at, kind, note, add, del}。"""
    root = wiki_dir(vault)
    pid = _safe_id(page_id)
    versions = _load_log(root, pid)
    hdir = _history_dir(root, pid)
    out, prev = [], None
    for v in versions:
        try:
            body = parse_page((hdir / v["file"]).read_text(encoding="utf-8"))["body"]
        except OSError:
            body = None
        add, rem = _diff_count(prev, body) if (prev is not None and body is not None) else (0, 0)
        out.append({k: v.get(k) for k in ("ver", "at", "kind", "note")} | {"add": add, "del": rem, "missing": body is None})
        if body is not None:
            prev = body
    return out[::-1]


def version_text(page_id: str, ver: int, vault: Path | None = None) -> dict[str, Any]:
    root = wiki_dir(vault)
    pid = _safe_id(page_id)
    for v in _load_log(root, pid):
        if int(v.get("ver") or 0) == int(ver):
            try:
                text = (_history_dir(root, pid) / v["file"]).read_text(encoding="utf-8")
            except OSError as exc:
                raise WikiError("NOT_FOUND", f"这一版的文件读不到：{errtext(exc)}") from exc
            p = parse_page(text)
            return {"ver": v["ver"], "at": v.get("at"), "kind": v.get("kind"), "title": p["title"], "tags": p["tags"], "body": p["body"]}
    raise WikiError("NOT_FOUND", f"没有第 {ver} 版")


def restore(page_id: str, ver: int, *, base_hash: str = "", vault: Path | None = None) -> dict[str, Any]:
    """恢复到某一版 = 用那一版的标题 / 标签 / 正文再存一版（kind=restore），之后的历史都还在。"""
    v = version_text(page_id, ver, vault)
    return save_page(page_id, title=v["title"], tags=v["tags"], body=v["body"], base_hash=base_hash,
                     kind="restore", note=f"恢复到第 {v['ver']} 版（{v.get('at') or ''}）", vault=vault)


def delete_page(page_id: str, *, base_hash: str = "", vault: Path | None = None) -> dict[str, Any]:
    """挪进 .trash（历史留着），不是彻底删除。"""
    root = wiki_dir(vault)
    with storage.file_lock(LOCK_NAME, wait_s=LOCK_WAIT_S):
        entry = _find(scan(vault), page_id)
        if base_hash and base_hash != entry["hash"]:
            raise WikiError("CONFLICT", "这页在别处改过了，先重新打开再删")
        _ensure_fresh(root, entry)
        text = entry["path"].read_text(encoding="utf-8")
        _catch_external(root, entry)
        dest = root / TRASH_DIR / f"{_stamp()}-{entry['path'].name}"
        storage.atomic_write_text(dest, text)
        entry["path"].unlink()
    return {"id": entry["page"]["id"], "title": entry["page"]["title"], "trashed": dest.name}


def list_trash(vault: Path | None = None) -> list[dict[str, Any]]:
    """删掉的页（.trash 里），新→旧：{name, id, title, at}。Obsidian 不显示点开头的文件夹，所以页面上要能列出来。"""
    tdir = wiki_dir(vault) / TRASH_DIR
    out = []
    for f in sorted(tdir.glob("*.md"), reverse=True) if tdir.is_dir() else []:
        try:
            p = parse_page(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        m = re.match(r"^(\d{8})-(\d{6})", f.name)
        at = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}T{m.group(2)[:2]}:{m.group(2)[2:4]}" if m else ""
        out.append({"name": f.name, "id": p.get("id") or "", "title": p.get("title") or f.stem, "at": at})
    return out


def undelete(name: str, vault: Path | None = None) -> dict[str, Any]:
    """把 .trash 里的一页放回来（同 id 已经有了就换个新 id；同名就在标题后加「（找回）」），记一版「恢复」。"""
    root = wiki_dir(vault)
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise WikiError("BAD_ARGS", "要找回哪一页？")
    src = root / TRASH_DIR / name
    with storage.file_lock(LOCK_NAME, wait_s=LOCK_WAIT_S):
        try:
            text = src.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WikiError("NOT_FOUND", "删除记录里没有这一页了") from exc
        entries = scan(vault)
        p = parse_page(text)
        pid = p.get("id") if _valid_id(str(p.get("id") or "")) and p.get("id") not in entries else new_id()
        title = str(p.get("title") or src.stem).strip()
        if _title_taken(entries, title):
            title = f"{title}（找回）"
        page = {**p, "id": pid, "title": title, "role": p.get("role") if p.get("role") in ROLES else "page"}
        page.setdefault("order", []); page.setdefault("tags", []); page.setdefault("extra", [])
        page.pop("adopted", None)
        page["updated"] = _now()
        page["created"] = page.get("created") or page["updated"]
        res = _write(root, None, page, "restore", "从删除里找回")
        src.unlink()
    return _result(res)


def _result(res: dict[str, Any], *, changed: bool = True) -> dict[str, Any]:
    page = dict(res["page"])
    page.pop("extra", None)
    page["file"] = res["path"].name
    page["hash"] = res["hash"]
    v = res.get("version")
    return {"page": page, "changed": changed, "version": ({k: v.get(k) for k in ("ver", "at", "kind", "note")} if v else None)}


# ── 索引（从正文派生；页面 / MCP / 问收藏读它；派生函数在 wiki_page） ──
def build_index(vault: Path | None = None, *, record_external: bool = True) -> dict[str, Any]:
    """重建 `_archive/wiki-index.json`。record_external：顺手给在 Obsidian 里直接改过的页补一条「外部编辑」历史。"""
    root = wiki_dir(vault)
    # 整个重建都在锁里：读页面和写索引之间不能插进别的保存，否则先起的重建会把更新的索引盖回去
    with storage.file_lock(LOCK_NAME, wait_s=LOCK_WAIT_S):
        entries = scan(vault)
        failed = []
        if record_external:
            for e in entries.values():
                if e["page"].get("adopted") is False:
                    continue   # 没有 id 的页先不建历史：等用户第一次在 Wiki 里保存、写上 id
                try:
                    _catch_external(root, e)
                except OSError as exc:   # 索引照建，但没记上的历史要如实报出去（CONVENTIONS §1）
                    failed.append({"id": e["page"]["id"], "title": e["page"]["title"], "error": errtext(exc)})
        data = _index_data(entries)
        storage.write_json(index_path(vault), data)
    data["history_failed"] = failed
    return data


def _index_data(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pages = []
    for e in entries.values():
        p = _public(e, body=False)
        p.update(derive(e["page"]))
        pages.append(p)
    folders = [p for p in pages if p["role"] == "topic" and p["index_tag"]]
    folder_tags = {f["index_tag"] for f in folders}
    by_tag: dict[str, list[str]] = {}
    for p in pages:
        for t in p["all_tags"]:
            by_tag.setdefault(t, []).append(p["id"])
    by_cite: dict[str, list[str]] = {}
    for p in pages:
        for c in p["cites"]:
            by_cite.setdefault(c, []).append(p["id"])
    tree = []
    for f in folders:   # 文件夹里的顺序：order 里拖好的在前，其余按更新时间新→旧
        members = [p for p in pages if p["role"] == "page" and f["index_tag"] in p["all_tags"]]
        rank = {pid: i for i, pid in enumerate(f.get("order") or [])}
        members.sort(key=lambda p: p.get("updated") or "", reverse=True)
        members.sort(key=lambda p: rank.get(p["id"], 10 ** 6))
        tree.append({"id": f["id"], "title": f["title"], "index_tag": f["index_tag"], "pages": [p["id"] for p in members]})
    loose = [p["id"] for p in pages if p["role"] == "page" and not (set(p["all_tags"]) & folder_tags)]
    return {"schema": SCHEMA, "built_at": _now(), "dir": DIR_NAME, "pages": pages, "folders": tree, "loose": loose,
            "tags": by_tag, "cites": by_cite}


# ── 导入（把原型 / 别处的页搬进来；已有同 id 的跳过） ──────────────────
def load_import_file(path: Path) -> list[str]:
    """读 JSON（{pages:[...]} 或 [...]）或原型的 wiki-data.local.js（`window.LWA_WIKI_LOCAL = {...};`）。每页是一整份 md 文本。"""
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r"=\s*(\{[\s\S]*\})\s*;?\s*$", text)
    try:   # 只当 JSON 解析，不执行 .js
        data = json.loads(m.group(1) if (m and not text.lstrip().startswith(("{", "["))) else text)
    except ValueError as exc:
        raise WikiError("BAD_ARGS", f"导入文件读不懂（要 JSON 或原型的 wiki-data.local.js）：{errtext(exc)}") from exc
    pages = data.get("pages") if isinstance(data, dict) else data
    if not isinstance(pages, list) or not all(isinstance(p, str) for p in pages):
        raise WikiError("BAD_ARGS", "导入文件里没有页面列表（要 {pages: [md 文本, …]}）")
    return pages


def import_pages(texts: list[str], *, vault: Path | None = None) -> list[dict[str, Any]]:
    root = wiki_dir(vault)
    results = []
    with storage.file_lock(LOCK_NAME, wait_s=LOCK_WAIT_S):
        entries = scan(vault)
        for text in texts:
            try:
                page = parse_page(text)
                pid = page["id"] if _valid_id(page["id"]) else new_id()
                title = page["title"] or pid
                if pid in entries:
                    results.append({"id": pid, "title": title, "status": "skipped", "code": "EXISTS", "error": "已经有这一页"})
                    continue
                if _title_taken(entries, title):
                    results.append({"id": pid, "title": title, "status": "skipped", "code": "TITLE_TAKEN", "error": "已经有同名的页"})
                    continue
                now = _now()
                page.update(id=pid, title=title, created=page.get("created") or now, updated=page.get("updated") or now)
                page.pop("adopted", None)
                res = _write(root, None, page, "import", "导入")
                entries[pid] = {"page": page, "path": res["path"], "hash": res["hash"]}
                results.append({"id": pid, "title": title, "status": "ok", "code": "", "error": ""})
            except Exception as exc:  # noqa: BLE001 - 逐条 try（CONVENTIONS §1.3）
                results.append({"id": "", "title": "", "status": "failed", "code": "WRITE_FAILED", "error": errtext(exc)})
    return results


# ── CLI ───────────────────────────────────────────────────────────────
def add_parser(sub) -> None:
    p = sub.add_parser("pwiki", help="个人 Wiki（PersonalWiki/）：列 / 读 / 新建 / 保存 / 历史 / 恢复 / 删除 / 建索引 / 导入（输出 JSON）")
    ws = p.add_subparsers(dest="pwiki_command")
    ws.add_parser("list", help="列出所有页（不带正文）")
    g = ws.add_parser("get", help="读一页（带正文和 hash）")
    g.add_argument("id")
    c = ws.add_parser("create", help="新建一页 / 文件夹")
    c.add_argument("title")
    c.add_argument("--folder", default="", help="放进哪个文件夹（文件夹的标签）")
    c.add_argument("--topic", action="store_true", help="这一页本身是个文件夹（大类）")
    c.add_argument("--prompts", action="store_true", help="放几个可删的写作提示")
    s = ws.add_parser("save", help="保存一页：stdin 一个 JSON {id, base_hash?, title?, tags?, body?, order?, kind?, note?}")
    s.add_argument("--input", default="-", help="JSON 文件路径，默认 stdin")
    h = ws.add_parser("history", help="一页的版本列表（新→旧）")
    h.add_argument("id")
    v = ws.add_parser("version", help="读某一版的全文")
    v.add_argument("id")
    v.add_argument("ver", type=int)
    r = ws.add_parser("restore", help="恢复到某一版（会记成新的一版）")
    r.add_argument("id")
    r.add_argument("ver", type=int)
    r.add_argument("--base-hash", default="")
    d = ws.add_parser("delete", help="删一页（挪进 PersonalWiki/.trash，历史留着）")
    d.add_argument("id")
    d.add_argument("--base-hash", default="")
    ws.add_parser("index", help="重建 _archive/wiki-index.json（顺手给 Obsidian 里改过的页记一条外部编辑）")
    im = ws.add_parser("import", help="导入页面：JSON 或原型的 wiki-data.local.js；已有同 id / 同名的跳过")
    im.add_argument("file")
    ws.add_parser("trash", help="列出删掉的页（PersonalWiki/.trash）")
    u = ws.add_parser("undelete", help="把删掉的一页放回来")
    u.add_argument("name", help="trash 列出的 name")
    a = ws.add_parser("ai", help="让文本 AI 改一段 / 整页：stdin 一个 JSON {id, scope:block|page, text, instruction, preset?}；只回建议，不写盘")
    a.add_argument("--input", default="-", help="JSON 文件路径，默认 stdin")


def _read_input(arg: str) -> dict[str, Any]:
    raw = sys.stdin.buffer.read().decode("utf-8") if arg == "-" else Path(arg).read_text(encoding="utf-8")
    try:
        data = json.loads(raw or "{}")
    except ValueError as exc:   # 插件给的 JSON 不对 = 参数问题（退出 2），不是写盘失败
        raise WikiError("BAD_ARGS", f"保存的内容不是合法 JSON：{errtext(exc)}") from exc
    if not isinstance(data, dict):
        raise WikiError("BAD_ARGS", "保存要的是一个 JSON 对象")
    return data


def dump_json(payload: Any) -> None:
    """同 read.dump_json（不 import read：它连带载小红书 adapter / httpx，pwiki 每次多花 1 秒多）。"""
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(line)
        return
    sys.stdout.flush()
    buffer.write(line.encode("utf-8"))
    buffer.flush()


def outcome(payload: dict[str, Any] | None, *, ok: bool, message: str, code: str | None = None) -> dict[str, Any]:
    """同 read.outcome（CONVENTIONS §1 外形）。"""
    base = dict(payload or {})
    existing = base.get("code")
    base["ok"] = bool(ok)
    base["code"] = str(code) if code is not None else (str(existing) if existing not in (None, "") else "")
    base["message"] = str(message or "")
    return base


def main_fast(argv: list[str]) -> int:
    """`python -m link_brain pwiki …` 的轻入口（__main__ 直接调，不经 cli.main）：只载这个模块，起一次 0.3 秒左右，
    以前整套 cli 要 1.5 秒，每次保存这一页就锁 1.5 秒（10-31 走查）。没想到的异常照样回一行 JSON。"""
    import argparse
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="python -m link_brain")
    add_parser(ap.add_subparsers(dest="command"))
    args = ap.parse_args(["pwiki", *argv])
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - 最后一道兜底：插件要的是一行 JSON，不是 traceback
        msg = f"Wiki 后端出错了：{errtext(exc)}"
        dump_json(outcome({}, ok=False, code="TRANSIENT.STEP_CRASHED", message=msg))
        print(msg, file=sys.stderr)
        return 1


def run(args) -> int:
    cmd = getattr(args, "pwiki_command", None) or "list"
    try:
        if cmd == "list":
            pages = list_pages()
            dump_json(outcome({"pages": pages}, ok=True, message=f"共 {len(pages)} 页"))
        elif cmd == "get":
            page = get_page(args.id)
            dump_json(outcome({"page": page}, ok=True, message=f"《{page['title']}》"))
        elif cmd == "create":
            res = create_page(args.title, role="topic" if args.topic else "page", folder=args.folder, prompts=args.prompts)
            dump_json(outcome(res, ok=True, message=f"已新建《{res['page']['title']}》"))
        elif cmd == "save":
            data = _read_input(args.input)
            res = save_page(str(data.get("id") or ""), title=data.get("title"), tags=data.get("tags"), body=data.get("body"),
                            order=data.get("order"), base_hash=str(data.get("base_hash") or ""),
                            kind=str(data.get("kind") or "auto"), note=str(data.get("note") or ""))
            dump_json(outcome(res, ok=True, message="已保存" if res["changed"] else "没有改动"))
        elif cmd == "history":
            vers = history(args.id)
            dump_json(outcome({"id": args.id, "versions": vers}, ok=True, message=f"{len(vers)} 个版本"))
        elif cmd == "version":
            v = version_text(args.id, args.ver)
            dump_json(outcome({"version": v}, ok=True, message=f"第 {v['ver']} 版"))
        elif cmd == "restore":
            res = restore(args.id, args.ver, base_hash=args.base_hash)
            dump_json(outcome(res, ok=True, message="已恢复；恢复前的内容也在历史里"))
        elif cmd == "delete":
            res = delete_page(args.id, base_hash=args.base_hash)
            dump_json(outcome(res, ok=True, message=f"已删《{res['title']}》（在 PersonalWiki/.trash 里，可找回）"))
        elif cmd == "index":
            data = build_index()
            failed = data["history_failed"]
            msg = f"索引已更新：{len(data['pages'])} 页"
            if failed:
                msg += f"；{len(failed)} 页在别处改过的内容没记进历史：{failed[0]['error']}"
            dump_json(outcome({"pages": len(data["pages"]), "folders": len(data["folders"]), "path": INDEX_NAME,
                               "history_failed": failed}, ok=not failed, message=msg, code="WRITE_FAILED" if failed else ""))
            if failed:
                print(msg, file=sys.stderr)
                return 1
        elif cmd == "import":
            results = import_pages(load_import_file(Path(args.file)))
            ok_n = sum(1 for r in results if r["status"] == "ok")
            failed = [r for r in results if r["status"] == "failed"]
            try:
                build_index()
            except Exception as exc:  # noqa: BLE001 - 导入已经写好，索引下次再建
                print(f"索引没建上：{errtext(exc)}", file=sys.stderr)
            dump_json(outcome({"results": results}, ok=not failed,
                              message=f"导入 {ok_n} 页，跳过 {sum(1 for r in results if r['status'] == 'skipped')} 页"
                              + (f"，{len(failed)} 页失败" if failed else ""), code="WRITE_FAILED" if failed else ""))
            return 1 if failed else 0
        elif cmd == "trash":
            rows = list_trash()
            dump_json(outcome({"pages": rows}, ok=True, message=f"删掉的页 {len(rows)} 个"))
        elif cmd == "undelete":
            res = undelete(args.name)
            dump_json(outcome(res, ok=True, message=f"已找回《{res['page']['title']}》"))
        elif cmd == "ai":   # 由 wiki_ai.main 接（__main__ 直接转过去）：这里不 import wiki_ai，免得把本模块卷进大 import 环
            raise WikiError("BAD_ARGS", "「pwiki ai」请用 python -m link_brain pwiki ai")
        else:
            raise WikiError("BAD_ARGS", f"不认识的子命令：{cmd}")
        return 0
    except WikiError as exc:
        dump_json(outcome({}, ok=False, code=exc.code, message=str(exc)))
        print(str(exc), file=sys.stderr)
        return 2 if exc.code in ("BAD_ARGS", "NOT_FOUND") else 1
    except storage.LockBusy as exc:
        dump_json(outcome({}, ok=False, code="LOCK_BUSY", message="Wiki 正在保存别的改动，稍后再试"))
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        msg = f"没保存上，内容还在，可重试：{errtext(exc)}"
        dump_json(outcome({}, ok=False, code="WRITE_FAILED", message=msg))
        print(msg, file=sys.stderr)
        return 1
