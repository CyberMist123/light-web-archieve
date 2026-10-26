"""精排适配器（1015 第三批 R2）：把 RRF 候选交给千问 rerank 模型重打分。

接口（问收藏的调用方用）：
    rerank(query, docs, settings=None, trace=None) -> list[dict]
      docs = 候选 item（retrieval.fields 能读的那种）。只送前 topN 篇；返回同一批 item 的浅拷贝，
      前 topN 篇按模型分数从高到低、每条带 rerank_score，topN 之后的原序接在后面（rerank_score=None），条数 = 输入条数。
      任何失败（没 key / 超时 / HTTP 错 / 返回缺条、index 越界或重复）一律抛 RerankError，调用方回退 RRF 原序。
      trace（dict）里写 trace["rerank"] = {model, docs, seconds, status, tokens}。
    enabled(settings) -> bool    设置里 rerank.enabled（默认关）
    compact_doc(item) -> str     送给模型的短文本：标题 / 标签 / 概要 / 正文前 500 字

协议 = DashScope 原生 text-rerank：{model, input:{query, documents}, parameters:{top_n, return_documents}}
→ output.results[{index, relevance_score}]。key 不打印、不进 trace、不进异常信息。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from . import ai_config, providers

RERANK_PATH = "/api/v1/services/rerank/text-rerank/text-rerank"
DEFAULT_HOST = "https://dashscope.aliyuncs.com"
BODY_CHARS = 500
# key / 主机没单独填时依次借这几个能力的配置（千问 key 通常在归档摘要的 keyFile 里）
_BORROW_FROM = ("summaryAI", "textAI", "visionAI", "embedAI")


class RerankError(RuntimeError):
    """精排失败；调用方据此回退 RRF。"""


def _cfg(settings: dict[str, Any]) -> dict[str, Any]:
    return {**ai_config.DEFAULTS["rerank"], **(settings.get("rerank") or {})}


def enabled(settings: dict[str, Any] | None = None) -> bool:
    settings = settings if settings is not None else ai_config.load()
    return bool(_cfg(settings).get("enabled"))


def _aliyun_base(url: Any) -> str:
    """千问系接口（*.aliyuncs.com，含 MaaS 网关）的 scheme://host；别家返回空。"""
    parts = urlsplit(str(url or "").strip())
    if parts.scheme in ("http", "https") and (parts.hostname or "").endswith("aliyuncs.com"):
        return f"{parts.scheme}://{parts.netloc}"
    return ""


def endpoint(settings: dict[str, Any]) -> str:
    url = str(_cfg(settings).get("endpoint") or "").strip()
    if url:
        return url
    for cap in _BORROW_FROM:
        cfg = settings.get(cap)
        base = _aliyun_base(cfg.get("endpoint")) if isinstance(cfg, dict) else ""
        if base:
            return base + RERANK_PATH
    return DEFAULT_HOST + RERANK_PATH


def _key(settings: dict[str, Any]) -> str:
    key, _ = providers.resolve_key(_cfg(settings))
    if key:
        return key
    for cap in _BORROW_FROM:
        cfg = settings.get(cap)
        if isinstance(cfg, dict) and _aliyun_base(cfg.get("endpoint")):
            key, _ = providers.resolve_key(cfg)
            if key:
                return key
    key, _ = providers.resolve_key({"apiKeyEnv": "DASHSCOPE_API_KEY"})
    return key


def compact_doc(item: dict[str, Any]) -> str:
    from .retrieval import fields
    fs = fields(item)
    body = " ".join(str(fs.get(k) or "") for k in ("body", "ocr", "transcript", "screen", "attachments") if fs.get(k))
    lines = [f"标题：{item.get('title') or ''}"]
    tags = item.get("tags") or []
    if tags:
        lines.append("标签：" + " ".join(str(t) for t in tags[:12]))
    if item.get("summary"):
        lines.append("概要：" + str(item["summary"])[:200])
    if body.strip():
        lines.append("正文：" + " ".join(body.split())[:BODY_CHARS])
    return "\n".join(lines)


def _post(url: str, key: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001 - 读错误体失败不影响报错
            pass
        raise RerankError(f"精排接口 HTTP {exc.code}（{providers.http_code(exc.code, body)}）") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RerankError(f"连不上精排接口：{type(exc).__name__}") from exc
    except ValueError as exc:
        raise RerankError("精排接口返回的不是 JSON") from exc


def rerank(query: str, docs: list[dict[str, Any]], settings: dict[str, Any] | None = None,
           trace: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    settings = settings if settings is not None else ai_config.load()
    cfg = _cfg(settings)
    docs = list(docs or [])
    try:
        top_n = max(1, int(cfg.get("topN") or 30))
    except (TypeError, ValueError):
        top_n = 30
    head, tail = docs[:top_n], docs[top_n:]
    model = str(cfg.get("model") or "qwen3-rerank")
    info: dict[str, Any] = {"model": model, "docs": len(head), "status": "error", "seconds": 0.0}
    if trace is not None:
        trace["rerank"] = info
    if not head:
        info["status"] = "empty"
        return []
    key = _key(settings)
    if not key:
        info["error"] = "no_key"
        raise RerankError("精排没有可用的 key")
    payload = {"model": model, "input": {"query": str(query or ""), "documents": [compact_doc(it) for it in head]},
               "parameters": {"top_n": len(head), "return_documents": False}}
    try:
        timeout = float(cfg.get("timeoutSec") or 8)
    except (TypeError, ValueError):
        timeout = 8.0
    start = time.perf_counter()
    from . import usage as ledger
    url = endpoint(settings)
    try:
        data = _post(url, key, payload, timeout)
    except RerankError as exc:
        info["error"] = str(exc)
        if "HTTP" in str(exc):
            ledger.record("rerank", {"endpoint": url, "model": model}, None, ok=False)
        raise
    finally:
        info["seconds"] = round(time.perf_counter() - start, 3)
    try:
        scores = _scores(data, len(head))
    except RerankError as exc:
        info["error"] = str(exc)
        raise
    order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
    usage = data.get("usage") if isinstance(data, dict) else None
    ledger.record("rerank", {"endpoint": url, "model": model}, usage if isinstance(usage, dict) else None)
    info.update(status="ok", tokens=(usage or {}).get("total_tokens") if isinstance(usage, dict) else None)
    return [{**head[i], "rerank_score": scores[i]} for i in order] + [{**it, "rerank_score": None} for it in tail]


def _scores(data: Any, n: int) -> dict[int, float]:
    output = data.get("output") if isinstance(data, dict) else None
    results = output.get("results") if isinstance(output, dict) else None
    if not isinstance(results, list):
        raise RerankError("精排接口返回缺 output.results")
    scores: dict[int, float] = {}
    for row in results:
        try:
            idx, score = int(row["index"]), float(row["relevance_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RerankError("精排结果条目格式不对") from exc
        if not 0 <= idx < n or idx in scores:
            raise RerankError(f"精排结果 index 越界或重复：{idx}")
        scores[idx] = score
    if len(scores) != n:
        raise RerankError(f"精排结果不完整：送 {n} 篇、回 {len(scores)} 篇")
    return scores
