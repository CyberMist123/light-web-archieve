"""`enrich`：给已经归档的笔记补识图 + 概要（1001）。**不碰号**：只读本地原文，调识图 / 小模型。

为什么单独一步：同步收藏只在「抓取阶段」用号（抓原文 + 本地渲染，不调模型、不识图），
新收的篇标成「待 enrich」；识图、概要放到这里慢慢补。这样：
- 抓取阶段又快又短，号用完就放（账号锁、开页节奏都只罩抓取）；
- 一篇识图卡死（0929 那晚一篇卡了 70 分钟）只卡它自己：每篇一个子进程、20 分钟上限，
  超时连同它起的子进程（OCR / 识图脚本）整棵杀掉；
- 失败记次数：前 3 次每晚都再试；连着 3 次没补成就「暂时放弃」——不推送，问题记录登记
  `TRANSIENT.RETRY_EXHAUSTED`（action=gave_up，带 next_at），按退避隔 2 / 4 / 7 天（之后每 7 天）再自动捡回来一次
  （第 4 批：以前是永久不再试，0921 起失败的几十篇就再也没人管；`--item` 点名随时可重跑）。

候选（`--pending`）：标了待 enrich 的 / 概要失败或缺失的（含从没生成过的）/ 有图没识的。标了的排前面。
状态记在对象目录 `enrich-state.json`：`{pending, fails, last_error, retry_after, updated_at}`。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import storage

SOURCE = "xiaohongshu"
MAX_FAILS = 3
GIVE_UP_BACKOFF_DAYS = (2, 4, 7)  # 第 3 / 4 / ≥5 次失败后隔几个日历日再自动试（封顶 7 天）
ITEM_TIMEOUT_SECONDS = int(os.environ.get("LWA_ENRICH_TIMEOUT", str(20 * 60)))
IMAGE_SUFFIXES = {".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif", ".heic", ".bmp"}
EXIT_OK = 0
EXIT_ERROR = 1
_CHILD_INCOMPLETE = 3  # 子进程跑完了但还缺东西（概要失败 / 有图没识出来）


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def retry_after_for(fails: int, now: datetime | None = None) -> str | None:
    """累计 fails 次失败后下次自动重试的时刻（日历日 0 点起）；还没到 MAX_FAILS = None（每晚照试）。"""
    if fails < MAX_FAILS:
        return None
    now = (now or datetime.now().astimezone()).astimezone()
    days = GIVE_UP_BACKOFF_DAYS[min(fails - MAX_FAILS, len(GIVE_UP_BACKOFF_DAYS) - 1)]
    return (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def backing_off(state: dict[str, Any], now: datetime | None = None) -> bool:
    """连着失败够 MAX_FAILS 次、还没到 retry_after：这次不自动捡。旧状态没有 retry_after = 到点了（捡回来再试一次）。"""
    if int(state.get("fails") or 0) < MAX_FAILS:
        return False
    try:
        return datetime.fromisoformat(str(state.get("retry_after"))) > (now or datetime.now().astimezone())
    except (TypeError, ValueError):
        return False


def state_path(source_key: str, source_id: str) -> Path:
    return storage.object_dir(source_key, source_id) / "enrich-state.json"


def load_state(source_key: str, source_id: str) -> dict[str, Any]:
    try:
        data = storage.read_json(state_path(source_key, source_id))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(source_key: str, source_id: str, state: dict[str, Any]) -> None:
    path = state_path(source_key, source_id)
    if not path.parent.exists():
        return
    storage.atomic_write_text(path, json.dumps({**state, "updated_at": _now()}, ensure_ascii=False, indent=2))


def mark_pending(source_key: str, source_id: str, reason: str = "新收藏") -> None:
    """抓取阶段收进来的新篇：标成待 enrich（识图 + 概要之后补）。重新抓过的篇也重新算次数。"""
    try:
        _save_state(source_key, source_id, {"pending": True, "fails": 0, "reason": reason})
    except OSError:
        pass


def _summary_configured() -> bool:
    from . import providers
    try:
        return providers.resolve("summaryAI") is not None
    except Exception:  # noqa: BLE001 - 配置读不动就当没配
        return False


def needs(source_key: str, source_id: str, *, llm: bool = True) -> list[str]:
    """这篇还缺什么：`summary`（概要失败 / 缺失，llm=True 才算）、`vision`（有图没识）。不含待 enrich 标记本身。"""
    from . import llm as llm_mod

    out: list[str] = []
    obj = storage.object_dir(source_key, source_id)
    try:
        meta = storage.read_json(obj / "meta.json")
    except (OSError, ValueError):
        return out
    if llm:
        doc = llm_mod.load_extracted(source_key, source_id)
        if not doc or doc.get("status") not in ("ok", "skipped"):
            out.append("summary")
        elif doc.get("status") == "skipped" and _summary_configured():
            out.append("summary")  # 以前没配模型跳过了，现在配上了：补
    try:
        manifest = storage.read_json(storage.raw_dir(source_key, source_id, meta["current_version"]) / "manifest.json")
    except (OSError, ValueError, KeyError):
        manifest = {}
    assets = {m["file"] for m in manifest.get("media", []) if m.get("file")
              and Path(m["file"]).suffix.lower() in IMAGE_SUFFIXES and (obj / m["file"]).is_file()}
    if assets:
        vision_path = storage.derived_dir(source_key, source_id) / "vision.json"
        try:
            done = {x.get("asset") for x in storage.read_json(vision_path).get("images", [])}
        except (OSError, ValueError):
            done = set()
        if assets - done:
            out.append("vision")
    return out


def candidates(*, pending_only_marked: bool = False) -> list[tuple[str, str, dict[str, Any], list[str]]]:
    """[(source_key, source_id, state, needs)]：标了待 enrich 的排前面；连着失败 ≥3 次的按 retry_after 退避，到点再捡。"""
    from . import index as index_mod

    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT source, source_id FROM objects ORDER BY item_id").fetchall()
    finally:
        conn.close()
    marked, rest = [], []
    for r in rows:
        key, sid = r["source"], r["source_id"]
        state = load_state(key, sid)
        if backing_off(state):
            continue
        missing = needs(key, sid)
        if state.get("pending"):
            marked.append((key, sid, state, missing))
        elif missing and not pending_only_marked:
            rest.append((key, sid, state, missing))
    return marked + rest


# --------------------------------------------------------------------------
# 子进程 + 整棵树限时
# --------------------------------------------------------------------------


def _child_argv(source_key: str, source_id: str, llm: bool) -> list[str]:
    return [sys.executable, "-c",
            "import sys; from link_brain import enrich; "
            "sys.exit(enrich._child(sys.argv[1], sys.argv[2], sys.argv[3] == '1'))",
            source_key, source_id, "1" if llm else "0"]


def _child(source_key: str, source_id: str, llm: bool) -> int:
    """子进程里真正干活：识图（缺的才调）+ 渲染（llm=True 时补概要）。"""
    from . import render as render_mod

    render_mod.render_item(source_key, source_id, verbose=False, llm=llm)
    left = needs(source_key, source_id, llm=llm)
    if left:
        print(f"还缺：{'、'.join(left)}", file=sys.stderr)
        return _CHILD_INCOMPLETE
    return 0


def kill_tree(proc: subprocess.Popen) -> None:
    """连同它起的子进程一起杀（CONVENTIONS §6.2：procs.kill_tree，跳过读取服务和它的浏览器；不用 taskkill /T）。"""
    if proc.poll() is not None:
        return
    from . import procs

    procs.kill_tree(proc.pid)
    try:
        proc.kill()
    except OSError:
        pass


def run_limited(argv: list[str], timeout: float) -> tuple[int | None, str, bool]:
    """跑一个子进程，超时整棵杀。返回 (退出码 或 None, stderr 尾巴, 是否超时)。"""
    repo = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = repo + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **kwargs)
    try:
        _, err = proc.communicate(timeout=timeout)
        return proc.returncode, (err or "").strip(), False
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            _, err = proc.communicate(timeout=30)
        except (subprocess.TimeoutExpired, ValueError):
            err = ""
        return None, (err or "").strip(), True


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def enrich_one(source_key: str, source_id: str, *, llm: bool = True, timeout: float | None = None) -> dict[str, Any]:
    """补一篇。返回 {item_id, status: done|failed|deferred, error?}；并更新 enrich-state.json。"""
    cap = ITEM_TIMEOUT_SECONDS if timeout is None else max(1.0, min(timeout, ITEM_TIMEOUT_SECONDS))
    item_id = f"xhs-{source_id}"
    state = load_state(source_key, source_id)
    error = ""
    timed_out = False
    try:
        before = needs(source_key, source_id, llm=llm)   # 10-03 同步记录：这次要补的是哪几项
    except Exception:  # noqa: BLE001
        before = []
    if os.environ.get("LINK_BRAIN_RENDER_INPROC"):  # 测试里要吃 monkeypatch，就地跑
        try:
            code = _child(source_key, source_id, llm)
        except Exception as exc:  # noqa: BLE001
            code, error = 1, f"{type(exc).__name__}: {exc}"
    else:
        code, err, timed_out = run_limited(_child_argv(source_key, source_id, llm), cap)
        error = (err.splitlines() or [""])[-1][:300]
    if timed_out and cap < ITEM_TIMEOUT_SECONDS:
        # 是这一批的时间预算到了、不是这篇卡死：不记失败，留着下次
        return {"item_id": item_id, "status": "deferred", "error": "时间预算到了，下次接着补"}
    if timed_out:
        error = f"识图/概要超过 {ITEM_TIMEOUT_SECONDS // 60} 分钟，已结束它（归档已存好）"
    from . import problems
    if code == 0:
        new_state = {**state, "fails": 0, "last_error": ""}
        new_state.pop("retry_after", None)
        if llm:
            new_state["pending"] = False
        _save_state(source_key, source_id, new_state)
        problems.resolve("enrich.summary", item_id, "TRANSIENT.RETRY_EXHAUSTED")
        _synclog(source_key, source_id, item_id, before, [], "")
        return {"item_id": item_id, "status": "done"}
    fails = int(state.get("fails") or 0) + 1
    if not error and code == _CHILD_INCOMPLETE:
        error = "还缺：" + "、".join(needs(source_key, source_id, llm=llm))
    error = error or f"退出码 {code}"
    retry_after = retry_after_for(fails)
    new_state = {**state, "fails": fails, "last_error": error}
    if retry_after:
        new_state["retry_after"] = retry_after
    _save_state(source_key, source_id, new_state)
    if retry_after:
        # 第 4 批：不再报警。暂时放弃 = TRANSIENT（到 retry_after 自动捡回来），只记不推；
        # 底下那次失败的原因（接口故障 / key 失效…）llm.py / vision.py 已按码登记，key 失效那类会推一次
        problems.report("enrich.summary", "TRANSIENT.RETRY_EXHAUSTED",
                        f"识图 / 概要连着 {fails} 次没补成：{error}"[:200], item_id=item_id,
                        title=_title(source_key, source_id), action="gave_up", next_at=retry_after)
    try:
        left = needs(source_key, source_id, llm=llm)
    except Exception:  # noqa: BLE001
        left = list(before)
    _synclog(source_key, source_id, item_id, before, left, error)
    return {"item_id": item_id, "status": "failed", "error": error, "fails": fails,
            "gave_up": fails >= MAX_FAILS, "retry_after": retry_after}


def _synclog(source_key: str, source_id: str, item_id: str, before: list[str], left: list[str], error: str) -> None:
    """10-03 同步记录：这次补的识图 / 概要，补上了 ✅、还缺 ❌（带原因）。本来就不缺的不记。"""
    try:
        from . import synclog
        title = _title(source_key, source_id)
        for kind in ("vision", "summary"):
            if kind in before:
                synclog.note(kind, item_id, kind not in left, title=title, reason=error or "没补成")
    except Exception as exc:  # noqa: BLE001
        print(f"[synclog] {type(exc).__name__}: {exc}", file=sys.stderr)


def _title(source_key: str, source_id: str) -> str | None:
    try:
        return storage.read_json(storage.object_dir(source_key, source_id) / "meta.json").get("title")
    except (OSError, ValueError):
        return None


def enrich_items(targets: list[tuple[str, str]], *, llm: bool = True, deadline: float | None = None,
                 limit: int = 0, verbose: bool = True) -> dict[str, Any]:
    """逐篇补；deadline（time.monotonic）到了就收手，剩下的留给下次。"""
    done, failed, deferred = [], [], 0
    for i, (key, sid) in enumerate(targets):
        if limit and len(done) + len(failed) >= limit:
            deferred += len(targets) - i
            break
        left = None if deadline is None else deadline - time.monotonic()
        if left is not None and left < 30:
            deferred += len(targets) - i
            break
        if verbose:
            print(f"[enrich] {i + 1}/{len(targets)} xhs-{sid} 识图 / 概要中", file=sys.stderr)
        out = enrich_one(key, sid, llm=llm, timeout=left)
        if out["status"] == "done":
            done.append(out["item_id"])
        elif out["status"] == "deferred":
            deferred += len(targets) - i
            break
        else:
            failed.append(out)
            if verbose:
                print(f"[enrich] xhs-{sid} 没补成（第 {out['fails']} 次）：{out['error']}", file=sys.stderr)
    return {"done": done, "failed": failed, "deferred": deferred}


def run(args) -> int:
    """`python -m link_brain enrich [--pending] [--item ID] [--budget-min N] [--limit N]`。stdout 只有一个 JSON。"""
    import contextlib

    from . import index as index_mod
    from .read import dump_json

    budget = float(getattr(args, "budget_min", 0) or 0)
    deadline = time.monotonic() + budget * 60 if budget > 0 else None
    with contextlib.redirect_stdout(sys.stderr):
        if getattr(args, "item", None):
            conn = index_mod.connect()
            try:
                row = index_mod.get_object(conn, args.item)
            finally:
                conn.close()
            if not row:
                print(f"没有归档过: {args.item}", file=sys.stderr)
                return EXIT_ERROR
            targets = [(row["source"], row["source_id"])]
        elif getattr(args, "pending", False):
            targets = [(k, s) for k, s, _, _ in candidates()]
        else:
            print("需要 --pending 或 --item", file=sys.stderr)
            return EXIT_ERROR
        out = enrich_items(targets, llm=True, deadline=deadline, limit=int(getattr(args, "limit", 0) or 0))
        gave_up = [f for f in out["failed"] if f.get("gave_up")]
        if gave_up:
            # 第 4 批：不推送（enrich_one 已逐篇登记 TRANSIENT.RETRY_EXHAUSTED，目录页问题入口看得到）
            print(f"[enrich] 连着 {MAX_FAILS} 次没补成、隔几天再自动试：{len(gave_up)} 篇"
                  "（要马上重跑：python -m link_brain enrich --item <item_id>）", file=sys.stderr)
    dump_json({"candidates": len(targets), **out})
    return EXIT_ERROR if out["failed"] else EXIT_OK
