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


def _layer1_problem(got: dict[str, Any], source_key: str, item_id: str | None, cfg: dict[str, Any] | None = None) -> None:
    """第一层识图的结果进问题记录：成功就把这篇的记录清掉；这篇自己的问题按篇登一条；
    接口那一侧的故障（key / 欠费 / 断网 / 限流 / 服务挂）归并到 ai.vision 一条（1008 Owner：一个原因一条）。"""
    if not item_id:
        return
    from . import ai_health, problems
    if got.get("status") == "ok":
        problems.resolve("vision.layer1", item_id)
        first = got.get("switched_from") or {}
        if not first:
            ai_health.clear("visionAI")
        elif ai_health.is_api_failure(first):
            # 1016：主接口还是坏的、这张是备用补上的：接口那一条留着，但照实写「已换用 X」
            ai_health.record("visionAI", first, cfg=cfg, switched_to=got.get("switched_to") or "")
    elif ai_health.is_api_failure(got):
        ai_health.record("visionAI", got, item_id=item_id, cfg=cfg)
        problems.resolve("vision.layer1", item_id, "PERMANENT.MODEL_OUTPUT_INVALID")  # 1016：旧的 400 那条别一直挂着
    elif got.get("code"):
        problems.report("vision.layer1", got["code"], got.get("error") or "识图失败", item_id=item_id)


def _understand(entry: dict[str, Any], path: Path, cfg: dict[str, Any] | None, source_key: str = "",
                item_id: str | None = None) -> dict[str, Any]:
    """有位置框的 OCR 结果 → 判版面；表格 / 几乎没字的图且配了识图接口 → 云端识图。

    0926 Owner：小红书「几乎没字但有字」的图基本是标题图（大字一句话 + 纯色底），
    直接转写成「标题：…」，不调模型、不描述底色——只有小红书这么设计，别的站照旧描述。
    """
    from . import providers, visual
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
        from . import usage
        with usage.tag("vision", item=item_id):
            got = providers.call_with_pool(cfg, lambda c: visual.understand(path, entry["lines"], c))
            if _should_switch(got):
                got = _understand_backup(path, entry["lines"], cfg, got, item_id)
        if got.get("status") == "ok" or old.get("status") != "ok":
            entry["visual"] = {k: v for k, v in got.items() if k not in ("usage", "truncated", "api_error", "switched_from")}
        if got.get("status") == "ok":
            entry["layout"] = got["kind"]
            mark_refine(entry, refine_reason(entry))
        _layer1_problem(got, source_key, item_id, cfg)
    elif old.get("status") == "ok" and old.get("v") == visual.VISUAL_VERSION:
        entry["layout"] = old["kind"]  # 已是新版结果：类型以模型判的为准，别被本地版面判断盖掉
    return entry


# 1016：第一层主接口 403 / 欠费 / 内容审核拦下时，换一个有视觉能力的备用：免费 key（Gemini）→ 设置 models 里标了
# "vision": true 的条目 → 精细识别模型（接口或 key 和主接口不同才算：同一把坏 key 再试没用）。
SWITCH_CODES = ("NEEDS_HUMAN.AUTH_FAILED", "NEEDS_HUMAN.QUOTA_EXCEEDED", "PERMANENT.CONTENT_FILTERED", "TRANSIENT.HTTP_429")


def _should_switch(got: dict[str, Any]) -> bool:
    return got.get("status") != "ok" and str(got.get("code") or "") in SWITCH_CODES


def backup_label(cfg: dict[str, Any]) -> str:
    from . import ai_health
    return str(cfg.get("label") or f"{ai_health.provider_name(cfg)} {cfg.get('model') or ''}").strip()


