"""ingest 流水线：链接 → adapter → 不可变 RAW。

Lot 1 只到 RAW 落盘；索引（Lot 2）、渲染（Lot 3）在后面接上。
落盘产物见 docs/FORMAT.md §1/§2/§3/§4。
"""

from __future__ import annotations

import hashlib
import io
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__, index as index_mod, problems, storage
from .adapters import xiaohongshu as xhs

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_CONTENT = 2
EXIT_NEEDS_HUMAN = 5  # 要人处理：登录态失效 / 风控验证码 / 18060 的服务挂了

MIME_EXT = {
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/heic": ".heic",
    "image/bmp": ".bmp",
}

DOWNLOAD_HEADERS = {"User-Agent": xhs.MOBILE_UA, "Referer": "https://www.xiaohongshu.com/"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 图片下载三检
# --------------------------------------------------------------------------


def download_image(url: str, dest_dir: Path, stem: str, *, client: httpx.Client) -> dict[str, Any]:
    """下载一张图并做三检：HTTP 2xx / Content-Type 是图片 / Pillow 能读出宽高。

    通过才写盘，bytes **原样落盘不转码**。返回 manifest 的媒体片段（不含 role/index）。
    """
    result: dict[str, Any] = {
        "file": None,
        "requested_url": url,
        "mime": None,
        "width": None,
        "height": None,
        "bytes": None,
        "sha256": None,
        "download_status": "failed",
        "error": None,
    }
    try:
        response = client.get(url, headers=DOWNLOAD_HEADERS, follow_redirects=True, timeout=60)
    except Exception as exc:  # noqa: BLE001 - 网络异常一律记进 manifest，不炸流程
        result["error"] = f"请求失败: {type(exc).__name__}: {exc}"
        return result

    # 检 ①
    if response.status_code // 100 != 2:
        result["error"] = f"HTTP {response.status_code}"
        return result
    # 检 ②
    mime = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    result["mime"] = mime or None
    if not mime.startswith("image/"):
        result["error"] = f"Content-Type 不是图片: {mime or '(空)'}"
        return result
    # 检 ③
    payload = response.content
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"Pillow 读不出图片: {type(exc).__name__}: {exc}"
        return result
    if not width or not height:
        result["error"] = "Pillow 读出的宽高为 0"
        return result

    path = dest_dir / f"{stem}{MIME_EXT.get(mime, '.bin')}"
    path.write_bytes(payload)
    result.update(
        file=path.name,
        width=width,
        height=height,
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        download_status="ok",
    )
    return result


def _download_comment_audio(audio: dict[str, Any], comment_id: str, assets: Path, rel_prefix: str,
                            client: httpx.Client) -> dict[str, Any]:
    """语音评论：CDN 直链（带签名，公开可取），存成 .m4a；失败只记状态，不影响归档。"""
    entry = {"role": "comment_audio", "comment_id": comment_id, "original_url": audio["url"],
             "file": None, "download_status": "failed"}
    try:
        response = client.get(audio["url"], timeout=60, follow_redirects=True)
        response.raise_for_status()
        if not response.content:
            raise ValueError("空文件")
        assets.mkdir(parents=True, exist_ok=True)
        name = f"comment-{comment_id}-audio.m4a"
        (assets / name).write_bytes(response.content)
        entry.update(file=f"{rel_prefix}/assets/{name}", bytes=len(response.content),
                     sha256=hashlib.sha256(response.content).hexdigest(), download_status="ok")
    except (httpx.HTTPError, OSError, ValueError) as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return entry


def download_media(source: dict[str, Any], raw_version_dir: Path, rel_prefix: str) -> dict[str, Any]:
    """按 source.json 下载全部图片，返回 manifest.json 的内容（docs/FORMAT.md §4）。"""
    note = source["note"]
    assets = raw_version_dir / "assets"
    media: list[dict[str, Any]] = []
    is_video = note["kind"] == "video"
    from .ai_config import sync_options
    opts = sync_options()

    with httpx.Client() as client:
        for image in (note["images"] if opts["downloadImages"] else []):
            # 视频型笔记的 imageList 就是封面，role 记 video_cover
            role = "video_cover" if is_video else "note_image"
            stem = f"cover-{image['index']:03d}" if is_video else f"image-{image['index']:03d}"
            entry = {"role": role, "index": image["index"], "original_url": image["url"]}
            entry.update(download_image(image["url"], assets, stem, client=client))
            if entry["file"]:
                entry["file"] = f"{rel_prefix}/assets/{entry['file']}"
            media.append(entry)

        for comment in source["comments"]:
            for group in [comment, *(comment.get("sub_comments") or [])]:
                for i, image in enumerate(group.get("images") or [], start=1):
                    stem = f"comment-{group['comment_id']}-{i:03d}"
                    entry = {
                        "role": "comment_image",
                        "index": i,
                        "comment_id": group["comment_id"],
                        "original_url": image["url"],
                    }
                    entry.update(download_image(image["url"], assets, stem, client=client))
                    if entry["file"]:
                        entry["file"] = f"{rel_prefix}/assets/{entry['file']}"
                    media.append(entry)
                audio = group.get("audio")
                if audio and audio.get("url"):
                    media.append(_download_comment_audio(audio, group["comment_id"], assets, rel_prefix, client))

    if opts["downloadVideo"] and is_video and (note.get("video") or {}).get("video_url"):
        from .videos import download
        media.append(download(note['video'], raw_version_dir, rel_prefix))

    declared = sum(1 for m in media if m["role"] in ("note_image", "comment_image", "video_cover"))
    ok = sum(
        1
        for m in media
        if m["role"] in ("note_image", "comment_image", "video_cover")
        and m["download_status"] == "ok"
    )
    return {
        "schema_version": 1,
        "version": int(raw_version_dir.name[1:]),
        "created_at": now_iso(),
        "images_declared": declared,
        "images_ok": ok,
        "images_complete": declared == ok,
        "media": media,
    }


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def _build_meta(
    *,
    parsed: dict[str, Any],
    source: dict[str, Any],
    manifest: dict[str, Any],
    version: int,
    captured_at: str,
    origin: str,
    actor: str,
    ingest_kind: str,
    note: str | None,
    first_archived: str,
) -> dict[str, Any]:
    attachments = source["note"]["attachments"]
    statuses = {a.get("status") for a in attachments}
    if not attachments:
        attachments_status = "none"
    elif "downloaded" in statuses:
        attachments_status = "downloaded"
    elif "metadata_only" in statuses:
        attachments_status = "metadata_only"
    else:
        attachments_status = "unavailable"
    return {
        "schema_version": 1,
        "item_id": f"xhs-{parsed['note_id']}",
        "source": xhs.SOURCE,
        "source_id": parsed["note_id"],
        "canonical_url": parsed["canonical_url"],
        "input_url": parsed["input_url"],
        "kind": source["note"]["kind"],
        "title": source["note"]["title"],
        "author": {
            k: source["note"]["author"][k] for k in ("user_id", "nickname", "profile_url")
        },
        "published_at": source["note"]["published_at"],
        "first_archived_at": first_archived,
        "last_checked_at": captured_at,
        "current_version": version,
        "versions": storage.existing_versions(xhs.SOURCE, parsed["note_id"]),
        "visible_note": None,
        "images_complete": manifest["images_complete"],
        "comments_complete": source["capture"]["comments_complete"],
        "attachments_status": attachments_status,
        "origin": origin,
        "actor": actor,
        "ingest_kind": ingest_kind,
        "note": note,
        "tool_versions": {
            "link_brain": __version__,
            "adapter": xhs.ADAPTER_VERSION,
            "mcp_endpoint": xhs.MCP_ENDPOINT,
        },
    }


# 18060 那个服务每次调用都新开一个 Chrome，本机内存紧的时候会偶发起不来
# （`[launcher] Failed to get the debug url`，2026-09-04 半夜实测：只剩 0.9G 可用内存时高发）。
# 这是**偶发**不是**死了**：先自己歇一会儿重试，全试完还不行才停车叫人。
SERVICE_RETRIES = 3
SERVICE_BACKOFF = (20, 60)


FILL_BUDGET_S = 540  # 续读一次给读取组件的评论预算（秒）；请求超时比它多 60 秒
FILL_MAX_ATTEMPTS = 3  # 一篇最多续读几次（每次能多拿约 500 条回复；再多就是几千楼的帖子，如实标缺）
FILL_GAP_HOURS = 20    # 两次续读同一篇至少隔这么久（同一晚别反复开同一页）


def _detail_kwargs(comment_floors: int | str | None, expand_floors: list[str] | None = None) -> dict[str, Any]:
    """评论楼层：10（默认，秒回）/ 20 / 50（滚评论区并展开楼中楼，限楼数）/ "all"（手动全量）。
    expand_floors（1008 续读）：只展开这些楼，给足预算。"""
    if expand_floors:
        return {"full_comments": True, "comment_limit": 10, "timeout": FILL_BUDGET_S + 60,
                "comment_budget_s": FILL_BUDGET_S, "expand_floors": list(expand_floors)}
    if comment_floors is None:
        from .ai_config import sync_options
        comment_floors = sync_options()["commentFloors"]
    if comment_floors == "all":
        return {"full_comments": True, "comment_limit": 2000, "timeout": 1500}
    floors = int(comment_floors)
    # 0929 Owner：10 楼也要展开楼中楼（load_all_comments=false 只给首屏，不点「展开回复」）
    floors = max(floors, 10)
    return {"full_comments": True, "comment_limit": floors, "timeout": 600}


def _fetch_with_retry(parsed: dict[str, Any], *, log, comment_floors=None, budget_left=None, expand_floors=None) -> Any:
    """抓详情；服务没起来时隔一会儿重试（最多 SERVICE_RETRIES 次）。

    budget_left（1001）：返回「这一批还剩几秒」的函数。剩下的不够再等一轮 + 再抓一次的最坏耗时，就不重试了，
    直接把 ServiceDownError 抛给调用方——夜跑的同步步骤有外层限时，别在预算尽头又挂一个 10 分钟的请求被整棵杀。
    """
    kwargs = _detail_kwargs(comment_floors, expand_floors)
    from . import accounts
    for attempt in range(1, SERVICE_RETRIES + 1):
        accounts.pace("打开笔记")  # 1001：跨进程开页间隔（与附件、补看、读收藏共用一个时刻戳）
        try:
            return xhs.fetch_detail(parsed["note_id"], parsed["xsec_token"], **kwargs)
        except xhs.ServiceDownError as exc:
            if attempt == SERVICE_RETRIES:
                raise
            wait = SERVICE_BACKOFF[min(attempt - 1, len(SERVICE_BACKOFF) - 1)]
            if budget_left is not None and budget_left() < wait + float(kwargs.get("timeout") or 600) + 60:
                log(f"服务没起来（第 {attempt}/{SERVICE_RETRIES} 次），这一批的时间不够再试了")
                raise
            log(f"服务没起来（第 {attempt}/{SERVICE_RETRIES} 次）：{str(exc)[:120]}；{wait}s 后重试")
        finally:
            accounts.pace_done()  # 开页间隔从这一页看完算起
        time.sleep(wait)
    raise AssertionError("unreachable")


def _merge_fill(source: dict[str, Any], existing: Any, expanded: set[str], captured_at: str, log) -> dict[str, Any]:
    meta = storage.read_json(storage.object_dir(xhs.SOURCE, source["source_id"]) / "meta.json")
    old = storage.read_json(storage.raw_dir(xhs.SOURCE, source["source_id"], meta["current_version"]) / "source.json")
    merged = xhs.merge_comments(old.get("comments") or [], source.get("comments") or [], expanded)
    new_cl = source["capture"].get("comment_load")
    if new_cl is not None:
        new_cl = {**new_cl, "fill_last_at": captured_at}
    cl = xhs.merge_comment_load((old.get("capture") or {}).get("comment_load"), new_cl, expanded, merged)
    before = sum(len(c.get("sub_comments") or []) for c in old.get("comments") or [])
    after = sum(len(c.get("sub_comments") or []) for c in merged)
    log(f"续读合并：楼中楼 {before} → {after} 条，还缺 {(cl or {}).get('replies_missing', 0)} 条")
    return {**source, "comments": merged, "capture": {**source["capture"], "comment_load": cl}}


def _log_comment_load(source: dict[str, Any], log) -> None:
    """评论读到哪一步、缺多少，进同步记录（1008 Owner：缺口要让人看到，不能悄悄少一截）。"""
    cl = (source.get("capture") or {}).get("comment_load")
    if not cl:
        return
    missing = int(cl.get("replies_missing") or 0)
    item_id = f"xhs-{source['source_id']}"
    title = (source.get("note") or {}).get("title")
    try:
        from . import synclog
        if missing > 0:
            why = xhs.REPLY_GAP_CN.get(_main_gap_reason(cl), "没读全")
            fillable = _fillable(cl)
            tail = "，下次同步接着读" if fillable else ""
            synclog.note("comments", item_id, False, title=title, reason=f"楼中楼还缺 {missing} 条（{why}）{tail}",
                         code="COMMENTS_PARTIAL", retry=["comments", item_id, "--fill"] if fillable else None)
            log(f"评论：楼中楼还缺 {missing} 条（{why}）")
        elif int(cl.get("fill_attempts") or 0) > 0:
            synclog.note("comments", item_id, True, title=title)
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] {type(exc).__name__}: {exc}", file=sys.stderr)


