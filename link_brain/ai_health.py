"""AI 接口故障归并（1008 Owner：一个原因一条报错，别 80 多条刷屏）。

概要 / 识图 / 精细识图 / 向量索引都要调云端接口。接口那一侧出事（key 无效、欠费、断网、限流、服务挂了）时，
以前每一篇都在问题记录里登一条「AI key 失效」——同一个原因、几百条。现在：

- 这类故障（`providers.result` 里 `api_error=True` 的那些码）**不按篇登记**，按能力归并成一条步骤级问题：
  step=`ai.<能力>`（ai.summary / ai.vision / ai.refine / ai.embed），item_id 为空；
- 那一条的原因写清：**哪个接口、哪个模型、key 从哪来（尾号）、HTTP 多少、是 key 无效还是欠费还是断网、怎么办、
  影响了几篇、补齐这些篇大约要多少 token / 多少钱**；
- 受影响的篇只记在 `_archive/ai-health.json`（每个能力一份：码、原因、首末时间、篇 id），篇本身留在待补状态，
  接口好了夜跑 / 「现在修」自然补回来；
- 同一能力再成功一次 → 这条问题解决、清单清空。

接口故障 ≠ 这篇的问题：enrich 不给这篇记失败次数（不然 3 次就「连着没补成」退避几天）。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage

FILE_NAME = "ai-health.json"
# 能力 → 归并后的步骤名（问题记录里 step=ai.<名>）
STEP_OF_CAP = {"summaryAI": "ai.summary", "visionAI": "ai.vision", "visionAI.refine": "ai.refine", "embedAI": "ai.embed",
               "textAI": "ai.ask"}
STEP_LABELS = {"ai.summary": "AI 概要 / 打标接口", "ai.vision": "识图接口", "ai.refine": "精细识图接口",
               "ai.embed": "向量索引接口", "ai.ask": "问答接口"}
# 每个能力每篇大约要花多少 → setup.estimate 里对应的条目
ESTIMATE_ITEM = {"summaryAI": "summary", "visionAI": "vision", "visionAI.refine": "vision"}
# 接口那一侧的故障码：归并、不按篇记
API_CODES = ("NEEDS_HUMAN.AUTH_FAILED", "NEEDS_HUMAN.QUOTA_EXCEEDED", "TRANSIENT.NETWORK", "TRANSIENT.HTTP_429",
             "TRANSIENT.HTTP_5XX", "TRANSIENT.SERVICE_BUSY", "TRANSIENT.SECRET_TIMEOUT", "TRANSIENT.BUDGET")
MAX_ITEMS_KEPT = 2000

# 码 → （是什么原因，怎么办）
CAUSE = {
    "NEEDS_HUMAN.AUTH_FAILED": ("接口拒绝了这把 key：key 填错、已过期或被停用", "到设置里换一把 key 再点「现在修」"),
    "NEEDS_HUMAN.QUOTA_EXCEEDED": ("账户欠费或额度用完", "去这家平台充值，或到设置里换一把 key，再点「现在修」"),
    "TRANSIENT.NETWORK": ("连不上接口：断网、代理没开或接口地址填错", "检查网络 / 代理和接口地址；好了会自动补"),
    "TRANSIENT.HTTP_429": ("接口限流（请求太密）", "不用处理，下次夜跑自动补"),
    "TRANSIENT.HTTP_5XX": ("接口那一侧暂时出错", "不用处理，下次夜跑自动补"),
    "TRANSIENT.SERVICE_BUSY": ("接口那一侧正忙或回包坏了", "不用处理，下次夜跑自动补"),
    "TRANSIENT.SECRET_TIMEOUT": ("从密码库取 key 超时", "看一眼密码库有没有锁住；好了会自动补"),
    "TRANSIENT.BUDGET": ("今天花到了你设的每天上限", "不用处理，明天接着补；想今天补完就到设置 AI 页调高上限"),
}


def is_api_failure(result: dict[str, Any] | None) -> bool:
    """这次调用失败是接口那一侧的事（归并处理），还是这篇自己的事（按篇处理）。"""
    if not result or result.get("status") == "ok":
        return False
    return str(result.get("code") or "") in API_CODES or bool(result.get("api_error"))


def _path() -> Path:
    return storage.archive_root() / FILE_NAME


def _load() -> dict[str, Any]:
    try:
        data = storage.read_json(_path())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict[str, Any]) -> None:
    try:
        storage.write_json(_path(), data)
    except OSError as exc:
        print(f"[ai_health] ai-health.json 没写上（{exc}）", file=sys.stderr)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def provider_name(cfg: dict[str, Any] | None) -> str:
    """接口是哪家的：先按模型名查价格表，查不到按接口域名猜，再不行就写域名。"""
    cfg = cfg or {}
    model = str(cfg.get("model") or "")
    try:
        from .setup import estimate
        hit = estimate._price(estimate.load_pricing(), model)
        if hit and hit[1].get("provider"):
            return str(hit[1]["provider"])
    except Exception:  # noqa: BLE001
        pass
    endpoint = str(cfg.get("endpoint") or "")
    for needle, name in (("deepseek", "DeepSeek"), ("aliyuncs", "阿里云百炼"), ("dashscope", "通义千问"),
                         ("googleapis", "Google"), ("openai.com", "OpenAI"), ("moonshot", "Moonshot"),
                         ("siliconflow", "硅基流动"), ("volces", "火山引擎"), ("bigmodel", "智谱")):
        if needle in endpoint:
            return name
    host = endpoint.split("//", 1)[-1].split("/", 1)[0]
    return host or "接口"


_PER_POST: dict[str, tuple[float, float | None]] = {}  # item → (每篇 token, 每篇元)；扫库一次就够，别每登一篇扫一遍


def _per_post(item: str) -> tuple[float, float | None]:
    if item in _PER_POST:
        return _PER_POST[item]
    from .setup import estimate
    est = estimate.estimate(posts=100)
    basis = est.get("basis") or {}
    if item == "summary":
        tokens = float(basis.get("summary_tokens_in") or 0) + float(basis.get("summary_tokens_out") or 0)
    else:
        tokens = float(basis.get("vision_calls") or 0) * (float(basis.get("vision_tokens_in") or 0)
                                                           + float(basis.get("vision_tokens_out") or 0))
    row = next((x for x in est.get("items") or [] if x.get("id") == item), None)
    yuan = row.get("yuan") if row else None
    _PER_POST[item] = (tokens, None if yuan is None else float(yuan) / 100)
    return _PER_POST[item]


def catchup_estimate(cap: str, n: int) -> str:
    """补齐 n 篇大约要多少 token、多少钱（按库里实际平均量 × 官方单价，setup.estimate 同一套算法）。算不出就空串。"""
    item = ESTIMATE_ITEM.get(cap)
    if not item or n <= 0:
        return ""
    try:
        per_tokens, per_yuan = _per_post(item)
        tokens = per_tokens * n
        tok = f"约 {tokens / 10000:.1f} 万 token" if tokens >= 10000 else f"约 {int(tokens)} token"
        if per_yuan is None:
            return tok
        yuan = per_yuan * n
        return f"{tok} ≈ ¥{yuan:.2f}" if yuan >= 0.01 else f"{tok} ≈ 不到 1 分钱"
    except Exception:  # noqa: BLE001
        return ""


def _detail(result: dict[str, Any]) -> str:
    """接口回的那句错误（去掉 key 之类），给人看原因用；没有就空。"""
    from . import problems
    text = str(result.get("error") or "")
    status = result.get("http_status")
    if status and f"HTTP {status}" not in text:
        text = f"HTTP {status}：{text}" if text else f"HTTP {status}"
    return problems.redact(text)[:120]


def reason_text(cap: str, entry: dict[str, Any]) -> str:
    """问题记录里那一句（≤ problems.REASON_MAX）。"""
    from . import providers
    label = providers.LABEL.get(cap, cap)
    cause, fix = CAUSE.get(entry.get("code") or "", ("接口调用失败", "看原因处理"))
    where = f"{label}（{entry.get('provider') or '接口'} {entry.get('model') or ''}".rstrip()
    if entry.get("key_hint"):
        where += f"，{entry['key_hint']}"
    where += "）"
    n = len(entry.get("items") or [])
    tail = f"影响 {n} 篇" if n else ""
    if entry.get("estimate"):
        tail += f"，补齐{entry['estimate']}"
    switched = ""
    if entry.get("switched_to"):
        # 1016：主接口坏着、备用补上了——照实写换成了谁、补了几次；主接口这条仍要人处理
        switched = f"已换用 {entry['switched_to']}（补上 {int(entry.get('switched_count') or 0)} 次）"
    bits = [where, entry.get("detail") or "", switched, f"原因：{cause}", f"处理：{fix}", tail]
    return "；".join(b for b in bits if b)


def record(cap: str, result: dict[str, Any], *, item_id: str | None = None, cfg: dict[str, Any] | None = None,
           switched_to: str = "") -> None:
    """接口故障归并登记：更新 ai-health.json，并把 step=ai.<能力> 那一条问题（同码）覆盖成最新一句。永不抛异常。

    switched_to：主接口这次失败、但已换用备用补上了（1016）——不算「影响的篇」，原因里写「已换用 X」。"""
    try:
        from . import problems, providers
        step = STEP_OF_CAP.get(cap)
        code = str(result.get("code") or "TRANSIENT.SERVICE_BUSY")
        if not step:
            return
        data = _load()
        entry = data.get(cap) or {}
        if entry.get("code") != code:
            # 原因变了（上次断网、这次欠费）：旧那条解决掉，重开一条
            if entry.get("code"):
                problems.resolve(step, None, entry["code"])
            entry = {"code": code, "since": _now(), "items": []}
        items = list(entry.get("items") or [])
        if switched_to:
            entry["switched_to"] = switched_to
            entry["switched_count"] = int(entry.get("switched_count") or 0) + 1
            if item_id in items:
                items.remove(item_id)
            item_id = None
        if item_id and item_id not in items:
            items.append(item_id)
        entry.update({
            "items": items[-MAX_ITEMS_KEPT:], "count": int(entry.get("count") or 0) + 1, "last_at": _now(),
            "http_status": result.get("http_status"), "detail": _detail(result),
            "provider": provider_name(cfg), "model": str((cfg or {}).get("model") or ""),
            "key_hint": providers.key_hint(cfg) if cfg else "",
        })
        entry["estimate"] = catchup_estimate(cap, len(items))
        data[cap] = entry
        _save(data)
        if (switched_to and not items and not code.startswith("NEEDS_HUMAN.")) or result.get("daily_limit"):
            # 1021 她：免费 key 当天薅完是正常的——不管备用补没补上、有没有篇在等，都不进问题面板 / 同步记录；
            # 篇留在待补，明天额度回来或下次备用补上自然补齐
            # 1019 她：Gemini 免费 key 限流 / 今天额度用完、备用当场补上 = 自然轮换，不是故障——
            # 只记进 ai-health.json（诊断里看得到），面板不挂；以前挂着的同码那条收掉
            problems.resolve(step, None, code)
            return
        problems.report(step, code, reason_text(cap, entry))
    except Exception as exc:  # noqa: BLE001
        print(f"[ai_health] 归并登记失败（{type(exc).__name__}: {exc}）", file=sys.stderr)


def clear(cap: str) -> None:
    """这个能力的接口又成功了：解决归并的那条问题、清掉受影响清单。永不抛异常。"""
    try:
        from . import problems
        step = STEP_OF_CAP.get(cap)
        data = _load()
        entry = data.pop(cap, None)
        if entry is not None:
            _save(data)
        if step and (entry is not None or problems.is_open_step(step)):
            problems.resolve(step, None)
    except Exception as exc:  # noqa: BLE001
        print(f"[ai_health] 清除失败（{type(exc).__name__}: {exc}）", file=sys.stderr)


def affected(cap: str) -> list[str]:
    return list((_load().get(cap) or {}).get("items") or [])


def status() -> dict[str, Any]:
    """{cap: {code, since, last_at, count, items: n, provider, model, key_hint, estimate}}——给设置页 / 诊断看。"""
    out = {}
    for cap, e in _load().items():
        out[cap] = {**{k: e.get(k) for k in ("code", "since", "last_at", "count", "provider", "model", "key_hint",
                                                 "estimate", "detail", "http_status", "switched_to")}, "items": len(e.get("items") or [])}
    return out


# 旧记录迁移：以前按篇登记的 AUTH_FAILED / QUOTA_EXCEEDED（enrich.summary / vision.layer1 / embed）→ 折成一条
_LEGACY_STEPS = {"enrich.summary": "summaryAI", "vision.layer1": "visionAI", "vision.refine": "visionAI.refine",
                 "embed": "embedAI"}


def migrate_legacy_rows() -> int:
    """把问题记录里还挂着的按篇 key 失效 / 欠费 / 断网条目收成每个能力一条。返回收掉几条。幂等、永不抛异常。"""
    try:
        from . import problems, providers
        rows = [r for r in problems.load(limit=5000) if r.get("step") in _LEGACY_STEPS
                and str(r.get("code") or "") in API_CODES]
        if not rows:
            return 0
        by_cap: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_cap.setdefault(_LEGACY_STEPS[r["step"]], []).append(r)
        n = 0
        for cap, group in by_cap.items():
            latest = max(group, key=lambda r: str(r.get("ts") or ""))
            cfg = None
            try:
                cfg = providers.resolve(cap)
            except Exception:  # noqa: BLE001
                pass
            for r in group:
                record(cap, {"code": latest.get("code"), "error": r.get("reason") or latest.get("reason")},
                       item_id=r.get("item_id"), cfg=cfg)
                problems.resolve(r["step"], r.get("item_id"), r.get("code"))
                n += 1
        return n
    except Exception as exc:  # noqa: BLE001
        print(f"[ai_health] 旧记录迁移失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 0
