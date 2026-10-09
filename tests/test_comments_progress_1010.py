"""1010 她报：笔记页手动「抓全部评论」提示说「底部状态栏能看进度」，其实看不到任何进度。

做法：`comments <id> --progress` 每走一步往 stdout 写一行进度事件（和 setup run 同一写法），最后一行照旧是结果 JSON：
start（准备）→ lock（号被别的任务占着时：谁在用、最多等几分钟）→ read（开页读评论区，最多几分钟）→ merge（和存下的合并）
→ media（下新冒出来的评论图 / 语音，done/total 是真计数）→ render（写进笔记）→ 结果。插件（note-actions.js）把它画在笔记页评论区顶上。
不开 --progress 的入口（夜跑、后台补跑、问题面板「再试一次」）一个字节都不变。
"""

from __future__ import annotations

import json
import os
import time

from link_brain import accounts, cli, ingest as ingest_mod
from link_brain.adapters import xiaohongshu as xhs

from test_comments_fill_1009 import ITEM, _floor, _ingest, _raw
from test_render import setup_env


def _lines(out: str) -> list[dict]:
    return [json.loads(x) for x in out.strip().splitlines() if x.strip()]


def _fake_download(got):
    def fake(url, dest_dir, stem, *, client):
        got.append(stem)
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{stem}.jpg").write_bytes(b"x")
        return {"file": f"{stem}.jpg", "requested_url": url, "mime": "image/jpeg", "width": 1, "height": 1,
                "bytes": 1, "sha256": "0", "download_status": "ok", "error": None}
    return fake


def test_manual_fetch_with_progress_reports_each_real_stage(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    got: list[str] = []
    monkeypatch.setattr(ingest_mod, "download_image", _fake_download(got))
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 3, 1)]))
    got.clear()
    reply = _floor("c1", 3, 3)
    reply["subComments"][1]["pictures"] = [{"urlDefault": "https://example.invalid/a.jpg"}, {"urlDefault": "https://example.invalid/b.jpg"}]
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([reply], has_more=False))
    code = cli.main(["comments", ITEM, "--progress", "--wait-lock-min", "10"])
    out = _lines(capsys.readouterr().out)
    assert code == 0
    events, result = out[:-1], out[-1]
    assert all(e["type"] == "progress" for e in events)
    stages = [e["stage"] for e in events]
    assert stages[0] == "start" and stages[-1] == "render"
    assert stages.index("read") < stages.index("merge") < stages.index("media") < stages.index("render")
    assert "lock" not in stages, "号没人占：不报「等号」"
    read = next(e for e in events if e["stage"] == "read")
    assert "最多 25 分钟" in read["text"]
    media = [e for e in events if e["stage"] == "media"]
    assert [(e["done"], e["total"]) for e in media] == [(0, 2), (1, 2), (2, 2)], "图片 / 语音按真下完的个数报"
    assert all(e.get("unit") == "个" for e in media)
    assert got == ["comment-c1-r1-001", "comment-c1-r1-002"], "正文图不重下"
    assert result["ok"] is True and result["message"].startswith("评论已更新"), result
    assert "type" not in result, "最后一行是结果，不是进度"


def test_without_progress_flag_stdout_is_only_the_result(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 3, 1)]))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: _raw([_floor("c1", 3, 3)], has_more=False))
    assert cli.main(["comments", ITEM]) == 0
    out = _lines(capsys.readouterr().out)
    assert len(out) == 1 and out[0]["ok"] is True, "别的入口（夜跑 / 补跑 / 问题面板）照旧只有一行结果"


def test_waiting_for_the_account_says_who_and_gives_a_readable_busy_result(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    _ingest(monkeypatch, capsys, _raw([_floor("c1", 3, 1)]))
    lock = accounts._account_lock()
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    lock.path.write_text(json.dumps({"pid": os.getppid(), "owner": "comments-fill", "heartbeat_ts": time.time()}), "utf-8")
    monkeypatch.setattr(accounts, "_account_lock", lambda: (lambda lk: (setattr(lk, "poll_s", 0.05), lk)[1])(lock))
    code = cli.main(["comments", ITEM, "--progress", "--wait-lock-min", "0.01"])
    out = _lines(capsys.readouterr().out)
    assert code == 6
    waits = [e for e in out[:-1] if e.get("stage") == "lock"]
    assert len(waits) == 1 and "后台补评论正在用小红书号" in waits[0]["text"] and "这一篇补完就轮到这里" in waits[0]["text"]
    result = out[-1]
    assert result["ok"] is False and result["code"] == "BUSY"
    assert result["message"].startswith("号一直被「后台补评论」占着"), result["message"]


def test_owner_text_maps_lock_owners_to_plain_words():
    assert ingest_mod.owner_text({"owner": "comments-fill"}) == "后台补评论"
    assert ingest_mod.owner_text({"owner": "sync-favorites"}) == "同步收藏"
    assert ingest_mod.owner_text({"owner": "something-new"}) == "something-new"
    assert ingest_mod.owner_text(None) == "别的任务"