def _main_gap_reason(cl: dict[str, Any]) -> str:
    gaps = cl.get("gaps") or []
    if not gaps:
        return str(cl.get("stop_reason") or "")
    return max(gaps, key=lambda g: int(g.get("missing") or 0)).get("reason") or str(cl.get("stop_reason") or "")


def _fillable(cl: dict[str, Any]) -> bool:
    """这篇还能不能续读：有能续的缺口、次数没用完。"""
    if int(cl.get("replies_missing") or 0) <= 0 or int(cl.get("fill_attempts") or 0) >= FILL_MAX_ATTEMPTS:
        return False
    return any(g.get("reason") in xhs.RESUMABLE_GAPS and g.get("comment_id") for g in cl.get("gaps") or [])


def fill_targets(cl: dict[str, Any]) -> list[str]:
    """要续读的楼（comment_id），缺得多的在前。"""
    gaps = [g for g in cl.get("gaps") or [] if g.get("reason") in xhs.RESUMABLE_GAPS and g.get("comment_id")]
    gaps.sort(key=lambda g: -int(g.get("missing") or 0))
    return [str(g["comment_id"]) for g in gaps]


def ingest_url(
    target: str,
    *,
    origin: str = "cli",
    actor: str = "human",
    ingest_kind: str = "shared",
    note: str | None = None,
    verbose: bool = False,
    refresh: bool = False,
    comment_floors: int | str | None = None,
    parsed: dict[str, Any] | None = None,
    budget_left=None,
    expand_floors: list[str] | None = None,
) -> dict[str, Any]:
    """抓一条链接并落一份不可变 RAW。返回摘要 dict（含 exit_code）。

    去重：`(source, source_id)` 命中索引且非 `--refresh` → 直接返回已有对象，不联网不下载。
    `--refresh`：重新抓取，规范化比对与最新版本一致就不写新 RAW，只更新 `last_checked_at`；
    有变化才写新版本（`raw/v0001` 字节绝不动）。
    """

    def log(message: str) -> None:
        if verbose:
            print(f"[ingest] {message}", file=sys.stderr)

    parsed = parsed or xhs.parse_input(target)  # catch 已经解析过（为了先判要不要拿账号锁）就别再跟一次短链
    log(f"input_kind={parsed['input_kind']} note_id={parsed['note_id']}")

    conn = index_mod.connect()
    created_at = now_iso()
    try:
        tombstone = conn.execute('SELECT * FROM tombstones WHERE source = ? AND source_id = ?',
                                 (xhs.SOURCE, parsed['note_id'])).fetchone()
        if tombstone:
            log('已删除，跳过')
            return {'status': 'trashed', 'item_id': tombstone['item_id'],
                    'note_id': parsed['note_id'], 'title': tombstone['title'], 'exit_code': EXIT_OK}
        existing = index_mod.find_object(conn, xhs.SOURCE, parsed["note_id"])

        if existing is not None and not refresh:
            log("index HIT，不调用 MCP，不下载")
            item_id = existing["item_id"]
            index_mod.add_relation(
                conn,
                item_id=item_id,
                origin=origin,
                actor=actor,
                ingest_kind=ingest_kind,
                note=note,
                created_at=created_at,
            )
            meta_path = storage.object_dir(xhs.SOURCE, parsed["note_id"]) / "meta.json"
            meta = storage.read_json(meta_path)
            return {
                "hit": True,
                "item_id": item_id,
                "note_id": parsed["note_id"],
                "kind": existing["kind"],
                "raw_dir": storage.raw_dir(xhs.SOURCE, parsed["note_id"], meta["current_version"]),
                "version": meta["current_version"],
                "manifest": None,
                "failed": [],
                "comments": None,
                "sub_comments": None,
                "comments_complete": existing["comments_complete"],
                "attachments_status": existing["attachments_status"],
                "exit_code": EXIT_OK,
            }

        log(f"MCP {xhs.MCP_TOOL} @ {xhs.MCP_ENDPOINT}")
        raw = _fetch_with_retry(parsed, log=log, comment_floors=comment_floors, budget_left=budget_left,
                                expand_floors=expand_floors)
        problems.resolve("ingest", None)  # 抓到了 = 读取服务好着：之前「服务没起来 / 超时」那几条步骤级问题算解决

        # 附件元数据只有笔记网页版有（MCP 不返回），游客可见；失败不阻断
        log(f"网页探测附件 {xhs.CANONICAL_FMT.format(note_id=parsed['note_id'])}")
        web_probe = xhs.fetch_related_file(parsed["note_id"], parsed.get("xsec_token"))
        if not web_probe["ok"]:
            # 0929：游客被登录墙挡住的笔记（附件照样有）当场用登录号再看一次，别等夜里补查
            from .attachments import _probe_logged_in
            logged = _probe_logged_in(parsed["note_id"], parsed.get("xsec_token"))
            if logged.get("needs_human"):
                # 1001：登录号补看撞到掉登录 / 风控 → 整批停车，别拿这篇的半截结果入库，也别接着开下一篇
                err = xhs.AccountBlockedError(f"读取账号需要处理：{logged.get('error')}")
                err.code = logged.get("code") or ""
                raise err
            if logged.get("ok"):
                log("游客看不到，登录号看到了笔记页（附件元数据取自登录号）")
                web_probe = {**web_probe, **logged}
            else:
                web_probe["error"] = f"{web_probe.get('error')}；登录号：{logged.get('error')}"
        if not web_probe["ok"]:
            log(f"网页探测失败（退回正文线索）: {web_probe['error']}")
            if web_probe.get("blocked"):
                # 游客网页那侧被拦了（验证码 / 登录墙），登录号补看也没拿到、但号本身没事（号出事上面已经整批停车）。
                # MCP 还能抓就不中止：只缺附件元数据，夜里 attachments --recheck 会再补查——TRANSIENT，只记不推。
                problems.report("ingest", "TRANSIENT.WEB_PROBE_BLOCKED",
                                f"网页那侧被拦了，附件信息暂缺：{web_probe['error']}"[:200],
                                item_id=f"xhs-{parsed['note_id']}")
        else:
            problems.resolve("ingest", f"xhs-{parsed['note_id']}", "TRANSIENT.WEB_PROBE_BLOCKED")

        captured_at = now_iso()
        source = xhs.normalize(raw, parsed, captured_at=captured_at, web_probe=web_probe)
        if expand_floors and existing is not None:
            # 1008 续读：这次只展开了指定的楼，其它楼的楼中楼沿用上一版（不然新版本反而少了）
            source = _merge_fill(source, existing, set(expand_floors), captured_at, log)
        _log_comment_load(source, log)
        new_sha = index_mod.normalized_source_sha256(source)

        object_dir = storage.object_dir(xhs.SOURCE, parsed["note_id"])
        meta_path = object_dir / "meta.json"

        if refresh and existing is not None:
            prior_sha = index_mod.latest_source_sha256(conn, existing["item_id"])
            if prior_sha is not None and prior_sha == new_sha:
                log("refresh：规范化比对无变化，不写新 RAW 版本，只更新 last_checked_at")
                meta = storage.read_json(meta_path)
                meta["last_checked_at"] = captured_at
                storage.write_json(meta_path, meta)
                index_mod.upsert_object(conn, meta, source)
                index_mod.add_relation(
                    conn,
                    item_id=meta["item_id"],
                    origin=origin,
                    actor=actor,
                    ingest_kind=ingest_kind,
                    note=note,
                    created_at=created_at,
                )
                return {
                    "hit": False,
                    "refreshed_unchanged": True,
                    "item_id": meta["item_id"],
                    "note_id": parsed["note_id"],
                    "kind": meta["kind"],
                    "raw_dir": storage.raw_dir(xhs.SOURCE, parsed["note_id"], meta["current_version"]),
                    "version": meta["current_version"],
                    "manifest": None,
                    "failed": [],
                    "comments": len(source["comments"]),
                    "sub_comments": sum(len(c.get("sub_comments") or []) for c in source["comments"]),
                    "comments_complete": source["capture"]["comments_complete"],
                    "attachments_status": meta["attachments_status"],
                    "exit_code": EXIT_OK,
                }
            log("refresh：规范化比对有变化，写新 RAW 版本")

        version = storage.next_version(xhs.SOURCE, parsed["note_id"])
        raw_dir = storage.ensure_raw_dir(xhs.SOURCE, parsed["note_id"], version)
        rel_prefix = f"raw/{storage.version_name(version)}"
        log(f"RAW → {raw_dir}")

        storage.write_json(raw_dir / "mcp_raw.json", raw)
        # 网页探测的原始结果单独存一份，方便以后回溯"当时页面上有没有附件"
        storage.write_json(raw_dir / "web_raw.json", web_probe)
        storage.write_json(raw_dir / "source.json", source)
        manifest = download_media(source, raw_dir, rel_prefix)
        storage.write_json(raw_dir / "manifest.json", manifest)

        first_archived = (
            storage.read_json(meta_path).get("first_archived_at")
            if meta_path.exists()
            else captured_at
        )
        meta = _build_meta(
            parsed=parsed,
            source=source,
            manifest=manifest,
            version=version,
            captured_at=captured_at,
            origin=origin,
            actor=actor,
            ingest_kind=ingest_kind,
            note=note,
            first_archived=first_archived,
        )
        if meta_path.exists():
            # 不由抓取产生、只能后加的字段：重建 meta 时原样带上（如收藏来自哪个号）
            previous = storage.read_json(meta_path)
            for key in ("favorited_by",):
                if key in previous and key not in meta:
                    meta[key] = previous[key]
        storage.write_json(meta_path, meta)

        index_mod.upsert_object(conn, meta, source)
        index_mod.add_source_version(
            conn,
            item_id=meta["item_id"],
            version=version,
            raw_dir=raw_dir,
            captured_at=captured_at,
            adapter=xhs.ADAPTER_VERSION,
            input_url=parsed["input_url"],
            input_kind=parsed["input_kind"],
            source_sha256=new_sha,
        )
        index_mod.add_relation(
            conn,
            item_id=meta["item_id"],
            origin=origin,
            actor=actor,
            ingest_kind=ingest_kind,
            note=note,
            created_at=created_at,
        )

        failed = [m for m in manifest["media"] if m["download_status"] == "failed"]
        return {
            "hit": False,
            "refreshed_unchanged": False,
            "item_id": meta["item_id"],
            "note_id": parsed["note_id"],
            "kind": meta["kind"],
            "raw_dir": raw_dir,
            "version": version,
            "manifest": manifest,
            "failed": failed,
            "comments": len(source["comments"]),
            "sub_comments": sum(len(c.get("sub_comments") or []) for c in source["comments"]),
            "comments_complete": source["capture"]["comments_complete"],
            "attachments_status": meta["attachments_status"],
            "exit_code": EXIT_MISSING_CONTENT if failed else EXIT_OK,
        }
    finally:
        conn.close()


