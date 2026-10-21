"""用量记账（1016）：每次调模型接口记一行，设置页「模型与提供商 → 用量与余额」按功能 / 提供商汇总。

记账点只在执行器里（CONVENTIONS §4 的 R 形状出口）：`text_stream.http_call`、`visual._chat`、
`semantic._post_embeddings`、`rerank.rerank`、`asr._http`。功能由调用方用 `with usage.tag("ask"):` 标，
没标就按能力推（summaryAI → 概要、visionAI → 识图 …）。

- 账本：`vault/_archive/usage/YYYY-MM.jsonl`，append-only，一行 < 1 KB（§6.5 允许 open('a')）。
  一行 = {ts, f 功能, p 提供商, m 模型, in, out, sec 音频秒数, item, ok}；不记 key、不记内容。
- 金额不入账，汇总时按 `pricing.json` 现价折算（DeepSeek 按调用时刻分高峰 / 空闲价）；价格表里没有的模型金额记 None（界面写「—」）。
- 余额：DeepSeek 有 `GET /user/balance`（用问答 / 概要里配的 DeepSeek key）；千问（百炼）没有拿 API key 能查的余额接口，只给控制台跳转。
- 记账失败永不影响调用本身（吞异常、stderr 一句）。
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from . import storage

# 功能词表（顺序 = 设置页表格顺序）
FEATURES = {
    "vision": "识图", "refine": "精细识图", "summary": "概要", "ask": "问收藏", "expand": "扩词",
    "embed": "向量（embedding）", "asr": "语音转写", "rerank": "精排（rerank）", "other": "索引 / wiki 整理",
}
FEATURE_OF_CAP = {"summaryAI": "summary", "visionAI": "vision", "visionAI.refine": "refine", "textAI": "ask",
                  "embedAI": "embed", "asrAI": "asr", "rerank": "rerank"}
WINDOWS = {"today": 1, "7d": 7, "30d": 30}
DIR_NAME = "usage"
BALANCE_URL = "https://api.deepseek.com/user/balance"

_TAG: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("lb_usage_tag", default=None)


@contextlib.contextmanager
def tag(feature: str, *, item: str | None = None) -> Iterator[None]:
    """标这一段调用算哪个功能（和哪一篇）。嵌套时里层优先；item 没给就沿用外层的。"""
    outer = _TAG.get() or {}
    token = _TAG.set({"f": feature or outer.get("f"), "item": item or outer.get("item")})
    try:
        yield
    finally:
        _TAG.reset(token)


def provider_of(endpoint: str = "", model: str = "") -> str:
    """提供商键：deepseek / aliyun / openai / google / 其他时写接口域名；本机命令行 = cli。"""
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


def _dir() -> Path:
    return storage.archive_root() / DIR_NAME


def _now() -> datetime:
    return datetime.now().astimezone()


def record(cap: str, cfg: dict[str, Any] | None, usage: dict[str, Any] | None = None, *, ok: bool = True,
           tokens_in: int | None = None, tokens_out: int | None = None, seconds: float | None = None,
           feature: str | None = None, now: datetime | None = None) -> None:
    """执行器每调一次接口就调一次。usage 是接口回传的 usage（OpenAI 形状）；没回传就记 0 token、照样计一次调用。"""
    try:
        cfg = cfg or {}
        t = _TAG.get() or {}
        u = usage if isinstance(usage, dict) else {}
        tin = tokens_in if tokens_in is not None else int(u.get("prompt_tokens") or u.get("input_tokens")
                                                          or (u.get("total_tokens") if not u.get("completion_tokens") else 0) or 0)
        tout = tokens_out if tokens_out is not None else int(u.get("completion_tokens") or u.get("output_tokens") or 0)
        when = now or _now()
        row: dict[str, Any] = {"ts": when.isoformat(timespec="seconds"),
                               "f": feature or t.get("f") or FEATURE_OF_CAP.get(cap, "other"),
                               "p": "cli" if cfg.get("mode") == "cli" else provider_of(cfg.get("endpoint"), cfg.get("model")),
                               "m": str(cfg.get("model") or "")[:80], "in": int(tin), "out": int(tout), "ok": bool(ok)}
        if seconds:
            row["sec"] = round(float(seconds), 1)
        if t.get("item"):
            row["item"] = str(t["item"])[:64]
        d = _dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{when:%Y-%m}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - 记账永不影响调用
        print(f"[usage] 没记上（{type(exc).__name__}: {exc}）", file=sys.stderr)


def load(days: int = 31, *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or _now()
    since = now - timedelta(days=days)
    months = {f"{now:%Y-%m}", f"{since:%Y-%m}"}
    rows: list[dict[str, Any]] = []
    for name in sorted(months):
        p = _dir() / f"{name}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
                ts = datetime.fromisoformat(r["ts"])
            except (ValueError, KeyError, TypeError):
                continue
            if ts.tzinfo is None:
                ts = ts.astimezone()
            if ts >= since:
                r["_ts"] = ts
                rows.append(r)
    return rows


# --------------------------------------------------------------------------
# 价钱
# --------------------------------------------------------------------------

def _offpeak(ts: datetime) -> bool:
    """DeepSeek 空闲时段：北京时间周一至周五 9-12、14-18 之外（含周末）。法定节假日不认，按高峰算（宁多不少）。"""
    bj = ts.astimezone(_bj())
    if bj.weekday() >= 5:
        return True
    return not (9 <= bj.hour < 12 or 14 <= bj.hour < 18)


def _bj():
    from datetime import timezone
    return timezone(timedelta(hours=8))


def cost_of(row: dict[str, Any], pricing: dict[str, Any]) -> float | None:
    from .setup import estimate
    if row.get("p") == "cli":
        return 0.0
    hit = estimate._price(pricing, str(row.get("m") or ""))
    if not hit:
        return None
    info = dict(hit[1])
    if row.get("sec") and info.get("price") is not None:
        return estimate.audio_cost(pricing, info, float(row["sec"]) / 60)
    ts = row.get("_ts")
    if ts is not None and info.get("input_offpeak") is not None and _offpeak(ts):
        info["input"], info["output"] = info["input_offpeak"], info.get("output_offpeak", info.get("output"))
    if info.get("input") is None and info.get("price_per_million") is not None:
        info["input"], info["output"] = info["price_per_million"], 0
    return estimate.token_cost(pricing, info, float(row.get("in") or 0), float(row.get("out") or 0))


def _blank() -> dict[str, Any]:
    return {"calls": 0, "failed": 0, "items": set(), "in": 0, "out": 0, "sec": 0.0, "cost": 0.0, "unpriced": 0}


def _add(acc: dict[str, Any], r: dict[str, Any], cost: float | None) -> None:
    acc["calls"] += 1
    acc["failed"] += 0 if r.get("ok", True) else 1
    if r.get("item"):
        acc["items"].add(r["item"])
    acc["in"] += int(r.get("in") or 0)
    acc["out"] += int(r.get("out") or 0)
    acc["sec"] += float(r.get("sec") or 0)
    if cost is None:
        acc["unpriced"] += 1
    else:
        acc["cost"] += cost


def _done(acc: dict[str, Any]) -> dict[str, Any]:
    return {**{k: acc[k] for k in ("calls", "failed", "in", "out", "unpriced")}, "items": len(acc["items"]),
            "sec": round(acc["sec"], 1), "cost": round(acc["cost"], 4)}


def summary(*, now: datetime | None = None) -> dict[str, Any]:
    """{windows: {today|7d|30d: {total, features: {f: …}, providers: {p: …}}}, month: {p: cost}, daily: [{date, cost, calls}]}"""
    from .setup import estimate
    now = now or _now()
    pricing = estimate.load_pricing()
    rows = load(max(WINDOWS.values()) + 1, now=now)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = start_today.replace(day=1)
    out: dict[str, Any] = {"windows": {}, "month": {}, "daily": []}
    priced = [(r, cost_of(r, pricing)) for r in rows]
    for name, days in WINDOWS.items():
        since = start_today - timedelta(days=days - 1)
        total, feats, provs = _blank(), {}, {}
        for r, c in priced:
            if r["_ts"] < since:
                continue
            _add(total, r, c)
            _add(feats.setdefault(r.get("f") or "other", _blank()), r, c)
            _add(provs.setdefault(r.get("p") or "other", _blank()), r, c)
        out["windows"][name] = {"total": _done(total),
                                "features": {f: _done(a) for f, a in sorted(feats.items(), key=lambda kv: list(FEATURES).index(kv[0]) if kv[0] in FEATURES else 99)},
                                "providers": {p: _done(a) for p, a in provs.items()}}
    month: dict[str, Any] = {}
    for r, c in priced:
        if r["_ts"] >= month_start:
            _add(month.setdefault(r.get("p") or "other", _blank()), r, c)
    out["month"] = {p: _done(a) for p, a in month.items()}
    by_day: dict[str, dict[str, Any]] = {}
    for r, c in priced:
        d = by_day.setdefault(f"{r['_ts']:%Y-%m-%d}", {"cost": 0.0, "calls": 0})
        d["calls"] += 1
        d["cost"] += c or 0.0
    for i in range(29, -1, -1):
        key = f"{start_today - timedelta(days=i):%Y-%m-%d}"
        d = by_day.get(key) or {"cost": 0.0, "calls": 0}
        out["daily"].append({"date": key, "cost": round(d["cost"], 4), "calls": d["calls"]})
    out["features"] = FEATURES
    out["as_of"] = pricing.get("as_of")
    return out


def month_summary(*, now: datetime | None = None) -> dict[str, Any] | None:
    """目录页边栏「Token 费用 · 本月」（1022 Collection+ 第 4 段 A）：本月账本按 pricing.json 现价折成人民币。
    返回 {month, cost_cny, by_feature: {功能中文: 元}, calls, unpriced, as_of}；本月一行账都没有返回 None（页面显示「—」，不显示 0 误导）。"""
    from .setup import estimate
    now = now or _now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = [r for r in load(now.day + 1, now=now) if r["_ts"] >= month_start]
    if not rows:
        return None
    pricing = estimate.load_pricing()
    total, by_feat, unpriced = 0.0, {}, 0
    for r in rows:
        c = cost_of(r, pricing)
        if c is None:
            unpriced += 1
            continue
        total += c
        f = r.get("f") or "other"
        by_feat[f] = by_feat.get(f, 0.0) + c
    ordered = sorted(by_feat.items(), key=lambda kv: list(FEATURES).index(kv[0]) if kv[0] in FEATURES else 99)
    return {"month": f"{now:%Y-%m}", "cost_cny": round(total, 2), "calls": len(rows), "unpriced": unpriced,
            "by_feature": {FEATURES.get(f, f): round(v, 2) for f, v in ordered}, "as_of": pricing.get("as_of")}


# --------------------------------------------------------------------------
# 提供商：跳转 + 余额
# --------------------------------------------------------------------------

def provider_links(pricing: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """pricing.json providers 里带 console 的那几家：{键: {name, console, usage, recharge, key_url, billing, balance_api}}。"""
    if pricing is None:
        from .setup import estimate
        pricing = estimate.load_pricing()
    out = {}
    for name, info in (pricing.get("providers") or {}).items():
        key = info.get("id") or provider_of(info.get("endpoint"))
        if info.get("console"):
            out[key] = {"name": name, **{k: info.get(k) for k in ("console", "usage", "recharge", "key_url", "billing",
                                                                     "balance_api", "balance_note", "checked")}}
    return out


def provider_key_of_name(name: str) -> str:
    n = str(name or "")
    if "DeepSeek" in n or "deepseek" in n:
        return "deepseek"
    if any(k in n for k in ("千问", "通义", "百炼", "阿里", "dashscope", "aliyun")):
        return "aliyun"
    return ""


def _deepseek_key(settings: dict[str, Any] | None) -> str:
    from . import providers
    for cap in ("textAI", "summaryAI"):
        try:
            cfg = providers.resolve(cap, settings)
        except Exception:  # noqa: BLE001
            cfg = None
        if cfg and provider_of(cfg.get("endpoint"), cfg.get("model")) == "deepseek" and cfg.get("apiKey"):
            return str(cfg["apiKey"]).strip()
    for m in (settings or {}).get("models") or []:
        if isinstance(m, dict) and "deepseek" in str(m.get("endpoint") or "") and m.get("apiKey"):
            return str(m["apiKey"]).strip()
    return ""


def deepseek_balance(settings: dict[str, Any] | None = None, *, timeout: float = 8.0) -> dict[str, Any]:
    """{ok, code, message, available, balances: [{currency, total, granted, topped_up}]}；没配 DeepSeek → SKIPPED。"""
    import httpx
    from . import providers
    key = _deepseek_key(settings)
    if not key:
        return {"ok": False, "code": "SKIPPED.NOT_CONFIGURED", "message": "没配 DeepSeek 的密钥，查不了余额"}
    try:
        resp = httpx.get(BALANCE_URL, headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                         timeout=timeout)
    except httpx.HTTPError as exc:
        return {"ok": False, "code": "TRANSIENT.NETWORK", "message": f"连不上 DeepSeek（{type(exc).__name__}）"}
    if resp.status_code >= 400:
        code = providers.http_code(resp.status_code, resp.text[:500])
        return {"ok": False, "code": code, "message": providers.http_error_text(resp.status_code, code)}
    try:
        doc = resp.json()
        bal = [{"currency": b.get("currency"), "total": b.get("total_balance"), "granted": b.get("granted_balance"),
                "topped_up": b.get("topped_up_balance")} for b in doc.get("balance_infos") or []]
    except (ValueError, AttributeError, TypeError):
        return {"ok": False, "code": "TRANSIENT.HTTP_5XX", "message": "DeepSeek 余额接口回包看不懂"}
    return {"ok": True, "code": "", "message": "", "available": bool(doc.get("is_available")), "balances": bal}


def balances(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    if settings is None:
        from . import ai_config
        settings = ai_config.load()
    return {"deepseek": deepseek_balance(settings),
            "aliyun": {"ok": False, "code": "", "unsupported": True,
                       "message": "百炼没有用 API key 能查的余额接口：点「充值」在阿里云费用中心看"}}


def key_status() -> dict[str, dict[str, Any]]:
    """ai-health 里还开着的 key 失效 / 欠费，按提供商归：{deepseek: {code, caps: [...]}}。"""
    from . import ai_health
    out: dict[str, dict[str, Any]] = {}
    for cap, e in ai_health.status().items():
        code = str(e.get("code") or "")
        if not code.startswith("NEEDS_HUMAN."):
            continue
        p = provider_key_of_name(e.get("provider") or "") or "other"
        slot = out.setdefault(p, {"code": code, "caps": [], "since": e.get("since")})
        slot["caps"].append(cap)
    return out


def decorate_problem_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """问题面板：接口那一侧的 key 失效 / 欠费行带上这家的「控制台」「充值」跳转（links）。"""
    try:
        from . import ai_health
        status = ai_health.status()
        links = provider_links()
        cap_of_step = {v: k for k, v in ai_health.STEP_OF_CAP.items()}
        for r in rows:
            code = str(r.get("code") or "")
            if not (code.endswith(".AUTH_FAILED") or code.endswith(".QUOTA_EXCEEDED")):
                continue
            cap = cap_of_step.get(str(r.get("step") or ""))
            name = (status.get(cap) or {}).get("provider") if cap else ""
            key = provider_key_of_name(name or "") or provider_key_of_name(str(r.get("reason") or r.get("message") or ""))
            if key in links:
                r["links"] = {"provider": links[key]["name"], "console": links[key]["console"],
                              "recharge": links[key]["recharge"]}
    except Exception as exc:  # noqa: BLE001
        print(f"[usage] 问题行没带上跳转（{exc}）", file=sys.stderr)
    return rows


def run(args) -> int:
    from .read import dump_json, outcome
    payload: dict[str, Any] = {"summary": summary(), "links": provider_links(), "keys": key_status()}
    try:  # 1018：AI 页「每个功能用谁」+ 每天上限，和用量一次读回来（少开一次后台）
        from . import ai_routes
        payload.update(ai_routes.routes())
    except Exception as exc:  # noqa: BLE001
        from .errtext import errtext
        payload["routes_error"] = errtext(exc)
    if getattr(args, "balance", False):
        payload["balances"] = balances()
    dump_json(outcome(payload, ok=True, message="已读取用量"))
    return 0
