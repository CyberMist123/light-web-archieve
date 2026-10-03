"""每晚夜跑（第 5 批：从仓外的 Windows 夜跑脚本搬进包里）：`python -m link_brain nightly`。

一晚上按 STEPS 的顺序跑一串 `python -m link_brain …` 子命令，规矩和原来的脚本一致：

- 每一步是带时限的子进程：输出边跑边逐行追加进日志（行首带时刻）；超时只结束这一步的整棵进程树
  （`procs.kill_tree`：读取服务 link-brain-reader 和它下面的浏览器一律放过，绝不 taskkill /T），记「超时」，接着跑下一步。
- 总预算（默认 405 分钟，计划任务执行时限 7 小时留 15 分钟收尾）：快到点时后面的步骤自动缩短 / 跳过，
  保证日志最后一定写得出「=== 夜跑结束 ===」。
- 开头：收藏同步正在跑（sync-status.json state=running 且 pid 是个活着的 python、不是被复用的 pid）就记一行直接退出；
  它占着号又很久没进展（默认 180 分钟）→ 登记 NEEDS_HUMAN.SYNC_STUCK。上一晚日志没有「=== 夜跑结束 ===」
  （被系统强停 / 断电）→ 登记 TRANSIENT.INTERRUPTED。
- 碰号的步骤退出 5（号要人处理：风控 / 掉登录 / 熔断）→ 之后所有碰号步骤一律跳过，只跑离线步骤；
  碰号步骤退出 6（号被别的任务占着）→ 登记 TRANSIENT.ACCOUNT_BUSY。
- 任何一步超时 / 崩溃 / 出错 / 参数不认：登记进问题记录（step = `nightly.<步骤>`，CONVENTIONS §2）；成功（0 / 2）就把这一步
  以前的问题标已解决。报警不直调：推不推由 problems 判（NEEDS_HUMAN 推一次、TRANSIENT 连续 3 天升级）。
- 收藏同步退出 1（不是风控 / 掉登录，例如机器卡导致登录检查超时）：等 25 分钟再试一次（读收藏有 10 分钟限频）；
  5 / 6 / 超时 / 参数不认不重试；剩的时间不够也不试。
- 精细识图（vision --refine）的免费 key：只从环境变量（变量名 = 设置 visionAI.refineKeysEnv，默认 LWA_GEMINI_KEYS）、
  或 `~/.link-brain/config.json` 的 `gemini_keys_cmd`（一条命令，标准输出就是 key，逗号 / 换行分隔；限时 60 秒，
  输出不进日志）/ `gemini_keys_file`（key 文件）拿；只注入这一步的子进程环境。都没有就照跑（退回设置里的识图模型）。
- 收尾：附件闸门（attachments --audit，不联网）还缺附件 → 退出 2。

退出码：0 全部正常 · 1 有步骤出问题（都已登记）· 2 还缺附件 · 5 号要人处理（今晚跳过了碰号步骤）· 6 另一趟夜跑正在跑。
日志：`~/.link-brain/nightly.log`（`LINK_BRAIN_HOME` 可改；超过 10 MB 开跑前转存为 nightly.log.1）。
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import procs, storage

# ---------------------------------------------------------------- 参数（默认值照原来的夜跑脚本）

BUDGET_MIN = 405          # 计划任务执行时限 7 小时（420 分钟），留 15 分钟给收尾
TASK_LIMIT_HOURS = 7      # 计划任务的 ExecutionTimeLimit（sync_schedule.install 用）
STUCK_MIN = 180           # 收藏同步 running 但这么多分钟没进展 → 登记「像是卡住了」（要人处理）
SYNC_RETRY_WAIT_MIN = 25  # 收藏同步非风控失败（exit 1）后等多久再试一次
SECRET_TIMEOUT_SEC = 60   # 取 key 的命令最多等多久（密码库卡住也不能拖死整晚）
PIPE_GRACE_SEC = 5        # 进程退了但孙进程还攥着输出管道：最多再等这么久
LOG_ROTATE_BYTES = 10 * 1024 * 1024
TAIL_BYTES = 4 * 1024 * 1024  # 判断「上一晚没走完」只看日志最后这么多

START_MARK = "=== 夜跑开始 ==="
END_MARK = "=== 夜跑结束 ==="

# 超时杀树时放过的映像名前缀：读取服务（procs 默认）+ 上游 xiaohongshu-mcp 的服务 / 登录程序。
# 本机还有别的要放过的程序：环境变量 LINK_BRAIN_KILL_EXCLUDE（逗号分隔的映像名前缀）追加。
KILL_EXCLUDE = (*procs.READER_IMAGE_PREFIXES, "xiaohongshu-mcp", "xiaohongshu-login")

EXIT_OK, EXIT_ERROR, EXIT_MISSING, EXIT_NEEDS_HUMAN, EXIT_BUSY = 0, 1, 2, 5, 6

SYNC_STEP = "sync-favorites"
REFINE_STEP = "vision --refine"
AUDIT_STEP = "attachments --audit"
KEYS_STEP = "gemini-keys"  # 取免费 key 单独记一步：精细识图没 key 照样成功，别把「取 key 失败」顺手标成已解决


@dataclass
class Step:
    name: str                    # 日志 / 问题记录里的名字（slug 后 = nightly.<名>，和原脚本一致，问题记录接得上）
    args: list[str]              # `python -m link_brain` 后面的参数
    timeout_min: float           # 这一步的时限
    account: bool = False        # 碰号：碰号步骤退出 5 之后跳过
    reserve_min: float = 15      # 给后面收尾步骤留的分钟数（总预算不够时本步自动缩短）
    quiet_stdout: bool = False   # 标准输出不进日志（大 JSON）
    argv: list[str] | None = None  # 测试 / 特殊用途：整条命令行（给了就不拼 python -m link_brain）

    def command(self, python: str) -> list[str]:
        return list(self.argv) if self.argv else [python, "-m", "link_brain", *self.args]


def default_steps() -> list[Step]:
    return [
        # 1) 收藏同步：只抓取 + 本地渲染（不调模型），到 150 分钟优雅收尾；超 170 分钟才杀
        Step(SYNC_STEP, ["sync-favorites", "--limit", "0", "--budget-min", "150"], 170, account=True),
        # 2) 目录页：就算同步出错也重写一次（库里可能已经落了几篇新的）
        Step("catalog", ["catalog"], 10),
        # 3) 附件补下 / 4) 附件补查：碰号。--budget-min 比时限少 5 分钟，Python 自己收手，不在下载半路被杀
        Step("attachments --all", ["attachments", "--all", "--budget-min", "30"], 35, account=True),
        Step("attachments --recheck", ["attachments", "--recheck", "--limit", "20", "--budget-min", "20"], 25,
             account=True),
        # 5) 识图 + 概要：只对本地已存的原文跑，不碰号
        Step("enrich --pending", ["enrich", "--pending", "--budget-min", "60"], 70),
        # 6) 识图第一层补跑
        Step("vision --upgrade", ["vision", "--upgrade", "--limit", "30"], 45),
        # 7) 识图第二层（免费 key 只注入这一步）
        Step(REFINE_STEP, ["vision", "--refine", "--limit", "0"], 35),
        # 8) 视频转写
        Step("videos --transcribe", ["videos", "--all", "--transcribe"], 25),
        # 9) 语义索引：放在内容都更新完之后，向量才不落后一天
        Step("embed", ["embed"], 25, reserve_min=10),
        # 10) 目录页再重写一次（带上今晚补好的角标）
        Step("catalog（收尾）", ["catalog"], 10, reserve_min=3),
        # 11) 附件闸门：不联网，只数还缺几个
        Step(AUDIT_STEP, ["attachments", "--audit"], 5, reserve_min=0, quiet_stdout=True),
    ]


STEPS: list[Step] = default_steps()


def step_slug(name: str) -> str:
    """'attachments --all' → 'attachments-all'，'catalog（收尾）' → 'catalog-final'（和原脚本 Get-StepSlug 一致）。"""
    s = re.sub(r"[^A-Za-z0-9]+", "-", name.replace("（收尾）", "-final"))
    return s.strip("-").lower()


def default_log_path() -> Path:
    return storage.link_brain_home() / "nightly.log"


def kill_exclude() -> tuple[str, ...]:
    extra = [x.strip() for x in os.environ.get("LINK_BRAIN_KILL_EXCLUDE", "").split(",") if x.strip()]
    return (*KILL_EXCLUDE, *extra)


@dataclass
class StepResult:
    name: str
    code: int | None = None
    timed_out: bool = False
    skipped: bool = False
    error: str | None = None
    traceback: bool = False
    usage_error: bool = False
    minutes: float = 0.0
    stdout: list[str] = field(default_factory=list)


_USAGE_RE = re.compile(r": error: (unrecognized arguments|argument )")


def _read_lines(stream, tag: str, out: queue.Queue) -> None:
    try:
        for raw in iter(stream.readline, b""):
            out.put((tag, raw.decode("utf-8", "replace").rstrip("\r\n")))
    except (OSError, ValueError):
        pass
    finally:
        out.put((tag, None))


class Nightly:
    def __init__(self, *, steps: list[Step] | None = None, budget_min: float = BUDGET_MIN,
                 log_path: Path | str | None = None, python: str | None = None,
                 stuck_min: float = STUCK_MIN, sync_retry_wait_min: float = SYNC_RETRY_WAIT_MIN,
                 secret_timeout_sec: float = SECRET_TIMEOUT_SEC, workdir: Path | str | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.steps = list(STEPS if steps is None else steps)
        self.budget_min = float(budget_min)
        self.log_path = Path(log_path) if log_path else default_log_path()
        self.python = python or sys.executable
        self.stuck_min = float(stuck_min)
        self.sync_retry_wait_min = float(sync_retry_wait_min)
        self.secret_timeout_sec = float(secret_timeout_sec)
        self.workdir = Path(workdir) if workdir else storage.link_brain_home()
        self.clock = clock
        self.sleep = sleep
        self.deadline = clock() + self.budget_min * 60
        self.account_stop = False
        self.account_stop_why = ""
        self.problems: list[str] = []
        self.vault = storage.vault_root()
        self.run_id: str | None = None   # 10-03 同步记录：这一晚那行的编号（每一步子进程带着它，结果并进同一行）

    # ------------------------------------------------------------ 日志
    def _write(self, text: str) -> None:
        # 每行单独开关文件（别长期占着句柄）；写不进去重试两次，再不行就算了（日志不能拖死夜跑）
        for _ in range(3):
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8", newline="") as fh:
                    fh.write(text + "\r\n")
                return
            except OSError:
                time.sleep(0.2)

    def log(self, message: str) -> None:
        self._write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}")

    def _line(self, text: str) -> None:
        self._write(f"{datetime.now():%H:%M:%S}  {text}")

    # ------------------------------------------------------------ 问题记录（进程内调 problems，失败只记日志）
    def register(self, step_name: str, code: str, reason: str) -> None:
        self.problems.append(reason)
        if self.run_id:
            try:
                from . import synclog
                synclog.error("nightly." + step_slug(step_name), reason, code)
                synclog.flush()
            except Exception as exc:  # noqa: BLE001
                self.log(f"[同步记录] 没写进去（{type(exc).__name__}: {exc}）")
        try:
            from . import problems
            row = problems.report("nightly." + step_slug(step_name), code, reason)
            if not row.get("written", True):
                self.log(f"[问题记录] 没写进去：{reason}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[问题记录] 没写进去（{type(exc).__name__}: {exc}）：{reason}")

    def resolve(self, step_name: str) -> None:
        try:
            from . import problems
            problems.resolve("nightly." + step_slug(step_name))
        except Exception as exc:  # noqa: BLE001
            self.log(f"[问题记录] 标已解决失败（{type(exc).__name__}: {exc}）：{step_name}")

    # ------------------------------------------------------------ 子进程
    def _env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"   # 子进程逐行吐，日志才是实时的
        env[storage.ENV_VAULT] = str(self.vault)  # 每一步都用同一个收藏库，不各自再猜
        if self.run_id:
            from . import synclog
            env[synclog.ENV_RUN] = self.run_id
        if extra:
            env.update(extra)
        return env

    def minutes_left(self) -> float:
        return (self.deadline - self.clock()) / 60

    def run_step(self, step: Step, *, env_extra: dict[str, str] | None = None) -> StepResult:
        r = StepResult(step.name)
        if step.account and self.account_stop:
            r.skipped = True
            self.log(f"[{step.name}] 跳过（碰号）：{self.account_stop_why}")
            return r
        left = self.minutes_left() - step.reserve_min
        if left < 2:
            r.skipped = True
            self.log(f"[{step.name}] 跳过：今晚总时间用完了")
            self.register(step.name, "TRANSIENT.STEP_TIMEOUT", f"{step.name} 没跑（总时间用完）")
            return r
        limit = min(step.timeout_min, left)
        self.log(f"=== {step.name} 开始（限时 {limit:.1f} 分钟）===")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            p = subprocess.Popen(step.command(self.python), cwd=str(self.workdir), env=self._env(env_extra),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=flags)
        except OSError as exc:
            r.error = f"{type(exc).__name__}: {exc}"
            self.log(f"[{step.name}] 起不来：{r.error}")
            self.register(step.name, "TRANSIENT.STEP_CRASHED", f"{step.name} 起不来：{r.error}")
            return r

        lines: queue.Queue = queue.Queue()
        for stream, tag in ((p.stdout, "out"), (p.stderr, "err")):
            threading.Thread(target=_read_lines, args=(stream, tag, lines), daemon=True).start()
        started = time.monotonic()
        limit_s = limit * 60
        open_streams = {"out", "err"}
        exit_at: float | None = None
        while open_streams:
            try:
                tag, line = lines.get(timeout=0.5)
            except queue.Empty:
                tag = line = None
            while tag is not None:
                if line is None:
                    open_streams.discard(tag)
                elif tag == "out":
                    r.stdout.append(line)
                    if not step.quiet_stdout:
                        self._line(line)
                else:
                    if "Traceback (most recent call last)" in line:
                        r.traceback = True
                    # argparse 不认参数也是 exit 2，别和「缺内容闸门」的 2 混成正常
                    if _USAGE_RE.search(line):
                        r.usage_error = True
                    self._line(line)
                try:
                    tag, line = lines.get_nowait()
                except queue.Empty:
                    tag = line = None
            if not open_streams:
                break
            now = time.monotonic()
            if not r.timed_out and now - started > limit_s:
                r.timed_out = True
                self.log(f"[{step.name}] 超时（{limit:.1f} 分钟），结束这一步的整棵进程树（放过读取服务），接着跑下一步")
                self._kill(p, step.name)
                exit_at = time.monotonic()
            if exit_at is None and p.poll() is not None:
                exit_at = now
            if exit_at is not None and time.monotonic() - exit_at > PIPE_GRACE_SEC:
                break  # 孙进程还攥着管道：不等了（读线程是 daemon，随它去）
        if p.poll() is None and not r.timed_out:
            # 管道先关了但进程还没退（少见）：在剩下的时限里接着等，到点照样杀
            remain = max(0.0, limit_s - (time.monotonic() - started))
            try:
                p.wait(timeout=remain)
            except subprocess.TimeoutExpired:
                r.timed_out = True
                self.log(f"[{step.name}] 超时（{limit:.1f} 分钟），结束这一步的整棵进程树（放过读取服务），接着跑下一步")
                self._kill(p, step.name)
        if p.poll() is None:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        if p.poll() is not None and not r.timed_out:
            r.code = p.returncode
        r.minutes = round((time.monotonic() - started) / 60, 1)
        self._classify(step, r, limit)
        return r

    def _kill(self, p: subprocess.Popen, name: str) -> None:
        try:
            killed = procs.kill_tree(p.pid, exclude=kill_exclude())
        except Exception as exc:  # noqa: BLE001
            self.log(f"[{name}] 结束进程树出错（{type(exc).__name__}: {exc}），只结束这一步本身")
            killed = []
        try:
            p.kill()
        except OSError:
            pass
        self.log(f"[{name}] 已结束 {len(killed)} 个进程")

    def _classify(self, step: Step, r: StepResult, limit: float) -> None:
        name = step.name
        if r.timed_out:
            self.register(name, "TRANSIENT.STEP_TIMEOUT", f"{name} 超时（{limit:.1f} 分钟被停）")
            self.log(f"=== {name} 结束：超时被停（用了 {r.minutes} 分钟）===")
        else:
            self.log(f"=== {name} 结束 exit={r.code}（{r.minutes} 分钟）===")
            # 统一退出码：0 成功/部分完成、1 出错、2 缺内容闸门、5 要人处理、6 号被别的任务占着
            # Traceback 只在退出码也不正常时才算崩溃（逐篇 print_exc 之后照样 exit 0 的不误报）
            abnormal = r.code not in (0, 2, 5, 6)
            if r.traceback and abnormal:
                self.register(name, "TRANSIENT.STEP_CRASHED", f"{name} 崩溃（exit={r.code}，日志里有 Traceback）")
            elif r.usage_error:
                self.register(name, "PERMANENT.STEP_ARGS", f"{name} 参数不认（exit={r.code}，程序版本对不上？）")
            elif abnormal:
                self.register(name, "TRANSIENT.STEP_CRASHED", f"{name} 出错（exit={r.code}）")
            elif step.account and r.code == 6:
                self.register(name, "TRANSIENT.ACCOUNT_BUSY", f"{name} 没拿到号（exit 6：号被别的任务占着，这一步今晚没做）")
            elif r.code in (0, 2):
                self.resolve(name)
        if step.account and r.code == 5:
            self.account_stop = True
            self.account_stop_why = f"{name} 退出 5（号要人处理：风控/掉登录/熔断），今晚不再开页"
            self.log(f"[护号] {self.account_stop_why}")

    # ------------------------------------------------------------ 开头的两项检查
    def unfinished_last_night(self) -> dict[str, str] | None:
        """日志里最后一个「夜跑开始」后面没有「夜跑结束」= 上一晚被系统强停 / 断电。返回 {start, last}。"""
        try:
            with open(self.log_path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - TAIL_BYTES))
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            return None
        lines = text.splitlines()
        start = next((i for i in range(len(lines) - 1, -1, -1) if START_MARK in lines[i]), -1)
        if start < 0:
            return None
        if any(END_MARK in ln for ln in lines[start + 1:]):
            return None
        last = next((ln.strip() for ln in reversed(lines[start + 1:]) if ln.strip()), "")
        return {"start": lines[start].strip(), "last": last}

    def running_sync(self) -> dict[str, Any] | None:
        """插件点的同步 / 上一趟还在跑：sync-status.json state=running 且 pid 是个活着的 python。
        防 pid 复用：那个进程的启动时刻不能晚于状态文件的 updated_at（同步每步都刷新它）。返回 {pid, idle_min}。"""
        from . import sync_state
        st = sync_state._read_raw()
        if st.get("state") != "running" or not st.get("pid"):
            return None
        try:
            pid = int(st["pid"])
            table = procs.process_table()
        except (TypeError, ValueError, OSError):
            return None
        except Exception:  # noqa: BLE001 - 枚举进程失败：当没在跑（宁可多跑一趟，号锁会兜住）
            return None
        proc = next((p for p in table if int(p["pid"]) == pid), None)
        if not proc or not str(proc.get("name") or "").lower().startswith("python"):
            return None
        updated = None
        try:
            updated = datetime.fromisoformat(str(st.get("updated_at"))).timestamp() if st.get("updated_at") else None
        except ValueError:
            updated = None
        idle = None
        if updated is not None:
            created = proc.get("created")
            if created is not None and created > updated + 5:
                self.log(f"[夜跑] sync-status 说 pid {pid} 在同步，但那个进程比状态最后更新还晚起：pid 被复用了，照常跑")
                return None
            idle = (time.time() - updated) / 60
        return {"pid": pid, "idle_min": idle}

    # ------------------------------------------------------------ 免费 key（只注入精细识图那一步）
    def _keys_env_name(self) -> str:
        try:
            from . import vision
            return vision._refine_keys_env()
        except Exception:  # noqa: BLE001
            return "LWA_GEMINI_KEYS"

    def refine_keys(self) -> tuple[str, list[str]]:
        """(变量名, key 列表)。环境变量已有就用它；否则 config.json 的 gemini_keys_cmd → gemini_keys_file。key 不进日志。"""
        name = self._keys_env_name()
        have = [k.strip() for k in os.environ.get(name, "").split(",") if k.strip()]
        if have:
            return name, have
        cfg = storage.user_config()
        cmd = os.environ.get("LWA_GEMINI_KEYS_CMD") or cfg.get("gemini_keys_cmd")
        path = os.environ.get("LWA_GEMINI_KEYS_FILE") or cfg.get("gemini_keys_file")
        text = ""
        if isinstance(cmd, str) and cmd.strip():
            text = self._run_secret_cmd(cmd.strip())
        elif isinstance(path, str) and path.strip():
            try:
                text = Path(os.path.expandvars(path.strip())).expanduser().read_text("utf-8-sig")
            except OSError as exc:
                self.log(f"[识图补跑] key 文件读不了（{type(exc).__name__}），这晚没 key 照跑")
        keys = [k.strip() for k in re.split(r"[,\r\n]+", text or "") if k.strip() and not k.strip().startswith("#")]
        return name, keys

    def _run_secret_cmd(self, cmd: str) -> str:
        """跑取 key 的命令：输出一律不进日志；限时，超时整棵结束（放过读取服务）并登记 SECRET_TIMEOUT。"""
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            p = subprocess.Popen(cmd, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError as exc:
            why = f"起不来：{type(exc).__name__}"
            self.log(f"[识图补跑] 取免费 key 的命令{why}；这晚没 key 照跑")
            self.register(KEYS_STEP, "TRANSIENT.SECRET_TIMEOUT", f"取免费 key 失败（{why}）")
            return ""
        try:
            out, _ = p.communicate(timeout=self.secret_timeout_sec)
        except subprocess.TimeoutExpired:
            self._kill(p, "取免费 key")
            why = f"{self.secret_timeout_sec:.0f} 秒没回来，已停"
            self.log(f"[识图补跑] 取免费 key 的命令{why}；这晚没 key 照跑")
            self.register(KEYS_STEP, "TRANSIENT.SECRET_TIMEOUT", f"取免费 key 失败（{why}，密码库卡住了？）")
            return ""
        if p.returncode != 0:
            self.log(f"[识图补跑] 取免费 key 的命令退出 {p.returncode}；这晚没 key 照跑")
            self.register(KEYS_STEP, "TRANSIENT.SECRET_TIMEOUT", f"取免费 key 失败（命令退出 {p.returncode}）")
            return ""
        self.resolve(KEYS_STEP)
        return (out or b"").decode("utf-8", "replace")

    # ------------------------------------------------------------ 特殊步骤
    def _sync_with_retry(self, step: Step) -> StepResult:
        r = self.run_step(step)
        if r.code == 6:
            self.log("[护号] 号被别的任务占着（导入 / 插件同步），同步这次没拿到号")
        elif r.code == 1 and not r.timed_out and not r.usage_error:
            if self.minutes_left() > self.sync_retry_wait_min + 60:
                self.log(f"[同步] 不是风控的失败（exit 1），{self.sync_retry_wait_min:g} 分钟后自动再试一次")
                first = len(self.problems)
                self.sleep(self.sync_retry_wait_min * 60)
                r = self.run_step(step)
                if r.code == 0:
                    # 重试成功：第一次那条汇总行撤掉（问题记录里已经 resolve）
                    self.problems = [p for i, p in enumerate(self.problems)
                                     if not (i < first and p.startswith(step.name + " "))]
                    self.log("[同步] 再试一次成功")
            else:
                self.log("[同步] 不是风控的失败（exit 1），但今晚剩的时间不够再试一次")
        return r

    def _refine(self, step: Step) -> StepResult:
        name, keys = self.refine_keys()
        self.log(f"[识图补跑] 免费 key 可用 {len(keys)} 个")
        r = self.run_step(step, env_extra={name: ",".join(keys)} if keys else None)
        summary = _last_json(r.stdout)
        if isinstance(summary, dict):
            models = "，".join(f"{k}×{v}" for k, v in (summary.get("models") or {}).items())
            self.log(f"[识图补跑] 本晚补好 {summary.get('refined')} 张，放弃 {summary.get('failed')} 张，"
                     f"还剩 {summary.get('pending_left')} 张待补，花费 ¥{summary.get('cost_yuan')}（{models}）")
        return r

    def _audit(self, step: Step) -> tuple[StepResult, bool]:
        r = self.run_step(step)
        missing = False
        data = _json_from_first_brace(r.stdout)
        if data is None:
            if any(x.strip() for x in r.stdout):
                self.log("[附件检查] 结果不是 JSON：" + "\n".join(r.stdout).strip()[:160])
            return r, False
        if (data.get("missing") or 0) > 0:
            unconfirmed = data.get("unconfirmed") or 0
            self.log(f"[附件检查] 未下载 {data['missing'] - unconfirmed} 个文件，另有 {unconfirmed} 条附件线索待确认；"
                     "在目录点击待补标识处理")
            missing = True
        else:
            self.log("[附件检查] 已知附件全部已保存")
        if (data.get("unprobed") or 0) > 0:
            self.log(f"[附件检查] 还有 {data['unprobed']} 篇没查清原网页有没有附件（每晚补查 20 篇）")
        else:
            self.log("[附件检查] 每篇原网页都查过附件了")
        return r, missing

    # ------------------------------------------------------------ 主流程
    def run(self) -> dict[str, Any]:
        running = self.running_sync()
        if running:
            self.log(f"[夜跑] 收藏同步正在跑（pid {running['pid']}，插件或上一趟），今晚不再起，也不碰它的浏览器")
            idle = running.get("idle_min")
            if idle is not None and idle > self.stuck_min:
                hours = round(idle / 60, 1)
                self.log(f"[夜跑] 它已经 {hours} 小时没有进展，像是卡住了：登记要人处理")
                self.register("run", "NEEDS_HUMAN.SYNC_STUCK",
                              f"有个收藏同步（pid {running['pid']}）占着号 {hours} 小时没进展，今晚夜跑没起。"
                              "重启 Obsidian 或结束这个 python 进程后，下一晚会接着收。")
            return self._result(EXIT_OK, "收藏同步正在跑，今晚夜跑没起", ran=False)

        unfinished = self.unfinished_last_night()
        self._rotate()
        self.log(START_MARK)
        self.log(f"[夜跑] 收藏库：{self.vault}；总预算 {self.budget_min:g} 分钟")
        try:
            from . import synclog
            # 夜跑自己是一次同步；外面给了编号（仓外脚本包着它）就用那个
            self.run_id = synclog.begin(own=True, run_id=os.environ.get(synclog.ENV_RUN) or None)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[同步记录] 没开上（{type(exc).__name__}: {exc}）")
        if unfinished:
            self.log(f"[夜跑] 上一晚没走完：{unfinished['start']}；日志停在「{unfinished['last']}」")
            self.register("run", "TRANSIENT.INTERRUPTED",
                          f"上一晚收藏夜跑没走完：开始于 {unfinished['start']}，没有「夜跑结束」这一行（被系统强停或断电）。"
                          f"日志最后一行：{unfinished['last'][:160]}")
        exit_code = EXIT_OK
        try:
            for step in self.steps:
                if step.name == SYNC_STEP:
                    self._sync_with_retry(step)
                elif step.name == REFINE_STEP:
                    self._refine(step)
                elif step.name == AUDIT_STEP:
                    _, missing = self._audit(step)
                    if missing and exit_code == EXIT_OK:
                        exit_code = EXIT_MISSING
                else:
                    self.run_step(step)
        except Exception as exc:  # noqa: BLE001 - 夜跑自己出错也要写得出「夜跑结束」
            self.register("run", "TRANSIENT.STEP_CRASHED", f"夜跑自己出错：{type(exc).__name__}: {exc}")
            self.log(f"[夜跑] 出错：{type(exc).__name__}: {exc}")
        finally:
            if self.account_stop:
                exit_code = EXIT_NEEDS_HUMAN
            elif self.problems:
                exit_code = EXIT_ERROR
            if self.problems:
                self.log(f"[夜跑] 有问题的步骤：{'；'.join(self.problems)}（已登记进问题记录，不推送）")
            self.log(f"[夜跑] 汇总 exit={exit_code}")
            if self.run_id:
                try:
                    from . import synclog
                    synclog.end(self.run_id, exit_code=exit_code)
                except Exception as exc:  # noqa: BLE001
                    self.log(f"[同步记录] 没收上尾（{type(exc).__name__}: {exc}）")
            self.log(END_MARK)
        message = {EXIT_OK: "夜跑完成", EXIT_MISSING: "夜跑完成，还有附件没下全",
                   EXIT_NEEDS_HUMAN: "号要人处理，今晚跳过了碰号的步骤",
                   EXIT_ERROR: "夜跑完成，有步骤出了问题（已登记进问题记录）"}[exit_code]
        return self._result(exit_code, message, ran=True)

    def _result(self, exit_code: int, message: str, *, ran: bool) -> dict[str, Any]:
        return {"ok": exit_code in (EXIT_OK, EXIT_MISSING), "code": "", "message": message, "exit": exit_code,
                "ran": ran, "problems": list(self.problems), "log": str(self.log_path)}

    def _rotate(self) -> None:
        try:
            if self.log_path.stat().st_size > LOG_ROTATE_BYTES:
                os.replace(self.log_path, self.log_path.with_name(self.log_path.name + ".1"))
        except OSError:
            pass

    def plan(self) -> dict[str, Any]:
        return {"ok": True, "code": "", "message": "只打印步骤计划，没跑", "vault": str(self.vault),
                "log": str(self.log_path), "budget_min": self.budget_min, "workdir": str(self.workdir),
                "steps": [{"name": s.name, "step": "nightly." + step_slug(s.name), "argv": s.command(self.python),
                           "timeout_min": s.timeout_min, "account": s.account, "reserve_min": s.reserve_min}
                          for s in self.steps]}


def _last_json(lines: list[str]) -> Any:
    import json
    for line in reversed(lines):
        if line.lstrip().startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def _json_from_first_brace(lines: list[str]) -> dict | None:
    """从第一行以 { 开头的地方取到结尾（万一前面混了别的输出；dump_json 可能是多行缩进）。"""
    import json
    first = next((i for i, x in enumerate(lines) if x.lstrip().startswith("{")), -1)
    text = "\n".join(lines[first:] if first >= 0 else lines).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def add_parser(sub) -> None:
    p = sub.add_parser("nightly", help="每晚夜跑：同步收藏 → 目录 → 附件 → 识图 / 概要 → 转写 → 索引（计划任务调它）")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="只打印步骤计划，不跑")
    p.add_argument("--vault", help="收藏库位置（不给就按 LINK_BRAIN_VAULT → ~/.link-brain/config.json → 程序目录/vault）")
    p.add_argument("--budget-min", dest="budget_min", type=float, default=BUDGET_MIN,
                   help=f"今晚总共最多跑几分钟（默认 {BUDGET_MIN}）")
    p.add_argument("--log", help="日志文件（默认 ~/.link-brain/nightly.log）")
    p.add_argument("--retry-wait-min", dest="retry_wait_min", type=float, default=SYNC_RETRY_WAIT_MIN,
                   help=f"收藏同步非风控失败后等几分钟再试一次（默认 {SYNC_RETRY_WAIT_MIN}）")


def run(args) -> int:
    from .read import dump_json

    if sys.stdout is None or sys.stderr is None:  # pythonw（计划任务）没有控制台
        devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - 进程结束才关
        sys.stdout = sys.stdout or devnull
        sys.stderr = sys.stderr or devnull
    if getattr(args, "vault", None):
        os.environ[storage.ENV_VAULT] = str(Path(args.vault).expanduser().resolve())
    job = Nightly(budget_min=args.budget_min, log_path=getattr(args, "log", None),
                  sync_retry_wait_min=args.retry_wait_min)
    if getattr(args, "dry_run", False):
        for s in job.steps:
            print(f"{s.name}：限时 {s.timeout_min:g} 分钟{'（碰号）' if s.account else ''}", file=sys.stderr)
        dump_json(job.plan())
        return EXIT_OK
    try:
        with storage.file_lock("nightly", wait_s=0, owner="nightly"):
            result = job.run()
    except storage.LockBusy as exc:
        job.log(f"[夜跑] 另一趟夜跑正在跑，这次不起：{exc}")
        print(f"没跑：另一趟夜跑正在跑（{exc}）", file=sys.stderr)
        dump_json(job._result(EXIT_BUSY, "另一趟夜跑正在跑", ran=False) | {"ok": False})
        return EXIT_BUSY
    if result["exit"] not in (EXIT_OK, EXIT_MISSING):
        print(result["message"] + f"（详情：{result['log']}）", file=sys.stderr)
    dump_json(result)
    return int(result["exit"])
