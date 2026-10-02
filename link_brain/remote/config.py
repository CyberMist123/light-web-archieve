"""远程阅读的配置：唯一来源是插件 data.json 的 `remote` 段（插件写，服务只读）。

    "remote": {"enabled": false, "domain": "https://example.com", "port": 18071, "folders": ["@xhs"]}

- `domain` 存完整来源（https://主机名，不带路径）；空 = 只认本机（127.0.0.1 / localhost）。
- `folders`：`@xhs` = 小红书收藏库（可见笔记 + 每篇的机读版 / 附件全文 / 批注）；其余是 vault 里的相对文件夹。
- 口令、令牌**不在这里**（见 store.py）。

默认值和插件 `remote-ui.js` 的 REMOTE_DEFAULTS 必须一致（tests/test_remote_config.py 核对），改一处改两处。
服务每次请求前调 `Settings.current()`：data.json 的 mtime 变了就重读（热重载域名 / 文件夹 / 开关）。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

XHS = "@xhs"
DEFAULTS: dict[str, Any] = {"enabled": False, "domain": "", "port": 18071, "folders": [XHS]}
PORT_MIN, PORT_MAX = 1024, 65535
ENV_SETTINGS = "LINK_BRAIN_REMOTE_SETTINGS"   # 开发 / 验收用：指向另一份 data.json（真库只读时用）

_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


class ConfigError(ValueError):
    pass


def settings_path(override: str | os.PathLike | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get(ENV_SETTINGS)
    if env:
        return Path(env)
    from ..ai_config import data_json_path
    return data_json_path()


def normalize_domain(value: Any) -> str:
    """'https://a.example.com/' → 'https://a.example.com'；空串 → ''；其他形状抛 ConfigError。
    只收 https（隧道 / 反代在外面终结 TLS）；不收端口、路径、查询、用户名。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.lower().startswith("https://"):
        raise ConfigError("域名要以 https:// 开头")
    host = text[8:].rstrip("/").lower()
    if not _HOST_RE.match(host):
        raise ConfigError("域名格式不对：只填 https://主机名，不带端口和路径")
    return "https://" + host


def domain_host(domain: str) -> str:
    return domain[8:] if domain.startswith("https://") else ""


def normalize_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ConfigError("端口要是数字") from None
    if not PORT_MIN <= port <= PORT_MAX:
        raise ConfigError(f"端口要在 {PORT_MIN}–{PORT_MAX} 之间")
    return port


def normalize(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """把 data.json 的 remote 段叠到默认上。返回 (配置, 问题列表)；坏值退回默认并记一句，绝不抛。
    文件夹在这里只做形状检查；能不能开放由 policy.check_folder 定（服务启动 / 热重载时再筛一遍）。"""
    out = json.loads(json.dumps(DEFAULTS))
    problems: list[str] = []
    if not isinstance(raw, dict):
        return out, problems
    out["enabled"] = raw.get("enabled") is True
    try:
        out["domain"] = normalize_domain(raw.get("domain"))
    except ConfigError as exc:
        problems.append(f"域名没生效：{exc}")
    if raw.get("port") not in (None, ""):
        try:
            out["port"] = normalize_port(raw.get("port"))
        except ConfigError as exc:
            problems.append(f"端口没生效：{exc}，用默认 {DEFAULTS['port']}")
    folders = raw.get("folders")
    if isinstance(folders, list):
        seen: list[str] = []
        for f in folders:
            if isinstance(f, str) and f.strip() and f.strip() not in seen:
                seen.append(f.strip())
        out["folders"] = seen
    return out, problems


def load(path: str | os.PathLike | None = None) -> tuple[dict[str, Any], list[str]]:
    p = settings_path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return normalize(None)[0], [f"没找到插件设置文件：{p.name}"]
    except (OSError, ValueError) as exc:
        return normalize(None)[0], [f"读不了插件设置：{type(exc).__name__}"]
    return normalize(data.get("remote") if isinstance(data, dict) else None)


class Settings:
    """服务端用：带 mtime 缓存的配置（最多每秒 stat 一次）。"""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = settings_path(path)
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._checked = 0.0
        self.value, self.problems = load(self.path)
        self._stamp = self._stat()

    def _stat(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def current(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._checked >= 1.0:
                self._checked = now
                stamp = self._stat()
                if stamp != self._stamp:
                    self._stamp = stamp
                    self.value, self.problems = load(self.path)
            return self.value