def vision_backups(primary: dict[str, Any] | None) -> list[dict[str, Any]]:
    """第一层识图的备用（按顺序），去掉和主接口同一接口同一把 key 的。key 只在内存里。"""
    from . import ai_config, providers
    out: list[dict[str, Any]] = []
    p0 = primary or {}
    keys = [] if p0.get("keyPool") == "gemini" else providers.pool_alive("gemini") or         [k.strip() for k in os.environ.get(_refine_keys_env(), "").split(",") if k.strip()]
    for i, key in enumerate(keys):
        out.append({"endpoint": GEMINI_ENDPOINT, "apiKey": key, "model": GEMINI_MODEL,
                    "label": f"Google {GEMINI_MODEL}（免费 key {i + 1}）"})
    try:
        settings = ai_config.load()
    except Exception:  # noqa: BLE001
        settings = {}
    for m in settings.get("models") or []:
        if not isinstance(m, dict) or not m.get("vision") or m.get("mode", "http") != "http" or not m.get("model"):
            continue
        try:
            cfg, _ = providers.finalize("visionAI", {**m, "mode": "http"})
        except Exception:  # noqa: BLE001
            cfg = None
        if cfg and cfg.get("apiKey"):
            out.append({**cfg, "label": f"{m.get('name') or ''} {m['model']}".strip()})
    try:
        strong = strong_config()
    except Exception:  # noqa: BLE001
        strong = None
    if strong and strong.get("model"):
        twin = cheap_twin(strong, str((settings.get("visionAI") or {}).get("backupModel") or ""))
        if twin:
            out.append(twin)
        out.append(strong)
    p = primary or {}

    def same_key(c):
        return c.get("endpoint") == p.get("endpoint") and (c.get("apiKey") or "") == (p.get("apiKey") or "")
    return [c for c in out if not same_key(c)]


def cheap_twin(strong: dict[str, Any], model: str = "") -> dict[str, Any] | None:
    """1018：免费 key 用完后，第一层的备用别直接上精细识别模型——qwen3.8-max 比 qwen3.8-flash 贵 15 倍，
    1017 一晚 418 张图走了 max ≈ ¥12.5。先用同一接口、同一把 key 的同代便宜看图模型顶（qwen3.8-max → qwen3.8-flash，
    即 1016 以前第一层一直在用的那个）；它也不行再轮到强模型。设置 visionAI.backupModel 可指定；找不到 = None。"""
    from .setup import estimate
    try:
        pricing = estimate.load_pricing()
    except (OSError, ValueError):
        return None
    hit = estimate._price(pricing, str(strong.get("model") or ""))
    if model:
        return None if hit and hit[0] == model else {**strong, "model": model}
    if not hit:
        return None
    name, info = hit
    family = name.rsplit("-", 1)[0] + "-"
    best = None
    for other, m in (pricing.get("models") or {}).items():
        if other == name or not other.startswith(family) or "vision" not in (m.get("kind") or []):
            continue
        if m.get("provider") != info.get("provider") or float(m.get("input") or 0) >= float(info.get("input") or 0):
            continue
        if best is None or float(m.get("input") or 0) > float(best[1].get("input") or 0):
            best = (other, m)
    return {**strong, "model": best[0]} if best else None


def _understand_backup(path: Path, lines, primary: dict[str, Any], first: dict[str, Any],
                       item_id: str | None) -> dict[str, Any]:
    from . import providers, visual
    for alt in vision_backups(primary):
        got = visual.understand(path, lines, alt)
        if got.get("status") == "ok":
            why = "被内容审核拦下" if first.get("code") == "PERMANENT.CONTENT_FILTERED" else \
                f"{first.get('code')}（HTTP {first.get('http_status') or '-'}）"
            print(f"[vision] {item_id or ''} {path.name}：主识图接口{why}，已换用 {backup_label(alt)}", file=sys.stderr)
            return {**got, "switched_to": backup_label(alt),
                    "switched_from": {k: first.get(k) for k in ("code", "error", "http_status", "api_error")}}
    return first


