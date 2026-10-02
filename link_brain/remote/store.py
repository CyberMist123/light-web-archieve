"""口令与令牌：`$LINK_BRAIN_HOME/remote/auth.json`（默认 ~/.link-brain/remote/），不进 data.json、不进仓库。

- 口令只存 scrypt 哈希（盐 16 字节，n=2**14 r=8 p=1）。
- 令牌只存 sha256（明文只在生成的那一刻出现一次）：
  · OAuth 访问令牌 `lbr_a_…`：1 小时；刷新令牌 `lbr_r_…`：90 天，用一次换一张新的（旧的作废）。
  · 给其他客户端的访问令牌 `lbr_p_…`：不过期，直到撤销。
- 动态注册的客户端：名字 + 回调地址；一小时内没换到令牌的注册会被清掉（防止被刷满）。
- 「撤销全部访问」= 清空客户端 / 全部令牌（口令保留）；之后所有客户端都要重新授权。

服务进程和设置页的 CLI 都会写这份文件：读改写一律在 `storage.file_lock("remote-auth")` 里做，原子写；
服务按 mtime 发现别人改过就重读（撤销立即生效）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .. import storage

ENV_DIR = "LINK_BRAIN_REMOTE_DIR"
ACCESS_TTL = 3600
REFRESH_TTL = 90 * 86400
PENDING_CLIENT_TTL = 3600
MAX_CLIENTS = 200
MAX_PERSONAL = 50
PASS_MIN = 8
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)
LAST_USED_EVERY = 300   # 「最近用过」最多每 5 分钟落一次盘


def state_dir() -> Path:
    env = os.environ.get(ENV_DIR)
    if env:
        return Path(env)
    base = os.environ.get("LINK_BRAIN_HOME") or str(Path.home() / ".link-brain")
    return Path(base) / "remote"


def _now() -> float:
    return time.time()


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _empty() -> dict[str, Any]:
    return {"schema_version": 1, "passphrase": None, "clients": {}, "access": {}, "refresh": {}, "personal": {},
            "revoked_all_at": None}


class AuthStore:
    def __init__(self, directory: str | os.PathLike | None = None):
        self.dir = Path(directory) if directory else state_dir()
        self.path = self.dir / "auth.json"
        self._mem_lock = threading.RLock()
        self._data: dict[str, Any] = _empty()
        self._stamp: tuple | None = None
        self._last_used_flush: dict[str, float] = {}
        self._reload(force=True)

    # —— 文件 ——
    def _stat(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _reload(self, force: bool = False) -> None:
        stamp = self._stat()
        if not force and stamp == self._stamp:
            return
        data = _empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k in data:
                    if k in raw and raw[k] is not None:
                        data[k] = raw[k]
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            # 坏文件：当成空（fail-closed：没有任何令牌能用），不覆盖原文件，等用户「撤销全部」重建
            data["_corrupt"] = True
        self._data = data
        self._stamp = stamp

    def _mutate(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        """锁内重读 → 改 → 原子写。"""
        with self._mem_lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with storage.file_lock("remote-auth", wait_s=10, owner="remote"):
                self._reload(force=True)
                data = {k: v for k, v in self._data.items() if not k.startswith("_")}
                result = fn(data)
                storage.write_json(self.path, data)
                self._data = data
                self._stamp = self._stat()
                return result

    def view(self) -> dict[str, Any]:
        with self._mem_lock:
            self._reload()
            return self._data

    # —— 口令 ——
    def passphrase_set(self) -> bool:
        return bool(self.view().get("passphrase"))

    def set_passphrase(self, passphrase: str) -> None:
        if not isinstance(passphrase, str) or len(passphrase) < PASS_MIN:
            raise ValueError(f"口令至少 {PASS_MIN} 个字符")
        if len(passphrase) > 256:
            raise ValueError("口令太长")
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, **_SCRYPT)

        def apply(d):
            d["passphrase"] = {"salt": salt.hex(), "hash": digest.hex(), "algo": "scrypt", **{k: _SCRYPT[k] for k in ("n", "r", "p")},
                               "set_at": _iso(_now())}
        self._mutate(apply)

    def check_passphrase(self, passphrase: str) -> bool:
        rec = self.view().get("passphrase")
        if not rec or not isinstance(passphrase, str) or not passphrase or len(passphrase) > 256:
            return False
        try:
            digest = hashlib.scrypt(passphrase.encode("utf-8"), salt=bytes.fromhex(rec["salt"]),
                                    n=int(rec["n"]), r=int(rec["r"]), p=int(rec["p"]), dklen=32)
        except (KeyError, ValueError, TypeError):
            return False
        return hmac.compare_digest(digest.hex(), str(rec.get("hash", "")))

    # —— 动态注册 ——
    def register_client(self, name: str, redirect_uris: list[str]) -> dict[str, Any]:
        client_id = "lbc_" + secrets.token_urlsafe(18)
        now = _now()

        def apply(d):
            clients = d["clients"]
            # 清掉一小时内没换到令牌的注册（防刷满）
            for cid, c in list(clients.items()):
                if not c.get("token_at") and now - float(c.get("created", 0)) > PENDING_CLIENT_TTL:
                    clients.pop(cid, None)
            if len(clients) >= MAX_CLIENTS:
                raise ValueError("已注册的客户端太多：到设置里「撤销全部访问」后再连")
            clients[client_id] = {"name": name, "redirect_uris": redirect_uris, "created": now, "token_at": None,
                                  "last_used": None}
        self._mutate(apply)
        return {"client_id": client_id, "name": name, "redirect_uris": redirect_uris}

    def client(self, client_id: str) -> dict[str, Any] | None:
        c = self.view()["clients"].get(client_id) if isinstance(client_id, str) else None
        return c if isinstance(c, dict) else None

    # —— 令牌 ——
    def issue_oauth(self, client_id: str, *, old_refresh: str | None = None) -> dict[str, Any] | None:
        """发一对新令牌；old_refresh 给了就先核对并作废它（轮换）。核不过 → None。"""
        access = "lbr_a_" + secrets.token_urlsafe(32)
        refresh = "lbr_r_" + secrets.token_urlsafe(32)
        now = _now()

        def apply(d):
            if client_id not in d["clients"]:
                return False
            if old_refresh is not None:
                rec = d["refresh"].get(token_hash(old_refresh))
                if not rec or rec.get("client_id") != client_id or float(rec.get("expires", 0)) < now:
                    return False
                d["refresh"].pop(token_hash(old_refresh), None)
            for table in ("access", "refresh"):   # 顺手清过期的
                for h, rec in list(d[table].items()):
                    if float(rec.get("expires", 0)) < now:
                        d[table].pop(h, None)
            d["access"][token_hash(access)] = {"client_id": client_id, "expires": now + ACCESS_TTL}
            d["refresh"][token_hash(refresh)] = {"client_id": client_id, "expires": now + REFRESH_TTL}
            d["clients"][client_id]["token_at"] = now
            return True
        if not self._mutate(apply):
            return None
        return {"access_token": access, "refresh_token": refresh, "expires_in": ACCESS_TTL}

    def refresh_owner(self, refresh: str) -> str | None:
        rec = self.view()["refresh"].get(token_hash(refresh)) if isinstance(refresh, str) else None
        if not rec or float(rec.get("expires", 0)) < _now():
            return None
        return rec.get("client_id")

    def new_personal(self, label: str) -> dict[str, Any]:
        label = (str(label or "").strip() or "访问令牌")[:40]
        token = "lbr_p_" + secrets.token_urlsafe(32)
        tid = "pt_" + secrets.token_hex(4)

        def apply(d):
            if len(d["personal"]) >= MAX_PERSONAL:
                raise ValueError(f"访问令牌最多 {MAX_PERSONAL} 个，先撤销不用的")
            d["personal"][tid] = {"hash": token_hash(token), "label": label, "created": _now(), "last_used": None}
        self._mutate(apply)
        return {"id": tid, "label": label, "token": token}

    def revoke_personal(self, tid: str) -> bool:
        return bool(self._mutate(lambda d: d["personal"].pop(tid, None) is not None))

    def revoke_all(self) -> dict[str, int]:
        def apply(d):
            counts = {"clients": len(d["clients"]), "tokens": len(d["access"]) + len(d["refresh"]),
                      "personal": len(d["personal"])}
            d["clients"], d["access"], d["refresh"], d["personal"] = {}, {}, {}, {}
            d["revoked_all_at"] = _iso(_now())
            return counts
        return self._mutate(apply)

    def authenticate(self, bearer: str | None) -> dict[str, Any] | None:
        """Bearer → 身份 {kind, id, label}；不认识 / 过期 / 已撤销 → None。"""
        if not isinstance(bearer, str) or not bearer.startswith("lbr_") or len(bearer) > 200:
            return None
        h = token_hash(bearer)
        d = self.view()
        now = _now()
        if bearer.startswith("lbr_a_"):
            rec = d["access"].get(h)
            if not rec or float(rec.get("expires", 0)) < now:
                return None
            client = d["clients"].get(rec.get("client_id"))
            if not client:
                return None
            ident = {"kind": "oauth", "id": rec["client_id"], "label": client.get("name") or "OAuth 客户端"}
        elif bearer.startswith("lbr_p_"):
            for tid, rec in d["personal"].items():
                if hmac.compare_digest(str(rec.get("hash", "")), h):
                    ident = {"kind": "personal", "id": tid, "label": rec.get("label") or "访问令牌"}
                    break
            else:
                return None
        else:
            return None
        self._touch(ident)
        return ident

    def _touch(self, ident: dict[str, Any]) -> None:
        key = ident["kind"] + ":" + ident["id"]
        now = _now()
        if now - self._last_used_flush.get(key, 0) < LAST_USED_EVERY:
            return
        self._last_used_flush[key] = now

        def apply(d):
            table = d["clients"] if ident["kind"] == "oauth" else d["personal"]
            if ident["id"] in table:
                table[ident["id"]]["last_used"] = now
        try:
            self._mutate(apply)
        except Exception:  # noqa: BLE001 - 记「最近用过」失败不影响这次访问
            pass

    def summary(self) -> dict[str, Any]:
        d = self.view()
        now = _now()
        clients = []
        for cid, c in d["clients"].items():
            if not c.get("token_at"):
                continue
            clients.append({"id": cid, "name": c.get("name") or "OAuth 客户端", "connected_at": _iso(c.get("token_at")),
                            "last_used": _iso(c.get("last_used"))})
        personal = [{"id": tid, "label": r.get("label"), "created": _iso(r.get("created")), "last_used": _iso(r.get("last_used"))}
                    for tid, r in d["personal"].items()]
        live_refresh = sum(1 for r in d["refresh"].values() if float(r.get("expires", 0)) >= now)
        return {"passphrase_set": bool(d.get("passphrase")), "passphrase_set_at": (d.get("passphrase") or {}).get("set_at"),
                "clients": clients, "personal": personal, "live_sessions": live_refresh,
                "revoked_all_at": d.get("revoked_all_at"), "corrupt": bool(d.get("_corrupt"))}


# —— 访问日志 / 状态文件 ——

LOG_MAX = 1024 * 1024


def access_log_path(directory: Path | None = None) -> Path:
    return (directory or state_dir()) / "access.log"


def status_path(directory: Path | None = None) -> Path:
    return (directory or state_dir()) / "status.json"


_LOG_LOCK = threading.Lock()


def log_access(entry: dict[str, Any], directory: Path | None = None) -> None:
    """一行一条：时间、谁、工具、路径、结果——不记查询词、不记内容、不记令牌。"""
    path = access_log_path(directory)
    row = {"ts": _iso(_now()), **{k: v for k, v in entry.items() if v is not None}}
    line = json.dumps(row, ensure_ascii=False)[:2000] + "\n"
    with _LOG_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > LOG_MAX:
                os.replace(path, path.with_suffix(".log.1"))
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


def recent_access(limit: int = 20, directory: Path | None = None) -> list[dict[str, Any]]:
    path = access_log_path(directory)
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 64 * 1024))
            tail = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(tail):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
        if len(out) >= limit:
            break
    return out


def write_status(payload: dict[str, Any], directory: Path | None = None) -> None:
    try:
        storage.write_json(status_path(directory), {**payload, "updated_at": _iso(_now())})
    except OSError:
        pass


def read_status(directory: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads(status_path(directory).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
