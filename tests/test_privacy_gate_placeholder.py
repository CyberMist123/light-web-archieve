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
