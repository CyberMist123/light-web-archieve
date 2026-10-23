"""每天花费上限（1018 她定：设置页 AI 页顶上一格「每天上限」，超了后台只用免费的）。

- 上限在 data.json 的 `budget.dailyYuan`（元；0 / 空 = 不限）；没写过 = 默认 DEFAULT_YUAN。
- 「今天」按北京时间分天（和阿里云 / DeepSeek 账单同一天）；花了多少 = 用量账本按 pricing.json 现价折算（usage.cost_of），
  所有功能都算进去（含问收藏）。
- **只拦后台补跑**：识图、精细识图、概要、索引 / wiki 整理（usage.tag 的 vision / refine / summary / other）。
  她自己问收藏、扩词、搜索用的向量、远程 Claude / ChatGPT 的调用一律不拦——到了上限也照常答。
- 只拦要钱的模型（`pricing.is_paid`）：显式免费的（本机命令行、Gemini 免费 key 池）照常跑；**价格表里查不到的当要钱**（宁可多拦）。
- 默认上限只在这里（DEFAULT_YUAN）；设置页显示 `status()` 给的 daily_yuan，不自己写默认值。
- 拦下 = 返回 TRANSIENT.BUDGET（api_error=True）：按接口故障归并，不按篇记失败、篇留待补，明天（或调高上限后）自然补上。
- 账本读一次缓存 60 秒，夜里一张张识图不每张都扫一遍账本。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

DEFAULT_YUAN = 3.0
GATED_FEATURES = ("vision", "refine", "summary", "other")
CODE = "TRANSIENT.BUDGET"
CACHE_S = 60.0
_cache: dict[str, Any] = {"at": 0.0, "day": "", "spent": 0.0}


def daily_cap(settings: dict[str, Any] | None = None) -> float:
    """元；0 = 不限。读不到设置按默认。"""
    if settings is None:
        try:
            from . import ai_config
            settings = ai_config.load()
        except Exception:  # noqa: BLE001
            settings = {}
    raw = (settings.get("budget") or {}).get("dailyYuan") if isinstance(settings.get("budget"), dict) else None
    if raw is None or raw == "":
        return DEFAULT_YUAN
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_YUAN


def bj_day(now: datetime | None = None) -> str:
    from .pricing import bj
    return (now or datetime.now().astimezone()).astimezone(bj()).strftime("%Y-%m-%d")


def spent_today(*, now: datetime | None = None, fresh: bool = False) -> float:
    """北京时间今天到现在花了多少元（估算）。"""
    day = bj_day(now)
    if not fresh and _cache["day"] == day and time.time() - _cache["at"] < CACHE_S:
        return float(_cache["spent"])
    from . import pricing, usage
    table = pricing.table()
    total = 0.0
    for r in usage.load(2, now=now):
        if r["_ts"].astimezone(pricing.bj()).strftime("%Y-%m-%d") != day:
            continue
        total += pricing.cost_of(r, table) or 0.0   # 未计价的这里只能按 0 加（不知道多少），拦不拦由 is_paid 决定
    _cache.update(at=time.time(), day=day, spent=total)
    return total


def is_paid(cfg: dict[str, Any] | None) -> bool:
    from . import pricing
    return pricing.is_paid(cfg)


def blocked(cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    """这次调用要不要拦：要拦返回 R（failed / TRANSIENT.BUDGET），不拦返回 None。永不抛异常（出错 = 不拦，fail-open）。"""
    try:
        from . import usage
        feature = (usage._TAG.get() or {}).get("f")
        if feature not in GATED_FEATURES or not is_paid(cfg):
            return None
        cap = daily_cap()
        if cap <= 0:
            return None
        spent = spent_today()
        if spent < cap:
            return None
        from . import providers
        return providers.result("failed", code=CODE, api_error=True,
                                error=f"今天（北京时间）已花约 ¥{spent:.2f}，到了你设的每天上限 ¥{cap:g}：后台补跑先只用免费的，明天接着补")
    except Exception:  # noqa: BLE001
        return None


def status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cap = daily_cap(settings)
    spent = spent_today(fresh=True)
    return {"daily_yuan": cap, "spent_today": round(spent, 4), "day": bj_day(), "over": bool(cap > 0 and spent >= cap)}
