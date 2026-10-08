"""10-03：推送隐私闸放过测试里明写是占位的假密钥（含 never-leak / fake / dummy / example / placeholder），真样子的照拦。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import privacy_gate as gate  # noqa: E402

REALISH = "sk" + "-" + "AbCdEfGhIjKlMnOpQrStUvWx1234"   # 拼出来的，免得源码里出现真样子的串被闸拦


def test_placeholder_key_passes():
    assert gate.scan_text("apiKey: sk-in-data-json-should-never-leak", []) == []


def test_real_looking_key_still_blocked():
    assert gate.scan_text(REALISH, []) == ["openai-style key"]


def test_one_real_among_placeholders_blocks():
    text = "sk-fake-key-aaaaaaaaaaaaaaaaaaaaaa and " + REALISH
    assert gate.scan_text(text, []) == ["openai-style key"]


# 1008：二进制文件的补丁里没有「+++ b/<路径>」，旧写法按补丁认文件类型，新增的 mp4 / db 整个漏检。
import subprocess  # noqa: E402


def _repo(tmp_path):
    def g(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    g("init", "-q")
    g("config", "user.email", "x@users.noreply.github.com")
    g("config", "user.name", "x")
    return g


def test_binary_private_file_is_blocked(tmp_path, monkeypatch):
    g = _repo(tmp_path)
    (tmp_path / "clip.mp4").write_bytes(b"\x00\x01binary\x00" * 10)
    (tmp_path / "notes.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 30)
    g("add", ".")
    g("commit", "-qm", "add")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    found = gate.scan_commit(sha, [])
    assert "clip.mp4: private file type" in found
    assert "notes.db: private file type" in found


def test_whitelisted_fixture_passes(tmp_path, monkeypatch):
    g = _repo(tmp_path)
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "tiny-1s.mp4").write_bytes(b"\x00\x01binary\x00" * 10)
    (tmp_path / "tests" / "fixtures" / "other.mp4").write_bytes(b"\x00\x02binary\x00" * 10)
    g("add", ".")
    g("commit", "-qm", "add")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert gate.scan_commit(sha, []) == ["tests/fixtures/other.mp4: private file type"]
