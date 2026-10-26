"""ingest 流水线：链接 → adapter → 不可变 RAW。

Lot 1 只到 RAW 落盘；索引（Lot 2）、渲染（Lot 3）在后面接上。
落盘产物见 docs/FORMAT.md §1/§2/§3/§4。
"""

from __future__ import annotations
from .errtext import errtext

import hashlib
import io
import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__, domain, index as index_mod, problems, sources, storage
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
        # 请求头（UA / Referer）由来源在下载计划里给，download_plan 建 client 时带上（1025 第二波 PR⑤b）
        response = client.get(url, follow_redirects=True, timeout=60)
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
        entry["error"] = errtext(exc)[:200]
    return entry


def download_plan(plan: list[dict[str, Any]], raw_version_dir: Path, rel_prefix: str, *, progress=None) -> dict[str, Any]:
    """照来源给的下载计划（`src.media_plan`）把图 / 语音 / 视频下进这个版本的 assets/，返回 manifest.json 的内容
    （docs/FORMAT.md §4）。通用：不认识任何来源的数据结构，只认任务里的 kind / role / url / stem。

    progress(stage, text, done, total)（1010，可选）：每下完一个文件报一次（插件「抓全部评论」在笔记页画进度）。"""
    assets = raw_version_dir / "assets"
    media: list[dict[str, Any]] = []
    total = len(plan) if progress else 0

    def tick() -> None:
        if progress and total:
            progress("media", f"下载图片 / 语音 {len(media)}/{total}", len(media), total)

    if progress and total:
        progress("media", f"下载图片 / 语音 0/{total}", 0, total)
    # 每条任务带自己的请求头（10-26 复审：原来整批共用第一条的头、视频丢头）；同一组头共用一个连接
    clients: dict[tuple, httpx.Client] = {}

    def client_for(t: dict[str, Any], **kw: Any) -> httpx.Client:
        h = t.get("headers") or {}
        key = tuple(sorted(h.items()))
        if key not in clients:
            clients[key] = httpx.Client(**({"headers": dict(h)} if h else {}), **kw)
        return clients[key]

    try:
        for t in plan:
            if t.get("kind") == "image":
                entry: dict[str, Any] = {"role": t["role"], "index": t.get("index")}
                if t.get("comment_id") is not None:
                    entry["comment_id"] = t["comment_id"]
                entry["original_url"] = t["url"]
                entry.update(download_image(t["url"], assets, t["stem"], client=client_for(t)))
                if entry["file"]:
                    entry["file"] = f"{rel_prefix}/assets/{entry['file']}"
                media.append(entry)
                tick()
            elif t.get("kind") == "audio":
                media.append(_download_comment_audio({"url": t["url"]}, t["comment_id"], assets, rel_prefix, client_for(t)))
                tick()
        for t in plan:
            if t.get("kind") == "video":
                from .videos import download
                vclient = None
                if t.get("headers"):   # 没给头的照旧让 videos 自己开连接（跟随跳转、90 秒）
                    vclient = httpx.Client(headers=dict(t["headers"]), follow_redirects=True, timeout=90)
                try:
                    media.append(download(t.get("payload") or {"video_url": t["url"]}, raw_version_dir, rel_prefix,
                                          **({"client": vclient} if vclient else {})))
                finally:
                    if vclient:
                        vclient.close()
                tick()
    finally:
        for c in clients.values():
            c.close()

    declared = sum(1 for m in media if m["role"] in ("note_image", "comment_image", "video_cover"))
    ok = sum(
        1
        for m in media
        if m["role"] in ("note_image", "comment_image", "video_cover")
        and m["download_status"] == "ok"
    )
    return {
        "schema_version": 1,
        # 暂存目录（.staging-…）还没有号：发布时 _retarget 填（1025 第二波 PR⑤a）
        "version": int(raw_version_dir.name[1:]) if raw_version_dir.name[1:].isdigit() else None,
        "created_at": now_iso(),
        "images_declared": declared,
        "images_ok": ok,
        "images_complete": declared == ok,
        "media": media,
    }


def download_media(source: dict[str, Any], raw_version_dir: Path, rel_prefix: str, *, progress=None) -> dict[str, Any]:
    """按 source.json 下载全部媒体（旧入口，续读复用 / 测试在用）：向这篇的来源要下载计划，再走 download_plan。"""
    from .ai_config import sync_options
    src = sources.get(source.get("source") or "")
    return download_plan(src.media_plan(source, sync_options()), raw_version_dir, rel_prefix, progress=progress)


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
    """抓取重建的 meta（字段顺序和 FORMAT.md §2 一致）。kind / 标题 / 作者 / 发布时间 / 评论齐没齐 / 附件状态 / 工具版本
    由来源给（`src.meta_fields`，1025 第二波 PR⑤b），其余通用。"""
    src = sources.get(parsed["source"])
    sid = parsed["source_id"]
    f = src.meta_fields(source)
    return {
        "schema_version": 1,
        "item_id": domain.item_id(src.name, sid),
        "source": src.name,
        "source_id": sid,
        "canonical_url": parsed["canonical_url"],
        "input_url": parsed["input_url"],
        "kind": f["kind"],
        "title": f["title"],
        "author": f["author"],
        "published_at": f["published_at"],
        "first_archived_at": first_archived,
        "last_checked_at": captured_at,
        "current_version": version,
        "versions": storage.existing_versions(src.name, sid),
        "visible_note": None,
        "images_complete": manifest["images_complete"],
        "comments_complete": f["comments_complete"],
        "attachments_status": f["attachments_status"],
        "origin": origin,
        "actor": actor,
        "ingest_kind": ingest_kind,
        "note": note,
        "tool_versions": {"link_brain": __version__, **f["tool_versions"]},
    }


