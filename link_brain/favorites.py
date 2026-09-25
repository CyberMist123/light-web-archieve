"""`sync-favorites` 子命令（Lot 6）：把 Owner 主号（momo）的**私密收藏**同步进归档。

小红书没有"列出我的收藏"的公开接口；私密收藏只有**登录态自己看自己**才读得到。
读取服务（`accounts.py`，一个号一个持久浏览器目录）的 `/api/v1/favorites` 负责这一步，
吐出 `{items:[{note_id, xsec_token, url, ...}]}`。

拿到 note_id 列表之后，逐条走**和 `catch` 一样**的 `ingest_url`：命中索引就是 HIT（不联网、
不下载），未命中才经同一个读取服务抓正文 / 图 / 评论。去重只认 `xiaohongshu:<note_id>`（硬约束 7）。

硬约束 8：stdout 只许有一个 JSON，日志一律走 stderr。未登录 / 安全验证时**停车 + 报警**，
由界面给出「扫码登录」或「打开验证」按钮；绝不自动重试。
"""

from __future__ import annotations

import sys
from typing import Any

from . import alert as alert_mod, catch as catch_mod, ingest as ingest_mod, read as read_mod
from .adapters import xiaohongshu as xhs
from . import accounts

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_HUMAN = 5

def fetch_favorites(*, limit: int = 50, verbose: bool = False) -> list[dict[str, Any]]:
    """经读取服务 `/api/v1/favorites` 读当前登录账号的收藏（与评论/附件同一个号、同一个会话）。

    要人处理的（未登录 / 安全验证 / 组件未装）→ `AccountBlockedError`，带 `.code`；
    其余（服务不在 / 超时 / 限频）→ `ServiceDownError`。一律停车，不在这里重试——
    重试会撞风控验证码（2026-09-25 实测）。
    """
    try:
        accounts.ensure_reader()
        data = accounts.api("GET", "/api/v1/favorites", timeout=420)
    except accounts.ReaderError as exc:
        msg = accounts.SOLUTIONS.get(exc.code, ("", str(exc), "", ""))
        text = f"{msg[1]}：{msg[2]}" if msg[2] else str(exc)
        err = (xhs.AccountBlockedError if exc.needs_human else xhs.ServiceDownError)(text)
        err.code = exc.code
        raise err from exc
    items = data.get("items") or []
    if verbose:
        print(f"[sync-favorites] {data.get('nickname')} 收藏 {len(items)} 条", file=sys.stderr)
    if limit and limit > 0:
        items = items[:limit]
    return items


def _sync_one(
    fav: dict[str, Any], *, origin: str, actor: str, verbose: bool, extract: bool
) -> dict[str, Any]:
    """一条收藏 → 归档条目 dict。逻辑同 `catch._catch_one`，只是 ingest_kind=favorite、note=None。"""
    url = fav.get("url") or ""
    try:
        summary = ingest_mod.ingest_url(
            url,
            origin=origin,
            actor=actor,
            ingest_kind="favorite",
            note=None,
            verbose=verbose,
        )
    except xhs.NeedsHumanError as exc:
        service = isinstance(exc, xhs.ServiceDownError)
        alert_mod.alert(
            alert_mod.KIND_SERVICE if service else alert_mod.KIND_ACCOUNT,
            "小红书收藏同步停了：" + ("18060 的服务要人管" if service else "号要人处理"),
            str(exc),
            url=url,
        )
        return {"item_id": None, "status": "blocked", "url": url, "error": str(exc), "login_account": None if service else 'xhs', "code": getattr(exc, "code", "")}
    except Exception as exc:  # noqa: BLE001 - 一条收藏挂了不该带走整批
        return {
            "item_id": None,
            "status": "error",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if summary.get('status') == 'trashed':
        print(f"[sync-favorites] {summary['item_id']} 已删除，跳过", file=sys.stderr)
        return {**summary, 'url': url}
    status = "hit" if summary.get("hit") else "new"
    source_key, source_id = xhs.SOURCE, summary["note_id"]

    render_error = None
    try:
        catch_mod._ensure_rendered(
            source_key, source_id, force=(status == "new"), extract=extract
        )
    except Exception as exc:  # noqa: BLE001 - 渲染失败不该吞掉已经落盘的归档
        render_error = f"渲染失败: {type(exc).__name__}: {exc}"

    try:
        payload = read_mod.item_payload(source_key, source_id, status=status)
    except Exception as exc:  # noqa: BLE001
        return {
            "item_id": summary.get("item_id"),
            "status": "error",
            "url": url,
            "error": f"读归档失败: {type(exc).__name__}: {exc}",
        }
    if render_error:
        payload["error"] = render_error
    return payload


def sync_favorites(
    *,
    limit: int = 50,
    origin: str = "cli",
    actor: str = "human",
    verbose: bool = False,
    extract: bool = False,
) -> dict[str, Any]:
    """读收藏 → 逐条 ingest（去重）→ `{"favorites": N, "synced": M, "items": [...]}`。"""
    try:
        favs = fetch_favorites(limit=limit, verbose=verbose)
    except xhs.NeedsHumanError as exc:
        service = isinstance(exc, xhs.ServiceDownError)
        code = getattr(exc, "code", "")
        if code != "RATE_LIMITED":  # 限频只是「刚同步过」，不打扰人
            alert_mod.alert(
                alert_mod.KIND_SERVICE if service else alert_mod.KIND_ACCOUNT,
                "小红书收藏同步停了：" + ("读取服务要处理" if service else "账号要处理"),
                str(exc),
            )
        return {
            "favorites": 0,
            "synced": 0,
            "login_account": None if service else "xhs",
            "code": code,
            "items": [{"item_id": None, "status": "blocked", "url": None, "error": str(exc), "code": code}],
        }

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fav in favs:
        entry = _sync_one(fav, origin=origin, actor=actor, verbose=verbose, extract=extract)
        item_id = entry.get("item_id")
        if item_id:
            if item_id in seen:
                continue
            seen.add(item_id)
        items.append(entry)
        if entry.get("status") == "blocked":
            break  # 号/服务出事，后面照抓也只是接着失败
    return {"favorites": len(favs), "synced": len(items), "items": items}


def run(args) -> int:
    from . import sync_state
    sync_state.record('running', message='正在同步收藏')
    try:
        payload = sync_favorites(
            limit=getattr(args, "limit", 50),
            origin=getattr(args, "origin", "cli"),
            actor=getattr(args, "actor", "human"),
            verbose=getattr(args, "verbose", False),
            extract=getattr(args, "extract", False),
        )
    except Exception:
        sync_state.record('failed', message='同步未完成，请打开账号 / 同步查看详情并重试')
        raise
    sync_state.record('finished', payload=payload)
    read_mod.dump_json(payload)
    if any(item.get("status") == "blocked" for item in payload["items"]):
        print("sync-favorites: 要人处理（登录态/风控/服务挂了），已停车并报警", file=sys.stderr)
        return EXIT_NEEDS_HUMAN
    if any(item.get("status") == "error" for item in payload["items"]):
        print("sync-favorites: 有收藏没归档成功，详见 JSON 里的 error 字段", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK
