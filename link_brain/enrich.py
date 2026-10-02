"""`enrich`：给已经归档的笔记补识图 + 概要（1001）。**不碰号**：只读本地原文，调识图 / 小模型。

为什么单独一步：同步收藏只在「抓取阶段」用号（抓原文 + 本地渲染，不调模型、不识图），
新收的篇标成「待 enrich」；识图、概要放到这里慢慢补。这样：
- 抓取阶段又快又短，号用完就放（账号锁、开页节奏都只罩抓取）；
- 一篇识图卡死（0929 那晚一篇卡了 70 分钟）只卡它自己：每篇一个子进程、20 分钟上限，
  超时连同它起的子进程（OCR / 识图脚本）整棵杀掉；
- 失败记次数，同一篇累计失败 3 次后不再自动重试（`--item` 点名仍可重跑）。

候选（`--pending`）：标了待 enrich 的 / 概要失败或缺失的 / 有图没识的。标了的排前面。
状态记在对象目录 `enrich-state.json`：`{pending, fails, last_error, updated_at}`。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import storage

SOURCE = "xiaohongshu"
MAX_FAILS = 3
ITEM_TIMEOUT_SECONDS = int(os.environ.get("LWA_ENRICH_TIMEOUT", str(20 * 60)))
IMAGE_SUFFIXES = {".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif", ".heic", ".bmp"}
EXIT_OK = 0
EXIT_ERROR = 1
_CHILD_INCOMPLETE = 3  # 子进程跑完了但还缺东西（概要失败 / 有图没识出来）


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
        if not doc or doc.get("status") != "ok":
            out.append("summary")
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
    """[(source_key, source_id, state, needs)]：标了待 enrich 的排前面；累计失败 ≥3 次的不再自动重试。"""
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
        if int(state.get("fails") or 0) >= MAX_FAILS:
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
    if code == 0:
        new_state = {**state, "fails": 0, "last_error": ""}
        if llm:
            new_state["pending"] = False
        _save_state(source_key, source_id, new_state)
        return {"item_id": item_id, "status": "done"}
    fails = int(state.get("fails") or 0) + 1
    if not error and code == _CHILD_INCOMPLETE:
        error = "还缺：" + "、".join(needs(source_key, source_id, llm=llm))
    _save_state(source_key, source_id, {**state, "fails": fails, "last_error": error or f"退出码 {code}"})
    return {"item_id": item_id, "status": "failed", "error": error or f"退出码 {code}", "fails": fails,
            "gave_up": fails >= MAX_FAILS}


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

    from . import alert as alert_mod, index as index_mod
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
            alert_mod.alert(alert_mod.KIND_BATCH, f"识图/概要连续 {MAX_FAILS} 次没补成：{len(gave_up)} 篇，不再自动重试",
                            "\n".join(f"{f['item_id']}: {f['error']}" for f in gave_up[:8])
                            + "\n要重跑：python -m link_brain enrich --item <item_id>")
    dump_json({"candidates": len(targets), **out})
    return EXIT_ERROR if out["failed"] else EXIT_OK
