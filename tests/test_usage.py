"""1016 用量记账：记账点 → 账本 → 按功能 / 提供商 / 窗口汇总 → 按现价折算；余额；问题行带跳转。不联网。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from link_brain import storage, usage

BJ = timezone(timedelta(hours=8))


def _rows():
    d = storage.archive_root() / "usage"
    return [json.loads(l) for p in sorted(d.glob("*.jsonl")) for l in p.read_text(encoding="utf-8").splitlines()]


def test_record_uses_tag_then_cap_and_never_stores_key():
    cfg = {"endpoint": "https://api.deepseek.com/chat/completions", "model": "deepseek-flash", "apiKey": "sk-secret"}
    usage.record("textAI", cfg, {"prompt_tokens": 100, "completion_tokens": 20})
    with usage.tag("expand", item="n1"):
        usage.record("textAI", cfg, {"prompt_tokens": 5, "completion_tokens": 1})
    rows = _rows()
    assert [r["f"] for r in rows] == ["ask", "expand"]
    assert rows[0]["p"] == "deepseek" and rows[0]["in"] == 100 and rows[0]["out"] == 20
    assert rows[1]["item"] == "n1"
    assert "sk-secret" not in (storage.archive_root() / "usage").joinpath(rows[0]["ts"][:7] + ".jsonl").read_text(encoding="utf-8")


def test_provider_of():
    assert usage.provider_of("https://dashscope.aliyuncs.com/compatible-mode/v1") == "aliyun"
    assert usage.provider_of("https://api.deepseek.com/chat/completions") == "deepseek"
    assert usage.provider_of("http://127.0.0.1:9000/v1") == "127.0.0.1:9000"


def test_summary_windows_features_and_cost():
    now = datetime(2026, 10, 14, 10, 0, tzinfo=BJ)  # 周三 10 点 = DeepSeek 高峰
    ds = {"endpoint": "https://api.deepseek.com/x", "model": "deepseek-flash"}
    qw = {"endpoint": "https://dashscope.aliyuncs.com/x", "model": "qwen3.8-flash"}
    with usage.tag("ask"):
        usage.record("textAI", ds, {"prompt_tokens": 1_000_000, "completion_tokens": 0}, now=now)
    with usage.tag("vision", item="a"):
        usage.record("visionAI", qw, {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}, now=now - timedelta(days=3))
    with usage.tag("vision", item="a"):
        usage.record("visionAI", qw, {"prompt_tokens": 0, "completion_tokens": 0}, ok=False, now=now - timedelta(days=3))
    usage.record("embedAI", {"endpoint": "https://dashscope.aliyuncs.com/x", "model": "no-such-model"},
                 {"prompt_tokens": 10, "total_tokens": 10}, now=now - timedelta(days=20))
    s = usage.summary(now=now)
    today, week, month = s["windows"]["today"], s["windows"]["7d"], s["windows"]["30d"]
    assert today["features"]["ask"]["cost"] == pytest.approx(2.0)            # 高峰输入价 2 元 / 百万
    assert "vision" not in today["features"]
    v = week["features"]["vision"]
    assert (v["calls"], v["failed"], v["items"]) == (2, 1, 1)
    assert v["cost"] == pytest.approx(0.8 + 2.7)
    assert month["features"]["embed"]["unpriced"] == 1                       # 价格表里没有：不编金额
    assert set(month["providers"]) == {"deepseek", "aliyun"}
    assert len(s["daily"]) == 30 and s["daily"][-1]["date"] == "2026-10-14"


def test_deepseek_offpeak_is_half_price():
    pricing = {"models": {"deepseek-flash": {"currency": "CNY", "input": 2.0, "output": 8.0,
                                             "input_offpeak": 1.0, "output_offpeak": 4.0}}}
    sat = {"p": "deepseek", "m": "deepseek-flash", "in": 1_000_000, "out": 0, "_ts": datetime(2026, 10, 17, 10, tzinfo=BJ)}
    tue_night = {**sat, "_ts": datetime(2026, 10, 13, 22, tzinfo=BJ)}
    tue_peak = {**sat, "_ts": datetime(2026, 10, 13, 15, tzinfo=BJ)}
    assert usage.cost_of(sat, pricing) == pytest.approx(1.0)
    assert usage.cost_of(tue_night, pricing) == pytest.approx(1.0)
    assert usage.cost_of(tue_peak, pricing) == pytest.approx(2.0)


def test_text_stream_call_records_once(monkeypatch):
    from link_brain import text_stream
    monkeypatch.setattr(text_stream, "http_call", lambda *a, **k: {"status": "ok", "text": "hi",
                                                                    "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    cfg = {"mode": "http", "endpoint": "https://api.deepseek.com/chat/completions", "model": "deepseek-flash", "apiKey": "k"}
    res = text_stream.call("i", "t", cfg, cap="summaryAI")
    assert res["status"] == "ok"
    text_stream.call("i", "t", cfg, cap="textAI", feature="other")
    assert [(r["f"], r["in"], r["out"]) for r in _rows()] == [("summary", 7, 3), ("other", 7, 3)]


def test_skipped_call_is_not_recorded():
    from link_brain import text_stream
    text_stream.call("i", "t", {"mode": "off"}, cap="textAI")
    assert not (storage.archive_root() / "usage").exists() or _rows() == []


def test_deepseek_balance_parses_and_maps_errors(monkeypatch):
    import httpx

    class R:
        def __init__(self, code, doc):
            self.status_code, self._doc, self.text = code, doc, json.dumps(doc)

        def json(self):
            return self._doc

    monkeypatch.setattr(usage, "_deepseek_key", lambda s: "sk-x")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R(200, {"is_available": True, "balance_infos": [
        {"currency": "CNY", "total_balance": "105.38", "granted_balance": "4.40", "topped_up_balance": "100.97"}]}))
    got = usage.deepseek_balance({})
    assert got["ok"] and got["balances"][0]["total"] == "105.38"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R(401, {"error": "Authentication Fails"}))
    got = usage.deepseek_balance({})
    assert not got["ok"] and got["code"] == "NEEDS_HUMAN.AUTH_FAILED"
    monkeypatch.setattr(usage, "_deepseek_key", lambda s: "")
    assert usage.deepseek_balance({})["code"] == "SKIPPED.NOT_CONFIGURED"


def test_problem_rows_get_console_links(monkeypatch):
    from link_brain import ai_health
    monkeypatch.setattr(ai_health, "status", lambda: {"visionAI": {"code": "NEEDS_HUMAN.AUTH_FAILED", "provider": "通义千问"}})
    rows = usage.decorate_problem_rows([{"step": "ai.vision", "code": "NEEDS_HUMAN.AUTH_FAILED"},
                                        {"step": "ai.vision", "code": "TRANSIENT.NETWORK"}])
    assert rows[0]["links"]["recharge"].startswith("https://usercenter2.aliyun.com/")
    assert rows[0]["links"]["console"].startswith("https://bailian.console.aliyun.com/")
    assert "links" not in rows[1]


def test_provider_links_from_pricing():
    links = usage.provider_links()
    assert links["deepseek"]["recharge"] == "https://platform.deepseek.com/top_up"
    assert links["deepseek"]["usage"] == "https://platform.deepseek.com/usage"
    assert links["aliyun"]["usage"].endswith("/costing-balance/usage-statistics")


def test_cli_usage_json(capsys):
    from link_brain import cli
    with usage.tag("ask"):
        usage.record("textAI", {"endpoint": "https://api.deepseek.com/x", "model": "deepseek-flash"},
                     {"prompt_tokens": 1, "completion_tokens": 1})
    assert cli.main(["usage"]) == 0
    doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert doc["ok"] and doc["summary"]["windows"]["today"]["total"]["calls"] == 1
    assert "balances" not in doc and "deepseek" in doc["links"]
