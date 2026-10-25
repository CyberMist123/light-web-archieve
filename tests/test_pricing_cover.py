"""pricing 的补充用例（现有 test_pricing_1023.py 已盖 is_free / is_paid 的主要形状和表内模型）。

按任务说明：price_of 未知模型、cny / token_cost / audio_cost 缺字段或 None、
is_free / is_paid 补充形状、offpeak 边界时刻（全部用固定带时区的 datetime，不用当前时间）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from link_brain import pricing

USD = {"usd_cny": {"rate": 7.2}, "models": {}}


def test_price_of_unknown_and_empty():
    p = {"models": {"m1": {"input": 1, "output": 2}, "m2": {"aliases": ["别名甲"]}}}
    assert pricing.price_of("m1", p) == ("m1", p["models"]["m1"])
    assert pricing.price_of("别名甲", p) == ("m2", p["models"]["m2"])   # 按别名查到
    assert pricing.price_of("查无此模型", p) is None
    assert pricing.price_of("", p) is None
    assert pricing.price_of(None, p) is None
    assert pricing.price_of("随便", {"models": {}}) is None


def test_cny_converts_usd_and_passes_cny_through():
    assert pricing.cny(USD, {"currency": "USD"}, 10.0) == 72.0
    assert pricing.cny({"usd_cny": {}}, {"currency": "USD"}, 10.0) is None      # 没有汇率
    assert pricing.cny(USD, {}, 3.5) == 3.5                                     # 人民币原样
    assert pricing.cny(USD, {}, None) is None


def test_token_cost_missing_fields_is_none():
    p = {"models": {}}
    info = {"input": 12.0, "output": 24.0}                                      # 百万 token 价
    assert pricing.token_cost(p, info, 1_000_000, 500_000) == 24.0              # 12 + 12
    assert pricing.token_cost(p, {"input": 12.0}, 100, 100) is None             # 缺 output
    assert pricing.token_cost(p, {"output": 24.0}, 100, 100) is None            # 缺 input
    assert pricing.token_cost(p, {"input": None, "output": None}, 100, 100) is None


def test_audio_cost_price_unit_and_missing():
    p = {"models": {}}
    assert pricing.audio_cost(p, {"price": 0.5}, 10) == 5.0                     # 每分钟 0.5 元 × 10 分钟
    assert pricing.audio_cost(p, {"price": 0.5, "unit": "per_second"}, 1) == 30.0  # 每秒价 × 60
    assert pricing.audio_cost(p, {}, 10) is None                                # 没写价
    assert pricing.audio_cost(p, {"price": 1.0, "currency": "USD"}, 2) is None  # USD 没汇率


def test_is_free_explicit_marks_only():
    p = {"models": {"f": {"free": True}, "paid": {"input": 1, "output": 2}}}
    assert pricing.is_free({"mode": "cli"}) is True
    assert pricing.is_free({"free": True}) is True
    assert pricing.is_free({"keyPool": "gemini"}) is True
    assert pricing.is_free({"keyPool": "别的池"}, p) is False                    # 别的池不白送
    assert pricing.is_free({"model": "f"}, p) is True                           # 表里 free: true
    assert pricing.is_free({"model": "paid"}, p) is False
    assert pricing.is_free({}) is False
    assert pricing.is_free(None) is False


def test_is_paid_unpriced_and_zero_price():
    p = {"models": {"paid": {"input": 1, "output": 2}, "nulled": {"input": None, "output": None},
                    "zero": {"input": 0, "output": 0}}}
    assert pricing.is_paid({"model": "paid"}, p) is True
    assert pricing.is_paid({"model": "nulled"}, p) is True                      # 表里有但价是 null = 要钱
    assert pricing.is_paid({"model": "zero"}, p) is False                       # 全 0 = 不要钱
    assert pricing.is_paid({"model": "查无"}, p) is True                        # 查不到 = 当要钱（宁可多拦）
    assert pricing.is_paid({"mode": "cli"}, p) is False
    assert pricing.is_paid({}, p) is True


def _bj(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone(timedelta(hours=8)))


def test_offpeak_boundaries_beijing_time():
    # 工作日高峰 = 北京时间周一至五 9-12、14-18 之外都算空闲
    assert pricing.offpeak(_bj(2026, 10, 26, 10)) is False        # 周一 10:00
    assert pricing.offpeak(_bj(2026, 10, 26, 9)) is False         # 9:00 整进高峰
    assert pricing.offpeak(_bj(2026, 10, 26, 12)) is True         # 12:00 午休出高峰
    assert pricing.offpeak(_bj(2026, 10, 26, 13, 59)) is True
    assert pricing.offpeak(_bj(2026, 10, 26, 14)) is False        # 14:00 回高峰
    assert pricing.offpeak(_bj(2026, 10, 26, 17, 59)) is False
    assert pricing.offpeak(_bj(2026, 10, 26, 18)) is True         # 18:00 出高峰
    assert pricing.offpeak(_bj(2026, 10, 26, 8, 59)) is True
    assert pricing.offpeak(_bj(2026, 10, 31, 10)) is True         # 周六白天也空闲
    assert pricing.offpeak(_bj(2026, 11, 1, 23)) is True          # 周日深夜


def test_offpeak_converts_other_timezones():
    # UTC 周一 02:00 = 北京 10:00 → 高峰；UTC 周六 18:00 = 北京周日 02:00 → 空闲
    assert pricing.offpeak(datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc)) is False
    assert pricing.offpeak(datetime(2026, 10, 31, 18, 0, tzinfo=timezone.utc)) is True
