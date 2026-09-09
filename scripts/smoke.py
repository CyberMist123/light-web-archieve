"""端到端自检（TASKBOOK Lot 5）：串一遍 18060 → RAW → 图片 → vision → 可见 md → agent.md → SQLite → read。

    python scripts/smoke.py "<小红书链接或分享文案>"      # 全链路，要联网 + 18060 活着
    python scripts/smoke.py --offline <item_id>          # 只验库里已有对象的下游（不联网）

成功打 PASS；失败明着说卡在哪一步，别让人猜。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from link_brain import comments as comments_mod  # noqa: E402
from link_brain import index as index_mod  # noqa: E402
from link_brain import storage  # noqa: E402

STEPS: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    STEPS.append((name, "ok" if ok else f"FAIL {detail}".strip()))
    return ok


def verify_object(item_id: str) -> bool:
    vault = storage.vault_root()
    conn = index_mod.connect()
    try:
        row = index_mod.get_object(conn, item_id)
    finally:
        conn.close()
    if not check("SQLite 有这条", row is not None, item_id):
        return False

    object_dir = vault / row["object_dir"]
    meta_path = object_dir / "meta.json"
    if not check("meta.json 在", meta_path.is_file(), str(meta_path)):
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    raw = object_dir / "raw" / f"v{meta['current_version']:04d}"
    check("RAW 封存了", (raw / "source.json").is_file(), str(raw))
    manifest_path = raw / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        declared = manifest.get("images_declared", 0)
        ok = manifest.get("images_ok", 0) == declared
        check("图片下全", ok, f"{manifest.get('images_ok')}/{declared}")

    agent_md = object_dir / "derived" / "agent.md"
    check("agent.md 生成了", agent_md.is_file(), str(agent_md))

    visible = meta.get("visible_note")
    vis_path = vault / visible if visible else None
    if not check("可见 md 在", bool(vis_path and vis_path.is_file()), str(visible)):
        return False
    text = vis_path.read_text(encoding="utf-8")
    check("留言层标记在", "link-brain:comments:start" in text)
    check("content 层在", "link-brain:content:start" in text)
    check("留言层解析得动", isinstance(comments_mod.read_comments(vis_path), list))
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="链接 / 分享文案；--offline 时是 item_id")
    ap.add_argument("--offline", action="store_true", help="不联网，只验库里已有对象的下游")
    args = ap.parse_args()
    if not args.target:
        ap.error("要给一个链接（或 --offline <item_id>）")

    item_id = args.target
    if not args.offline:
        from link_brain import ingest as ingest_mod

        try:
            summary = ingest_mod.ingest_url(args.target, origin="cli", actor="human")
            item_id = summary["item_id"]
            check("抓取（18060 → RAW）", True, item_id)
        except Exception as exc:  # noqa: BLE001 — 自检脚本要把任何炸法都报出来
            check("抓取（18060 → RAW）", False, f"{type(exc).__name__}: {exc}")
            _report()
            return 1

    ok = verify_object(item_id)
    return _report() if ok else _report(force_fail=True)


def _report(force_fail: bool = False) -> int:
    failed = [f"{n}: {s}" for n, s in STEPS if s != "ok"]
    for name, state in STEPS:
        print(f"  {'✓' if state == 'ok' else '✗'} {name}" + ("" if state == "ok" else f" — {state}"))
    if failed or force_fail:
        print("FAIL —— 卡在：" + "; ".join(failed) if failed else "FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
