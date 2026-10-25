"""设置页 AI 页「每个功能用谁」（1018）：每个功能一行——主用 → 备用（从左往右顶）、每条大概多少钱、现在的状态。

只读：按生产同一套解析（providers.resolve / vision.vision_backups / llm.summary_fallbacks / 精细识图的免费 key → 强模型），
所以表上写的顺序就是夜里真走的顺序。输出里不带 key 本身，只带 key 从哪来（key_source）。

价钱：按近 30 天账本里这个功能每次调用的平均 token × 这个模型的现价（pricing.py）；账本里没有就按库里平均量（setup.estimate）。
免费只认显式标记（pricing.is_free：本机命令行、Gemini 免费 key 池）；价格表里查不到的写「—，未计价」，预算按要钱的拦。
"""
from __future__ import annotations

from typing import Any

# 功能 → (能力名, 账本里的功能词, 价钱按多少次算, 单位)
FEATURES = [
    ("ask", "问收藏", "textAI", "ask", 1, "次"),
    ("summary", "概要 · 打标签", "summaryAI", "summary", 100, "篇"),
    ("vision", "识图", "visionAI", "vision", 100, "张"),
    ("refine", "精细识图", "visionAI.refine", "refine", 100, "张"),
    ("embed", "语义搜索", "embedAI", "embed", 100, "次"),
]
PROVIDER_ID = {"DeepSeek": "deepseek", "通义千问": "aliyun", "阿里云百炼": "aliyun", "Google": "google", "Google Gemini": "google",
               "OpenAI": "openai"}


def _avg_tokens(rows: list[dict[str, Any]], feature: str) -> tuple[float, float] | None:
    got = [(r.get("in") or 0, r.get("out") or 0) for r in rows if r.get("f") == feature and r.get("ok") and (r.get("in") or 0) > 0]
    if not got:
        return None
    return sum(a for a, _ in got) / len(got), sum(b for _, b in got) / len(got)


def _fallback_tokens(feature: str) -> tuple[float, float] | None:
    try:
        from .setup import estimate
        b = estimate.library_stats()
    except Exception:  # noqa: BLE001
        return None
    if feature == "summary" and b.get("summary_in"):
        return float(b["summary_in"]), float(b.get("summary_out") or 0)
    if feature in ("vision", "refine") and b.get("vision_in"):
        return float(b["vision_in"]), float(b.get("vision_out") or 0)
    return None


def _entry(cfg: dict[str, Any], label: str, table: dict[str, Any], tokens: tuple[float, float] | None,
           per: int, unit: str) -> dict[str, Any]:
    from . import ai_health, pricing, providers, usage
    model = str(cfg.get("model") or "")
    out: dict[str, Any] = {"label": label, "model": model}
    if cfg.get("mode") == "cli":
        out.update(provider="cli", model=usage.model_name(cfg), free=True, price="免费（本机）",
                   key="本机已登录的账号")
        return out
    name = ai_health.provider_name(cfg)
    out["provider"] = PROVIDER_ID.get(name) or pricing.provider_of(cfg.get("endpoint"), model)
    out["key"] = (f"{len(providers.pool_keys(str(cfg['keyPool'])))} 把轮流用" if cfg.get("keyPool")
                  else cfg.get("keySource") or providers.key_source(cfg))
    if pricing.is_free(cfg, table):
        out.update(free=True, price="免费")
        return out
    out["free"] = False
    hit = pricing.price_of(model, table)
    if not hit:
        out.update(unpriced=True, price="—，未计价")
        return out
    cost = pricing.token_cost(table, hit[1], *tokens) if tokens else None
    if cost is None:
        out["price"] = "按用量"
    else:
        total = cost * per
        out["yuan"] = round(total, 4)
        out["price"] = f"约 ¥{total:.2f}/{'' if per == 1 else '百'}{unit}" if total >= 0.01 else f"不到 1 分/{'' if per == 1 else '百'}{unit}"
    return out


def _label(cfg: dict[str, Any]) -> str:
    from . import ai_health
    if cfg.get("label"):
        return str(cfg["label"])
    if cfg.get("mode") == "cli":
        from . import usage
        return f"本机 {usage.model_name(cfg)}"
    return f"{ai_health.provider_name(cfg)} {cfg.get('model') or ''}".strip()


