"""「一键装好 / 跑完」（1009 作者：装好插件 → 填 API（可选）→ 点一次 → 同步、OCR / 识图、概要、目录、索引一口气跑完；
不填 API 也一口气跑完轻量版）。`python -m link_brain setup run`。

按「开始」页勾的功能（data.json 的 setup.selected；没选过 = 轻量版）依次：
  装好缺的（能自动装的逐项装，装不了的如实给做法、不挡后面）→ 确认小红书登录（只问读取服务内存状态，不开页）→
  同步收藏（含本地 OCR、开了 AI 就顺手识图 / 概要）→ 补识图 / 概要（开了 AI 才跑）→ 整理目录 →
  语义索引（开了 AI 才跑）→ 评论补齐转后台（读不完的接着补）。
1103：同步之后读一次小红书专辑（以前只在夜跑读）；和读收藏共用限频，离上次读收藏不满 30 分钟先等够。
每一步是带时限的子进程（超时只结束这一步、放过读取服务和它的浏览器）；stdout 一行一个进度事件
`{"type":"progress","stage","label","index","count","state":"running|ok|skipped|failed","text"}`，最后一行 result
（CONVENTIONS §1 形状 + stages[]）。号要人处理（掉登录 / 验证）→ 碰号的步骤跳过、离线的照跑，结果里一句话说清先做哪一步。
1101：没登小红书但本机登过 B 站 = 只用 B 站，小红书那几步跳过、不算要人处理。B 站收藏不在这里下（视频大，作者定的只手动同步）。
1102（安装审查 6/7/8）：
  - 读取组件没起来（被杀毒隔离 / 端口被占 / 崩了 → `DISCONNECTED`）和没装（`NOT_INSTALLED`）不算号的事：login 记 failed，
    result 的 code 分别是 `TRANSIENT.DISCONNECTED` / `NEEDS_HUMAN.NOT_INSTALLED`，message 让人点重试或看 reader.log，不引导扫码。
  - 只能检查、要用户自己在 Obsidian 里装的（check_only + fix=manual）单列 `needs_you`，不算 failed：
    其余都成时 ok=true、退出 0，message 末尾附一句要用户做什么。（当时唯一的一项 Dataview 1102 起不再需要——页面由
    LWA 插件自己显示——眼下没有 check_only 项，分类逻辑留着给以后同类的项。）
  - 每个步骤状态一变就写 `_archive/setup-run.json`（running / pid / started_at / current / stages / result）：
    Obsidian 关掉、stdout 管道断了之后进度仍落盘，插件重开时按它续画或说「上次没跑完，停在 X 步」。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from .common import Emit
from ..errtext import errtext

LIGHT = ["core", "reader", "ocr"]
# 1103 作者：视频说话转文字（CapsWriter，约 2 GB）不进自动安装：用户勾上才由插件单独起 `setup install --component asr` 后台下载
INDEPENDENT = ("asr", "capslock")
STAGES = [
    ("catalog_first", "生成目录页"),
    ("install", "装好要用的组件"),
    ("login", "确认小红书登录"),
    ("sync", "同步收藏（含 OCR / 识图 / 概要）"),
    ("enrich", "补识图 / 概要"),
    ("albums", "读小红书专辑"),
    ("catalog", "整理目录"),
    ("embed", "建语义索引"),
    ("comments", "评论补齐（读不完的后台接着补）"),
]
TIMEOUT_MIN = {"catalog_first": 10, "sync": 170, "enrich": 70, "albums": 30, "catalog": 10, "embed": 25}
# 1104（审查 3）：装一项组件（子进程 `setup install`，计时覆盖读输出全程）；父进程退了、后代还攥着管道时最多再等这么久
INSTALL_TIMEOUT_MIN = 40
CHILD_EXIT_GRACE_S = 10
RUN_LOCK = "setup-run"   # 整轮一把（按收藏库）：两个窗口 / 插件和命令行同时跑时，后到的说忙，不覆盖进度文件
ALBUMS_WAIT_MAX_S = 35 * 60   # 1103：专辑列表和读收藏共用限频，同步完最多等这么久再读（自律间隔 30 分钟）
STATE_FILE = "setup-run.json"
# 读取组件那一侧的码（不是号的事）：服务没起来 / 没应答 → 自动可重试；没装 → 要人点一下「一键装好」
READER_DOWN_CODES = ("DISCONNECTED", "TIMEOUT", "BUSY", "BROWSER_STUCK")
READER_MESSAGE = "读取组件没起来，点重试或看 reader.log"
LOGIN_WAIT_TEXT = "还没登录小红书：扫码登录后自动开始同步"
# 要用户自己在 Obsidian 里做的（check_only + fix=manual）：给人话，不算 failed
NEEDS_YOU_TEXT: dict[str, str] = {}   # 功能 id → 一句人话；1102 起 Dataview 不再需要，眼下是空的


def state_path():
    from .. import storage
    return storage.archive_root() / STATE_FILE


def write_state(state: dict[str, Any]) -> bool:
    """`_archive/setup-run.json`：写不进去不挡安装（fail-open），返回写成没写成。"""
    from .. import storage
    try:
        storage.write_json(state_path(), state)
        return True
    except (OSError, ValueError):
        return False


def login_code(code: str) -> str:
    """login 一步的原始码 → result 的故障码：读取组件没起来 TRANSIENT.DISCONNECTED · 没装 NEEDS_HUMAN.NOT_INSTALLED ·
    其余（掉登录 / 验证 / 风控 / 开发副本）都是号要人处理 NEEDS_HUMAN。"""
    if not code:
        return ""
    if code in READER_DOWN_CODES:
        return "TRANSIENT.DISCONNECTED"
    if code == "NOT_INSTALLED":
        return "NEEDS_HUMAN.NOT_INSTALLED"
    return "NEEDS_HUMAN"


class SettingsUnreadable(RuntimeError):
    """data.json 在、但连读几次都不是完整的 JSON（插件正写到一半 / 被别的程序改坏）。"""


def _settings_readable(tries: int = 4, wait_s: float = 0.5, sleep: Callable[[float], None] = time.sleep) -> None:
    """1104（审查 5）：读到半截的 data.json 不能当成「没选过 = 轻量版」——短暂重读，还不行抛 SettingsUnreadable。
    文件不在 = 真没选过，照轻量版。"""
    import json
    from .. import ai_config
    path = ai_config.data_json_path()
    for i in range(tries):
        if not path.exists():
            return
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
            return
        except (OSError, ValueError):
            if i < tries - 1:
                sleep(wait_s)
    raise SettingsUnreadable(f"插件设置文件读不动（{path.name} 可能正在保存或被改坏了）")


def selected() -> list[str]:
    """这一刻的选择：没选过 = 轻量版；1104（审查 1）：缺的必选项 / 依赖一律补齐（读取组件是必选，
    老配置、手改的列表里缺了也照补），和插件 withDeps 同一口径。设置文件读到半截抛 SettingsUnreadable。"""
    from .. import ai_config
    from . import components
    _settings_readable()
    try:
        sel = (ai_config.load().get("setup") or {}).get("selected")
    except Exception:  # noqa: BLE001
        sel = None
    return components.normalize_selection(list(sel) if isinstance(sel, list) and sel else list(LIGHT))


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
    exited_at: float | None = None
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
            elif tag == "out" and line.lstrip().startswith("{"):
                # 1104（审查 8 / 3）：子命令 stdout 的 JSON（进度事件、最后的 result）原样交给调用方，不再丢掉
                try:
                    obj = json.loads(line)
                except ValueError:
                    obj = None
                if isinstance(obj, dict):
                    on_line(obj)
        now = time.monotonic()
        if p.poll() is not None and exited_at is None:
            exited_at = now
        # 1104（审查 3）：超时不管父进程还在不在都算——父进程退了、后代还攥着管道时以前会一直等 EOF
        if now > deadline:
            timed_out = p.poll() is None or bool(open_streams)
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
        if exited_at is not None and now - exited_at > CHILD_EXIT_GRACE_S:
            break   # 父进程已退出，留下的后代还攥着管道：不再等它，结果按父进程的退出码算
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    return (None if timed_out else p.returncode), timed_out


def _albums_wait_s() -> float:
    try:
        from ..sources.xiaohongshu import albums
        return albums.list_gap_left_s()
    except Exception:  # noqa: BLE001 - 算不出来就按现在能读
        return 0.0


def _run_lock_name() -> str:
    """按收藏库一把：两个库各跑各的，同一个库只能有一轮。"""
    import hashlib
    from .. import storage
    return f"{RUN_LOCK}-{hashlib.sha1(str(storage.vault_root()).encode('utf-8')).hexdigest()[:10]}"


def _install_via_child(cid: str, emit: Emit, child) -> dict[str, Any]:
    """1104（审查 3）：装一项走限时子进程 `setup install --component <id>`（以前在本进程里装：读 uv 输出那段没有时限、
    OCR 自检卡住整轮跟着卡）。子进程的进度事件原样转给插件，最后一行 result 就是这一项的结果（带 settings_patch）。"""
    got: dict[str, Any] = {}

    def on_line(x) -> None:
        if not isinstance(x, dict):
            return
        if x.get("type") == "result":
            got.clear()
            got.update(x)
        elif x.get("type") == "progress":
            emit({**x, "stage": "install"})
    rc, timed_out = child(["setup", "install", "--component", cid], timeout_min=INSTALL_TIMEOUT_MIN, on_line=on_line)
    if timed_out:
        return {"ok": False, "code": "TRANSIENT.TIMEOUT", "status": "failed", "component": cid,
                "message": f"装 {cid} 超过 {INSTALL_TIMEOUT_MIN} 分钟没装完，已停下（下了的留着，再点一次接着装）"}
    if not got:
        return {"ok": False, "code": "TRANSIENT.STEP_CRASHED", "status": "failed", "component": cid,
                "message": f"装 {cid} 的进程没给结果就退出了（退出码 {rc}），详情见 ~/.link-brain/logs"}
    return got


def _report_setup(stages: list[dict[str, Any]], install_fail: list[tuple[str, str, str]]) -> None:
    """1104（审查 7）：装组件没成的登记进问题记录（修复区「当前状态」和上次跑完的结果用同一份分类）；这一轮装好了就解掉。
    号 / 读取组件的事由 login 那一步登记（report_blocked）。永不抛。"""
    try:
        from .. import problems
        if not install_fail and any(s["id"] == "install" and s["state"] == "ok" for s in stages):
            problems.resolve("setup")
        for cid, code, why in install_fail:
            try:
                problems.report("setup", code or "TRANSIENT.STEP_CRASHED", f"{cid}：{why}"[:300], item_id=None, title=f"装 {cid}")
            except problems.BadCode:
                problems.report("setup", "TRANSIENT.STEP_CRASHED", f"{cid}：{why}"[:300], item_id=None, title=f"装 {cid}")
    except Exception:  # noqa: BLE001 - 登记失败不挡安装
        pass


def run(emit: Emit, *, child=_child, install=None, account_check=None, bili_check=None, albums_wait=_albums_wait_s,
        sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """整轮在一把按收藏库的锁里（1104 审查 4）：拿不到 = 另一个窗口 / 命令行正在跑，说忙、不碰进度文件。
    中途出意外也把进度文件收尾成 running=false + result（审查 9），插件重开不会一直显示「在跑」。"""
    from .. import storage
    name = _run_lock_name()
    try:
        with storage.file_lock(name, wait_s=0, owner="一键装好 / 跑完"):
            return _run(emit, child=child, install=install, account_check=account_check, bili_check=bili_check,
                        albums_wait=albums_wait, sleep=sleep)
    except storage.LockBusy as exc:
        if exc.name != name:
            raise
        return {"type": "result", "ok": False, "code": "TRANSIENT.BUSY", "busy": True, "stages": [],
                "message": "这个收藏库已经有一轮「一键装好 / 跑完」在跑（另一个窗口或命令行），进度在设置页「懒人安装」；跑完再点"}


def _run(emit: Emit, *, child, install, account_check, bili_check, albums_wait, sleep) -> dict[str, Any]:
    from . import components
    from .. import storage
    stages: list[dict[str, Any]] = []
    count = len(STAGES)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    # vault：这一轮实际写到哪（进程环境里钉死的收藏位置）。插件那边改了位置是下一轮生效，续画按这里读（1103）
    state: dict[str, Any] = {"running": True, "pid": os.getpid(), "started_at": started_at, "updated_at": started_at,
                             "current": None, "detail": "", "stages": stages, "result": None, "vault": str(storage.vault_root())}

    def flush_state() -> None:
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        write_state(state)

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        state.update(running=False, current=None, detail="", result=result)
        flush_state()
        return result

    # 1103 作者：边跑边选——没跑到的步骤按「到它时最新的设置」。selected() 每次现读 data.json，各步开始时重读
    try:
        sel = selected()
    except SettingsUnreadable as exc:
        return finish({"type": "result", "ok": False, "code": "TRANSIENT.BUSY", "stages": stages,
                       "message": f"{exc}：等几秒再点一次「一键装好 / 跑完」；还不行在设置页随便改一项让它重存一次"})
    try:
        return finish(_steps(emit, sel, stages, state, flush_state, child=child, install=install, account_check=account_check,
                             bili_check=bili_check, albums_wait=albums_wait, sleep=sleep, count=count, components=components))
    except Exception as exc:  # noqa: BLE001 - 收尾：进度文件不能停在 running
        cur = state.get("current")
        return finish({"type": "result", "ok": False, "code": "TRANSIENT.STEP_CRASHED", "stages": stages,
                       "message": f"一键装好 / 跑完中途出错（{dict(STAGES).get(cur, cur) or '收尾'}）：{errtext(exc)}；做了的都存好了，再点一次接着来"})


def _steps(emit: Emit, sel: list[str], stages: list[dict[str, Any]], state: dict[str, Any], flush_state, *, child, install,
           account_check, bili_check, albums_wait, sleep, count: int, components) -> dict[str, Any]:
    blocked_why = ""
    blocked_code = ""   # 1102：login 那一步的 result 码（NEEDS_HUMAN / TRANSIENT.DISCONNECTED / NEEDS_HUMAN.NOT_INSTALLED）
    reader_down = False
    xhs_off = False   # 1101：没登小红书、登了 B 站 = 只用 B 站，小红书那几步跳过，不算要人处理
    login_wait = False   # 1103：小红书还没登录 = 等扫码（不算失败）
    needs_you: list[dict[str, str]] = []
    notes: list[str] = []

    def cur_sel(prev: list[str]) -> list[str]:
        """1104（审查 5）：步骤之间设置文件读到半截——这一步按上一步的选择走，不当成「没选过」。"""
        try:
            return selected()
        except SettingsUnreadable:
            if "设置文件一时读不动，后面几步按开跑时的选择走" not in notes:
                notes.append("设置文件一时读不动，后面几步按开跑时的选择走")
            return prev

    def say(stage: str, state_: str, text: str = "", detail: str | None = None) -> dict[str, Any]:
        idx = [s for s, _ in STAGES].index(stage) + 1
        label = dict(STAGES)[stage]
        row = {"id": stage, "label": label, "state": state_, "text": text}
        # 先落盘再发事件：stdout 那头（插件）看到的任何一条，文件里都已经有了
        if state_ != "running":
            stages.append(row)
            state["current"] = None
            state["detail"] = ""
            flush_state()
        elif state["current"] != stage or (detail is not None and detail != state.get("detail")):
            # 同一步的多次 running 事件只在换步 / 换了在做的事（装哪一项、等什么）时落盘（子进程每秒一行进度，不用每行都写）
            state["current"] = stage
            if detail is not None:
                state["detail"] = detail
            flush_state()
        emit({"type": "progress", "stage": stage, "label": label, "index": idx, "count": count, "state": state_,
              "text": text})
        return row

    def step(stage: str, args: list[str], env_extra: dict[str, str] | None = None) -> int | None:
        say(stage, "running", "")
        last = {"t": 0.0}
        res: dict[str, Any] = {}

        def on_line(line) -> None:
            if isinstance(line, dict):
                if line.get("type") == "result" or ("ok" in line and "message" in line):
                    res.clear()
                    res.update(line)   # 1104（审查 8）：子命令最后的结果 JSON（缺什么、为什么）留着，下面说人话用
                return
            now = time.monotonic()
            if now - last["t"] >= 1.0:
                last["t"] = now
                emit({"type": "progress", "stage": stage, "label": dict(STAGES)[stage],
                      "index": [s for s, _ in STAGES].index(stage) + 1, "count": count, "state": "running",
                      "text": line[-160:]})
        rc, timed_out = child(args, timeout_min=TIMEOUT_MIN.get(stage, 30), on_line=on_line, env_extra=env_extra)
        said = str(res.get("message") or "").strip()[:200]
        # 1104（审查 8）：不再一律承诺「夜里接着做」——夜跑可能根本没开；说清做到哪、怎么接着做
        again = "再点一次「一键装好 / 跑完」接着做；开了定时同步的会在下次同步时补"
        if timed_out:
            say(stage, "failed", f"超过 {TIMEOUT_MIN.get(stage, 30)} 分钟没做完，先停（做了的都存好了；{again}）")
        elif rc == 0:
            say(stage, "ok", "完成")
        elif rc in (2, 3):
            say(stage, "partial", f"做了一部分：{said or '有几篇没处理完'}（{again}）")
        elif rc == 5:
            say(stage, "failed", "小红书要你处理（验证 / 登录），这一步先停")
        elif rc == 6:
            say(stage, "failed", "号正被别的任务用着，这一步先跳过")
        else:
            say(stage, "failed", f"出错退出（{rc}）：{said}" if said else f"出错退出（{rc}），原因见问题面板 / 同步记录")
        return rc

    # 0) 目录页先有（1103 作者：想看目录不该等几小时的同步）：不依赖登录、不等组件；空库也出一个空目录页，同步中边存边填
    step("catalog_first", ["catalog"])

    # 1) 装好要用的组件（不要 key、不是「以后」的；语音那两项单独装，见 INDEPENDENT）
    # 1104 作者定（审查 4 问）：「边跑边改」以步骤开始为界——要装哪几项在这一步开始时定下，已开始的不撤回
    sel = cur_sel(sel)
    say("install", "running", "检查中…")
    targets = [c["id"] for c in components.COMPONENTS
               if c["id"] in sel and not c.get("later") and not c.get("needs_key") and c["id"] not in INDEPENDENT]
    check_only = {c["id"] for c in components.COMPONENTS if c.get("check_only")}
    chk = components.check(targets)
    manual: list[str] = []
    install_fail: list[tuple[str, str, str]] = []
    for r in chk.get("results") or []:
        if r["status"] in ("ready", "needs_key"):
            continue
        if r.get("fix") == "auto":
            say("install", "running", f"安装 {r['item_id']}…", detail=r["item_id"])
            fwd = lambda ev: emit({**ev, "stage": "install"})  # noqa: E731
            out = install(r["item_id"], fwd) if install else _install_via_child(r["item_id"], emit, child)
            # 1103：每装完一项就报一条结果（插件据此清掉「正在装 X」、重读功能清单，不等整轮跑完）；
            # 1104（审查 5）：带上 settings_patch（如 OCR 的模型目录），插件按字段合进内存，免得下次保存盖掉
            ev = {"type": "progress", "stage": "install", "component": r["item_id"], "state": "ok" if out.get("ok") else "failed",
                  "status": out.get("status") or "", "text": out.get("message") or ""}
            if out.get("settings_patch"):
                ev["settings_patch"] = out["settings_patch"]
            emit(ev)
            if not out.get("ok"):
                manual.append(f"{r['item_id']}：{out.get('message') or '没装上'}")
                install_fail.append((r["item_id"], str(out.get("code") or ""), out.get("message") or "没装上"))
        elif r["item_id"] in check_only:
            # 1102：只能检查、要用户自己在 Obsidian 里装的：单列 needs_you，不算这一步失败
            hint = r.get("fix_hint") or r.get("detail") or "要手动装"
            needs_you.append({"item_id": r["item_id"], "status": r["status"],
                              "text": NEEDS_YOU_TEXT.get(r["item_id"]) or f"还要你装 {r['item_id']}（{hint}）", "hint": hint})
        else:
            manual.append(f"{r['item_id']}：{r.get('fix_hint') or r.get('detail') or '要手动装'}")
            install_fail.append((r["item_id"], "SKIPPED.NOT_CONFIGURED", r.get("fix_hint") or r.get("detail") or "要手动装"))
    install_text = "全部就绪" if not manual else "；".join(manual)[:300]
    if needs_you:
        install_text = ("；".join(x["text"] for x in needs_you) if not manual else install_text + "；" +
                        "；".join(x["text"] for x in needs_you))[:300]
    say("install", "ok" if not manual else "failed", install_text)
    _report_setup(stages, install_fail)

    # 2) 小红书登录（问读取服务：没在跑会先拉起它；只有它记得「没登录」又没熔断时才深查一次，见 account_wait_reason）
    say("login", "running", "")
    check = account_check or _account_state
    code, why = check()
    if code in ("NOT_LOGGED_IN", "NOT_INSTALLED") and (bili_check or _bili_logged_in)():
        xhs_off = True
        say("login", "skipped", "没登小红书，只用 B 站：小红书的几步跳过（要用小红书就去扫码，再点一次）")
    elif code == "NOT_LOGGED_IN":
        # 1103 作者：扫码可以慢慢来——没登录不算这一轮失败：组件照装、目录照建，小红书那几步等扫码后自动接上
        login_wait = True
        blocked_code = "NEEDS_HUMAN.NOT_LOGGED_IN"
        say("login", "waiting", LOGIN_WAIT_TEXT)
    elif code:
        blocked_code = login_code(code)
        reader_down = blocked_code != "NEEDS_HUMAN"
        blocked_why = why
        say("login", "failed", why)
        # 1104（审查 7）：读取组件没起来 / 没装 / 号出事 也进问题记录，修复区「当前状态」不再说「没有要你处理的」
        try:
            from .. import problems
            problems.report_blocked("login", code, why, service=code in READER_DOWN_CODES)
        except Exception:  # noqa: BLE001
            pass
    else:
        say("login", "ok", "已登录")

    # 3) 同步收藏
    if xhs_off:
        say("sync", "skipped", "没登小红书；B 站收藏在「收藏与同步 → B 站」手动同步")
    elif login_wait:
        say("sync", "skipped", LOGIN_WAIT_TEXT)
    elif reader_down:
        say("sync", "skipped", "读取组件没起来（见上一步）")
    elif blocked_why:
        say("sync", "skipped", "先处理小红书登录（见上一步）")
    else:
        rc = step("sync", ["sync-favorites", "--limit", "0", "--extract"], {"LINK_BRAIN_SYNC_TRIGGER": "manual"})
        if rc == 5:
            blocked_why = blocked_why or "小红书要你处理（验证 / 登录）"
            blocked_code = blocked_code or "NEEDS_HUMAN"
    sel = cur_sel(sel)
    if _ai_on(sel, "summaryAI") or _ai_on(sel, "visionAI"):
        step("enrich", ["enrich", "--pending", "--budget-min", "60"])
    else:
        say("enrich", "skipped", "没开 AI（轻量版）：不做概要 / 识图" if not ({"ai_text", "ai_vision"} & set(sel))
            else "勾了 AI 但接口 / key 没配好：到「功能」里填上再跑")
    # 1103 作者：小红书专辑第一次就读出来（以前只在夜跑读）——号能用才读；和读收藏共用限频，离上次读收藏不满 30 分钟就等够再读
    if xhs_off or login_wait or reader_down or blocked_why:
        say("albums", "skipped", "小红书没登录 / 要你处理：扫码后再点一次「一键装好 / 跑完」会读")
    else:
        wait = min(max(0.0, float(albums_wait() or 0)), ALBUMS_WAIT_MAX_S)
        if wait > 0:
            say("albums", "running", f"刚读过收藏，歇 {wait / 60:.0f} 分钟再读专辑（不连读，免得被限频）", detail="等限频")
            sleep(wait)
        rc = step("albums", ["albums", "sync", "--max", "6", "--budget-min", "25"])
        if rc == 5:
            blocked_why = blocked_why or "小红书要你处理（验证 / 登录）"
            blocked_code = blocked_code or "NEEDS_HUMAN"
    step("catalog", ["catalog"])
    sel = cur_sel(sel)
    if _ai_on(sel, "embedAI"):
        step("embed", ["embed"])
    else:
        say("embed", "skipped", "没开 AI：关键词搜索照常能用")
    if xhs_off:
        say("comments", "skipped", "没登小红书，不用补评论")
    elif login_wait:
        say("comments", "skipped", "扫码登录小红书后，同步完自动补评论")
    elif reader_down:
        say("comments", "skipped", "读取组件没起来，补不了评论")
    elif blocked_why:
        say("comments", "skipped", "先处理小红书登录")
    else:
        say("comments", "running", "")
        try:
            from .. import comment_fill
            r = comment_fill.spawn_worker()
            st = comment_fill.survey()
            if r.get("ok"):
                say("comments", "ok", ("后台在补" if st["pending"] else "评论都补齐了") +
                    (f"（{st['pending']} 篇、{st['missing']} 条回复）" if st["pending"] else ""))
            else:
                say("comments", "failed", f"后台补评论没拉起来：{r.get('message') or ''}"[:200])
        except Exception as exc:  # noqa: BLE001
            say("comments", "failed", f"后台补评论没拉起来：{errtext(exc)}"[:200])
    failed = [s for s in stages if s["state"] == "failed"]
    partial = [s for s in stages if s["state"] == "partial"]
    if reader_down:
        message = f"{READER_MESSAGE}：{blocked_why}"
    elif blocked_why:
        message = f"先处理小红书：{blocked_why}；处理好再点一次「一键装好 / 跑完」"
    elif failed:
        message = "跑完了，有 " + str(len(failed)) + " 步没成：" + "；".join(f"{s['label']}（{s['text']}）" for s in failed)[:300]
    elif login_wait:
        # 1104（审查 8）：「准备好了、等扫码」不是「都跑完了」——同步还一篇没做
        message = "装好了，还没同步：" + LOGIN_WAIT_TEXT
    else:
        message = "都跑完了" + ("（轻量版）" if not ({"ai_text", "ai_vision"} & set(sel)) else "")
        if partial:
            message += "；" + "、".join(s["label"] for s in partial) + "只做了一部分，再点一次接着做"
        if xhs_off:
            message += "；没登小红书，只整理了库里已有的。B 站收藏在「收藏与同步 → B 站」点「立即同步」"
    if needs_you:
        message += "；" + "；".join(x["text"] for x in needs_you)
    if notes:
        message += "；" + "；".join(notes)
    return {"type": "result", "ok": not failed and not blocked_why, "code": blocked_code,
            "message": message, "stages": stages, "needs_you": needs_you, "selected": sel,
            "synced": any(s["id"] == "sync" and s["state"] in ("ok", "partial") for s in stages)}


def _bili_logged_in() -> bool:
    """B 站登过（本机有 cookie 文件就算；不联网）。"""
    try:
        from ..sources.bilibili import login
        return login.has_cookies()
    except Exception:  # noqa: BLE001
        return False


def _account_state() -> tuple[str, str]:
    """('', '') = 号能用；否则 (码, 一句该做什么)。没装读取组件也在这里说。"""
    from .. import comment_fill
    try:
        code, why = comment_fill.account_wait_reason()
    except Exception as exc:  # noqa: BLE001 - DEV_COPY_BLOCKED 等
        return "BLOCKED", str(exc)
    if code == "NOT_INSTALLED":
        return code, "没装读取组件：点「重试」会再装一次（或按 README 手动装）"
    if code in READER_DOWN_CODES:
        # 1102：读取服务没起来（被杀毒软件隔离 / 端口被占 / 刚崩了）不是号的事：不引导扫码，给日志路径
        from ..sources.xiaohongshu import accounts
        return code, f"读取服务没连上（{code}）：点「重试」会再拉起一次；还不行看 {accounts.home() / 'reader.log'}"
    return code, why
