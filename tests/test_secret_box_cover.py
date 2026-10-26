"""r5 补测：口令可取回副本（Windows DPAPI 真加解密只写 tmp_path；跨平台用平台分支断言，不 skip）。"""
from __future__ import annotations

import base64
import sys

from link_brain.remote import secret_box as sb

_WIN = sys.platform == "win32"


def test_supported_matches_platform():
    assert sb.supported() is _WIN


def test_save_load_roundtrip_on_windows(tmp_path):
    ok = sb.save(tmp_path, "口令-pass-π")
    assert ok is _WIN
    f = tmp_path / sb.FILE_NAME
    if _WIN:
        assert f.is_file()
        blob = base64.b64decode(f.read_text(encoding="ascii"))  # 文件是 base64 密文
        assert "口令-pass-π".encode("utf-8") not in blob
        assert sb.load(tmp_path) == "口令-pass-π"
    else:
        assert not f.exists()  # 非 Windows 不落副本
        assert sb.load(tmp_path) is None


def test_load_missing_or_corrupt_returns_none(tmp_path):
    assert sb.load(tmp_path) is None  # 文件不在
    (tmp_path / sb.FILE_NAME).write_text("不是 base64！！", encoding="utf-8")
    assert sb.load(tmp_path) is None  # 解不开一律 None，不抛
    (tmp_path / sb.FILE_NAME).write_text(base64.b64encode(b"junk-not-dpapi").decode("ascii"), encoding="ascii")
    assert sb.load(tmp_path) is None


def test_clear_is_idempotent(tmp_path):
    sb.save(tmp_path, "pw")
    sb.clear(tmp_path)
    assert not (tmp_path / sb.FILE_NAME).exists()
    sb.clear(tmp_path)  # 再清一次不炸
    assert sb.load(tmp_path) is None


def test_unsupported_or_failed_save_removes_stale_copy(tmp_path, monkeypatch):
    # 机器不支持：返回 False，旧的（换口令前的）副本删掉，不留对不上的旧值
    monkeypatch.setattr(sb, "supported", lambda: False)
    stale = tmp_path / sb.FILE_NAME
    stale.write_text("stale", encoding="ascii")
    assert sb.save(tmp_path, "new") is False
    assert not stale.exists()

    # 支持但 DPAPI 调用失败：同样 False + 删旧副本
    monkeypatch.setattr(sb, "supported", lambda: True)

    def boom(data: bytes) -> bytes:
        raise OSError("CryptProtectData 失败")

    monkeypatch.setattr(sb, "protect", boom)
    stale.write_text("stale", encoding="ascii")
    assert sb.save(tmp_path, "new") is False
    assert not stale.exists()


def test_path_joins_file_name(tmp_path):
    assert sb.path(tmp_path) == tmp_path / "passphrase.dpapi"
