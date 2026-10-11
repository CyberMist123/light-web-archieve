"""1011：目标被别的进程开着、os.replace 一直 PermissionError 时，atomic_write 退而原地覆写，不崩、不留临时文件。"""

import os

from link_brain import storage


def test_atomic_write_falls_back_to_in_place_when_replace_denied(tmp_path, monkeypatch):
    target = tmp_path / "目录.md"
    target.write_bytes(b"old content that is longer")

    def deny(src, dst):
        raise PermissionError(5, "拒绝访问")

    monkeypatch.setattr(storage.os, "replace", deny)
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)
    storage.atomic_write_text(target, "新")
    assert target.read_text(encoding="utf-8") == "新"
    assert [p.name for p in tmp_path.iterdir()] == ["目录.md"]


def test_atomic_write_denied_and_missing_target_still_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "x")))
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)
    target = tmp_path / "new.md"
    try:
        storage.atomic_write_text(target, "a")
        raised = False
    except PermissionError:
        raised = True
    assert raised
    assert list(tmp_path.iterdir()) == []
