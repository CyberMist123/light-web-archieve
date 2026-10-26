"""粘一把 key，认出是哪家（1018 她：设置页「AI 服务」只要粘贴，别让人选服务商、填地址）。

做法：按前缀先猜（AIza… = Google），其余拿这把 key 去各家的 `/models` 列表接口问一下（只读、不花钱），
哪家认它就是哪家。认出后按价格表（pricing.table，含用户覆盖）的推荐 / 备选模型，给出这家能顶的几项功能该填的接口和模型
（fills：{能力键: {endpoint, model}}）——**只给建议，不写设置**：插件拿到后只往空着的那几格里填（规矩同
home-ui「填上它的地址和模型」：已经填好的地址、密钥引用一个不动）。

key 只从标准输入读，不进命令行参数、不落盘、不打印、不进日志。

CLI：
  echo <key> | python -m link_brain keys detect
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

PROVIDERS = {
    # id: (pricing.json 里的名字, 列模型的接口)
    "deepseek": ("DeepSeek", "https://api.deepseek.com/models"),
    "aliyun": ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1/models"),
    "openai": ("OpenAI", "https://api.openai.com/v1/models"),
    "google": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/models"),
}
LABEL = {"deepseek": "DeepSeek", "aliyun": "通义千问", "openai": "OpenAI", "google": "Gemini"}
# 功能 → 设置里的能力键（概要默认跟问收藏走，所以只在问收藏填不了时才单独填概要）
FEATURE_CAP = {"ask": "textAI", "summary": "summaryAI", "vision": "visionAI"}
EMBED = {"aliyun": {"endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings", "model": "qwen3.7-text-embedding-flash"}}


def _pricing() -> dict[str, Any]:
    from . import pricing
    return pricing.table()   # 含用户覆盖（~/.link-brain/pricing.json）


def guess(key: str) -> list[str]:
    """按前缀排个先后（不下结论）：AIza 只可能是 Google；sk-ant 是 Anthropic（不是 OpenAI 兼容接口，不支持）。"""
    k = key.strip()
    if k.startswith("AIza"):
        return ["google"]
    if k.startswith("sk-ant"):
        return []
    return ["deepseek", "aliyun", "openai"]


def _accepts(provider: str, key: str, timeout: float = 8.0) -> bool:
    import httpx
    url = PROVIDERS[provider][1]
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    except httpx.HTTPError:
        return False
    return r.status_code == 200


def fills_for(provider: str) -> dict[str, dict[str, str]]:
    """这家能顶的功能：推荐模型是这家的就用推荐，否则用备选里第一个这家的。"""
    p = _pricing()
    name = PROVIDERS[provider][0]
    prov = (p.get("providers") or {}).get(name) or {}
    models = p.get("models") or {}
    out: dict[str, dict[str, str]] = {}
    for feature, cap in FEATURE_CAP.items():
        picks = [p.get("recommended", {}).get(feature), *(p.get("alternatives", {}).get(feature) or [])]
        hit = next((m for m in picks if m and (models.get(m) or {}).get("provider") == name), None)
        if hit and prov.get("endpoint"):
            out[cap] = {"endpoint": prov["endpoint"], "model": (models[hit].get("api_model") or hit)}
    if "textAI" in out:
        out.pop("summaryAI", None)
    if provider in EMBED:
        out["embedAI"] = dict(EMBED[provider])
    return out


SLOT_CAPS = ("textAI", "summaryAI", "visionAI", "embedAI", "asrAI")


def slots_for(provider: str, settings: dict[str, Any] | None = None) -> list[str]:
    """1027 设置页「粘一把 key」换掉用不了的那家：设置里哪几格现在指着这家的接口（pricing.provider_of 一处认哪家，前端不猜）。
    返回格子路径：「summaryAI」「summaryAI.fallback」「visionAI.refine」…；概要「跟随问答」那一格不算（它用的就是 textAI）。"""
    from . import pricing
    if settings is None:
        from . import ai_config
        try:
            settings = ai_config.load()
        except Exception:  # noqa: BLE001 - 设置读不动就当没有，前端如实说「没找到哪一项在用它」
            settings = {}
    out: list[str] = []
    for cap in SLOT_CAPS:
        cfg = settings.get(cap)
        if not isinstance(cfg, dict):
            continue
        if cap == "summaryAI" and cfg.get("mode") in (None, "", "inherit"):
            pass
        elif cfg.get("endpoint") and pricing.provider_of(cfg.get("endpoint"), cfg.get("model") or "") == provider:
            out.append(cap)
        for sub in ("fallback", "refine"):
            sc = cfg.get(sub)
            if isinstance(sc, dict) and sc.get("endpoint") and pricing.provider_of(sc.get("endpoint"), sc.get("model") or "") == provider:
                out.append(f"{cap}.{sub}")
    return out


def detect(key: str) -> dict[str, Any]:
    key = (key or "").strip()
    if not key or any(ch.isspace() for ch in key):
        return {"ok": False, "code": "SKIPPED.BAD_INPUT", "message": "粘贴的不像一把 key（是空的，或中间有空格）"}
    order = guess(key)
    if not order:
        return {"ok": False, "code": "SKIPPED.UNSUPPORTED", "message": "这像是 Anthropic 的 key：它不是通用接口，这里用不了"}
    with ThreadPoolExecutor(max_workers=len(order)) as pool:
        verdict = dict(zip(order, pool.map(lambda pid: _accepts(pid, key), order)))
    hit = next((pid for pid in order if verdict[pid]), None)
    if not hit:
        return {"ok": False, "code": "NEEDS_HUMAN.AUTH_FAILED",
                "message": "试了 " + "、".join(LABEL[p] for p in order) + "，都不认这把 key：看看是不是复制少了几个字，或者已经作废"}
    p = _pricing()
    prov = (p.get("providers") or {}).get(PROVIDERS[hit][0]) or {}
    return {"ok": True, "code": "", "provider": hit, "name": LABEL[hit], "fills": fills_for(hit), "slots": slots_for(hit),
            "key_url": prov.get("key_url", ""), "message": f"认出是 {LABEL[hit]}"}


def add_parser(sub) -> None:
    p = sub.add_parser("keys", help="粘一把 key 认出是哪家（key 从标准输入读）")
    ks = p.add_subparsers(dest="keys_command", metavar="<detect>")
    ks.add_parser("detect", help="从标准输入读一把 key，问各家 /models 认出是哪家，给出该填的接口和模型")


def run(args) -> int:
    from .read import dump_json, outcome
    key = sys.stdin.readline() if not sys.stdin.isatty() else ""
    out = detect(key)
    dump_json(outcome(out, ok=bool(out.get("ok")), message=out.get("message") or "", code=out.get("code") or ""))
    return 0 if out.get("ok") else 1
