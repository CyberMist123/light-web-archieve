"""B 站收藏夹同步（阶段二批次 B 的最短路径，1029 她：「今晚按收藏夹名当专辑都下载同步了吧；超过 1 小时的只放链接告诉我是啥，之后让我选」）。

流程：登录态 → 列自己全部收藏夹（含私密）→ 逐个收藏夹扫描（favorites.sync_folder：快照 + 关系表）→ 跨收藏夹按 BV 去重 →
分流：失效 / 非视频 / 多 P / 超过时长上限 → **只记清单不下载**；其余逐条走阶段一的单视频入库（ingest.ingest_url，ingest_kind=favorite）
→ 收藏夹名经 note_albums 成目录里的「专辑」→ 写 `_archive/bilibili-sync/last-sync.json` 和可见的待选清单 `Web/Bilibili/B站待选清单.md`。

不做：多 P 下载（批次 B 正式做，此处列进待选）、取消收藏的处理（关系表已记 active，meta 不动）、定时（批次 C）。
每条视频单独 try；登录失效 / 风控 / 缺依赖 → 整批停下如实报；磁盘余量低于阈值 → 停。再跑一次只补没入库的（索引命中即 HIT）。
"""
from __future__ import annotations

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
    - long：超过上限（她选了再下：`--allow BV`）；multi_p：多 P（批次 B 做，先列着）；
    - invalid：原站已失效；non_video：音频 / 合集 / 其它类型。"""
    allow = allow or set()
    deny = deny or set()
    by_bv: dict[str, dict[str, Any]] = {}
    others: list[dict[str, Any]] = []
    for s in snaps:
        folder = s.get("title") or str(s.get("media_id"))
        for it in s.get("items") or []:
            row = {"bvid": it.get("bvid") or "", "title": it.get("title") or "", "upper": it.get("upper_name") or "",
                   "duration": it.get("duration"), "page_count": int(it.get("page_count") or 0), "folders": [folder],
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
        elif in_library(bv):
            buckets["hit"].append(row)
        elif row["page_count"] > 1:
            row["reason"] = f"多 P（{row['page_count']} P）：分 P 下载批次 B 做"
            buckets["multi_p"].append(row)
        elif bv not in allow and (row["duration"] or 0) > max_duration_s:
            row["reason"] = f"时长 {_hms(row['duration'])}，超过 {_hms(max_duration_s)}"
            buckets["long"].append(row)
        else:
            buckets["download"].append(row)
    # 收藏时间新的先下（她最近收的最想看）
    for k in ("download", "long", "multi_p"):
        buckets[k].sort(key=lambda r: r.get("fav_time") or 0, reverse=True)
    return {"buckets": buckets, "bv_total": len(by_bv),
            "counts": {k: len(v) for k, v in buckets.items()}}


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
    b = result["buckets"]
    lines = ["---", "cssclasses: [link-brain]", "tags: [bilibili, 待选]", "---", "",
             f"> [!info] B 站收藏同步 · {result.get('finished_at') or _now()}",
             f"> 收藏夹 {result['counts'].get('folders', 0)} 个 · 去重后 {result.get('bv_total', 0)} 个 BV · "
             f"已入库 {result['counts'].get('downloaded', 0) + result['counts'].get('hit', 0)} · 本次新下 {result['counts'].get('downloaded', 0)} · "
             f"失败 {result['counts'].get('failed', 0)} · 待选 {len(b.get('long') or []) + len(b.get('multi_p') or [])}",
             "",
             "下面这些**只记了链接，没下载**。想同步哪条就告诉 Fable / 在命令行加 `--allow BV号` 再跑一次 `bilibili sync`。", ""]
    sections = [("超过 1 小时（你选了再下）", b.get("long") or []),
                ("多 P 视频（分 P 下载下一批做）", b.get("multi_p") or []),
                ("这次没下成（下次同步会再试）", b.get("failed") or []),
                ("原站已失效（只留记录）", b.get("invalid") or []),
                ("不是视频稿件（音频 / 合集等，暂不支持）", b.get("non_video") or []),
                ("你删了的（不再下载，只留记录）", b.get("denied") or [])]
    for title, rows in sections:
        if not rows:
            continue
        lines += [f"## {title}（{len(rows)}）", ""]
        lines += [_line(r) for r in rows]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def pending_note_path() -> Path:
    return storage.visible_dir(SOURCE) / PENDING_NOTE


# ---- 她的选择（持久）：allow = 放行（不看时长上限）；deny = 删 = 任何情况下都不保存（同小红书回收站：写删除屏蔽，本地留一条记录）--------

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
    """记下她的选择。deny 的同时写删除屏蔽（index.write_tombstone，source=bilibili）：以后 ingest / catch / sync 一律不再保存；
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
             log: Callable[[str], None] | None = None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """返回 {ok, code, message, counts, buckets, folders, ...}；stdout 不碰（调用方打 JSON），人话走 log。"""
    say = log or (lambda m: print(m, file=sys.stderr, flush=True))
    started = _now()
    client, st = favorites.default_client()
    out: dict[str, Any] = {"started_at": started, "login": st.get("state"), "dry_run": dry_run, "folders": [],
                           "counts": {}, "buckets": {}, "stopped": None}
    try:
        if st.get("state") != "logged_in":
            out.update(ok=False, code="NOT_LOGGED_IN", message=f"B 站没登录（{st.get('detail') or st.get('reason') or st.get('state')}）：先 `bilibili login`")
            return out
        mid = login.my_mid(client)
        if not mid:
            out.update(ok=False, code="UNKNOWN", message="查不到自己的 mid，没法列收藏夹")
            return out
        res = favorites.list_folders(client, mid)
        if res["status"] not in ("ok", "empty"):
            out.update(ok=False, code="SYNC_FAILED", message=f"列收藏夹失败：{(res.get('error') or {}).get('message') or res['status']}")
            return out
        rows = res["folders"]
        if folders:
            want = {f.strip() for f in folders if f.strip()}
            rows = [f for f in rows if f["title"] in want or str(f["media_id"]) in want or str(f["fid"]) in want]
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
        if dry_run:
            b["skipped_by_limit"] = b["download"][len(queue):]
            out["buckets"] = b
            out["counts"].update(downloaded=0, failed=0)
            out.update(ok=True, code="", message=f"预演：会下载 {len(queue)} 条，{len(b['long'])} 条超过时长只记链接", finished_at=_now())
            return out

        from ... import ingest as ingest_mod
        from . import ytdlp
        vault = storage.vault_root()
        streak, pauses = 0, 0
        # 1029 她：workers>1 时后面几条的 yt-dlp 先在后台下（瓶颈是单连接拉 CDN）；入库照旧一条一条。撞限流就退回一条一条下
        parallel = workers > 1
        ytdlp.prefetch_start(workers if parallel else 1)
        if parallel:
            say(f"并行下载 {workers} 路（入库仍一条一条）")
        for i, r in enumerate(queue, start=1):
            if parallel:
                for nxt in queue[i - 1:i - 1 + workers + 1]:
                    ytdlp.prefetch(ytdlp.download_url(nxt["bvid"]))
            if streak >= FAIL_STREAK:
                pauses += 1
                if pauses > MAX_PAUSES:
                    out["stopped"] = f"连着 {streak} 条失败、歇了 {MAX_PAUSES} 次还不行（疑似风控 / 断网），停在第 {i} 条"
                    say(out["stopped"])
                    break
                say(f"连着 {streak} 条失败，歇 {int(PAUSE_S // 60)} 分钟再继续（第 {pauses}/{MAX_PAUSES} 次）")
                sleep(PAUSE_S)
                streak = 0
            free = _free_gb(vault)
            if free < min_free_gb:
                out["stopped"] = f"磁盘只剩 {free:.1f} GB（阈值 {min_free_gb} GB），停在第 {i} 条"
                say(out["stopped"])
                break
            say(f"[{i}/{len(queue)}] {r['bvid']} {r['title'][:40]} ({_hms(r['duration'])}) …")
            try:
                summary = ingest_mod.ingest_url(r["url"], origin="cli", actor="human", ingest_kind=INGEST_KIND,
                                                note=None, verbose=False)
                if summary.get("status") == "trashed":
                    r["reason"] = "在回收站里（她删过），不拉回"
                    b["failed"].append(r)
                    continue
                fresh = not (summary.get("hit") or summary.get("refreshed_unchanged"))
                err = ingest_mod.after_commit(SOURCE, r["bvid"], fresh=fresh, reason="收藏同步")
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
                out["stopped"] = f"要人处理（{getattr(exc, 'code', '') or 'NEEDS_HUMAN'}）：{errtext(exc)}"
                say(out["stopped"])
                break
            except (SourceError, Exception) as exc:  # noqa: BLE001 - 一条坏了不带走整批
                r["reason"] = errtext(exc)[:200]
                b["failed"].append(r)
                streak += 1
                if getattr(exc, "code", "") in ("HTTP_429", "NETWORK"):
                    streak = FAIL_STREAK   # 限流 / 断网：不用等连败，下一条前就歇
                    if parallel:
                        parallel = False
                        ytdlp.prefetch_stop()
                        say("    限流 / 断网：退回一条一条下")
                say(f"    失败：{r['reason']}")
            if gap_s and i < len(queue):
                sleep(gap_s)
        ytdlp.prefetch_stop()
        b["skipped_by_limit"] = b["download"][len(queue):]
        b["not_reached"] = queue[len(b["downloaded"]) + len(b["failed"]):]
        out["buckets"] = b
        out["counts"].update(downloaded=len(b["downloaded"]), failed=len(b["failed"]), not_reached=len(b["not_reached"]))
        out["finished_at"] = _now()
        _persist(out)
        ok = out["stopped"] is None and not b["failed"]
        code = "" if ok else ("NEEDS_HUMAN" if out["stopped"] and "要人处理" in out["stopped"] else "SYNC_FAILED")
        msg = (f"同步完：新下 {len(b['downloaded'])} 条、已在库 {len(b['hit'])} 条、失败 {len(b['failed'])} 条；"
               f"超过 {_hms(max_duration_s)} 的 {len(b['long'])} 条和多 P 的 {len(b['multi_p'])} 条只记了链接，见「{PENDING_NOTE}」")
        if out["stopped"]:
            msg = out["stopped"] + "；" + msg
        out.update(ok=ok, code=code, message=msg)
        return out
    finally:
        from . import ytdlp
        ytdlp.prefetch_stop()   # 半路炸了也别留着后台下载拖住进程退出
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


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
                   max_duration_s=int(getattr(args, "max_duration", MAX_DURATION_S) or MAX_DURATION_S),
                   gap_s=float(getattr(args, "gap", GAP_S) or 0), min_free_gb=float(getattr(args, "min_free_gb", MIN_FREE_GB) or 0),
                   folders=getattr(args, "folder", None) or None, allow=getattr(args, "allow", None) or None,
                   workers=max(1, int(getattr(args, "workers", 1) or 1)))
    payload = {k: v for k, v in out.items() if k != "buckets"}
    payload["pending"] = {k: [{"bvid": r.get("bvid"), "title": r.get("title"), "duration": r.get("duration"), "reason": r.get("reason")}
                              for r in v] for k, v in (out.get("buckets") or {}).items() if k in ("long", "multi_p", "failed", "denied")}
    read_mod.dump_json(read_mod.outcome(payload, ok=bool(out.get("ok")), message=out.get("message") or "", code=out.get("code") or ""))
    if out.get("ok"):
        return EXIT_OK
    return EXIT_NEEDS_HUMAN if out.get("code") in ("NOT_LOGGED_IN", "NEEDS_HUMAN") else EXIT_ERROR
