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
from urllib.parse import urlsplit

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
        own = vis.get("refine") if isinstance(vis.get("refine"), dict) else None
        if own:  # 1016：第二层单独配接口 / key（如第一层 Gemini 轮 key、第二层兜底百炼 max）
            cfg = {**cfg, **own}
            if "keyPool" not in own:
                cfg.pop("keyPool", None)
        cfg.pop("refine", None)
        cfg["model"] = (own or {}).get("model") or vis.get("refineModel") or vis.get("model") or ""
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


# --------------------------------------------------------------------------
# 1016 key 轮流用（keyPool）：一家给了好几把 key（她的 Gemini 免费 key ×4），设置里写 `"keyPool": "gemini"`。
# 每次取第一把今天还没用坏的；撞 401 / 403 / 429 / 欠费 → 这把记作今天用坏、换下一把；全坏了才算这一家失败（走备用）。
# key 来源：环境变量 LWA_GEMINI_KEYS（夜跑从密码库注入，逗号分隔）→ ~/.link-brain/config.json 的 gemini_keys_file
# （一行一把，只本用户可读）。key 只在内存里，不落盘、不进日志。
# --------------------------------------------------------------------------

POOL_ENV = {"gemini": "LWA_GEMINI_KEYS"}
POOL_FILE_FIELD = {"gemini": "gemini_keys_file"}
POOL_DEAD_CODES = ("NEEDS_HUMAN.AUTH_FAILED", "NEEDS_HUMAN.QUOTA_EXCEEDED", "TRANSIENT.HTTP_429")
_POOL_DEAD: dict[str, dict[str, float]] = {}  # 池名 → {key: 到几点（time.time()）之前别用}
# 429 分两种：每分钟限额（歇一分钟就好，POOL_COOL_S）和每天限额（body 里带 PerDay，今天别用了）。key 被拒 / 欠费 = 今天别用。
POOL_COOL_S = 65.0


def is_daily_limit(body: str) -> bool:
    # 只认 Google 配额 id 里的 PerDay（如 EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier）；
    # 每分钟限额的 body 里也可能出现 daily 字样（文档链接），不能据此把 key 当成今天用完
    return "perday" in (body or "").lower().replace(" ", "")


def pool_keys(name: str) -> list[str]:
    """一个 key 池里所有的 key（按顺序、去重）。拿不到 = []。"""
    raw = os.environ.get(POOL_ENV.get(name, ""), "")
    if not raw.strip():
        try:
            from . import storage
            path = (storage.user_config() or {}).get(POOL_FILE_FIELD.get(name, ""))
            raw = Path(str(path)).expanduser().read_text("utf-8-sig") if path else ""
        except OSError:
            raw = ""
    out: list[str] = []
    for k in raw.replace(",", "\n").splitlines():
        k = k.strip()
        if k and k not in out:
            out.append(k)
    return out


def _end_of_day() -> float:
    import time
    from datetime import datetime, timedelta
    now = datetime.now()
    nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return time.time() + (nxt - now).total_seconds()


def pool_alive(name: str) -> list[str]:
    import time
    now = time.time()
    dead = {k for k, until in _POOL_DEAD.get(name, {}).items() if until > now}
    return [k for k in pool_keys(name) if k not in dead]


def pool_next_free(name: str) -> float | None:
    """key 全在歇的时候，最早哪一把几秒后能用（今天用坏的不算）；没有 = None。"""
    import time
    now = time.time()
    waits = [u - now for u in _POOL_DEAD.get(name, {}).values() if now < u <= now + POOL_COOL_S + 1]
    return min(waits) if waits else None


def pool_mark_dead(name: str, key: str, code: str = "", daily: bool = True) -> None:
    """记一把 key 用坏：每分钟限额（429 且不是每天限额）歇 POOL_COOL_S 秒，其他（被拒 / 欠费 / 每天限额）今天别用。"""
    import time
    cool = code == "TRANSIENT.HTTP_429" and not daily
    _POOL_DEAD.setdefault(name, {})[key] = time.time() + POOL_COOL_S if cool else _end_of_day()


