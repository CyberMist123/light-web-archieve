"""开源前 P1（1025）：旁路并回后删不掉（被占）→ 放 `.merged` 标记，压实不再被它卡死，也不会再并一遍。

修前：`_compact_locked` 只要看到 problems.pending/ 里还有 .jsonl 就不压（怕丢事件 id 后分不出哪些并过了），
删不掉的旁路一直在 → 问题记录永不压实、越写越长。"""
from pathlib import Path

from link_brain import problems, storage


def _block_unlink(monkeypatch):
    real = Path.unlink

    def fake(self, *a, **k):
        if self.parent.name == problems.PENDING_DIR and self.suffix == ".jsonl":
            raise PermissionError("被占用")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", fake)
    return real


def _seed(n_main: int) -> dict:
    row = {"key": "x|nightly|T", "step": "nightly", "code": "TRANSIENT.X", "ts": "2026-10-25T01:00:00+10:00"}
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    problems.path().write_text(problems._dump(problems._stamped([dict(row) for _ in range(n_main)])), encoding="utf-8")
    return row


def test_undeletable_side_file_gets_marker_and_compaction_proceeds(monkeypatch):
    row = _seed(3)
    problems._write_pending(problems._dump(problems._stamped([dict(row)])))
    real_unlink = _block_unlink(monkeypatch)

    assert problems._merge_pending_locked() == 1                     # 并回了一行，但旁路删不掉
    side = list(problems.pending_dir().glob("*.jsonl"))
    assert len(side) == 1 and side[0].with_suffix(".merged").exists(), "删不掉就该放 .merged 标记"
    assert problems._pending_files() == [], "带标记的旁路不算「还没并回」"
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 4, "读的时候也不再把它算一遍"

    assert problems._compact_locked(threshold=0) is True, "修前：旁路还在就永远不压实"
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 4
    assert len(problems._read_file(problems.path(), True)) == 1

    assert problems._merge_pending_locked() == 0, "下一次并回不能再并这份"
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 4

    monkeypatch.setattr(Path, "unlink", real_unlink)
    problems._merge_pending_locked()                                 # 能删了：文件和标记一起清掉
    assert not list(problems.pending_dir().iterdir())
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 4


def test_marker_without_file_is_cleaned_and_new_side_files_still_block_compaction(monkeypatch):
    row = _seed(2)
    d = problems.pending_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "1-1-1.merged").write_text("", encoding="utf-8")            # 文件早没了、只剩标记
    problems._write_pending(problems._dump(problems._stamped([dict(row)])))  # 另一份新旁路，还没并回
    assert len(problems._pending_files()) == 1
    assert problems._compact_locked(threshold=0) is False, "真没并回的旁路照样挡住压实"
    assert problems._merge_pending_locked() == 1
    assert not list(d.glob("*.merged")), "孤零零的标记顺手清掉"
    assert not list(d.glob("*.jsonl"))
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 3


def test_marker_write_failure_falls_back_to_old_behaviour(monkeypatch):
    row = _seed(1)
    problems._write_pending(problems._dump(problems._stamped([dict(row)])))
    _block_unlink(monkeypatch)
    real_write = storage.atomic_write_text

    def flaky(path, text):
        if Path(path).suffix == problems.MERGED_SUFFIX:
            raise PermissionError("目录只读")
        return real_write(path, text)
    monkeypatch.setattr(problems.storage, "atomic_write_text", flaky)
    problems._merge_pending_locked()
    assert len(problems._pending_files()) == 1, "标记写不上：还按「没并回」对待，压实继续等（不比修前差）"
    assert problems._compact_locked(threshold=0) is False
