"""报警：号出事了不许不知不觉挂着跑（Owner 2026-09-04 点名）。

三件事：`looks_blocked` 分得清「号出事」和「这篇没了」；MCP 报错会升级成 `AccountBlockedError`
并给专门的退出码 5；`catch` 撞上就停车，不把后面的链接接着刷成失败。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from link_brain import alert as alert_mod, catch as catch_mod, cli, ingest, storage
from link_brain.adapters import xiaohongshu as xhs

XHS_URL = "https://www.xiaohongshu.com/explore/0000000000000000deadbeef"
OTHER_URL = "https://www.xiaohongshu.com/explore/1111111111111111cafebabe"


# --------------------------------------------------------------------------
# 分类
# --------------------------------------------------------------------------


def test_looks_service_down_catches_the_2026_09_04_failure():
    """实际踩到的那条：MCP 回「[launcher] Failed to get the debug url」，后面 7 条全 3 秒失败。"""
    assert xhs.looks_service_down(
        "工具 get_feed_detail 执行时发生内部错误: [launcher] Failed to get the debug url"
    )
    assert xhs.looks_service_down("All connection attempts failed")
    assert not xhs.looks_service_down("笔记不存在或已删除")


def test_looks_blocked_tells_account_trouble_from_missing_note():
    assert xhs.looks_blocked("MCP get_feed_detail 报错: 请登录后再试")
    assert xhs.looks_blocked("需要完成安全验证")
    assert xhs.looks_blocked("Too Many Requests")
    assert not xhs.looks_blocked("笔记不存在或已删除")
    assert not xhs.looks_blocked("")


# --------------------------------------------------------------------------
# 报警派发
# --------------------------------------------------------------------------


def test_alert_runs_external_command_with_json_on_stdin(tmp_path, monkeypatch):
    out = tmp_path / "got.json"
    script = tmp_path / "sink.py"
    # 注意子进程要按 UTF-8 读 stdin（Windows 上默认是 GBK，会把中文读成乱码）
    script.write_text(
        "import sys, pathlib\n"
        "data = sys.stdin.buffer.read().decode('utf-8')\n"
        f"pathlib.Path(r'{out}').write_text(data, encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(alert_mod.ENV_ALERT_CMD, f'"{sys.executable}" "{script}"')

    assert alert_mod.alert(alert_mod.KIND_ACCOUNT, "标题", "正文", url="u") is True
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["kind"] == alert_mod.KIND_ACCOUNT
    assert payload["title"] == "标题" and payload["body"] == "正文" and payload["url"] == "u"


def test_alert_without_command_still_writes_stderr(monkeypatch, capsys):
    monkeypatch.delenv(alert_mod.ENV_ALERT_CMD, raising=False)
    assert alert_mod.alert("k", "t", "b") is False
    assert "t" in capsys.readouterr().err


def test_alert_never_raises_when_command_is_broken(monkeypatch, capsys):
    monkeypatch.setenv(alert_mod.ENV_ALERT_CMD, "definitely-not-a-real-command-xyz")
    assert alert_mod.alert("k", "t", "b") is False  # 报警自己挂了也不能带走归档
    assert "报警命令" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 端到端：ingest / catch 撞上风控
# --------------------------------------------------------------------------


def _blocked_env(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.delenv(alert_mod.ENV_ALERT_CMD, raising=False)

    def boom(*a, **k):
        raise xhs.AccountBlockedError("小红书那侧要人处理（登录态失效 / 风控验证码）")

    monkeypatch.setattr(xhs, "fetch_detail", boom)


def test_ingest_returns_exit_code_5_on_account_trouble(tmp_path, monkeypatch, capsys):
    _blocked_env(tmp_path, monkeypatch)
    assert cli.main(["ingest", XHS_URL]) == ingest.EXIT_NEEDS_HUMAN
    err = capsys.readouterr().err
    assert "账号/风控" in err and "alert" in err


def test_catch_stops_at_first_blocked_link(tmp_path, monkeypatch, capsys):
    _blocked_env(tmp_path, monkeypatch)
    calls = {"n": 0}
    real = catch_mod._catch_one

    def counting(url, **kwargs):
        calls["n"] += 1
        return real(url, **kwargs)

    monkeypatch.setattr(catch_mod, "_catch_one", counting)

    code = cli.main(["catch", f"两条 {XHS_URL} 和 {OTHER_URL}"])
    assert code == catch_mod.EXIT_NEEDS_HUMAN
    payload = json.loads(capsys.readouterr().out)
    assert payload["found"] == 1  # 第二条根本没试
    assert payload["items"][0]["status"] == "blocked"
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# 偶发起不来要先重试，别一抖就停车
# --------------------------------------------------------------------------


def test_ingest_retries_flaky_browser_launch_before_giving_up(tmp_path, monkeypatch):
    """本机内存紧时 MCP 的 Chrome 会偶发起不来；第二次就成的话不该惊动人。"""
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(ingest.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise xhs.ServiceDownError("[launcher] Failed to get the debug url")
        return {"ok": True}

    monkeypatch.setattr(xhs, "fetch_detail", flaky)
    assert ingest._fetch_with_retry({"note_id": "x", "xsec_token": "t"}, log=lambda _: None) == {"ok": True}
    assert calls["n"] == 2


def test_ingest_gives_up_after_all_retries(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(ingest.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def always_down(*a, **k):
        calls["n"] += 1
        raise xhs.ServiceDownError("[launcher] Failed to get the debug url")

    monkeypatch.setattr(xhs, "fetch_detail", always_down)
    import pytest

    with pytest.raises(xhs.ServiceDownError):
        ingest._fetch_with_retry({"note_id": "x", "xsec_token": "t"}, log=lambda _: None)
    assert calls["n"] == ingest.SERVICE_RETRIES
