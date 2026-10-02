"""第 4 批：故障分类接进各调用点 + 给页面的数据（problems-summary.json / items[].problems / CLI）。

全部走 tmp vault（conftest），不联网、不碰读取服务。推送出口 alert._alert 一律打桩计数。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from _samples import encrypted_pdf_bytes, text_pdf
from link_brain import (alert as alert_mod, ask, attachments as att_mod, catalog, cli, enrich, pdftext, problems,
                        storage, sync_state)
from test_catalog import _make_object

TZ = timezone(timedelta(hours=10))


def at(day: int, hour: int = 4, minute: int = 10):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_mod, "_alert", lambda kind, title, body, **extra: sent.append((kind, title, body, extra)) or True)
    return sent


def _codes(step=None):
    return [(r["step"], r["code"]) for r in problems.load() if step is None or r["step"] == step]


# --------------------------------------------------------------------------
# 分类判定：读取服务 / 账号撞墙（favorites / ingest / catch / attachments 共用 report_blocked）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code,service,step,full", [
    ("NOT_LOGGED_IN", False, "login", "NEEDS_HUMAN.NOT_LOGGED_IN"),
    ("CAPTCHA_REQUIRED", False, "login", "NEEDS_HUMAN.CAPTCHA_REQUIRED"),
    ("ACCOUNT_RISK", False, "login", "NEEDS_HUMAN.ACCOUNT_RISK"),
    ("RISK_HOLD", False, "login", "NEEDS_HUMAN.RISK_HOLD"),
    ("NOT_INSTALLED", False, "login", "NEEDS_HUMAN.NOT_INSTALLED"),
    ("WRONG_ACCOUNT", False, "login", "NEEDS_HUMAN.WRONG_ACCOUNT"),
    ("", False, "login", "NEEDS_HUMAN.ACCOUNT_BLOCKED"),       # 号出事了但没带风险码
    ("", True, "ingest", "TRANSIENT.DISCONNECTED"),            # 读取服务没起来
    ("TIMEOUT", True, "ingest", "TRANSIENT.TIMEOUT"),
    ("FAVORITES_FAILED", True, "ingest", "TRANSIENT.FAVORITES_FAILED"),  # 1002 那晚：机器卡、500、非风控
    ("HTTP_500", True, "ingest", "TRANSIENT.HTTP_5XX"),
])
def test_report_blocked_classifies_account_vs_service(pushes, code, service, step, full):
    row = problems.report_blocked("ingest", code, "撞墙了", service=service)
    assert row["step"] == step and row["code"] == full
    assert len(pushes) == (1 if full.startswith("NEEDS_HUMAN.") else 0)


def test_rate_limited_is_not_a_problem(pushes):
    assert problems.report_blocked("sync.favorites", "RATE_LIMITED", "刚同步过", service=True) is None
    assert problems.load() == [] and pushes == []


def test_one_account_problem_seen_by_sync_attachments_and_ingest_pushes_once(pushes):
    problems.report_blocked("sync.favorites", "NOT_LOGGED_IN", "同步撞见")
    problems.report_blocked("attachments.download", "NOT_LOGGED_IN", "下附件撞见")
    problems.report_blocked("ingest", "NOT_LOGGED_IN", "导入撞见")
    assert _codes() == [("login", "NEEDS_HUMAN.NOT_LOGGED_IN")] and len(pushes) == 1


def test_needs_human_for_many_items_pushes_once_per_step(pushes):
    """要人处理的码各篇都撞见：只推一次（同一步骤 + 同一码）。"""
    for i in range(5):
        problems.report("ingest", "NEEDS_HUMAN.FAVORITES_SUSPICIOUS", "数不对", item_id=f"xhs-{i}")
    assert len(pushes) == 1 and len(problems.load()) == 5
    problems.report("sync.favorites", "NEEDS_HUMAN.FAVORITES_SUSPICIOUS", "数不对")  # 另一步骤再推一次
    assert len(pushes) == 2


def test_key_failure_pushes_only_after_two_nights(pushes):
    """key 失效 / 欠费：产品规则「连续几晚没修好」才推。第一晚只进列表（橙色计数），第二晚还在才推一次。"""
    for i in range(5):
        problems.report("enrich.summary", "NEEDS_HUMAN.AUTH_FAILED", "401", item_id=f"xhs-{i}", _now_fn=lambda: at(1))
    assert pushes == [] and len(problems.load()) == 5
    assert problems.summary()["needs_human"] == 5
    problems.report("enrich.summary", "NEEDS_HUMAN.AUTH_FAILED", "401", item_id="xhs-0", _now_fn=lambda: at(2))
    problems.report("enrich.summary", "NEEDS_HUMAN.AUTH_FAILED", "401", item_id="xhs-1", _now_fn=lambda: at(2))
    assert len(pushes) == 1
    # 中间修好了（都解决）再坏：重新从第一晚算
    for i in range(5):
        problems.resolve("enrich.summary", f"xhs-{i}")
    problems.report("enrich.summary", "NEEDS_HUMAN.QUOTA_EXCEEDED", "欠费", item_id="xhs-0", _now_fn=lambda: at(3))
    assert len(pushes) == 1


def test_stuck_for_many_items_pushes_once_per_step(pushes):
    for day in (1, 2, 3):
        for i in range(3):
            problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id=f"xhs-{i}",
                            _now_fn=lambda d=day: at(d))
    stuck = [r for r in problems.load() if r["code"] == "NEEDS_HUMAN.STUCK"]
    # 同一步骤同一个原因卡 3 天 = 一件事：只升级一条（顶部橙色 +1）、只推一次
    assert len(stuck) == 1 and stuck[0]["item_id"] is None and len(pushes) == 1
    assert pushes[0][1].startswith("连续几天没修好")


def test_stuck_counts_days_across_items(pushes):
    """每晚卡住的是不同的几篇，但同一步骤同一个原因连着 3 晚 → 也升级（原因在步骤，不在某一篇）。"""
    for day in (1, 2, 3):
        problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id=f"xhs-{day}",
                        _now_fn=lambda d=day: at(d))
    assert [r["code"] for r in problems.load()].count("NEEDS_HUMAN.STUCK") == 1 and len(pushes) == 1


def test_stuck_resolves_only_when_no_item_is_still_failing(pushes):
    for day in (1, 2, 3):
        for i in range(2):
            problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id=f"xhs-{i}",
                            _now_fn=lambda d=day: at(d))
    stuck = lambda: [r for r in problems.load() if r["code"] == "NEEDS_HUMAN.STUCK"]
    problems.resolve("attachments.download", "xhs-0")
    assert len(stuck()) == 1, "还有一篇卡着：升级那条留着"
    problems.resolve("attachments.download")  # 步骤级 resolve 也不能把它解决掉
    assert len(stuck()) == 1
    problems.resolve("attachments.download", "xhs-1")
    assert stuck() == [], "各篇都好了：升级那条跟着解决"
    # 再坏一天不会立刻又升级、又推
    problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id="xhs-0", _now_fn=lambda: at(4))
    assert stuck() == [] and len(pushes) == 1


def test_push_body_says_what_to_do(pushes):
    problems.report("login", "NOT_LOGGED_IN", "登录检查：未登录")
    kind, title, body, extra = pushes[0]
    assert kind == "problem" and title == "需要登录：小红书账号"
    assert body.startswith("小红书账号掉登录了") and "登录检查：未登录" in body and extra["code"] == "NEEDS_HUMAN.NOT_LOGGED_IN"


# --------------------------------------------------------------------------
# sync_state：record / account_problem / account_ok
# --------------------------------------------------------------------------


def _blocked(code, account="xhs"):
    return {"favorites": 0, "synced": 0, "login_account": account, "code": code,
            "items": [{"item_id": None, "status": "blocked", "error": f"撞了 {code}", "code": code,
                       "login_account": account}]}


def test_record_blocked_by_account_is_needs_human_on_login(pushes):
    sync_state.record("finished", payload=_blocked("CAPTCHA_REQUIRED"))
    sync_state.record("finished", payload=_blocked("CAPTCHA_REQUIRED"))  # 第二晚还是：不重推
    assert _codes() == [("login", "NEEDS_HUMAN.CAPTCHA_REQUIRED")] and len(pushes) == 1
    assert json.loads(sync_state.path().read_text("utf-8"))["state"] == "blocked"  # sync-status.json 照写


def test_record_service_failure_is_transient_and_quiet(pushes):
    sync_state.record("finished", payload=_blocked("FAVORITES_FAILED", account=None))
    assert _codes() == [("sync.favorites", "TRANSIENT.FAVORITES_FAILED")] and pushes == []
    sync_state.record("finished", payload=_blocked("", account=None))
    assert ("sync.favorites", "TRANSIENT.DISCONNECTED") in _codes() and pushes == []


def test_record_wrong_account_and_suspicious_push(pushes):
    sync_state.record("finished", payload=_blocked("WRONG_ACCOUNT"))
    assert _codes() == [("login", "NEEDS_HUMAN.WRONG_ACCOUNT")] and len(pushes) == 1
    sync_state.record("finished", payload={"favorites": 0, "synced": 0, "items": [], "favorites_total": 0,
                                           "suspicious": "收藏读回 0 条", "code": "FAVORITES_SUSPICIOUS"})
    assert ("sync.favorites", "NEEDS_HUMAN.FAVORITES_SUSPICIOUS") in _codes() and len(pushes) == 2


def test_record_too_many_failures_and_crash_are_transient(pushes):
    sync_state.record("finished", payload={"favorites": 5, "synced": 3, "code": "TOO_MANY_FAILURES",
                                           "items": [{"status": "error", "error": "抓不到"}] * 3})
    sync_state.record("failed", message="同步未完成，请打开账号 / 同步查看详情并重试")
    assert set(_codes()) == {("sync.favorites", "TRANSIENT.TOO_MANY_FAILURES"), ("sync.favorites", "TRANSIENT.SYNC_FAILED")}
    assert pushes == []


def test_record_ready_resolves_sync_and_login_problems(pushes):
    sync_state.record("finished", payload=_blocked("NOT_LOGGED_IN"))
    sync_state.record("finished", payload=_blocked("TIMEOUT", account=None))
    sync_state.record("finished", payload={"favorites": 3, "synced": 3, "items": [{"status": "hit"}] * 3,
                                           "fetched_new": ["a", "b"], "deferred": 4})
    assert problems.load() == []
    status = json.loads(sync_state.path().read_text("utf-8"))
    assert status["state"] == "ready" and status["new"] == 2 and status["deferred"] == 4


def test_rate_limited_sync_neither_reports_nor_resolves(pushes):
    sync_state.account_problem("NOT_LOGGED_IN", "登录检查：未登录")
    sync_state.record("finished", payload=_blocked("RATE_LIMITED", account=None))
    assert _codes() == [("login", "NEEDS_HUMAN.NOT_LOGGED_IN")]


def test_account_problem_and_ok(pushes):
    status = sync_state.account_problem("NOT_LOGGED_IN", "登录检查：未登录")
    assert status["message"] == problems.STATE_REGISTRY["NEEDS_HUMAN.NOT_LOGGED_IN"]["hover"]  # 文案唯一源
    assert _codes() == [("login", "NEEDS_HUMAN.NOT_LOGGED_IN")] and len(pushes) == 1
    sync_state.account_ok()
    assert problems.load() == [] and sync_state.load()["state"] == "ready"


def test_account_messages_come_from_the_registry():
    for code in sync_state.ACCOUNT_CODES:
        assert sync_state.account_message(code) == problems.STATE_REGISTRY[f"NEEDS_HUMAN.{code}"]["hover"]
    assert not hasattr(sync_state, "_ACCOUNT_MESSAGES")


@pytest.mark.parametrize("code", ["NOT_LOGGED_IN", "CAPTCHA_REQUIRED", "WRONG_ACCOUNT", "INTERRUPTED", "DISCONNECTED",
                                  "NOT_INSTALLED", "RISK_HOLD", "ACCOUNT_RISK"])
def test_page_codes_all_have_labels(code):
    shown = problems.describe(code)
    assert shown["label"] and shown["hover"] and "{" not in shown["hover"]


# --------------------------------------------------------------------------
# 「pid 还活着」只在 Python 判：current() 落盘 INTERRUPTED + 登记 + 刷新 summary
# --------------------------------------------------------------------------


def test_dead_running_sync_becomes_interrupted_on_disk(monkeypatch, pushes):
    storage.write_json(sync_state.path(), {"state": "running", "pid": 999999, "progress": "第 3/9 条", "message": "正在同步收藏"})
    monkeypatch.setattr(sync_state, "_alive", lambda pid: False)
    assert sync_state.load()["code"] == "INTERRUPTED"
    assert json.loads(sync_state.path().read_text("utf-8"))["state"] == "running"  # load 只读
    status = sync_state.current()
    disk = json.loads(sync_state.path().read_text("utf-8"))
    assert status["code"] == disk["code"] == "INTERRUPTED" and disk["state"] == "failed" and disk["detail"] == "第 3/9 条"
    assert _codes() == [("sync.favorites", "TRANSIENT.INTERRUPTED")] and pushes == []
    summary = json.loads(problems.summary_path().read_text("utf-8"))
    assert summary["sync"]["code"] == "INTERRUPTED" and summary["sync"]["label"] == "被打断"
    sync_state.current()  # 已经落盘：不重复登记
    assert problems.load()[0]["count"] == 1


def test_live_running_sync_is_left_alone(monkeypatch):
    storage.write_json(sync_state.path(), {"state": "running", "pid": 4242})
    monkeypatch.setattr(sync_state, "_alive", lambda pid: True)
    assert sync_state.current()["state"] == "running" and problems.load() == []


# --------------------------------------------------------------------------
# problems-summary.json 契约（前端读，字段名固定）
# --------------------------------------------------------------------------

SUMMARY_KEYS = {"updated_at", "needs_human", "auto", "gave_up", "skipped", "last_runs", "sync"}
SYNC_KEYS = {"state", "code", "message", "label", "hover", "detail", "updated_at", "last_success", "favorites", "new",
             "deferred", "progress", "running"}


def test_summary_file_is_written_after_every_report_and_resolve(pushes):
    problems.report("login", "NOT_LOGGED_IN", "掉了")
    problems.report("embed", "TRANSIENT.NETWORK", "断网")
    problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "锁", item_id="xhs-1")
    problems.report("ask", "SKIPPED.FALLBACK", "退回", action="skipped")
    data = json.loads(problems.summary_path().read_text("utf-8"))
    assert set(data) == SUMMARY_KEYS
    assert (data["needs_human"], data["auto"], data["gave_up"], data["skipped"]) == (1, 1, 1, 1)
    assert all(isinstance(data[k], int) for k in ("needs_human", "auto", "gave_up", "skipped"))
    datetime.fromisoformat(data["updated_at"])
    assert set(data["sync"]) == SYNC_KEYS
    problems.resolve("login")
    assert json.loads(problems.summary_path().read_text("utf-8"))["needs_human"] == 0


def test_sync_status_writes_refresh_the_summary():
    sync_state.record("finished", payload={"favorites": 3, "synced": 3, "items": [], "fetched_new": ["a"], "deferred": 2})
    sync = json.loads(problems.summary_path().read_text("utf-8"))["sync"]
    assert sync["state"] == "ready" and sync["new"] == 1 and sync["deferred"] == 2 and sync["last_success"]
    sync_state.record("running", message="正在同步收藏")
    sync_state.progress("第 1/3 条")
    sync = json.loads(problems.summary_path().read_text("utf-8"))["sync"]
    assert sync["running"] is True and sync["progress"] == "第 1/3 条"


def test_summary_write_failure_does_not_break_report(monkeypatch, pushes, capsys):
    def boom(*a, **k):
        raise OSError("磁盘满")
    real = storage.write_json
    monkeypatch.setattr(storage, "write_json", lambda p, obj: boom() if p == problems.summary_path() else real(p, obj))
    row = problems.report("embed", "TRANSIENT.NETWORK", "断网")
    assert row["written"] is True and problems.load()
    assert "problems-summary.json 没写上" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 附件转 md：假 OCR 故障第二晚自动重试；加密 PDF 不重试、不推送、卡片可见
# --------------------------------------------------------------------------


def _with_attachment(tmp_path, monkeypatch, name, payload, sid="a1"):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _make_object(tmp_path, sid, title="合成笔记", tags=["AI"], summary="概要", stem=f"合成笔记{sid}")
    obj = storage.object_dir("xiaohongshu", sid)
    (obj / "attachments").mkdir(parents=True, exist_ok=True)
    (obj / "attachments" / name).write_bytes(payload)
    storage.write_json(obj / "attachments.json",
                       {"schema_version": 1, "files": [{"doc_id": "d1", "file": name, "name": name, "sha256": "s1"}]})
    return sid


def _item(sid):
    data = json.loads((storage.archive_root() / "catalog-data.json").read_text("utf-8"))
    return next(it for it in data["items"] if it["id"] == f"xhs-{sid}"), data


def test_fake_ocr_fault_is_retried_automatically_the_next_night(tmp_path, monkeypatch, pushes):
    payload = text_pdf(tmp_path / "src.pdf", [["Tutorial line"] * 6]).read_bytes()
    sid = _with_attachment(tmp_path, monkeypatch, "扫描.pdf", payload)
    calls = []
    ok_after = {"day": 2}

    def fake(path, **kw):
        calls.append(path.name)
        if len(calls) < ok_after["day"]:
            return {"status": "failed", "method": None, "markdown": None, "note": "本地 OCR 超时", "partial": 0,
                    "code": "TRANSIENT.SERVICE_BUSY"}
        return {"status": "ok", "method": "ocr", "markdown": "# 扫描.pdf\n\n正文", "note": "", "partial": 0, "code": ""}
    monkeypatch.setattr(pdftext, "attachment_to_markdown", fake)

    night1 = pdftext.convert_object_attachments("xiaohongshu", sid, now=at(1, 4, 10))
    assert night1[0]["status"] == "failed" and night1[0]["next_at"].startswith("2026-10-02T00:00")
    rec = att_mod.load_downloaded("xiaohongshu", sid)["d1"]["conversion_failed"]
    assert rec["code"] == "TRANSIENT.SERVICE_BUSY" and rec["tries"] == 1 and rec["next_at"] == night1[0]["next_at"]
    row = problems.load()[0]
    assert row["code"] == "TRANSIENT.SERVICE_BUSY" and row["action"] == "retry_later" and row["next_at"] == rec["next_at"]
    when = problems.when_text(rec["next_at"])
    assert row["group"] == "auto" and f"{when} 再试" in row["hover"]
    catalog.build()
    it, data = _item(sid)
    assert [(p["code"], p["group"], p["action"]) for p in it["problems"]] == [("TRANSIENT.SERVICE_BUSY", "auto", "retry_later")]
    assert f"{when} 再试" in it["problems"][0]["hover"] and it["problems"][0]["label"] == data["state_registry"]["TRANSIENT.SERVICE_BUSY"]["label"]

    same_night = pdftext.convert_object_attachments("xiaohongshu", sid, now=at(1, 5, 0))
    assert same_night[0]["status"] == "backoff" and len(calls) == 1  # 退避中：当晚不再白跑 OCR

    night2 = pdftext.convert_object_attachments("xiaohongshu", sid, now=at(2, 4, 5))  # 第二晚 4:05 < 24 小时也照样重试
    assert night2[0]["status"] == "ok" and len(calls) == 2
    assert problems.load() == [] and pushes == []
    catalog.build()
    assert _item(sid)[0]["problems"] == []


def test_transient_backoff_grows_and_caps_at_seven_days():
    got = [att_mod.conversion_next_at(n, at(1)) for n in (1, 2, 3, 4, 9)]
    assert [g[:10] for g in got] == ["2026-10-02", "2026-10-03", "2026-10-05", "2026-10-08", "2026-10-08"]


def test_encrypted_pdf_is_not_retried_not_pushed_and_visible_on_the_card(tmp_path, monkeypatch, pushes):
    sid = _with_attachment(tmp_path, monkeypatch, "锁.pdf", encrypted_pdf_bytes())
    calls = []
    real = pdftext.attachment_to_markdown
    monkeypatch.setattr(pdftext, "attachment_to_markdown", lambda p, **kw: calls.append(1) or real(p, **kw))
    first = pdftext.convert_object_attachments("xiaohongshu", sid, now=at(1))
    assert first[0]["code"] == "PERMANENT.PDF_ENCRYPTED" and first[0]["next_at"] is None
    for day in (2, 3, 9):
        assert pdftext.convert_object_attachments("xiaohongshu", sid, now=at(day))[0]["status"] == "conversion_failed"
    assert len(calls) == 1 and pushes == []
    row = problems.load()[0]
    assert (row["code"], row["action"], row["group"]) == ("PERMANENT.PDF_ENCRYPTED", "gave_up", "gave_up")
    catalog.build()
    it, data = _item(sid)
    assert it["problems"] == [{"code": "PERMANENT.PDF_ENCRYPTED", "label": "全文没转出来",
                               "hover": data["state_registry"]["PERMANENT.PDF_ENCRYPTED"]["hover"],
                               "group": "gave_up", "action": "gave_up"}]
    assert "attachment_reason" in it and "attachment_errors" in it  # 旧字段保留，前端还在用


def test_item_problems_from_object_files(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _make_object(tmp_path, "v1", title="视频", tags=[], summary="", stem="视频v1", kind="video")
    obj = storage.object_dir("xiaohongshu", "v1")
    storage.write_json(obj / "derived" / "transcript.json", {"status": "no_speech", "text": ""})
    storage.write_json(obj / "derived" / "vision.json", {"images": [
        {"asset": "a.webp", "status": "ok", "visual": {"status": "failed", "code": "NEEDS_HUMAN.AUTH_FAILED", "error": "401"}},
        {"asset": "b.webp", "status": "ok", "refine": {"status": "failed", "error": "格式不对"}}]})
    storage.write_json(obj / "derived" / "extracted.json", {"status": "failed", "code": "TRANSIENT.HTTP_5XX", "error": "502"})
    storage.write_json(obj / "attachment-state.json", {"errors": [{"doc_id": "d", "error": "附件下载超时"}]})
    storage.write_json(obj / "enrich-state.json", {"fails": 1})
    catalog.build()
    it, _ = _item("v1")
    codes = {p["code"]: p for p in it["problems"]}
    assert set(codes) == {"PERMANENT.NO_SPEECH", "NEEDS_HUMAN.AUTH_FAILED", "PERMANENT.MODEL_OUTPUT_INVALID",
                          "TRANSIENT.HTTP_5XX", "TRANSIENT.DOWNLOAD_FAILED"}
    assert all(set(p) == {"code", "label", "hover", "group", "action"} for p in it["problems"])
    assert codes["NEEDS_HUMAN.AUTH_FAILED"]["group"] == "needs_you"
    assert codes["TRANSIENT.DOWNLOAD_FAILED"]["hover"].startswith("附件下载超时")
    # enrich 连着失败够次数：用「暂时放弃」那条代替概要失败
    storage.write_json(obj / "enrich-state.json", {"fails": 3, "last_error": "还缺：summary", "retry_after": "2026-10-05T00:00:00+10:00"})
    catalog.build()
    codes = {p["code"]: p for p in _item("v1")[0]["problems"]}
    assert "TRANSIENT.HTTP_5XX" not in codes and codes["TRANSIENT.RETRY_EXHAUSTED"]["action"] == "gave_up"
    assert f"{problems.when_text('2026-10-05T00:00:00+10:00')} 再试" in codes["TRANSIENT.RETRY_EXHAUSTED"]["hover"]


def test_catalog_data_carries_the_state_registry(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    _, _, data_path = catalog.build()
    data = json.loads(data_path.read_text("utf-8"))
    assert data["state_registry"] == problems.registry_for_js()


# --------------------------------------------------------------------------
# enrich：暂时放弃 → 退避后自动捡回来；旧状态（fails≥3 没有 retry_after）下一晚就捡
# --------------------------------------------------------------------------


def test_enrich_backoff_and_old_given_up_items_come_back():
    assert enrich.retry_after_for(2) is None
    assert enrich.retry_after_for(3, at(1)).startswith("2026-10-03T00:00")
    assert enrich.retry_after_for(4, at(1)).startswith("2026-10-05T00:00")
    assert enrich.retry_after_for(9, at(1)).startswith("2026-10-08T00:00")
    assert enrich.backing_off({"fails": 3, "retry_after": "2026-10-03T00:00:00+10:00"}, at(2)) is True
    assert enrich.backing_off({"fails": 3, "retry_after": "2026-10-03T00:00:00+10:00"}, at(3)) is False
    assert enrich.backing_off({"fails": 5}, at(2)) is False  # 0921 起就放弃的旧状态：捡回来再试
    assert enrich.backing_off({"fails": 1}, at(2)) is False


# --------------------------------------------------------------------------
# 问答：资料筛选失败 → SKIPPED.FALLBACK（结果里保留 selection_failed）
# --------------------------------------------------------------------------

ITEMS = [{"id": str(i), "title": f"项目 {i}", "tags": [], "summary": "", "note": f"{i}.md", "url": "",
          "search_fields": {"body": f"相关项目 {i} 的说明。"}} for i in range(12)]


def test_ask_selection_failure_is_recorded_as_skipped(monkeypatch, pushes):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    replies = iter([{"status": "failed", "error": "timeout"}, {"status": "ok", "text": "答[来源1]"}])
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: next(replies))
    r = ask.answer("推荐相关项目")
    assert r["status"] == "ok" and r["selection_failed"] is True
    row = problems.load()[0]
    assert (row["step"], row["code"], row["action"], row["group"]) == ("ask", "SKIPPED.FALLBACK", "skipped", "off")
    assert pushes == [] and problems.summary()["skipped"] == 1 and problems.summary()["needs_human"] == 0


# --------------------------------------------------------------------------
# CLI：list 带 label/hover/group · resolve · summary · 夜跑步骤名
# --------------------------------------------------------------------------


def _cli(capsys, *argv):
    code = cli.main(["problems", *argv])
    out = capsys.readouterr()
    return code, json.loads(out.out.strip().splitlines()[-1]), out.err


@pytest.mark.parametrize("step", ["nightly.run", "nightly.catalog-final", "nightly.attachments-all",
                                  "nightly.vision-refine", "nightly.sync-favorites"])
@pytest.mark.parametrize("code", ["TRANSIENT.STEP_TIMEOUT", "TRANSIENT.STEP_CRASHED", "PERMANENT.STEP_ARGS",
                                  "TRANSIENT.SECRET_TIMEOUT", "TRANSIENT.INTERRUPTED", "TRANSIENT.ACCOUNT_BUSY"])
def test_cli_nightly_codes_and_step_names(capsys, pushes, step, code):
    rc, out, _ = _cli(capsys, "report", "--step", step, "--code", code, "--reason", "超过 45 分钟")
    assert rc == 0 and out["ok"] and out["row"]["code"] == code and pushes == []
    rc, out, _ = _cli(capsys, "list")
    row = out["problems"][0]
    assert row["label"] == problems.STATE_REGISTRY[code]["label"] and row["group"] in ("auto", "gave_up")
    assert row["hover"] and "{" not in row["hover"] and row["step_label"].startswith("夜跑：")
    rc, out, _ = _cli(capsys, "resolve", "--step", step)
    assert rc == 0 and out == {"ok": True, "code": "", "message": "已解决 1 条", "resolved": 1}


def test_cli_sync_stuck_pushes_once(capsys, pushes):
    for _ in range(2):
        rc, out, _ = _cli(capsys, "report", "--step", "nightly.sync-favorites", "--code", "NEEDS_HUMAN.SYNC_STUCK",
                          "--reason", "占着号 3 小时没进展")
        assert rc == 0
    assert len(pushes) == 1 and pushes[0][1].startswith("同步卡住了")


def test_cli_resolve_by_item_and_code(capsys, pushes):
    problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id="xhs-1")
    problems.report("attachments.download", "TRANSIENT.DOWNLOAD_FAILED", "超时", item_id="xhs-2")
    rc, out, _ = _cli(capsys, "resolve", "--step", "attachments.download", "--item-id", "xhs-1",
                      "--code", "TRANSIENT.DOWNLOAD_FAILED")
    assert rc == 0 and out["resolved"] == 1 and [r["item_id"] for r in problems.load()] == ["xhs-2"]
    rc, out, _ = _cli(capsys, "resolve", "--step", "embed")
    assert rc == 0 and out["resolved"] == 0 and out["message"] == "没有要解决的"


@pytest.mark.parametrize("argv", [["--step", "nightly."], ["--step", "nightly.Bad Name"], ["--step", "whatever"],
                                  ["--step", "embed", "--code", "bad.code"]])
def test_cli_resolve_rejects_bad_input(capsys, argv):
    rc, out, err = _cli(capsys, "resolve", *argv)
    assert rc == 1 and out["ok"] is False and err.strip()


def test_cli_summary_rechecks_the_sync_pid_and_rewrites_the_file(capsys, monkeypatch):
    storage.write_json(sync_state.path(), {"state": "running", "pid": 999999, "progress": "第 2/5 条"})
    monkeypatch.setattr(sync_state, "_alive", lambda pid: False)
    rc, out, _ = _cli(capsys, "summary")
    assert rc == 0 and out["ok"] and out["sync"]["state"] == "failed" and out["sync"]["code"] == "INTERRUPTED"
    disk = json.loads(problems.summary_path().read_text("utf-8"))
    assert disk["sync"]["code"] == "INTERRUPTED" and set(disk) == SUMMARY_KEYS
    assert json.loads(sync_state.path().read_text("utf-8"))["code"] == "INTERRUPTED"


def test_cli_export_is_redacted(capsys, pushes, tmp_path):
    home = str(__import__("pathlib").Path.home())
    problems.report("embed", "TRANSIENT.NETWORK",
                    f"Authorization: Bearer abc.def apiKey=sk-1234567890abcd {home}\\x.log xsec_token=SECRET1 cookie=a1b2")
    rc, out, _ = _cli(capsys, "export")
    text = out["text"]
    for secret in ("abc.def", "sk-1234567890abcd", "SECRET1", "a1b2", home):
        assert secret not in text
