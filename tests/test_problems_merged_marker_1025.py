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


def test_reader_does_not_double_count_side_file_merged_and_compacted_mid_read(monkeypatch):
    """Codex 1025 复查 #12：读者先读到旁路；写者随后并回（删不掉 → 标记）并压实（丢事件 id）；读者再读主文件。
    修前读者返回 4（实际 3 次）：主文件里压实后的那行没有 eid，去重认不出旁路那行已经并进去了。"""
    row = {"key": "x|nightly|T", "step": "nightly", "code": "TRANSIENT.X", "ts": "2026-10-25T01:00:00+10:00"}
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    problems._write_pending(problems._dump(problems._stamped([dict(row)])))  # 旁路这行的事件 id 比主文件的早：压实只留最后一行的 id
    _seed(2)
    _block_unlink(monkeypatch)
    real_read = problems._read_file
    state = {"fired": False}

    def racing_read(p, strict):
        if p == problems.path() and not state["fired"]:
            state["fired"] = True                                   # 读者读完旁路、还没读主文件：写者并回 + 压实
            problems._merge_pending_locked()
            assert problems._compact_locked(threshold=0) is True
        return real_read(p, strict)
    monkeypatch.setattr(problems, "_read_file", racing_read)
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 3, "修前：4"
    monkeypatch.setattr(problems, "_read_file", real_read)
    assert problems._fold(problems._read_rows())[row["key"]]["count"] == 3


def test_reader_keeps_side_file_merged_after_main_was_read(monkeypatch):
    """反向交错：读者读完主文件之后旁路才被并回 → 旁路行还要算（主文件那份是旧的），且不算两次。"""
    row = {"key": "x|nightly|T", "step": "nightly", "code": "TRANSIENT.X", "ts": "2026-10-25T01:00:00+10:00"}
    storage.archive_root().mkdir(parents=True, exist_ok=True)
    problems._write_pending(problems._dump(problems._stamped([dict(row)])))
    _seed(2)
    real_pending = problems._pending_files
    calls = {"n": 0}

    def racing_pending():
        calls["n"] += 1
        if calls["n"] == 2:                                          # 第二眼之前：写者刚并回并删掉旁路
            problems._merge_pending_locked()
        return real_pending()
    monkeypatch.setattr(problems, "_pending_files", racing_pending)
    folded = problems._fold(problems._read_rows())
    assert folded[row["key"]]["count"] == 3
