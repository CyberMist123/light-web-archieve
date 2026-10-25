"""谁收的（1020 她定）：目录默认只看她自己的收藏，别的按来源分组。

- 她自己的收藏（收藏同步进来的 / 她在电脑上自己导入的）→ ""（主收藏）
- 她在 TG 发给 Fable 的链接 → 「fable」（1023 她定：TG 发来的算 Fable；1025 PR① 起不再单独叫「聊天分享」，`domain.via` 记 "tg"）
- Fable 自己逛到收的 → 「fable」
- CC / GPT 做项目收的 → 项目名（catch --project，比如 graph / ai群聊）；没给项目名就记 actor 名字
后来她自己收藏了同一篇（meta.favorited_by 有值）→ 回到主收藏。
规则本体 1025 挪进 `domain.py`（collected_by / clean_project / FABLE / via），这里留转发；`relabel` 有副作用，留在这里。
"""
from __future__ import annotations

from typing import Any

from . import domain
from .domain import FABLE, clean_project, collected_by, via  # noqa: F401 - 旧 import 路径留着

CHAT_SHARE = "聊天分享"   # 旧分组名（1020–1025），只给认旧值的地方用；新代码别再产生它


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
            source, source_id = domain.parse_item_id(ref) or (xhs.SOURCE, str(ref).strip())
            meta_path = storage.object_dir(source, source_id) / "meta.json"
            if not source_id or not meta_path.exists():
                out.append({"item_id": ref, "status": "missing"})
                continue
            old_meta = storage.read_json(meta_path)
            old = (old_meta.get("origin"), old_meta.get("actor"))

            def change(meta):   # 1025：单篇锁里重读再写，只动 OWNER 的三个键（原来是锁外整份覆写）
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

            meta = storage.update_json(meta_path, change, lock_name=storage.obj_lock_name(
                old_meta.get("item_id") or domain.item_id(source, source_id)))
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
