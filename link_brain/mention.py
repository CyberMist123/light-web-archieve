"""批注里 @ 她的 AI（1020 她定）：「@名字」开头的批注 → 交给通知命令送到 AI 那里；AI 的回复落回同一个批注框。

- 打标在前端（annotate-view.js：设置「批注留言对象」填了名字才开，`to_fable=true`）和 `note add`。
- `note notify`：扫全库 notes.json，没送过的 to_fable 批注一条一条交给通知命令（stdin 一个 JSON），
  成功才记进 `~/.link-brain/mention-notified.json`——同一条只送一次，改了 / 删了不重送。
  定时跑（手机上写的批注插件够不着 Python，只能靠扫）；送到之后怎么递、什么时候叫 AI 是通知命令的事。
- 通知命令：环境变量 `LINK_BRAIN_NOTIFY_CMD` 优先，其次 `~/.link-brain/notify-cmd.txt` 第一行（同 alert-cmd.txt 的写法）。
  没配就什么都不送、也不记账（配上以后照样补送）。
- `note reply`：AI 回一条，写进同一个 notes.json（`reply_to` 指着被回的那条，`author` 显示名字），
  批注框里显示在她那条下面；前端保存时先读盘再合并，所以不会被覆盖。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import note as note_mod, storage
from .errtext import errtext

ENV_NOTIFY_CMD = "LINK_BRAIN_NOTIFY_CMD"
DISPLAY = {"fable": "Fable", "gpt": "GPT", "claude": "Claude"}


def _home() -> Path:
    return Path(os.environ.get("LINK_BRAIN_HOME") or str(Path.home() / ".link-brain"))


def notify_command() -> str:
    command = os.environ.get(ENV_NOTIFY_CMD, "").strip()
    if command:
        return command
    try:
        text = (_home() / "notify-cmd.txt").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def _ledger_path() -> Path:
    return _home() / "mention-notified.json"


def _load_ledger() -> dict[str, str]:
    try:
        data = json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _key(item_id: str, annot: dict[str, Any]) -> str:
    return f"{item_id}:{annot.get('id') or annot.get('ts') or ''}"


def pending() -> list[dict[str, Any]]:
    """没送过的 @ 批注（旧→新）。读不了的 notes.json 跳过（不动它）。"""
    ledger = _load_ledger()
    out: list[dict[str, Any]] = []
    root = storage.archive_root()
    for path in sorted(root.glob("*/*/notes.json")):
        source, source_id = path.parent.parent.name, path.parent.name
        try:
            data = note_mod.load_notes(source, source_id)
        except note_mod.NotesCorrupt:
            continue
        annots = [a for a in note_mod.live_annotations(data) if a.get("to_fable") and not a.get("reply_to")]
        if not annots:
            continue
        meta = {}
        try:
            meta = json.loads((path.parent / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        item_id = meta.get("item_id") or f"xhs-{source_id}"
        for a in annots:
            if _key(item_id, a) in ledger:
                continue
            out.append({
                "kind": "mention",
                "item_id": item_id,
                "source_id": source_id,
                "title": meta.get("title") or "",
                "visible_note": meta.get("visible_note") or "",
                "annot_id": a.get("id") or "",
                "text": str(a.get("text") or "").strip(),
                "ts": a.get("ts") or "",
            })
    out.sort(key=lambda p: str(p["ts"]))
    return out


def _send(command: str, payload: dict[str, Any]) -> tuple[bool, str]:
    try:
        # 同 alert._run：命令行是她自己配的，交给 shell 拆（Windows 带引号路径 shlex 拆不对）
        proc = subprocess.run(command, shell=True, input=json.dumps(payload, ensure_ascii=False),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except Exception as exc:  # noqa: BLE001 - 一条送不出去不该拖垮整轮
        return False, errtext(exc)
    if proc.returncode != 0:
        return False, f"退出码 {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
    return True, ""


def notify_pending(*, dry_run: bool = False) -> dict[str, Any]:
    rows = pending()
    command = notify_command()
    if dry_run or not rows:
        return {"ok": True, "pending": len(rows), "sent": 0, "items": rows if dry_run else []}
    if not command:
        return {"ok": True, "pending": len(rows), "sent": 0, "note": "没配通知命令（notify-cmd.txt），先不送"}
    ledger = _load_ledger()
    sent, errors = 0, []
    for row in rows:
        ok, why = _send(command, row)
        if ok:
            ledger[_key(row["item_id"], {"id": row["annot_id"], "ts": row["ts"]})] = \
                datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            sent += 1
        else:
            errors.append(f"{row['item_id']}:{row['annot_id']} {why}")
    if sent:
        storage.write_json(_ledger_path(), ledger)
    return {"ok": not errors, "pending": len(rows), "sent": sent, "errors": errors}


def reply(target: str, annot_id: str, text: str, *, actor: str = "fable") -> dict[str, Any]:
    obj = note_mod.resolve(target)
    if obj is None:
        return {"target": target, "status": "missing"}
    text = (text or "").strip()
    if not text:
        return {"item_id": obj["item_id"], "status": "empty"}
    data = note_mod.load_notes(obj["source"], obj["source_id"])
    if not any(a.get("id") == annot_id for a in note_mod.live_annotations(data)):
        return {"item_id": obj["item_id"], "status": "no_such_annotation", "annot_id": annot_id}
    who = actor.split(":", 1)[-1].lower()
    entry = {
        "id": "a" + uuid.uuid4().hex[:12],
        # 和 annotate-view.js 的 new Date().toISOString() 同一格式（UTC、Z 结尾）：前端按字符串排时间，混格式会排乱
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "text": text,
        "to_fable": False,
        "author": DISPLAY.get(who, who),
        "by": actor if ":" in actor else f"ai:{who}",
        "reply_to": annot_id,
    }
    data["annotations"].append(entry)
    note_mod.save_notes(obj["source"], obj["source_id"], data)
    return {"item_id": obj["item_id"], "status": "ok", "annotation": entry}


def run(args) -> int:
    sub = getattr(args, "note_command", None)
    try:
        if sub == "notify":
            out = notify_pending(dry_run=getattr(args, "dry_run", False))
            print(json.dumps(out, ensure_ascii=False))
            return 0 if out["ok"] else 1
        out = reply(args.target, args.annot_id, args.text, actor=getattr(args, "as_actor", "fable") or "fable")
    except note_mod.NotesCorrupt as exc:
        print(str(exc), file=sys.stderr)
        out = {"status": "corrupt", "error": str(exc)}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("status") == "ok" else 1
