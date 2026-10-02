"""图片：本地 OCR（第 0 层）+ 识图（第一层每张、第二层只补跑挑出来的），结果落 derived/vision.json。

规则（docs/FORMAT.md、docs/TASKBOOK.md Lot 3、CONVENTIONS §4）：
- 每张图一条记录，`asset` 回指相对对象目录的 RAW 路径（`raw/v0001/assets/xxx.webp`）。
- 按不可变 RAW 资产路径跳过已经识别过的图。
- OCR 只有 local（rapidocr 进程内）/ off；识图接口 = providers.resolve('visionAI')（第二层 'visionAI.refine'）。
- 单张图失败记 `status:"failed"`（带故障码），不阻断整体流程；失败 / 没开都登记进 problems。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from . import storage

IMAGE_SUFFIXES = {".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif", ".heic", ".bmp"}


def _item_id(source_key: str, source_id: str) -> str:
    try:
        return storage.read_json(storage.object_dir(source_key, source_id) / "meta.json").get("item_id") \
            or f"{source_key}-{source_id}"
    except (OSError, ValueError):
        return f"{source_key}-{source_id}"


def run_ocr(image_path: Path, cfg: dict[str, Any] | None = None, *, timeout: int | None = None) -> dict[str, Any]:
    """OCR 一张图（§4：生产和设置页「测试 OCR」同一个函数）。返回 {status, ocr, text, code, error[, lines]}。

    设置 ocr.mode：local = rapidocr 进程内（带位置框，免费）；off = 关。没装 rapidocr 时 skipped。
    """
    from . import providers, visual
    cfg = cfg if cfg is not None else providers.resolve("ocr")
    if cfg is None:
        r = providers.skipped_for("ocr")
        return {**r, "ocr": None, "error": r["error"] + "；正文和原图仍正常归档。"}
    if not visual.available():
        return {**providers.skipped("ocr", "没装本地 OCR（pip install rapidocr）"), "ocr": None}
    out = visual.local_ocr(image_path)
    out.setdefault("code", "" if out.get("status") == "ok" else "TRANSIENT.SERVICE_BUSY")
    out["text"] = out.get("ocr")
    return out


def _layer1_problem(got: dict[str, Any], source_key: str, item_id: str | None) -> None:
    """第一层识图的结果进问题记录：接口故障按码登记（同一篇一条），成功就把这篇的记录清掉。"""
    if not item_id:
        return
    from . import problems
    if got.get("status") == "ok":
        problems.resolve("vision.layer1", item_id)
    elif got.get("code"):
        problems.report("vision.layer1", got["code"], got.get("error") or "识图失败", item_id=item_id)


def _understand(entry: dict[str, Any], path: Path, cfg: dict[str, Any] | None, source_key: str = "",
                item_id: str | None = None) -> dict[str, Any]:
    """有位置框的 OCR 结果 → 判版面；表格 / 几乎没字的图且配了识图接口 → 云端识图。

    0926 Owner：小红书「几乎没字但有字」的图基本是标题图（大字一句话 + 纯色底），
    直接转写成「标题：…」，不调模型、不描述底色——只有小红书这么设计，别的站照旧描述。
    """
    from . import visual
    if entry.get("status") != "ok" or "lines" not in entry:
        return entry
    entry["layout"] = visual.classify(entry["lines"])
    title = (visual.title_text(entry["lines"]) if source_key == "xiaohongshu" and entry["layout"] == "picture"
             and visual.flat_background(path) else "")
    if title:
        entry["layout"] = "title"
        entry["visual"] = {"kind": "title", "status": "ok", "text": "标题：" + title}
        return entry
    # 第一层（0927 起每张图都走；0928 分两层）：便宜模型带着 OCR 判类型、按图纠错、标打码
    old = entry.get("visual") or {}
    if cfg and (old.get("status") != "ok" or old.get("v") != visual.VISUAL_VERSION):
        got = visual.understand(path, entry["lines"], cfg)
        if got.get("status") == "ok" or old.get("status") != "ok":
            entry["visual"] = {k: v for k, v in got.items() if k not in ("usage", "truncated", "api_error")}
        if got.get("status") == "ok":
            entry["layout"] = got["kind"]
            mark_refine(entry, refine_reason(entry))
        _layer1_problem(got, source_key, item_id)
    elif old.get("status") == "ok" and old.get("v") == visual.VISUAL_VERSION:
        entry["layout"] = old["kind"]  # 已是新版结果：类型以模型判的为准，别被本地版面判断盖掉
    return entry


REFINE_MIN_CHARS = int(os.environ.get("LWA_REFINE_MIN_CHARS", "300"))
REFINE_TRIES = 3  # 第一次 + 重试 2 次（只数「模型给了结果但不合格」，接口故障不算，见 refine_object）
API_STREAK_STOP = 3  # 连着几张都是接口故障就今晚收手


def refine_reason(entry: dict[str, Any]) -> str:
    """第一层跑完后，这张图值不值得交给强模型补跑（0928 Owner 定的三条里的前两条；第三条是手动点名）。"""
    from . import visual
    v = entry.get("visual") or {}
    lines = entry.get("lines") or []
    chars = sum(len(l.get("text") or "") for l in lines)
    if v.get("kind") in ("diagram", "table") and chars > REFINE_MIN_CHARS:
        return f"{'流程图' if v['kind'] == 'diagram' else '表格'}且字多（OCR {chars} 字）"
    if v.get("shaky"):
        return "第一层" + v["shaky"]
    if v.get("kind") == "table" and visual.table_problem(v.get("text") or ""):
        return "第一层表格格式坏了"
    mean = sum(l.get("score", 0) for l in lines) / len(lines) if lines else 1.0
    if chars >= 30 and mean < 0.7:
        return f"OCR 平均信心偏低（{mean:.2f}）"
    return ""


def mark_refine(entry: dict[str, Any], reason: str, *, manual: bool = False) -> bool:
    """打 refine: pending 标。已补跑成功/已放弃的不重打（手动点名除外）。"""
    if not reason:
        return False
    cur = entry.get("refine") or {}
    if cur.get("status") in ("done", "failed") and not manual:
        return False
    entry["refine"] = {"status": "pending", "reason": reason, "tries": 0 if manual else cur.get("tries", 0)}
    return True


def build_vision(source_key: str, source_id: str, *, verbose: bool = False, upgrade: bool = False) -> dict[str, Any]:
    """对当前版本 `raw/vNNNN/assets/` 下每张图跑 OCR，落 `derived/vision.json`。

    按不可变 RAW 资产路径复用 OCR；manifest 引用旧版本图片时同样保留。
    返回写盘的 vision.json 内容。
    """
    object_dir = storage.object_dir(source_key, source_id)
    meta_path = object_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"没有归档过: {source_key}/{source_id}")
    meta = storage.read_json(meta_path)
    version = meta["current_version"]
    raw_dir = storage.raw_dir(source_key, source_id, version)
    assets_dir = raw_dir / "assets"
    rel_prefix = f"raw/{storage.version_name(version)}/assets"

    derived_dir = storage.derived_dir(source_key, source_id)
    vision_path = derived_dir / "vision.json"
    existing = {}
    if vision_path.exists():
        existing = {item['asset']: item for item in storage.read_json(vision_path).get('images', []) if item.get('asset')}
    manifest = storage.read_json(raw_dir / 'manifest.json')
    assets = [m['file'] for m in manifest.get('media', []) if m.get('file') and Path(m['file']).suffix.lower() in IMAGE_SUFFIXES]
    from . import visual
    cfg = visual.vision_config()
    item_id = _item_id(source_key, source_id)
    images = []
    for asset_rel in dict.fromkeys(assets):
        path = object_dir / asset_rel
        if not path.is_file():
            continue
        cached = existing.get(asset_rel)
        if cached and cached.get('status') == 'ok':
            # upgrade：旧结果没有位置框（CMX 时代）就用本地 OCR 重跑一次，补上表格/图片识别
            if upgrade and cached.get("ocr_v") != 2 and visual.available():  # 0927：旧 OCR 没切块，重认一遍
                cached = {'asset': asset_rel, **visual.local_ocr(path)}
            images.append(_understand(cached, path, cfg, source_key, item_id) if upgrade or "lines" in cached else cached)
            continue
        result = run_ocr(path)
        result.pop("text", None)
        images.append(_understand({'asset': asset_rel, **result}, path, cfg, source_key, item_id))

    doc = {
        "schema_version": 1,
        "version": version,
        "images": images,
    }
    storage.write_json(vision_path, doc)
    return doc


def run_upgrade(args) -> int:
    """`vision --upgrade`：给旧图补本地 OCR 位置框、版面判断和识图（表格 / 几乎没字的图）。

    每晚分批跑（--limit 篇），做完的篇记在 derived/vision.json 的 upgraded 标记里，下次跳过。
    """
    from . import index as index_mod, read as read_mod, render as render_mod, visual
    if not visual.available():
        print("未安装本地 OCR：pip install rapidocr", file=sys.stderr)
        return 1
    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT source, source_id FROM objects ORDER BY item_id").fetchall()
    finally:
        conn.close()
    done = tables = pictures = 0
    for row in rows:
        vpath = storage.derived_dir(row["source"], row["source_id"]) / "vision.json"
        if vpath.exists() and storage.read_json(vpath).get("upgraded_v") == visual.VISUAL_VERSION:
            continue  # 0928：按识图版本记，版本一升全库夜里慢慢重跑第一层
        if args.limit and done >= args.limit:
            break
        try:
            doc = build_vision(row["source"], row["source_id"], upgrade=True)
        except (FileNotFoundError, KeyError, OSError) as exc:
            print(f"{row['source_id']}: 跳过（{exc}）", file=sys.stderr)
            continue
        doc["upgraded"] = True
        doc["upgraded_v"] = visual.VISUAL_VERSION
        storage.write_json(vpath, doc)
        tables += sum(1 for im in doc["images"] if im.get("layout") == "table")
        pictures += sum(1 for im in doc["images"] if im.get("layout") == "picture")
        render_mod.render_object(row["source"], row["source_id"])
        done += 1
    read_mod.dump_json({"objects": done, "tables": tables, "pictures": pictures})
    return 0


# ---------------------------------------------------------------- 第二层：补跑（0928）

REFINE_GAP_SECONDS = tuple(float(x) for x in os.environ.get("LWA_REFINE_GAP", "5,15").split(","))


def strong_config() -> dict[str, Any] | None:
    """第二层用的强模型：providers.resolve('visionAI.refine')——识图接口 + 精细识别模型（留空 = 第一层同一个）。"""
    from . import providers
    return providers.resolve("visionAI.refine")


# 0928 Owner：第二层优先用 Google AI Studio 的免费 key（gemini flash 实测架构图 17/17，和 qwen3.8-max 一样准）。
# 免费档常 429（限额）/ 503（过载）：429 换下一个 key，503 歇一会儿同 key 再试一次；key 全用不了就退回设置里的强模型。
# key 只从环境变量来（变量名 = 设置 visionAI.refineKeysEnv，默认 LWA_GEMINI_KEYS，逗号分隔），由调用方临时注入，不落盘、不进仓库。
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL = os.environ.get("LWA_GEMINI_MODEL", "gemini-3.5-flash")
_KEY_DEAD_CODES = ("TRANSIENT.HTTP_429", "TRANSIENT.HTTP_5XX", "NEEDS_HUMAN.AUTH_FAILED", "NEEDS_HUMAN.QUOTA_EXCEEDED")


def _refine_keys_env() -> str:
    from . import ai_config
    return str((ai_config.load().get("visionAI") or {}).get("refineKeysEnv") or "LWA_GEMINI_KEYS")


class RefineRouter:
    """第二层走哪个模型：免费 key 轮换 → 设置里的强模型兜底。一晚上共用一个实例，记住哪些 key 今天用完了。"""

    def __init__(self, fallback: dict[str, Any] | None):
        self.keys = [k.strip() for k in os.environ.get(_refine_keys_env(), "").split(",") if k.strip()]
        self.dead: set[int] = set()
        self.fallback = fallback
        self.used: dict[str, int] = {}

    def refine(self, path: Path, lines, kind: str) -> dict[str, Any]:
        import time
        from . import visual
        for i, key in enumerate(self.keys):
            if i in self.dead:
                continue
            cfg = {"endpoint": GEMINI_ENDPOINT, "apiKey": key, "model": GEMINI_MODEL}
            got = visual.refine(path, lines, kind, cfg)
            if got.get("http_status") == 503:  # 过载：歇一会儿再试一次
                time.sleep(30)
                got = visual.refine(path, lines, kind, cfg)
            if got.get("status") == "ok" or got.get("code") not in _KEY_DEAD_CODES:
                self.used[GEMINI_MODEL] = self.used.get(GEMINI_MODEL, 0) + 1
                return {**got, "model": f"{GEMINI_MODEL}（免费 key {i + 1}）"}  # 成功，或内容本身不合格（算一次尝试）
            self.dead.add(i)  # 这个 key 今晚限额满了 / 不可用
        if not self.fallback:
            from . import providers
            return providers.result("failed", code="SKIPPED.NOT_CONFIGURED", api_error=True,
                                    error="免费 key 都用不了，也没配精细识别模型")
        got = visual.refine(path, lines, kind, self.fallback)
        self.used[self.fallback["model"]] = self.used.get(self.fallback["model"], 0) + 1
        return got


def refine_object(source_key: str, source_id: str, cfg: dict[str, Any], *, budget: int = 0,
                  verbose: bool = True, tally: dict[str, Any] | None = None) -> dict[str, Any]:
    """补跑这篇里 refine: pending 的图（一次一张、跑完歇一会）。成功写 refined 并重生成机读版。"""
    import random
    import time
    from datetime import datetime
    from . import render as render_mod, visual
    tally = tally if tally is not None else {"done": 0, "failed": 0, "retry": 0, "cost_yuan": 0.0, "runs": 0}
    vpath = storage.derived_dir(source_key, source_id) / "vision.json"
    if not vpath.exists():
        return tally
    doc = storage.read_json(vpath)
    changed = False
    for entry in doc.get("images", []):
        ref = entry.get("refine") or {}
        if ref.get("status") != "pending":
            continue
        if budget and tally["runs"] >= budget:
            break
        if tally.get("api_streak", 0) >= API_STREAK_STOP:
            break  # 接口连着不通：今晚别再一张张白等
        if tally["runs"]:
            time.sleep(random.uniform(*REFINE_GAP_SECONDS))
        tally["runs"] += 1
        kind = (entry.get("visual") or {}).get("kind") or entry.get("layout") or "text"
        img = storage.object_dir(source_key, source_id) / entry["asset"]
        got = cfg.refine(img, entry.get("lines"), kind) if isinstance(cfg, RefineRouter) else visual.refine(img, entry.get("lines"), kind, cfg)
        tally["cost_yuan"] += got.get("cost_yuan") or 0.0
        ref["at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if got.get("status") != "ok" and got.get("api_error"):
            # 1001（审计 vision-4）：接口故障不计次数，留在 pending 明晚再来；连着 3 张都这样就今晚收手
            ref["error"] = got.get("error")
            tally["api_errors"] = tally.get("api_errors", 0) + 1
            tally["api_streak"] = tally.get("api_streak", 0) + 1
            if str(got.get("code") or "").startswith("NEEDS_HUMAN."):
                tally["needs_human"] = {"code": got["code"], "error": got.get("error")}
        elif got.get("status") == "ok":
            ref["tries"] = ref.get("tries", 0) + 1
            entry["refined"] = got
            ref["status"] = "done"
            ref.pop("error", None)
            tally["done"] += 1
            tally["api_streak"] = 0
        else:
            ref["tries"] = ref.get("tries", 0) + 1
            tally["api_streak"] = 0
            ref["error"] = got.get("error")
            if ref["tries"] >= REFINE_TRIES:
                ref["status"] = "failed"  # 不再每晚重跑；手动点名可以再来
                tally["failed"] += 1
                from . import problems
                problems.report("vision.refine", "PERMANENT.MODEL_OUTPUT_INVALID",
                                f"{entry['asset'].split('/')[-1]}：{got.get('error') or '精细识别结果不合格'}",
                                item_id=_item_id(source_key, source_id))
            else:
                tally["retry"] += 1
        entry["refine"] = ref
        changed = changed or not got.get("api_error") or got.get("status") == "ok"
        if verbose:
            print(f"[refine] {source_id} {entry['asset'].split('/')[-1]}：{ref['status']}"
                  f"（{ref.get('reason')}；{got.get('model')} ¥{got.get('cost_yuan') or 0:.4f}"
                  + (f"；{ref.get('error')}" if ref.get("error") else "") + "）", file=sys.stderr)
        storage.write_json(vpath, doc)  # 每张写一次：中途被打断也不丢已补好的
    if changed:
        render_mod.render_object(source_key, source_id)
    return tally


def pending_refines() -> list[tuple[str, str, int]]:
    rows = []
    for vpath in sorted((storage.vault_root() / "_archive").glob("*/*/derived/vision.json")):
        try:
            doc = storage.read_json(vpath)
        except (OSError, ValueError):
            continue
        n = sum(1 for e in doc.get("images", []) if (e.get("refine") or {}).get("status") == "pending")
        if n:
            rows.append((vpath.parents[2].name, vpath.parents[1].name, n))
    return rows


def run_refine(args) -> int:
    """`vision --refine`：每晚 4 点那一轮调；只跑打了标的图，日志记本晚补了几张、还剩几张、花了多少钱。"""
    from .read import dump_json
    fallback = strong_config()
    cfg = RefineRouter(fallback)
    if not cfg.keys and not fallback:
        from . import problems, providers
        reason = providers.why_not("visionAI.refine") or "没配识图接口"
        print(f"{reason}，跳过补跑", file=sys.stderr)
        if pending_refines():
            problems.report("vision.refine", "SKIPPED.NOT_CONFIGURED", f"精细识别没开：{reason}", action="skipped")
        return 0
    tally = {"done": 0, "failed": 0, "retry": 0, "cost_yuan": 0.0, "runs": 0}
    for source_key, source_id, _ in pending_refines():
        if args.limit and tally["runs"] >= args.limit:
            break
        if tally.get("api_streak", 0) >= API_STREAK_STOP:
            print("[refine] 识图接口连着不通，今晚先停（待补的图留着，明晚再来，不算失败次数）", file=sys.stderr)
            break
        refine_object(source_key, source_id, cfg, budget=args.limit, tally=tally)
    from . import problems
    if tally.get("needs_human"):
        problems.report("vision.refine", tally["needs_human"]["code"], tally["needs_human"]["error"] or "识图接口要人处理")
    elif tally.get("api_streak", 0) >= API_STREAK_STOP:
        problems.report("vision.refine", "TRANSIENT.SERVICE_BUSY", "识图接口连着不通，今晚先停，明晚接着补")
    elif tally["runs"]:
        problems.resolve("vision.refine", None)
    left = sum(n for _, _, n in pending_refines())
    dump_json({"models": cfg.used, "refined": tally["done"], "failed": tally["failed"], "will_retry": tally["retry"],
               "api_errors": tally.get("api_errors", 0),
               "pending_left": left, "cost_yuan": round(tally["cost_yuan"], 4)})
    return 0


def run_refine_mark(args) -> int:
    """手动点名（插件「精细识别」/ 问答时 AI 要求）：标 pending；--now 马上补跑这篇。"""
    from . import index as index_mod
    from .read import dump_json
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, args.refine_mark)
    finally:
        conn.close()
    if not row:
        print(f"没有归档过: {args.refine_mark}", file=sys.stderr)
        return 1
    vpath = storage.derived_dir(row["source"], row["source_id"]) / "vision.json"
    if not vpath.exists():
        print("这篇还没有识图结果", file=sys.stderr)
        return 1
    doc = storage.read_json(vpath)
    marked = 0
    for entry in doc.get("images", []):
        if args.asset and not entry["asset"].endswith(args.asset):
            continue
        if (entry.get("visual") or {}).get("kind") == "title":
            continue
        marked += mark_refine(entry, "手动点名", manual=True)
    storage.write_json(vpath, doc)
    out: dict[str, Any] = {"item_id": args.refine_mark, "marked": marked}
    if args.now and marked:
        cfg = RefineRouter(strong_config())
        if cfg.keys or cfg.fallback:
            tally = refine_object(row["source"], row["source_id"], cfg)
            out.update(refined=tally["done"], failed=tally["failed"], cost_yuan=round(tally["cost_yuan"], 4))
    dump_json(out)
    return 0
