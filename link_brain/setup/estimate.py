"""`setup estimate`：按收藏库里的实际平均量 × 官方单价（link_brain/pricing.json），估每 100 篇要花多少钱。

量从哪来（只读收藏库，不联网）：
- 概要 + 打标：每篇 derived/extracted.json 记的 usage（输入 / 输出 token；接口没回传时是按字数估的）取平均；
  库里没有就按正文 + 评论字数用 llm.estimate_tokens 折 token，再加提示词。
- 识图：每篇 derived/vision.json 里真调过识图模型的图（visual.tokens = [输入, 输出]）——平均每篇几次、每次多少 token。
  标题图（大字一句话）不调模型，所以「次数」比「图片数」少。
- 视频：每篇 source.json 的 note.video.duration_sec，平均每篇几分钟（没视频的篇算 0）。
- 问答：一次 = 设置里的检索上限字数（retrieval.totalCharLimit）+ 提示词折 token，输出按 maxTokens 的一半估。
库空 / 读不到 → 用 DEFAULT_TYPICAL（开发时一个 361 篇的真实小红书收藏库的平均）并标 from_library:false。
价格：用户设置里配的模型在价格表里就按它算，否则按 pricing.json 的 recommended；DeepSeek 按高峰价算（空闲时段半价写在 how 里）。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PRICING_PATH = Path(__file__).resolve().parent.parent / "pricing.json"
MAX_SAMPLE = 3000

# 开发时一个 361 篇真实收藏库（2026-10-03）的平均，库空时用
DEFAULT_TYPICAL = {"avg_chars": 370, "avg_comment_chars": 285, "avg_images": 5.84, "avg_video_min": 0.23,
                   "summary_in": 1700, "summary_out": 518, "vision_calls": 3.68, "vision_in": 2137, "vision_out": 194}
SUMMARY_PROMPT_TOKENS = 600   # 估算时概要提示词 + 输出格式说明的 token（库里有实测 usage 时不用）
SUMMARY_OUT_DEFAULT = 500


def load_pricing() -> dict[str, Any]:
    data = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    try:
        from .. import storage
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


# --------------------------------------------------------------------------
# 库里的平均量
# --------------------------------------------------------------------------

def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def library_stats() -> dict[str, Any]:
    from .. import storage
    root = storage.archive_root()
    dirs = []
    for source_dir in (root / "xiaohongshu",):
        try:
            dirs += [d for d in source_dir.iterdir() if (d / "meta.json").is_file()]
        except OSError:
            continue
    dirs = sorted(dirs, key=lambda d: d.stat().st_mtime, reverse=True)[:MAX_SAMPLE]
    n = 0
    chars = comment_chars = images = video_min = 0.0
    s_in = s_out = s_n = 0
    v_calls = v_in = v_out = 0
    v_notes = 0
    for d in dirs:
        versions = sorted((d / "raw").glob("v*")) if (d / "raw").is_dir() else []
        source = _read(versions[-1] / "source.json") if versions else None
        if not isinstance(source, dict):
            continue
        n += 1
        note = source.get("note") or {}
        chars += len(str(note.get("title") or "")) + len(str(note.get("body") or ""))
        comment_chars += sum(len(str(c.get("text") or c.get("content") or "")) for c in source.get("comments") or []
                             if isinstance(c, dict))
        try:
            video_min += float((note.get("video") or {}).get("duration_sec") or 0) / 60
        except (TypeError, ValueError):
            pass
        ex = _read(d / "derived" / "extracted.json")
        if isinstance(ex, dict) and ex.get("status") == "ok":
            u = ex.get("usage") or {}
            tin, tout = int(u.get("input_tokens_est") or 0), int(u.get("output_tokens_est") or 0)
            if tin:
                s_in, s_out, s_n = s_in + tin, s_out + tout, s_n + 1
        vis = _read(d / "derived" / "vision.json")
        if isinstance(vis, dict):
            v_notes += 1
            ims = vis.get("images") or []
            images += len(ims)
            for im in ims:
                tok = (im.get("visual") or {}).get("tokens") if isinstance(im, dict) else None
                if isinstance(tok, list) and len(tok) == 2:
                    v_calls, v_in, v_out = v_calls + 1, v_in + int(tok[0] or 0), v_out + int(tok[1] or 0)
    if not n:
        return {"from_library": False, "sample": 0}
    out: dict[str, Any] = {"from_library": True, "sample": n, "avg_chars": round(chars / n),
                           "avg_comment_chars": round(comment_chars / n),
                           "avg_images": round(images / v_notes, 2) if v_notes else None,
                           "avg_video_min": round(video_min / n, 2)}
    if s_n:
        out.update(summary_sample=s_n, summary_in=round(s_in / s_n), summary_out=round(s_out / s_n))
    if v_calls and v_notes:
        out.update(vision_sample=v_calls, vision_calls=round(v_calls / v_notes, 2), vision_in=round(v_in / v_calls),
                   vision_out=round(v_out / v_calls))
    return out


# --------------------------------------------------------------------------
# 价格
# --------------------------------------------------------------------------

def _price(pricing: dict[str, Any], model: str) -> tuple[str, dict[str, Any]] | None:
    models = pricing.get("models") or {}
    if model in models:
        return model, models[model]
    for key, info in models.items():
        if model in (info.get("aliases") or []):
            return key, info
    return None


def _cny(pricing: dict[str, Any], info: dict[str, Any], value: float | None) -> float | None:
    if value is None:
        return None
    if info.get("currency") == "USD":
        rate = (pricing.get("usd_cny") or {}).get("rate")
        return None if not rate else value * float(rate)
    return value


def token_cost(pricing: dict, info: dict, tin: float, tout: float) -> float | None:
    pin, pout = _cny(pricing, info, info.get("input")), _cny(pricing, info, info.get("output"))
    if pin is None or pout is None:
        return None
    return (tin * pin + tout * pout) / 1_000_000


def audio_cost(pricing: dict, info: dict, minutes: float) -> float | None:
    price = _cny(pricing, info, info.get("price"))
    if price is None:
        return None
    return price * minutes * (60 if info.get("unit") == "per_second" else 1)


def _configured_models() -> dict[str, str]:
    """设置里实际配的模型名（没配就空）。"""
    try:
        from .. import ai_config, providers
        s = ai_config.load()
        out = {}
        for item, cap in (("summary", "summaryAI"), ("vision", "visionAI"), ("ask", "textAI"), ("video", "asrAI")):
            cfg = providers.resolve(cap, ai_config.with_model(s) if cap == "textAI" else s)
            if cfg and cfg.get("mode") == "http" and cfg.get("model"):
                out[item] = str(cfg["model"])
        return out
    except Exception:  # noqa: BLE001
        return {}


def _round(x: float | None, nd: int = 2) -> float | None:
    if x is None:
        return None
    return round(x, nd) if x >= 0.01 else round(x, 4)


def estimate(posts: int = 100) -> dict[str, Any]:
    from .. import ai_config, llm
    pricing = load_pricing()
    lib = library_stats()
    typ = dict(DEFAULT_TYPICAL)
    basis = {"from_library": bool(lib.get("from_library")), "sample": lib.get("sample", 0)}
    for k in ("avg_chars", "avg_comment_chars", "avg_images", "avg_video_min"):
        basis[k] = lib[k] if lib.get(k) is not None else typ[k]
    # 概要：库里有实测 usage 用它；否则按字数折 token
    if lib.get("summary_in"):
        s_in, s_out = lib["summary_in"], lib["summary_out"]
        s_how = f"库里 {lib['summary_sample']} 篇概要记下的平均 token（输入 {s_in} / 输出 {s_out}）"
    elif lib.get("from_library"):
        text_tokens = llm.estimate_tokens("中" * int(basis["avg_chars"] + basis["avg_comment_chars"]))
        s_in, s_out = text_tokens + SUMMARY_PROMPT_TOKENS, SUMMARY_OUT_DEFAULT
        s_how = (f"按平均正文 {basis['avg_chars']} 字 + 评论 {basis['avg_comment_chars']} 字折约 {text_tokens} token，"
                 f"加提示词约 {SUMMARY_PROMPT_TOKENS}、输出约 {SUMMARY_OUT_DEFAULT} token")
    else:
        s_in, s_out = typ["summary_in"], typ["summary_out"]
        s_how = f"库里还没数据，用典型值（输入 {s_in} / 输出 {s_out} token）"
    if lib.get("vision_calls") is not None:
        v_calls, v_in, v_out = lib["vision_calls"], lib["vision_in"], lib["vision_out"]
        v_how = (f"库里平均每篇 {v_calls} 次识图（{lib['vision_sample']} 次实测；标题图不调模型），"
                 f"每次输入 {v_in} / 输出 {v_out} token（图片按 token 计入输入）")
    else:
        v_calls = round(float(basis["avg_images"] or typ["avg_images"]) * typ["vision_calls"] / typ["avg_images"], 2)
        v_in, v_out = typ["vision_in"], typ["vision_out"]
        v_how = (f"平均每篇 {basis['avg_images']} 张图，约 {v_calls} 次识图（标题图不调模型），每次输入 {v_in} / 输出 {v_out} token"
                 "（典型值，按千问 qwen3.8-flash 实测）")
    basis.update(summary_tokens_in=s_in, summary_tokens_out=s_out, vision_calls=v_calls, vision_tokens_in=v_in,
                 vision_tokens_out=v_out)
    settings = ai_config.load()
    retr = settings.get("retrieval") or {}
    ctx_chars = int(retr.get("totalCharLimit") or 8000)
    max_tokens = int((settings.get("textAI") or {}).get("maxTokens") or 1200)
    a_in = llm.estimate_tokens("中" * ctx_chars) + llm.estimate_tokens(str((settings.get("prompts") or {}).get("answer") or ""))
    a_out = max_tokens // 2
    configured = _configured_models()
    rec = pricing.get("recommended") or {}
    alts = pricing.get("alternatives") or {}

    def pick(item: str) -> tuple[str, dict, bool]:
        mine = configured.get(item)
        if mine:
            hit = _price(pricing, mine)
            if hit:
                return hit[0], hit[1], True
        hit = _price(pricing, rec.get(item, "")) or ("", {})
        return hit[0], hit[1], False

    def cost_of(item: str, key: str, info: dict) -> float | None:
        if item == "summary":
            per = token_cost(pricing, info, s_in, s_out)
            return None if per is None else per * posts
        if item == "vision":
            per = token_cost(pricing, info, v_in, v_out)
            return None if per is None else per * v_calls * posts
        if item == "video":
            per = audio_cost(pricing, info, float(basis["avg_video_min"] or 0))
            return None if per is None else per * posts
        return token_cost(pricing, info, a_in, a_out)

    def offpeak_note(info: dict) -> str:
        return "；按高峰价算，北京时间工作日 9-12 点、14-18 点以外半价" if "input_offpeak" in info else ""

    names = {"summary": "概要 + 打标", "vision": "识图", "video": "视频转写（用 API 时；本地 CapsWriter 免费）",
             "ask": "问答（每问一次）"}
    hows = {"summary": s_how, "vision": v_how,
            "video": f"平均每篇视频 {basis['avg_video_min']} 分钟（没视频的篇算 0）× 每分钟单价",
            "ask": f"一次带检索摘录约 {ctx_chars} 字 + 提示词 ≈ {a_in} token 输入，输出按 maxTokens 一半 ≈ {a_out} token"}
    items = []
    for item in ("summary", "vision", "video", "ask"):
        key, info, mine = pick(item)
        yuan = cost_of(item, key, info) if info else None
        alt_rows = []
        for alt in dict.fromkeys([rec.get(item, ""), *(alts.get(item) or [])]):
            hit = _price(pricing, alt)
            if hit and hit[0] != key:
                alt_rows.append({"model": hit[0], "provider": hit[1].get("provider"),
                                 "yuan": _round(cost_of(item, hit[0], hit[1])),
                                 "openai_compatible": hit[1].get("openai_compatible")})
        how = hows[item] + offpeak_note(info)
        if item == "vision":
            how += "；别家图片折 token 的方式不同，备选价格只是按同样 token 数粗比"
        if item == "video" and info.get("openai_compatible") is False:
            how += "；这个接口不是 OpenAI 兼容的，插件现在不能直接接"
        items.append({"id": item, "name": names[item], "provider": info.get("provider"), "model": key or None,
                      "configured": mine, "yuan": _round(yuan), "per": "次" if item == "ask" else f"{posts} 篇",
                      "how": how, "price": {k: info.get(k) for k in ("currency", "unit", "input", "output", "price")
                                             if k in info}, "alternatives": alt_rows})
    sources = list(dict.fromkeys((pricing.get("sources") or {}).values()))
    usd = pricing.get("usd_cny") or {}
    return {"ok": True, "code": "", "message": f"按{'库里' if basis['from_library'] else '典型'}平均量估算，每 {posts} 篇",
            "posts": posts, "basis": basis, "items": items,
            "prices": {"as_of": pricing.get("as_of"), "sources": sources,
                       "usd_cny": {"rate": usd.get("rate"), "date": usd.get("date"), "source": usd.get("source")},
                       **({"user_override": pricing["user_override"]} if pricing.get("user_override") else {})},
            "local_free": ["ocr", "asr"]}

