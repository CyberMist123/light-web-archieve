"""第 6 批：`python -m link_brain report week`——本周同步情况（目录页「N 篇 · 更新 …」点开的窗口数据）。

合成库：几篇对象分在不同日子，各缺不同的东西；只读本地，conftest 已把 vault / ~/.link-brain 指到 tmp。
"""

from __future__ import annotations

import json

import pytest
import sqlite3
from datetime import datetime
from pathlib import Path

from link_brain import cli, index, report, storage, sync_state

NOW = datetime(2026, 10, 3, 12, 0).astimezone()


def _ts(day: int, hour: int = 4, minute: int = 30) -> str:
    return datetime(2026, 10, day, hour, minute).astimezone().isoformat(timespec="seconds")


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _obj(sid: str, *, title: str, at: str | None, note: bool = True, agent: bool = True, summary: bool = True,
         images: int = 0, vision: bool = True, attachments: list[dict] | None = None, records: list[dict] | None = None,
         files: dict[str, bytes] | None = None, mds: tuple[str, ...] = ()) -> Path:
    vault = storage.vault_root()
    obj = storage.object_dir("xiaohongshu", sid)
    visible = f"Web/Xiaohongshu/{title}.md"
    meta = {"item_id": f"xhs-{sid}", "source": "xiaohongshu", "source_id": sid, "title": title, "kind": "image",
            "current_version": 1, "visible_note": visible}
    if at:
        meta["first_archived_at"] = at
    _write(obj / "meta.json", meta)
    if note:
        _write(vault / visible, f"# {title}\n")
    if agent:
        _write(obj / "derived" / "agent.md", f"# {title}\n")
    if summary:
        _write(obj / "derived" / "extracted.json", {"status": "ok", "data": {"summary": "概要"}})
    media = []
    for i in range(images):
        rel = f"raw/v0001/assets/image-{i + 1:03d}.webp"
        (obj / rel).parent.mkdir(parents=True, exist_ok=True)
        (obj / rel).write_bytes(b"RIFF0000WEBP")
        media.append({"file": rel})
    _write(obj / "raw" / "v0001" / "manifest.json", {"media": media})
    if images and vision:
        _write(obj / "derived" / "vision.json", {"images": [{"asset": m["file"], "status": "ok"} for m in media]})
    _write(obj / "raw" / "v0001" / "source.json", {"note": {"title": title, "attachments": attachments or []}})
    if records is not None:
        _write(obj / "attachments.json", {"files": records})
    for name, blob in (files or {}).items():
        (obj / "attachments").mkdir(parents=True, exist_ok=True)
        (obj / "attachments" / name).write_bytes(blob)
    for doc_id in mds:
        _write(obj / "derived" / "attachments" / f"{doc_id}.md", "全文")
    return obj


def _library():
    # 今天（10-03）：A 齐；B 没正文 / 没机读版 / 没概要 / 图没识；C 附件 3 个该有（1 个没下）+ 1 条线索（不算），
    #   下好的 PDF 转了、Word 没转
    _obj("a" * 24, title="全都齐了", at=_ts(3), images=2)
    _obj("b" * 24, title="什么都没生成", at=_ts(3, 5), note=False, agent=False, summary=False, images=1, vision=False)
    _obj("c" * 24, title="带附件", at=_ts(3, 6),
         attachments=[{"doc_id": "d1", "name": "讲义.pdf"}, {"doc_id": "d2", "name": "表格.docx"},
                      {"doc_id": "d3", "name": "没下到.pdf"}, {"hint": "评论区说有附件"}],
         records=[{"doc_id": "d1", "name": "讲义.pdf", "file": "讲义.pdf"}, {"doc_id": "d2", "name": "表格.docx", "file": "表格.docx"}],
         files={"讲义.pdf": b"%PDF-1.4 x", "表格.docx": b"PK\x03\x04 x"}, mds=("d1",))
    # 10-01：一篇齐的；09-20：窗口外；没有时间字段的一篇
    _obj("d" * 24, title="前天那篇", at=_ts(1, 23, 50))
    _obj("e" * 24, title="很久以前", at=datetime(2026, 9, 20, 4, 0).astimezone().isoformat())
    _obj("f" * 24, title="没有时间", at=None)


@pytest.fixture(autouse=True)
def _no_real_tool_dir(monkeypatch, tmp_path):
    """report 还会读读取组件目录下旧夜跑脚本的 fav-sync.log：测试里指到空的临时目录，别读到本机真日志。"""
    monkeypatch.setenv("LINK_BRAIN_XHS_TOOL_DIR", str(tmp_path / "xhs-tool"))


def test_old_script_log_is_read_too(tmp_path):
    _library()
    tool = tmp_path / "xhs-tool"
    tool.mkdir()
    (tool / "fav-sync.log").write_text("2026-10-02 04:00:00  === 夜跑开始 ===\n2026-10-02 06:00:00  === 夜跑结束 ===\n",
                                       encoding="utf-8")
    out = report.week(7, now=NOW)
    assert out["nightly_source"] == "log"
    assert any(r["date"] == "2026-10-02" and r["nightly"]["finished"] is True for r in out["rows"])