def run(args) -> int:
    try:
        summary = ingest_url(
            args.target,
            origin=args.origin,
            actor=args.actor,
            ingest_kind=args.ingest_kind,
            note=args.note,
            verbose=getattr(args, "verbose", False),
            refresh=getattr(args, "refresh", False),
        )
    except xhs.NeedsHumanError as exc:
        # 号出事 / 服务出事：单独一个退出码 + 登记问题（账号类 NEEDS_HUMAN 推一次；服务类 TRANSIENT 只记），
        # 别让批量脚本闷头把剩下的全刷成失败
        service = isinstance(exc, xhs.ServiceDownError)
        problems.report_blocked("ingest", getattr(exc, "code", "") or "", f"导入停了：{exc}", service=service)
        print(f"归档中止（{'服务' if service else '账号/风控'}）: {exc}", file=sys.stderr)
        return EXIT_NEEDS_HUMAN
    except xhs.AdapterError as exc:
        print(f"归档失败: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileExistsError as exc:
        print(f"归档失败: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if summary.get('status') == 'trashed':
        from .read import dump_json
        dump_json(summary)
        return EXIT_OK

    if summary.get("hit"):
        print(f"HIT  {summary['item_id']}  kind={summary['kind']}  {summary['raw_dir']}")
        return summary["exit_code"]

    if summary.get("refreshed_unchanged"):
        print(f"REFRESH（无变化）  {summary['item_id']}  {summary['raw_dir']}")
        return summary["exit_code"]

    # ingest 落盘成功（含缺内容 gate 的情况）后自动 vision + render，不阻断 ingest 本身的退出码
    if summary.get("item_id"):
        try:
            from . import render as render_mod

            source_key, source_id = xhs.SOURCE, summary["note_id"]
            render_mod.render_item(source_key, source_id, verbose=getattr(args, "verbose", False))
        except Exception as exc:  # noqa: BLE001 - 渲染失败不应回退 ingest 的退出码
            print(f"[ingest] vision/render 失败（不影响归档）: {type(exc).__name__}: {exc}", file=sys.stderr)

    manifest = summary["manifest"]
    print(f"{summary['item_id']}  kind={summary['kind']}  {summary['raw_dir']}")
    print(
        f"  图片 {manifest['images_ok']}/{manifest['images_declared']}"
        f"  一级评论 {summary['comments']}  楼中楼 {summary['sub_comments']}"
        f"  comments_complete={summary['comments_complete']}"
        f"  附件={summary['attachments_status']}"
    )
    if summary["failed"]:
        print("  缺内容 gate：以下媒体没拿到 ——", file=sys.stderr)
        for item in summary["failed"]:
            print(f"    [{item['role']}#{item['index']}] {item['original_url']} : {item['error']}",
                  file=sys.stderr)
    return summary["exit_code"]


def fetch_comments(target: str, *, floors: int | str = "all", verbose: bool = False, fill: bool = False) -> dict[str, Any]:
    """手动抓一篇的评论区（Owner 0926：超过 50 楼 / 全量只在指定笔记上手动抓，不进每晚同步）。

    target 可以是 item_id（xhs-<note_id>）或链接；用归档里最新的 xsec_token 重抓（--refresh 语义，
    RAW 只在内容有变化时出新版本），含楼中楼、评论图片、语音评论，完了重新渲染可见页。
    """
    from . import catch as catch_mod
    url = target
    if not target.startswith("http"):
        conn = index_mod.connect()
        try:
            row = index_mod.get_object(conn, target)
        finally:
            conn.close()
        if not row:
            raise FileNotFoundError(f"没有归档过: {target}")
        meta = storage.read_json(storage.object_dir(row["source"], row["source_id"]) / "meta.json")
        note = storage.read_json(storage.raw_dir(row["source"], row["source_id"], meta["current_version"]) / "source.json")["note"]
        url = f"https://www.xiaohongshu.com/explore/{row['source_id']}?xsec_token={note.get('xsec_token') or ''}"
    expand = None
    if fill:
        if target.startswith("http"):
            raise FileNotFoundError("续读要给已归档的 item_id")
        cl = (storage.read_json(storage.raw_dir(row["source"], row["source_id"], meta["current_version"]) / "source.json")
              .get("capture") or {}).get("comment_load") or {}
        expand = fill_targets(cl)
        if not expand:
            return {"item_id": row["item_id"], "note_id": row["source_id"], "filled": False, "reason": "没有能续读的缺口",
                    "comments": None, "sub_comments": None, "comments_complete": None, "version": meta["current_version"],
                    "refreshed_unchanged": True}
    summary = ingest_url(url, refresh=True, comment_floors=floors, verbose=verbose, expand_floors=expand)
    catch_mod._ensure_rendered(xhs.SOURCE, summary["note_id"], force=True, extract=False)
    if fill:
        summary["filled"] = not summary.get("refreshed_unchanged")
    return summary


def pending_fills(*, limit: int = 0, now: datetime | None = None) -> list[tuple[str, str, dict[str, Any]]]:
    """还有能续读缺口的篇：[(source, source_id, comment_load)]，缺得多的在前；20 小时内刚续过的跳过。"""
    now = now or datetime.now().astimezone()
    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT source, source_id FROM objects ORDER BY item_id").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            meta = storage.read_json(storage.object_dir(r["source"], r["source_id"]) / "meta.json")
            cl = (storage.read_json(storage.raw_dir(r["source"], r["source_id"], meta["current_version"]) / "source.json")
                  .get("capture") or {}).get("comment_load")
        except (OSError, ValueError, KeyError):
            continue
        if not cl or not _fillable(cl):
            continue
        last = cl.get("fill_last_at")
        if last:
            try:
                if (now - datetime.fromisoformat(str(last))).total_seconds() < FILL_GAP_HOURS * 3600:
                    continue
            except ValueError:
                pass
        out.append((r["source"], r["source_id"], cl))
    out.sort(key=lambda x: -int(x[2].get("replies_missing") or 0))
    return out[:limit] if limit else out


def run_fill_pending(args) -> int:
    """`comments --fill-pending [--limit N] [--budget-min M]`：夜跑步骤——给预算内能续读的篇各续一次。"""
    import time
    from .read import dump_json
    budget = float(getattr(args, "budget_min", 0) or 0)
    deadline = time.monotonic() + budget * 60 if budget > 0 else None
    done, failed, skipped = [], [], 0
    targets = pending_fills(limit=int(getattr(args, "limit", 0) or 0))
    for i, (src, sid, cl) in enumerate(targets):
        if deadline is not None and deadline - time.monotonic() < FILL_BUDGET_S + 120:
            skipped = len(targets) - i
            break
        item_id = f"xhs-{sid}"
        try:
            out = fetch_comments(item_id, floors=10, fill=True, verbose=getattr(args, "verbose", False))
            done.append({"item_id": item_id, "filled": out.get("filled"), "sub_comments": out.get("sub_comments")})
        except xhs.NeedsHumanError as exc:
            print(f"续读中止（账号或服务要处理）: {exc}", file=sys.stderr)
            dump_json({"done": done, "failed": failed, "stopped": str(exc), "left": len(targets) - i})
            return EXIT_NEEDS_HUMAN
        except (xhs.AdapterError, FileNotFoundError, OSError) as exc:
            failed.append({"item_id": item_id, "error": str(exc)[:200]})
    dump_json({"candidates": len(targets), "done": done, "failed": failed, "deferred": skipped})
    return EXIT_ERROR if failed and not done else EXIT_OK


def run_comments(args) -> int:
    from .read import dump_json
    if getattr(args, "fill_pending", False):
        return run_fill_pending(args)
    if not args.target:
        print("要给 item_id 或链接（或用 --fill-pending）", file=sys.stderr)
        return EXIT_ERROR
    try:
        floors = args.floors if args.floors == "all" else int(args.floors)
        if getattr(args, "fill", False):
            floors = 10
        summary = fetch_comments(args.target, floors=floors, verbose=getattr(args, "verbose", False),
                                 fill=getattr(args, "fill", False))
    except xhs.NeedsHumanError as exc:
        print(f"评论抓取中止（账号或服务要处理）: {exc}", file=sys.stderr)
        dump_json({'ok': False, 'code': 'NEEDS_HUMAN', 'message': f'评论没抓：{exc}'})
        return EXIT_NEEDS_HUMAN
    except (xhs.AdapterError, FileNotFoundError) as exc:
        print(f"评论抓取失败: {exc}", file=sys.stderr)
        dump_json({'ok': False, 'code': '', 'message': f'评论没抓：{exc}'})
        return EXIT_ERROR
    out = {k: summary.get(k) for k in ("item_id", "note_id", "comments", "sub_comments", "comments_complete", "version",
                                       "refreshed_unchanged", "filled", "reason") if k in summary}
    message = (f'评论没有变化（{summary.get("comments", 0)} 条）' if summary.get('refreshed_unchanged') else
               f'评论已更新：{summary.get("comments", 0)} 条一级、{summary.get("sub_comments", 0)} 条回复')
    if summary.get('comments_complete') is False:
        message += '；还有没读全的楼，夜里接着读'
    dump_json({**out, 'ok': True, 'code': '', 'message': message})
    return 0
