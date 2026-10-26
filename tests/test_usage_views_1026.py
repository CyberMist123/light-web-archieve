"""1026（录屏场景 08 · 25:09「没有按照 API 来换的」）：花费按服务商 / 按 API 或模型 / 按功能三种看法、人民币、每次调用可追溯；
免费的（本机命令行如 OpenCode、Gemini 免费 key 池）记「免费 / 未计费」不算进 ¥（她 1023 拍板）；价格表里查不到的记「未计价」，
不编金额、不当 0（已知缺口：gemini-3.5-flash 付费档、gemini-embedding-2、命令行空模型名）。不联网。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from link_brain import ai_routes, pricing, storage, usage

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=BJ)   # 周三 10 点 = DeepSeek 高峰
DS = {"endpoint": "https://api.deepseek.com/chat/completions", "model": "deepseek-flash"}
GEM = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def _raw(row: dict) -> None:
    """直接写一行老账本（1023 前的命令行行没有模型名）。"""
    d = storage.archive_root() / "usage"
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"{NOW:%Y-%m}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _ledger():
    with usage.tag("ask", item="n-ask"):
        usage.record("textAI", DS, {"prompt_tokens": 1_000_000, "completion_tokens": 0}, now=NOW)            # ¥2.00
    with usage.tag("summary", item="n-sum"):
        usage.record("summaryAI", {"endpoint": GEM, "model": "gemini-3.5-flash", "keyPool": "gemini"},
                     {"prompt_tokens": 5000, "completion_tokens": 300}, now=NOW)                             # 免费 key 池
        usage.record("summaryAI", {"mode": "cli", "command": "opencode run -m opencode/deepseek-v4.1-flash-free --pure"},
                     {"prompt_tokens": 800, "completion_tokens": 100}, now=NOW)                              # 本机命令行
        usage.record("summaryAI", {"endpoint": GEM, "model": "gemini-3.5-flash", "apiKey": "paid"},
                     {"prompt_tokens": 900, "completion_tokens": 90}, now=NOW)                               # 付费 key：价格没核到 → 未计价
    usage.record("embedAI", {"endpoint": GEM, "model": "gemini-embedding-2", "apiKey": "paid"},
                 {"prompt_tokens": 10, "total_tokens": 10}, now=NOW)                                         # 未计价
    _raw({"ts": NOW.isoformat(timespec="seconds"), "f": "ask", "p": "cli", "m": "", "in": 0, "out": 0, "ok": True})   # 老的空模型名


def test_bill_of_three_states():
    t = pricing.table()
    assert pricing.bill_of({"p": "cli", "m": ""}, t) == (0.0, "free")
    assert pricing.bill_of({"p": "google", "m": "gemini-3.5-flash", "free": True, "in": 9, "out": 9}, t) == (0.0, "free")
    assert pricing.bill_of({"p": "google", "m": "gemini-3.5-flash", "in": 9, "out": 9}, t) == (None, "unpriced")
    assert pricing.bill_of({"p": "google", "m": "gemini-embedding-2", "in": 9, "out": 0}, t) == (None, "unpriced")
    assert pricing.bill_of({"p": "x", "m": "no-such-model", "in": 9}, t) == (None, "unpriced")
    cost, st = pricing.bill_of({"p": "deepseek", "m": "deepseek-flash", "in": 1_000_000, "out": 0, "_ts": NOW}, t)
    assert st == "paid" and cost == pytest.approx(2.0)
    assert not pricing.is_priced(t["models"]["gemini-3.5-flash"]) and pricing.is_priced(t["models"]["deepseek-flash"])


def test_summary_by_provider_model_feature_free_not_in_yuan():
    _ledger()
    s = usage.summary(now=NOW)
    w = s["windows"]["today"]
    tot = w["total"]
    assert (tot["calls"], tot["free"], tot["unpriced"]) == (6, 3, 2)
    assert tot["cost"] == pytest.approx(2.0), "合计只算真花的钱：免费的不算进 ¥、未计价的不当 0 也不编"
    # 按服务商
    assert w["providers"]["deepseek"]["cost"] == pytest.approx(2.0)
    g = w["providers"]["google"]
    assert (g["calls"], g["free"], g["unpriced"], g["cost"]) == (3, 1, 2, 0)
    assert (w["providers"]["cli"]["calls"], w["providers"]["cli"]["free"]) == (2, 2)
    # 按 API 或模型（键 = 服务商|模型；空模型名的命令行行也有一格）
    m = w["models"]
    assert m["deepseek|deepseek-flash"]["cost"] == pytest.approx(2.0) and m["deepseek|deepseek-flash"]["model"] == "deepseek-flash"
    assert (m["google|gemini-3.5-flash"]["free"], m["google|gemini-3.5-flash"]["unpriced"]) == (1, 1)
    assert m["cli|opencode opencode/deepseek-v4.1-flash-free"]["free"] == 1
    assert m["cli|"]["free"] == 1 and m["cli|"]["provider"] == "cli"
    assert {(u["model"], u["calls"]) for u in w["unpriced_models"]} == {("gemini-3.5-flash", 1), ("gemini-embedding-2", 1)}
    # 按功能
    assert w["features"]["summary"]["free"] == 2 and w["features"]["summary"]["unpriced"] == 1
    # 本月按服务商（钥匙串「本月」那一句）也带免费次数
    assert s["month"]["cli"]["free"] == 2


def test_every_call_traceable():
    _ledger()
    s = usage.summary(now=NOW)
    rec = s["recent"]
    assert len(rec) == 6 and s["recent_limit"] == usage.RECENT_LIMIT
    by = {(r["p"], r["m"], r["status"]) for r in rec}
    assert ("deepseek", "deepseek-flash", "paid") in by
    assert ("google", "gemini-3.5-flash", "free") in by and ("google", "gemini-3.5-flash", "unpriced") in by
    ask = next(r for r in rec if r["p"] == "deepseek")
    assert ask["item"] == "n-ask" and ask["f"] == "ask" and ask["cost"] == pytest.approx(2.0)
    assert all(r["cost"] is None for r in rec if r["status"] == "unpriced"), "未计价的一次不写 0"
    assert all("apiKey" not in json.dumps(r) and "paid" != r.get("m") for r in rec), "不带 key"


def test_recent_is_capped(monkeypatch):
    monkeypatch.setattr(usage, "RECENT_LIMIT", 3)
    _ledger()
    s = usage.summary(now=NOW)
    assert len(s["recent"]) == 3 and s["recent_limit"] == 3


def test_route_entry_with_null_price_is_unpriced_not_by_usage():
    t = pricing.table()
    e = ai_routes._entry({"endpoint": GEM, "model": "gemini-3.5-flash", "apiKey": "paid"}, "Gemini", t, (1000.0, 100.0), 100, "篇")
    assert e.get("unpriced") is True and e["price"] == "—，未计价"
    f = ai_routes._entry({"endpoint": GEM, "model": "gemini-3.5-flash", "keyPool": "gemini"}, "Gemini 免费", t, (1000.0, 100.0), 100, "篇")
    assert f["free"] is True and f["price"] == "免费"
    c = ai_routes._entry({"mode": "cli", "command": "opencode run"}, "OpenCode", t, None, 1, "次")
    assert c["free"] is True and c["price"].startswith("免费")
