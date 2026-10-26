"""1027 设置页「AI 控制台」折线（usage.summary()["series"]）：近 30 天每天 × 服务商 / 模型 / 功能的人民币。
免费 / 未计价的调用不画成 ¥0（那天记 None，整条都没花钱的键不进折线）；一次都没调用的那天记 0；和表格同一个账本。不联网。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from link_brain import usage

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=BJ)
DS = {"endpoint": "https://api.deepseek.com/chat/completions", "model": "deepseek-flash"}
GEM = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def test_series_paid_only_free_is_gap_not_zero():
    with usage.tag("ask"):
        usage.record("textAI", DS, {"prompt_tokens": 1_000_000, "completion_tokens": 0}, now=NOW)                    # 今天 ¥2
        usage.record("textAI", DS, {"prompt_tokens": 500_000, "completion_tokens": 0}, now=NOW - timedelta(days=2))  # 前天 ¥1
    with usage.tag("summary"):
        usage.record("summaryAI", {"endpoint": GEM, "model": "gemini-3.5-flash", "keyPool": "gemini"},
                     {"prompt_tokens": 50, "completion_tokens": 5}, now=NOW)                                          # 免费
        usage.record("summaryAI", {"endpoint": GEM, "model": "gemini-3.5-flash", "apiKey": "paid"},
                     {"prompt_tokens": 50, "completion_tokens": 5}, now=NOW - timedelta(days=1))                     # 未计价
    s = usage.summary(now=NOW)
    se = s["series"]
    assert len(se["dates"]) == 30 and se["dates"][-1] == "2026-10-14" and se["dates"][0] == "2026-09-15"
    ds = se["providers"]["deepseek"]
    assert ds[-1] == pytest.approx(2.0) and ds[-3] == pytest.approx(1.0)
    assert ds[-2] == 0, "那天一次都没调用 DeepSeek：0"
    assert "google" not in se["providers"], "整条只有免费 / 未计价：不进折线（不画成 ¥0）"
    assert "summary" not in se["features"] and "ask" in se["features"]
    assert list(se["models"]) == ["deepseek|deepseek-flash"], "模型键和 windows.models 同一个写法"
    # 同一账本：30 天折线加起来 = 30 天表格合计
    assert sum(v or 0 for v in ds) == pytest.approx(s["windows"]["30d"]["providers"]["deepseek"]["cost"])


def test_series_day_with_only_free_calls_is_none():
    with usage.tag("ask"):
        usage.record("textAI", DS, {"prompt_tokens": 1_000_000, "completion_tokens": 0}, now=NOW)
        usage.record("textAI", {"mode": "cli", "command": "codex exec -"}, {"prompt_tokens": 9, "completion_tokens": 9}, now=NOW - timedelta(days=1))
    se = usage.summary(now=NOW)["series"]
    ask = se["features"]["ask"]
    assert ask[-1] == pytest.approx(2.0)
    assert ask[-2] is None, "那天只有本机命令行（免费 / 未计费）：None，不是 ¥0"
