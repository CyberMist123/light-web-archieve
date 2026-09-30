"""`catch` 子命令：主模型的入口。

给它一整条聊天消息原文，它自己找里面的小红书链接、归档（命中索引就是 HIT，不联网）、
**只往 stdout 打一个 JSON**，让调用方一眼判断要不要展开：

    {"found": 1, "items": [{"item_id": "...", "status": "new", ...}]}

消息里没有小红书链接就是 `{"found": 0, "items": []}`，零成本。
JSON 结构见 `docs/FORMAT.md` §10。

硬约束 8：这里**不起 HTTP 服务、不起 MCP 服务**。TG / CMX 端就是 Bash 直调这个 CLI。
所以 stdout 只许有那一个 JSON —— 过程日志（报警、附件排队、歇几秒）一律走 stderr（lwa 依赖这一点）。

1001 护号：
- 只有真要联网抓的链接（不在库里 / --refresh）才去拿账号锁；`--wait-lock-min`（默认 2）内拿不到
  → 这些链接记 busy、退出码 6（「正在同步收藏，稍后再收」）。HIT 的照常秒回。
- 抓取阶段（用号）只做：抓原文 + 本地渲染 + 附件；放掉账号锁之后，识图（和 `--extract` 的概要）
  交给 enrich，每篇一个子进程、20 分钟上限（审计 xc-2：以前在主进程里不限时跑，一卡住插件按钮全锁死）。
"""

from __future__ import annotations

import contextlib
import sys
from typing import Any
from urllib.parse import urlsplit

from . import accounts, alert as alert_mod, ingest as ingest_mod, read as read_mod, storage
from .adapters import xiaohongshu as xhs

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_HUMAN = 5
EXIT_ACCOUNT_BUSY = 6
BUSY_MESSAGE = "正在同步收藏，稍后再收"

# 只认小红书；消息里的其它链接一律不碰（V1 没有别的 adapter）。
# rednote.com 是小红书海外域，分享链接大多是它（/discovery/item/<id>），必须认。
XHS_HOSTS = ("xiaohongshu.com", "rednote.com", "xhslink.cn", "xhslink.com")
# URL_RE 已经排掉了大部分中文标点，这里再收一遍粘在链接尾巴上的收尾符号
TRAILING = "，。、；：！？）)]】》>\"'“”‘’"


def _is_xhs(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in XHS_HOSTS)


def find_xhs_urls(message: str) -> list[str]:
    """从任意消息全文里抠出小红书链接，按出现顺序去重。"""
    found: list[str] = []
    for match in xhs.URL_RE.finditer(message or ""):
        url = match.group(0).rstrip(TRAILING)
        if _is_xhs(url) and url not in found:
            found.append(url)
    return found


def _ensure_rendered(
    source_key: str, source_id: str, *, force: bool, extract: bool
) -> None:
    """保证可见 md / agent.md 在盘上（手动补抓评论等老入口用；会在本进程里跑识图）。

    HIT 且文件都在 → 什么都不做（vision 会 spawn 子进程，白花钱）。
    新归档、或者可见 md 不见了（被删/改名）→ 补渲染一次。
    `verbose` 永远传 False：`render_item` 的 verbose 打的是 stdout，会污染 JSON。
    """
    meta_path = storage.object_dir(source_key, source_id) / "meta.json"
    rel = storage.read_json(meta_path).get("visible_note") if meta_path.exists() else None
    have = bool(rel) and (storage.vault_root() / rel).exists()
    if not (force or extract or not have):
        return
    from . import render as render_mod

    render_mod.render_item(source_key, source_id, verbose=False, llm=extract)


class _LazyLock:
    """第一次真要联网时才拿账号锁；拿不到记住，后面的链接不再重复等。"""

    def __init__(self, stack: contextlib.ExitStack, owner: str, wait_s: float):
        self.stack, self.owner, self.wait_s = stack, owner, wait_s
        self.held = False
        self.busy: accounts.AccountBusyError | None = None

    def ensure(self) -> None:
        if self.held:
            return
        if self.busy is not None:
            raise self.busy
        try:
            self.stack.enter_context(accounts.account_session(self.owner, wait_s=self.wait_s))
        except accounts.AccountBusyError as exc:
            self.busy = exc
            raise
        self.held = True


def _needs_fetch(parsed: dict[str, Any]) -> bool:
    """不在库里、也不在回收站里 = 要联网抓。"""
    from . import index as index_mod
    conn = index_mod.connect()
    try:
        if index_mod.find_object(conn, xhs.SOURCE, parsed["note_id"]) is not None:
            return False
        return conn.execute("SELECT 1 FROM tombstones WHERE source = ? AND source_id = ?",
                            (xhs.SOURCE, parsed["note_id"])).fetchone() is None
    finally:
        conn.close()


