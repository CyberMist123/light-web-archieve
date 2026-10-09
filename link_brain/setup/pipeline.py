"""「一键装好 / 跑完」（1009 她：装好插件 → 填 API（可选）→ 点一次 → 同步、OCR / 识图、概要、目录、索引一口气跑完；
不填 API 也一口气跑完轻量版）。`python -m link_brain setup run`。

按「开始」页勾的功能（data.json 的 setup.selected；没选过 = 轻量版）依次：
  装好缺的（能自动装的逐项装，装不了的如实给做法、不挡后面）→ 确认小红书登录（只问读取服务内存状态，不开页）→
  同步收藏（含本地 OCR、开了 AI 就顺手识图 / 概要）→ 补识图 / 概要（开了 AI 才跑）→ 整理目录 →
  语义索引（开了 AI 才跑）→ 评论补齐转后台（读不完的接着补）。
每一步是带时限的子进程（超时只结束这一步、放过读取服务和它的浏览器）；stdout 一行一个进度事件
`{"type":"progress","stage","label","index","count","state":"running|ok|skipped|failed","text"}`，最后一行 result
（CONVENTIONS §1 形状 + stages[]）。号要人处理（掉登录 / 验证）→ 碰号的步骤跳过、离线的照跑，结果里一句话说清先做哪一步。
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from .common import Emit

LIGHT = ["core", "reader", "dataview", "ocr"]
STAGES = [
    ("install", "装好要用的组件"),
    ("login", "确认小红书登录"),
    ("sync", "同步收藏（含 OCR / 识图 / 概要）"),
    ("enrich", "补识图 / 概要"),
    ("catalog", "整理目录"),
    ("embed", "建语义索引"),
    ("comments", "评论补齐（读不完的后台接着补）"),
]
TIMEOUT_MIN = {"sync": 170, "enrich": 70, "catalog": 10, "embed": 25}


def selected() -> list[str]:
    from .. import ai_config
    try:
        sel = (ai_config.load().get("setup") or {}).get("selected")
    except Exception:  # noqa: BLE001
        sel = None
    return list(sel) if isinstance(sel, list) and sel else list(LIGHT)


def _ai_on(sel: list[str], cap: str) -> bool:
    """这项 AI 勾了、也配好了能用（没配 key 的勾了也不跑，结果里说一句）。"""
    from .. import providers
    comp = {"summaryAI": "ai_text", "visionAI": "ai_vision", "embedAI": "ai_text"}[cap]
    if comp not in sel:
        return False
    try:
        return providers.resolve(cap) is not None
    except Exception:  # noqa: BLE001
        return False


def _child(args: list[str], *, timeout_min: float, on_line: Callable[[str], None], env_extra: dict[str, str] | None = None,
           python: str | None = None) -> tuple[int | None, bool]:
    """跑一步 `python -m link_brain …`：stderr 每行交给 on_line（给人看的进度），超时整棵结束（放过读取服务）。"""
    from .. import nightly, procs
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    if env_extra:
        env.update(env_extra)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    p = subprocess.Popen([python or sys.executable, "-m", "link_brain", *args], stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, creationflags=flags)
    lines: queue.Queue = queue.Queue()

    def pump(stream, tag):
        try:
            for raw in iter(stream.readline, b""):
                lines.put((tag, raw.decode("utf-8", "replace").rstrip("\r\n")))
        except (OSError, ValueError):
            pass
        finally:
            lines.put((tag, None))

    for stream, tag in ((p.stdout, "out"), (p.stderr, "err")):
        threading.Thread(target=pump, args=(stream, tag), daemon=True).start()
    deadline = time.monotonic() + timeout_min * 60
    open_streams = {"out", "err"}
    timed_out = False
    while open_streams:
        try:
            tag, line = lines.get(timeout=0.5)
        except queue.Empty:
            tag = line = None
        if tag is not None:
            if line is None:
                open_streams.discard(tag)
            elif tag == "err" and line.strip():
                on_line(line.strip())
        if time.monotonic() > deadline and p.poll() is None:
            timed_out = True
            try:
                procs.kill_tree(p.pid, exclude=nightly.kill_exclude())
            except Exception:  # noqa: BLE001
                pass
            try:
                p.kill()
            except OSError:
                pass
            break
        if p.poll() is not None and not open_streams:
            break
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    return (None if timed_out else p.returncode), timed_out


def run(emit: Emit, *, child=_child, account_check=None) -> dict[str, Any]:
    from . import components
    sel = selected()
    stages: list[dict[str, Any]] = []
    count = len(STAGES)
    blocked_why = ""

    def say(stage: str, state: str, text: str = "") -> dict[str, Any]:
        idx = [s for s, _ in STAGES].index(stage) + 1
        label = dict(STAGES)[stage]
        emit({"type": "progress", "stage": stage, "label": label, "index": idx, "count": count, "state": state,
              "text": text})
        row = {"id": stage, "label": label, "state": state, "text": text}
        if state != "running":
            stages.append(row)
        return row

    # 1) 装好要用的组件（不要 key、不是「以后」的）
    say("install", "running", "检查中…")
    targets = [c["id"] for c in components.COMPONENTS if c["id"] in sel and not c.get("later") and not c.get("needs_key")]
    chk = components.check(targets)
    manual: list[str] = []
    for r in chk.get("results") or []:
        if r["status"] in ("ready", "needs_key"):
            continue
        if r.get("fix") == "auto":
            say("install", "running", f"安装 {r['item_id']}…")
            out = components.install(r["item_id"], lambda ev: emit({**ev, "stage": "install"}))
            if not out.get("ok"):
                manual.append(f"{r['item_id']}：{out.get('message') or '没装上'}")
        else:
            manual.append(f"{r['item_id']}：{r.get('fix_hint') or r.get('detail') or '要手动装'}")
    say("install", "ok" if not manual else "failed", "全部就绪" if not manual else "；".join(manual)[:300])

    # 2) 小红书登录（只看内存状态，不开页）
    say("login", "running", "")
    check = account_check or _account_state
    code, why = check()
    if code:
        blocked_why = why
        say("login", "failed", why)
    else:
        say("login", "ok", "已登录")

    # 3) 同步收藏
    def step(stage: str, args: list[str], env_extra: dict[str, str] | None = None) -> int | None:
        say(stage, "running", "")
        last = {"t": 0.0}

        def on_line(line: str) -> None:
            now = time.monotonic()
            if now - last["t"] >= 1.0:
                last["t"] = now
                emit({"type": "progress", "stage": stage, "label": dict(STAGES)[stage],
                      "index": [s for s, _ in STAGES].index(stage) + 1, "count": count, "state": "running",
                      "text": line[-160:]})
        rc, timed_out = child(args, timeout_min=TIMEOUT_MIN.get(stage, 30), on_line=on_line, env_extra=env_extra)
        if timed_out:
            say(stage, "failed", f"超过 {TIMEOUT_MIN.get(stage, 30)} 分钟没做完，先停（做了的都存好了，夜里接着做）")
        elif rc in (0, 2, 3):
            say(stage, "ok", "完成" if rc == 0 else "做了一部分（剩下的夜里接着做）")
        elif rc == 5:
            say(stage, "failed", "小红书要你处理（验证 / 登录），这一步先停")
        elif rc == 6:
            say(stage, "failed", "号正被别的任务用着，这一步先跳过")
        else:
            say(stage, "failed", f"出错退出（{rc}），原因见问题面板 / 同步记录")
        return rc

    if blocked_why:
        say("sync", "skipped", "先处理小红书登录（见上一步）")
    else:
        rc = step("sync", ["sync-favorites", "--limit", "0", "--extract"], {"LINK_BRAIN_SYNC_TRIGGER": "manual"})
        if rc == 5:
            blocked_why = blocked_why or "小红书要你处理（验证 / 登录）"
    if _ai_on(sel, "summaryAI") or _ai_on(sel, "visionAI"):
        step("enrich", ["enrich", "--pending", "--budget-min", "60"])
    else:
        say("enrich", "skipped", "没开 AI（轻量版）：不做概要 / 识图" if not ({"ai_text", "ai_vision"} & set(sel))
            else "勾了 AI 但接口 / key 没配好：到「功能」里填上再跑")
    step("catalog", ["catalog"])
    if _ai_on(sel, "embedAI"):
        step("embed", ["embed"])
    else:
        say("embed", "skipped", "没开 AI：关键词搜索照常能用")
    if blocked_why:
        say("comments", "skipped", "先处理小红书登录")
    else:
        say("comments", "running", "")
        try:
            from .. import comment_fill
            r = comment_fill.spawn_worker()
            st = comment_fill.survey()
            say("comments", "ok", ("后台在补" if st["pending"] else "评论都补齐了") +
                (f"（{st['pending']} 篇、{st['missing']} 条回复）" if st["pending"] else "") if r.get("ok") else "没拉起来")
        except Exception as exc:  # noqa: BLE001
            say("comments", "failed", f"后台补评论没拉起来：{type(exc).__name__}: {exc}"[:200])
    failed = [s for s in stages if s["state"] == "failed"]
    if blocked_why:
        message = f"先处理小红书：{blocked_why}；处理好再点一次「一键装好 / 跑完」"
    elif failed:
        message = "跑完了，有 " + str(len(failed)) + " 步没成：" + "；".join(f"{s['label']}（{s['text']}）" for s in failed)[:300]
    else:
        message = "都跑完了" + ("（轻量版）" if not ({"ai_text", "ai_vision"} & set(sel)) else "")
    return {"type": "result", "ok": not failed and not blocked_why, "code": "NEEDS_HUMAN" if blocked_why else "",
            "message": message, "stages": stages, "selected": sel}


def _account_state() -> tuple[str, str]:
    """('', '') = 号能用；否则 (码, 一句该做什么)。没装读取组件也在这里说。"""
    from .. import comment_fill
    try:
        code, why = comment_fill.account_wait_reason()
    except Exception as exc:  # noqa: BLE001 - DEV_COPY_BLOCKED 等
        return "BLOCKED", str(exc)
    if code == "NOT_INSTALLED":
        return code, "没装读取组件：在「功能」里点「一键装好」装上（或按 README 手动装）"
    return code, why
