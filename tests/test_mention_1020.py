"""1020 批注 @Fable 打通：note notify 把没送过的 @ 批注交给通知命令（只送一次、失败不记账）；
note reply 让 AI 回进同一个 notes.json；prune-comments 清掉 system 留在正文留言层的「收好了」。"""

from __future__ import annotations

import json
import sys

from link_brain import cli, comments as comments_mod, note as note_mod, storage
from link_brain.adapters import xiaohongshu as xhs

from test_catch import NOTE_ID, XHS_URL, load_fixture, setup_env


def _archived(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    assert cli.main(["catch", XHS_URL, "--origin", "tg", "--actor", "human"]) == 0
    capsys.readouterr()


def _notify_cmd(tmp_path, *, fail: bool = False) -> tuple[str, object]:
    out = tmp_path / ("failed.jsonl" if fail else "sent.jsonl")
    script = tmp_path / ("notify-fail.py" if fail else "notify.py")
    script.write_text(
        "import sys\n"
        f"open(r'{out}', 'a', encoding='utf-8').write(sys.stdin.read() + '\\n')\n"
        + ("sys.exit(3)\n" if fail else ""),
        encoding="utf-8")
    return f'"{sys.executable}" "{script}"', out


def _sent(path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def test_notify_sends_each_mention_once(tmp_path, monkeypatch, capsys):
    _archived(tmp_path, monkeypatch, capsys)
    note_mod.add_annotation(NOTE_ID, "普通批注")
    added = note_mod.add_annotation(NOTE_ID, "@fable 这个你怎么看")["annotation"]

    assert cli.main(["note", "notify"]) == 0           # 没配命令：不送、不记账
    assert json.loads(capsys.readouterr().out)["sent"] == 0

    cmd, sent = _notify_cmd(tmp_path, fail=True)
    monkeypatch.setenv("LINK_BRAIN_NOTIFY_CMD", cmd)
    assert cli.main(["note", "notify"]) == 1           # 送失败：不记账，下次再送
    capsys.readouterr()

    cmd, sent = _notify_cmd(tmp_path)
    monkeypatch.setenv("LINK_BRAIN_NOTIFY_CMD", cmd)
    assert cli.main(["note", "notify"]) == 0
    assert json.loads(capsys.readouterr().out)["sent"] == 1
    rows = _sent(sent)
    assert len(rows) == 1 and rows[0]["kind"] == "mention"
    assert rows[0]["annot_id"] == added["id"] and rows[0]["text"] == "@fable 这个你怎么看"
    assert rows[0]["item_id"] == f"xhs-{NOTE_ID}" and rows[0]["title"]

    assert cli.main(["note", "notify"]) == 0           # 第二轮：已送过
    assert json.loads(capsys.readouterr().out)["sent"] == 0
    assert len(_sent(sent)) == 1


def test_reply_lands_under_the_annotation_and_is_not_itself_sent(tmp_path, monkeypatch, capsys):
    _archived(tmp_path, monkeypatch, capsys)
    added = note_mod.add_annotation(NOTE_ID, "@fable 看看")["annotation"]
    assert cli.main(["note", "reply", NOTE_ID, added["id"], "我看了，挺好"]) == 0
    out = json.loads(capsys.readouterr().out)
    entry = out["annotation"]
    assert (entry["reply_to"], entry["author"], entry["by"], entry["to_fable"]) == (added["id"], "Fable", "ai:fable", False)
    assert entry["ts"].endswith("Z")                   # 和前端同一格式
    data = note_mod.load_notes(xhs.SOURCE, NOTE_ID)
    assert [a["text"] for a in data["annotations"]] == ["@fable 看看", "我看了，挺好"]

    assert cli.main(["note", "reply", NOTE_ID, "a-nope", "x"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "no_such_annotation"

    cmd, sent = _notify_cmd(tmp_path)
    monkeypatch.setenv("LINK_BRAIN_NOTIFY_CMD", cmd)
    cli.main(["note", "notify"])
    capsys.readouterr()
    assert [r["annot_id"] for r in _sent(sent)] == [added["id"]], "回复不会被当成 @ 再送一遍"


def test_prune_removes_only_system_comments(tmp_path, monkeypatch, capsys):
    _archived(tmp_path, monkeypatch, capsys)
    item_id = f"xhs-{NOTE_ID}"
    comments_mod.add_comment(item_id, "「x」收好了，图和概要都转完了", actor="system", target="fable")
    comments_mod.add_comment(item_id, "这条留给 Fable 看", actor="human", target="fable")
    assert cli.main(["prune-comments", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["removed"] == 1
    assert cli.main(["prune-comments"]) == 0
    assert json.loads(capsys.readouterr().out) | {"dry_run": False} == {"ok": True, "actor": "system", "notes": 1,
                                                                        "removed": 1, "dry_run": False}
    meta = storage.read_json(storage.object_dir(xhs.SOURCE, NOTE_ID) / "meta.json")
    visible = storage.vault_root() / meta["visible_note"]
    left = comments_mod.read_comments(visible)
    assert [(c.actor, c.text) for c in left] == [("human", "这条留给 Fable 看")]
    assert "收好了" not in visible.read_text(encoding="utf-8")
