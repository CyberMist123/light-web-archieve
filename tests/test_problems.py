"""第 0 批：问题记录骨架（CONVENTIONS §2 / §3）。只测 problems 模块本身：还没有任何调用点接进来。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from link_brain import alert as alert_mod, cli, problems, storage

TZ = timezone(timedelta(hours=10))


def at(day: int, hour: int = 4):
    return lambda: datetime(2026, 10, day, hour, 0, tzinfo=TZ)


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(alert_mod, "_alert", lambda kind, title, body, **extra: sent.append((kind, title, body, extra)) or True)
    return sent


# --------------------------------------------------------------------------
# 码与分类
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code,cls", [
    ("NOT_LOGGED_IN", "NEEDS_HUMAN"), ("CAPTCHA_REQUIRED", "NEEDS_HUMAN"), ("RISK_HOLD", "NEEDS_HUMAN"),
    ("WRONG_ACCOUNT", "NEEDS_HUMAN"), ("NOT_INSTALLED", "NEEDS_HUMAN"), ("ACCOUNT_RISK", "NEEDS_HUMAN"),
    ("FAVORITES_SUSPICIOUS", "NEEDS_HUMAN"),
    ("RATE_LIMITED", "TRANSIENT"), ("DISCONNECTED", "TRANSIENT"), ("TIMEOUT", "TRANSIENT"), ("BUSY", "TRANSIENT"),
    ("INTERRUPTED", "TRANSIENT"), ("TOO_MANY_FAILURES", "TRANSIENT"),
    ("PERMANENT.PDF_ENCRYPTED", "PERMANENT"), ("SKIPPED.NOT_CONFIGURED", "SKIPPED"),
    ("TRANSIENT.HTTP_5XX", "TRANSIENT"), ("NEEDS_HUMAN.STUCK", "NEEDS_HUMAN"),
    ("HTTP_429", "TRANSIENT"), ("HTTP_503", "TRANSIENT"), ("HTTP_401", "NEEDS_HUMAN"), ("HTTP_403", "NEEDS_HUMAN"),
    ("HTTP_402", "NEEDS_HUMAN"), ("HTTP_400", "PERMANENT"),
    ("SOMETHING_NEW", "TRANSIENT"),  # 未知裸码：自动重试，3 天不好就升级 STUCK，不会悄悄藏起来
])
def test_classify(code, cls):
    assert problems.classify(code) == cls


def test_normalize_keeps_existing_codes_and_maps_http():
    assert problems.normalize("NOT_LOGGED_IN") == "NEEDS_HUMAN.NOT_LOGGED_IN"
    assert problems.normalize("HTTP_429") == "TRANSIENT.HTTP_429"
    assert problems.normalize("HTTP_502") == "TRANSIENT.HTTP_5XX"
    assert problems.normalize("HTTP_401") == "NEEDS_HUMAN.AUTH_FAILED"
    for bad in ("", "lower_case", "FOO.BAR", "TRANSIENT.", "TRANSIENT.bad", "TRANSIENT.A.B"):
        with pytest.raises(problems.BadCode):
            problems.normalize(bad)


def test_lookup_exact_then_class_wildcard():
    assert problems.lookup("NOT_LOGGED_IN")["label"] == "需要登录"
    assert problems.lookup("NOT_LOGGED_IN")["where"] == "top+card"
    assert problems.lookup("TRANSIENT.SOMETHING_ELSE")["label"] == "稍后自动重试"
    assert problems.lookup("SKIPPED.WHATEVER")["group"] == "off"


# --------------------------------------------------------------------------
# 记录：折叠 / 解决 / 计数
# --------------------------------------------------------------------------


def test_report_appends_one_line_and_load_folds_by_key(pushes):
    p = problems.path()
    problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "PDF 有打开密码", item_id="xhs-1", title="教程",
                    _now_fn=at(1))
    problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "PDF 有打开密码", item_id="xhs-1", title="教程",
                    _now_fn=at(2))
    lines = p.read_text("utf-8").splitlines()
    assert len(lines) == 2 and all(json.loads(x)["key"] == "attachments.convert|xhs-1|PDF_ENCRYPTED" for x in lines)
    rows = problems.load()
    assert len(rows) == 1
    row = rows[0]
    assert row["count"] == 2 and row["action"] == "gave_up" and row["code"] == "PERMANENT.PDF_ENCRYPTED"
    assert row["label"] == "全文没转出来" and row["group"] == "gave_up" and row["where"] == "card"
    assert row["ts"].startswith("2026-10-02")
    assert pushes == [], "PERMANENT 不推送"


def test_report_row_shape_matches_conventions(pushes):
    row = problems.report("videos.transcribe", "TRANSIENT.HTTP_5XX", "x" * 500, item_id="xhs-9", title="t" * 300,
                          next_at="2026-10-03T04:00:00+10:00", _now_fn=at(1))
    stored = json.loads(problems.path().read_text("utf-8").splitlines()[0])
    for key in ("ts", "key", "step", "item_id", "title", "code", "reason", "action", "next_at", "count", "resolved_at"):
        assert key in stored
    assert len(stored["reason"]) == problems.REASON_MAX and len(stored["title"]) == problems.TITLE_MAX
    assert stored["action"] == "retry_later" and stored["next_at"].startswith("2026-10-03")
    assert len(problems.path().read_bytes().splitlines()[0]) <= 4096, "单次追加 ≤ 4 KB（§6.5）"
    assert row["written"] is True


def test_resolve_marks_resolved_and_recurrence_starts_fresh(pushes):
    problems.report("vision.refine", "TRANSIENT.HTTP_429", "限流", item_id="xhs-2", _now_fn=at(1))
    problems.report("vision.refine", "PERMANENT.MODEL_OUTPUT_INVALID", "格式不对", item_id="xhs-2", _now_fn=at(1))
    problems.report("vision.refine", "TRANSIENT.SERVICE_BUSY", "收手", _now_fn=at(1))  # 步骤级
    assert problems.resolve("vision.refine", "xhs-2", code="HTTP_429", _now_fn=at(1)) == 1
    left = {r["key"] for r in problems.load()}
    assert left == {"vision.refine|xhs-2|MODEL_OUTPUT_INVALID", "vision.refine||SERVICE_BUSY"}
    assert problems.resolve("vision.refine", "xhs-2", _now_fn=at(1)) == 1
    assert problems.resolve("vision.refine", _now_fn=at(1)) == 1  # item_id=None = 只解决步骤级
    assert problems.load() == []
    assert problems.resolve("vision.refine", "xhs-2") == 0
    resolved = problems.load(include_resolved=True)
    assert len(resolved) == 3 and all(r["resolved_at"] for r in resolved)
    # 解决之后同 key 又出现：新的一轮，count 从 1 算
    problems.report("vision.refine", "TRANSIENT.HTTP_429", "又限流", item_id="xhs-2", _now_fn=at(2))
    again = [r for r in problems.load() if r["key"] == "vision.refine|xhs-2|HTTP_429"]
    assert again[0]["count"] == 1 and again[0]["resolved_at"] is None


def test_load_orders_needs_human_first_then_auto_then_gave_up_then_off(pushes):
    problems.report("embed", "SKIPPED.NOT_CONFIGURED", "没配 embedding", _now_fn=at(1))
    problems.report("attachments.convert", "PERMANENT.PDF_DAMAGED", "坏了", item_id="xhs-1", _now_fn=at(1))
    problems.report("videos.transcribe", "TRANSIENT.NETWORK", "断网", item_id="xhs-2", _now_fn=at(1))
    problems.report("sync.favorites", "NOT_LOGGED_IN", "掉登录", _now_fn=at(1))
    assert [r["group"] for r in problems.load()] == ["needs_you", "auto", "gave_up", "off"]
    s = problems.summary()
    assert (s["needs_human"], s["auto"], s["gave_up"], s["skipped"]) == (1, 1, 1, 1)
    assert set(s["last_runs"]) == {"embed", "attachments.convert", "videos.transcribe", "sync.favorites"}
    problems.resolve("sync.favorites")
    assert problems.summary()["needs_human"] == 0
    assert problems.summary()["last_runs"]["sync.favorites"]["ok"] is True


def test_bad_lines_are_skipped_not_fatal(pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(1))
    with problems.path().open("a", encoding="utf-8") as fh:
        fh.write('{"half line\n\n[1,2]\n')
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(1))
    assert problems.load()[0]["count"] == 2


def test_bad_code_or_action_raises():
    with pytest.raises(problems.BadCode):
        problems.report("embed", "nope", "x")
    with pytest.raises(ValueError):
        problems.report("embed", "TRANSIENT.NETWORK", "x", action="whatever")


def test_report_never_raises_on_disk_failure(monkeypatch, pushes):
    def boom(rows):
        raise OSError("磁盘满了")
    monkeypatch.setattr(problems, "_append", boom)
    row = problems.report("login", "NEEDS_HUMAN.NOT_LOGGED_IN", "掉登录", _now_fn=at(1))
    assert row["written"] is False and len(pushes) == 1, "写不进去也照样推（要人处理的事不能因为磁盘丢）"


# --------------------------------------------------------------------------
# 推送出口
# --------------------------------------------------------------------------


def test_needs_human_pushes_once_per_unresolved_key(pushes):
    for d in (1, 1, 2, 3):
        problems.report("sync.favorites", "NOT_LOGGED_IN", "掉登录", _now_fn=at(d))
    assert len(pushes) == 1
    kind, title, body, extra = pushes[0]
    assert kind == "problem" and title.startswith("需要登录") and extra["code"] == "NEEDS_HUMAN.NOT_LOGGED_IN"
    # 别的 key（别的 step / 别的码）各推一次
    problems.report("login", "NOT_LOGGED_IN", "掉登录", _now_fn=at(3))
    problems.report("sync.favorites", "CAPTCHA_REQUIRED", "验证码", _now_fn=at(3))
    assert len(pushes) == 3
    # 解决之后再出现：再推一次
    problems.resolve("sync.favorites", code="NOT_LOGGED_IN")
    problems.report("sync.favorites", "NOT_LOGGED_IN", "又掉了", _now_fn=at(4))
    assert len(pushes) == 4
    problems.report("sync.favorites", "NOT_LOGGED_IN", "又掉了", _now_fn=at(4))
    assert len(pushes) == 4


def test_permanent_and_skipped_and_transient_do_not_push(pushes):
    problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", "密码", item_id="a", _now_fn=at(1))
    problems.report("embed", "SKIPPED.DISABLED", "关了", _now_fn=at(1))
    problems.report("videos.transcribe", "TRANSIENT.HTTP_5XX", "500", item_id="b", _now_fn=at(1))
    assert pushes == []


def test_transient_three_consecutive_days_escalates_to_stuck_once(pushes):
    for d in (1, 1, 2):
        problems.report("videos.transcribe", "TRANSIENT.HTTP_5XX", "接口 500", item_id="xhs-5", title="视频",
                        _now_fn=at(d))
    assert pushes == [] and all(r["code"] != "NEEDS_HUMAN.STUCK" for r in problems.load())
    problems.report("videos.transcribe", "TRANSIENT.HTTP_5XX", "接口 500", item_id="xhs-5", title="视频", _now_fn=at(3))
    stuck = [r for r in problems.load() if r["code"] == "NEEDS_HUMAN.STUCK"]
    # 升级按步骤记（item_id=None）：同一个原因卡住多篇也只算一件事
    assert len(stuck) == 1 and stuck[0]["key"] == "videos.transcribe||STUCK"
    assert stuck[0]["item_id"] is None and "连续 3 天" in stuck[0]["reason"] and stuck[0]["group"] == "needs_you"
    assert len(pushes) == 1 and pushes[0][1].startswith("连续几天没修好")
    # 第 4 天还在：STUCK 没解决，不重推、不重复登记
    problems.report("videos.transcribe", "TRANSIENT.HTTP_5XX", "接口 500", item_id="xhs-5", _now_fn=at(4))
    assert len(pushes) == 1 and len([r for r in problems.load() if r["code"] == "NEEDS_HUMAN.STUCK"]) == 1
    # 成功一次：transient 和 STUCK 一起解决
    assert problems.resolve("videos.transcribe", "xhs-5") == 2
    assert problems.load() == []


def test_transient_with_a_gap_day_does_not_escalate(pushes):
    for d in (1, 2, 4, 5):
        problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(d))
    assert pushes == []
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(6))  # 4、5、6 连续
    assert len(pushes) == 1


def test_resolution_resets_the_day_streak(pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(1))
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(2))
    problems.resolve("embed")
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(3))
    assert pushes == []


# --------------------------------------------------------------------------
# 压实
# --------------------------------------------------------------------------


def test_compaction_keeps_latest_500_keys_and_their_state(monkeypatch, pushes):
    monkeypatch.setattr(problems, "MAX_KEYS", 20)
    for i in range(25):
        problems.report("attachments.convert", "PERMANENT.PDF_DAMAGED", f"坏 {i}", item_id=f"xhs-{i:03d}",
                        _now_fn=lambda i=i: datetime(2026, 10, 1, 0, i, tzinfo=TZ))
    lines = problems.path().read_text("utf-8").splitlines()
    assert len(lines) <= 21
    keys = {r["key"] for r in problems.load()}
    assert "attachments.convert|xhs-024|PDF_DAMAGED" in keys and "attachments.convert|xhs-000|PDF_DAMAGED" not in keys
    # 压实后折叠出来的 count / days / notified 不丢
    for d in (1, 2):
        problems.report("sync.favorites", "NOT_LOGGED_IN", "掉登录", _now_fn=at(d, 5))
    for i in range(30):
        problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=lambda: datetime(2026, 10, 2, 6, tzinfo=TZ))
    row = next(r for r in problems.load() if r["key"] == "sync.favorites||NOT_LOGGED_IN")
    assert row["count"] == 2 and row["notified"] is True
    problems.report("sync.favorites", "NOT_LOGGED_IN", "掉登录", _now_fn=at(3, 5))
    assert len(pushes) == 1, "压实之后也不会重推"
    assert len(problems.path().read_text("utf-8").splitlines()) <= 21


def test_compaction_holds_the_problems_lock(pushes):
    problems.report("embed", "TRANSIENT.NETWORK", "断网", _now_fn=at(1))
    with storage.file_lock("problems"):
        # 同进程可重入：压实自己拿得到；别的进程此时追加会等 / 退化为不压实的追加
        assert problems.compact() is False


# --------------------------------------------------------------------------
# 复制报错（脱敏）
# --------------------------------------------------------------------------


def test_redact_strips_secrets_paths_and_xsec_token(tmp_path):
    home = tmp_path / "home" / "someone"
    vault = tmp_path / "data" / "vault"
    text = (f'apiKey=sk-abcdef1234567890 "token": "t0p-secret" Cookie: a=b; c=d Authorization: Bearer abc.def.ghi '
            f'https://www.xiaohongshu.com/explore/1?xsec_token=ABC123&xsec_source=pc '
            f'{vault}\\_archive\\x.json {home}\\.link-brain\\reader.log {str(home).replace(chr(92), "/")}/a')
    out = problems.redact(text, vault=vault, home=home)
    for secret in ("sk-abcdef1234567890", "t0p-secret", "a=b", "abc.def.ghi", "ABC123", str(home), str(vault)):
        assert secret not in out, secret
    assert "<vault>\\_archive\\x.json" in out and "~\\.link-brain\\reader.log" in out and "~/a" in out
    assert "xsec_source=pc" in out and "xsec_token=<redacted>" in out


def test_export_redacted_has_versions_steps_and_recent_problems(monkeypatch, pushes):
    vault = storage.vault_root()
    problems.report("attachments.convert", "PERMANENT.PDF_ENCRYPTED", f"打不开 {vault}\\a.pdf apiKey=sk-zzzzzzzzzzzz",
                    item_id="xhs-1", title="我的教程", _now_fn=at(1))
    text = problems.export_redacted(plugin_version="9.9.9")
    assert "插件版本：9.9.9" in text and "Python：" in text
    assert "attachments.convert" in text and "xhs-1" in text and "我的教程" in text, "item_id 和标题是用户自己的数据，保留"
    assert str(vault) not in text and "sk-zzzz" not in text and "<vault>" in text


# --------------------------------------------------------------------------
# CLI：python -m link_brain problems list|report|export
# --------------------------------------------------------------------------


def _last_json(out: str):
    return json.loads(out.strip().splitlines()[-1])


def test_cli_report_list_export(capsys, pushes):
    assert cli.main(["problems", "report", "--step", "nightly.attachments", "--code", "TRANSIENT.STEP_TIMEOUT",
                     "--reason", "步骤超过 40 分钟"]) == 0
    out = _last_json(capsys.readouterr().out)
    assert out["ok"] is True and out["row"]["code"] == "TRANSIENT.STEP_TIMEOUT" and out["row"]["step"] == "nightly.attachments"
    assert cli.main(["problems", "list"]) == 0
    listed = _last_json(capsys.readouterr().out)
    assert listed["ok"] is True and listed["summary"]["auto"] == 1 and listed["problems"][0]["label"] == "步骤超时"
    assert cli.main(["problems", "export"]) == 0
    exported = _last_json(capsys.readouterr().out)
    assert "nightly.attachments" in exported["text"]


def test_cli_report_rejects_bad_step_and_code(capsys):
    assert cli.main(["problems", "report", "--step", "nightly.x", "--code", "nope"]) == 1
    assert "故障码格式不对" in capsys.readouterr().err.strip().splitlines()[-1]
    assert cli.main(["problems", "report", "--step", "whatever", "--code", "TRANSIENT.NETWORK"]) == 1
    assert "step 不在词表里" in capsys.readouterr().err
    assert not problems.path().exists()
    assert cli.main(["problems"]) == 1
