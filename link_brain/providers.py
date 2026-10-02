"""外部能力的 provider 接口（CONVENTIONS §4）：配置 → 执行器的唯一入口。

- `resolve(cap)`：从插件 data.json（`ai_config.load`，含旧配置的内存换算）取这一项能力的配置，叠上默认值，
  解出 key，带上超时；没配置 / 关了 → None。调用方拿到 None 就记 `SKIPPED.*`、返回 `{"status": "skipped"}`。
- `why_not(cap)`：None 的原因，一句能直接给人看的话（进 problems 记录和测试按钮）。
- `http_code(status, body)`：HTTP 状态 → 故障码（§4.6）。
- `result(...)`：执行器统一返回形状 R。

能力键（§4.1）：textAI（问答）· summaryAI（归档概要/打标，默认继承 textAI）· visionAI（识图第一层）·
visionAI.refine（第二层）· ocr · asrAI · docConvert · embedAI（向量索引，没有设置页入口）。

key 来源顺序（§4.3）：`cfg.apiKey` → `cfg.keyFile/keyField`（CSV 两列：名称,值）→ `os.environ[cfg.apiKeyEnv]` → 没有。
**这里不出现任何默认目录、默认用户路径、默认 key 文件名**。key 只在内存里过一手，不打印、不进日志。
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Any

CAPS = ("textAI", "summaryAI", "visionAI", "visionAI.refine", "ocr", "asrAI", "docConvert", "embedAI")
MODES = {
    "textAI": ("http", "cli", "off"),
    "summaryAI": ("inherit", "http", "cli", "off"),
    "visionAI": ("http", "off"),
    "visionAI.refine": ("http", "off"),
    "ocr": ("local", "off"),
    "asrAI": ("capswriter", "http", "off"),
    "docConvert": ("local", "off"),
    "embedAI": ("http", "off"),
}
LABEL = {"textAI": "文本 AI", "summaryAI": "归档摘要模型", "visionAI": "识图接口", "visionAI.refine": "精细识别模型",
         "ocr": "文字识别（OCR）", "asrAI": "语音识别", "docConvert": "附件转 Markdown", "embedAI": "向量索引"}
# 只给别的键「借」接口用：继承时这些字段跟着接口走，不单独覆盖


def _settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    if settings is not None:
        return settings
    from . import ai_config
    return ai_config.load()


def _defaults(cap: str) -> dict[str, Any]:
    from . import ai_config
    base = cap.split(".", 1)[0]
    if cap == "visionAI.refine":
        return dict(ai_config.DEFAULTS.get("visionAI") or {})
    return dict(ai_config.DEFAULTS.get(base) or {})


def raw_config(cap: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """这一项能力在设置里的原样配置（已叠默认值，未解 key）。summaryAI / visionAI.refine 的继承在这里展开。"""
    s = _settings(settings)
    if cap == "summaryAI":
        own = {**_defaults("summaryAI"), **(s.get("summaryAI") or {})}
        if (own.get("mode") or "inherit") == "inherit":
            text = {**_defaults("textAI"), **(s.get("textAI") or {})}
            cfg = {k: v for k, v in text.items()}
            for key in ("model", "maxTokens", "timeoutSec"):
                if own.get(key) not in (None, ""):
                    cfg[key] = own[key]
            cfg["inherited"] = True
            return cfg
        return own
    if cap == "visionAI.refine":
        vis = {**_defaults("visionAI"), **(s.get("visionAI") or {})}
        cfg = dict(vis)
        cfg["model"] = vis.get("refineModel") or vis.get("model") or ""
        cfg["timeoutSec"] = vis.get("refineTimeoutSec") or vis.get("timeoutSec")
        return cfg
    cfg = {**_defaults(cap), **(s.get(cap) or {})}
    if cap == "asrAI" and not cfg.get("capsWriterDir"):
        # 端口留空时去读 CapsWriter 自己的 config_server.py：目录就是设置里「CapsWriter 目录」那一项
        cfg["capsWriterDir"] = (s.get("voice") or {}).get("capsWriterDir") or ""
    return cfg


# --------------------------------------------------------------------------
# key
# --------------------------------------------------------------------------

def read_key_file(path: str, field: str = "apiKey") -> tuple[dict[str, str] | None, str]:
    """读 CSV 形式的密钥文件（每行「名称,值」，UTF-8 带不带 BOM 或 GBK）。返回 (全部字段 或 None, 出错原因)。"""
    try:
        raw = Path(path).expanduser().read_bytes()
    except OSError:
        return None, "读不到设置里指定的密钥文件"
    try:
        text = raw.decode("utf-8-sig") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError:
            return None, "密钥文件的编码认不出来（要 UTF-8 或 GBK）"
    return {r[0].strip(): r[1].strip() for r in csv.reader(io.StringIO(text)) if len(r) >= 2}, ""


def resolve_key(cfg: dict[str, Any]) -> tuple[str, str]:
    """(key, 出错原因)。顺序：apiKey → keyFile/keyField → 环境变量 apiKeyEnv。"""
    key = str(cfg.get("apiKey") or "").strip()
    if key:
        return key, ""
    err = ""
    if cfg.get("keyFile"):
        data, err = read_key_file(cfg["keyFile"])
        if data is not None:
            key = data.get(cfg.get("keyField") or "apiKey", "")
            if not key:
                err = f"密钥文件里没有「{cfg.get('keyField') or 'apiKey'}」这一项"
    if not key and cfg.get("apiKeyEnv"):
        key = os.environ.get(str(cfg["apiKeyEnv"]), "").strip()
        if key:
            err = ""
    return key, err


# --------------------------------------------------------------------------
# resolve
# --------------------------------------------------------------------------

def _timeout(cfg: dict[str, Any], cap: str) -> float:
    for value in (cfg.get("timeoutSec"), _defaults(cap).get("timeoutSec")):
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return 120.0


def _check(cap: str, cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    label = LABEL.get(cap, cap)
    mode = str(cfg.get("mode") or "").strip()
    if cap == "summaryAI" and cfg.get("inherited"):
        label = "归档摘要模型（和文本 AI 相同）"
    if label[-1:].isascii():
        label += " "  # 「文本 AI 没填…」
    if mode == "off":
        return None, f"{label}已关闭"
    allowed = MODES.get(cap, ())
    if mode not in allowed:
        return None, f"{label}的方式「{mode or '空'}」不认识（可选：{' / '.join(allowed)}）"
    out = dict(cfg)
    out["cap"] = cap
    out["timeoutSec"] = _timeout(cfg, cap)
    if mode == "http":
        if not str(cfg.get("endpoint") or "").strip():
            return None, f"{label}没填接口地址"
        if cap != "embedAI" and not str(cfg.get("model") or "").strip() and cap != "asrAI":
            return None, f"{label}没填模型名"
        key, err = resolve_key(cfg)
        out["apiKey"] = key
        out.pop("keyFile", None)
        out.pop("keyField", None)
        if cfg.get("requireKey") and not key:
            return None, f"{label}没有可用的 key" + (f"（{err}）" if err else "")
        if err and not key:
            out["keyError"] = err
    elif mode == "cli":
        command = cfg.get("command")
        if not command:
            return None, f"{label}没填命令行"
    elif mode == "capswriter":
        try:
            out["port"] = int(cfg.get("port") or 0) or capswriter_port(cfg)
        except (TypeError, ValueError):
            return None, f"{label}的端口不是数字"
        out["host"] = str(cfg.get("host") or "127.0.0.1")
    return out, ""


def resolve(cap: str, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """合并默认值、解 key、带 timeoutSec；None = 未配置 / 关了（原因见 why_not）。"""
    if cap not in CAPS:
        raise ValueError(f"不认识的能力：{cap}")
    cfg, _ = _check(cap, raw_config(cap, settings))
    return cfg


def why_not(cap: str, settings: dict[str, Any] | None = None) -> str:
    _, reason = _check(cap, raw_config(cap, settings))
    return reason


def finalize(cap: str, cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """已经拿到手的一份原样配置（如问答页下拉叠出来的 textAI）走一遍同样的检查。"""
    if cfg.get("cap") == cap and "timeoutSec" in cfg and "keyFile" not in cfg:
        return cfg, ""  # 已经 resolve 过
    return _check(cap, {**_defaults(cap), **cfg})


# --------------------------------------------------------------------------
# CapsWriter 端口：默认读它 config_server.py 里的 ServerConfig.port（知道安装目录时），否则 6016
# --------------------------------------------------------------------------

CAPSWRITER_DEFAULT_PORT = 6016  # HaujetZhao/CapsWriter-Offline config_server.py ServerConfig.port 的出厂值


def capswriter_port(cfg: dict[str, Any] | None = None) -> int:
    import re
    folder = (cfg or {}).get("capsWriterDir") or os.environ.get("CAPSWRITER_DIR") or ""
    if folder:
        try:
            text = (Path(folder) / "config_server.py").read_text(encoding="utf-8", errors="replace")
            m = re.search(r"class\s+ServerConfig\b.*?\n\s*port\s*=\s*['\"]?(\d+)", text, re.S)
            if m:
                return int(m.group(1))
        except OSError:
            pass
    return CAPSWRITER_DEFAULT_PORT


# --------------------------------------------------------------------------
# 统一返回形状 + HTTP 状态 → 故障码
# --------------------------------------------------------------------------

def result(status: str, text: str | None = None, *, code: str = "", error: str | None = None,
           usage: dict[str, Any] | None = None, truncated: bool = False, api_error: bool = False,
           **extra: Any) -> dict[str, Any]:
    """R = {status: ok|failed|skipped, text, code, error, usage, truncated, api_error}（另可带执行器自己的键）。"""
    return {"status": status, "text": text, "code": code, "error": error, "usage": usage,
            "truncated": truncated, "api_error": api_error, **extra}


def skipped(cap: str, reason: str, *, disabled: bool = False) -> dict[str, Any]:
    code = "SKIPPED.DISABLED" if disabled else "SKIPPED.NOT_CONFIGURED"
    return result("skipped", code=code, error=reason)


def skipped_for(cap: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw_config(cap, settings)
    return skipped(cap, why_not(cap, settings) or f"{LABEL.get(cap, cap)}没配置",
                   disabled=str(raw.get("mode") or "") == "off")


_QUOTA_HINTS = ("arrearage", "insufficient_quota", "insufficient balance", "insufficient_balance", "quota",
                "欠费", "余额不足", "billing", "payment required")


def http_code(status: int, body: str = "") -> str:
    """§4.6：429→TRANSIENT.HTTP_429；401/403→NEEDS_HUMAN.AUTH_FAILED；402/欠费→NEEDS_HUMAN.QUOTA_EXCEEDED；
    5xx→TRANSIENT.HTTP_5XX；其他 4xx→PERMANENT.MODEL_OUTPUT_INVALID。"""
    low = (body or "").lower()
    if status == 402 or (400 <= status < 500 and status != 429 and any(h in low for h in _QUOTA_HINTS)):
        return "NEEDS_HUMAN.QUOTA_EXCEEDED"
    if status == 429:
        return "TRANSIENT.HTTP_429"
    if status in (401, 403):
        return "NEEDS_HUMAN.AUTH_FAILED"
    if status >= 500:
        return "TRANSIENT.HTTP_5XX"
    return "PERMANENT.MODEL_OUTPUT_INVALID"


def http_error_text(status: int, code: str) -> str:
    return {
        "TRANSIENT.HTTP_429": f"接口限流（HTTP {status}），稍后自动再试",
        "NEEDS_HUMAN.AUTH_FAILED": f"接口拒绝了 key（HTTP {status}）：到设置里检查或换一个",
        "NEEDS_HUMAN.QUOTA_EXCEEDED": f"接口提示欠费或额度用完（HTTP {status}）",
        "TRANSIENT.HTTP_5XX": f"接口暂时出错（HTTP {status}），稍后自动再试",
    }.get(code, f"接口不接受这次请求（HTTP {status}）：检查模型名和接口地址")


def http_failure(status: int, body: str = "") -> dict[str, Any]:
    code = http_code(status, body)
    # api_error：接口那一侧的故障（限流 / 鉴权 / 欠费 / 服务挂了），不是「这次请求本身有问题」
    return result("failed", code=code, error=http_error_text(status, code),
                  api_error=code != "PERMANENT.MODEL_OUTPUT_INVALID", http_status=status)


def network_failure(exc: Exception) -> dict[str, Any]:
    kind = "超时" if "Timeout" in type(exc).__name__ else "连不上"
    return result("failed", code="TRANSIENT.NETWORK", error=f"接口{kind}：{type(exc).__name__}", api_error=True)
