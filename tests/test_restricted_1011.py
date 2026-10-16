"""1011：网页版限制的笔记（她收藏里有、浏览器里打开要「验证一下」，读取服务打开详情页、页面上没有这篇）。

全部用假读取服务（monkeypatch fetch_detail / accounts.*），不联网、不碰号、不起组件。断言：
- 读取组件的 `[NOTE_RESTRICTED]` 报错认成「只是这一篇」：不当成号出事（不停整批、不写熔断），风险码照样优先；
- 兜底：每篇每天最多搜一次标题、搜到新口令先歇 LWA_FETCH_REST 再开一次（开页前照旧 pace）；搜到了就用新口令补上、清掉标记；
- 还是打不开：一篇一条安静的问题（note.restricted · PERMANENT.NOTE_RESTRICTED，不推送、不重复刷次数），不算评论「没进展」、
  不报 COMMENTS_INCOMPLETE / DOWNLOAD_FAILED；后台补评论 / 附件补下跳过它（不再每晚 3 次）；卡片角标、笔记页「打开验证」；
- 「打开验证」（note-verify）：过了 → 清标记、记新口令、续读计数清零、附件退避清掉、拉起后台补评论；没过 → 照实说、留着；
  号本身在熔断中 → 先走原来的熔断验证；旧读取组件 → 说清要更新。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from link_brain import accounts, attachments, catalog, cli, comment_fill, problems, repair, restricted, storage
from link_brain.adapters import xiaohongshu as xhs

from test_render import NOTE_ID, fake_parsed, load_fixture, setup_env

ITEM = f"xhs-{NOTE_ID}"
# 读取组件（Go）NoteRestrictedError.Error() 的原样文本（经 MCP「获取Feed详情失败: 」前缀）
GO_TEXT = ("获取Feed详情失败: [NOTE_RESTRICTED] 详情页没渲染出这篇笔记（页面状态里找不到 " + NOTE_ID +
           "，页面停在 /explore/" + NOTE_ID + "）：网页版限制了这篇，要人工打开看一眼")



@pytest.fixture(autouse=True)
def _confirm_on_first_hit(monkeypatch):
    """1017 起撞见一次只算疑似、隔天再撞才确认；这里测的是「已确认」那条路，按一次即确认跑。"""
    from link_brain import restricted as _r
    monkeypatch.setattr(_r, "CONFIRM_DAYS", 1)

def _floor(cid: str, shown: int, have: int) -> dict:
    return {"id": cid, "content": f"楼 {cid}", "userInfo": {"userId": "u1", "nickname": "某人"},
            "subCommentCount": str(shown),
            "subComments": [{"id": f"{cid}-r{i}", "content": f"回复 {i}", "userInfo": {"userId": "u2"}} for i in range(have)]}


def _raw(floors: list[dict]) -> dict:
    raw = load_fixture()
    raw["data"]["note"]["interactInfo"]["commentCount"] = "9999"
    raw["data"]["comments"] = {"list": floors, "cursor": "", "hasMore": True}
    return raw


@pytest.fixture
def env(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    # 口令跟着链接走（默认的假 parse_input 一律回固定口令，看不出用的是不是新口令）
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: {
        **fake_parsed(text), "xsec_token": (re.search(r"xsec_token=([^&]+)", text) or [None, "FAKE_TOKEN_FOR_TESTS"])[1]})
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([_floor("c1", 5, 1)]))
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)
    capsys.readouterr()
    paces: list[str] = []
    monkeypatch.setattr(accounts, "pace", lambda what="开页": paces.append(what) or 0.0)
    monkeypatch.setattr(accounts, "pace_done", lambda: None)
    sleeps: list[float] = []
    monkeypatch.setattr(restricted.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(restricted, "_rest_seconds", lambda: 123.0)
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    return SimpleNamespace(paces=paces, sleeps=sleeps)


def _restricted_fetch(calls: list, *, ok_token: str | None = None, floors=None):
    """假 fetch_detail：口令是 ok_token 时正常返回，其余一律回读取组件的 NOTE_RESTRICTED。"""
    def fake(note_id, token, **kw):
        calls.append(token)
        if ok_token and token == ok_token:
            return _raw(floors or [_floor("c1", 5, 5)])
        raise xhs.tool_error("get_feed_detail", GO_TEXT)
    return fake


def _search(monkeypatch, result, calls=None):
    def fake(note_id, keyword):
        (calls if calls is not None else []).append((note_id, keyword))
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(accounts, "search_note_token", fake)


def _rows(step=restricted.STEP):
    return [r for r in problems.load() if r.get("step") == step]


def _md() -> str:
    return next(storage.vault_root().glob("Web/Xiaohongshu/*.md")).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 认码
# --------------------------------------------------------------------------


def test_reader_text_is_note_restricted_not_account_trouble():
    exc = xhs.tool_error("get_feed_detail", GO_TEXT)
    assert isinstance(exc, xhs.NoteRestrictedError) and not isinstance(exc, xhs.NeedsHumanError)
    assert not xhs.looks_blocked(str(exc)), "给她看的话里不能有让别处当成「号出事」的字"
    # 风险码永远优先（不放宽熔断）
    assert isinstance(xhs.tool_error("get_feed_detail", "[CAPTCHA_REQUIRED] x [NOTE_RESTRICTED]"), xhs.AccountBlockedError)
    assert isinstance(xhs.tool_error("get_feed_detail", "[RISK_HOLD] 熔断中"), xhs.AccountBlockedError)
    # 没有标记的老报错照旧
    assert type(xhs.tool_error("get_feed_detail", "feed x not found in noteDetailMap")) is xhs.AdapterError
    assert accounts.SOLUTIONS["NOTE_RESTRICTED"][1] == restricted.TEXT
    assert "NOTE_RESTRICTED" not in accounts.NEEDS_HUMAN_CODES


# --------------------------------------------------------------------------
# 评论补齐
# --------------------------------------------------------------------------


def test_fill_restricted_searches_once_then_opens_with_fresh_token(env, monkeypatch):
    calls, searched = [], []
    monkeypatch.setattr(xhs, "fetch_detail", _restricted_fetch(calls, ok_token="FRESH"))
    _search(monkeypatch, {"found": True, "xsec_token": "FRESH", "count": 20}, searched)
    out = comment_fill.fill_one(ITEM)
    assert calls == ["FAKE_TOKEN_FOR_TESTS", "FRESH"], "旧口令打不开 → 搜到新口令 → 用它再开一次（只一次）"
    assert searched and searched[0][0] == NOTE_ID and searched[0][1], "按笔记 id + 标题搜"
    assert "搜这篇的标题" in env.paces and env.paces.count("打开笔记") == 2, "搜索和每次开页前都过开页间隔"
    assert env.sleeps == [123.0], "搜到新口令后先歇 LWA_FETCH_REST 再开（不连着开）"
    assert out["filled"] is True and not out.get("restricted")
    st = restricted.load(NOTE_ID)
    assert st["token"] == "FRESH" and not st.get("restricted") and st["search"]["result"] == "found"
    assert restricted.best_token(NOTE_ID, "OLD") == "FRESH"
    assert _rows() == [], "补上了：不留问题"
    assert comment_fill.load_state("xiaohongshu", NOTE_ID).get("no_progress") == 0


def test_fill_restricted_not_found_is_one_quiet_item_and_is_skipped(env, monkeypatch):
    calls, searched = [], []
    monkeypatch.setattr(xhs, "fetch_detail", _restricted_fetch(calls))
    _search(monkeypatch, {"found": False, "count": 20}, searched)
    pushed = []
    monkeypatch.setattr(problems, "_push", lambda row: pushed.append(row))
    out = comment_fill.fill_one(ITEM)
    assert out["restricted"] is True and out["filled"] is False and out["reason"] == restricted.TEXT
    assert calls == ["FAKE_TOKEN_FOR_TESTS"], "搜不到新口令：不再开第二次"
    assert env.sleeps == [], "没搜到就不歇（也不开页）"
    st = restricted.load(NOTE_ID)
    assert st["restricted"] is True and st["search"]["result"] == "not_found"
    rows = _rows()
    assert len(rows) == 1 and rows[0]["code"] == restricted.CODE and rows[0]["item_id"] == ITEM
    assert rows[0]["group"] == "gave_up" and "打开验证" in rows[0]["reason"] and pushed == [], "安静：不推送"
    # 不算评论「没进展」，也不报 COMMENTS_INCOMPLETE
    cf = comment_fill.load_state("xiaohongshu", NOTE_ID)
    assert not cf.get("no_progress") and not cf.get("stuck")
    assert _rows(comment_fill.STEP) == []
    # 后台补评论不再挑它；状态里如实数
    later = datetime.now().astimezone() + timedelta(hours=2)
    monkeypatch.setattr(comment_fill, "_now", lambda: later)
    sv = comment_fill.survey(now=later)
    assert sv["ready"] == [] and [e["item_id"] for e in sv["restricted"]] == [ITEM] and sv["pending"] == 0
    # 第二次（同一天，又被手动点了一次「再试一次」）：照试一次，但今天不再搜；问题还是一条、次数不刷
    out2 = comment_fill.fill_one(ITEM, manual=True)
    assert out2["restricted"] is True and len(searched) == 1, "每篇每天最多搜一次"
    assert len(_rows()) == 1 and _rows()[0]["count"] == 1
    # 后台（非手动）直接跳过、不开页
    n = len(calls)
    assert comment_fill.fill_one(ITEM)["restricted"] is True and len(calls) == n
    # 笔记页：评论区顶上一行 + 「打开验证」；卡片角标
    md = _md()
    assert restricted.TEXT in md and "lb-act-note-verify" in md
    items = catalog.collect(storage.vault_root())
    probs = next(it for it in items if it["id"] == ITEM)["problems"]
    assert [p["code"] for p in probs if p["code"] == restricted.CODE] == [restricted.CODE]
    # 自愈轮不替她开页：manual，写清下一步
    p = repair.plan(rows[0])
    assert p["kind"] == "manual" and "打开验证" in p["next"]


def test_fill_pending_run_does_not_loop_on_restricted(env, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(xhs, "fetch_detail", _restricted_fetch(calls))
    _search(monkeypatch, {"found": False})
    later = datetime.now().astimezone() + timedelta(hours=2)
    monkeypatch.setattr(comment_fill, "_now", lambda: later)
    monkeypatch.setattr(comment_fill, "account_wait_reason", lambda: ("", ""))
    monkeypatch.setattr(accounts, "_gap_range", lambda env_name, default: (0.0, 0.0))
    args = SimpleNamespace(until_done=False, budget_min=0, limit=0, verbose=False, wait_lock_min=0.01, then_background=False)
    assert comment_fill.run(args, sleep=lambda s: None) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert len(calls) == 1, "一晚只开一次：之后跳过，不再 3 次"
    assert out["ok"] is True and "网页版要验证才能看" in out["message"]
    assert comment_fill.run(args, sleep=lambda s: None) == 0
    assert len(calls) == 1, "再跑一轮也不开"
    capsys.readouterr()


def test_legacy_given_up_fill_is_released_once_then_classified(env, monkeypatch, capsys):
    """1011 以前因「not found in noteDetailMap」连着 3 次放弃的续读：本地解开一次（零开页），后台按新办法再试一次 → 记成「网页版要验证」。
    别的原因放弃的不动；解开过的不再解第二次。"""
    legacy = "AdapterError: MCP get_feed_detail 报错: 获取Feed详情失败: feed x not found in noteDetailMap"
    comment_fill.save_state("xiaohongshu", NOTE_ID, {"attempts": 3, "no_progress": 3, "stuck": True, "stuck_floors": 10,
                                                     "stuck_reason": "这篇读不出来：" + legacy, "last_error": legacy})
    problems.report(comment_fill.STEP, "PERMANENT.COMMENTS_INCOMPLETE", "评论续读连着 3 次没成", item_id=ITEM, action="gave_up")
    assert comment_fill.survey()["stuck"], "迁移前：已放弃，后台不会再开"
    assert restricted.release_legacy_fill_stuck() == [ITEM]
    st = comment_fill.load_state("xiaohongshu", NOTE_ID)
    assert not st.get("stuck") and st["no_progress"] == 0 and st.get("legacy_released")
    assert _rows(comment_fill.STEP) == [], "那条「评论没补全」标已解决"
    assert restricted.release_legacy_fill_stuck() == [], "幂等"
    # 后台按新办法试一次：认出来、搜一次、记成「网页版要验证」
    calls = []
    monkeypatch.setattr(xhs, "fetch_detail", _restricted_fetch(calls))
    _search(monkeypatch, {"found": False})
    later = datetime.now().astimezone() + timedelta(hours=2)
    monkeypatch.setattr(comment_fill, "_now", lambda: later)
    monkeypatch.setattr(comment_fill, "account_wait_reason", lambda: ("", ""))
    monkeypatch.setattr(accounts, "_gap_range", lambda env_name, default: (0.0, 0.0))
    args = SimpleNamespace(until_done=False, budget_min=0, limit=0, verbose=False, wait_lock_min=0.01, then_background=False)
    assert comment_fill.run(args, sleep=lambda s: None) == 0
    capsys.readouterr()
    assert len(calls) == 1 and restricted.is_restricted(NOTE_ID) and len(_rows()) == 1
    # 别的原因放弃的不动
    comment_fill.save_state("xiaohongshu", NOTE_ID, {"stuck": True, "stuck_floors": 10, "stuck_reason": "这楼当时没展开"})
    assert restricted.release_legacy_fill_stuck() == []


def test_search_hitting_account_trouble_stops_like_before(env, monkeypatch):
    calls = []
    monkeypatch.setattr(xhs, "fetch_detail", _restricted_fetch(calls))
    _search(monkeypatch, accounts.ReaderError("RISK_HOLD", detail="熔断中"))
    with pytest.raises(xhs.AccountBlockedError) as ei:
        comment_fill.fill_one(ITEM)
    assert ei.value.code == "RISK_HOLD"
    assert restricted.load(NOTE_ID)["search"]["result"] == "error", "先记再搜：今天不会再搜第二次"
    assert not restricted.search_due(restricted.load(NOTE_ID))
    # 服务那侧的失败（看不见的验证组件 / 忙）→ 只记，这篇照常记成要验证
    restricted.save(NOTE_ID, {})
    _search(monkeypatch, accounts.ReaderError("HIDDEN_WIDGET", "页面里有验证组件但没显示滑块"))
    assert comment_fill.fill_one(ITEM)["restricted"] is True


def test_normal_open_clears_a_stale_mark(env, monkeypatch):
    restricted.mark(NOTE_ID, item_id=ITEM, title="t", via="comments.fill")
    assert len(_rows()) == 1
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([_floor("c1", 5, 5)]))
    comment_fill.fill_one(ITEM, manual=True)
    assert not restricted.is_restricted(NOTE_ID) and _rows() == []


def test_manual_fetch_all_comments_says_restricted(env, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(xhs, "fetch_detail", _restricted_fetch(calls))
    _search(monkeypatch, {"found": False})
    monkeypatch.setattr(accounts, "account_session", lambda *a, **k: __import__("contextlib").nullcontext())
    assert cli.main(["comments", ITEM]) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["code"] == "NOTE_RESTRICTED" and "打开验证" in out["message"] and out["ok"] is False
    assert restricted.is_restricted(NOTE_ID)


# --------------------------------------------------------------------------
# 附件
# --------------------------------------------------------------------------


def _declare_attachment(monkeypatch):
    # 这篇只声明一个有编号的附件（合成笔记正文里的「附件」线索不参与：那条走正文线索找编号的另一条路）
    monkeypatch.setattr(attachments, "declared_attachments", lambda obj, src: [{"doc_id": "doc1", "name": "a.pdf"}])


def test_attachment_reader_code_maps_to_restricted(env, monkeypatch, tmp_path):
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: {})

    def api(method, route, **kw):
        raise accounts.ReaderError("NOTE_RESTRICTED", restricted.TEXT)
    monkeypatch.setattr(accounts, "api", api)
    with pytest.raises(attachments.AttachmentRestricted):
        attachments.fetch_bytes(doc_id="d", note_id=NOTE_ID, xsec_token="t", file_name="a.pdf", staging_dir=tmp_path / "s")


def test_attachment_restricted_no_triple_retry_and_skipped_after(env, monkeypatch):
    _declare_attachment(monkeypatch)
    fetches = []

    def fake_fetch(**kw):
        fetches.append(kw["xsec_token"])
        raise attachments.AttachmentRestricted(restricted.TEXT)
    monkeypatch.setattr(attachments, "fetch_bytes", fake_fetch)
    monkeypatch.setattr(attachments, "_pace", lambda attempt=1: None)
    _search(monkeypatch, {"found": True, "xsec_token": "FRESH"})
    out = attachments.download_for_object("xiaohongshu", NOTE_ID)
    assert fetches == ["FAKE_TOKEN_FOR_TESTS", "FRESH"], "不进 3 次循环：旧口令一次 + 新口令一次"
    assert [r["status"] for r in out["results"]] == ["restricted"]
    assert env.sleeps == [123.0]
    assert restricted.is_restricted(NOTE_ID) and len(_rows()) == 1
    assert _rows("attachments.download") == [], "不报「附件没下好」"
    state = storage.read_json(storage.object_dir("xiaohongshu", NOTE_ID) / "attachment-state.json")
    assert not state.get("download_backoff") and not state.get("errors"), "不进跨夜退避、卡片上不出「附件没下好」"
    # 之后（今晚 / 明晚）：直接跳过，不开页
    n = len(fetches)
    out2 = attachments.download_for_object("xiaohongshu", NOTE_ID)
    assert [r["status"] for r in out2["results"]] == ["restricted"] and len(fetches) == n


def test_attachment_fallback_defers_when_budget_is_short(env, monkeypatch):
    _declare_attachment(monkeypatch)
    monkeypatch.setattr(attachments, "fetch_bytes", lambda **kw: (_ for _ in ()).throw(attachments.AttachmentRestricted("x")))
    monkeypatch.setattr(attachments, "_pace", lambda attempt=1: None)
    searched = []
    _search(monkeypatch, {"found": True, "xsec_token": "FRESH"}, searched)
    left = {"v": attachments.attempt_cost(1) + 5}
    out = attachments.download_for_object("xiaohongshu", NOTE_ID, budget_left=lambda: left["v"])
    assert [r["status"] for r in out["results"]] == ["deferred"] and searched == []
    assert not restricted.is_restricted(NOTE_ID), "时间不够：不记、下次接着试（含搜一次）"


def test_logged_in_recheck_skips_restricted_notes(env, monkeypatch):
    restricted.mark(NOTE_ID, item_id=ITEM, title="t", via="attachments")
    obj = storage.object_dir("xiaohongshu", NOTE_ID)
    storage.write_json(obj / "derived" / "web_recheck.json", {"ok": False, "stage": "guest_unseen",
                                                             "guest_at": datetime.now().astimezone().isoformat()})
    probed = []
    monkeypatch.setattr(attachments, "_probe_logged_in", lambda *a: probed.append(a) or {"ok": False})
    monkeypatch.setattr(attachments, "write_recheck_status", lambda *a, **k: {})
    out = attachments.recheck_tail(limit=5)
    assert probed == [] and out["checked"] == 0 and out["gone"] == 0


# --------------------------------------------------------------------------
# 「打开验证」
# --------------------------------------------------------------------------


def _verify_api(monkeypatch, *, mode="note", session_after=None, opened=None):
    sent = []

    def api(method, route, *, timeout=45, body=None):
        sent.append((method, route, body))
        if route == "/api/v1/verify/window":
            return opened if opened is not None else {"opened": True, "mode": mode}
        if route == "/api/v1/login/session":
            return session_after or {}
        raise AssertionError(route)
    monkeypatch.setattr(accounts, "api", api)
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: {"risk_hold": None, "verifying": False})
    monkeypatch.setattr(accounts, "VERIFY_POLL_SECONDS", 0)
    monkeypatch.setattr(accounts.time, "sleep", lambda s: None)
    return sent


def test_note_verify_passed_requeues_capture(env, monkeypatch, capsys):
    restricted.mark(NOTE_ID, item_id=ITEM, title="t", via="comments.fill")
    comment_fill.save_state("xiaohongshu", NOTE_ID, {"no_progress": 2, "stuck": True, "stuck_floors": 10})
    obj = storage.object_dir("xiaohongshu", NOTE_ID)
    storage.write_json(obj / "attachment-state.json", {"errors": [], "download_backoff": {"doc1": {"tries": 2}}})
    spawned = []
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: spawned.append(1) or {"ok": True, "started": True})
    sent = _verify_api(monkeypatch, session_after={"verifying": False, "verify_result": "note_ok", "risk_hold": None,
                                                   "verify_note": {"note_id": NOTE_ID, "ok": True, "token": "WIN"}})
    assert cli.main(["note-verify", ITEM, "--wait"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["result"] == "note_ok" and "后台补" in out["message"]
    assert "token" not in out, "口令不进 stdout"
    assert sent[0] == ("POST", "/api/v1/verify/window", {"note_id": NOTE_ID, "xsec_token": "FAKE_TOKEN_FOR_TESTS"})
    st = restricted.load(NOTE_ID)
    assert not st["restricted"] and st["token"] == "WIN" and st.get("verified_at")
    assert _rows() == []
    cf = comment_fill.load_state("xiaohongshu", NOTE_ID)
    assert cf["no_progress"] == 0 and not cf.get("stuck")
    assert not storage.read_json(obj / "attachment-state.json").get("download_backoff")
    assert spawned == [1], "拉起后台补评论"
    # 同一篇刚在窗口里开过：后台补评论照旧隔 45 分钟再开
    sv = comment_fill.survey(now=datetime.now().astimezone() + timedelta(minutes=10))
    assert [e["item_id"] for e in sv["cooling"]] == [ITEM]
    assert restricted.TEXT not in _md()


def test_note_verify_not_passed_keeps_mark(env, monkeypatch, capsys):
    restricted.mark(NOTE_ID, item_id=ITEM, title="t", via="comments.fill")
    _verify_api(monkeypatch, session_after={"verifying": False, "verify_result": "note_not_seen", "risk_hold": None,
                                            "verify_note": {"note_id": NOTE_ID, "ok": False, "token": ""}})
    assert cli.main(["note-verify", ITEM, "--wait"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is False and out["code"] == "NOTE_RESTRICTED" and "再点一次" in out["message"]
    assert restricted.is_restricted(NOTE_ID)
    assert restricted.load(NOTE_ID)["verify"]["result"] == "note_not_seen"
    assert [r.get("verify_result") for r in _rows()] == ["note_not_seen"]


def test_note_verify_defers_to_account_hold_and_old_reader(env, monkeypatch, capsys):
    monkeypatch.setattr(accounts, "ensure_reader", lambda **k: {"risk_hold": {"code": "CAPTCHA_REQUIRED", "since": "x"}})
    called = []
    monkeypatch.setattr(accounts, "open_verify", lambda wait=False: called.append(wait) or {
        "state": "captcha", "message": "窗口里没出现验证，暂停还在", "next_step": "…", "verify_result": "no_captcha_seen"})
    out = accounts.open_note_verify(NOTE_ID, "t", wait=True)
    assert called == [True] and out["mode"] == "hold" and out["ok"] is False and "号本身要先过验证" in out["message"]
    # 旧读取组件：没有熔断时只回 no_hold、不开窗
    _verify_api(monkeypatch, opened={"opened": False, "result": "no_hold", "risk_hold": None})
    out = accounts.open_note_verify(NOTE_ID, "t", wait=True)
    assert out["ok"] is False and "旧版" in out["message"]


def test_registry_and_steps():
    assert restricted.STEP in problems.STEPS and problems.step_label(restricted.STEP) == "网页版要验证"
    row = problems.lookup(restricted.CODE)
    assert row["group"] == "gave_up" and row["where"] == "card"