def _catch_one(
    url: str, *, message: str, origin: str, actor: str, verbose: bool, lock: _LazyLock | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """抓取阶段的一条链接。返回条目 dict；新抓的带内部键 `_source_id`（之后补识图用）。"""
    from . import enrich as enrich_mod, render as render_mod

    try:
        parsed = xhs.parse_input(url)
        if lock is not None and (refresh or _needs_fetch(parsed)):
            lock.ensure()
        summary = ingest_mod.ingest_url(
            url,
            origin=origin,
            actor=actor,
            ingest_kind="shared",
            note=message,
            verbose=verbose,
            refresh=refresh,
            parsed=parsed,
        )
    except accounts.AccountBusyError as exc:
        return {"item_id": None, "status": "busy", "url": url, "error": f"{BUSY_MESSAGE}（{exc}）",
                "code": "ACCOUNT_BUSY"}
    except xhs.NeedsHumanError as exc:
        # 号出事 / 服务出事，不是这条链接的问题：报警 + 让上层停车，别把剩下的全刷成失败
        service = isinstance(exc, xhs.ServiceDownError)
        alert_mod.alert(
            alert_mod.KIND_SERVICE if service else alert_mod.KIND_ACCOUNT,
            "小红书归档停了：" + ("读取服务要处理" if service else "账号要处理"),
            str(exc),
            url=url,
        )
        return {"item_id": None, "status": "blocked", "url": url, "error": str(exc),
                "code": getattr(exc, "code", "") or ""}
    except Exception as exc:  # noqa: BLE001 - 一条链接抓挂了不该带走整条消息
        return {
            "item_id": None,
            "status": "error",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if summary.get('status') == 'trashed':
        return {**summary, 'url': url}
    fresh = not (summary.get("hit") or summary.get("refreshed_unchanged"))
    status = "new" if fresh else "hit"
    source_key, source_id = xhs.SOURCE, summary["note_id"]

    render_error = None
    try:
        if fresh:
            enrich_mod.mark_pending(source_key, source_id, reason="导入")
        # 本地渲染（不调模型、不识图）；HIT 只在可见 md 丢了时补一份
        meta_path = storage.object_dir(source_key, source_id) / "meta.json"
        rel = storage.read_json(meta_path).get("visible_note") if meta_path.exists() else None
        if fresh or not (rel and (storage.vault_root() / rel).exists()):
            render_mod.render_object(source_key, source_id, verbose=False, llm=False)
    except Exception as exc:  # noqa: BLE001 - 渲染失败不该吞掉已经落盘的归档
        render_error = f"渲染失败: {type(exc).__name__}: {exc}"

    blocked_code = ""
    if fresh:
        from . import attachments as attachments_mod
        blocked_code = attachments_mod.grab_after_ingest(source_key, source_id) or ""  # 0927：导入时就下附件

    return {"item_id": summary.get("item_id"), "status": status, "url": url, "_source_id": source_id,
            "_render_error": render_error, "_blocked_code": blocked_code}


def _finish(entry: dict[str, Any], enriched: dict[str, Any] | None) -> dict[str, Any]:
    """抓取阶段的条目 → 给调用方的 payload（在识图/概要补完之后读，概要才是新的）。"""
    source_id = entry.get("_source_id")
    if not source_id:
        return {k: v for k, v in entry.items() if not k.startswith("_")}
    try:
        payload = read_mod.item_payload(xhs.SOURCE, source_id, status=entry["status"])
    except Exception as exc:  # noqa: BLE001
        return {
            "item_id": entry.get("item_id"),
            "status": "error",
            "url": entry.get("url"),
            "error": f"读归档失败: {type(exc).__name__}: {exc}",
        }
    problem = entry.get("_render_error")
    if enriched and enriched.get("status") == "failed":
        problem = f"识图/概要没补完（归档已存好，夜里会补）：{enriched.get('error')}"
    if problem:
        payload["error"] = problem
    return payload


def catch_message(
    message: str,
    *,
    origin: str = "cli",
    actor: str = "human",
    verbose: bool = False,
    extract: bool = False,
    refresh: bool = False,
    wait_lock_s: float = 120,
) -> dict[str, Any]:
    """一条消息 → `{"found": N, "items": [...]}`（同一篇笔记出现两次只算一条）。"""
    from . import enrich as enrich_mod

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    with contextlib.ExitStack() as stack:
        lock = _LazyLock(stack, "catch", wait_lock_s)
        for url in find_xhs_urls(message):
            entry = _catch_one(url, message=message, origin=origin, actor=actor, verbose=verbose,
                               lock=lock, refresh=refresh)
            item_id = entry.get("item_id")
            if item_id:
                if item_id in seen:
                    continue
                seen.add(item_id)
            entries.append(entry)
            if entry.get("_blocked_code"):  # 这篇存好了，但下附件时号出事：后面的链接别再开页
                entries.append({"item_id": None, "status": "blocked", "url": url, "code": entry["_blocked_code"],
                                "error": f"下附件时账号要处理（{entry['_blocked_code']}），已停车"})
                break
            if entry.get("status") == "blocked":
                break  # 号出事了，后面的链接照抓也只是接着失败
    # 账号锁已放：识图（--extract 时连概要）交给 enrich，每篇限时的子进程，不碰号
    items = []
    for entry in entries:
        enriched = None
        if entry.get("status") == "new" and entry.get("_source_id"):
            enriched = enrich_mod.enrich_one(xhs.SOURCE, entry["_source_id"], llm=extract)
        items.append(_finish(entry, enriched))
    return {"found": len(items), "items": items}


def run(args) -> int:
    with contextlib.redirect_stdout(sys.stderr):  # stdout 只留最后那一个 JSON（lwa 依赖）
        payload = catch_message(
            args.message,
            origin=args.origin,
            actor=args.actor,
            verbose=getattr(args, "verbose", False),
            extract=getattr(args, "extract", False),
            refresh=getattr(args, "refresh", False),
            wait_lock_s=float(getattr(args, "wait_lock_min", 2) or 0) * 60,
        )
        statuses = {item.get("status") for item in payload["items"]}
        if "blocked" in statuses:
            print("catch: 要人处理（登录态/风控/服务挂了），已停车并报警", file=sys.stderr)
            code = EXIT_NEEDS_HUMAN
        elif "busy" in statuses:
            print(f"catch: {BUSY_MESSAGE}（号正被同步收藏 / 附件占着）", file=sys.stderr)
            code = EXIT_ACCOUNT_BUSY
        elif "error" in statuses:
            print("catch: 有链接没归档成功，详见 JSON 里的 error 字段", file=sys.stderr)
            code = EXIT_ERROR
        else:
            code = EXIT_OK
    read_mod.dump_json(payload)
    return code