# 抓取能决定的 meta 字段 / 重抓合并规则（1024 车 1 写在这里，1025 第二波 PR① 挪进 domain.py；这里留同名转发）
from .domain import FETCH_OWNED, merge_meta  # noqa: E402,F401


def _write_meta(meta_path, fetched: dict[str, Any], *, project: str | None = None) -> dict[str, Any]:
    """抓取重建的 meta 落盘：单篇锁里重读当前 meta 再合并（抓取最长 1500 秒，期间别的入口可能写过）。
    project（1020 AI 为哪个项目收的）：这次写了新版本才记，和 meta 同一次写进（1025 第二波 PR⑤c，原来 catch 入库后再单独改一次）。"""
    name = domain.clean_project(project) if project else ""

    def change(old):
        merged = merge_meta(old, fetched)
        if name:
            merged["project"] = name
        return merged

    return storage.update_json(meta_path, change, lock_name=storage.obj_lock_name(fetched["item_id"]), missing_ok=True)


def _touch_checked(meta_path, item_id: str, captured_at: str) -> dict[str, Any]:
    return storage.update_json(meta_path, lambda m: m.update(last_checked_at=captured_at),
                               lock_name=storage.obj_lock_name(item_id))


from .comment_fill import FILL_BUDGET_S  # noqa: E402 - 续读一次给读取组件的评论预算（秒），规则都在 comment_fill
FILL_MAX_ATTEMPTS = 3  # 1009 起不再按总次数封顶（连着 comment_fill.NO_PROGRESS_LIMIT 次没进展才停）；留着给旧调用方
FILL_GAP_HOURS = 20    # 1009 起改成 comment_fill.FILL_GAP_MIN（45 分钟）；留着给旧调用方

# 抓详情（重试 / 楼层参数）1025 第二波 PR⑤b 挪进小红书 adapter；这里留同名转发给旧调用方和测试
from .adapters.xiaohongshu import (  # noqa: E402,F401
    SERVICE_BACKOFF, SERVICE_RETRIES, DOWNLOAD_HEADERS, _detail_kwargs, _fetch_with_retry)


# 评论续读那一族 1025 第二波 PR⑤b 挪进小红书 comment_fill；这里留同名转发
from .comment_fill import (  # noqa: E402,F401
    _fillable, _log_comment_load, _main_gap_reason, _merge_fill, _reuse_media, fill_targets)


# ---- 1025 第二波 PR⑤a：写新版本走暂存 + 单篇锁里提交；崩一半的孤儿版本收编 ----------------------------

def _retarget(manifest: dict[str, Any], stg: "storage.Staging", version: int) -> dict[str, Any]:
    """暂存里写的 manifest：文件路径前缀 raw/.staging-…/ 换成 raw/vNNNN/，填 version。引用旧版本的路径（续读复用）不动。
    传进来的是副本（publish 撞号重取时会再调一次，用原件重算）。"""
    old, new = f"raw/{stg.path.name}/", f"raw/{storage.version_name(version)}/"
    for m in manifest.get("media") or []:
        f = m.get("file")
        if isinstance(f, str) and f.startswith(old):
            m["file"] = new + f[len(old):]
    manifest["version"] = version
    return manifest