def _collapse_pool(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gemini 几把免费 key 在备用链里各占一格 → 并成一格「Gemini 免费（N 把）」。"""
    out: list[dict[str, Any]] = []
    for c in chain:
        if "免费 key" in str(c.get("label") or ""):
            if out and out[-1].get("_pool"):
                out[-1]["_n"] += 1
                continue
            out.append({**c, "_pool": True, "_n": 1})
        else:
            out.append(c)
    for c in out:
        if c.pop("_pool", None):
            n = c.pop("_n")
            c["label"] = f"Gemini 免费（{n} 把 key）" if n > 1 else "Gemini 免费"
            c["key"] = f"{n} 把轮流用"
    return out


def _chains(settings: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """每个功能的配置链（含 key，只在内存里）。"""
    from . import llm, providers, vision
    chains: dict[str, list[dict[str, Any]]] = {}
    text = providers.resolve("textAI", settings)
    chains["ask"] = [text] if text else []
    summ = providers.resolve("summaryAI", settings)
    chains["summary"] = ([summ] + llm.summary_fallbacks(summ, settings)) if summ else []
    vis = providers.resolve("visionAI", settings)
    chains["vision"] = ([vis] + vision.vision_backups(vis)) if vis else []
    strong = vision.strong_config()
    router = vision.RefineRouter(strong)
    pool = [{"endpoint": vision.GEMINI_ENDPOINT, "model": vision.GEMINI_MODEL, "apiKey": k, "free": True,
             "label": f"Google {vision.GEMINI_MODEL}（免费 key {i + 1}）"} for i, k in enumerate(router.keys)]
    chains["refine"] = (pool + [strong]) if (vis and (pool or strong)) else []
    emb = providers.resolve("embedAI", settings)
    chains["embed"] = [emb] if emb else []
    return chains


def _state(health: dict[str, Any], cap: str, on: bool, budget_over: bool, chain: list) -> tuple[str, str]:
    if not on:
        return "off", "关着"
    if not chain:
        return "off", "没配好"
    e = health.get(cap)
    if not e:
        return "ok", "正常"
    code = str(e.get("code") or "")
    if code == "TRANSIENT.BUDGET" or (budget_over and code.startswith("TRANSIENT.")):
        return "budget", "今天到上限，只用免费的"
    if e.get("switched_to"):
        return "backup", f"主用的暂时不行，{e['switched_to']} 顶着"
    if code.startswith("NEEDS_HUMAN."):
        return "down", "停了：" + (e.get("detail") or "key 用不了")
    return "waiting", "暂时不通，好了自动补"


def routes(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    from . import ai_config, ai_health, budget, pricing, usage
    settings = settings if settings is not None else ai_config.load()
    table = pricing.table()
    rows = usage.load(30)
    health = ai_health.status()
    bud = budget.status(settings)
    sel = settings.get("setup", {}).get("selected") if isinstance(settings.get("setup"), dict) else None
    sel = set(sel) if isinstance(sel, list) else None
    on_of = {"ask": "ai_text", "summary": "ai_text", "embed": "ai_text", "vision": "ai_vision", "refine": "ai_vision"}
    try:
        chains = _chains(settings)
    except Exception as exc:  # noqa: BLE001
        return {"features": [], "budget": bud, "error": f"读不出各功能的配置（{exc}）"}
    out = []
    for fid, name, cap, feat, per, unit in FEATURES:
        tokens = _avg_tokens(rows, feat) or _fallback_tokens(feat)
        chain = _collapse_pool([_entry(c, _label(c), table, tokens, per, unit) for c in chains.get(fid) or [] if c])
        on = sel is None or on_of[fid] in sel
        state, text = _state(health, cap, on, bud["over"], chain)
        out.append({"id": fid, "name": name, "cap": cap, "on": on, "chain": chain, "state": state, "state_text": text})
    models = [m.get("name") for m in settings.get("models") or [] if isinstance(m, dict) and not m.get("hidden")]
    out[0]["choices"] = [m for m in models if m]
    out[0]["active"] = settings.get("activeModel") or ""
    return {"features": out, "budget": bud}
