"""B 站收藏夹只读发现 + 快照 + 对比 + 关系表（第二阶段批次 A）。

网络全是 httpx.MockTransport（不出本机）；样本是 tests/fixtures/bilibili_fav_*.json 里编的脱敏数据，
结构照 2026-10-29 匿名实测的返回。vault / ~/.link-brain 由 conftest 指到 tmp。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import httpx
import pytest

from link_brain import storage
from link_brain.sources.bilibili import favorites as fav

FIX = Path(__file__).parent / "fixtures"
OWNER = 900001


def _fixture(name: str):
    return json.loads((FIX / f"bilibili_fav_{name}.json").read_text("utf-8"))


PAGE = _fixture("page")
MEDIA = PAGE["data"]["medias"][0]
INFO = PAGE["data"]["info"]


def media(n: int, *, attr: int = 0, page: int = 1, typ: int = 2, bvid: str | None = None) -> dict:
    m = copy.deepcopy(MEDIA)
    bv = bvid if bvid is not None else f"BV1fake{n:05d}"
    m.update(id=100000000000 + n, type=typ, attr=attr, page=page, fav_time=1700000000 + 10_000 - n,
             bvid=bv if typ == 2 else "", bv_id=bv if typ == 2 else "", title="已失效视频" if attr else f"样本视频 {n}")
    m["ugc"] = {"first_cid": 200000000000 + n}
    return m


class FakeBili:
    """假 B 站：收藏夹 media_id → 条目（收藏时间倒序）。可以按 (media_id, pn) 塞固定回复、藏条目、改总数。"""

    def __init__(self):
        self.folders: dict[int, list[dict]] = {}
        self.counts: dict[int, int] = {}          # 改 info.media_count（默认 = 条目数）
        self.hidden: dict[int, set[str]] = {}     # 分页列表里不给、全部 id 接口照给
        self.forbidden: set[int] = set()
        self.not_found: set[int] = set()
        self.page_override: dict[tuple[int, int], list] = {}   # 依次弹出：httpx.Response / Exception / dict(data)
        self.ids_override: dict[int, object] = {}
        self.folders_reply: object = _fixture("folders")
        self.calls: list[tuple[str, dict]] = []
        self.cookies_seen: list[str] = []

    def add(self, media_id: int, items: list[dict], *, title: str = "样本收藏夹"):
        self.folders[media_id] = items
        self._titles = getattr(self, "_titles", {})
        self._titles[media_id] = title

    def info(self, media_id: int) -> dict:
        i = copy.deepcopy(INFO)
        i.update(id=media_id, fid=media_id // 100, title=self._titles.get(media_id, "样本收藏夹"),
                 media_count=self.counts.get(media_id, len(self.folders.get(media_id, []))))
        return i

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append((request.url.path, params))
        self.cookies_seen.append(request.headers.get("cookie", ""))
        path = request.url.path
        if path.endswith("/folder/created/list-all"):
            return _reply(self.folders_reply)
        media_id = int(params["media_id"])
        if path.endswith("/resource/ids"):
            ov = self.ids_override.get(media_id)
            if ov is not None:
                return _reply(ov)
            rows = [{"id": m["id"], "type": m["type"], "bv_id": m["bvid"], "bvid": m["bvid"]}
                    for m in self.folders.get(media_id, [])]
            return httpx.Response(200, json={"code": 0, "message": "OK", "ttl": 1, "data": rows})
        pn, ps = int(params.get("pn", 1)), int(params["ps"])
        queue = self.page_override.get((media_id, pn))
        if queue:
            return _reply(queue.pop(0), info=self.info(media_id))
        if media_id in self.forbidden:
            return httpx.Response(200, json=_fixture("forbidden"))
        if media_id in self.not_found:
            return httpx.Response(200, json=_fixture("not_found"))
        hide = self.hidden.get(media_id, set())
        all_items = self.folders[media_id]
        chunk = all_items[(pn - 1) * ps: pn * ps]
        shown = [m for m in chunk if m["bvid"] not in hide]
        has_more = pn * ps < len(all_items)
        return httpx.Response(200, json={"code": 0, "message": "OK", "ttl": 1, "data": {
            "info": self.info(media_id), "medias": shown or None, "has_more": has_more, "ttl": 1}})


def _reply(spec, info=None) -> httpx.Response:
    if isinstance(spec, httpx.Response):
        return spec
    if isinstance(spec, Exception):
        raise spec
    if isinstance(spec, dict) and "data_medias" in spec:   # 简写：只给这页的 medias / has_more
        return httpx.Response(200, json={"code": 0, "message": "OK", "ttl": 1, "data": {
            "info": info, "medias": spec["data_medias"], "has_more": spec.get("has_more", False), "ttl": 1}})
    return httpx.Response(200, json=spec)


@pytest.fixture
def bili():
    return FakeBili()


def client_for(fake: FakeBili, **kw) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake), **kw)


def scan(fake, media_id, **kw):
    kw.setdefault("page_gap_s", 0)
    kw.setdefault("sleep", lambda _s: None)
    return fav.sync_folder(client_for(fake), media_id, **kw)


def pages_called(fake, media_id) -> list[int]:
    return [int(p["pn"]) for path, p in fake.calls
            if path.endswith("/resource/list") and int(p["media_id"]) == media_id]


# ---------------------------------------------------------------------------
# 翻页
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n, pages", [(1, 1), (20, 1), (21, 2), (45, 3)])
def test_paging_reads_every_item_once(bili, n, pages):
    bili.add(1000101, [media(i) for i in range(1, n + 1)])
    res = scan(bili, 1000101)
    snap = res["snapshot"]
    assert snap["complete"] is True and snap["status"] == "complete"
    assert snap["pages_read"] == list(range(1, pages + 1))
    assert pages_called(bili, 1000101) == list(range(1, pages + 1))
    assert [x["bvid"] for x in snap["items"]] == [f"BV1fake{i:05d}" for i in range(1, n + 1)]
    assert snap["media_count"] == n == snap["item_count"]
    assert snap["owner_mid"] == OWNER and snap["missing_pages"] == []
    # 落盘：最近一次 + 上次完整，路径是 <owner>-<media>
    assert fav.load_snapshot(OWNER, 1000101)["complete"] is True
    assert fav.load_last_complete(OWNER, 1000101)["item_count"] == n
    assert fav.vault_rel(fav.snapshot_path(OWNER, 1000101)) == \
        f"_archive/bilibili-sync/folders/{OWNER}-1000101.json"


def test_item_fields_invalid_and_multi_p(bili):
    bili.add(1000101, [media(1, page=3), media(2, attr=9), media(3, attr=1), media(4, typ=21)])
    snap = scan(bili, 1000101)["snapshot"]
    by = {fav.item_key(x): x for x in snap["items"]}
    assert by["BV1fake00001"]["page_count"] == 3 and by["BV1fake00001"]["first_cid"] == 200000000001
    assert by["BV1fake00002"]["invalid_reason"] == "up_deleted"
    assert by["BV1fake00003"]["invalid_reason"] == "deleted"
    assert "collection:100000000004" in by          # 合集不丢，单独标 kind
    s = fav.summarize(snap)
    assert (s["bv"], s["bv_live"], s["invalid"], s["non_video"], s["estimated_pages"]) == (3, 1, 2, 1, 3)


def test_page_size_capped_at_20(bili):
    bili.add(1000101, [media(i) for i in range(1, 26)])
    scan(bili, 1000101, ps=50)
    assert {p["ps"] for path, p in bili.calls if path.endswith("/resource/list")} == {"20"}


# ---------------------------------------------------------------------------
# 断页 / 总数不符 / 空 / 无权限
# ---------------------------------------------------------------------------

def _seed_complete(bili, media_id, n):
    bili.add(media_id, [media(i) for i in range(1, n + 1)])
    first = scan(bili, media_id)["snapshot"]
    assert first["complete"]
    bili.calls.clear()
    return first


@pytest.mark.parametrize("bad", [
    httpx.Response(412, text="blocked"),
    httpx.Response(429, text="slow down"),
    httpx.Response(200, json={"code": -412, "message": "请求被拦截"}),
    httpx.Response(200, json={"code": -403, "message": "访问权限不足"}),
])
def test_broken_page_is_partial_and_keeps_last_complete(bili, bad):
    first = _seed_complete(bili, 1000101, 45)
    bili.page_override[(1000101, 2)] = [bad]
    res = scan(bili, 1000101)
    snap = res["snapshot"]
    assert snap["complete"] is False and snap["status"] == "partial"
    assert snap["pages_read"] == [1] and snap["missing_pages"] == [2]
    assert pages_called(bili, 1000101) == [1, 2]                    # 限流 / 无权限不重试、不往后翻
    assert fav.load_last_complete(OWNER, 1000101)["fetched_at"] == first["fetched_at"]
    assert fav.load_last_complete(OWNER, 1000101)["item_count"] == 45
    assert res["diff"]["unfavorited"] == [] and res["diff"]["unfavorited_blocked"]
    # 关系表：没读到的那些仍是 active（部分扫描不解除）
    assert all(r["active"] for r in fav.load_relations().values())


def test_timeout_retries_once_then_continues(bili):
    bili.add(1000101, [media(i) for i in range(1, 30)])
    bili.page_override[(1000101, 2)] = [httpx.ReadTimeout("slow")]
    slept = []
    snap = scan(bili, 1000101, sleep=slept.append)["snapshot"]
    assert snap["complete"] is True
    assert pages_called(bili, 1000101) == [1, 2, 2]
    assert fav.RETRY_GAP_S in slept


def test_timeout_twice_is_partial(bili):
    bili.add(1000101, [media(i) for i in range(1, 30)])
    bili.page_override[(1000101, 2)] = [httpx.ReadTimeout("slow"), httpx.ConnectError("down")]
    snap = scan(bili, 1000101)["snapshot"]
    assert snap["status"] == "partial" and snap["error"]["reason"] == "network"
    assert snap["missing_pages"] == [2] and len(snap["items"]) == 20


def test_empty_page_with_has_more_is_partial(bili):
    bili.add(1000101, [media(i) for i in range(1, 45)])
    bili.page_override[(1000101, 2)] = [{"data_medias": None, "has_more": True}]
    snap = scan(bili, 1000101)["snapshot"]
    assert snap["status"] == "partial" and snap["error"]["reason"] == "empty_page"
    assert snap["missing_pages"] == [2]


def test_count_mismatch_never_complete(bili):
    bili.add(1000101, [media(i) for i in range(1, 22)])
    bili.counts[1000101] = 25                              # 说 25 条，翻完只有 21
    res = scan(bili, 1000101)
    snap = res["snapshot"]
    assert snap["complete"] is False and snap["error"]["reason"] == "count_mismatch"
    assert snap["count_mismatch"] == {"expected": 25, "got": 21, "raw": 21}
    assert snap["ids_check"]["ok"] is False                # id 接口也只有 21 个：补不上
    assert not fav.last_complete_path(OWNER, 1000101).exists()
    assert res["diff"]["unfavorited"] == []


def test_count_mismatch_when_ids_endpoint_fails(bili):
    bili.add(1000101, [media(i) for i in range(1, 25)])
    bili.hidden[1000101] = {"BV1fake00003"}
    bili.ids_override[1000101] = httpx.Response(412, text="blocked")
    snap = scan(bili, 1000101)["snapshot"]
    assert snap["complete"] is False and snap["status"] == "partial"
    assert snap["ids_check"]["ok"] is False


def test_items_hidden_from_list_are_reconciled_by_ids(bili):
    """实测：没登录时分页会悄悄少条（某页 19 条、has_more 仍 true），全部 id 接口给全。"""
    bili.add(1000101, [media(i) for i in range(1, 46)])
    bili.hidden[1000101] = {"BV1fake00003", "BV1fake00030"}
    snap = scan(bili, 1000101)["snapshot"]
    assert snap["complete"] is True and snap["raw_count"] == 43 and snap["item_count"] == 45
    assert snap["hidden_in_list"] == ["BV1fake00003", "BV1fake00030"]
    stub = next(x for x in snap["items"] if x["bvid"] == "BV1fake00003")
    assert stub["listed"] is False and stub["title"] == ""
    assert [x["bvid"] for x in snap["items"]][:4] == ["BV1fake00001", "BV1fake00002", "BV1fake00003", "BV1fake00004"]
    assert fav.summarize(snap)["hidden_in_list"] == 2


def test_listed_item_missing_from_ids_is_not_complete(bili):
    bili.add(1000101, [media(i) for i in range(1, 22)])
    bili.counts[1000101] = 22
    rows = [{"id": 1, "type": 2, "bvid": f"BV1other{i:05d}"} for i in range(22)]
    bili.ids_override[1000101] = {"code": 0, "message": "OK", "ttl": 1, "data": rows}
    snap = scan(bili, 1000101)["snapshot"]
    assert snap["complete"] is False and snap["ids_check"]["listed_not_in_ids"]


def test_legal_empty_folder(bili):
    bili.add(1000101, [])
    snap = scan(bili, 1000101)["snapshot"]
    assert snap["status"] == "empty" and snap["complete"] is True
    assert snap["media_count"] == 0 and snap["items"] == []


def test_forbidden_is_not_empty(bili):
    bili.forbidden.add(1000301)
    res = scan(bili, 1000301, owner_mid=OWNER)
    snap = res["snapshot"]
    assert snap["status"] == "forbidden" and snap["complete"] is False
    assert snap["media_count"] is None and snap["missing_pages"] == [1]
    assert "无访问权限" in snap["error"]["message"]
    assert not fav.last_complete_path(OWNER, 1000301).exists()


def test_forbidden_code_403_on_first_page(bili):
    bili.add(1000301, [media(1)])
    bili.page_override[(1000301, 1)] = [httpx.Response(200, json={"code": -403, "message": "访问权限不足"})]
    snap = scan(bili, 1000301, owner_mid=OWNER)["snapshot"]
    assert snap["status"] == "forbidden" and not snap["complete"]


def test_not_found_and_api_error_are_not_empty(bili):
    bili.not_found.add(1000401)
    assert scan(bili, 1000401)["snapshot"]["status"] == "not_found"
    bili.add(1000501, [media(1)])
    bili.page_override[(1000501, 1)] = [httpx.Response(502, text="bad gateway"), httpx.Response(502, text="x")]
    snap = scan(bili, 1000501)["snapshot"]
    assert snap["status"] == "error" and snap["error"]["reason"] == "http_5xx"
    bili.add(1000601, [media(1)])
    bili.page_override[(1000601, 1)] = [httpx.Response(200, text="<html>not json</html>")]
    assert scan(bili, 1000601)["snapshot"]["error"]["reason"] == "bad_response"


def test_forbidden_scan_does_not_touch_previous_complete(bili):
    first = _seed_complete(bili, 1000101, 5)
    bili.forbidden.add(1000101)
    res = scan(bili, 1000101, owner_mid=OWNER)
    assert res["snapshot"]["status"] == "forbidden"
    assert fav.load_last_complete(OWNER, 1000101)["fetched_at"] == first["fetched_at"]
    assert res["diff"]["unfavorited"] == []
    assert all(r["active"] for r in fav.load_relations().values())


# ---------------------------------------------------------------------------
# 检查点 / 续读 / 锁
# ---------------------------------------------------------------------------

def test_checkpoint_written_per_page_and_resume_reads_only_missing(bili, monkeypatch):
    bili.add(1000101, [media(i) for i in range(1, 46)])
    writes = []
    real = storage.write_json

    def spy(path, payload):
        if Path(path).name == f"{OWNER}-1000101.json":
            writes.append((len(payload["pages_read"]), payload.get("in_progress", False)))
        return real(path, payload)

    monkeypatch.setattr(storage, "write_json", spy)
    part = scan(bili, 1000101, max_pages=2)["snapshot"]
    assert part["status"] == "partial" and part["error"] is None
    assert part["pages_read"] == [1, 2] and part["missing_pages"] == [3]
    assert writes[:2] == [(1, True), (2, True)]                     # 每页一次检查点
    bili.calls.clear()
    full = scan(bili, 1000101)["snapshot"]
    assert pages_called(bili, 1000101) == [1, 3]                    # 第 1 页只用来核总数，第 2 页不重读
    assert full["complete"] and full["resumed_from"] == 3 and full["item_count"] == 45


def test_resume_restarts_when_count_changed(bili):
    bili.add(1000101, [media(i) for i in range(1, 46)])
    scan(bili, 1000101, max_pages=2)
    bili.folders[1000101] = [media(99)] + bili.folders[1000101]     # 中间新收藏了一条：页码错位
    bili.calls.clear()
    full = scan(bili, 1000101)["snapshot"]
    assert pages_called(bili, 1000101) == [1, 2, 3]
    assert full["complete"] and full["item_count"] == 46 and "resumed_from" not in full


def test_concurrent_scan_of_same_folder_is_busy(bili):
    bili.add(1000101, [media(1)])
    with storage.file_lock("bilibili-fav-1000101", wait_s=0, owner="other"):
        import threading
        out = {}
        t = threading.Thread(target=lambda: out.update(r=scan(bili, 1000101)))
        t.start()
        t.join()
    assert out["r"]["snapshot"]["status"] == "busy"
    assert not fav.snapshot_path(OWNER, 1000101).exists()


# ---------------------------------------------------------------------------
# 对比与关系表
# ---------------------------------------------------------------------------

def _snap(keys_valid, keys_invalid=(), *, complete=True, owner=OWNER, media_id=1000101):
    items = [{"bvid": k, "kind": "video", "id": i, "invalid": False} for i, k in enumerate(keys_valid)]
    items += [{"bvid": k, "kind": "video", "id": 100 + i, "invalid": True} for i, k in enumerate(keys_invalid)]
    return {"owner_mid": owner, "media_id": media_id, "complete": complete,
            "status": "complete" if complete else "partial", "items": items}


def test_diff_four_classes():
    prev = _snap(["A", "B", "C", "D"])
    curr = _snap(["B", "E"], ["C"])
    d = fav.diff_snapshot(prev, curr)
    assert d["new"] == ["E"] and d["same"] == ["B"] and d["unavailable"] == ["C"]
    assert d["unfavorited"] == ["A", "D"] and d["hold"] is False


def test_diff_first_scan_everything_new():
    d = fav.diff_snapshot(None, _snap(["A", "B"], ["X"]))
    assert d["new"] == ["A", "B"] and d["unavailable"] == ["X"] and d["unfavorited"] == []


def test_partial_scan_never_yields_unfavorited():
    prev = _snap(["A", "B", "C"])
    d = fav.diff_snapshot(prev, _snap(["A"], complete=False))
    assert d["unfavorited"] == [] and "没读全" in d["unfavorited_blocked"]
    assert d["same"] == ["A"]


def test_big_drop_is_held_for_review():
    prev = _snap([f"K{i}" for i in range(20)])
    d = fav.diff_snapshot(prev, _snap(["K0", "K1"]))
    assert len(d["unfavorited"]) == 18 and d["hold"] is True


def test_diff_refuses_different_folders():
    with pytest.raises(ValueError):
        fav.diff_snapshot(_snap(["A"]), _snap(["A"], media_id=1000201))


def test_relations_lifecycle(bili):
    bili.add(1000101, [media(i) for i in range(1, 6)])
    scan(bili, 1000101, now="2026-10-29T10:00:00+11:00")
    rel = fav.load_relations()
    key = f"{OWNER}:1000101:BV1fake00001"
    assert rel[key]["active"] and rel[key]["first_seen"] == rel[key]["last_seen"] == "2026-10-29T10:00:00+11:00"
    assert rel[key]["fav_time"] == 1700000000 + 10_000 - 1
    # 取消收藏 2 号（完整扫描）→ 关系 inactive，行不删
    bili.folders[1000101] = [m for m in bili.folders[1000101] if m["bvid"] != "BV1fake00002"]
    res = scan(bili, 1000101, now="2026-10-30T10:00:00+11:00")
    assert res["diff"]["unfavorited"] == ["BV1fake00002"] and res["relations"]["deactivated"] == 1
    rel = fav.load_relations()
    gone = rel[f"{OWNER}:1000101:BV1fake00002"]
    assert gone["active"] is False and gone["inactive_since"] == "2026-10-30T10:00:00+11:00"
    assert rel[key]["first_seen"] == "2026-10-29T10:00:00+11:00" and rel[key]["last_seen"] == "2026-10-30T10:00:00+11:00"
    # 又收藏回来 → reactivated
    bili.folders[1000101].append(media(2))
    res = scan(bili, 1000101, now="2026-10-31T10:00:00+11:00")
    assert res["relations"]["reactivated"] == 1 and fav.load_relations()[f"{OWNER}:1000101:BV1fake00002"]["active"]


def test_held_drop_does_not_deactivate(bili):
    bili.add(1000101, [media(i) for i in range(1, 21)])
    scan(bili, 1000101)
    bili.folders[1000101] = bili.folders[1000101][:3]
    res = scan(bili, 1000101)
    assert res["diff"]["hold"] is True and res["relations"]["deactivated"] == 0 and res["relations"]["held"] == 17
    assert all(r["active"] for r in fav.load_relations().values())


def test_same_bv_in_two_folders_two_relations_one_video(bili):
    bili.add(1000101, [media(1), media(2), media(3)], title="A 夹")
    bili.add(1000201, [media(3), media(4)], title="B 夹")
    a = scan(bili, 1000101)["snapshot"]
    b = scan(bili, 1000201)["snapshot"]
    rows = fav.relations_for("BV1fake00003")
    assert sorted((r["media_id"], r["folder_title"]) for r in rows) == [(1000101, "A 夹"), (1000201, "B 夹")]
    assert all(r["active"] for r in rows)
    d = fav.dedupe_bvids([a, b])
    assert d == {"before": 5, "after": 4, "shared": {"BV1fake00003": [1000101, 1000201]}}


# ---------------------------------------------------------------------------
# 不写 Cookie
# ---------------------------------------------------------------------------

def test_snapshot_and_relations_never_contain_cookie(bili):
    bili.add(1000101, [media(i) for i in range(1, 25)])
    client = client_for(bili, cookies={"SESSDATA": "sess-secret-value", "bili_jct": "jct-secret-value",
                                       "DedeUserID": "900001"})
    fav.sync_folder(client, 1000101, page_gap_s=0, sleep=lambda _s: None)
    assert any("sess-secret-value" in c for c in bili.cookies_seen)   # 请求确实带了 Cookie
    root = fav.sync_root()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    assert {p.name for p in files} >= {f"{OWNER}-1000101.json", f"{OWNER}-1000101.last-complete.json", "relations.json"}
    for p in files:
        text = p.read_text("utf-8")
        for bad in ("sess-secret-value", "jct-secret-value", "SESSDATA", "bili_jct", "DedeUserID", "Cookie",
                    "cookie", "upos", "deadline=", str(storage.vault_root())):
            assert bad not in text, (p.name, bad)


# ---------------------------------------------------------------------------
# 收藏夹列表 / 链接 / 登录态降级
# ---------------------------------------------------------------------------

def test_list_folders_ok_hidden_empty(bili):
    c = client_for(bili)
    res = fav.list_folders(c, OWNER)
    assert res["status"] == "ok" and [f["media_id"] for f in res["folders"]] == [1000101, 1000201, 1000301]
    f0, f1, f2 = res["folders"]
    assert (f0["default"], f0["private"]) == (True, False)
    assert (f1["default"], f1["private"]) == (False, False)
    assert (f2["default"], f2["private"]) == (False, True)
    bili.folders_reply = {"code": 0, "message": "OK", "ttl": 1, "data": None}
    assert fav.list_folders(c, OWNER)["status"] == "hidden"
    bili.folders_reply = {"code": 0, "message": "OK", "ttl": 1, "data": {"count": 0, "list": None}}
    assert fav.list_folders(c, OWNER)["status"] == "empty"
    bili.folders_reply = httpx.Response(412, text="blocked")
    r = fav.list_folders(c, OWNER)
    assert r["status"] == "error" and r["error"]["reason"] == "rate_limited"


@pytest.mark.parametrize("text, media_id, owner, kind", [
    ("https://space.bilibili.com/900001/favlist?fid=1000101&ftype=create", 1000101, 900001, "folder"),
    ("space.bilibili.com/900001/favlist?fid=1000101", 1000101, 900001, "folder"),
    ("看这个 https://space.bilibili.com/900001/favlist?fid=1000101&spm_id_from=333.1387 好东西", 1000101, 900001,
     "folder"),
    ("https://space.bilibili.com/900001/favlist?fid=3000001&ftype=collect", 3000001, 900001, "collection"),
    ("https://space.bilibili.com/900001/favlist", None, 900001, "owner"),
    ("https://www.bilibili.com/medialist/detail/ml1000101", 1000101, None, "folder"),
    ("https://www.bilibili.com/medialist/play/ml1000101?from=x", 1000101, None, "folder"),
    ("https://www.bilibili.com/list/ml1000101?oid=1&bvid=BV1fake00001", 1000101, None, "folder"),
    ("ml1000101", 1000101, None, "folder"),
    ("1000101", 1000101, None, "folder"),
    ("fid=1000101", 1000101, None, "folder"),
])
def test_parse_folder_url_shapes(text, media_id, owner, kind):
    p = fav.parse_folder_url(text)
    assert p is not None and (p["media_id"], p["owner_mid"], p["kind"]) == (media_id, owner, kind)


@pytest.mark.parametrize("text", [
    "", "随便一句话", "https://www.youtube.com/list/ml1000101", "https://evil.example/space.bilibili.com/1/favlist",
    "https://www.bilibili.com/video/BV1fake00001", "https://b23.tv/abcdef", "12",
])
def test_parse_folder_url_rejects(text):
    assert fav.parse_folder_url(text) is None


def test_login_module_missing_degrades_to_anonymous(monkeypatch):
    import link_brain.sources.bilibili as pkg
    monkeypatch.setitem(sys.modules, "link_brain.sources.bilibili.login", None)   # import 时抛 ImportError
    monkeypatch.delattr(pkg, "login", raising=False)                              # 阶段一合进来后包上可能已有
    st = fav.login_state()
    assert st["state"] == "unavailable" and "公开收藏夹" in st["reason"]
    client, st2 = fav.default_client()
    try:
        assert st2["state"] == "unavailable" and not client.cookies
    finally:
        client.close()


def test_login_status_error_is_unknown_not_logged_out(monkeypatch):
    import types
    mod = types.ModuleType("link_brain.sources.bilibili.login")

    def boom():
        raise RuntimeError("cookie 文件坏了")

    mod.status = boom
    monkeypatch.setitem(sys.modules, "link_brain.sources.bilibili.login", mod)
    import link_brain.sources.bilibili as pkg
    monkeypatch.setattr(pkg, "login", mod, raising=False)
    assert fav.login_state()["state"] == "unknown"


def test_cli_scan_prints_one_json_line(bili, monkeypatch, capsys):
    bili.add(1000101, [media(i) for i in range(1, 22)])
    monkeypatch.setattr(fav, "default_client", lambda: (client_for(bili), {"state": "unavailable"}))
    monkeypatch.setattr(fav, "PAGE_GAP_S", 0)
    monkeypatch.setattr(fav, "sync_folder", lambda *a, **k: _real_sync(*a, **{**k, "page_gap_s": 0}))
    code = fav.main(["scan", "https://space.bilibili.com/900001/favlist?fid=1000101"])
    out = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and len(out) == 1
    payload = json.loads(out[0])
    assert payload["ok"] is True and payload["summary"]["items"] == 21
    assert payload["snapshot"] == f"_archive/bilibili-sync/folders/{OWNER}-1000101.json"
    assert fav.main(["scan", "https://www.youtube.com/x"]) == 2


_real_sync = fav.sync_folder
