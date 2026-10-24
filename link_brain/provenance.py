"""谁收的（1020 她定）：目录默认只看她自己的收藏，别的按来源分组。

- 她自己的收藏（收藏同步进来的 / 她在电脑上自己导入的）→ ""（主收藏）
- 她在 TG 发给 Fable 的链接 → 「聊天分享」（不进主收藏的默认显示）
- Fable 自己逛到收的 → 「fable」
- CC / GPT 做项目收的 → 项目名（catch --project，比如 graph / ai群聊）；没给项目名就记 actor 名字
后来她自己收藏了同一篇（meta.favorited_by 有值）→ 回到主收藏。
"""
from __future__ import annotations

from typing import Any

CHAT_SHARE = "聊天分享"


def collected_by(meta: dict[str, Any]) -> str:
    if meta.get("favorited_by") or meta.get("ingest_kind") == "favorite":
        return ""
    actor = str(meta.get("actor") or "human")
    if actor == "human":
        return CHAT_SHARE if meta.get("origin") == "tg" else ""
    project = str(meta.get("project") or "").strip()
    if project:
        return project
    return actor.split(":", 1)[1].strip() if ":" in actor else actor


def clean_project(value: Any) -> str:
    """项目名进目录当分组名：去空白、限长，不许带路径分隔符。"""
    text = " ".join(str(value or "").split())[:40]
    return text.replace("/", "-").replace("\\", "-")


def relabel(refs: list[str], *, actor: str | None = None, origin: str | None = None,
            project: str | None = None) -> list[dict[str, Any]]:
    """改「谁收的」（1020：19 号 CC 调研顺手收的帖被 lwa 记成了她在 TG 分享的）。改 meta + 索引 relations 里对应那行；
    改完自动重建目录（1023）。project="" 表示清掉项目名。"""
    from . import index as index_mod, storage
    from .adapters import xiaohongshu as xhs

    out: list[dict[str, Any]] = []
    conn = index_mod.connect()
    try:
        for ref in refs:
            source_id = str(ref).strip().removeprefix("xhs-")
            meta_path = storage.object_dir(xhs.SOURCE, source_id) / "meta.json"
            if not source_id or not meta_path.exists():
                out.append({"item_id": ref, "status": "missing"})
                continue
            meta = storage.read_json(meta_path)
            old = (meta.get("origin"), meta.get("actor"))
            if actor:
                meta["actor"] = actor
            if origin:
                meta["origin"] = origin
            if project is not None:
                name = clean_project(project)
                if name:
                    meta["project"] = name
                else:
                    meta.pop("project", None)
            storage.write_json(meta_path, meta)
            conn.execute("UPDATE relations SET origin = ?, actor = ? WHERE item_id = ? AND origin = ? AND actor = ?",
                         (meta.get("origin"), meta.get("actor"), meta.get("item_id"), old[0], old[1]))
            out.append({"item_id": meta.get("item_id"), "status": "ok", "src": collected_by(meta)})
        conn.commit()
    finally:
        conn.close()
    if any(o.get("status") == "ok" for o in out):
        from .catalog import ensure_fresh, mark_dirty  # 1023：改完直接进目录，不用再手动跑 catalog
        mark_dirty("改来源")
        ensure_fresh(wait_s=30)
    return out
