"""r4-d1 补测：@ 批注送 AI（_send 全程打桩——它 shell=True 真跑命令，绝不能落地）。"""
from __future__ import annotations

import json

from link_brain import mention, storage


def _mk_item(vault, source, sid, annotations, meta=None, notes_raw=None):
    d = vault / storage.ARCHIVE_DIRNAME / source / sid
    d.mkdir(parents=True)
    if notes_raw is not None:
        (d / "notes.json").write_text(notes_raw, encoding="utf-8")
    else:
        (d / "notes.json").write_text(json.dumps({"starred": False, "annotations": annotations}), encoding="utf-8")
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def test_pending_collects_only_unsent_mentions(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    _mk_item(tmp_path / "vault", "xiaohongshu", "sid1", [
        {"id": "a1", "ts": "2026-10-25T10:00:00Z", "text": "  @Fable 看看这篇 ", "to_fable": True},
        {"id": "a2", "ts": "2026-10-25T11:00:00Z", "text": "AI 早回过的话", "to_fable": True, "reply_to": "a0"},  # 回复不送
        {"id": "a3", "ts": "2026-10-25T12:00:00Z", "text": "普通批注"},  # 没 to_fable
        {"id": "a4", "ts": "2026-10-25T13:00:00Z", "text": "   ", "to_fable": True},  # 空文本不算活批注
        {"id": "a5", "ts": "2026-10-25T14:00:00Z", "text": "@Fable 已删", "to_fable": True},  # 墓碑
    ], meta={"item_id": "xhs-sid1", "title": "标题", "visible_note": "可见备注"}, notes_raw=None)
    _mk_item(tmp_path / "vault", "xiaohongshu", "sid2",
             [{"ts": "2026-10-24T09:00:00Z", "text": "@Fable 更早的", "to_fable": True}],  # 没有 id → 用 ts 当 key
             meta={"item_id": "xhs-sid2", "title": "旧帖"})
    # a5 标记删除
    p = tmp_path / "vault" / "_archive" / "xiaohongshu" / "sid1" / "notes.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["deleted"] = ["a5"]
    p.write_text(json.dumps(data), encoding="utf-8")

    rows = mention.pending()
    assert [(r["item_id"], r["annot_id"]) for r in rows] == [("xhs-sid2", ""), ("xhs-sid1", "a1")]  # 旧→新
    r = rows[1]
    assert r["kind"] == "mention" and r["source_id"] == "sid1"
    assert r["title"] == "标题" and r["visible_note"] == "可见备注" and r["text"] == "@Fable 看看这篇"


def test_pending_skips_corrupt_notes_and_junk_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    _mk_item(tmp_path / "vault", "xiaohongshu", "bad", [], notes_raw="{not json")
    _mk_item(tmp_path / "vault", "xiaohongshu", "list", [], notes_raw="[1,2]")  # 不是对象也按坏了处理
    # 来源目录名不在 PREFIX、meta 又没给 item_id → _archive 下的杂目录，跳过
    _mk_item(tmp_path / "vault", "downloads", "misc",
             [{"id": "z", "ts": "2026-10-25T10:00:00Z", "text": "@Fable 杂目录", "to_fable": True}])
    assert mention.pending() == []


def test_pending_falls_back_to_domain_item_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    # meta.json 缺失 / 读不了（非法 JSON）时都回退到 前缀-来源id
    _mk_item(tmp_path / "vault", "xiaohongshu", "abc",
             [{"id": "m1", "ts": "2026-10-25T10:00:00Z", "text": "@Fable", "to_fable": True}])
    d = _mk_item(tmp_path / "vault", "xiaohongshu", "def",
                 [{"id": "m2", "ts": "2026-10-25T11:00:00Z", "text": "@Fable", "to_fable": True}])
    (d / "meta.json").write_text("{broken", encoding="utf-8")  # 直接写非法 JSON，别被 json.dumps 转成合法字符串
    assert {r["item_id"] for r in mention.pending()} == {"xhs-abc", "xhs-def"}
    assert all(r["title"] == "" for r in mention.pending())


def test_ledger_bad_file_is_empty_and_good_file_suppresses(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    _mk_item(tmp_path / "vault", "xiaohongshu", "s1",
             [{"id": "a1", "ts": "2026-10-25T10:00:00Z", "text": "@Fable", "to_fable": True}],
             meta={"item_id": "xhs-s1"})
    ledger = tmp_path / "mention-notified.json"
    for bad in ("{oops", "[\"a\"]"):  # 坏 JSON / 不是对象 → 当空账本，全部照送
        ledger.write_text(bad, encoding="utf-8")
        assert len(mention.pending()) == 1
    ledger.write_text(json.dumps({"xhs-s1:a1": "2026-10-25T12:00:00+11:00"}), encoding="utf-8")
    assert mention.pending() == []  # 送过的不再出现


def test_notify_pending_dry_run_never_sends_or_records(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.delenv(mention.ENV_NOTIFY_CMD, raising=False)
    _mk_item(tmp_path / "vault", "xiaohongshu", "s1",
             [{"id": "a1", "ts": "2026-10-25T10:00:00Z", "text": "@Fable hi", "to_fable": True}],
             meta={"item_id": "xhs-s1"})

    def must_not_run(command, payload):
        raise AssertionError("_send 绝不能真跑")

    monkeypatch.setattr(mention, "_send", must_not_run)
    out = mention.notify_pending(dry_run=True)
    assert out == {"ok": True, "pending": 1, "sent": 0,
                   "items": [{"kind": "mention", "item_id": "xhs-s1", "source_id": "s1", "title": "",
                              "visible_note": "", "annot_id": "a1", "text": "@Fable hi",
                              "ts": "2026-10-25T10:00:00Z"}]}
    assert not (tmp_path / "mention-notified.json").exists()  # 不记账

    # 没配通知命令（env 没有、notify-cmd.txt 也没有）：不送、给出 note、items 为空
    monkeypatch.setattr(mention, "_send", lambda *a: (_ for _ in ()).throw(AssertionError("不该送")))
    out2 = mention.notify_pending()
    assert out2["ok"] is True and out2["pending"] == 1 and out2["sent"] == 0
    assert "没配通知命令" in out2["note"] and "items" not in out2  # 这条返回结构不带 items


def test_notify_command_env_wins_then_first_comment_free_line(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv(mention.ENV_NOTIFY_CMD, "  python relay.py --x  ")
    assert mention.notify_command() == "python relay.py --x"  # env 优先，strip 首尾
    monkeypatch.setenv(mention.ENV_NOTIFY_CMD, "")
    assert mention.notify_command() == ""  # 空串不算配了
    (tmp_path / "notify-cmd.txt").write_text("# 注释\n\n  python relay.py  \n第二行不该用", encoding="utf-8")
    assert mention.notify_command() == "python relay.py"  # 第一个非空非 # 行
    (tmp_path / "notify-cmd.txt").write_text("# 只有注释", encoding="utf-8")
    assert mention.notify_command() == ""


def test_notify_pending_sends_records_and_retries_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv(mention.ENV_NOTIFY_CMD, "fake-cmd-would-run")
    _mk_item(tmp_path / "vault", "xiaohongshu", "s1",
             [{"id": "a1", "ts": "2026-10-25T10:00:00Z", "text": "@Fable 一", "to_fable": True},
              {"id": "a2", "ts": "2026-10-25T11:00:00Z", "text": "@Fable 二", "to_fable": True}],
             meta={"item_id": "xhs-s1"})
    sent_payloads = []

    def fake_send(command, payload):
        sent_payloads.append((command, payload))
        return (payload["annot_id"] != "a2", "")  # a2 送失败

    monkeypatch.setattr(mention, "_send", fake_send)
    out = mention.notify_pending()
    assert out["ok"] is False and out["pending"] == 2 and out["sent"] == 1
    assert len(out["errors"]) == 1 and "xhs-s1:a2" in out["errors"][0]
    assert all(cmd == "fake-cmd-would-run" for cmd, _ in sent_payloads)
    ledger = json.loads((tmp_path / "mention-notified.json").read_text(encoding="utf-8"))
    assert set(ledger) == {"xhs-s1:a1"}  # 失败的那条不记账

    rows = mention.pending()
    assert [r["annot_id"] for r in rows] == ["a2"]  # 失败的下次还送

    monkeypatch.setattr(mention, "_send", lambda *a: (True, ""))
    out2 = mention.notify_pending()
    assert out2["ok"] is True and out2["sent"] == 1
    assert set(json.loads((tmp_path / "mention-notified.json").read_text(encoding="utf-8"))) == {"xhs-s1:a1", "xhs-s1:a2"}