REFINE_MIN_CHARS = int(os.environ.get("LWA_REFINE_MIN_CHARS", "300"))
REFINE_TRIES = 3  # 请求本身被拒（4xx）这类：跨晚累计 3 次放弃（接口故障不算，见 refine_object）
# 10-04 当场自愈（Owner：凌晨跑完出 bug 当场修，不留到第二天）：模型给了结果但不合格（复读 / 截断 / 格式坏），
# 同一次运行里依次：换参数重试（温度调高，跳出复读循环）→ 换另一个已配置的模型 → 还不行才放弃并退回第一层结果。
RETRY_TEMPERATURE = 0.6
ALT_TEMPERATURE = 0.3
API_STREAK_STOP = 3  # 连着几张都是接口故障就今晚收手


def refine_reason(entry: dict[str, Any]) -> str:
    """第一层跑完后，这张图值不值得交给强模型补跑（0928 Owner 定的三条里的前两条；第三条是手动点名）。"""
    from . import providers, visual
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


def stamp_doubt(entry: dict[str, Any]) -> dict[str, Any]:
    """1017：识图 / OCR 文字靠不住的图记 `doubt: true` + `doubt_reason`（判据 agentmd.doubt_reasons，机读版据此写一句
    「识图存疑…以原图为准」）；靠得住的把这两个字段拿掉。识不准不是故障：不进问题记录。"""
    from . import agentmd
    why = agentmd.shaky(entry)
    if why:
        entry["doubt"] = True
        entry["doubt_reason"] = why
    else:
        entry.pop("doubt", None)
        entry.pop("doubt_reason", None)
    return entry


REFINE_GAVE_UP = "PERMANENT.MODEL_OUTPUT_INVALID"


