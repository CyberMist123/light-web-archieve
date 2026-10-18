"""1018 她：AI 服务只要粘一把 key，认出是哪家。联网那一步一律换成假的，不真问各家接口。"""

from __future__ import annotations

import io
import json

from link_brain import cli, keyprobe


def test_google_prefix_only_asks_google(monkeypatch):
    asked = []
    monkeypatch.setattr(keyprobe, "_accepts", lambda pid, key, timeout=8.0: asked.append(pid) or True)
    out = keyprobe.detect("AIzaFAKEKEY")
    assert out["ok"] and out["provider"] == "google" and asked == ["google"]
    assert out["fills"]["textAI"]["endpoint"].startswith("https://generativelanguage.googleapis.com/")


def test_sk_key_is_whoever_accepts_it(monkeypatch):
    monkeypatch.setattr(keyprobe, "_accepts", lambda pid, key, timeout=8.0: pid == "aliyun")
    out = keyprobe.detect("sk-fake")
    assert out["provider"] == "aliyun" and out["name"] == "通义千问"
    assert set(out["fills"]) == {"textAI", "visionAI", "embedAI"}


def test_nobody_accepts_says_so_without_echoing_key(monkeypatch):
    monkeypatch.setattr(keyprobe, "_accepts", lambda pid, key, timeout=8.0: False)
    out = keyprobe.detect("sk-secret-123")
    assert not out["ok"] and out["code"] == "NEEDS_HUMAN.AUTH_FAILED" and "sk-secret" not in json.dumps(out)


def test_bad_input_and_anthropic():
    assert keyprobe.detect("  ")["code"] == "SKIPPED.BAD_INPUT"
    assert keyprobe.detect("sk-ant-xyz")["code"] == "SKIPPED.UNSUPPORTED"


def test_cli_reads_key_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr(keyprobe, "_accepts", lambda pid, key, timeout=8.0: pid == "deepseek" and key == "sk-ds")
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-ds\n"))
    assert cli.main(["keys", "detect"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["provider"] == "deepseek" and "sk-ds" not in json.dumps(out)