def call_with_pool(cfg: dict[str, Any] | None, call):
    """用 cfg 调一次 call(cfg) → 结果 dict；cfg 带 keyPool 时，结果码是 key 用坏类就换下一把再调，直到成功或 key 用光。
    不带 keyPool 原样调一次。结果里 pool_key_index 记第几把（从 1 起，给日志用，不带 key 本身）。"""
    if not cfg or not cfg.get("keyPool"):
        return call(cfg)
    name = str(cfg["keyPool"])
    keys = pool_alive(name)
    if not keys:
        return result("failed", code="NEEDS_HUMAN.AUTH_FAILED", api_error=True,
                      error=f"{name} 的 key 今天都用不了了（或一把都没配）")
    allk = pool_keys(name)
    got: dict[str, Any] = {}
    for key in keys:
        got = call({**cfg, "apiKey": key})
        if not isinstance(got, dict) or str(got.get("code") or "") not in POOL_DEAD_CODES:
            if isinstance(got, dict):
                got.setdefault("pool_key_index", allk.index(key) + 1)
            return got
        pool_mark_dead(name, key, str(got.get("code") or ""), bool(got.get("daily_limit")))
    return got


def resolve_key(cfg: dict[str, Any]) -> tuple[str, str]:
    """(key, 出错原因)。顺序：apiKey → keyPool（第一把今天没用坏的）→ keyFile/keyField → 环境变量 apiKeyEnv。"""
    key = str(cfg.get("apiKey") or "").strip()
    if not key and cfg.get("keyPool"):
        alive = pool_alive(str(cfg["keyPool"]))
        if alive:
            return alive[0], ""
        return "", f"{cfg['keyPool']} 的 key 一把都拿不到（或今天都用坏了）"
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


# 1008 Owner：「开始」页选了轻量版（不带 AI 的功能组合）就是另一种模式——AI 概要 / 识图不该再跑、更不该报失败。
# 门禁只看 setup.selected 里有没有勾对应组件；没走过「开始」页（selected 不是列表）= 不拦（fail-open，老用户零感知）。
SETUP_COMPONENT = {"textAI": "ai_text", "summaryAI": "ai_text", "embedAI": "ai_text",
                   "visionAI": "ai_vision", "visionAI.refine": "ai_vision"}
SETUP_COMPONENT_CN = {"ai_text": "AI 问答 · 概要 · 打标", "ai_vision": "识图"}


def normalize_endpoint(kind: str, url: str) -> str:
    url = str(url or '').strip().rstrip('/')
    if not url:
        return url
    if '://' not in url:
        url = 'https://' + url
    parsed = urlsplit(url)
    suffix = {'chat': '/chat/completions', 'asr': '/audio/transcriptions', 'embed': '/embeddings'}[kind]
    if parsed.path.endswith(suffix):
        return url
    if parsed.path in ('/v1', '/compatible-mode/v1', '/openai', '/v1beta/openai'):
        return url + suffix
    if not parsed.path:
        prefix = {'dashscope.aliyuncs.com': '/compatible-mode/v1',
                  'generativelanguage.googleapis.com': '/v1beta/openai'}.get(parsed.hostname, '/v1')
        return url + prefix + suffix
    return url