def test_week_counts_per_day_without_index_db():
    _library()
    out = report.week(7, now=NOW)
    assert out["ok"] is True and out["days"] == 7
    assert out["time_field"] == "first_archived_at"
    assert [r["date"] for r in out["rows"]] == [f"2026-10-0{d}" for d in (3, 2, 1)] + [f"2026-09-{d}" for d in (30, 29, 28, 27)]
    today = out["rows"][0]
    assert today["weekday"] == "周六"
    assert today["new"] == 3
    assert today["note"] == {"done": 2, "missing": 1}
    assert today["agent"] == {"done": 2, "missing": 1}
    assert today["attachments"] == {"expected": 3, "downloaded": 2, "missing": 1, "convertible": 2, "converted": 1, "unconverted": 1}
    assert today["vision_missing"] == 1 and today["summary_missing"] == 1
    inc = {x["title"]: x for x in today["incomplete"]}
    assert set(inc) == {"什么都没生成", "带附件"}, "齐了的不列"
    assert inc["什么都没生成"]["missing"] == ["正文", "机读版", "识图", "概要"]
    assert inc["什么都没生成"]["note"] is None, "没正文就没得点开"
    assert inc["带附件"]["missing"] == ["附件缺 1 个", "附件转文字差 1 个"]
    assert inc["带附件"]["note"] == "Web/Xiaohongshu/带附件.md"
    assert out["rows"][1]["new"] == 0
    day1 = out["rows"][2]
    assert day1["new"] == 1 and day1["incomplete"] == []
    assert out["total"]["new"] == 4, "窗口外的不算"
    assert out["no_time"] == 1
    assert out["deferred"] is None


def test_week_reads_index_db_read_only_and_cli_json(capsys):
    _library()
    conn = index.connect()
    for sid, at in (("a" * 24, _ts(3)), ("d" * 24, _ts(1, 23, 50))):
        conn.execute("INSERT INTO objects (item_id, source, source_id, canonical_url, kind, first_archived_at, last_checked_at,"
                     " current_version, object_dir) VALUES (?, 'xiaohongshu', ?, '', 'image', ?, ?, 1, '')",
                     (f"xhs-{sid}", sid, at, at))
    conn.commit()
    conn.close()
    db = storage.index_db_path()
    before = db.stat().st_mtime_ns
    out = report.week(7, now=NOW)
    assert out["total"]["new"] == 2, "有 index.db 就按它枚举（只登记了两篇）"
    assert db.stat().st_mtime_ns == before
    # CLI：stdout 只有一行 JSON
    _write(sync_state.path(), {"state": "ready", "deferred": 12, "last_success": _ts(3, 4, 40)})
    assert cli.main(["report", "week", "--days", "3"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc["ok"] is True and doc["code"] == "" and doc["days"] == 3 and len(doc["rows"]) == 3
    assert doc["deferred"] == 12


def test_nightly_from_log_and_problems(tmp_path):
    _library()
    log = storage.link_brain_home() / "nightly.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\r\n".join([
        "2026-10-01 04:00:00  === 夜跑开始 ===",
        "2026-10-01 05:10:00  === 夜跑结束 ===",
        "2026-10-03 04:00:00  === 夜跑开始 ===",
        "2026-10-03 04:05:00  === sync-favorites 开始（限时 60.0 分钟）===",
    ]) + "\r\n", encoding="utf-8")
    rows = [
        {"ts": _ts(3, 4, 50), "key": "nightly.sync-favorites||STEP_TIMEOUT", "step": "nightly.sync-favorites", "item_id": None,
         "title": None, "code": "TRANSIENT.STEP_TIMEOUT", "reason": "超时", "action": "retry_later", "count": 1, "resolved_at": None},
        {"ts": _ts(1, 4, 20), "key": "attachments.convert|xhs-x|NETWORK", "step": "attachments.convert", "item_id": "xhs-x",
         "title": "某篇", "code": "TRANSIENT.NETWORK", "reason": "OCR 连不上", "action": "retry_later", "count": 1, "resolved_at": None},
        {"ts": _ts(2, 9), "key": "attachments.convert|xhs-x|NETWORK", "resolved_at": _ts(2, 9)},
        {"ts": _ts(3, 1), "key": "config||LEGACY_CONFIG", "step": "config", "item_id": None, "code": "SKIPPED.LEGACY_CONFIG",
         "reason": "旧设置", "action": "skipped", "count": 1, "resolved_at": None},
    ]
    _write(storage.archive_root() / "problems.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    out = report.week(7, now=NOW)
    assert out["nightly_source"] == "log"
    n3, n2, n1 = (out["rows"][i]["nightly"] for i in range(3))
    assert n3["finished"] is False and n3["text"].startswith("夜跑没走完（04:00 开始")
    assert [p["code"] for p in n3["problems"]] == ["TRANSIENT.STEP_TIMEOUT"], "设置换算这类不算夜跑问题"
    assert n3["open_problems"] == 1 and "1 个还没解决" in n3["text"]
    assert n2["finished"] is None and n2["text"] == "那天没跑夜跑"
    assert n1["finished"] is True and n1["text"].startswith("夜跑走完了")
    assert n1["problems"][0]["open"] is False and "都已解决" in n1["text"]


def test_nightly_without_log_uses_sync_status():
    _library()
    _write(sync_state.path(),
           {"state": "failed", "message": "收藏只读回一截", "updated_at": _ts(3, 4, 50), "last_success": _ts(2, 4, 2), "deferred": 5})
    out = report.week(3, now=NOW)
    assert out["nightly_source"] == "problems"
    texts = [r["nightly"]["text"] for r in out["rows"]]
    assert texts[0] == "收藏同步没成功：收藏只读回一截"
    assert texts[1] == "收藏同步成功"
    assert texts[2] == "没有问题记录"
    assert all(r["nightly"]["finished"] is None for r in out["rows"])
    assert out["deferred"] == 5


def test_empty_library():
    out = report.week(7, now=NOW)
    assert out["ok"] is True and out["total"]["new"] == 0 and len(out["rows"]) == 7
    assert all(r["incomplete"] == [] for r in out["rows"])
