"""1025：`crawl.write_status` 与 `remote/secret_box.save` 是最后两处手写原子写（CONVENTIONS §6.5），
本文件先钉住迁移后的行为：

- write_status：连写两次字段都在、目录不留 `*.tmp`；`storage.atomic_write_text` 抛 OSError 时不炸、
  旧内容原样（进度文件写不进去不该带崩抓取）。
- secret_box.save：成功落 base64 副本；写失败 → 返回 False 且旧副本删掉（它现在的约定：
  免得留着和新口令对不上的旧值）。
"""

from __future__ import annotations

import base64

from link_brain import crawl, storage
from link_brain.remote import secret_box


def test_write_status_merges_and_leaves_no_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr("link_brain.accounts.home", lambda: tmp_path)
    crawl.write_status(a=1)
    crawl.write_status(b=2)
    data = crawl.read_status()
    assert data["a"] == 1 and data["b"] == 2
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_status_survives_atomic_write_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("link_brain.accounts.home", lambda: tmp_path)
    crawl.write_status(a=1)

    def boom(path, text):
        raise OSError("盘满了")
    monkeypatch.setattr(storage, "atomic_write_text", boom)

    crawl.write_status(c=3)   # 不许抛
    data = crawl.read_status()
    assert data["a"] == 1 and "c" not in data
    assert list(tmp_path.glob("*.tmp")) == []


def test_secret_box_save_writes_base64(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_box, "supported", lambda: True)
    monkeypatch.setattr(secret_box, "protect", lambda data: bytes(data))
    assert secret_box.save(tmp_path, "pw") is True
    p = secret_box.path(tmp_path)
    assert base64.b64decode(p.read_text(encoding="ascii")) == b"pw"


def test_secret_box_save_failure_deletes_old_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_box, "supported", lambda: True)
    monkeypatch.setattr(secret_box, "protect", lambda data: bytes(data))
    assert secret_box.save(tmp_path, "pw") is True

    def boom(path, text):
        raise OSError("盘满了")
    monkeypatch.setattr(storage, "atomic_write_text", boom)

    assert secret_box.save(tmp_path, "pw2") is False
    assert not secret_box.path(tmp_path).exists()
