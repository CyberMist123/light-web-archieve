"""答案缓存（Lot D）：同类问题再来时，知道以前答过、此后又多了哪些收藏。

`vault/_archive/answers.json` 追加式索引（vault 整体 gitignored，回答原文不进仓）：
每条 {id, ts, question, terms, item_ids, item_titles, export_path, first_line, vec?}。

- ask 成功生成回答后 `record()` 记一条；导出时 `attach_export()` 回填 export_path。
- 新问题先 `lookup()`：有语义层（semantic.db 在、查询向量拿得到）用余弦比历史问题向量，
  没有就比 terms 的 Jaccard 重叠。
- 命中后 ask 往模型上下文注入 `context_block()`，回答开头加 `hint_line()` 一行。

**一切 fail-open**：answers.json 缺 / 坏 / 没向量 / 任何异常 = 当全新问题，ask 行为与没有
本模块时一致。写入走临时文件 + os.replace；坏文件挪成 answers.json.corrupt 后重新开始。

真机探针：`python -m link_brain.answer_cache probe "问题"`（看历史问题相似度，不调模型）；
`python -m link_brain.answer_cache list`（最近几条，不打印回答原文以外的内容）。
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import tempfile
import uuid
from array import array
from datetime import datetime
from pathlib import Path

from . import storage

INDEX_NAME = "answers.json"
# 语义阈值：问题对问题的余弦（embedding 单位向量）。换说法的同一问 ≥0.8，同领域不同问
# 多在 0.6-0.75；提示行是用户可见的，宁漏勿错，取 0.80。
SEM_THRESHOLD = 0.80
# 词法阈值：cache_terms 的 Jaccard（只在没向量时用，是兜底）。实测：
# 睡不好怎么办/晚上睡不好怎么改善 1.0、英语口语 0.75、AI记忆层项目两种问法 0.67、
# Claude Code 插件两种问法 0.75 → 命中；上海周末去哪玩/遛娃去哪 0.43、AI会做梦吗/AI做梦的记忆 0.5、
# 记忆层 vs 减脂餐 0、猫粮 vs 狗粮 0 → 不命中。已知误命中：只差地名的问法（上海/成都吃火锅 0.67），
# 词法没有实体权重，接受——有语义层时以向量为准。
TERM_THRESHOLD = 0.6
TERM_MIN_SHARED = 2
FIRST_LINE_MAX = 160


def index_path() -> Path:
    return storage.archive_root() / INDEX_NAME


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 读写（fail-open + 原子）
# --------------------------------------------------------------------------

def _valid(entry) -> bool:
    return (isinstance(entry, dict) and isinstance(entry.get("question"), str)
            and isinstance(entry.get("ts"), str) and _parse_ts(entry["ts"]) is not None
            and isinstance(entry.get("item_ids", []), list))


def load() -> list[dict]:
    """全部有效条目；文件缺失/坏/结构不对一律返回 []。"""
    try:
        data = json.loads(index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [e for e in entries if _valid(e)]


def _save(entries: list[dict]) -> None:
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".answers-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "entries": entries}, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_for_write() -> list[dict]:
    """写之前读：文件存在但解析不了就挪到 .corrupt 留证，再从空开始（不静默覆盖）。"""
    path = index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return [e for e in data["entries"] if _valid(e)]
    except (OSError, ValueError):
        pass
    try:
        os.replace(path, path.with_name(INDEX_NAME + ".corrupt"))
    except OSError:
        pass
    return []


# --------------------------------------------------------------------------
# 相似度
# --------------------------------------------------------------------------

_FILLER = set("和与的跟及或哪吗呢了个吧啊么")


def cache_terms(terms) -> list[str]:
    """把 ask.query_terms 的检索词收窄成「比问题像不像」用的词：
    丢单字（睡/办/哪）、丢含虚字的二字切片（梦和/和记）、丢能被 ≥2 个其它词拼出来的整句块
    （做梦和记忆 = 做梦+记忆），否则连接词和整句块会把同一问的重叠率拉低。"""
    ts = list(dict.fromkeys(str(t) for t in (terms or []) if len(str(t)) >= 2))
    ts = [t for t in ts if not (re.fullmatch(r"[一-鿿]{2}", t) and set(t) & _FILLER)]
    return [t for t in ts if not (len(t) >= 4 and sum(1 for o in ts if o != t and o in t) >= 2)]


def term_overlap(a, b) -> tuple[float, int]:
    A, B = set(cache_terms(a)), set(cache_terms(b))
    if not A or not B:
        return 0.0, 0
    shared = len(A & B)
    return shared / len(A | B), shared


def _encode_vec(vec) -> str:
    return base64.b64encode(array("f", [float(x) for x in vec]).tobytes()).decode("ascii")


def _decode_vec(text) -> list[float] | None:
    try:
        arr = array("f")
        arr.frombytes(base64.b64decode(text))
        return list(arr)
    except (ValueError, TypeError):
        return None


def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def question_vector(question: str):
    """查询向量（与 hybrid 检索共用 semantic 的 LRU，不额外发 HTTP）；
    语义层不可用（没 semantic.db / 没 key / 失败）返回 None。"""
    try:
        from . import semantic
        if not semantic.db_path().is_file():
            return None
        vec = semantic.query_vector(question)
        if vec is None:
            return None
        return {"model": semantic.load_config()["model"], "v": [float(x) for x in vec]}
    except Exception:  # noqa: BLE001 - fail-open
        return None


def lookup(question: str, terms, entries: list[dict] | None = None, qvec=None):
    """最像的一条历史问答；没有达到阈值返回 None。

    两边都有同模型向量 → 余弦 ≥ SEM_THRESHOLD；否则 → terms Jaccard ≥ TERM_THRESHOLD
    且至少共享 TERM_MIN_SHARED 个词。语义命中优先于词法命中；同分取较新。
    返回 entry 的拷贝，附 match={"method","score"}。
    """
    try:
        entries = load() if entries is None else entries
        if not entries:
            return None
        best = None  # (rank_key, entry, method, score)
        for entry in entries:
            method, value = None, 0.0
            stored = entry.get("vec") if isinstance(entry.get("vec"), dict) else None
            if qvec and stored and stored.get("model") == qvec.get("model"):
                vec = _decode_vec(stored.get("b64"))
                if vec and len(vec) == len(qvec["v"]):
                    value = cosine(qvec["v"], vec)
                    method = "semantic" if value >= SEM_THRESHOLD else None
                    if method is None:
                        continue  # 有可比向量就以向量为准，不再用词法兜底
            if method is None:
                value, shared = term_overlap(terms, entry.get("terms"))
                if value < TERM_THRESHOLD or shared < TERM_MIN_SHARED:
                    continue
                method = "terms"
            key = (method == "semantic", round(value, 6), entry["ts"])
            if best is None or key > best[0]:
                best = (key, entry, method, value)
        if not best:
            return None
        hit = dict(best[1])
        hit.pop("vec", None)
        hit["match"] = {"method": best[2], "score": round(best[3], 4)}
        return hit
    except Exception:  # noqa: BLE001 - fail-open：缓存任何问题都当全新问题
        return None


# --------------------------------------------------------------------------
# 「此后新增」与注入
# --------------------------------------------------------------------------

def _parse_ts(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.astimezone()


def newer_items(items, since_ts) -> list[dict]:
    """入库时间（item.ts = first_archived_at）严格晚于 since_ts 的那些；保持原顺序。
    入库时间缺失/解析不了的不算新。"""
    since = _parse_ts(since_ts)
    if since is None:
        return []
    out = []
    for it in items or []:
        ts = _parse_ts(it.get("ts")) if it.get("ts") else None
        if ts is not None and ts > since:
            out.append(it)
    return out


def date_label(ts) -> str:
    dt = _parse_ts(ts)
    return dt.astimezone().strftime("%Y-%m-%d") if dt else "日期不详"


def hint_line(hit, new_count: int) -> str:
    day = date_label(hit.get("ts"))
    if new_count:
        return f"> 以前问过类似问题（{day}），本次结合 {new_count} 条新材料"
    return f"> 以前问过类似问题（{day}），此后没有新增相关收藏，结论沿用"


def context_block(hit, items_by_id: dict, new_sources: list[dict]) -> str:
    """给模型的缓存上下文。new_sources: 本次材料里「此后新增」的那些 source（带 citation）。"""
    titles = []
    for i, item_id in enumerate(hit.get("item_ids") or []):
        it = items_by_id.get(item_id)
        stored = (hit.get("item_titles") or [])
        title = (it or {}).get("title") or (stored[i] if i < len(stored) else "") or "（已移除的收藏）"
        titles.append(f"《{title}》")
    lines = ["【以前问过类似问题——仅供对照，不是事实来源】",
             f"上次问题（{date_label(hit.get('ts'))}）：{hit.get('question', '')}",
             "当时用的收藏：" + ("、".join(titles) if titles else "（无记录）")]
    if hit.get("first_line"):
        lines.append("上次回答开头：" + str(hit["first_line"]))
    if new_sources:
        lines.append("此后新增的相关收藏（已在下方原始材料中）：" + "、".join(
            f"《{s.get('title')}》[来源{s.get('citation')}]" for s in new_sources))
        lines.append("请以本次原始材料为准，重点说明新增收藏带来的补充或变化；与上次一致的部分可简述沿用。")
    else:
        lines.append("此后新增的相关收藏：无。请以本次原始材料为准作答，结论可沿用上次。")
    lines.append("回答开头不要自己写「以前问过」之类的提示，系统会加。")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 记录与导出回填
# --------------------------------------------------------------------------

def first_line(markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        line = line.strip().lstrip("#>").strip()
        if line and not line.startswith("以前问过类似问题"):
            return line[:FIRST_LINE_MAX]
    return ""


def record(question: str, terms, sources: list[dict], markdown: str, qvec=None, ts: str | None = None):
    """追加一条；任何失败静默返回 None（不许影响回答本身）。"""
    try:
        entry = {"id": uuid.uuid4().hex[:12], "ts": ts or now_iso(), "question": question,
                 "terms": list(terms or []),
                 "item_ids": [s.get("id") for s in sources if s.get("id")],
                 "item_titles": [s.get("title") or "" for s in sources if s.get("id")],
                 "export_path": None, "first_line": first_line(markdown)}
        if qvec and qvec.get("v"):
            entry["vec"] = {"model": qvec.get("model"), "b64": _encode_vec(qvec["v"])}
        entries = _load_for_write()
        entries.append(entry)
        _save(entries)
        return entry
    except Exception:  # noqa: BLE001 - fail-open
        return None


def attach_export(question: str, asked_at, export_path) -> bool:
    """导出时回填 export_path：同一问题里 ts 离 asked_at 最近（24h 内）的一条；
    asked_at 不详就取最新一条还没回填的。找不到就算了（返回 False）。"""
    try:
        question = (question or "").strip()
        entries = _load_for_write()
        same = [e for e in entries if e.get("question", "").strip() == question]
        if not same:
            return False
        asked = _parse_ts(asked_at) if asked_at and asked_at != "unknown" else None
        if asked:
            scored = [(abs((_parse_ts(e["ts"]) - asked).total_seconds()), e) for e in same]
            scored = [x for x in scored if x[0] <= 86400]
            if not scored:
                return False
            target = min(scored, key=lambda x: x[0])[1]
        else:
            pending = [e for e in same if not e.get("export_path")] or same
            target = max(pending, key=lambda e: _parse_ts(e["ts"]))
        path = Path(export_path)
        try:
            rel = path.resolve().relative_to(storage.vault_root().resolve()).as_posix()
        except ValueError:
            rel = str(path)
        target["export_path"] = rel
        _save(entries)
        return True
    except Exception:  # noqa: BLE001 - fail-open：回填失败不许挡导出
        return False


# --------------------------------------------------------------------------
# 真机探针（不改 cli.py，模块自带入口）
# --------------------------------------------------------------------------

def _main(argv=None) -> int:
    import argparse
    import sys
    from .read import dump_json
    parser = argparse.ArgumentParser(prog="python -m link_brain.answer_cache")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("-n", type=int, default=10)
    probe = sub.add_parser("probe")
    probe.add_argument("question")
    args = parser.parse_args(argv)
    entries = load()
    if args.cmd == "list":
        dump_json({"path": str(index_path()), "total": len(entries), "recent": [
            {k: e.get(k) for k in ("ts", "question", "item_ids", "export_path", "first_line")}
            | {"has_vec": bool(e.get("vec"))} for e in entries[-args.n:]]})
        return 0
    from .ask import query_terms
    terms = query_terms(args.question)
    qvec = question_vector(args.question)
    rows = []
    for e in entries:
        stored = e.get("vec") or {}
        vec = _decode_vec(stored.get("b64")) if qvec and stored.get("model") == qvec["model"] else None
        rows.append({"ts": e["ts"], "question": e["question"],
                     "cosine": round(cosine(qvec["v"], vec), 4) if vec else None,
                     "jaccard": round(term_overlap(terms, e.get("terms"))[0], 4)})
    rows.sort(key=lambda r: (r["cosine"] or 0, r["jaccard"]), reverse=True)
    hit = lookup(args.question, terms, entries, qvec)
    dump_json({"semantic": bool(qvec), "thresholds": {"cosine": SEM_THRESHOLD, "jaccard": TERM_THRESHOLD},
               "hit": {k: hit.get(k) for k in ("ts", "question", "match")} if hit else None,
               "top": rows[:10]})
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
