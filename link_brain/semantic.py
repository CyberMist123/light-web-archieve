"""Chunk 索引 + embedding 旁挂（Lot B）。

catalog-data.json 的 items 切成 chunk，存独立 SQLite `vault/_archive/semantic.db`
（chunks + embeddings 两表，content-hash 增量）。不动 index.db、不动 catalog-data.json。

**一切 fail-open**：没 key / 没 semantic.db / numpy 缺失 / HTTP 失败时，
`query_hits()` 返回 None，检索退回纯词法，行为与没有本模块时完全一致。
凭据只读内存（env 或仓外 CSV），不落盘、不打印、不进日志。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from array import array
from collections import OrderedDict
from pathlib import Path

from . import storage

DB_NAME = "semantic.db"
# 切块目标：正文/附件/转写 ~200-500 字一块；短字段整块
CHUNK_MIN, CHUNK_MAX = 200, 500
_CHUNK_FIELDS = ("body", "ocr", "attachments", "transcript", "comments")

_QUERY_VEC_CACHE: OrderedDict[str, "object"] = OrderedDict()  # question -> ndarray（只缓存成功）
_QUERY_VEC_CACHE_MAX = 64
_MATRIX_CACHE = {"stamp": None, "data": None}


def db_path() -> Path:
    return storage.archive_root() / DB_NAME


def load_config() -> dict:
    """embedding 节配置；缺失时给 DashScope text-embedding-v4 默认值。"""
    from . import llm
    try:
        cfg = llm.load_config().get("embedding") or {}
    except (OSError, ValueError):
        cfg = {}
    return {"model": cfg.get("model") or "text-embedding-v4",
            "endpoint": (cfg.get("endpoint") or "").strip(),
            "dimensions": cfg.get("dimensions"),
            "query_timeout_sec": float(cfg.get("query_timeout_sec") or 5)}


# --------------------------------------------------------------------------
# 切块
# --------------------------------------------------------------------------

def split_units(text: str) -> list[str]:
    """按标题行 / 空行切自然段；没有段落结构就按句号切。"""
    text = str(text or "").strip()
    if not text:
        return []
    parts = re.split(r"\n{2,}|(?=^#{1,6}\s)", text, flags=re.M)
    units = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= CHUNK_MAX:
            units.append(part)
            continue
        # 超长段按句子再切，硬上限兜底
        buf = ""
        for sent in re.split(r"(?<=[。！？!?；;\n])", part):
            if buf and len(buf) + len(sent) > CHUNK_MAX:
                units.append(buf.strip())
                buf = sent
            else:
                buf += sent
            while len(buf) > CHUNK_MAX:
                units.append(buf[:CHUNK_MAX])
                buf = buf[CHUNK_MAX:]
        if buf.strip():
            units.append(buf.strip())
    return units


def _merge(units: list[str]) -> list[str]:
    """相邻小段合并到 200-500 字，别把一句话切成一个 chunk。"""
    merged: list[str] = []
    buf = ""
    for unit in units:
        if buf and len(buf) + 1 + len(unit) > CHUNK_MAX:
            merged.append(buf)
            buf = unit
        else:
            buf = (buf + "\n" + unit) if buf else unit
    if buf:
        merged.append(buf)
    return merged


def chunk_item(item: dict) -> list[tuple[str, int, str]]:
    """一个 item -> [(field, seq, text)]。meta 块让「换个说法搜标题」也有向量可比。"""
    out: list[tuple[str, int, str]] = []
    meta = " ".join(x for x in [str(item.get("title") or ""),
                                " ".join(item.get("tags") or []),
                                str(item.get("summary") or "")] if x.strip()).strip()
    if meta:
        out.append(("meta", 0, meta[:CHUNK_MAX]))
    fields = item.get("search_fields") or {}
    for field in _CHUNK_FIELDS:
        value = fields.get(field) or ("" if field != "body" else item.get("search_text") or "")
        for seq, text in enumerate(_merge(split_units(str(value)))):
            if len(text.strip()) >= 8:  # 太短的碎屑没有语义信息
                out.append((field, seq, text))
    return out


def content_hash(model: str, text: str) -> str:
    return hashlib.sha256((model + "\x00" + text).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# 库
# --------------------------------------------------------------------------

def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()))
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS chunks("
        " item_id TEXT NOT NULL, field TEXT NOT NULL, seq INTEGER NOT NULL,"
        " text TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(item_id, field, seq));"
        "CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(hash);"
        "CREATE TABLE IF NOT EXISTS embeddings("
        " hash TEXT PRIMARY KEY, model TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL);")
    return conn


def sync_chunks(conn: sqlite3.Connection, items: list[dict], model: str) -> dict:
    """chunks 表重建成 catalog 当前状态；embeddings 按 hash 保留（增量的依据）。"""
    rows = []
    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        for field, seq, text in chunk_item(item):
            rows.append((item_id, field, seq, text, content_hash(model, text)))
    conn.execute("DELETE FROM chunks")
    conn.executemany("INSERT INTO chunks(item_id, field, seq, text, hash) VALUES(?,?,?,?,?)", rows)
    # 清掉不再被任何 chunk 引用的旧向量
    conn.execute("DELETE FROM embeddings WHERE hash NOT IN (SELECT DISTINCT hash FROM chunks)")
    conn.commit()
    return {"chunks": len(rows), "items": len({r[0] for r in rows})}


# --------------------------------------------------------------------------
# Provider：OpenAI 兼容 /embeddings（默认 DashScope text-embedding-v4）
# --------------------------------------------------------------------------

def _endpoint_and_key(cfg: dict) -> tuple[str, str]:
    """key 取法与问答通路完全一致（env DASHSCOPE_API_KEY 或仓外 CSV）；不落盘不打印。"""
    from .text_stream import default_http_config
    base_cfg = default_http_config({})
    key = base_cfg.get("apiKey") or ""
    endpoint = cfg.get("endpoint") or ""
    if not endpoint:
        chat = base_cfg.get("endpoint") or ""
        endpoint = chat.rsplit("/chat/completions", 1)[0].rstrip("/") + "/embeddings"
    return endpoint, key


def _post_embeddings(texts: list[str], cfg: dict, timeout: float) -> list[list[float]]:
    """一次 HTTP 批量取向量；失败抛异常，由调用方决定告警或退词法。"""
    import httpx
    endpoint, key = _endpoint_and_key(cfg)
    if not key:
        raise RuntimeError("no-api-key")
    body = {"model": cfg["model"], "input": texts}
    if cfg.get("dimensions"):
        body["dimensions"] = int(cfg["dimensions"])
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key.strip()}
    resp = httpx.post(endpoint, headers=headers, json=body, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"embeddings HTTP {resp.status_code}")
    data = resp.json().get("data") or []
    if len(data) != len(texts):
        raise RuntimeError("embeddings 返回数量不符")
    ordered = sorted(data, key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in ordered]


# --------------------------------------------------------------------------
# embed 子命令
# --------------------------------------------------------------------------

def run_embed(re_embed: bool = False, batch_size: int = 10) -> dict:
    """增量 embed；`re_embed=True` 全部重算。失败只报状态，不影响其它链路。"""
    from .ask import load_items
    cfg = load_config()
    items = load_items()
    if not items:
        return {"status": "failed", "error": "catalog-data.json 里没有 items，先跑 catalog"}
    conn = connect()
    try:
        info = sync_chunks(conn, items, cfg["model"])
        if re_embed:
            conn.execute("DELETE FROM embeddings")
            conn.commit()
        pending = [r[0] for r in conn.execute(
            "SELECT DISTINCT hash FROM chunks WHERE hash NOT IN (SELECT hash FROM embeddings)")]
        texts = {h: t for h, t in conn.execute(
            "SELECT hash, MIN(text) FROM chunks GROUP BY hash") if h in set(pending)}
        embedded = failed = 0
        error = None
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            try:
                vectors = _post_embeddings([texts[h] for h in batch], cfg, timeout=30)
            except Exception as exc:  # noqa: BLE001 - 网络/配置错误一律告警收尾，不炸调用方
                failed += len(pending) - start
                error = type(exc).__name__ if not isinstance(exc, RuntimeError) else str(exc)
                break
            for h, vec in zip(batch, vectors):
                blob = array("f", vec).tobytes()
                conn.execute("INSERT OR REPLACE INTO embeddings(hash, model, dim, vector) VALUES(?,?,?,?)",
                             (h, cfg["model"], len(vec), blob))
            conn.commit()
            embedded += len(batch)
        done = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    finally:
        conn.close()
    _MATRIX_CACHE.update(stamp=None, data=None)
    result = {"status": "ok" if not failed else "failed", "model": cfg["model"],
              "items": info["items"], "chunks": info["chunks"],
              "embedded_now": embedded, "embedded_total": done,
              "skipped": max(0, len(pending) - embedded - failed),
              "pending_before": len(pending)}
    if error:
        result["error"] = f"embedding 调用失败（{error}）；已完成 {embedded}/{len(pending)}，下次增量续跑"
    return result


# --------------------------------------------------------------------------
# 查询侧：暴力余弦 + fail-open
# --------------------------------------------------------------------------

def _load_matrix(model: str):
    """chunk 向量矩阵，按 db mtime 缓存。返回 (matrix, rows) 或 None。"""
    import numpy as np
    path = db_path()
    stamp = (str(path), path.stat().st_mtime_ns, model)
    if _MATRIX_CACHE["stamp"] == stamp:
        return _MATRIX_CACHE["data"]
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT c.item_id, c.field, c.text, e.dim, e.vector FROM chunks c"
            " JOIN embeddings e ON e.hash = c.hash WHERE e.model = ?", (model,)).fetchall()
    finally:
        conn.close()
    if not rows:
        data = None
    else:
        dim = rows[0][3]
        rows = [r for r in rows if r[3] == dim]
        matrix = np.frombuffer(b"".join(r[4] for r in rows), dtype=np.float32).reshape(len(rows), dim)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1
        matrix = matrix / norms[:, None]
        data = (matrix, [(r[0], r[1], r[2]) for r in rows])
    _MATRIX_CACHE.update(stamp=stamp, data=data)
    return data


def query_vector(question: str):
    """查询向量，LRU 缓存成功结果；任何失败返回 None（不缓存失败）。"""
    import numpy as np
    question = (question or "").strip()
    if not question:
        return None
    if question in _QUERY_VEC_CACHE:
        _QUERY_VEC_CACHE.move_to_end(question)
        return _QUERY_VEC_CACHE[question]
    cfg = load_config()
    try:
        vec = _post_embeddings([question[:2000]], cfg, timeout=cfg["query_timeout_sec"])[0]
    except Exception:  # noqa: BLE001 - 查询侧任何失败都退纯词法
        return None
    arr = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(arr))
    if not n:
        return None
    arr = arr / n
    _QUERY_VEC_CACHE[question] = arr
    while len(_QUERY_VEC_CACHE) > _QUERY_VEC_CACHE_MAX:
        _QUERY_VEC_CACHE.popitem(last=False)
    return arr


def query_hits(question: str, top_chunks: int = 80, chunks_per_item: int = 2):
    """chunk 余弦扫描 → item 取 max。

    返回 {item_id: {"score": float, "chunks": [{"field","text","score"}...]}}；
    没 db / 没 key / 缺 numpy / HTTP 失败一律返回 None（fail-open）。
    """
    try:
        if not db_path().is_file():
            return None
        import numpy as np  # noqa: F401 - import 失败即退词法
        cfg = load_config()
        data = _load_matrix(cfg["model"])
        if not data:
            return None
        qvec = query_vector(question)
        if qvec is None:
            return None
        matrix, rows = data
        if matrix.shape[1] != qvec.shape[0]:
            return None
        sims = matrix @ qvec
        order = sims.argsort()[::-1][:top_chunks]
        hits: dict[str, dict] = {}
        for idx in order:
            item_id, field, text = rows[int(idx)]
            score = float(sims[int(idx)])
            entry = hits.setdefault(item_id, {"score": score, "chunks": []})
            entry["score"] = max(entry["score"], score)
            if len(entry["chunks"]) < chunks_per_item:
                entry["chunks"].append({"field": field, "text": text, "score": round(score, 4)})
        return hits
    except Exception:  # noqa: BLE001 - 硬约束：语义层任何异常都不许影响词法检索
        return None


def run(args) -> int:
    from .read import dump_json
    result = run_embed(re_embed=getattr(args, "all", False))
    dump_json(result)
    return 0 if result.get("status") == "ok" else 1
