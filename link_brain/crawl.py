"""交替抓取（1016）：像人一样「看一会儿收藏、翻一会儿评论」，把收藏和评论慢慢抓全。

她的要求：收藏要抓全（用户中位数几千篇）——先抓新增，再抓以前的；补评论和看收藏间歇进行；同一种行为别连着猛做。
做法：按固定轮换跑现成的命令（每块都有自己的账号锁、限频、熔断判断，这里只排班）：

    新收藏（增量，读列表；两次读列表隔 ≥ FAV_LIST_GAP_MIN 分钟）→ 补评论 → 旧收藏积压（按全量名单，不读列表）→ 补评论 → …

- 每块限时（--fav-min / --comments-min），块与块之间歇 1–3 分钟；累计干满 WORK_MIN 分钟强制歇 REST_MIN 分钟；
- 某一种行为反复被拦（actionlog.repeat_pause）就跳过那一块，其他块照跑；
- 任何一块退出码 5（号要人处理：风控 / 掉登录 / 熔断）→ 整个停下，等她处理；
- 夜跑在跑或快开始（comment_fill.nightly_busy）→ 让路；
- 进度写 `~/.link-brain/crawl-status.json`，实时终端（`python -m link_brain watch`）读它。

只排班，不碰号的细节：真正开页的仍是 sync-favorites / comments --fill-pending，它们的节奏（篇间 60–180 秒、楼中楼闸）照旧。
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import actionlog, storage

STATUS_FILE = "crawl-status.json"
FAV_LIST_GAP_MIN = 35  # 读收藏列表：读取服务 10 分钟限一次，自律 ≥ 30 分钟（0925 连读 10 次弹过滑块）

# 轮换：(块名, 行为种类, 命令参数)。{m} 换成这一块的分钟数。
ROTATION: list[tuple[str, str, list[str]]] = [
    ("fav_new", "favorites", ["sync-favorites", "--limit", "0", "--budget-min", "{m}", "--wait-lock-min", "5"]),
    ("comments", "comments", ["comments", "--fill-pending", "--budget-min", "{m}", "--wait-lock-min", "5"]),
    ("fav_backlog", "note", ["sync-favorites", "--from-snapshot", "--limit", "0", "--budget-min", "{m}", "--wait-lock-min", "5"]),
    ("comments", "comments", ["comments", "--fill-pending", "--budget-min", "{m}", "--wait-lock-min", "5"]),
]
BLOCK_CN = {"fav_new": "抓新收藏", "fav_backlog": "补以前的收藏", "comments": "补评论"}


def status_path() -> Path:
    from . import accounts
    return accounts.home() / STATUS_FILE


def write_status(**fields: Any) -> None:
    try:
        p = status_path()
        data: dict[str, Any] = {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        data.update(fields, updated_at=datetime.now().astimezone().isoformat(timespec="seconds"), pid=os.getpid())
        storage.atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1))
    except OSError:
        pass


def read_status() -> dict[str, Any]:
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _run_block(argv: list[str], block: str) -> int:
    env = {**os.environ, "LWA_TRIGGER": f"crawl:{block}", "PYTHONIOENCODING": "utf-8"}
    return subprocess.call([sys.executable, "-m", "link_brain", *argv], env=env)


def plan_block(i: int, *, last_list_read: float | None, now: float) -> int:
    """第 i 轮该跑轮换里的哪一块：读列表的块离上次读列表不到 FAV_LIST_GAP_MIN 分钟就往后挪（纯逻辑）。"""
    for k in range(len(ROTATION)):
        j = (i + k) % len(ROTATION)
        if ROTATION[j][0] == "fav_new" and last_list_read is not None and now - last_list_read < FAV_LIST_GAP_MIN * 60:
            continue
        return j
    return (i + 1) % len(ROTATION)


def run(args, *, sleep: Callable[[float], None] = time.sleep, run_block: Callable[[list[str], str], int] = _run_block,
        clock: Callable[[], float] = time.monotonic, busy: Callable[[], str] | None = None) -> int:
    from . import comment_fill
    busy = busy or comment_fill.nightly_busy
    work_min, rest_min = comment_fill.WORK_MIN, comment_fill.REST_MIN
    start = clock()
    stop_at = start + float(args.hours) * 3600 if getattr(args, "hours", 0) else None
    i, worked, last_list_read = 0, 0.0, None
    history: list[dict[str, Any]] = []
    write_status(state="running", started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                 block="", message="开始交替抓取", history=[])

    def nap(seconds: float, state: str, message: str) -> None:
        write_status(state=state, block="", message=message,
                     resume_at=datetime.fromtimestamp(time.time() + seconds).astimezone().isoformat(timespec="seconds"))
        print(f"[crawl] {datetime.now():%H:%M:%S} {message}", file=sys.stderr, flush=True)
        sleep(seconds)

    exit_code = 0
    while stop_at is None or clock() < stop_at:
        why = busy()
        if why:
            nap(300, "waiting", why)
            continue
        if worked >= work_min * 60:
            worked = 0.0
            nap(rest_min * 60, "resting", f"连着抓了 {work_min} 分钟，像人一样歇 {rest_min} 分钟")
            continue
        j = plan_block(i, last_list_read=last_list_read, now=clock())
        block, action, argv = ROTATION[j]
        i = j + 1
        rp_why, _ = actionlog.repeat_pause(action)
        if rp_why:
            history.append({"block": block, "skipped": rp_why})
            write_status(history=history[-20:])
            print(f"[crawl] 跳过「{BLOCK_CN[block]}」：{rp_why}", file=sys.stderr, flush=True)
            if all(actionlog.repeat_pause(a)[0] for _, a, _ in ROTATION):
                nap(1800, "waiting", "每种行为都在暂停期，半小时后再看")
            continue
        minutes = int(args.fav_min if block.startswith("fav") else args.comments_min)
        cmd = [a.replace("{m}", str(minutes)) for a in argv]
        write_status(state="running", block=block, message=f"{BLOCK_CN[block]}（最多 {minutes} 分钟）", resume_at="")
        print(f"[crawl] {datetime.now():%H:%M:%S} → {BLOCK_CN[block]}（最多 {minutes} 分钟）", file=sys.stderr, flush=True)
        t0 = clock()
        code = run_block(cmd, block)
        spent = clock() - t0
        worked += spent
        if block == "fav_new":
            last_list_read = clock()
        history.append({"block": block, "exit": code, "minutes": round(spent / 60, 1),
                        "at": datetime.now().astimezone().isoformat(timespec="seconds")})
        write_status(history=history[-20:])
        if code == 5:
            write_status(state="stopped", block="", message="号要你处理（风控 / 掉登录 / 熔断），交替抓取先停；处理好再开")
            exit_code = 5
            break
        if code == 6:
            nap(300, "waiting", "号被别的任务占着，5 分钟后再排")
            continue
        nap(random.uniform(60, 180), "resting", f"{BLOCK_CN[block]}做完（退出码 {code}），换下一件前歇一下")
    else:
        write_status(state="done", block="", message="到点了，交替抓取结束")
    return exit_code