def retire_refine_problems(item_id: str | None = None) -> int:
    """1017 作者裁决：精细识图因模型输出不合格放弃 ≠ 故障，改在机读版标「识图存疑」。以前登记的
    `vision.refine|<篇>|MODEL_OUTPUT_INVALID` 一律按 CONVENTIONS §2「已解决」口径追加 resolved 行（problems.resolve）；
    item_id=None = 全库扫一遍（幂等，没有就 0 开销）。顺带把 1008 那次「卡片有标、面板没有」的一次性补登记记成做过——
    它补登记的正是这类，不然新库第一次打开面板会再补回来。永不抛异常。"""
    from . import problems
    try:
        if item_id:
            return problems.resolve("vision.refine", item_id, REFINE_GAVE_UP)
        done = 0
        for row in problems.load(100000, include_resolved=False, include_minor=True):
            if row.get("step") == "vision.refine" and row.get("item_id") and row.get("code") == REFINE_GAVE_UP:
                done += problems.resolve("vision.refine", row["item_id"], REFINE_GAVE_UP)
        mark = storage.archive_root() / problems.MIGRATIONS_NAME
        try:
            seen = storage.read_json(mark)
        except (OSError, ValueError):
            seen = {}
        seen = seen if isinstance(seen, dict) else {}
        if not seen.get("orphan_refine_1008"):
            from datetime import datetime
            storage.write_json(mark, {**seen, "orphan_refine_1008": datetime.now().astimezone().isoformat(timespec="seconds"),
                                      "orphan_refine_1008_note": "1017 作废：精细识图放弃不进问题面板"})
        return done
    except Exception as exc:  # noqa: BLE001 - 收旧行失败最多是面板里多挂一条
        print(f"[vision] 收旧的精细识图放弃行没做成（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 0


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
    from . import providers, visual
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
            images.append(stamp_doubt(_understand(cached, path, cfg, source_key, item_id)
                                      if upgrade or "lines" in cached else cached))
            continue
        result = run_ocr(path)
        result.pop("text", None)
        images.append(stamp_doubt(_understand({'asset': asset_rel, **result}, path, cfg, source_key, item_id)))

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
        try:  # 10-03 同步记录：识图第一层补跑了这一篇
            from . import synclog
            synclog.note("vision", _item_id(row["source"], row["source_id"]), True)
        except Exception as exc:  # noqa: BLE001
            print(f"[synclog] {type(exc).__name__}: {exc}", file=sys.stderr)
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
        from . import providers
        self.keys = providers.pool_alive("gemini") or             [k.strip() for k in os.environ.get(_refine_keys_env(), "").split(",") if k.strip()]
        self.dead: set[int] = set()
        self.fallback = fallback
        self.used: dict[str, int] = {}
        self.last_cfg: dict[str, Any] | None = None

    def refine(self, path: Path, lines, kind: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """overrides：换参数重试时叠在本次用到的配置上（如 temperature）。self.last_cfg = 这次实际用的那份（不含 key 的去向）。"""
        import time
        from . import visual
        extra = dict(overrides or {})
        for i, key in enumerate(self.keys):
            if i in self.dead:
                continue
            cfg = {"endpoint": GEMINI_ENDPOINT, "apiKey": key, "model": GEMINI_MODEL, **extra}
            self.last_cfg = cfg
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
        self.last_cfg = {**self.fallback, **extra}
        got = visual.refine(path, lines, kind, self.last_cfg)
        self.used[self.fallback["model"]] = self.used.get(self.fallback["model"], 0) + 1
        return got


def _content_invalid(got: dict[str, Any]) -> bool:
    """模型给了结果、但结果不合格（复读 / 截断 / 流程图或表格格式坏）——换参数 / 换模型有意义；接口故障和请求被拒不算。"""
    return got.get("status") != "ok" and not got.get("api_error") and bool(got.get("text")) \
        and not str(got.get("code") or "").startswith(("NEEDS_HUMAN.", "SKIPPED."))


def _same_model(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    return bool(a and b) and (a.get("endpoint"), a.get("model")) == (b.get("endpoint"), b.get("model"))


def alternate_models(used: dict[str, Any] | None) -> list[dict[str, Any]]:
    """「另一个已配置的模型」：设置里的精细识别模型、第一层识图模型，去掉刚用过的、去重。"""
    from . import providers, visual
    out: list[dict[str, Any]] = []
    for get in (strong_config, visual.vision_config):
        try:
            cfg = get()
        except Exception:  # noqa: BLE001 - 配置读不动就当没有
            cfg = None
        if cfg and cfg.get("model") and not _same_model(cfg, used) and not any(_same_model(cfg, x) for x in out):
            out.append(cfg)
    return out


def refine_with_fallbacks(img: Path, lines, kind: str, cfg) -> tuple[dict[str, Any], list[str]]:
    """一张图的精细识别 + 当场自愈梯子。返回 (最后结果, 试过的做法)。
    ① 原样 ② 结果不合格 → 同一路换参数（温度 RETRY_TEMPERATURE）③ 还不合格 → 依次换别的已配置模型。
    接口故障 / 要人处理 / 没配：立即返回（交给调用方按原规则处理），不在这里白烧钱。"""
    from . import providers, visual
    router = cfg if isinstance(cfg, RefineRouter) else None
    got = router.refine(img, lines, kind) if router else visual.refine(img, lines, kind, cfg)
    used = router.last_cfg if router else cfg
    tried = [str(got.get("model") or (used or {}).get("model") or "模型")]
    if not _content_invalid(got):
        return got, tried
    cost = float(got.get("cost_yuan") or 0.0)
    first_error = got.get("error")
    retry = (router.refine(img, lines, kind, {"temperature": RETRY_TEMPERATURE}) if router
             else visual.refine(img, lines, kind, {**cfg, "temperature": RETRY_TEMPERATURE}))
    cost += float(retry.get("cost_yuan") or 0.0)
    tried.append(f"换参数（温度 {RETRY_TEMPERATURE}）")
    got = retry
    if got.get("status") == "ok" or not _content_invalid(got) and got.get("api_error"):
        return {**got, "cost_yuan": cost}, tried
    for alt in alternate_models(used):
        nxt = visual.refine(img, lines, kind, {**alt, "temperature": ALT_TEMPERATURE})
        cost += float(nxt.get("cost_yuan") or 0.0)
        tried.append(f"换模型 {alt.get('model')}")
        if nxt.get("status") == "ok":
            return {**nxt, "cost_yuan": cost}, tried
        if _content_invalid(nxt) or not got.get("text"):
            got = nxt
    if got.get("status") != "ok" and got.get("text") is None:
        got = {**got, "error": first_error or got.get("error")}
    if "复读" in str(got.get("error") or "") + str(first_error or ""):
        # 1016：复读别整图退回——先把图切成上下几段分别精细识别再拼；还不行就截到复读前、保留有效的那一段
        tiles = refine_tiles(img, lines, kind, used, router)
        if tiles is not None:
            cost += float(tiles.get("cost_yuan") or 0.0)
            tried.append(f"分 {tiles.get('tiles')} 段重识")
            if tiles.get("status") == "ok":
                return {**tiles, "cost_yuan": cost}, tried
        kept = salvage_repeat(got.get("text") or "")
        if kept:
            tried.append("截到复读前")
            return {**got, "status": "ok", "text": kept, "partial": True, "code": "", "error": None,
                    "cost_yuan": cost}, tried
    return {**got, "cost_yuan": cost, "ladder_exhausted": True, "api_error": False}, tried


SALVAGE_MIN_CHARS = 80   # 截到复读前至少还剩这么多字才算「有效部分」
SALVAGE_NOTE = "（后面出现复读，已截掉；完整文字见本地 OCR）"
TILE_MAX = 4


def salvage_repeat(text: str) -> str:
    """复读结果截到第一处复读标记为止（被复读的那段保留一次）。剩下太少 / 是流程图（截了就坏）→ 空串。"""
    from . import providers, visual
    if not text or "```mermaid" in text or visual.REPEAT_MARK not in text:
        return ""
    cut = text.split(visual.REPEAT_MARK, 1)[0].rstrip()
    if len("".join(cut.split())) < SALVAGE_MIN_CHARS:
        return ""
    return cut + "\n" + SALVAGE_NOTE


def refine_tiles(img: Path, lines, kind: str, cfg, router=None) -> dict[str, Any] | None:
    """把图切成上下 N 段（有重叠）分别精细识别、按顺序拼起来。流程图 / 太矮的图不切（结构会断）→ None。"""
    import tempfile
    from . import providers, visual
    if kind == "diagram" or (not cfg and router is None):
        return None
    try:
        from PIL import Image
        with Image.open(img) as im:
            im = im.convert("RGB")
            w, h = im.size
            if h < 400:
                return None
            n = max(2, min(TILE_MAX, round(h / max(w * 0.6, 1))))
            step, pad = h / n, int(h / n * 0.06)
            parts, cost = [], 0.0
            with tempfile.TemporaryDirectory() as tmp:
                for i in range(n):
                    y0, y1 = max(0, int(i * step) - pad), min(h, int((i + 1) * step) + pad)
                    tp = Path(tmp) / f"tile{i}.png"
                    im.crop((0, y0, w, y1)).save(tp)
                    seg = [l for l in (lines or []) if y0 <= (l["box"][1] + l["box"][3]) / 2 <= y1]
                    part = router.refine(tp, seg, "text") if router else visual.refine(tp, seg, "text", cfg)
                    cost += float(part.get("cost_yuan") or 0.0)
                    if part.get("status") != "ok":
                        return {**part, "tiles": n, "cost_yuan": cost}
                    parts.append(str(part.get("text") or "").strip())
    except Exception as exc:  # noqa: BLE001 - 切不了就走截断
        print(f"[refine] 分段重识没做成（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return None
    model = ((router.last_cfg if router else cfg) or {}).get("model")
    return {"status": "ok", "kind": "text", "text": "\n\n".join(t for t in parts if t),
            "model": f"{model}（分 {n} 段）", "tiles": n, "cost_yuan": cost, "code": "", "error": None}


def refine_object(source_key: str, source_id: str, cfg: dict[str, Any], *, budget: int = 0,
                  verbose: bool = True, tally: dict[str, Any] | None = None) -> dict[str, Any]:
    """补跑这篇里 refine: pending 的图（一次一张、跑完歇一会）。成功写 refined 并重生成机读版。"""
    from . import usage
    with usage.tag("refine", item=_item_id(source_key, source_id) or source_id):
        return _refine_object(source_key, source_id, cfg, budget=budget, verbose=verbose, tally=tally)


def _refine_object(source_key: str, source_id: str, cfg: dict[str, Any], *, budget: int = 0,
                   verbose: bool = True, tally: dict[str, Any] | None = None) -> dict[str, Any]:
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
    ran = False
    for entry in doc.get("images", []):
        ref = entry.get("refine") or {}
        if repeat_retry_due(ref):
            ref.update({"status": "pending", "repeat_retry": 1})
        if ref.get("status") != "pending":
            continue
        if budget and tally["runs"] >= budget:
            break
        if tally.get("api_streak", 0) >= API_STREAK_STOP:
            break  # 接口连着不通：今晚别再一张张白等
        if tally["runs"]:
            time.sleep(random.uniform(*REFINE_GAP_SECONDS))
        tally["runs"] += 1
        ran = True
        kind = (entry.get("visual") or {}).get("kind") or entry.get("layout") or "text"
        img = storage.object_dir(source_key, source_id) / entry["asset"]
        got, tried = refine_with_fallbacks(img, entry.get("lines"), kind, cfg)
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
            ref.pop("fallback", None)
            if len(tried) > 1:
                ref["healed"] = "；".join(tried[1:])
            if got.get("partial"):
                ref["partial"] = True  # 截到复读前：只保留了有效的前一段  # 当场换参数 / 换模型才成的：留个底
            tally["done"] += 1
            tally["api_streak"] = 0
        elif got.get("ladder_exhausted"):
            # 换参数、换模型都试过了还不合格：当场放弃这张，笔记里继续用第一层的结果（写明）
            ref["tries"] = ref.get("tries", 0) + len(tried)
            ref["status"] = "failed"
            ref["fallback"] = "layer1"
            ref["error"] = got.get("error")
            ref["tried"] = " / ".join(tried)
            tally["api_streak"] = 0
            tally["failed"] += 1
            # 1017 作者裁决：这不是故障、不进问题面板——机读版给这张图标「识图存疑…以原图为准」（stamp_doubt）
        else:
            ref["tries"] = ref.get("tries", 0) + 1
            tally["api_streak"] = 0
            ref["error"] = got.get("error")
            if ref["tries"] >= REFINE_TRIES:
                ref["status"] = "failed"  # 不再每晚重跑；手动点名可以再来
                ref["fallback"] = "layer1"
                tally["failed"] += 1  # 1017：同上，不进问题面板，机读版标存疑
            else:
                tally["retry"] += 1
        entry["refine"] = ref
        stamp_doubt(entry)
        changed = changed or not got.get("api_error") or got.get("status") == "ok"
        if verbose:
            print(f"[refine] {source_id} {entry['asset'].split('/')[-1]}：{ref['status']}"
                  f"（{ref.get('reason')}；{got.get('model')} ¥{got.get('cost_yuan') or 0:.4f}"
                  + (f"；{ref.get('error')}" if ref.get("error") else "") + "）", file=sys.stderr)
        storage.write_json(vpath, doc)  # 每张写一次：中途被打断也不丢已补好的
    if ran:
        # 1017：放弃不再登记；这篇以前登过的「AI 结果不可用」（1008 起按篇一条）跑过就收掉
        retire_refine_problems(_item_id(source_key, source_id))
    if changed:
        render_mod.render_object(source_key, source_id)
    return tally


def repeat_retry_due(ref: dict[str, Any]) -> bool:
    """1016 以前因「出现复读」整图退回第一层的：给一次分段重识 / 截断保留的机会（只一次）。"""
    return ref.get("status") == "failed" and "复读" in str(ref.get("error") or "") and not ref.get("repeat_retry")


def pending_refines() -> list[tuple[str, str, int]]:
    rows = []
    for vpath in sorted((storage.vault_root() / "_archive").glob("*/*/derived/vision.json")):
        try:
            doc = storage.read_json(vpath)
        except (OSError, ValueError):
            continue
        n = sum(1 for e in doc.get("images", []) if (e.get("refine") or {}).get("status") == "pending"
                or repeat_retry_due(e.get("refine") or {}))
        if n:
            rows.append((vpath.parents[2].name, vpath.parents[1].name, n))
    return rows


def run_refine(args) -> int:
    """`vision --refine`：每晚 4 点那一轮调；只跑打了标的图，日志记本晚补了几张、还剩几张、花了多少钱。"""
    from .read import dump_json
    retire_refine_problems()  # 1017：以前登记的精细识图放弃行收掉（幂等）
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
    from . import ai_health, problems
    if tally.get("needs_human"):
        # 1008：key / 欠费归并到 ai.refine 一条（带哪个接口、哪把 key、怎么办）
        ai_health.record("visionAI.refine", {**tally["needs_human"], "api_error": True}, cfg=cfg.last_cfg or fallback)
    elif tally.get("api_streak", 0) >= API_STREAK_STOP:
        ai_health.record("visionAI.refine", {"code": "TRANSIENT.SERVICE_BUSY", "error": "识图接口连着不通，今晚先停，明晚接着补",
                                             "api_error": True}, cfg=cfg.last_cfg or fallback)
    elif tally["runs"]:
        problems.resolve("vision.refine", None)
        ai_health.clear("visionAI.refine")
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
        dump_json({'ok': False, 'code': '', 'message': '没有归档过这篇笔记'})
        return 1
    vpath = storage.derived_dir(row["source"], row["source_id"]) / "vision.json"
    if not vpath.exists():
        print("这篇还没有识图结果", file=sys.stderr)
        dump_json({'ok': False, 'code': '', 'message': '这篇还没有识图结果'})
        return 1
    doc = storage.read_json(vpath)
    marked = 0
    retry_failed = bool(getattr(args, "retry_failed", False))
    for entry in doc.get("images", []):
        if args.asset and not entry["asset"].endswith(args.asset):
            continue
        if (entry.get("visual") or {}).get("kind") == "title":
            continue
        if retry_failed:
            # 当场自愈（问题列表「现在修」）：只把放弃了的那几张重新标上，别把整篇的图都重跑一遍
            if (entry.get("refine") or {}).get("status") == "failed":
                marked += mark_refine(entry, (entry.get("refine") or {}).get("reason") or "重试放弃的图", manual=True)
            continue
        marked += mark_refine(entry, "手动点名", manual=True)
    storage.write_json(vpath, doc)
    out: dict[str, Any] = {"item_id": args.refine_mark, "marked": marked, 'ok': True, 'code': '',
                           'message': f'已记下 {marked} 张图，夜里补跑' if marked else '这篇没有要精细识别的图'}
    if args.now and marked:
        cfg = RefineRouter(strong_config())
        if cfg.keys or cfg.fallback:
            tally = refine_object(row["source"], row["source_id"], cfg)
            out.update(refined=tally["done"], failed=tally["failed"], cost_yuan=round(tally["cost_yuan"], 4))
            out['message'] = f'精细识别完成：{tally["done"]} 张'
            if tally['failed']:
                out['message'] += f'，{tally["failed"]} 张没认准（机读版里已标「识图存疑」，以原图为准）'
        else:
            out.update(code='SKIPPED.NOT_CONFIGURED', message=f'已记下 {marked} 张图；精细识别模型没配，配好后夜里补跑')
    dump_json(out)
    return 0
