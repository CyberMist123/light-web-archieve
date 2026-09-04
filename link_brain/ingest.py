"""ingest 流水线：链接 → adapter → 不可变 RAW。

Lot 1 只到 RAW 落盘；索引（Lot 2）、渲染（Lot 3）在后面接上。
落盘产物见 docs/FORMAT.md §1/§2/§3/§4。
"""

from __future__ import annotations

import hashlib
import io
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__, alert as alert_mod, index as index_mod, storage
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


def download_media(source: dict[str, Any], raw_version_dir: Path, rel_prefix: str) -> dict[str, Any]:
    """按 source.json 下载全部图片，返回 manifest.json 的内容（docs/FORMAT.md §4）。"""
    note = source["note"]
    assets = raw_version_dir / "assets"
    media: list[dict[str, Any]] = []
    is_video = note["kind"] == "video"

    with httpx.Client() as client:
        for image in note["images"]:
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

    if is_video and note.get("video", {}).get("video_url"):
        media.append(
            {
                "role": "video",
                "index": 1,
                "file": None,
                "original_url": note["video"]["video_url"],
                "requested_url": None,
                "mime": None,
                "width": note["video"].get("width"),
                "height": note["video"].get("height"),
                "bytes": None,
                "sha256": None,
                "download_status": "skipped",
                "error": "视频本体按设计不下载（只留 URL + 封面）",
            }
        )

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


def ingest_url(
    target: str,
    *,
    origin: str = "cli",
    actor: str = "human",
    ingest_kind: str = "shared",
    note: str | None = None,
    verbose: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """抓一条链接并落一份不可变 RAW。返回摘要 dict（含 exit_code）。

    去重：`(source, source_id)` 命中索引且非 `--refresh` → 直接返回已有对象，不联网不下载。
    `--refresh`：重新抓取，规范化比对与最新版本一致就不写新 RAW，只更新 `last_checked_at`；
    有变化才写新版本（`raw/v0001` 字节绝不动）。
    """

    def log(message: str) -> None:
        if verbose:
            print(f"[ingest] {message}", file=sys.stderr)

    parsed = xhs.parse_input(target)
    log(f"input_kind={parsed['input_kind']} note_id={parsed['note_id']}")

    conn = index_mod.connect()
    created_at = now_iso()
    try:
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
        raw = xhs.fetch_detail(parsed["note_id"], parsed["xsec_token"])

        # 附件元数据只有笔记网页版有（MCP 不返回），游客可见；失败不阻断
        log(f"网页探测附件 {xhs.CANONICAL_FMT.format(note_id=parsed['note_id'])}")
        web_probe = xhs.fetch_related_file(parsed["note_id"], parsed.get("xsec_token"))
        if not web_probe["ok"]:
            log(f"网页探测失败（退回正文线索）: {web_probe['error']}")
            if web_probe.get("blocked"):
                # 网页那侧被拦了（验证码/登录墙）。MCP 还能抓就不中止，但必须让人知道
                alert_mod.alert(
                    alert_mod.KIND_ACCOUNT,
                    "小红书网页那侧被拦了（附件元数据会缺）",
                    f"{parsed['note_id']}: {web_probe['error']}",
                    url=web_probe["url"],
                )

        captured_at = now_iso()
        source = xhs.normalize(raw, parsed, captured_at=captured_at, web_probe=web_probe)
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
        # 号出事 / 服务出事：单独一个退出码 + 报警，别让批量脚本闷头把剩下的全刷成失败
        service = isinstance(exc, xhs.ServiceDownError)
        alert_mod.alert(
            alert_mod.KIND_SERVICE if service else alert_mod.KIND_ACCOUNT,
            "小红书归档停了：" + ("18060 的服务要人管" if service else "号要人处理"),
            str(exc),
            url=args.target,
        )
        print(f"归档中止（{'服务' if service else '账号/风控'}）: {exc}", file=sys.stderr)
        return EXIT_NEEDS_HUMAN
    except xhs.AdapterError as exc:
        print(f"归档失败: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileExistsError as exc:
        print(f"归档失败: {exc}", file=sys.stderr)
        return EXIT_ERROR

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