class _Discarded(Exception):
    """提交前在锁里复查发现不该发布（抓的时候被删 / 别的入口已经存好同一篇 / 内容没变）。reason 给调用方分流。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _commit_version(conn, parsed: dict[str, Any], stg: "storage.Staging", manifest0: dict[str, Any], *,
                    source: dict[str, Any], sha: str, captured_at: str, expect_existing: bool, check_sha: bool,
                    meta_kw: dict[str, Any], log) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """提交点：单篇锁里复查 → 发布暂存 → 写 meta → 写索引。返回 (version, manifest, meta)；不该发布抛 _Discarded。

    锁只包住这一小段（抓取 / 下图最长二十多分钟都在锁外、写进只有自己看得见的暂存目录），所以删除 / 改标签不会被长抓取卡住。
    - 抓的时候被删了（墓碑）→ 不发布（_Discarded("trashed")）。
    - expect_existing=False（当新帖抓的）但现在已在库 → 别的入口刚存好同一篇，不再出第二个版本（"raced"）。
    - check_sha → 和库里最新版本内容一样就不发布（"unchanged"；refresh 或并发重抓）。
    """
    src = sources.get(parsed["source"])
    sid = parsed["source_id"]
    item_id = domain.item_id(src.name, sid)
    with storage.file_lock(storage.obj_lock_name(item_id), wait_s=120, owner="ingest"):
        probe = storage.probe_object(conn, src.name, sid)
        lk = domain.lookup(probe)
        if lk.state is domain.Presence.DELETED:
            log("提交前复查：抓的时候被删了，不发布")
            raise _Discarded("trashed")
        if not expect_existing and lk.state is domain.Presence.IN_LIBRARY and not lk.needs_reindex:
            log("提交前复查：别的入口刚存好这一篇，不再写第二个版本")
            raise _Discarded("raced")
        if check_sha and probe.in_index and index_mod.latest_source_sha256(conn, item_id) == sha:
            log("提交前复查：和库里最新版本内容一样，不写新版本")
            raise _Discarded("unchanged")
        out: dict[str, Any] = {}

        def finalize(v: int) -> dict[str, Any]:
            out["manifest"] = _retarget(copy.deepcopy(manifest0), stg, v)
            return out["manifest"]

        version = stg.publish(finalize)
        manifest = out["manifest"]
        raw_dir = storage.raw_dir(src.name, sid, version)
        log(f"RAW → {raw_dir}")
        kw = dict(meta_kw)
        project = kw.pop("project", None)
        meta = _build_meta(parsed=parsed, source=source, manifest=manifest, version=version, captured_at=captured_at,
                           first_archived=captured_at, **kw)
        # 抓取管不着的字段（project、visible_note_pinned、favorited_by、首次的 ingest_kind…）按当前 meta 保留（同一把锁，可重入）
        meta = _write_meta(storage.object_dir(src.name, sid) / "meta.json", meta, project=project)
        index_mod.upsert_object(conn, meta, source)
        index_mod.add_source_version(conn, item_id=meta["item_id"], version=version, raw_dir=raw_dir,
                                     captured_at=captured_at, adapter=src.version, input_url=parsed["input_url"],
                                     input_kind=parsed["input_kind"], source_sha256=sha)
    return version, manifest, meta


def _adopt(conn, parsed: dict[str, Any], probe, *, origin: str, actor: str, ingest_kind: str, note: str | None,
           log, project: str | None = None) -> dict[str, Any]:
    """磁盘上已经有完整版本、但索引里没有（上次崩在「发布之后、写 meta / 索引之前」，或 index.db 重建丢了行）：
    不联网，直接用磁盘上最新的完整版本补 meta / 索引。返回 {meta, source, manifest, version, raw_dir}。"""
    src = sources.get(parsed["source"])
    sid = parsed["source_id"]
    item_id = domain.item_id(src.name, sid)
    meta_path = storage.object_dir(src.name, sid) / "meta.json"
    with storage.file_lock(storage.obj_lock_name(item_id), wait_s=120, owner="ingest adopt"):
        meta = storage.read_json(meta_path) if meta_path.is_file() else None
        versions = storage.existing_versions(src.name, sid)       # 调用方保证至少一个完整版本
        version = int(meta["current_version"]) if meta and int(meta.get("current_version") or 0) in versions else versions[-1]
        if meta is not None and (int(meta.get("current_version") or 0) != version or meta.get("versions") != versions):
            log(f"meta 指向的版本不完整 / 版本表过时：改指 {storage.version_name(version)}")
            meta = storage.update_json(meta_path, lambda m: m.update(current_version=version, versions=versions),
                                       lock_name=storage.obj_lock_name(item_id))
        raw_dir = storage.raw_dir(src.name, sid, version)
        source = storage.read_json(raw_dir / "source.json")
        manifest = storage.read_json(raw_dir / "manifest.json")
        if meta is None:
            captured = (source.get("capture") or {}).get("captured_at") or now_iso()
            log(f"收编孤儿版本 {storage.version_name(version)}（上次崩在写 meta 之前），不重抓")
            meta = _write_meta(meta_path, _build_meta(parsed=parsed, source=source, manifest=manifest, version=version,
                                                      captured_at=captured, origin=origin, actor=actor,
                                                      ingest_kind=ingest_kind, note=note, first_archived=captured),
                               project=project)
        else:
            log("meta 在、索引里没有：按磁盘补索引，不重抓")   # 以前入过库（hit）：不覆盖 project
        index_mod.upsert_object(conn, meta, source)
        index_mod.add_source_version(conn, item_id=item_id, version=version, raw_dir=raw_dir,
                                     captured_at=(source.get("capture") or {}).get("captured_at") or meta["last_checked_at"],
                                     adapter=src.version, input_url=parsed["input_url"],
                                     input_kind=parsed["input_kind"], source_sha256=src.fingerprint(source))
    return {"meta": meta, "source": source, "manifest": manifest, "version": version, "raw_dir": raw_dir}


def _discarded_summary(conn, parsed: dict[str, Any], reason: str, source: dict[str, Any], log) -> dict[str, Any]:
    """_commit_version 决定不发布时给调用方的摘要：被删 → trashed；别人刚存好 / 内容没变 → 当「已在库」。"""
    src = sources.get(parsed["source"])
    sid = parsed["source_id"]
    if reason == "trashed":
        t = index_mod.get_tombstone(conn, src.name, sid)
        return {"status": "trashed", "item_id": t["item_id"] if t else domain.item_id(src.name, sid), "note_id": sid,
                "title": t["title"] if t else None, "exit_code": EXIT_OK}
    meta_path = storage.object_dir(src.name, sid) / "meta.json"
    meta = storage.update_json(meta_path, lambda m: m.update(last_checked_at=now_iso()),
                               lock_name=storage.obj_lock_name(domain.item_id(src.name, sid))) if reason == "unchanged" \
        else storage.read_json(meta_path)
    return {"hit": reason == "raced", "refreshed_unchanged": reason == "unchanged", "item_id": meta["item_id"],
            "note_id": sid, "kind": meta.get("kind"),
            "raw_dir": storage.raw_dir(src.name, sid, meta["current_version"]), "version": meta["current_version"],
            "manifest": None, "failed": [], **_comment_counts(source),
            "comments_complete": meta.get("comments_complete"), "attachments_status": meta.get("attachments_status"),
            "exit_code": EXIT_OK}


def _comment_counts(source: dict[str, Any]) -> dict[str, int]:
    comments = source.get("comments") or []
    return {"comments": len(comments), "sub_comments": sum(len(c.get("sub_comments") or []) for c in comments)}


def after_commit(source: str, source_id: str, *, fresh: bool, reason: str = "导入") -> str | None:
    """⑨ 入库收尾（提交之后；1025 第二波 PR⑤c，取代 catch / 收藏同步各写各的那几份）：
    新写了版本 → 标识图 / 概要待办（enrich 夜跑补，不现场花钱）+ 本地渲染（不调模型）；已在库的只在可见 md 丢了时补渲染。
    失败不回退（都能从 meta + RAW 重算），返回给人看的一行错误，没出错返回 None。"""
    from . import enrich as enrich_mod, render as render_mod
    try:
        if fresh:
            enrich_mod.mark_pending(source, source_id, reason=reason)
        meta_path = storage.object_dir(source, source_id) / "meta.json"
        rel = storage.read_json(meta_path).get("visible_note") if meta_path.exists() else None
        if fresh or not (rel and (storage.vault_root() / rel).exists()):
            render_mod.render_object(source, source_id, verbose=False, llm=False)
    except Exception as exc:  # noqa: BLE001 - 渲染失败不该吞掉已经落盘的归档
        return f"渲染失败: {errtext(exc)}"
    return None


def recognize(target: str, parsed: dict[str, Any] | None = None):
    """① 认来源 + 解析（1025 第二波 PR⑤b）：返回 (来源模块, parsed)。parsed 里一定有 source / source_id。

    catch 已经解析过（为了先判要不要拿账号锁）就直接用，不再跟一次短链。认不出链接是哪家的：只有一个来源时交给它解析
    （它自己报「不是我的链接」），多个来源时报错。"""
    if parsed is not None and parsed.get("source"):
        return sources.get(parsed["source"]), parsed
    found = sources.detect(target)
    if found:
        src = found[0][0]
    elif len(sources.names()) == 1:
        src = sources.get(sources.names()[0])
    else:
        raise sources.SourceError(f"认不出这是哪个网站的链接：{target[:80]}")
    return src, (parsed if parsed is not None else src.parse(target))


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
    fill: bool = False,
    fill_budget_s: int | None = None,
    progress=None,
    expand_resume: list[str] | None = None,
    floors_resume: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """抓一条链接并落一份不可变 RAW。返回摘要 dict（含 exit_code）。

    1025 第二波 PR⑤b：这里只认来源接口（`link_brain.sources`）——认来源 / 解析 / 抓 / 规范化 / 指纹 / 下载计划 / meta 里来源那几项
    都问 `src`，不认识任何一家的数据结构。expand_floors / expand_resume / floors_resume 经 FetchOptions.extra 转给来源；
    fill=True（评论续读，要求已归档）要来源有 comments_fill 能力，整段交给 `src.fill`。

    progress(stage, text, done=None, total=None)（1010，可选）：开页读评论区 / 下图 / 语音各报一次进度（插件「抓全部评论」用）。

    去重：`(source, source_id)` 命中索引且非 `--refresh` → 直接返回已有对象，不联网不下载。
    `--refresh`：重新抓取，规范化比对与最新版本一致就不写新 RAW，只更新 `last_checked_at`；
    有变化才写新版本（`raw/v0001` 字节绝不动）。
    """

    def log(message: str) -> None:
        if verbose:
            print(f"[ingest] {message}", file=sys.stderr)

    src, parsed = recognize(target, parsed)
    if not parsed.get("source"):
        parsed = {**parsed, "source": src.name, "source_id": parsed.get("source_id") or parsed.get("note_id")}
    sid = parsed["source_id"]
    log(f"source={src.name} input_kind={parsed['input_kind']} source_id={sid}")

    conn = index_mod.connect()
    created_at = now_iso()
    rel = dict(origin=origin, actor=actor, ingest_kind=ingest_kind, note=note, created_at=created_at)
    try:
        probe = storage.probe_object(conn, src.name, sid)
        lk = domain.lookup(probe)
        if lk.state is domain.Presence.DELETED:
            tombstone = index_mod.get_tombstone(conn, src.name, sid)
            log('已删除，跳过')
            return {'status': 'trashed', 'item_id': tombstone['item_id'] if tombstone else domain.item_id(src.name, sid),
                    'note_id': sid, 'title': tombstone['title'] if tombstone else None, 'exit_code': EXIT_OK}
        if (lk.state is domain.Presence.ORPHAN or lk.needs_reindex) and probe.complete_versions:
            # 1025 第二波 PR⑤a：上次崩在发布之后 / 索引丢了 → 用磁盘上的完整版本补上，不联网重抓
            got = _adopt(conn, parsed, probe, origin=origin, actor=actor, ingest_kind=ingest_kind, note=note, log=log,
                         project=project)
            index_mod.add_relation(conn, item_id=got["meta"]["item_id"], **rel)
            if not refresh and not fill:
                doc = got["source"]
                # 孤儿版本（从没写成 meta）= 对她来说是新帖：按新帖渲染 / 排识图；meta 在只是索引丢了 = 以前入过库，按已在库
                orphan = lk.state is domain.Presence.ORPHAN
                return {"hit": not orphan, "refreshed_unchanged": False, "adopted": True, "item_id": got["meta"]["item_id"],
                        "note_id": sid, "kind": got["meta"]["kind"], "raw_dir": got["raw_dir"],
                        "version": got["version"], "manifest": got["manifest"], "failed": [],
                        **_comment_counts(doc),
                        "comments_complete": (doc.get("capture") or {}).get("comments_complete"),
                        "attachments_status": got["meta"].get("attachments_status"), "exit_code": EXIT_OK}
        existing = index_mod.find_object(conn, src.name, sid)

        if existing is not None and not refresh:
            log("index HIT，不联网，不下载")
            item_id = existing["item_id"]
            index_mod.add_relation(conn, item_id=item_id, **rel)
            meta = storage.read_json(storage.object_dir(src.name, sid) / "meta.json")
            return {
                "hit": True,
                "item_id": item_id,
                "note_id": sid,
                "kind": existing["kind"],
                "raw_dir": storage.raw_dir(src.name, sid, meta["current_version"]),
                "version": meta["current_version"],
                "manifest": None,
                "failed": [],
                "comments": None,
                "sub_comments": None,
                "comments_complete": existing["comments_complete"],
                "attachments_status": existing["attachments_status"],
                "exit_code": EXIT_OK,
            }

        if fill and existing is not None and "comments_fill" in src.capabilities:
            return src.fill(parsed, conn, existing, log=log, progress=progress, comment_floors=comment_floors,
                            budget_left=budget_left, expand_floors=expand_floors, fill_budget_s=fill_budget_s,
                            expand_resume=expand_resume, floors_resume=floors_resume, origin=origin, actor=actor,
                            ingest_kind=ingest_kind, note=note, created_at=created_at)

        # ③ 抓 ④ 规范化
        extra = {k: v for k, v in (("expand_floors", expand_floors), ("expand_resume", expand_resume),
                                   ("floors_resume", floors_resume)) if v}
        fetched = src.fetch(parsed, sources.FetchOptions(refresh=refresh, comment_floors=comment_floors,
                                                         budget_left=budget_left, progress=progress, log=log, extra=extra))
        captured_at = now_iso()
        doc = src.normalize(fetched, parsed, captured_at=captured_at)
        new_sha = src.fingerprint(doc)
        meta_path = storage.object_dir(src.name, sid) / "meta.json"

        if refresh and existing is not None:
            prior_sha = index_mod.latest_source_sha256(conn, existing["item_id"])
            if prior_sha is not None and prior_sha == new_sha:
                log("refresh：规范化比对无变化，不写新 RAW 版本，只更新 last_checked_at")
                meta = _touch_checked(meta_path, existing["item_id"], captured_at)
                index_mod.upsert_object(conn, meta, doc)
                index_mod.add_relation(conn, item_id=meta["item_id"], **rel)
                return {
                    "hit": False,
                    "refreshed_unchanged": True,
                    "item_id": meta["item_id"],
                    "note_id": sid,
                    "kind": meta["kind"],
                    "raw_dir": storage.raw_dir(src.name, sid, meta["current_version"]),
                    "version": meta["current_version"],
                    "manifest": None,
                    "failed": [],
                    **_comment_counts(doc),
                    "comments_complete": (doc.get("capture") or {}).get("comments_complete"),
                    "attachments_status": meta["attachments_status"],
                    "exit_code": EXIT_OK,
                }
            log("refresh：规范化比对有变化，写新 RAW 版本")

        # ⑤ 暂存（RAW 全写进 raw/.staging-…/）⑥⑦ 锁里复查 + 发布 + 提交（_commit_version）⑧ 索引
        meta_kw = dict(origin=origin, actor=actor, ingest_kind=ingest_kind, note=note, project=project)
        from .ai_config import sync_options
        with storage.stage_version(src.name, sid) as stg:
            for name, payload in fetched.raw_files.items():   # 来源的原样返回（小红书：mcp_raw.json + web_raw.json）
                storage.write_json(stg.path / name, payload)
            storage.write_json(stg.path / "source.json", doc)
            manifest0 = download_plan(src.media_plan(doc, sync_options()), stg.path, f"raw/{stg.path.name}",
                                      progress=progress)
            try:
                version, manifest, meta = _commit_version(
                    conn, parsed, stg, manifest0, source=doc, sha=new_sha, captured_at=captured_at,
                    expect_existing=existing is not None, check_sha=existing is not None or refresh,
                    meta_kw=meta_kw, log=log)
            except _Discarded as d:
                out = _discarded_summary(conn, parsed, d.reason, doc, log)
                if d.reason != "trashed":
                    # 和原来「refresh 无变化」那支一样：这次来源的关联照记、索引的 last_checked_at 跟上
                    if d.reason == "unchanged":
                        index_mod.upsert_object(conn, storage.read_json(meta_path), doc)
                    index_mod.add_relation(conn, item_id=out["item_id"], **rel)
                return out
        raw_dir = storage.raw_dir(src.name, sid, version)
        index_mod.add_relation(conn, item_id=meta["item_id"], **rel)

        failed = [m for m in manifest["media"] if m["download_status"] == "failed"]
        return {
            "hit": False,
            "refreshed_unchanged": False,
            "item_id": meta["item_id"],
            "note_id": sid,
            "kind": meta["kind"],
            "raw_dir": raw_dir,
            "version": version,
            "manifest": manifest,
            "failed": failed,
            **_comment_counts(doc),
            "comments_complete": (doc.get("capture") or {}).get("comments_complete"),
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
    except sources.NeedsHuman as exc:
        # 号出事 / 服务出事：单独一个退出码 + 登记问题（账号类 NEEDS_HUMAN 推一次；服务类 TRANSIENT 只记），
        # 别让批量脚本闷头把剩下的全刷成失败
        service = isinstance(exc, xhs.ServiceDownError)
        problems.report_blocked("ingest", getattr(exc, "code", "") or "", f"导入停了：{exc}", service=service)
        print(f"归档中止（{'服务' if service else '账号/风控'}）: {exc}", file=sys.stderr)
        return EXIT_NEEDS_HUMAN
    except sources.SourceError as exc:
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

    # ingest 落盘成功（含缺内容 gate 的情况）后自动 render，不阻断 ingest 本身的退出码。
    # 1024：不现场识图（花钱、慢）——这篇标成 enrich 待办，识图 / 概要由 enrich（夜跑 / 自愈轮）补
    if summary.get("item_id"):
        source_key, source_id = xhs.SOURCE, summary["note_id"]
        from . import enrich as enrich_mod
        enrich_mod.mark_pending(source_key, source_id, reason="导入")
        try:
            from . import render as render_mod

            render_mod.render_item(source_key, source_id, verbose=getattr(args, "verbose", False), vision=False)
        except Exception as exc:  # noqa: BLE001 - 渲染失败不应回退 ingest 的退出码
            print(f"[ingest] render 失败（不影响归档）: {errtext(exc)}", file=sys.stderr)

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


def fetch_comments(target: str, *, floors: int | str = "all", verbose: bool = False, fill: bool = False,
                   progress=None) -> dict[str, Any]:
    """手动抓一篇的评论区（Owner 0926：超过 50 楼 / 全量只在指定笔记上手动抓，不进每晚同步）。

    target 可以是 item_id（xhs-<note_id>）或链接；用归档里最新的 xsec_token 重抓（--refresh 语义，
    RAW 只在内容有变化时出新版本），含楼中楼、评论图片、语音评论，完了重新渲染可见页。
    progress（1010）：见 progress_emitter——读评论区 / 合并 / 下图 / 写进笔记各报一次。
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
    from . import comment_fill
    if fill:
        if target.startswith("http"):
            raise FileNotFoundError("续读要给已归档的 item_id")
        # 1009：按设置里的楼数现算缺口（老笔记没有 comment_load 也认），她点的照跑（不看 45 分钟间隔 / 已放弃）
        out = comment_fill.fill_one(row["item_id"], verbose=verbose, manual=True)
        out.setdefault("comments", None)
        out.setdefault("sub_comments", None)
        out.setdefault("comments_complete", None)
        return out
    if not target.startswith("http") and floors == "all":
        # 1026（她：「抓全部评论……有一些它会不齐」）：整篇抓过、还有没齐的 → 这一下只接着补（没翻到底从停下那页往后翻，
        # 翻到底了只展开缺回复的楼，带游标从存下的最后一条往后拉），不再从第 1 楼整篇重来；结果照实报「已抓几楼 / 翻没翻到底 / 还缺什么」
        state0 = comment_fill.load_state(row["source"], row["source_id"])
        _, source0 = comment_fill.current_source(row["source"], row["source_id"])
        if comment_fill.manual_plan(source0, state0) == "resume":
            if progress:
                progress("start", "这篇整篇抓过：只接着补没齐的（没翻到底就从停下那页往后翻，翻到底了只展开缺回复的楼）")
            try:
                out = comment_fill.fill_one(row["item_id"], floors=comment_fill.FLOOR_ALL, verbose=verbose, manual=True,
                                            progress=progress)
            except Exception as exc:
                _record_full_quietly(row, errtext(exc))
                raise
            if out.get("trashed"):
                return {**out, "status": "trashed"}
            rep = _record_full_quietly(row)
            if progress:
                progress("render", "写进笔记、刷新这一页")
            catch_mod._ensure_rendered(xhs.SOURCE, row["source_id"], force=True, extract=False)
            _, source1 = comment_fill.current_source(row["source"], row["source_id"])
            return {**out, "resumed": True, "report": rep, "note_id": row["source_id"],
                    "comments": len(source1.get("comments") or []),
                    "sub_comments": sum(len(c.get("sub_comments") or []) for c in source1.get("comments") or []),
                    "comments_complete": (source1.get("capture") or {}).get("comments_complete")}
    if not target.startswith("http"):
        # 1009：手动「现在抓全部评论」也并集合并（调小楼数 / 原帖删了评论都不丢已存的）
        from . import restricted
        sid = row["source_id"]

        def attempt(token: str) -> dict[str, Any]:
            return ingest_url(f"https://www.xiaohongshu.com/explore/{sid}?xsec_token={token}", refresh=True,
                              comment_floors=floors, verbose=verbose, fill=True, fill_budget_s=None, progress=progress)

        old_token = restricted.best_token(sid, note.get("xsec_token") or "")
        try:
            try:
                summary = attempt(old_token)
            except Exception as exc:
                if floors == "all" and not isinstance(exc, sources.ItemRestricted):
                    _record_full_quietly(row, errtext(exc))   # 1026：没成也记一笔，评论区顶上照实写原因、下次接着
                raise
        except sources.ItemRestricted as exc:
            # 1011：这篇在网页版要验证才能看：今天没搜过就用标题搜一次新口令、歇一会儿再开一次；还不行就如实说、给「打开验证」
            opened, summary = restricted.retry_with_fresh_token(
                sid, title=note.get("title"), old_token=old_token, attempt=attempt,
                restricted_exc=(xhs.NoteRestrictedError,), item_id=row["item_id"], via="comments", detail=str(exc)[:200],
                progress=progress)
            if not opened:
                try:
                    catch_mod._ensure_rendered(xhs.SOURCE, sid, force=True, extract=False)
                except Exception as rexc:  # noqa: BLE001 - 笔记页那一行下次渲染会跟上
                    print(f"[comments] 重渲染没成：{type(rexc).__name__}: {rexc}", file=sys.stderr)
                raise xhs.NoteRestrictedError(restricted.TEXT) from exc
        else:
            restricted.clear(sid, item_id=row["item_id"], why="手动抓评论打开了这篇")
        if summary.get("status") == "trashed":
            return summary                      # 1025 PR⑤a：抓的时候被删了，没发布，也不重渲染
        state = comment_fill.load_state(row["source"], row["source_id"])
        _, source2 = comment_fill.current_source(row["source"], row["source_id"])
        sc = comment_fill.scope(source2, comment_fill.floor_target(), state)
        if not sc["missing"] and state.get("stuck"):
            from . import problems as problems_mod
            comment_fill._settle(row["source"], row["source_id"], state, row["item_id"], problems_mod)
        if floors == "all":
            summary = {**summary, "report": _record_full_quietly(row)}
    else:
        summary = ingest_url(url, refresh=True, comment_floors=floors, verbose=verbose, progress=progress)
    if summary.get("status") == "trashed":
        return summary
    if progress:
        progress("render", "写进笔记、刷新这一页")
    catch_mod._ensure_rendered(xhs.SOURCE, summary["note_id"], force=True, extract=False)
    return summary


