"""1025 Codex 复查：压实检查完「没有旁路」、读记录之前别的进程写进旁路 → 旁路事件不能被折进主文件后又被并回一次。"""
from link_brain import problems, storage


def test_side_file_written_during_compaction_not_double_counted(monkeypatch):
    row = {"key": "x|nightly|T", "step": "nightly", "code": "TRANSIENT.X", "ts": "2026-10-25T01:00:00+10:00"}
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    side = problems._dump(problems._stamped([dict(row)]))  # 旁路这行的事件 id 比主文件里的早：压实只留最后一行的 id
    problems.path().write_text(problems._dump(problems._stamped([dict(row), dict(row)])), encoding="utf-8")

    real = problems._pending_files
    calls = {"n": 0}

    def racing():
        calls["n"] += 1
        if calls["n"] == 1:  # 压实刚检查完没有旁路，另一个进程正好写进来一行
            problems._write_pending(side)
            return []
        return real()

    monkeypatch.setattr(problems, "_pending_files", racing)
    problems._compact_locked(threshold=0)
    monkeypatch.setattr(problems, "_pending_files", real)
    problems._merge_pending_locked()
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 3
