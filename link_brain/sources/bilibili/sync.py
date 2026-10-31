"""B 站收藏夹同步（阶段二批次 B 的最短路径，1029 作者：「今晚按收藏夹名当专辑都下载同步了吧；超过 1 小时的只放链接告诉我是啥，之后让我选」）。

流程：登录态 → 列自己全部收藏夹（含私密）→ 逐个收藏夹扫描（favorites.sync_folder：快照 + 关系表）→ 跨收藏夹按 BV 去重 →
分流：失效 / 非视频 / 超过 5 P 的多 P / 超过时长上限 → **只记清单不下载**（1031 起 ≤5 P 的多 P 拆成每 P 一条下）；其余逐条走阶段一的单视频入库（ingest.ingest_url，ingest_kind=favorite）
→ 收藏夹名经 note_albums 成目录里的「专辑」→ 写 `_archive/bilibili-sync/last-sync.json` 和可见的待选清单 `Web/Bilibili/B站待选清单.md`。

不做：取消收藏的处理（关系表已记 active，meta 不动）、定时（批次 C）。
每条视频单独 try；登录失效 / 风控 / 缺依赖 → 整批停下如实报；磁盘余量低于阈值 → 停。再跑一次只补没入库的（索引命中即 HIT）。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ... import storage
from ...errtext import errtext
from .. import AccountBlocked, NeedsHuman, SourceError
from . import CANONICAL_FMT, favorites, login
from . import name as SOURCE

MAX_DURATION_S = 3600
INGEST_KIND = "favorite"   # 收藏同步进来的（第一次怎么进来的；是不是收藏由 domain 判）
GAP_S = 5.0
MIN_FREE_GB = 10.0
FAIL_STREAK = 5          # 连着这么多条失败 → 多半是风控 / 断网：歇 PAUSE_S 再接着
PAUSE_S = 600.0
MAX_PAUSES = 3           # 歇过这么多次还连败 → 停下如实报，别整夜撞接口
RESCAN_HOURS = 6.0       # 收藏夹的完整快照不到这么久就直接复用，不再扫（1029 实测：71 个收藏夹连扫两遍就 412）
FOLDER_GAP_S = 3.0       # 两个收藏夹之间歇一下；翻页间隔见 PAGE_GAP_S
PAGE_GAP_S = 2.0
PENDING_NOTE = "B站待选清单.md"
LAST_SYNC = "last-sync.json"
FOLDER_LIST = "folder-list.json"   # 1031：上次列到的全部收藏夹（含被关掉的），挑选页不连网就靠它列收藏夹
MULTI_P_AUTO = 5         # 1031 作者：多 P 不超过这么多 P 的自动拆开、一个 P 一条下；更多的进挑选页，用户勾了才下
WORKERS_MAX = 8          # 1031 作者：同时下几路放到 8（撞 412/429 照旧自动退回一路）
# 1031：停下来时给用户的下一步（设置页直接显示 message；码是 CONVENTIONS §2 的细分码，裸写，和原来的 NOT_LOGGED_IN 一样）
HINTS = {
    "NOT_LOGGED_IN": "在设置页「账号登录 → B 站」点「扫码登录」重新扫一次，再点「立即同步」（已经下好的不会重下）",
    "MISSING_DEPENDENCY": ("yt-dlp 要装进 LWA 用的那个 Python：在程序目录运行 pip install -e .（.venv 是 uv 建的就用 uv pip install -e .）；"
                           "ffmpeg 要另装并加进 PATH。装好再点「立即同步」，从没下的接着下"),
    "HTTP_429": "B 站限流 / 风控了：先停一停（建议过 1 小时），并行路数调成 1 再同步；已经下好的不会重下",
    "NETWORK": "网络不通或 B 站接口没响应，稍后再试",
    "DISK_LOW": "磁盘快满了：腾出空间后再点「立即同步」，会从没下的接着下",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _hms(sec: Any) -> str:
    try:
        s = int(sec or 0)
    except (TypeError, ValueError):
        return "?"
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _gb(n: Any) -> str:
    try:
        b = float(n or 0)
    except (TypeError, ValueError):
        return "?"
    return f"{b / (1 << 30):.1f} GB" if b >= (1 << 30) else f"{b / (1 << 20):.0f} MB"


def _dur(sec: Any) -> str:
    """耗时给人看：3 小时 20 分 / 45 分钟 / 不到 1 分钟。"""
    try:
        m = int(round(float(sec or 0) / 60))
    except (TypeError, ValueError):
        return "?"
    if m < 1:
        return "不到 1 分钟"
    h, m = divmod(m, 60)
    return (f"{h} 小时" + (f" {m} 分" if m else "")) if h else f"{m} 分钟"


def _free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(str(path)).free / (1024 ** 3)
    except OSError:
        return float("inf")


# ---- 计划 -----------------------------------------------------------------------------------------------------------

def plan(snaps: list[dict[str, Any]], *, max_duration_s: int = MAX_DURATION_S, allow: set[str] | None = None,
         deny: set[str] | None = None, in_library: Callable[[str], bool] = lambda bvid: False) -> dict[str, Any]:
    """多个收藏夹的快照 → 按 BV 去重后的分流。每条 {bvid, title, upper, duration, page_count, folders[], fav_time, url, reason}。

    - download：正常单 P、时长 ≤ 上限（或在 allow 里）、还没入库；
    - hit：已在库（只补关系，不下载）；
    - long：超过上限（用户选了再下：`--allow BV`）；multi_p：超过 MULTI_P_AUTO 个 P、用户还没勾的（勾了 = allow）；
      多 P 的其余情况拆成每 P 一条（page / source_id / url 带 ?p=N，P1 的 source_id 就是 BV 号），按 P 判在不在库；
    - invalid：原站已失效；non_video：音频 / 合集 / 其它类型。"""
    allow = allow or set()
    deny = deny or set()
    by_bv: dict[str, dict[str, Any]] = {}
    others: list[dict[str, Any]] = []
    for s in snaps:
        folder = s.get("title") or str(s.get("media_id"))
        fid = str(s.get("media_id") or "")
        for it in s.get("items") or []:
            row = {"bvid": it.get("bvid") or "", "title": it.get("title") or "", "upper": it.get("upper_name") or "",
                   "duration": it.get("duration"), "page_count": int(it.get("page_count") or 0), "folders": [folder],
                   "folder_ids": [fid] if fid else [],
                   "fav_time": it.get("fav_time"), "kind": it.get("kind"), "invalid": bool(it.get("invalid")),
                   "invalid_reason": it.get("invalid_reason"), "listed": it.get("listed", True)}
            if it.get("kind") != "video" or not row["bvid"]:
                row["url"] = ""
                others.append(row)
                continue
            row["url"] = CANONICAL_FMT.format(bvid=row["bvid"])
            got = by_bv.get(row["bvid"])
            if got is None:
                by_bv[row["bvid"]] = row
            else:
                if folder not in got["folders"]:
                    got["folders"].append(folder)
                if fid and fid not in got.setdefault("folder_ids", []):
                    got["folder_ids"].append(fid)
                if not got["title"] and row["title"]:
                    got.update(title=row["title"], upper=row["upper"], duration=row["duration"], page_count=row["page_count"])
    buckets: dict[str, list[dict[str, Any]]] = {"download": [], "hit": [], "long": [], "multi_p": [], "invalid": [],
                                                "non_video": others, "denied": []}
    for bv, row in by_bv.items():
        if bv in deny:
            row["reason"] = "你删了：任何情况下都不保存（已写删除屏蔽）"
            buckets["denied"].append(row)
        elif row["invalid"]:
            buckets["invalid"].append(row)
        elif row["page_count"] > 1 and bv not in allow and row["page_count"] > MULTI_P_AUTO:
            row["reason"] = f"共 {row['page_count']} P，超过 {MULTI_P_AUTO} P：在「挑选要同步的…」里勾了才下"
            buckets["multi_p"].append(row)
        elif row["page_count"] > 1 and bv not in allow and max_duration_s and (row["duration"] or 0) > max_duration_s:
            row["reason"] = f"{row['page_count']} P 共 {_hms(row['duration'])}，超过 {_hms(max_duration_s)}"
            buckets["long"].append(row)
        elif row["page_count"] > 1:
            for part in _parts(row):
                buckets["hit" if in_library(part["source_id"]) else "download"].append(part)
        elif in_library(bv):
            buckets["hit"].append(row)
        elif bv not in allow and max_duration_s and (row["duration"] or 0) > max_duration_s:   # 1031：0 = 不限时长
            row["reason"] = f"时长 {_hms(row['duration'])}，超过 {_hms(max_duration_s)}"
            buckets["long"].append(row)
        else:
            buckets["download"].append(row)
    # 收藏时间新的先下（用户最近收的最想看）；同一个多 P 按 P 号排
    for k in ("download", "long", "multi_p"):
        buckets[k].sort(key=lambda r: (-(r.get("fav_time") or 0), r.get("page") or 1))
    return {"buckets": buckets, "bv_total": len(by_bv),
            "counts": {k: len(v) for k, v in buckets.items()}}


def _parts(row: dict[str, Any]) -> list[dict[str, Any]]:
    """多 P → 每 P 一条。收藏列表只给总时长和 P 数：每 P 时长按平均估（预估用，duration_estimated）；标题入库时按 yt-dlp 的分 P 标题。"""
    n = int(row["page_count"])
    per = int((row.get("duration") or 0) / n) or None
    out = []
    for page in range(1, n + 1):
        out.append({**row, "folders": list(row["folders"]), "folder_ids": list(row.get("folder_ids") or []), "page": page,
                    "source_id": row["bvid"] if page == 1 else f"{row['bvid']}_p{page}",
                    "url": CANONICAL_FMT.format(bvid=row["bvid"]) + (f"?p={page}" if page > 1 else ""),
                    "title": f"{row['title']} · P{page}", "duration": per, "duration_estimated": True})
    return out


# ---- 待选清单（可见笔记，纯 Markdown，不是 LWA 对象）---------------------------------------------------------------

def _line(r: dict[str, Any]) -> str:
    bits = [f"**{r.get('title') or r.get('bvid') or '（无标题）'}**"]
    if r.get("upper"):
        bits.append(r["upper"])
    if r.get("duration"):
        bits.append(_hms(r["duration"]))
    if (r.get("page_count") or 0) > 1:
        bits.append(f"{r['page_count']} P")
    if r.get("folders"):
        bits.append("收藏夹：" + " / ".join(r["folders"]))
    if r.get("fav_time"):
        try:
            bits.append("收藏于 " + datetime.fromtimestamp(int(r["fav_time"])).strftime("%Y-%m-%d"))
        except (TypeError, ValueError, OSError):
            pass
    link = f" [打开]({r['url']})" if r.get("url") else ""
    reason = f"（{r['reason']}）" if r.get("reason") else ""
    return f"- [ ] {' · '.join(bits)}{link}{reason}"


def render_pending_note(result: dict[str, Any]) -> str:
    # 1031 作者：失效的、超过 1 小时的都不用管——不算「待选」、不在上面提醒，只放到「明细」里查得到；待选只剩多 P
    b = result["buckets"]
    lines = ["---", "cssclasses: [link-brain]", "tags: [bilibili, 待选]", "---", "",
             f"> [!info] B 站收藏同步 · {result.get('finished_at') or _now()}",
             f"> 收藏夹 {result['counts'].get('folders', 0)} 个 · 去重后 {result.get('bv_total', 0)} 个 BV · "
             f"已入库 {result['counts'].get('downloaded', 0) + result['counts'].get('hit', 0)} · 本次新下 {result['counts'].get('downloaded', 0)} · "
             f"失败 {result['counts'].get('failed', 0)} · 多 P 待选 {len(b.get('multi_p') or [])}",
             "",
             "下面这些**只记了链接，没下载**。想同步哪条就告诉 Fable / 在命令行加 `--allow BV号` 再跑一次 `bilibili sync`。", ""]
    sections = [(f"多 P 超过 {MULTI_P_AUTO} P 的（在「挑选要同步的…」里勾了才下）", b.get("multi_p") or []),
                ("这次没下成（下次同步会再试）", b.get("failed") or [])]
    limit = (result.get("options") or {}).get("max_duration_s", MAX_DURATION_S)
    details = [(f"超过 {_dur(limit) if limit else '时长上限'}（只记链接，不用处理；想要的话放行后再同步）", b.get("long") or []),
               ("原站已失效（只留记录）", b.get("invalid") or []),
               ("不是视频稿件（音频 / 合集等，暂不支持）", b.get("non_video") or []),
               ("你删了的（不再下载，只留记录）", b.get("denied") or [])]
    for title, rows in sections:
        if not rows:
            continue
        lines += [f"## {title}（{len(rows)}）", ""]
        lines += [_line(r) for r in rows]
        lines.append("")
    if any(rows for _t, rows in details):
        lines += ["---", "", "# 明细（不用处理，只是查得到）", ""]
        for title, rows in details:
            if not rows:
                continue
            lines += [f"## {title}（{len(rows)}）", ""]
            lines += [_line(r) for r in rows]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def pending_note_path() -> Path:
    return storage.visible_dir(SOURCE) / PENDING_NOTE


# ---- 用户的选择（持久）：allow = 放行（不看时长上限）；deny = 删 = 任何情况下都不保存（同小红书回收站：写删除屏蔽，本地留一条记录）--------

CHOICES = "choices.json"


def choices_path() -> Path:
    return favorites.sync_root() / CHOICES


def load_choices() -> dict[str, dict[str, Any]]:
    try:
        data = storage.read_json(choices_path())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {"allow": dict(data.get("allow") or {}), "deny": dict(data.get("deny") or {})}


def _known(bvid: str) -> dict[str, Any]:
    """待选清单 / 关系表里这条的标题等（给屏蔽记录和选择表留一条看得懂的记录）。"""
    try:
        last = storage.read_json(favorites.sync_root() / LAST_SYNC)
        for rows in (last.get("buckets") or {}).values():
            for r in rows or []:
                if isinstance(r, dict) and r.get("bvid") == bvid:
                    return {"title": r.get("title"), "upper": r.get("upper"), "duration": r.get("duration"), "folders": r.get("folders")}
    except (OSError, ValueError, AttributeError):
        pass
    try:   # 收藏夹快照里有标题 / UP / 时长（last-sync.json 还没写出来时靠它）
        for sp in sorted((favorites.sync_root() / "folders").glob("*.json")):
            snap = storage.read_json(sp)
            for it in (snap.get("items") or []) if isinstance(snap, dict) else []:
                if isinstance(it, dict) and it.get("bvid") == bvid and it.get("title"):
                    return {"title": it.get("title"), "upper": it.get("upper_name"), "duration": it.get("duration"),
                            "folders": [snap.get("title") or ""]}
    except (OSError, ValueError):
        pass
    for row in favorites.load_relations().values():
        if row.get("bvid") == bvid:
            return {"title": None, "folders": [row.get("folder_title")]}
    return {}


def choose(*, allow: list[str] | None = None, deny: list[str] | None = None, undo: list[str] | None = None) -> dict[str, Any]:
    """记下用户的选择。deny 的同时写删除屏蔽（index.write_tombstone，source=bilibili）：以后 ingest / catch / sync 一律不再保存；
    已经在库的不动（删库走现有 delete 命令）。undo 从两张表里拿掉（屏蔽本身用 trash --forget 解除，这里不代劳）。"""
    from ... import domain, index as index_mod
    now = _now()
    out: dict[str, list[str]] = {"allowed": [], "denied": [], "undone": [], "already_in_library": []}
    conn = index_mod.connect()
    try:
        def apply(data: dict[str, Any]) -> None:
            data.setdefault("allow", {})
            data.setdefault("deny", {})
            for bv in undo or []:
                if data["allow"].pop(bv, None) is not None or data["deny"].pop(bv, None) is not None:
                    out["undone"].append(bv)
            for bv in allow or []:
                data["deny"].pop(bv, None)
                data["allow"][bv] = {**_known(bv), "chosen_at": now}
                out["allowed"].append(bv)
            for bv in deny or []:
                data["allow"].pop(bv, None)
                info = _known(bv)
                data["deny"][bv] = {**info, "chosen_at": now}
                out["denied"].append(bv)
                if index_mod.find_object(conn, SOURCE, bv) is not None:
                    out["already_in_library"].append(bv)
                    continue
                tomb = index_mod.get_tombstone(conn, SOURCE, bv)
                if tomb is None or (info.get("title") and (tomb["title"] or bv) == bv):   # 没屏蔽过，或上次只记了 BV 号现在有标题了
                    index_mod.write_tombstone(conn, {"source": SOURCE, "source_id": bv, "item_id": domain.item_id(SOURCE, bv),
                                                     "title": info.get("title") or bv, "url": CANONICAL_FMT.format(bvid=bv),
                                                     "cover": None, "deleted_at": now, "trash_dir": f"_archive/bilibili-sync/denied/{bv}",
                                                     "state": "done"})
            data["updated_at"] = now
        storage.update_json(choices_path(), apply, lock_name="bilibili-choices", missing_ok=True)
    finally:
        conn.close()
    return out


# ---- 预估（1031 作者：点「立即同步」前先看要下多少、多大、多久）--------------------------------------------------------
# 全是估计：体积 = 总时长 × 每分钟体积（按画质档取已入库的实测）；耗时 = 体积 ÷ 下载速度（已入库的 yt-dlp 实测耗时，没有就按 STATE.md
# 记的单连接 130–430 KB/s）× 并行路数，再加上每条之间歇的秒数和入库的几秒。只读 RAW 里的 manifest / source.json，不联网。

FALLBACK_SPEED_BPS = (130 * 1024, 430 * 1024)    # 1029 实测：单连接拉 B 站 CDN 130–430 KB/s
# 这一档和 1080 档都没有实测时，每分钟多少字节（B 站常见码率的粗估）：(低, 高)
FALLBACK_BYTES_PER_MIN = {"720": (6 << 20, 12 << 20), "1080": (12 << 20, 25 << 20), "max": (12 << 20, 30 << 20)}
# 只有 1080 档的实测时换算到别的档：720 ≈ 1080 的一半；max 没大会员 ≈ 1080 上下（同为 1080p，HEVC / AV1 还更小）；
# 有大会员可能出 4K，大约 1080 的 2–4 倍
QUALITY_FROM_1080 = {"720": (0.45, 0.7), "max": (0.8, 1.3), "max_vip": (0.8, 4.0)}
INGEST_OVERHEAD_S = 5.0   # 入库（挪文件 / 算 sha / 渲染）每条大约几秒，串行
MIN_SAMPLES = 3


def _pct(vals: list[float], q: float) -> float:
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def library_samples() -> list[dict[str, Any]]:
    """已入库 B 站对象的实测：每条 {bytes, duration_s, seconds（yt-dlp 下载耗时，可能缺）, quality（1031 前入库的都是 1080 档）}。"""
    root = storage.archive_root() / SOURCE
    out: list[dict[str, Any]] = []
    try:
        objs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for obj in objs:
        try:
            versions = storage.existing_versions(SOURCE, obj.name)
            if not versions:
                continue
            raw = storage.raw_dir(SOURCE, obj.name, versions[-1])
            manifest = storage.read_json(raw / "manifest.json")
            video = next((m for m in manifest.get("media") or [] if m.get("role") == "video" and m.get("download_status") == "ok"), None)
            if not video or not video.get("bytes") or not video.get("duration_sec"):
                continue
            dl: dict[str, Any] = {}
            try:
                dl = (storage.read_json(raw / "source.json").get("capture") or {}).get("downloader") or {}
            except (OSError, ValueError, AttributeError):
                pass
            out.append({"bytes": int(video["bytes"]), "duration_s": float(video["duration_sec"]),
                        "seconds": float(dl["seconds"]) if dl.get("seconds") else None,
                        "quality": dl.get("quality") or "1080"})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return out


def estimate(rows: list[dict[str, Any]], *, quality: str = "max", workers: int = 1, gap_s: float = GAP_S, vip: bool = False,
             samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """本轮要下的 rows → {count, total_duration_s, size_bytes{low,high}, speed_bps{low,high}, eta_s{low,high}, basis{size,speed}, note}。"""
    from . import ytdlp
    quality = ytdlp.normalize_quality(quality)
    workers = max(1, int(workers or 1))
    samples = library_samples() if samples is None else samples
    durs = [float(r.get("duration") or 0) for r in rows]
    total = sum(durs)
    unknown = sum(1 for d in durs if d <= 0)

    def per_min(rows_: list[dict[str, Any]]) -> tuple[float, float]:
        rates = [s["bytes"] / (s["duration_s"] / 60) for s in rows_ if s["duration_s"] > 0]
        return _pct(rates, 0.25), _pct(rates, 0.75)

    label = ytdlp.QUALITY_LABELS[quality]
    same = [s for s in samples if s.get("quality") == quality]
    base = [s for s in samples if s.get("quality") == "1080"]
    if len(same) >= MIN_SAMPLES:
        bpm = per_min(same)
        bpm_basis = f"已入库 {len(same)} 条「{label}」的实测（取中间一半）"
    elif len(base) >= MIN_SAMPLES:
        lo, hi = per_min(base)
        f = (1.0, 1.0) if quality == "1080" else QUALITY_FROM_1080["max_vip" if quality == "max" and vip else quality]
        bpm = (lo * f[0], hi * f[1])
        bpm_basis = f"已入库 {len(base)} 条 1080p 的实测（取中间一半）" + ("" if quality == "1080" else f"，按「{label}」换算")
        if quality == "max":
            bpm_basis += "；有大会员可能出 4K，上限放宽" if vip else "；没大会员时最高一般就是 1080p"
    else:
        bpm = FALLBACK_BYTES_PER_MIN[quality]
        bpm_basis = "库里实测太少，按 B 站常见码率粗估"
    timed = [s["bytes"] / s["seconds"] for s in samples if s.get("seconds") and s["seconds"] > 0]
    if len(timed) >= MIN_SAMPLES:
        one = (_pct(timed, 0.25), _pct(timed, 0.75))
        speed_basis = f"已入库 {len(timed)} 条的下载耗时实测（单路，取中间一半）× {workers} 路"
    else:
        one = FALLBACK_SPEED_BPS
        speed_basis = f"单连接 130–430 KB/s（10-29 实测）× {workers} 路"
    speed = (one[0] * workers, one[1] * workers)
    size = (total / 60 * bpm[0], total / 60 * bpm[1])
    fixed = len(rows) * (gap_s + INGEST_OVERHEAD_S)
    eta = ((size[0] / speed[1] if speed[1] else 0) + fixed, (size[1] / speed[0] if speed[0] else 0) + fixed)
    note = "都是估计：体积按时长 × 每分钟体积，耗时按下载速度算，实际看 B 站给的码率和网速"
    if unknown:
        note += f"；{unknown} 条不知道时长，没算进去"
    if workers > 1:
        note += "；并行按路数线性估，带宽不够时会更慢"
    return {"count": len(rows), "total_duration_s": int(total), "unknown_duration": unknown, "quality": quality, "workers": workers,
            "bytes_per_min": {"low": int(bpm[0]), "high": int(bpm[1])},
            "size_bytes": {"low": int(size[0]), "high": int(size[1])},
            "speed_bps": {"low": int(speed[0]), "high": int(speed[1])},
            "eta_s": {"low": int(eta[0]), "high": int(eta[1])},
            "basis": {"size": bpm_basis, "speed": speed_basis, "samples": len(samples)},
            "estimated": True, "note": note}


# ---- 跑 ------------------------------------------------------------------------------------------------------------

def _fresh_snapshot(owner_mid: int, media_id: int, media_count: int, rescan_hours: float) -> dict[str, Any] | None:
    """上次完整快照够新、总数没变 → 直接用它（不联网）。"""
    snap = favorites.load_last_complete(owner_mid, media_id)
    if not snap or not snap.get("complete") or snap.get("media_count") != media_count:
        return None
    try:
        age_h = (datetime.now().astimezone() - datetime.fromisoformat(str(snap.get("fetched_at")))).total_seconds() / 3600
    except (TypeError, ValueError):
        return None
    return snap if 0 <= age_h <= rescan_hours else None


def run_sync(*, dry_run: bool = False, limit: int | None = None, max_duration_s: int = MAX_DURATION_S, gap_s: float = GAP_S,
             min_free_gb: float = MIN_FREE_GB, folders: list[str] | None = None, allow: list[str] | None = None,
             rescan_hours: float = RESCAN_HOURS, folder_gap_s: float = FOLDER_GAP_S, workers: int = 1,
             quality: str | None = None, danmaku: bool = True, tv: bool = True,
             skip_folders: list[str] | None = None, toview: bool = True,
             log: Callable[[str], None] | None = None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """返回 {ok, code, message, counts, buckets, folders, estimate, options, ...}；stdout 不碰（调用方打 JSON），人话走 log。
    1031：quality = max | 1080 | 720（不传 = ytdlp.DEFAULT_QUALITY）；danmaku=False 不存弹幕。这一趟 ytdlp.OPTIONS 改成这两样，结束复原。
    1031 作者（挑选页）：skip_folders = 关掉的收藏夹 id（"toview" = 稍后再看），整个跳过——不扫、不下；toview=True 时稍后再看
    当成一个「稍后再看」收藏夹一起走 plan / 下载。"""
    from . import ytdlp
    say = log or (lambda m: print(m, file=sys.stderr, flush=True))
    started = _now()
    quality = ytdlp.normalize_quality(quality or ytdlp.DEFAULT_QUALITY)
    workers = max(1, min(WORKERS_MAX, int(workers or 1)))
    skip = {str(x).strip() for x in (skip_folders or []) if str(x).strip()}
    if not dry_run:
        # 1031：缺下载器就别去扫收藏夹了（10-31 那趟扫完 71 个收藏夹才在第 1 条撞上 No module named yt_dlp）
        lacking = ytdlp.missing_tools()
        if lacking:
            return _stop_before_start(started, dry_run, "MISSING_DEPENDENCY", ytdlp.missing_text(lacking))
    prev_opts = ytdlp.configure(quality=quality, danmaku=danmaku, tv=tv)
    try:
        client, st = favorites.default_client()
    except BaseException:
        ytdlp.configure(**prev_opts)
        raise
    from . import tvapi
    out: dict[str, Any] = {"started_at": started, "login": st.get("state"), "dry_run": dry_run, "folders": [],
                           "counts": {}, "buckets": {}, "stopped": None, "pid": os.getpid(), "pid_created": _created(os.getpid()),
                           "options": {"quality": quality, "danmaku": bool(danmaku), "workers": workers,
                                       "max_duration_s": max_duration_s, "vip": bool(st.get("vip")),
                                       "skip_folders": sorted(skip),
                                       "tv": bool(tv) and tvapi.usable_token() is not None}}
    if not dry_run:
        # 1031：上次被关机 / 注销 / 「停止」杀掉的那一趟，临时目录里留着半截的下载——不管多新，进程没了的都清掉，那条这次重下
        cleared = sweep_dead_tmp()
        if cleared:
            say(f"清掉上次中断留下的 {cleared} 个半截下载目录（那几条这次重下）")
    try:
        if st.get("state") == "unknown":
            # 1031：查不到 ≠ 没登录（断网 / 接口抽风），别叫用户去重新扫码
            out.update(ok=False, code="NETWORK", message=f"查不到 B 站登录状态（{st.get('detail') or st.get('reason') or '网络不通'}）：{HINTS['NETWORK']}")
            return out
        if st.get("state") != "logged_in":
            out.update(ok=False, code="NOT_LOGGED_IN", message=f"B 站没登录或登录已失效：{HINTS['NOT_LOGGED_IN']}")
            return out
        mid = login.my_mid(client)
        if not mid:
            out.update(ok=False, code="UNKNOWN", message="查不到自己的 mid，没法列收藏夹（多半是登录刚失效或网络抖了一下，稍后再试）")
            return out
        res = favorites.list_folders(client, mid)
        if res["status"] not in ("ok", "empty"):
            kind = (res.get("error") or {}).get("reason")
            code = {"rate_limited": "HTTP_429", "not_logged_in": "NOT_LOGGED_IN", "network": "NETWORK", "timeout": "NETWORK"}.get(str(kind), "SYNC_FAILED")
            msg = f"列收藏夹失败：{(res.get('error') or {}).get('message') or res['status']}"
            out.update(ok=False, code=code, message=msg + (f"；{HINTS[code]}" if code in HINTS else ""))
            return out
        rows = res["folders"]
        _write_folder_list(mid, rows)
        want = {f.strip() for f in folders if f.strip()} if folders else set()
        if want:
            rows = [f for f in rows if f["title"] in want or str(f["media_id"]) in want or str(f["fid"]) in want]
        skipped = [f for f in rows if str(f["media_id"]) in skip]
        rows = [f for f in rows if str(f["media_id"]) not in skip]
        if skipped:
            say(f"跳过你关掉的收藏夹 {len(skipped)} 个：" + "、".join(f["title"] for f in skipped))
        say(f"收藏夹 {len(rows)} 个：" + "、".join(f"{f['title']}({f['media_count']})" for f in rows))
        snaps: list[dict[str, Any]] = []
        reused = 0
        for n, f in enumerate(rows):
            fresh = _fresh_snapshot(mid, f["media_id"], f["media_count"], rescan_hours)
            if fresh is not None:
                snap, reused = fresh, reused + 1
            else:
                if n and folder_gap_s:
                    sleep(folder_gap_s)
                r = favorites.sync_folder(client, f["media_id"], owner_mid=mid, log=say, page_gap_s=PAGE_GAP_S)
                snap = r["snapshot"]
            snaps.append(snap)
            out["folders"].append({"title": f["title"], "media_id_masked": favorites.mask_mid(f["media_id"]),
                                   "private": f["private"], "media_count": f["media_count"], "status": snap.get("status"),
                                   "complete": bool(snap.get("complete")), "items": len(snap.get("items") or []),
                                   "reused": fresh is not None, "error": (snap.get("error") or {}).get("message")})
        if reused:
            say(f"{reused} 个收藏夹复用了 {rescan_hours:g} 小时内的完整快照，没重扫")
        out["counts"]["folders"] = len(rows)
        out["counts"]["skipped_folders"] = len(skipped)
        # 1031 作者：稍后再看一起同步，当成「稍后再看」专辑（关掉了 / 只同步指定收藏夹且没点名它 → 不读）
        from . import toview as toview_mod
        if toview and toview_mod.TOVIEW_ID not in skip and (not want or want & {toview_mod.TOVIEW_ID, toview_mod.TITLE}):
            if rows and folder_gap_s:
                sleep(folder_gap_s)
            try:
                tv_r = toview_mod.sync_toview(client, mid, log=say)
            except Exception as exc:  # noqa: BLE001 - 稍后再看出岔子不耽误收藏夹那边
                say(f"稍后再看没读到：{errtext(exc)[:200]}")
                tv_r = {"snapshot": {"items": [], "status": "error", "complete": False}, "stale": False,
                        "error": {"reason": "error", "message": errtext(exc)[:200]}}
            snap = tv_r["snapshot"]
            snaps.append(snap)
            out["folders"].append({"title": toview_mod.TITLE, "media_id_masked": toview_mod.TOVIEW_ID, "kind": "toview",
                                   "private": True, "media_count": snap.get("media_count"), "status": snap.get("status"),
                                   "complete": bool(snap.get("complete")), "items": len(snap.get("items") or []),
                                   "reused": bool(tv_r["stale"]), "error": (tv_r["error"] or {}).get("message")})
            out["counts"]["toview"] = len(snap.get("items") or [])
        elif toview_mod.TOVIEW_ID in skip:
            out["counts"]["skipped_folders"] += 1

        from ... import index as index_mod
        conn = index_mod.connect()
        try:
            def in_library(bvid: str) -> bool:
                return index_mod.find_object(conn, SOURCE, bvid) is not None
            ch = load_choices()
            pl = plan(snaps, max_duration_s=max_duration_s, allow=set(allow or []) | set(ch["allow"]), deny=set(ch["deny"]),
                      in_library=in_library)
        finally:
            conn.close()
        out["bv_total"] = pl["bv_total"]
        b = pl["buckets"]
        out["counts"].update(pl["counts"])
        say(f"去重后 {pl['bv_total']} 个 BV：待下 {len(b['download'])}，已在库 {len(b['hit'])}，超时长 {len(b['long'])}，"
            f"多 P {len(b['multi_p'])}，失效 {len(b['invalid'])}，非视频 {len(b['non_video'])}，已排除 {len(b['denied'])}")
        queue = b["download"][: limit] if limit else b["download"]
        b["downloaded"], b["failed"] = [], []
        try:
            out["estimate"] = estimate(queue, quality=quality, workers=workers, gap_s=gap_s, vip=bool(st.get("vip")))
        except Exception as exc:  # noqa: BLE001 - 估不出来不耽误同步
            out["estimate"] = {"count": len(queue), "estimated": True, "error": errtext(exc)[:200]}
        if dry_run:
            b["skipped_by_limit"] = b["download"][len(queue):]
            out["buckets"] = b
            out["counts"].update(downloaded=0, failed=0)
            e = out["estimate"]
            msg = f"预演：会下载 {len(queue)} 条" + (f"，多于 {MULTI_P_AUTO} P 的多 P {len(b['multi_p'])} 条等你在挑选页勾" if b["multi_p"] else "")
            if e.get("size_bytes"):
                msg += (f"；估计 {_gb(e['size_bytes']['low'])}–{_gb(e['size_bytes']['high'])}、"
                        f"{_dur(e['eta_s']['low'])}–{_dur(e['eta_s']['high'])}（{ytdlp.QUALITY_LABELS[quality]}，{workers} 路）")
            out.update(ok=True, code="", message=msg, finished_at=_now())
            return out

        from ... import ingest as ingest_mod
        vault = storage.vault_root()
        say(f"画质：{ytdlp.QUALITY_LABELS[quality]}；弹幕：{'存' if danmaku else '不存'}")
        streak, pauses = 0, 0
        stop_code, last_fail_code = "", ""
        # 1031：设置页的「停止」是杀进程树，走不到结尾的 _persist——每条做完先把进度写进 last-sync.json（state=running），
        # 设置页看到 running 但进程已经没了，就说「上次中途停了」
        out["buckets"] = b
        out["state"] = "running"
        # 1029 作者：workers>1 时后面几条的 yt-dlp 先在后台下（瓶颈是单连接拉 CDN）；入库照旧一条一条。撞限流就退回一条一条下
        parallel = workers > 1
        ytdlp.prefetch_start(workers if parallel else 1)
        if parallel:
            say(f"并行下载 {workers} 路（入库仍一条一条）")
        for i, r in enumerate(queue, start=1):
            if parallel:
                for nxt in queue[i - 1:i - 1 + workers + 1]:
                    ytdlp.prefetch(ytdlp.download_url(nxt["bvid"], int(nxt.get("page") or 1)))
            if streak >= FAIL_STREAK:
                pauses += 1
                if pauses > MAX_PAUSES:
                    out["stopped"] = f"连着 {streak} 条失败、歇了 {MAX_PAUSES} 次还不行（疑似风控 / 断网），停在第 {i} 条"
                    stop_code = last_fail_code if last_fail_code in ("HTTP_429", "NETWORK") else "HTTP_429"
                    say(out["stopped"])
                    break
                say(f"连着 {streak} 条失败，歇 {int(PAUSE_S // 60)} 分钟再继续（第 {pauses}/{MAX_PAUSES} 次）")
                sleep(PAUSE_S)
                streak = 0
            free = _free_gb(vault)
            if free < min_free_gb:
                out["stopped"] = f"磁盘只剩 {free:.1f} GB（阈值 {min_free_gb} GB），停在第 {i} 条"
                stop_code = "DISK_LOW"
                say(out["stopped"])
                break
            say(f"[{i}/{len(queue)}] {r['bvid']} {r['title'][:40]} ({_hms(r['duration'])}) …")
            try:
                summary = ingest_mod.ingest_url(r["url"], origin="cli", actor="human", ingest_kind=INGEST_KIND,
                                                note=None, verbose=False)
                if summary.get("status") == "trashed":
                    r["reason"] = "在回收站里（你删过），不拉回"
                    b["failed"].append(r)
                    continue
                fresh = not (summary.get("hit") or summary.get("refreshed_unchanged"))
                err = ingest_mod.after_commit(SOURCE, r.get("source_id") or r["bvid"], fresh=fresh, reason="收藏同步")
                r["item_id"] = summary.get("item_id")
                failed_media = [m.get("role") for m in (summary.get("manifest") or {}).get("media") or [] if m.get("download_status") == "failed"]
                if failed_media:
                    r["partial"] = failed_media
                if err:
                    r["render_error"] = err
                b["downloaded"].append(r)
                streak = 0
                say(f"    入库 {r.get('item_id')}" + (f"，没拿到：{'、'.join(failed_media)}" if failed_media else ""))
            except (AccountBlocked, NeedsHuman) as exc:
                r["reason"] = errtext(exc)
                b["failed"].append(r)
                out["stopped"] = f"要人处理：{str(exc) or errtext(exc)}"   # 1031：码在 code 里，卡片上只放人话
                stop_code = str(getattr(exc, "code", "") or "NEEDS_HUMAN").split(".")[-1]
                say(out["stopped"])
                break
            except (SourceError, Exception) as exc:  # noqa: BLE001 - 一条坏了不带走整批
                r["reason"] = errtext(exc)[:200]
                b["failed"].append(r)
                streak += 1
                last_fail_code = str(getattr(exc, "code", "") or "")
                if getattr(exc, "code", "") in ("HTTP_429", "NETWORK"):
                    streak = FAIL_STREAK   # 限流 / 断网：不用等连败，下一条前就歇
                    if parallel:
                        parallel = False
                        ytdlp.prefetch_stop()
                        say("    限流 / 断网：退回一条一条下")
                say(f"    失败：{r['reason']}")
            _progress(out, b, done=i, total=len(queue))
            if gap_s and i < len(queue):
                sleep(gap_s)
        ytdlp.prefetch_stop()
        b["skipped_by_limit"] = b["download"][len(queue):]
        b["not_reached"] = queue[len(b["downloaded"]) + len(b["failed"]):]
        out["buckets"] = b
        out["counts"].update(downloaded=len(b["downloaded"]), failed=len(b["failed"]), not_reached=len(b["not_reached"]))
        out["finished_at"] = _now()
        out["state"] = "stopped" if out["stopped"] else "done"
        if out["stopped"]:   # 1031：停在第几条（设置页「上次停在第 N 条、为什么」）
            out["progress"] = {**(out.get("progress") or {}), "done": len(b["downloaded"]) + len(b["failed"]), "total": len(queue)}
        else:
            out.pop("progress", None)
        ok = out["stopped"] is None and not b["failed"]
        code = "" if ok else (stop_code or "SYNC_FAILED")
        # 1031 作者：超时长 / 失效的不用管，结束提示里不再提；多 P 照旧只记清单
        msg = (f"同步完：新下 {len(b['downloaded'])} 条、已在库 {len(b['hit'])} 条、失败 {len(b['failed'])} 条"
               + (f"；多于 {MULTI_P_AUTO} P 的多 P {len(b['multi_p'])} 条等你在「挑选要同步的…」里勾，也列在「{PENDING_NOTE}」" if b["multi_p"] else ""))
        if out["stopped"]:
            msg = out["stopped"] + "；" + (HINTS[stop_code] + "。" if stop_code in HINTS else "") + msg
        out.update(ok=ok, code=code, message=msg)
        _persist(out)
        return out
    finally:
        ytdlp.prefetch_stop()   # 半路炸了也别留着后台下载拖住进程退出
        ytdlp.configure(**prev_opts)
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


# ---- 断点续跑（1031：10-29 那轮 --workers 8 下到 349/849 时被 Windows 关机 / 注销结束，之后没人接着跑）------------------
# 续跑本来就成立：plan 用索引判「已入库」，再点一次只补没入库的；被打断的那条没发布（manifest 没写）就不算入库，下次重下。
# 这里补两件：①进程没了的临时下载目录不等 6 小时、开跑就清；②设置页要说清「上次停在第几条、为什么停」（last_summary）。

_TMP_PID_RE = re.compile(r"^dl-\d{8}T\d{6}-(?P<pid>\d+)-[0-9a-f]+$")


def _created(pid: int) -> float | None:
    try:
        from ... import procs
        return procs.created_of(int(pid))
    except Exception:  # noqa: BLE001 - 拿不到创建时间就只认 pid
        return None


def _pid_alive(pid: Any, created: Any = None) -> bool:
    """判活只认 storage.pid_state（查不清 = 当活着）；记过创建时间就再核一次，pid 被复用算死。"""
    if not pid or storage.pid_state(pid) == "dead":
        return False
    if created is None:
        return True
    now = _created(int(pid))
    return True if now is None else abs(now - float(created)) < 1


def sweep_dead_tmp() -> int:
    """清 `~/.link-brain/bilibili/tmp/dl-<时间>-<pid>-<随机>`：那个 pid 已经不在（不是本进程）的整目录删掉。返回清了几个。"""
    from . import ytdlp
    n = 0
    try:
        dirs = list(ytdlp.tmp_root().iterdir())
    except OSError:
        return 0
    for p in dirs:
        m = _TMP_PID_RE.match(p.name)
        if not p.is_dir() or not m or int(m.group("pid")) == os.getpid():
            continue
        if storage.pid_state(int(m.group("pid"))) == "dead":
            shutil.rmtree(p, ignore_errors=True)
            n += 0 if p.exists() else 1
    return n


INTERRUPTED_REASON = "进程被结束了（关机 / 注销 / 点了「停止」/ Obsidian 关掉），没来得及收尾"


def last_summary() -> dict[str, Any]:
    """上次同步的摘要（设置页 B 站卡用）。running 但进程已经没了 = 被打断：说停在第几条、为什么，提示再点会接着下。
    超时长 / 失效的只给数字放在明细里（用户不用管）；待处理只算多 P 和失败。"""
    try:
        last = storage.read_json(favorites.sync_root() / LAST_SYNC)
    except (OSError, ValueError):
        last = None
    if not isinstance(last, dict) or not last:
        return {"exists": False, "message": "还没同步过 B 站收藏"}
    c = last.get("counts") or {}
    state = last.get("state") or ("done" if last.get("finished_at") else "unknown")
    running = state == "running" and _pid_alive(last.get("pid"), last.get("pid_created"))
    if state == "running" and not running:
        state = "interrupted"
    prog = last.get("progress") or {}
    try:
        pending_note = pending_note_path().relative_to(storage.vault_root()).as_posix()
    except (ValueError, OSError):
        pending_note = None
    out = {"exists": True, "state": state, "running": running, "started_at": last.get("started_at"),
           "finished_at": last.get("finished_at"), "options": last.get("options") or {},
           "downloaded": int(c.get("downloaded") or 0), "failed": int(c.get("failed") or 0), "hit": int(c.get("hit") or 0),
           "multi_p": int(c.get("multi_p") or 0), "not_reached": int(c.get("not_reached") or 0),
           "details": {"long": int(c.get("long") or 0), "invalid": int(c.get("invalid") or 0),
                       "non_video": int(c.get("non_video") or 0), "denied": int(c.get("denied") or 0)},
           "progress": prog or None, "stopped": last.get("stopped"), "code": last.get("code") or "",
           "pending_note": pending_note}
    if state == "interrupted":
        out["stop_reason"] = INTERRUPTED_REASON
        out["code"] = "INTERRUPTED"
        # 1101 作者「最好是没有电脑经验的小白看得懂的话」
        out["message"] = (f"上次同步没跑完：下到第 {prog.get('done', '?')} 条（一共 {prog.get('total', '?')} 条）时停了，"
                          f"多半是关了电脑或 Obsidian。已经下好的都在，点「立即同步」会接着下剩下的。")
    elif running:
        out["message"] = f"正在同步：第 {prog.get('done', 0)}/{prog.get('total', '?')} 条"
    elif state == "stopped":
        out["stop_reason"] = last.get("stopped")
        out["message"] = last.get("message") or f"上次同步中途停了：{last.get('stopped')}"
    else:
        out["message"] = last.get("message") or "上次同步完成"
    return out


def long_list(*, max_duration_s: int = MAX_DURATION_S) -> dict[str, Any]:
    """1031 作者：超过时长上限、还没入库的收藏列成清单，用户在设置页自己勾哪些要下。只读本地收藏夹快照，不连 B 站。
    每条 {bvid, title, upper, duration, folders, url, chosen}；chosen = 已经放行（下次同步就下）。失效不列；多 P 见 multi_list。"""
    snaps = _local_snapshots()
    ch = load_choices()
    from ... import index as index_mod
    conn = index_mod.connect()
    try:
        pl = plan(snaps, max_duration_s=max_duration_s, deny=set(ch["deny"]),
                  in_library=lambda bv: index_mod.find_object(conn, SOURCE, bv) is not None)
    finally:
        conn.close()
    rows = [{"bvid": r["bvid"], "title": r["title"], "upper": r["upper"], "duration": r["duration"], "duration_text": _hms(r["duration"]),
             "folders": r["folders"], "folder_ids": r.get("folder_ids") or [], "url": r["url"],
             "chosen": r["bvid"] in ch["allow"]} for r in pl["buckets"]["long"]]
    rows.sort(key=lambda r: (r["chosen"], -(r["duration"] or 0)))
    return {"items": rows, "total": len(rows), "chosen": sum(1 for r in rows if r["chosen"]), "max_duration": max_duration_s}


def multi_list() -> dict[str, Any]:
    """1031 作者：超过 MULTI_P_AUTO 个 P 的多 P 收藏列成清单，用户在挑选页勾哪些要下（勾 = allow，下次同步拆成每 P 一条下）。
    只读本地快照，不连 B 站。每条 {bvid, title, upper, page_count, duration, folders, url, chosen, done（已入库几 P）}。"""
    snaps = _local_snapshots()
    ch = load_choices()
    from ... import index as index_mod
    conn = index_mod.connect()
    try:
        pl = plan(snaps, max_duration_s=0, deny=set(ch["deny"]),
                  in_library=lambda bv: index_mod.find_object(conn, SOURCE, bv) is not None)
        rows = []
        for r in pl["buckets"]["multi_p"]:
            done = sum(1 for part in _parts(r) if index_mod.find_object(conn, SOURCE, part["source_id"]) is not None)
            rows.append({"bvid": r["bvid"], "title": r["title"], "upper": r["upper"], "page_count": r["page_count"],
                         "duration": r["duration"], "duration_text": _hms(r["duration"]), "folders": r["folders"],
                         "folder_ids": r.get("folder_ids") or [], "url": r["url"], "chosen": r["bvid"] in ch["allow"], "done": done})
    finally:
        conn.close()
    rows.sort(key=lambda r: (r["chosen"], r["page_count"]))
    return {"items": rows, "total": len(rows), "chosen": sum(1 for r in rows if r["chosen"]), "auto_max": MULTI_P_AUTO}


# ---- 挑选页（1031 作者：「没有让我选哪些下载」）：收藏夹开关 + 超长视频逐条勾选。只读本地，不连 B 站 --------------------------

def folder_list_path() -> Path:
    return favorites.sync_root() / FOLDER_LIST


def _write_folder_list(mid: Any, rows: list[dict[str, Any]]) -> None:
    """列到的全部收藏夹（含关掉的）落盘：挑选页列收藏夹用。写不上不耽误同步。"""
    try:
        storage.write_json(folder_list_path(), {"owner_mid": mid, "fetched_at": _now(), "folders": [
            {"id": str(f["media_id"]), "title": f["title"], "private": bool(f.get("private")), "media_count": f.get("media_count")}
            for f in rows]})
    except OSError as exc:
        print(f"[bilibili sync] 收藏夹列表没写上：{errtext(exc)}", file=sys.stderr)


def _local_snapshots() -> list[dict[str, Any]]:
    out = []
    for sp in sorted((favorites.sync_root() / "folders").glob("*.json")):
        if sp.name.endswith(".last-complete.json"):
            continue
        try:
            snap = storage.read_json(sp)
        except (OSError, ValueError):
            continue
        if isinstance(snap, dict):
            out.append(snap)
    return out


def picker(*, max_duration_s: int = MAX_DURATION_S) -> dict[str, Any]:
    """挑选页的数据：{folders: [{id, title, media_count, private, kind, scanned}], long: long_list(...), message}。
    收藏夹 = 上次列到的全部（folder-list.json）+ 本地快照里有的；稍后再看排第一。一个都没有 → 叫用户先预估 / 同步一次。"""
    from . import toview as toview_mod
    try:
        listed = storage.read_json(folder_list_path())
    except (OSError, ValueError):
        listed = {}
    listed = listed if isinstance(listed, dict) else {}
    owner = listed.get("owner_mid")
    by_id: dict[str, dict[str, Any]] = {}
    for f in listed.get("folders") or []:
        if isinstance(f, dict) and f.get("id"):
            by_id[str(f["id"])] = {"id": str(f["id"]), "title": f.get("title") or "", "media_count": f.get("media_count"),
                                   "private": bool(f.get("private")), "kind": "folder", "scanned": False}
    for snap in _local_snapshots():
        if owner and snap.get("owner_mid") and str(snap.get("owner_mid")) != str(owner):
            continue   # 别人的公开收藏夹（单独扫过的）不算用户的
        fid = str(snap.get("media_id") or "")
        if not fid:
            continue
        is_tv = fid == toview_mod.TOVIEW_ID
        row = by_id.setdefault(fid, {"id": fid, "title": snap.get("title") or "", "media_count": snap.get("media_count"),
                                     "private": bool(snap.get("private")), "kind": "folder"})
        row["scanned"] = True
        if is_tv:
            row["kind"] = "toview"
        if row.get("media_count") is None:
            row["media_count"] = snap.get("media_count") if snap.get("media_count") is not None else len(snap.get("items") or [])
    folders = list(by_id.values())
    if folders and toview_mod.TOVIEW_ID not in by_id:
        # 列到过收藏夹但还没读过稍后再看（旧版本同步的）：照样给一行开关，条数等下次同步
        folders.insert(0, {"id": toview_mod.TOVIEW_ID, "title": toview_mod.TITLE, "media_count": None, "private": True,
                           "kind": "toview", "scanned": False})
    folders.sort(key=lambda f: 0 if f["kind"] == "toview" else 1)
    lo = long_list(max_duration_s=max_duration_s)
    mp = multi_list()
    if not folders:
        msg = "还没扫过收藏夹：先点一次「预估」或「立即同步」，扫一遍收藏夹"
    else:
        msg = f"收藏夹 {len(folders)} 个" + (f"；超过 {_hms(max_duration_s)} 还没入库的 {lo['total']} 条，已选 {lo['chosen']} 条"
                                             if max_duration_s else "；没设时长上限，长视频不用挑")
        if mp["total"]:
            msg += f"；超过 {MULTI_P_AUTO} P 的多 P {mp['total']} 条，已选 {mp['chosen']} 条"
    return {"folders": folders, "long": lo, "multi": mp, "fetched_at": listed.get("fetched_at"), "empty": not folders, "message": msg}


def run_pick(args) -> int:
    from ... import read as read_mod
    from ...cli import EXIT_OK
    out = picker(max_duration_s=max(0, int(getattr(args, "max_duration", MAX_DURATION_S) or 0)))
    read_mod.dump_json(read_mod.outcome(out, ok=True, message=out["message"]))
    return EXIT_OK


def run_long(args) -> int:
    from ... import read as read_mod
    from ...cli import EXIT_OK
    out = long_list(max_duration_s=int(getattr(args, "max_duration", MAX_DURATION_S) or 0))
    msg = f"超过 {_hms(out['max_duration'])} 的收藏 {out['total']} 条，已选 {out['chosen']} 条" if out["max_duration"] else "没设时长上限：没有要挑的"
    read_mod.dump_json(read_mod.outcome(out, ok=True, message=msg))
    return EXIT_OK


def run_last(args) -> int:
    from ... import read as read_mod
    from ...cli import EXIT_OK
    s = last_summary()
    read_mod.dump_json(read_mod.outcome(s, ok=True, message=s.get("message") or ""))
    return EXIT_OK


def _progress(out: dict[str, Any], b: dict[str, Any], *, done: int, total: int) -> None:
    """每条做完写一次 last-sync.json（state=running + 进度）：被「停止」杀掉时设置页还能说出已经下了几条。写不上不管。"""
    out["progress"] = {"done": done, "total": total, "at": _now()}
    out["counts"].update(downloaded=len(b["downloaded"]), failed=len(b["failed"]))
    try:
        storage.write_json(favorites.sync_root() / LAST_SYNC, out)
    except OSError:
        pass


def _stop_before_start(started: str, dry_run: bool, code: str, reason: str) -> dict[str, Any]:
    """开跑前就停（没连网、没动队列）：只把上次记录的「为什么停」换成这次的，计数 / 进度 / 待选清单都不碰，
    侧栏 SYNC 和设置页照旧说「停在第几条」，原因是这次的人话。"""
    msg = f"{reason}；{HINTS[code]}" if code in HINTS else reason
    out = {"started_at": started, "finished_at": _now(), "dry_run": dry_run, "counts": {}, "buckets": {},
           "stopped": f"要人处理：{reason}", "ok": False, "code": code, "message": msg}
    try:
        last = storage.read_json(favorites.sync_root() / LAST_SYNC)
    except (OSError, ValueError):
        last = None
    if isinstance(last, dict) and last:
        last.update(state="stopped", stopped=out["stopped"], ok=False, code=code, message=msg,
                    started_at=started, finished_at=out["finished_at"], pid=None)
        try:
            storage.write_json(favorites.sync_root() / LAST_SYNC, last)
        except OSError as exc:
            print(f"[bilibili sync] last-sync.json 没写上：{errtext(exc)}", file=sys.stderr)
    return out


def _persist(out: dict[str, Any]) -> None:
    """结果落两处：机读 `_archive/bilibili-sync/last-sync.json`；人看的待选清单 `Web/Bilibili/B站待选清单.md`。
    都不含 Cookie；写不上只记日志。"""
    try:
        storage.write_json(favorites.sync_root() / LAST_SYNC, out)
    except OSError as exc:
        print(f"[bilibili sync] last-sync.json 没写上：{errtext(exc)}", file=sys.stderr)
    try:
        p = pending_note_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        storage.atomic_write_text(p, render_pending_note(out))
    except OSError as exc:
        print(f"[bilibili sync] 待选清单没写上：{errtext(exc)}", file=sys.stderr)
    try:
        from ...catalog import ensure_fresh
        ensure_fresh(wait_s=120)
    except Exception as exc:  # noqa: BLE001
        print(f"[bilibili sync] 目录没重建：{errtext(exc)}", file=sys.stderr)


def run_choose(args) -> int:
    from ... import read as read_mod
    from ...cli import EXIT_OK
    out = choose(allow=getattr(args, "allow", None) or [], deny=getattr(args, "deny", None) or [], undo=getattr(args, "undo", None) or [])
    ch = load_choices()
    msg = (f"放行 {len(out['allowed'])} 条、删 {len(out['denied'])} 条、撤销 {len(out['undone'])} 条；"
           f"现在放行表 {len(ch['allow'])} 条、屏蔽表 {len(ch['deny'])} 条")
    if out["already_in_library"]:
        msg += f"；{len(out['already_in_library'])} 条已经在库里，没动（要删走 delete）"
    read_mod.dump_json(read_mod.outcome({**out, "allow": sorted(ch["allow"]), "deny": sorted(ch["deny"])}, ok=True, message=msg))
    return EXIT_OK


def run(args) -> int:
    from ... import read as read_mod
    from ...cli import EXIT_ERROR, EXIT_NEEDS_HUMAN, EXIT_OK
    out = run_sync(dry_run=bool(getattr(args, "dry_run", False)), limit=getattr(args, "limit", None),
                   max_duration_s=max(0, int(MAX_DURATION_S if getattr(args, "max_duration", None) is None else args.max_duration)),
                   gap_s=float(getattr(args, "gap", GAP_S) or 0), min_free_gb=float(getattr(args, "min_free_gb", MIN_FREE_GB) or 0),
                   folders=getattr(args, "folder", None) or None, allow=getattr(args, "allow", None) or None,
                   workers=max(1, min(WORKERS_MAX, int(getattr(args, "workers", 1) or 1))),
                   skip_folders=getattr(args, "skip_folder", None) or None,
                   quality=getattr(args, "quality", None), danmaku=not bool(getattr(args, "no_danmaku", False)),
                   tv=not bool(getattr(args, "no_tv", False)))
    payload = {k: v for k, v in out.items() if k != "buckets"}
    payload["pending"] = {k: [{"bvid": r.get("bvid"), "title": r.get("title"), "duration": r.get("duration"), "reason": r.get("reason")}
                              for r in v] for k, v in (out.get("buckets") or {}).items() if k in ("long", "multi_p", "failed", "denied")}
    try:   # 1031：设置页「待选清单」链接用库内相对路径打开
        payload["pending_note"] = pending_note_path().relative_to(storage.vault_root()).as_posix()
    except (ValueError, OSError):
        payload["pending_note"] = None
    read_mod.dump_json(read_mod.outcome(payload, ok=bool(out.get("ok")), message=out.get("message") or "", code=out.get("code") or ""))
    if out.get("ok"):
        return EXIT_OK
    return EXIT_NEEDS_HUMAN if out.get("code") in NEEDS_HUMAN_CODES else EXIT_ERROR


NEEDS_HUMAN_CODES = ("NOT_LOGGED_IN", "NEEDS_HUMAN", "MISSING_DEPENDENCY", "DISK_LOW")