def _record_full_quietly(row, error: str = "") -> dict[str, Any] | None:
    """手动抓全部评论的结果记进续读状态（comment_fill.record_full）；记不上不挡抓评论本身。"""
    from . import comment_fill
    try:
        return comment_fill.record_full(row["source"], row["source_id"], error=error)
    except Exception as exc:  # noqa: BLE001
        print(f"[comments] 抓取结果没记上：{errtext(exc)}", file=sys.stderr)
        return None


# 1010：手动「抓全部评论」的进度事件（--progress）。stdout 一行一个 JSON（和 setup run 同一写法），最后一行照旧是结果：
#   {"type":"progress","stage":"start|lock|read|merge|media|render","text":"…"[, "done":n, "total":m, "unit":"个"]}
# 插件（note-actions.js）在笔记页评论区顶上画一行进度 + 细条，底部状态栏同步显示；只报真发生的那一步，不编进度。
LOCK_OWNER_TEXT = {"comments-fill": "后台补评论", "sync-favorites": "同步收藏", "ingest": "导入", "comments": "另一次抓评论",
                   "attachments": "补附件", "attachments --recheck": "补查附件", "login-status": "查登录", "catch": "导入"}


def owner_text(holder: dict[str, Any] | None) -> str:
    owner = str((holder or {}).get("owner") or "")
    return LOCK_OWNER_TEXT.get(owner) or owner or "别的任务"