def gate(cap: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    from .setup.components import PRESETS
    comp = SETUP_COMPONENT.get(cap)
    setup = _settings(settings).get('setup') or {}
    selected = setup.get('selected')
    gated = bool(comp and isinstance(selected, list) and setup.get('aiSynced') and comp not in selected)
    preset = 'light' if isinstance(selected, list) and set(selected) == set(PRESETS['light']) else ''
    reason = ''
    if gated:
        reason = f'{LABEL.get(cap, cap)}现在不会跑：「开始」页没勾「{SETUP_COMPONENT_CN[comp]}」'
        reason += '（轻量版）' if preset else ''
        reason += '；要用就在「开始」页勾上，或在 AI 页点「勾上」'
    return {'gated': gated, 'component': comp, 'preset': preset, 'reason': reason}


def setup_off_reason(cap: str, settings: dict[str, Any] | None = None) -> str:
    """这项能力被「开始」页的功能选择关掉了 → 一句原因；没关 → 空串。"""
    comp = SETUP_COMPONENT.get(cap)
    if not comp:
        return ""
    setup = _settings(settings).get("setup") or {}
    selected = setup.get("selected")
    # aiSynced：插件启动时把「已配好 key 的 AI」勾回 selected 后置 true；没对齐过的老设置不拦（否则升级当晚夜跑就把 AI 关了）
    if not isinstance(selected, list) or comp in selected or not setup.get("aiSynced"):
        return ""
    label = LABEL.get(cap, cap)
    return gate(cap, settings)['reason']


def _check(cap: str, cfg: dict[str, Any], settings: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
    label = LABEL.get(cap, cap)
    mode = str(cfg.get("mode") or "").strip()
    if cap == "summaryAI" and cfg.get("inherited"):
        label = "归档摘要模型（和文本 AI 相同）"
    if label[-1:].isascii():
        label += " "  # 「文本 AI 没填…」
    if mode == "off":
        return None, f"{label}已关闭"
    off = setup_off_reason(cap, settings)
    if off:
        return None, off
    allowed = MODES.get(cap, ())
    if mode not in allowed:
        return None, f"{label}的方式「{mode or '空'}」不认识（可选：{' / '.join(allowed)}）"
    out = dict(cfg)
    out["cap"] = cap
    out["timeoutSec"] = _timeout(cfg, cap)
    if mode == "http":
        out['endpoint'] = normalize_endpoint('asr' if cap == 'asrAI' else 'embed' if cap == 'embedAI' else 'chat', cfg.get('endpoint'))
        if not str(cfg.get("endpoint") or "").strip():
            return None, f"{label}没填接口地址"
        if cap != "embedAI" and not str(cfg.get("model") or "").strip() and cap != "asrAI":
            return None, f"{label}没填模型名"
        key, err = resolve_key(cfg)
        out["apiKey"] = key
        out["keySource"] = key_source(cfg)
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
    cfg, _ = _check(cap, raw_config(cap, settings), settings)
    return cfg


def why_not(cap: str, settings: dict[str, Any] | None = None) -> str:
    _, reason = _check(cap, raw_config(cap, settings), settings)
    return reason


def key_source(cfg: dict[str, Any]) -> str:
    """key 是从哪来的（给报错看，不含 key 本身）：设置里填的 / 密钥文件 <文件名> / 环境变量 <名>。"""
    if str(cfg.get("apiKey") or "").strip():
        return "设置里填的 key"
    if cfg.get("keyFile"):
        name = Path(str(cfg["keyFile"])).name
        field = cfg.get("keyField") or "apiKey"
        return f"密钥文件 {name} 里的「{field}」"
    if cfg.get("apiKeyEnv"):
        return f"环境变量 {cfg['apiKeyEnv']}"
    return "没有 key"


def key_hint(cfg: dict[str, Any]) -> str:
    """「设置里填的 key（尾号 ab12）」——报错里认 key 用；只给末 4 位。"""
    src = cfg.get("keySource") or key_source(cfg)
    key = str(cfg.get("apiKey") or "").strip()
    return f"{src}（尾号 {key[-4:]}）" if len(key) >= 8 else src


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
# 1015：百炼等接口的内容审核拦截是 HTTP 400 + data_inspection_failed，不是模型名 / 地址写错
_FILTER_HINTS = ("data_inspection_failed", "inappropriate content", "content_filter", "content_policy_violation")


def http_code(status: int, body: str = "") -> str:
    """§4.6：429→TRANSIENT.HTTP_429；401/403→NEEDS_HUMAN.AUTH_FAILED；402/欠费→NEEDS_HUMAN.QUOTA_EXCEEDED；
    5xx→TRANSIENT.HTTP_5XX；其他 4xx→PERMANENT.MODEL_OUTPUT_INVALID。"""
    low = (body or "").lower()
    if status == 402 or (400 <= status < 500 and status != 429 and any(h in low for h in _QUOTA_HINTS)):
        return "NEEDS_HUMAN.QUOTA_EXCEEDED"
    if status == 429:
        return "TRANSIENT.HTTP_429"
    if 400 <= status < 500 and any(h in low for h in _FILTER_HINTS):
        return "PERMANENT.CONTENT_FILTERED"
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
        "PERMANENT.CONTENT_FILTERED": f"接口的内容审核拦下了这张图（HTTP {status}），不是设置问题",
    }.get(code, f"接口不接受这次请求（HTTP {status}）：检查模型名和接口地址")


def http_failure(status: int, body: str = "") -> dict[str, Any]:
    code = http_code(status, body)
    extra: dict[str, Any] = {}
    if code == "TRANSIENT.HTTP_429" and is_daily_limit(body):
        extra["daily_limit"] = True  # 1016：每天限额满了（key 池今天别再用这把），区别于每分钟限额
    if code == "PERMANENT.CONTENT_FILTERED":  # 审核拦的是附带文字（如 OCR）还是图本身：调用方据此决定去掉文字重试
        extra["filtered_input"] = "text" if "input text" in (body or "").lower() else "unknown"
    # api_error：接口那一侧的故障（限流 / 鉴权 / 欠费 / 服务挂了），不是「这次请求本身有问题」
    return result("failed", code=code, error=http_error_text(status, code),
                  api_error=code not in ("PERMANENT.MODEL_OUTPUT_INVALID", "PERMANENT.CONTENT_FILTERED"),
                  http_status=status, **extra)


def network_failure(exc: Exception) -> dict[str, Any]:
    kind = "超时" if "Timeout" in type(exc).__name__ else "连不上"
    return result("failed", code="TRANSIENT.NETWORK", error=f"接口{kind}：{type(exc).__name__}", api_error=True)
