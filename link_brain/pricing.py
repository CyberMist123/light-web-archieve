"""价格的唯一来源（ARCH-AUDIT 第 2 批）：算钱、判免费、猜提供商只调这里。

- 价格表：包内 `pricing.json` + 用户覆盖 `~/.link-brain/pricing.json`（按键深合并）→ `table()`。
- 「查不到价」只有一种结果：`None` = 未计价（界面写「—，未计价」）；预算把它当**要钱**的（宁可多拦）。
- 「免费」只认显式标记（`is_free`）：本机命令行（mode=cli）、Gemini 免费 key 池（keyPool=gemini，或执行器在配置上标
  `free: true`）、价格表里写了 `"free": true` 的模型。不在价格表里 ≠ 免费。
- 账本一行（usage.record 写）带 `free: true` 的按 0 元算；`p == "cli"` 同样 0 元。
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PRICING_PATH = Path(__file__).resolve().with_name("pricing.json")
FREE_POOLS = ("gemini",)   # 这些 key 池是免费额度（她的 Gemini 免费 key）
PRICE_KEYS = ("input", "output", "price", "price_per_million")


def table() -> dict[str, Any]:
    data = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    try:
        from . import storage
        user = storage.link_brain_home() / "pricing.json"
        if user.is_file():
            over = json.loads(user.read_text(encoding="utf-8-sig"))
            if isinstance(over, dict):
                data = _merge(data, over)
                data["user_override"] = str(user)
    except (OSError, ValueError):
        pass
    return data


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def price_of(model: str, pricing: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]] | None:
    """(价格表里的键, 这一行)；按名字或 aliases 查，查不到 None。"""
    models = (pricing if pricing is not None else table()).get("models") or {}
    model = str(model or "")
    if not model:
        return None
    if model in models:
        return model, models[model]
    for key, info in models.items():
        if model in (info.get("aliases") or []):
            return key, info
    return None


def cny(pricing: dict[str, Any], info: dict[str, Any], value: float | None) -> float | None:
    if value is None:
        return None
    if info.get("currency") == "USD":
        rate = (pricing.get("usd_cny") or {}).get("rate")
        return None if not rate else value * float(rate)
    return value


def token_cost(pricing: dict, info: dict, tin: float, tout: float) -> float | None:
    pin, pout = cny(pricing, info, info.get("input")), cny(pricing, info, info.get("output"))
    if pin is None or pout is None:
        return None
    return (tin * pin + tout * pout) / 1_000_000


def audio_cost(pricing: dict, info: dict, minutes: float) -> float | None:
    price = cny(pricing, info, info.get("price"))
    if price is None:
        return None
    return price * minutes * (60 if info.get("unit") == "per_second" else 1)


# --------------------------------------------------------------------------
# 免费 / 要钱
# --------------------------------------------------------------------------

def is_free(cfg: dict[str, Any] | None, pricing: dict[str, Any] | None = None) -> bool:
    """只认显式标记：本机命令行、免费 key 池、执行器标的 free、价格表里 free: true。"""
    cfg = cfg or {}
    if cfg.get("mode") == "cli" or cfg.get("free") is True or str(cfg.get("keyPool") or "") in FREE_POOLS:
        return True
    hit = price_of(str(cfg.get("model") or ""), pricing)
    return bool(hit and hit[1].get("free") is True)


def is_paid(cfg: dict[str, Any] | None, pricing: dict[str, Any] | None = None) -> bool:
    """要不要钱（预算拦不拦）：显式免费的不要；查不到价的当要钱；价格全是 0 的不要。"""
    if is_free(cfg, pricing):
        return False
    hit = price_of(str((cfg or {}).get("model") or ""), pricing)
    if not hit:
        return True
    info = hit[1]
    if not is_priced(info):
        return True   # 表里有这个模型但价格写的 null（查不到）：同样按要钱
    return any(float(info.get(k) or 0) > 0 for k in PRICE_KEYS)


# --------------------------------------------------------------------------
# 一行账本 / 一次调用值多少钱
# --------------------------------------------------------------------------

def bj():
    return timezone(timedelta(hours=8))


def offpeak(ts: datetime) -> bool:
    """DeepSeek 空闲时段：北京时间周一至周五 9-12、14-18 之外（含周末）。法定节假日不认，按高峰算（宁多不少）。"""
    t = ts.astimezone(bj())
    if t.weekday() >= 5:
        return True
    return not (9 <= t.hour < 12 or 14 <= t.hour < 18)


def is_priced(info: dict[str, Any] | None) -> bool:
    """价格表这一行有没有能算钱的单价（token 两价齐、或音频单价、或向量单价）；写 null 的 = 查不到 = 未计价。"""
    info = info or {}
    return (info.get("input") is not None and info.get("output") is not None) \
        or info.get("price") is not None or info.get("price_per_million") is not None \
        or info.get("free") is True


def bill_of(row: dict[str, Any], pricing: dict[str, Any] | None = None) -> tuple[float | None, str]:
    """账本一行 → (元, 状态)。状态三种，设置页「花了多少」照它写：
    free = 免费 / 未计费（本机命令行、Gemini 免费 key 池、价格表写了 free；她 1023 拍板：不算进 ¥）；
    paid = 按价格表算出来的钱；unpriced = 价格表里查不到（元 = None，不编、不当 0）。"""
    pricing = pricing if pricing is not None else table()
    if row.get("p") == "cli" or row.get("free") is True:
        return 0.0, "free"
    hit = price_of(str(row.get("m") or ""), pricing)
    if hit and hit[1].get("free") is True:
        return 0.0, "free"
    cost = cost_of(row, pricing)
    return cost, ("unpriced" if cost is None else "paid")


def cost_of(row: dict[str, Any], pricing: dict[str, Any] | None = None) -> float | None:
    """账本一行（{p, m, in, out, sec?, free?, _ts?}）→ 元；未计价 = None。"""
    if row.get("p") == "cli" or row.get("free") is True:
        return 0.0
    pricing = pricing if pricing is not None else table()
    hit = price_of(str(row.get("m") or ""), pricing)
    if not hit:
        return None
    info = dict(hit[1])
    if info.get("free") is True:
        return 0.0
    if row.get("sec") and info.get("price") is not None:
        return audio_cost(pricing, info, float(row["sec"]) / 60)
    ts = row.get("_ts")
    if ts is not None and info.get("input_offpeak") is not None and offpeak(ts):
        info["input"], info["output"] = info["input_offpeak"], info.get("output_offpeak", info.get("output"))
    if info.get("input") is None and info.get("price_per_million") is not None:
        info["input"], info["output"] = info["price_per_million"], 0
    return token_cost(pricing, info, float(row.get("in") or 0), float(row.get("out") or 0))


def call_cost(cfg: dict[str, Any] | None, tin: float, tout: float, *, pricing: dict[str, Any] | None = None,
              now: datetime | None = None) -> float | None:
    """执行器刚调完一次：按和账本同一套规则算这一次多少元（夜跑「花费」、概要 extracted.json 用）。"""
    cfg = cfg or {}
    row = {"p": "cli" if cfg.get("mode") == "cli" else provider_of(cfg.get("endpoint"), cfg.get("model")),
           "m": str(cfg.get("model") or ""), "in": tin, "out": tout,
           "_ts": now or datetime.now().astimezone()}
    if is_free(cfg, pricing):
        row["free"] = True
    return cost_of(row, pricing)


def provider_of(endpoint: str = "", model: str = "") -> str:
    """提供商键：deepseek / aliyun / openai / google / 其他时写接口域名；本机命令行由调用方记 cli。"""
    e, m = str(endpoint or "").lower(), str(model or "").lower()
    if "deepseek" in e or (not e and m.startswith("deepseek")):
        return "deepseek"
    if "aliyuncs" in e or "dashscope" in e or (not e and m.startswith("qwen")):
        return "aliyun"
    if "openai.com" in e:
        return "openai"
    if "googleapis" in e:
        return "google"
    if not e:
        return "other"
    host = e.split("://", 1)[-1].split("/", 1)[0]
    return host or "other"
