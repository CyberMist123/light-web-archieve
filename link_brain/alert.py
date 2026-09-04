"""出事了要吵醒人：登录态掉了、撞风控验证码、附件下不来。

**本仓库公开**，所以这里不含任何推送地址/key，只认一个外部命令：

    LINK_BRAIN_ALERT_CMD="python C:\\...\\lwa-alert.py"

约定：命令从 **stdin 收一个 JSON**（`{kind, title, body, item_id, url, hint}`），
自己决定怎么送（Bark、TG、邮件都行）。没配这个变量就退化成 stderr 一行，
**永远不抛异常、不阻断归档**——报警失败不该把归档也带走。

写这个命令的人注意：JSON 是 **UTF-8 字节**，Windows 上 Python 默认按 GBK 读 stdin，
要 `sys.stdin.buffer.read().decode("utf-8")`，不然中文全是乱码。
"""

from __future__ import annotations

import json
import os

import subprocess
import sys
from typing import Any

ENV_ALERT_CMD = "LINK_BRAIN_ALERT_CMD"

# 需要人来处理的几类事故（不是"这篇没了"这种数据问题）
KIND_ACCOUNT = "account_blocked"  # 登录态失效 / 风控验证码
KIND_SERVICE = "service_down"  # 18060 的 MCP 不在线 / 它那个浏览器起不来
KIND_ATTACHMENT = "attachment_failed"  # 附件字节没拿到
KIND_BATCH = "batch_aborted"  # 批量里出事，已经停车


def _run(command: str, payload: dict[str, Any]) -> bool:
    try:
        # 这个变量本身就是一条命令行（Owner 自己配的，我们不往里插任何数据），
        # 交给 shell 去拆最省事：Windows 上带引号的路径 shlex 拆不对
        proc = subprocess.run(
            command,
            shell=True,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001 - 报警自己挂了也只能记一句
        print(f"[alert] 报警命令跑不起来（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print(f"[alert] 报警命令退出码 {proc.returncode}: {(proc.stderr or '').strip()[:300]}",
              file=sys.stderr)
        return False
    return True


def alert(kind: str, title: str, body: str, **extra: Any) -> bool:
    """报一次警。返回外部命令是否成功；没配命令返回 False（但 stderr 一定有）。"""
    payload = {"kind": kind, "title": title, "body": body, **extra}
    print(f"[alert] {kind}: {title} — {body}", file=sys.stderr)
    command = os.environ.get(ENV_ALERT_CMD, "").strip()
    if not command:
        return False
    return _run(command, payload)
