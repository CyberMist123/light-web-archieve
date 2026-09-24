"""`sync-favorites` 子命令（Lot 6）：把 Owner 主号（momo）的**私密收藏**同步进归档。

小红书没有"列出我的收藏"的公开接口，`user_profile(tab="fav")` 对私密收藏只回游客视图
（`feeds:null`）。真正能读到私密收藏的是**登录态自己看自己**：由外部读取器 `favdump.exe`
（`C:\\Users\\18717\\.xiaohongshu-mcp`，Codex 的 persistent-profile 方案 + 客户端路由进「我」→
收藏 tab）吐出 `{items:[{note_id, xsec_token, url, ...}]}`。

拿到 note_id 列表之后，逐条走**和 `catch` 一样**的 `ingest_url`：命中索引就是 HIT（不联网、
不下载），未命中才连 18060 抓正文 / 图 / 评论。去重只认 `xiaohongshu:<note_id>`（硬约束 7）。

硬约束 8：这里不起 HTTP / MCP 服务；调度（每晚一次）在仓库外。stdout 只许有一个 JSON，
日志一律走 stderr。收藏读取要登录态 —— favdump 报未登录（退出码 3）时**停车 + 报警**，
让 Owner 重扫一次（`sessioncheck.exe -login`），不是每晚都要她扫。

读收藏**必须** `XHS_HOST=https://www.xiaohongshu.com`：rednote.com 的 web_session 在登录浏览器
关掉后会被服务端作废，只有 xiaohongshu.com 的会话能跨无扫码重启存活（2026-09-07 实测）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from . import alert as alert_mod, catch as catch_mod, ingest as ingest_mod, read as read_mod
from .adapters import xiaohongshu as xhs
from . import accounts

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_HUMAN = 5

# 外部读取器：默认本机路径，可用环境变量覆盖（和 media.py / alert.py 一样走可配外部命令）。
DEFAULT_FAVDUMP = str(accounts.fav_exe() or 'favdump')
DEFAULT_FAV_HOST = "https://www.xiaohongshu.com"
DEFAULT_FAV_PROFILE = str(accounts.fav_profile())
# favdump 退出码约定（见 cmd/favdump/main.go）：0 成功、3 未登录/掉线、其它=错误。
FAVDUMP_LOGIN_REQUIRED = 3


def fetch_favorites(*, limit: int = 50, verbose: bool = False) -> list[dict[str, Any]]:
    """跑 favdump.exe 读当前登录用户的私密收藏，返回 `[{note_id, xsec_token, url, title, ...}]`。

    未登录（退出码 3）→ `AccountBlockedError`（要 Owner 重扫）；其它非零 → `ServiceDownError`。
    """
    favdump = accounts.fav_exe() or DEFAULT_FAVDUMP
    env = accounts.fav_env()

    if verbose:
        print(f"[sync-favorites] favdump={favdump} host={env['XHS_HOST']}", file=sys.stderr)

    try:
        proc = subprocess.run(
            [favdump], capture_output=True, env=env, timeout=360
        )
    except FileNotFoundError as exc:
        raise xhs.ServiceDownError(
            "收藏同步尚未配置：请打开 Link Brain 设置页查看收藏同步状态；普通链接归档不受影响。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise xhs.ServiceDownError("favdump 读收藏超时（浏览器起不来？）") from exc

    if proc.returncode == FAVDUMP_LOGIN_REQUIRED:
        if 'login check failed' in proc.stderr.decode('utf-8', 'replace').lower():
            raise xhs.ServiceDownError('收藏登录状态暂时无法验证，请关闭占用的登录窗口后重试。')
        raise xhs.AccountBlockedError(
            "收藏账号登录已失效：请在 Link Brain 设置页点击收藏同步「重新扫码」，或运行 link-brain login favorites。"
        )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[-400:]
        raise xhs.ServiceDownError(f"favdump 失败（exit={proc.returncode}）：{detail}")

    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as exc:
        raise xhs.ServiceDownError(f"favdump 输出不是合法 JSON：{exc}") from exc

    items = data.get("items") or []
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
        return {"item_id": None, "status": "blocked", "url": url, "error": str(exc), "login_account": None if service else 'xhs'}
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
        alert_mod.alert(
            alert_mod.KIND_SERVICE if service else alert_mod.KIND_ACCOUNT,
            "小红书收藏同步停了："
            + ("收藏读取服务出错" if service else "收藏登录态要 Owner 重扫一次"),
            str(exc),
        )
        return {
            "favorites": 0,
            "synced": 0,
            "login_account": None if service else "favorites",
            "items": [{"item_id": None, "status": "blocked", "url": None, "error": str(exc)}],
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
