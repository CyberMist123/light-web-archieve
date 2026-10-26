"""r5 补测：远程访问的口令 / 令牌仓（AuthStore 全程 tmp 目录；令牌只存哈希；不出网、不起进程）。"""
from __future__ import annotations

import json
import sys

from link_brain.remote import store

_WIN = sys.platform == "win32"


def test_passphrase_scrypt_roundtrip(tmp_path):
    s = store.AuthStore(tmp_path)
    assert s.passphrase_set() is False
    try:
        s.set_passphrase("short")
        raise AssertionError("太短的口令必须拒绝")
    except ValueError as exc:
        assert "8" in str(exc)
    s.set_passphrase("一串够长的口令哦")
    assert s.passphrase_set() is True
    assert s.check_passphrase("一串够长的口令哦") is True
    assert s.check_passphrase("错的口令错的口令") is False
    assert s.check_passphrase("") is False and s.check_passphrase(None) is False
    rec = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))["passphrase"]
    assert rec["algo"] == "scrypt" and rec["n"] == 2 ** 14 and rec["r"] == 8 and rec["p"] == 1
    assert "一串够长的口令哦" not in (tmp_path / "auth.json").read_text(encoding="utf-8")  # 文件里只有哈希
    # DPAPI 可取回副本只在 Windows 落；reveal 出来的必须还能过校验
    assert (tmp_path / "passphrase.dpapi").exists() is _WIN
    revealed = s.reveal_passphrase()
    assert (revealed == "一串够长的口令哦") if _WIN else (revealed is None)


def test_generate_passphrase_shape():
    pw = store.AuthStore.generate_passphrase()
    groups = pw.split("-")
    assert len(groups) == 4 and all(len(g) == 5 for g in groups)
    assert not (set(pw) - {"-"}) & set("0O1lI")   # 去掉易混字符（横杠分隔符除外）


def test_client_register_issue_and_rotate(tmp_path):
    s = store.AuthStore(tmp_path)
    reg = s.register_client("网页版", ["https://cb.example/cb"])
    assert reg["client_id"].startswith("lbc_") and s.client(reg["client_id"])["name"] == "网页版"
    assert s.issue_oauth("lbc_不存在") is None          # 没注册的客户端发不了
    pair = s.issue_oauth(reg["client_id"])
    assert pair["access_token"].startswith("lbr_a_") and pair["refresh_token"].startswith("lbr_r_")
    assert pair["expires_in"] == store.ACCESS_TTL
    assert s.refresh_owner(pair["refresh_token"]) == reg["client_id"]
    # 轮换：旧刷新令牌换新对，旧的立刻作废
    pair2 = s.issue_oauth(reg["client_id"], old_refresh=pair["refresh_token"])
    assert pair2 is not None and pair2["refresh_token"] != pair["refresh_token"]
    assert s.refresh_owner(pair["refresh_token"]) is None
    assert s.refresh_owner(pair2["refresh_token"]) == reg["client_id"]
    # 别人家的刷新令牌冒充：核不过、什么都不发
    assert s.issue_oauth(reg["client_id"], old_refresh="lbr_r_bogus") is None


def test_authenticate_kinds_and_revocation(tmp_path):
    s = store.AuthStore(tmp_path)
    tok = s.new_personal("")["token"]                    # 空标签 → 默认名
    ident = s.authenticate(tok)
    assert ident == {"kind": "personal", "id": ident["id"], "label": "访问令牌"}
    assert s.authenticate("lbr_p_错的") is None and s.authenticate("garbage") is None
    assert s.authenticate("lbr_x_前缀不对") is None      # 只认 a/p 两类
    assert s.authenticate("lbr_a_" + "x" * 300) is None  # 超长直接拒
    reg = s.register_client("某客户端", [])
    access = s.issue_oauth(reg["client_id"])["access_token"]
    assert s.authenticate(access) == {"kind": "oauth", "id": reg["client_id"], "label": "某客户端"}
    # 吊销客户端 = 注册和名下访问 / 刷新令牌一起没
    assert s.revoke_client(reg["client_id"]) is True and s.revoke_client(reg["client_id"]) is False
    assert s.authenticate(access) is None and s.client(reg["client_id"]) is None
    # 撤销全部：清客户端和令牌，口令保留
    s.revoke_all()
    assert s.authenticate(tok) is None
    assert s.passphrase_set() is False                    # 本测试没设过口令
    summ = s.summary()
    assert summ["clients"] == [] and summ["personal"] == [] and summ["revoked_all_at"]


def test_summary_lists_connected_and_personal(tmp_path):
    s = store.AuthStore(tmp_path)
    s.set_passphrase("一串够长的口令哦")
    pending = s.register_client("还没换令牌的", [])
    connected = s.register_client("已连上的", [])
    s.issue_oauth(connected["client_id"])
    p = s.new_personal("手机上的客户端")
    summ = s.summary()
    assert [c["name"] for c in summ["clients"]] == ["已连上的"]   # 没换到令牌的不算已连接
    assert [r["label"] for r in summ["personal"]] == ["手机上的客户端"]
    assert summ["live_sessions"] == 1 and summ["passphrase_set"] is True
    assert summ["passphrase_copyable"] is _WIN and summ["corrupt"] is False


def test_corrupt_file_fail_closed(tmp_path):
    s = store.AuthStore(tmp_path)
    s.set_passphrase("一串够长的口令哦")
    p = s.new_personal("标签")["token"]
    assert s.authenticate(p) is not None
    (tmp_path / "auth.json").write_text("{坏掉", encoding="utf-8")
    s2 = store.AuthStore(tmp_path)                        # 新实例读坏文件：当空仓，不抛也不覆盖
    assert s2.summary()["corrupt"] is True
    assert s2.passphrase_set() is False and s2.authenticate(p) is None
    assert (tmp_path / "auth.json").read_text(encoding="utf-8") == "{坏掉"   # 原文件没被动


def test_access_log_and_status_roundtrip(tmp_path):
    assert store.recent_access(directory=tmp_path) == []  # 没有日志文件
    store.log_access({"who": "personal:pt_1", "tool": "search", "ok": True}, directory=tmp_path)
    store.log_access({"who": "personal:pt_1", "tool": "read", "ok": False}, directory=tmp_path)
    rows = store.recent_access(directory=tmp_path)
    assert [r["tool"] for r in rows] == ["read", "search"]  # 新的在前
    assert all("token" not in r and "ts" in r for r in rows)
    assert store.read_status(directory=tmp_path) == {}    # 没有 status 文件
    store.write_status({"pid": 123}, directory=tmp_path)
    st = store.read_status(directory=tmp_path)
    assert st["pid"] == 123 and "updated_at" in st
    (tmp_path / "status.json").write_text("not-json", encoding="utf-8")
    assert store.read_status(directory=tmp_path) == {}    # 坏了回空


def test_personal_label_trim_and_cap(tmp_path):
    s = store.AuthStore(tmp_path)
    long = "名" * 50
    out = s.new_personal(long)
    assert out["label"] == "名" * 40                        # 标签截到 40
    assert out["id"].startswith("pt_") and out["token"].startswith("lbr_p_")
    # 文件里存的只是哈希，令牌明文不落盘
    assert out["token"] not in (tmp_path / "auth.json").read_text(encoding="utf-8")
    assert s.revoke_personal(out["id"]) is True and s.revoke_personal(out["id"]) is False
