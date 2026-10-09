"""10-09 远程 MCP 设置页一批：库外文件夹（@ext）、口令 DPAPI 副本 / 随机生成 / 取回、单个客户端吊销、
主题改完当场重算命中、folders / probe 命令。合成数据，不联网。"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from link_brain import mcp_tools as mt, topics as tmod
from link_brain.remote import cli as rcli, secret_box
from link_brain.remote.policy import EXT, Denied, Policy, check_external
from link_brain.remote.store import AuthStore

from test_mcp_tools import vault  # noqa: F401 - fixture


# ---------------------------------------------------------------- 库外文件夹

def _ext_dir(tmp_path: Path) -> Path:
    d = tmp_path / "外面的笔记"
    (d / "子").mkdir(parents=True)
    (d / "a.md").write_text("# 外面\n\n鱼片", encoding="utf-8")
    (d / "子" / "b.txt").write_text("二级", encoding="utf-8")
    (d / ".hidden").mkdir()
    (d / ".hidden" / "x.md").write_text("不该读到", encoding="utf-8")
    (d / "api_key.txt").write_text("sk-xxx", encoding="utf-8")
    (d / "pic.png").write_bytes(b"\x89PNG")
    return d


def test_external_folder_read_list_and_guards(vault, tmp_path):  # noqa: F811
    ext = _ext_dir(tmp_path)
    pol = Policy.build(vault, ["@xhs", str(ext)])
    label = "外面的笔记"
    assert pol.externals == ((label, os.path.realpath(ext)),)
    assert f"{EXT}/{label}" in pol.folders and f"{EXT}/{label}" in pol.roots()
    assert pol.resolve_file(f"{EXT}/{label}/a.md").read_text("utf-8").startswith("# 外面")
    assert pol.resolve_file(f"{EXT}/{label}/子/b.txt").is_file()
    for bad, code in ((f"{EXT}/{label}/.hidden/x.md", "FORBIDDEN"), (f"{EXT}/{label}/api_key.txt", "FORBIDDEN"),
                      (f"{EXT}/{label}/pic.png", "NOT_TEXT"), (f"{EXT}/{label}/../a.md", "INVALID_PATH"),
                      (f"{EXT}/别的/a.md", "NOT_SHARED")):
        with pytest.raises(Denied) as e:
            pol.resolve_file(bad)
        assert e.value.code == code, bad
    c = mt.Ctx(policy=pol, local=False, who="测试")
    listed = mt.files(c, {"path": f"{EXT}/{label}"})
    dumped = json.dumps(listed, ensure_ascii=False)
    assert listed["kind"] == "dir" and "a.md" in dumped and ".hidden" not in dumped and "api_key" not in dumped
    got = mt.files(c, {"path": f"{EXT}/{label}/a.md"})
    assert got["kind"] == "file" and "鱼片" in json.dumps(got, ensure_ascii=False)
    # 本机 stdio：绝对路径互转
    lc = mt.Ctx(policy=pol, local=True, who="测试")
    assert mt._to_rel(lc, str(ext / "a.md")) == f"{EXT}/{label}/a.md"
    assert mt._abs(lc, f"{EXT}/{label}/a.md") == str(Path(os.path.realpath(ext)) / "a.md")
    with pytest.raises(Denied):
        mt._to_rel(lc, str(tmp_path / "别处.md"))


def test_external_folder_rejections(vault, tmp_path):  # noqa: F811
    with pytest.raises(Denied):
        check_external(vault, os.path.splitdrive(str(tmp_path))[0] + os.sep if os.name == "nt" else "/")
    with pytest.raises(Denied):
        check_external(vault, str(vault))                      # 库本身
    with pytest.raises(Denied):
        check_external(vault, str(Path(vault).parent))        # 包含库
    with pytest.raises(Denied):
        check_external(vault, str(tmp_path / "不存在"))
    # 失效的项在 build 时静默丢掉，不影响其他
    pol = Policy.build(vault, ["@xhs", str(tmp_path / "不存在")])
    assert pol.folders == ("@xhs",) and pol.externals == ()


def test_folders_command_lists_two_levels_and_externals(vault, tmp_path, monkeypatch, capsys):  # noqa: F811
    (Path(vault) / "读书" / "二级" / "三级").mkdir(parents=True)
    ext = _ext_dir(tmp_path)
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"remote": {"enabled": True, "folders": ["@xhs", str(ext), str(tmp_path / "没了")]}}), "utf-8")
    out = rcli.folders_payload(str(data))
    assert "读书" in out["folders"] and "读书/二级" in out["folders"] and "读书/二级/三级" not in out["folders"]
    assert [e["ok"] for e in out["externals"]] == [True, False]
    assert rcli.folders_payload(str(data), check=str(ext))["ok"] is True
    assert rcli.folders_payload(str(data), check=str(vault))["ok"] is False


# ---------------------------------------------------------------- 口令 / 客户端

def test_passphrase_copy_generate_reveal(tmp_path):
    st = AuthStore(tmp_path / "remote")
    assert st.reveal_passphrase() is None
    gen = st.generate_passphrase()
    assert len(gen) == 23 and gen.count("-") == 3
    st.set_passphrase(gen)
    assert st.check_passphrase(gen)
    raw = (tmp_path / "remote" / "auth.json").read_text("utf-8")
    assert gen not in raw
    if secret_box.supported():
        blob = secret_box.path(tmp_path / "remote").read_text("ascii")
        assert gen not in blob
        assert st.reveal_passphrase() == gen
        assert st.summary()["passphrase_copyable"] is True
        # 副本和哈希对不上（被换过）→ 不给
        secret_box.save(tmp_path / "remote", "另一个口令abc")
        assert st.reveal_passphrase() is None
    else:
        assert st.reveal_passphrase() is None


def test_cli_generate_and_reveal(tmp_path, capsys, monkeypatch):
    sdir = str(tmp_path / "remote")
    ns = SimpleNamespace(remote_command="passphrase", generate=True, reveal=False, state_dir=sdir, settings=None)
    assert rcli.run(ns) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] and out["passphrase"]
    ns2 = SimpleNamespace(remote_command="passphrase", generate=False, reveal=True, state_dir=sdir, settings=None)
    code = rcli.run(ns2)
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    if secret_box.supported():
        assert code == 0 and got["passphrase"] == out["passphrase"]
    else:
        assert code == 1 and got["code"] == "NO_COPY"


def test_revoke_single_client(tmp_path):
    st = AuthStore(tmp_path / "remote")
    a = st.register_client("claude.ai", ["https://claude.ai/cb"])["client_id"]
    b = st.register_client("ChatGPT", ["https://chatgpt.com/cb"])["client_id"]
    ta, tb = st.issue_oauth(a), st.issue_oauth(b)
    assert st.authenticate(ta["access_token"]) and st.authenticate(tb["access_token"])
    assert st.revoke_client(a) is True
    assert st.authenticate(ta["access_token"]) is None and st.refresh_owner(ta["refresh_token"]) is None
    assert st.authenticate(tb["access_token"])["label"] == "ChatGPT"
    assert st.revoke_client(a) is False
    assert [c["name"] for c in st.summary()["clients"]] == ["ChatGPT"]


# ---------------------------------------------------------------- 主题：当场重算

def test_topic_counts_are_fresh_after_create(vault, monkeypatch):  # noqa: F811
    c = mt.Ctx(policy=Policy.build(vault, ["@xhs"]), local=False, who="测试")
    made = mt.topics(c, {"action": "create", "name": "鱼", "keywords": ["鱼片"]})
    assert made["created"]["count"] == 1 and made["created"]["count_fresh"] is True
    assert "当场" in made["note"]
    up = mt.topics(c, {"action": "update", "topic": "鱼", "add_keywords": ["番茄"]})
    assert up["updated"]["count"] == 2
    got = mt.topics(c, {"action": "get", "topic": "鱼"})
    assert {i["id"] for i in got["topic"]["items"]} == {"abc12345", "bbb22222"} and "当场" in got["note"]
    listed = mt.topics(c, {})
    assert "note" in listed   # 目录还没重建（rebuild 被替身了）：list 如实说可能是旧的


def test_probe_without_domain(tmp_path):
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"remote": {"enabled": True}}), "utf-8")
    assert rcli.probe(str(data))["code"] == "NO_DOMAIN"


def test_status_has_stdio_snippet(tmp_path):
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"remote": {"enabled": False}}), "utf-8")
    out = rcli.status(str(data), str(tmp_path / "remote"))
    assert "link_brain" in out["stdio"]["json"] and out["stdio"]["claude_code"].startswith("claude mcp add")