def progress_emitter(args):
    """`comments <id> --progress`：返回 emit(stage, text, done=None, total=None)；没开就 None（别的入口一字不变）。"""
    if not getattr(args, "progress", False):
        return None
    from .setup.common import stdout_emit

    def emit(stage: str, text: str, done: int | None = None, total: int | None = None) -> None:
        event: dict[str, Any] = {"type": "progress", "stage": stage, "text": text}
        if done is not None and total is not None:
            event.update(done=int(done), total=int(total), unit="个")
        try:
            stdout_emit(event)
        except (OSError, ValueError):
            pass  # 管道断了（插件那头停了）：照样把活干完，结果靠退出码
    return emit


def lock_wait_reporter(emit, wait_min: float | int | None = None):
    """号被别的任务占着、要等的时候报一次：「后台补评论正在用号，它这一篇补完就轮到这里（最多等 N 分钟）」。"""
    if emit is None:
        return None

    def on_wait(holder: dict[str, Any] | None, left: float) -> None:
        who = owner_text(holder)
        tail = "它这一篇补完就轮到这里" if (holder or {}).get("owner") == "comments-fill" else "它用完就轮到这里"
        emit("lock", f"等号：{who}正在用小红书号，{tail}（最多等 {max(1, round(left / 60))} 分钟）")
    return on_wait


