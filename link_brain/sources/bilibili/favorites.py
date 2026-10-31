"""Bilibili 收藏夹：只读发现 + 分页快照 + 对比 + 收藏关系表（第二阶段批次 A）。

只读：本模块只调 B 站两个公开的只读接口，不下载任何视频、不写 Cookie：
- `x/v3/fav/folder/created/list-all?up_mid=`：某人创建的收藏夹（没登录只看得到公开的；整个列表被隐藏时 data=null）；
- `x/v3/fav/resource/list?media_id=&pn=&ps=`：收藏夹内容，`ps` 最大 20，按 `has_more` 翻页，
  `info.media_count` 是总数。字段以 bilibili-API-collect 的 fav/info、fav/list 为准，2026-10-29 匿名实测过：
  - 公开收藏夹：`code=0`，`data.info` 有、`data.medias` 是这一页；翻过最后一页 `medias=null, has_more=false`；
  - 私密 / 无权限：`code=0`，但 `data.info=null, data.medias=null`（不是文档写的 -403，-403 也照样认）；
  - 不存在的 id：`code=0, data=null`；不是数字：`code=-400`。
  已删的收藏夹和别人的私密收藏夹匿名看都是「没有 info」——判不清时一律记 `forbidden`（无权限或已删），绝不当空收藏夹。

快照（`_archive/bilibili-sync/folders/`，路径只用相对 vault 的 POSIX 路径、只写 `storage.write_json`）：
- `<owner_mid>-<media_id>.json`：**最近一次扫描**，翻一页落一次盘（检查点）；没翻完 / 出错是 `complete=false`，
  带 `pages_read / missing_pages / error`，下次 `scan_folder(resume=True)` 只补缺页；
- `<owner_mid>-<media_id>.last-complete.json`：**上次完整快照**，只有总数核对通过的扫描才覆盖它。
  部分扫描绝不动它，对比（`diff_snapshot`）拿它当基准。

收藏关系（`_archive/bilibili-sync/relations.json`）：键 `(owner_mid, media_id, bvid)`，记 fav_time / first_seen /
last_seen / active。只有完整且不可疑的扫描才把「不在了」的关系标 `active=false`；从不删行、不碰本地归档。
本批只设计 + 写入，还没接进对象 meta（等阶段一的 BV 对象落地）。

登录：阶段一提供 `link_brain.sources.bilibili.login`（`http_client()` / `status()`）。这里一律函数内延迟 import；
没有它（阶段一还没合）就退回不带登录的只读客户端——公开收藏夹照读，私密收藏夹如实报 `forbidden`。
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, urlparse

from link_brain import storage
from link_brain.errtext import errtext

API = "https://api.bilibili.com"
FOLDERS_URL = API + "/x/v3/fav/folder/created/list-all"
RESOURCE_URL = API + "/x/v3/fav/resource/list"
IDS_URL = API + "/x/v3/fav/resource/ids"
PAGE_SIZE_MAX = 20                 # 接口定义域 1–20（实测传 21 不报错，但别依赖）
PAGE_GAP_S = 1.0                   # 翻页之间歇一下：只读接口也别连珠炮
RETRY_GAP_S = 3.0                  # 超时 / 断网 / 5xx 只重试一次；限流（412/429）不重试，当场停
TIMEOUT_S = 15.0
SYNC_DIRNAME = "bilibili-sync"
SCHEMA_VERSION = 1
SUSPICIOUS_DROP = 0.5              # 完整扫描比上次少一半以上（且上次 ≥ SUSPICIOUS_MIN 条）→ 待核实，先不解除关系
SUSPICIOUS_MIN = 10
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/130.0 Safari/537.36")

# 收藏项 type（fav/list）：2 视频稿件、12 音频、21 视频合集。只有视频稿件有 bvid；其余照样留一条记录（kind 标出来），不丢。
KIND_OF_TYPE = {2: "video", 12: "audio", 21: "collection"}
# 收藏项 attr：0 正常、9 UP 主自己删了、1 其他原因删了（实测失效项标题是「已失效视频」）
INVALID_OF_ATTR = {9: "up_deleted", 1: "deleted"}

# 扫描 / 单页的原因词表（快照里的 status / error.reason）。还没接 problems：故障码等批次 C 接同步记录时一起登记。
RATE_LIMIT_CODES = {-412, -352, -509, -799}   # 请求被拦截 / 风控校验失败 / 请求过于频繁
RETRYABLE = {"timeout", "network", "http_5xx"}


# ---------------------------------------------------------------------------
# 客户端与登录态（阶段一提供；这里只按契约调用）
# ---------------------------------------------------------------------------

def anonymous_client():
    """不带任何 Cookie 的只读客户端：只看得到公开收藏夹。阶段一的登录模块不在时用它。"""
    import httpx
    return httpx.Client(headers={"User-Agent": _UA, "Referer": "https://www.bilibili.com/"},
                        timeout=TIMEOUT_S, follow_redirects=False)


def login_state() -> dict[str, Any]:
    """阶段一 `login.status()` 的结果；模块还没接上 → state=unavailable（不是 logged_out：判不了）。"""
    try:
        from link_brain.sources.bilibili import login  # 阶段一提供
    except ImportError as exc:
        return {"state": "unavailable", "reason": f"B 站登录模块还没接上（{errtext(exc)}），只能读公开收藏夹"}
    try:
        st = login.status()
    except Exception as exc:  # noqa: BLE001 登录态查不清 ≠ 没登录
        return {"state": "unknown", "reason": errtext(exc)[:200]}
    return dict(st) if isinstance(st, dict) else {"state": "unknown", "reason": "login.status() 返回的不是对象"}


def default_client():
    """(client, login_state)：登录了用阶段一带 Cookie 的客户端；否则匿名只读客户端，并在 state 里写清。"""
    st = login_state()
    if st.get("state") == "logged_in":
        from link_brain.sources.bilibili import login
        return login.http_client(), st
    return anonymous_client(), st


def mask_mid(mid: Any) -> str:
    """日志 / 报告里的 mid、收藏夹 id 只露头尾。"""
    s = str(mid or "")
    return s if len(s) <= 4 else f"{s[:2]}***{s[-2:]}"


# ---------------------------------------------------------------------------
# 单次请求：一律回 (data, error)，error 是 {reason, code, http_status, message} 或 None
# ---------------------------------------------------------------------------

def _err(reason: str, message: str, *, code: Any = None, http_status: int | None = None) -> dict[str, Any]:
    return {"reason": reason, "code": code, "http_status": http_status, "message": str(message)[:200]}


def _get(client, url: str, params: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    import httpx
    try:
        resp = client.get(url, params=params)
    except httpx.TimeoutException as exc:
        return None, _err("timeout", errtext(exc))
    except httpx.HTTPError as exc:
        return None, _err("network", errtext(exc))
    status = resp.status_code
    if status in (412, 429):
        return None, _err("rate_limited", f"HTTP {status}：B 站限流 / 拦截了这次请求", http_status=status)
    if status >= 500:
        return None, _err("http_5xx", f"HTTP {status}", http_status=status)
    if status != 200:
        return None, _err("http_error", f"HTTP {status}", http_status=status)
    try:
        body = resp.json()
    except ValueError:
        return None, _err("bad_response", "返回的不是 JSON", http_status=status)
    if not isinstance(body, dict) or "code" not in body:
        return None, _err("bad_response", "返回的 JSON 没有 code", http_status=status)
    code = body.get("code")
    msg = str(body.get("message") or "")
    if code == 0:
        return body.get("data"), None
    if code in RATE_LIMIT_CODES:
        return None, _err("rate_limited", f"B 站风控 / 限流（{code} {msg}）", code=code, http_status=status)
    if code == -101:
        return None, _err("not_logged_in", "B 站说没登录（-101）", code=code, http_status=status)
    if code == -403:
        return None, _err("forbidden", f"无访问权限（-403 {msg}）", code=code, http_status=status)
    if code == 11010:
        return None, _err("not_found", f"收藏夹不存在（11010 {msg}）", code=code, http_status=status)
    if code == -400:
        return None, _err("bad_request", f"请求错误（-400 {msg}）", code=code, http_status=status)
    return None, _err("api_error", f"B 站接口返回 {code} {msg}", code=code, http_status=status)


# ---------------------------------------------------------------------------
# 收藏夹列表
# ---------------------------------------------------------------------------

def _folder_row(raw: dict[str, Any]) -> dict[str, Any]:
    attr = int(raw.get("attr") or 0)
    return {
        "media_id": int(raw.get("id") or 0),
        "fid": int(raw.get("fid") or 0),
        "owner_mid": int(raw.get("mid") or 0),
        "title": str(raw.get("title") or ""),
        "attr": attr,
        "private": bool(attr & 1),          # 位 0：1 = 私密
        "default": not bool(attr & 2),      # 位 1：0 = 默认收藏夹
        "media_count": int(raw.get("media_count") or 0),
    }


def list_folders(client, up_mid: Any) -> dict[str, Any]:
    """某人创建的收藏夹。status：ok / empty（真的 0 个）/ hidden（整个列表不给看）/ error。

    没登录时私密收藏夹不在列表里（接口直接不返回），所以 ok 也不代表「全部」：调用方看 `login` 决定怎么说。"""
    data, err = _get(client, FOLDERS_URL, {"up_mid": up_mid})
    out: dict[str, Any] = {"up_mid": int(up_mid) if str(up_mid).isdigit() else up_mid, "folders": []}
    if err:
        return {**out, "status": "error", "error": err}
    if data is None:
        return {**out, "status": "hidden", "error": _err("hidden", "这个用户的收藏夹列表不公开")}
    rows = [_folder_row(x) for x in (data.get("list") or []) if isinstance(x, dict)]
    count = int(data.get("count") or 0)
    if not rows:
        return {**out, "status": "empty", "count": count}
    return {**out, "status": "ok", "count": count, "folders": rows}


# ---------------------------------------------------------------------------
# 收藏夹内容：逐页
# ---------------------------------------------------------------------------

def _item_row(raw: dict[str, Any]) -> dict[str, Any]:
    typ = int(raw.get("type") or 0)
    attr = int(raw.get("attr") or 0)
    ugc = raw.get("ugc") if isinstance(raw.get("ugc"), dict) else {}
    upper = raw.get("upper") if isinstance(raw.get("upper"), dict) else {}
    row = {
        "bvid": str(raw.get("bvid") or raw.get("bv_id") or ""),
        "id": int(raw.get("id") or 0),                 # 视频 = avid；音频 = auid；合集 = 合集 id
        "kind": KIND_OF_TYPE.get(typ, "other"),
        "type": typ,
        "title": str(raw.get("title") or ""),
        "fav_time": int(raw.get("fav_time") or 0),
        "attr": attr,
        "invalid": attr != 0,
        "invalid_reason": INVALID_OF_ATTR.get(attr, "invalid" if attr else None),
        "page_count": int(raw.get("page") or 0),       # 分 P 数（只是收藏列表里的说法，下载时以视频详情的 pages[] 为准）
        "first_cid": int(ugc.get("first_cid") or 0) or None,
        "upper_mid": int(upper.get("mid") or 0) or None,
        "upper_name": str(upper.get("name") or ""),
        "pubtime": int(raw.get("pubtime") or 0) or None,
        "duration": int(raw.get("duration") or 0) or None,
        # 1101：封面网址（待下载页的卡片用；只是网址，不下载）。B 站给的有 http:// 和 //，统一成 https
        "cover": _https(raw.get("cover")),
    }
    return row


def _https(url: Any) -> str:
    u = str(url or "").strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[len("http://"):]
    return u if u.startswith("https://") else ""


def item_key(item: dict[str, Any]) -> str:
    """收藏项的身份：视频用 BV；没有 BV 的（音频 / 合集）用 `<kind>:<id>`。"""
    return item.get("bvid") or f"{item.get('kind') or 'other'}:{item.get('id')}"


def fetch_page(client, media_id: Any, pn: int, ps: int = PAGE_SIZE_MAX, *,
               sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """读一页。回 {pn, status, info, items, has_more, error}；status：ok / end / forbidden / not_found / error。

    超时 / 断网 / 5xx 重试一次（歇 RETRY_GAP_S）；限流和权限类不重试。"""
    params = {"media_id": media_id, "pn": pn, "ps": ps, "order": "mtime", "type": 0, "tid": 0, "platform": "web"}
    data, err = _get(client, RESOURCE_URL, params)
    if err and err["reason"] in RETRYABLE:
        sleep(RETRY_GAP_S)
        data, err = _get(client, RESOURCE_URL, params)
    page: dict[str, Any] = {"pn": pn, "info": None, "items": [], "has_more": False, "error": None}
    if err:
        status = err["reason"] if err["reason"] in ("forbidden", "not_found") else "error"
        return {**page, "status": status, "error": err}
    if data is None:
        return {**page, "status": "not_found", "error": _err("not_found", "收藏夹不存在（接口回 data=null）")}
    info = data.get("info")
    if not isinstance(info, dict):
        return {**page, "status": "forbidden",
                "error": _err("forbidden", "无访问权限：私密收藏夹（没登录或不是自己的），或收藏夹已删")}
    medias = data.get("medias")
    if medias is not None and not isinstance(medias, list):
        return {**page, "info": info, "status": "error", "error": _err("bad_response", "medias 不是列表")}
    items = [_item_row(m) for m in (medias or []) if isinstance(m, dict)]
    has_more = bool(data.get("has_more"))
    if not items and has_more:
        # 空页却说还有下一页：接口异常，不能当读完
        return {**page, "info": info, "status": "error", "has_more": True,
                "error": _err("empty_page", f"第 {pn} 页是空的，接口却说还有下一页")}
    return {**page, "info": info, "items": items, "has_more": has_more, "status": "ok" if items else "end"}


def iter_folder_items(client, media_id: Any, ps: int = PAGE_SIZE_MAX, *, start_pn: int = 1,
                      page_gap_s: float = PAGE_GAP_S, sleep: Callable[[float], None] = time.sleep,
                      max_pages: int | None = None) -> Iterator[dict[str, Any]]:
    """按 has_more 逐页读（每次 yield 一页，见 fetch_page）。出错的那页也 yield，然后停。"""
    ps = max(1, min(int(ps), PAGE_SIZE_MAX))
    pn = max(1, int(start_pn))
    read = 0
    while True:
        page = fetch_page(client, media_id, pn, ps, sleep=sleep)
        yield page
        read += 1
        if page["status"] != "ok" or not page["has_more"]:
            return
        if max_pages is not None and read >= max_pages:
            return
        pn += 1
        if page_gap_s:
            sleep(page_gap_s)


def fetch_ids(client, media_id: Any, *, sleep: Callable[[float], None] = time.sleep):
    """`x/v3/fav/resource/ids`：一次回整个收藏夹的 [{id, type, bvid}]（收藏时间倒序）。回 (list | None, error)。

    用来核对成员：2026-10-29 实测公开收藏夹没登录时分页列表会悄悄少几条（某页 19 条、has_more 仍为 true），
    204 条只翻出 201 条；这个接口给全了 204 个 id。"""
    data, err = _get(client, IDS_URL, {"media_id": media_id, "platform": "web"})
    if err and err["reason"] in RETRYABLE:
        sleep(RETRY_GAP_S)
        data, err = _get(client, IDS_URL, {"media_id": media_id, "platform": "web"})
    if err:
        return None, err
    if not isinstance(data, list):
        return None, _err("bad_response", "全部 id 接口没给列表")
    rows = []
    for x in data:
        if not isinstance(x, dict):
            continue
        typ = int(x.get("type") or 0)
        rows.append({"id": int(x.get("id") or 0), "type": typ, "kind": KIND_OF_TYPE.get(typ, "other"),
                     "bvid": str(x.get("bvid") or x.get("bv_id") or "")})
    return rows, None


def _stub(row: dict[str, Any]) -> dict[str, Any]:
    """分页列表没给、全部 id 接口有的那条：只知道 id / BV，详情空着，标 listed=false。"""
    return {"bvid": row["bvid"], "id": row["id"], "kind": row["kind"], "type": row["type"], "title": "",
            "fav_time": None, "attr": None, "invalid": False, "invalid_reason": None, "page_count": 0,
            "first_cid": None, "upper_mid": None, "upper_name": "", "pubtime": None, "duration": None,
            "listed": False}


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------

def sync_root() -> Path:
    return storage.archive_root() / SYNC_DIRNAME


def snapshot_name(owner_mid: Any, media_id: Any) -> str:
    return f"{owner_mid or 'unknown'}-{media_id}"


def snapshot_path(owner_mid: Any, media_id: Any) -> Path:
    return sync_root() / "folders" / f"{snapshot_name(owner_mid, media_id)}.json"


def last_complete_path(owner_mid: Any, media_id: Any) -> Path:
    return sync_root() / "folders" / f"{snapshot_name(owner_mid, media_id)}.last-complete.json"


def relations_path() -> Path:
    return sync_root() / "relations.json"


def vault_rel(path: Path) -> str:
    """相对 vault 的 POSIX 路径（报告 / JSON 里只用这个，不露本机目录）。"""
    try:
        return Path(path).resolve().relative_to(storage.vault_root()).as_posix()
    except ValueError:
        return Path(path).name


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = storage.read_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_snapshot(owner_mid: Any, media_id: Any) -> dict[str, Any] | None:
    return _read(snapshot_path(owner_mid, media_id))


def load_last_complete(owner_mid: Any, media_id: Any) -> dict[str, Any] | None:
    return _read(last_complete_path(owner_mid, media_id))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _owner_of(info: dict[str, Any] | None) -> int | None:
    if not isinstance(info, dict):
        return None
    upper = info.get("upper") if isinstance(info.get("upper"), dict) else {}
    mid = upper.get("mid") or info.get("mid")
    return int(mid) if mid else None


def _finish(snap: dict[str, Any]) -> dict[str, Any]:
    """按已读页定 complete / status：没有出错页、最后一页 has_more=false、去重条数 == media_count 才算完整
    （分页少的条目已由 _reconcile 按全部 id 接口补成 listed=false 的占位）。"""
    expected = snap.get("media_count")
    got = len(snap["items"])
    snap["item_count"] = got
    if snap.get("error"):
        reason = snap["error"].get("reason")
        if not snap["pages_read"]:
            first_page_reasons = ("forbidden", "not_found", "not_logged_in", "rate_limited")
            snap["status"] = reason if reason in first_page_reasons else "error"
        else:
            snap["status"] = "partial"
        snap["complete"] = False
    elif snap.get("reached_end") and expected is not None and got != expected:
        snap["status"] = "partial"
        snap["complete"] = False
        snap["error"] = _err("count_mismatch", f"总数对不上：收藏夹说 {expected} 条，翻完只读到 {got} 条（去重后）")
        snap["count_mismatch"] = {"expected": expected, "got": got, "raw": snap.get("raw_count", got)}
    elif snap.get("reached_end"):
        snap["complete"] = True
        snap["status"] = "empty" if got == 0 else "complete"
    else:
        snap["complete"] = False
        snap["status"] = "partial"
    snap.pop("in_progress", None)
    return snap


def _checkpoint(snap: dict[str, Any]) -> None:
    storage.write_json(snapshot_path(snap.get("owner_mid"), snap["media_id"]), snap)


def scan_folder(client, media_id: Any, *, owner_mid: Any = None, resume: bool = True, ps: int = PAGE_SIZE_MAX,
                page_gap_s: float = PAGE_GAP_S, sleep: Callable[[float], None] = time.sleep,
                max_pages: int | None = None, now: str | None = None,
                log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """扫一个收藏夹：逐页读、每页原子落盘检查点，读完核对总数，完整才覆盖「上次完整快照」。

    resume=True 且上次扫描没完成、收藏夹总数没变：只从缺的页接着读（已读页的条目保留）；
    总数变了 / 上次已完整：从第 1 页重来（收藏是按收藏时间倒序，总数一变页码就错位）。
    max_pages：本轮最多读几页（大收藏夹分轮读；没读完 = partial，下轮接着）。
    回快照 dict（同时写盘）；拿不到这个收藏夹的扫描锁 → status=busy，什么都不写。
    要对比和关系表用 sync_folder（同一把锁里先取上次完整快照再覆盖）。"""
    return sync_folder(client, media_id, owner_mid=owner_mid, resume=resume, ps=ps, page_gap_s=page_gap_s,
                       sleep=sleep, max_pages=max_pages, now=now, log=log, relations=False)["snapshot"]


def sync_folder(client, media_id: Any, *, owner_mid: Any = None, resume: bool = True, ps: int = PAGE_SIZE_MAX,
                page_gap_s: float = PAGE_GAP_S, sleep: Callable[[float], None] = time.sleep,
                max_pages: int | None = None, now: str | None = None,
                log: Callable[[str], None] | None = None, relations: bool = True) -> dict[str, Any]:
    """扫描 + 对比 + 关系表，一把锁里做完：{snapshot, prev_complete_at, diff, relations, summary}。

    对比基准是**这次扫描之前**的上次完整快照；这次完整才覆盖它。"""
    media_id = int(media_id)
    lock = f"bilibili-fav-{media_id}"
    try:
        with storage.file_lock(lock, wait_s=0, owner=lock):
            snap = _scan_locked(client, media_id, owner_mid=owner_mid, resume=resume, ps=ps,
                                page_gap_s=page_gap_s, sleep=sleep, max_pages=max_pages, now=now, log=log)
            prev = load_last_complete(snap.get("owner_mid"), media_id) if snap.get("owner_mid") else None
            diff = diff_snapshot(prev, snap)
            if snap["complete"]:
                storage.write_json(last_complete_path(snap["owner_mid"], media_id), snap)
            rel = update_relations(snap, diff) if relations else None
            return {"snapshot": snap, "prev_complete_at": (prev or {}).get("fetched_at"), "diff": diff,
                    "relations": rel, "summary": summarize(snap)}
    except storage.LockBusy:
        snap = {"media_id": media_id, "owner_mid": owner_mid, "status": "busy", "complete": False,
                "error": _err("busy", "这个收藏夹正在被另一个任务扫描")}
        return {"snapshot": snap, "prev_complete_at": None, "diff": None, "relations": None,
                "summary": summarize(snap)}


def _scan_locked(client, media_id: int, *, owner_mid, resume, ps, page_gap_s, sleep, max_pages, now,
                 log=None) -> dict[str, Any]:
    say = log or (lambda _m: None)
    fetched_at = now or _now_iso()
    ps = max(1, min(int(ps), PAGE_SIZE_MAX))
    say(f"扫收藏夹 {mask_mid(media_id)}：读第 1 页")
    first = fetch_page(client, media_id, 1, ps, sleep=sleep)
    info = first.get("info")
    owner = _owner_of(info) or (int(owner_mid) if owner_mid else None)
    snap: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "owner_mid": owner,
        "media_id": media_id,
        "fid": int(info.get("fid") or 0) if isinstance(info, dict) else None,
        "title": str(info.get("title") or "") if isinstance(info, dict) else "",
        "private": bool(int(info.get("attr") or 0) & 1) if isinstance(info, dict) else None,
        "fetched_at": fetched_at,
        "started_at": fetched_at,
        "complete": False,
        "status": "scanning",
        "in_progress": True,
        "media_count": int(info.get("media_count") or 0) if isinstance(info, dict) else None,
        "page_size": ps,
        "pages_read": [],
        "missing_pages": [],
        "reached_end": False,
        "raw_count": 0,
        "error": None,
        "items": [],
    }
    if first["status"] in ("forbidden", "not_found") or (first["status"] == "error" and info is None):
        snap["error"] = first["error"]
        snap["missing_pages"] = [1]
        _finish(snap)
        _checkpoint(snap)
        return snap

    prev = load_snapshot(owner, media_id) if resume else None
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    start_pn = 1
    if (prev and not prev.get("complete") and not prev.get("reached_end") and prev.get("pages_read")
            and prev.get("media_count") == snap["media_count"] and prev.get("page_size") == ps):
        # 续读：保留上次读到的页，从第一个没读的页开始（第 1 页刚读过，总数一致才走到这）
        snap["started_at"] = prev.get("started_at") or fetched_at
        snap["pages_read"] = sorted(int(p) for p in prev["pages_read"])
        snap["raw_count"] = int(prev.get("raw_count") or 0)
        for it in prev.get("items") or []:
            k = item_key(it)
            if k not in by_key:
                order.append(k)
            by_key[k] = it
        start_pn = next((n for n in range(1, max(snap["pages_read"]) + 2) if n not in snap["pages_read"]), 1)
        snap["resumed_from"] = start_pn
        say(f"接着上次读：已有 {len(snap['pages_read'])} 页，从第 {start_pn} 页开始")

    def absorb(page: dict[str, Any]) -> None:
        snap["pages_read"].append(page["pn"])
        snap["pages_read"] = sorted(set(snap["pages_read"]))
        snap["raw_count"] += len(page["items"])
        for it in page["items"]:
            k = item_key(it)
            if k not in by_key:
                order.append(k)
            by_key[k] = it
        snap["items"] = [by_key[k] for k in order]
        if not page["has_more"]:
            snap["reached_end"] = True

    if start_pn == 1:
        pages: Iterator[dict[str, Any]] = iter([first])
        if first["status"] == "ok" and first["has_more"] and (max_pages is None or max_pages > 1):
            if page_gap_s:
                sleep(page_gap_s)
            pages = _chain(first, iter_folder_items(client, media_id, ps, start_pn=2, page_gap_s=page_gap_s,
                                                    sleep=sleep,
                                                    max_pages=None if max_pages is None else max_pages - 1))
    else:
        if page_gap_s:
            sleep(page_gap_s)
        pages = iter_folder_items(client, media_id, ps, start_pn=start_pn, page_gap_s=page_gap_s, sleep=sleep,
                                  max_pages=max_pages)
    for page in pages:
        if page["status"] in ("ok", "end"):
            absorb(page)
            say(f"第 {page['pn']} 页：{len(page['items'])} 条（累计 {len(snap['items'])}/{snap['media_count']}）")
            snap["fetched_at"] = _now_iso() if now is None else now
            _checkpoint(snap)
            continue
        snap["error"] = page["error"]
        snap["missing_pages"] = [page["pn"]]
        break
    if not snap["reached_end"] and not snap["error"] and snap["pages_read"]:
        snap["missing_pages"] = [max(snap["pages_read"]) + 1]   # 本轮预算到了：下一页留给下轮
    if snap["reached_end"] and not snap["error"] and len(snap["items"]) != snap["media_count"]:
        _reconcile(client, snap, sleep=sleep, say=say)
    _finish(snap)
    _checkpoint(snap)
    return snap


def _reconcile(client, snap: dict[str, Any], *, sleep, say) -> None:
    """翻完了但条数 ≠ media_count：拿全部 id 接口核对成员。

    全部 id 正好 media_count 个、分页读到的每条都在里面 → 按 id 接口的顺序重排，分页没给的补占位（listed=false），
    `hidden_in_list` 记下是哪几条；对不上（id 接口失败 / 个数不对 / 分页里有 id 接口没有的）→ 不补，交给 _finish 判 partial。"""
    rows, err = fetch_ids(client, snap["media_id"], sleep=sleep)
    if err or rows is None:
        snap["ids_check"] = {"ok": False, "error": err}
        return
    listed = {item_key(x): x for x in snap["items"]}
    id_keys = [item_key(r) for r in rows]
    in_ids = set(id_keys)
    extra = [k for k in listed if k not in in_ids]
    snap["ids_check"] = {"ok": len(in_ids) == snap["media_count"] and not extra,
                         "ids": len(in_ids), "listed": len(listed), "listed_not_in_ids": extra[:20]}
    if not snap["ids_check"]["ok"]:
        return
    hidden = [k for k in id_keys if k not in listed]
    snap["items"] = [listed.get(k) or _stub(r) for k, r in zip(id_keys, rows)]
    snap["hidden_in_list"] = hidden
    say(f"分页少了 {len(hidden)} 条，全部 id 接口核对后补了占位（只有 BV，详情待登录后补）")


def _chain(first, rest):
    yield first
    yield from rest


def summarize(snap: dict[str, Any]) -> dict[str, Any]:
    """预览：多少条、多少个 BV、失效几条、非视频几条、预计多少 P（收藏列表给的分 P 数之和，下载前以视频详情为准）。"""
    items = snap.get("items") or []
    videos = [x for x in items if x.get("kind") == "video" and x.get("bvid")]
    live = [x for x in videos if not x.get("invalid")]
    return {
        "media_id": snap.get("media_id"), "title": snap.get("title"), "status": snap.get("status"),
        "complete": bool(snap.get("complete")), "media_count": snap.get("media_count"),
        "items": len(items), "raw_count": snap.get("raw_count", len(items)),
        "pages_read": len(snap.get("pages_read") or []), "missing_pages": snap.get("missing_pages") or [],
        "bv": len({x["bvid"] for x in videos}), "bv_live": len({x["bvid"] for x in live}),
        "invalid": sum(1 for x in items if x.get("invalid")),
        "hidden_in_list": len(snap.get("hidden_in_list") or []),
        "non_video": sum(1 for x in items if x.get("kind") != "video"),
        "estimated_pages": sum(max(1, int(x.get("page_count") or 1)) for x in live),
    }


def dedupe_bvids(snaps: list[dict[str, Any]]) -> dict[str, Any]:
    """多个收藏夹合起来：去重前多少条、去重后多少个 BV、哪些 BV 在不止一个收藏夹里（只下载一次的依据）。"""
    where: dict[str, list[int]] = {}
    total = 0
    for s in snaps:
        for it in s.get("items") or []:
            if not it.get("bvid"):
                continue
            total += 1
            where.setdefault(it["bvid"], []).append(int(s.get("media_id") or 0))
    shared = {bv: sorted(set(ids)) for bv, ids in where.items() if len(set(ids)) > 1}
    return {"before": total, "after": len(where), "shared": shared}


# ---------------------------------------------------------------------------
# 对比
# ---------------------------------------------------------------------------

def diff_snapshot(prev: dict[str, Any] | None, curr: dict[str, Any]) -> dict[str, Any]:
    """上次完整快照 vs 这次扫描 → new / same / unfavorited / unavailable（都是 item_key 列表）。

    - unavailable：这次读到、但已失效（不进下载队列，保留已有归档）；
    - new：这次读到、没失效、上次没有；same：两边都有、没失效；
    - unfavorited：上次有、这次没有。**只有这次是完整扫描才算**；部分扫描一律为空（`unfavorited_blocked` 写原因）。
      完整扫描但比上次少一半以上 → 仍列出，但 `hold=true`（待核实，关系表先不解除）。"""
    if prev and (str(prev.get("media_id")) != str(curr.get("media_id"))
                 or (prev.get("owner_mid") and curr.get("owner_mid")
                     and str(prev.get("owner_mid")) != str(curr.get("owner_mid")))):
        raise ValueError("两份快照不是同一个收藏夹（owner_mid / media_id 对不上）")
    prev_keys = {item_key(x) for x in (prev or {}).get("items") or []}
    new: list[str] = []
    same: list[str] = []
    unavailable: list[str] = []
    seen: set[str] = set()
    for it in curr.get("items") or []:
        k = item_key(it)
        if k in seen:
            continue
        seen.add(k)
        if it.get("invalid"):
            unavailable.append(k)
        elif k in prev_keys:
            same.append(k)
        else:
            new.append(k)
    out: dict[str, Any] = {"new": new, "same": same, "unfavorited": [], "unavailable": unavailable,
                           "unfavorited_blocked": None, "hold": False}
    if not curr.get("complete"):
        out["unfavorited_blocked"] = f"这次扫描没读全（{curr.get('status')}），不判断取消收藏"
        return out
    if not prev:
        return out
    gone = [k for k in (item_key(x) for x in prev.get("items") or []) if k not in seen]
    out["unfavorited"] = list(dict.fromkeys(gone))
    if len(prev_keys) >= SUSPICIOUS_MIN and len(seen) < len(prev_keys) * SUSPICIOUS_DROP:
        out["hold"] = True
        out["hold_reason"] = f"比上次少太多（{len(prev_keys)} → {len(seen)}），待核实，先不解除收藏关系"
    return out


# ---------------------------------------------------------------------------
# 收藏关系表
# ---------------------------------------------------------------------------

def relation_key(owner_mid: Any, media_id: Any, key: str) -> str:
    return f"{owner_mid}:{media_id}:{key}"


def update_relations(snap: dict[str, Any], diff: dict[str, Any] | None = None, *,
                     now: str | None = None, deactivate_missing: bool = True) -> dict[str, int]:
    """把一次扫描写进关系表（锁内读改写）。读到的：新建或刷新 last_seen / fav_time / active=true；
    完整扫描（且对比没有 hold）里不在了的：active=false + inactive_since。从不删行。回各类计数。
    1031：deactivate_missing=False（稍后再看用）= 不在了的也不解除——看完就移出稍后再看是常态，本地那条仍归「稍后再看」专辑。"""
    owner, media_id = snap.get("owner_mid"), snap.get("media_id")
    stamp = now or snap.get("fetched_at") or _now_iso()
    counts = {"added": 0, "seen": 0, "reactivated": 0, "deactivated": 0, "held": 0}
    if not owner or not media_id:
        return counts
    deactivate = deactivate_missing and bool(snap.get("complete")) and not (diff or {}).get("hold")
    if snap.get("complete") and (diff or {}).get("hold"):
        counts["held"] = len((diff or {}).get("unfavorited") or [])

    def apply(data: dict[str, Any]) -> None:
        data.setdefault("schema_version", SCHEMA_VERSION)
        rel = data.setdefault("relations", {})
        present: set[str] = set()
        for it in snap.get("items") or []:
            k = relation_key(owner, media_id, item_key(it))
            present.add(k)
            row = rel.get(k)
            if row is None:
                rel[k] = {"owner_mid": owner, "media_id": media_id, "bvid": it.get("bvid") or None,
                          "item_key": item_key(it), "folder_title": snap.get("title") or "",
                          "fav_time": it.get("fav_time") or None, "first_seen": stamp, "last_seen": stamp,
                          "active": True, "inactive_since": None}
                counts["added"] += 1
                continue
            if not row.get("active"):
                counts["reactivated"] += 1
            row.update(folder_title=snap.get("title") or row.get("folder_title") or "",
                       fav_time=it.get("fav_time") or row.get("fav_time"), last_seen=stamp,
                       active=True, inactive_since=None)
            counts["seen"] += 1
        if deactivate:
            prefix = f"{owner}:{media_id}:"
            for k, row in rel.items():
                if k.startswith(prefix) and k not in present and row.get("active"):
                    row.update(active=False, inactive_since=stamp)
                    counts["deactivated"] += 1
        data["updated_at"] = stamp

    storage.update_json(relations_path(), apply, lock_name="bilibili-relations", missing_ok=True)
    return counts


def load_relations() -> dict[str, dict[str, Any]]:
    data = _read(relations_path()) or {}
    rel = data.get("relations")
    return rel if isinstance(rel, dict) else {}


def relations_for(bvid: str) -> list[dict[str, Any]]:
    """一个 BV 在哪些收藏夹里（含已不在的，看 active）。"""
    return [row for row in load_relations().values() if row.get("bvid") == bvid]


# ---------------------------------------------------------------------------
# 收藏夹链接
# ---------------------------------------------------------------------------

_BILI_HOSTS = ("bilibili.com",)
_ML_RX = re.compile(r"(?:^|[/=])ml(\d{3,})(?:$|[/?#&])", re.I)


def parse_folder_url(text: str) -> dict[str, Any] | None:
    """收藏夹链接 / id → {media_id, owner_mid, kind, input}；认不出 → None。

    认的形状：`space.bilibili.com/<mid>/favlist?fid=<media_id>[&ftype=create]`、
    `www.bilibili.com/medialist/detail/ml<id>`、`.../medialist/play/ml<id>`、`www.bilibili.com/list/ml<id>`、
    裸 `ml<id>`、裸数字（当完整 media_id）、`fid=<id>`。`ftype=collect` 是收藏的合集，不是收藏夹 → kind=collection。
    别的站、b23.tv 短链（要联网展开，留给入口层）一律 None。"""
    s = (text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{3,}", s):
        return {"media_id": int(s), "owner_mid": None, "kind": "folder", "input": s}
    m = re.fullmatch(r"(?:ml|fid=)(\d{3,})", s, re.I)
    if m:
        return {"media_id": int(m.group(1)), "owner_mid": None, "kind": "folder", "input": s}
    found = re.search(r"https?://[^\s<>\"'）)]+", s)
    if not found and re.match(r"(?:[\w-]+\.)*bilibili\.com/", s, re.I):
        found = re.match(r"\S+", "https://" + s)
    if not found:
        return None
    url = found.group(0)
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _BILI_HOSTS):
        return None
    qs = parse_qs(u.query)
    owner = None
    m = re.match(r"/(\d+)/favlist", u.path)
    if host.startswith("space.") and m:
        owner = int(m.group(1))
        fid = (qs.get("fid") or [""])[0]
        if not fid.isdigit():
            return {"media_id": None, "owner_mid": owner, "kind": "owner", "input": url}  # 只给了人：列他的收藏夹
        kind = "collection" if (qs.get("ftype") or [""])[0] == "collect" else "folder"
        return {"media_id": int(fid), "owner_mid": owner, "kind": kind, "input": url}
    m = _ML_RX.search(u.path + ("?" + u.query if u.query else ""))
    if m:
        return {"media_id": int(m.group(1)), "owner_mid": owner, "kind": "folder", "input": url}
    return None


# ---------------------------------------------------------------------------
# 命令行（只读）：python -m link_brain.sources.bilibili.favorites list <mid> | scan <链接或 id> [--max-pages N]
# 入口层的 `link_brain bilibili ...` 子命令等阶段一的 cli 合进来再接；stdout 只有最后一行 JSON，进度走 stderr。
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    from link_brain import read as read_mod

    ap = argparse.ArgumentParser(prog="python -m link_brain.sources.bilibili.favorites")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="列某人创建的收藏夹（没登录只看得到公开的）")
    p_list.add_argument("mid")
    p_scan = sub.add_parser("scan", help="扫一个收藏夹，写快照和关系表（不下载）")
    p_scan.add_argument("target", help="收藏夹链接 / ml<id> / media_id")
    p_scan.add_argument("--max-pages", type=int, default=None)
    p_scan.add_argument("--no-resume", action="store_true")
    p_scan.add_argument("--no-relations", action="store_true")
    args = ap.parse_args(argv)

    client, login = default_client()
    print(f"B 站登录态：{login.get('state')} {login.get('reason') or ''}".rstrip(), file=sys.stderr)
    if args.cmd == "list":
        res = list_folders(client, args.mid)
        ok = res["status"] in ("ok", "empty")
        msg = {"ok": f"{len(res['folders'])} 个收藏夹", "empty": "这个人没有（看得到的）收藏夹",
               "hidden": "这个人的收藏夹列表不公开"}.get(res["status"]) or (res.get("error") or {}).get("message", "")
        read_mod.dump_json(read_mod.outcome({**res, "login": login.get("state")}, ok=ok, message=msg))
        return 0 if ok else 1
    parsed = parse_folder_url(args.target)
    if not parsed or not parsed.get("media_id") or parsed.get("kind") != "folder":
        why = "这是收藏的合集，不是收藏夹（批次 D 再接）" if parsed and parsed.get("kind") == "collection" \
            else "认不出收藏夹链接 / id"
        read_mod.dump_json(read_mod.outcome({"target": args.target}, ok=False, message=why))
        return 2

    res = sync_folder(client, parsed["media_id"], owner_mid=parsed.get("owner_mid"), resume=not args.no_resume,
                      max_pages=args.max_pages, relations=not args.no_relations,
                      log=lambda m: print(m, file=sys.stderr))
    snap, d = res["snapshot"], res["diff"]
    out = {"summary": res["summary"], "prev_complete_at": res["prev_complete_at"],
           "snapshot": vault_rel(snapshot_path(snap.get("owner_mid"), snap["media_id"])),
           "diff": {k: (len(v) if isinstance(v, list) else v) for k, v in (d or {}).items()},
           "relations": res["relations"], "login": login.get("state"), "error": snap.get("error")}
    ok = bool(snap.get("complete"))
    if ok:
        msg = f"读完 {snap.get('item_count', 0)} 条（{len(snap.get('pages_read') or [])} 页）"
    elif snap.get("error"):
        msg = f"没读全：{snap['error'].get('message') or snap.get('status')}"
    else:
        msg = f"本轮读了 {len(snap.get('pages_read') or [])} 页，下次从第 {(snap.get('missing_pages') or ['?'])[0]} 页接着读"
    read_mod.dump_json(read_mod.outcome(out, ok=ok, message=msg))
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