def pending_fills(*, limit: int = 0, now: datetime | None = None) -> list[tuple[str, str, dict[str, Any]]]:
    """还有缺口、现在就能续的篇：[(source, source_id, 缺口摘要)]（1009 起按设置楼数现算，见 comment_fill.survey）。"""
    from . import comment_fill
    sv = comment_fill.survey(now=now)
    out = [(e["source"], e["source_id"], {"replies_missing": e["missing"], "mode": e["mode"], "targets": e["targets"]})
           for e in sv["ready"]]
    return out[:limit] if limit else out


def run_fill_pending(args) -> int:
    """`comments --fill-pending [--limit N] [--budget-min M] [--until-done] [--then-background]`（见 comment_fill.run）。"""
    from . import comment_fill
    return comment_fill.run(args)


def run_comments(args) -> int:
    from .read import dump_json
    if getattr(args, "fill_status", False):
        from . import comment_fill
        dump_json(comment_fill.status_payload())
        return EXIT_OK
    if getattr(args, "fill_pending", False):
        if getattr(args, "detach", False):
            from . import comment_fill
            from .read import outcome
            r = comment_fill.spawn_worker()
            dump_json(outcome(r, ok=bool(r.get("ok")), message=r.get("message") or ""))
            return EXIT_OK if r.get("ok") else EXIT_ERROR
        return run_fill_pending(args)
    if not args.target:
        print("要给 item_id 或链接（或用 --fill-pending）", file=sys.stderr)
        return EXIT_ERROR
    try:
        floors = args.floors if args.floors == "all" else int(args.floors)
        fill = getattr(args, "fill", False)
        summary = fetch_comments(args.target, floors=floors, verbose=getattr(args, "verbose", False),
                                 fill=fill, progress=None if fill else progress_emitter(args))
    except sources.NeedsHuman as exc:
        print(f"评论抓取中止（账号或服务要处理）: {exc}", file=sys.stderr)
        dump_json({'ok': False, 'code': 'NEEDS_HUMAN', 'message': f'评论没抓：{exc}'})
        return EXIT_NEEDS_HUMAN
    except sources.ItemRestricted as exc:
        # 1011：只是这一篇（网页版要验证才能看）：笔记页评论区顶上已经有「打开验证」
        print(f"评论没抓：{exc}", file=sys.stderr)
        dump_json({'ok': False, 'code': 'NOTE_RESTRICTED', 'item_id': args.target,
                   'message': '评论没抓：这篇在小红书网页版要验证才能看——点评论区顶上的「打开验证」过一下，过完自动补抓'})
        return EXIT_ERROR
    except (sources.SourceError, FileNotFoundError) as exc:
        print(f"评论抓取失败: {exc}", file=sys.stderr)
        dump_json({'ok': False, 'code': '', 'message': f'评论没抓：{exc}'})
        return EXIT_ERROR
    if summary.get("restricted"):
        # 1011：续读（--fill，问题面板「再试一次」）撞到网页版限制：如实说，不说「评论已更新」
        dump_json({'ok': False, 'code': 'NOTE_RESTRICTED', 'item_id': summary.get('item_id') or args.target,
                   'message': '评论没抓：这篇在小红书网页版要验证才能看——点评论区顶上的「打开验证」过一下，过完自动补抓'})
        return EXIT_ERROR
    out = {k: summary.get(k) for k in ("item_id", "note_id", "comments", "sub_comments", "comments_complete", "version",
                                       "refreshed_unchanged", "filled", "reason", "report", "resumed") if k in summary}
    message = (f'评论没有变化（{summary.get("comments", 0)} 条）' if summary.get('refreshed_unchanged') else
               f'评论已更新：{summary.get("comments", 0)} 条一级、{summary.get("sub_comments", 0)} 条回复')
    if summary.get('comments_complete') is False:
        message += '；还有没读全的楼，夜里接着读'
    report = summary.get("report")
    if isinstance(report, dict) and report.get("text"):
        # 1026：手动抓全部评论——照实说抓到哪了（已抓楼数 / 翻没翻到最后一页 / 还缺什么、为什么），还有没齐的告诉她再点能接着补
        head = ("评论没有变化" if summary.get('refreshed_unchanged') else
                "接着补抓完了" if summary.get("resumed") else "评论已更新")
        message = f'{head}：{report["text"]}' + ('；再点「接着补抓」从停下的地方接着来' if report.get("resumable") else '')
    dump_json({**out, 'ok': True, 'code': '', 'message': message})
    return 0
