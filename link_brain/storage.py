"""vault 路径解析 + RAW 版本管理 + 原子写 + 跨入口文件锁（CONVENTIONS §6.4 / §6.5）。

RAW 不可变：`raw/v0001/` 一旦写完就不再打开写。任何修正写 `v0002`。
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from . import ARCHIVE_DIRNAME, INDEX_DB_NAME, VAULT_DIRNAME, VISIBLE_SUBDIR

ENV_VAULT = "LINK_BRAIN_VAULT"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def link_brain_home() -> Path:
    """程序自己的状态目录：`$LINK_BRAIN_HOME`，默认 `~/.link-brain`（锁、日志、读取组件、用户配置都住这里）。"""
    return Path(os.environ.get("LINK_BRAIN_HOME") or str(Path.home() / ".link-brain"))


def user_config_path() -> Path:
    return link_brain_home() / "config.json"


_USER_CONFIG_CACHE: dict = {}


def user_config() -> dict:
    """`~/.link-brain/config.json`（第 5 批）：不属于某个 vault 的用户级设置，如 `vault`（收藏库位置）、
    `gemini_keys_cmd` / `gemini_keys_file`（夜跑精细识图的 key 来源）、`xhs_tool_dir`（读取组件目录）。
    没有文件 / 读不动 / 不是对象 = 空字典（fail-open）。按 mtime 缓存，vault_root() 频繁调用也不反复读盘。"""
    p = user_config_path()
    try:
        st = p.stat()
    except OSError:
        return {}
    key = (str(p), st.st_mtime_ns, st.st_size)
    if _USER_CONFIG_CACHE.get("key") == key:
        return dict(_USER_CONFIG_CACHE["data"])
    try:
        data = json.loads(p.read_text("utf-8-sig"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _USER_CONFIG_CACHE.update(key=key, data=data)
    return dict(data)


def vault_root() -> Path:
    """vault 根目录（第 5 批：程序位置和收藏库位置解耦）。

    顺序：环境变量 LINK_BRAIN_VAULT → `~/.link-brain/config.json` 的 `vault` → 旧默认「程序目录/vault」
    （作者本机现状不变）。插件调用时总会传 LINK_BRAIN_VAULT；计划任务 / 命令行靠后两者。"""
    override = os.environ.get(ENV_VAULT)
    if override:
        return Path(override).resolve()
    configured = user_config().get("vault")
    if isinstance(configured, str) and configured.strip():
        return Path(os.path.expandvars(configured.strip())).expanduser().resolve()
    return repo_root() / VAULT_DIRNAME


def archive_root() -> Path:
    return vault_root() / ARCHIVE_DIRNAME


def index_db_path() -> Path:
    return archive_root() / INDEX_DB_NAME


def visible_dir() -> Path:
    return vault_root().joinpath(*VISIBLE_SUBDIR)


def object_dir(source: str, source_id: str) -> Path:
    """`vault/_archive/<source>/<source_id>/`"""
    return archive_root() / source / source_id


def raw_dir(source: str, source_id: str, version: int) -> Path:
    return object_dir(source, source_id) / "raw" / version_name(version)


def derived_dir(source: str, source_id: str) -> Path:
    return object_dir(source, source_id) / "derived"


def version_name(version: int) -> str:
    return f"v{version:04d}"


def existing_versions(source: str, source_id: str) -> list[int]:
    base = object_dir(source, source_id) / "raw"
    if not base.is_dir():
        return []
    out = []
    for child in base.iterdir():
        if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
            out.append(int(child.name[1:]))
    return sorted(out)


def next_version(source: str, source_id: str) -> int:
    versions = existing_versions(source, source_id)
    return (versions[-1] + 1) if versions else 1


def ensure_raw_dir(source: str, source_id: str, version: int) -> Path:
    """创建 raw/vNNNN/assets/ 并返回 raw 版本目录。已存在则拒绝（RAW 不可变）。"""
    target = raw_dir(source, source_id, version)
    if target.exists():
        raise FileExistsError(f"RAW 版本已存在，不可覆写: {target}")
    (target / "assets").mkdir(parents=True)
    return target


# 原子写替换一直被拒时允许「原地覆写」的派生文件（能整份重生成的）：页面（md / 页面脚本 / 样式）、
# 对象的 derived/ 下、_archive/ 根上的目录数据。其余（meta.json、notes.json、raw/、设置…）都是真相文件。
_IN_PLACE_SUFFIXES = {".md", ".js", ".css"}
_IN_PLACE_ARCHIVE_FILES = {"catalog-data.json", "trash-data.json", "problems-summary.json"}


def in_place_fallback_ok(path: Path) -> bool:
    p = Path(path)
    if p.suffix.lower() in _IN_PLACE_SUFFIXES:
        return True
    if "derived" in p.parent.parts:
        return True
    return p.parent.name == ARCHIVE_DIRNAME and p.name in _IN_PLACE_ARCHIVE_FILES


def atomic_write_bytes(path: Path, data: bytes) -> Path:
    """原子写（审计 io-11 / raw-1）：同目录临时文件 → fsync → os.replace。

    进程写到一半被杀（计划任务上限、lwa 超时、关 Obsidian 带走子进程）时，
    目标文件要么是旧的完整内容、要么是新的完整内容，不会留半截。
    Windows 上目标正被别的进程（Obsidian / 同步软件）短暂打开时 os.replace 会 PermissionError，稍等重试几次。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    # 1011：Obsidian 渲染进程会长期开着某些 md（不带 FILE_SHARE_DELETE），替换永远被拒——
                    # 目录页因此从 10-10 13:59 起一直没更新、夜跑 catalog 天天崩。退而原地覆写（它允许共享写）；
                    # 失去「不留半截」保证，所以只给能整份重生成的派生文件（1024：meta.json / notes.json 这些
                    # 真相文件写不上就抛错，由调用方如实报，不冒险留半截）。
                    if not path.exists() or not in_place_fallback_ok(path):
                        raise
                    with open(path, "r+b") as out:
                        out.write(data)
                        out.truncate()
                        out.flush()
                        os.fsync(out.fileno())
                    os.unlink(tmp)
                    break
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def atomic_write_text(path: Path, text: str) -> Path:
    return atomic_write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, payload) -> Path:
    return atomic_write_text(
        path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    )


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> tuple[list[dict], int]:
    """读 append-only jsonl：(各行 dict, 跳过的坏行数)。没有文件 = ([], 0)；别的 OSError 照抛。

    按字节读、逐行解码：写到一半崩了，行尾截在汉字中间，只丢那一行（和 JSON 坏行一样跳过并计数），
    不拖累整份文件。空行不算坏行；不是 dict 的行算坏行。"""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return [], 0
    rows: list[dict] = []
    bad = 0
    for raw in data.splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    return rows, bad


def obj_lock_name(item_id: str) -> str:
    """单篇锁的名字：同一篇的 meta.json 读改写都在这把锁里（1024）。"""
    return f"obj-{item_id}"


def update_json(path: Path, fn, *, lock_name: str, wait_s: float = 60, missing_ok: bool = False):
    """读改写一个 JSON 文件（1024）：拿锁 → 重读 → fn 改 → 原子写。返回写后的内容。

    fn(data) 原地改 data（也可以返回一个新 dict 代替）；**只改自己负责的键**，别拿手上的旧副本整份写回。
    内容没变就不写。文件不存在：missing_ok=False 抛 FileNotFoundError；True 则从 {} 开始。
    拿不到锁抛 LockBusy；写不上照原样抛（真相文件没有原地覆写退路）。"""
    path = Path(path)
    with file_lock(lock_name, wait_s=wait_s, owner=lock_name):
        try:
            data = read_json(path)
        except FileNotFoundError:
            if not missing_ok:
                raise
            data = {}
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        result = fn(data)
        if result is not None:
            data = result
        if path.exists() and json.dumps(data, ensure_ascii=False, sort_keys=True) == before:
            return data
        write_json(path, data)
        return data


# ---------------------------------------------------------------------------
# 跨入口文件锁（CONVENTIONS §6.4）：O_EXCL 建锁文件 + 心跳 + 陈旧判定。
# 从 accounts.py 的账号锁抽出来；账号锁是它的一个实例（accounts.account_session）。
# 锁文件内容 = {pid, owner, started, heartbeat, heartbeat_ts}；同一进程可重入。
# 陈旧 = 持有进程确认已退出，或心跳停了 stale_s 秒（拒绝访问打不开的进程按心跳判，不当死）。
# ---------------------------------------------------------------------------

LOCK_STALE_SECONDS = 10 * 60
LOCK_HEARTBEAT_SECONDS = 60
_HELD: dict[str, dict] = {}
_HELD_GUARD = threading.Lock()


class LockBusy(RuntimeError):
    """wait_s 内拿不到锁。`holder` = 锁文件内容（pid / owner / started / heartbeat）。"""

    def __init__(self, name: str, holder: dict | None = None):
        self.name = name
        self.holder = holder or {}
        owner = self.holder.get("owner") or "别的任务"
        super().__init__(f"「{name}」正被「{owner}」占用，稍后再试")


def locks_dir() -> Path:
    """具名锁住这里：`$LINK_BRAIN_HOME/locks`（默认 ~/.link-brain/locks），不进 vault（vault 会被同步到别处）。"""
    return link_brain_home() / "locks"


def pid_state(pid) -> str:
    """'alive' / 'dead' / 'unknown'。只有确认进程不在了才是 dead。

    Windows 上 OpenProcess 失败不一定是进程没了：拒绝访问（别的用户 / 会话、提权进程）也会失败。
    那种情况算 unknown，交给心跳判陈旧，别把别人活着的锁当垃圾接管。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return "dead"
    if pid <= 0:
        return "dead"
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            err = ctypes.get_last_error()
            return "dead" if err == 87 else "unknown"  # 87 = ERROR_INVALID_PARAMETER：没有这个进程
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return "unknown"
            return "alive" if code.value == 259 else "dead"  # 259 = STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return "alive"
    except ProcessLookupError:
        return "dead"
    except OSError:
        return "unknown"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class FileLock:
    """一把具体的锁（一个锁文件）。进程内状态按路径登记在 _HELD 里，所以对象可以随用随建。"""

    def __init__(self, path: Path, *, name: str | None = None, stale_s: float | None = None,
                 heartbeat_s: float | None = None, pid_state_fn=None, poll_s: float = 0.5):
        self.path = Path(path)
        self.poll_s = poll_s  # 等锁时多久再试一次（账号锁一等就是几分钟，用 5 秒；目录重建这种秒级的用 0.5 秒）
        self.name = name or self.path.stem
        self.stale_s = LOCK_STALE_SECONDS if stale_s is None else stale_s
        self.heartbeat_s = LOCK_HEARTBEAT_SECONDS if heartbeat_s is None else heartbeat_s
        self.pid_state = pid_state_fn or pid_state
        self.key = os.path.normcase(os.path.abspath(str(self.path)))

    # -- 进程内状态 --
    def state(self) -> dict:
        with _HELD_GUARD:
            # 1024：mutex 是进程内的线程锁——重入只认「同一个线程」，别的线程在这里排队（远程服务多线程）
            return _HELD.setdefault(self.key, {"count": 0, "stop": None, "thread": None, "owner": "",
                                               "started": "", "lost": False, "mutex": threading.RLock()})

    @property
    def lost(self) -> bool:
        return bool(self.state().get("lost"))

    # -- 锁文件 --
    def read(self) -> tuple[str | None, dict | None]:
        try:
            raw = self.path.read_text("utf-8")
        except FileNotFoundError:
            return None, None
        except OSError:
            return "", None  # 正在被改写（Windows 上 replace 那一瞬）：当它还在
        try:
            data = json.loads(raw)
        except ValueError:
            return raw, None
        return raw, data if isinstance(data, dict) else None

    def is_stale(self, info: dict | None) -> bool:
        if not info:
            try:
                return time.time() - self.path.stat().st_mtime > 60  # 写坏的锁文件：放一分钟再当垃圾
            except OSError:
                return False
        pid = info.get("pid")
        if pid == os.getpid() and not self.state()["count"]:
            return True  # 本进程以前没放掉的
        if self.pid_state(pid) == "dead":
            return True
        beat = info.get("heartbeat_ts")
        if not isinstance(beat, (int, float)):
            try:
                beat = datetime.fromisoformat(str(info.get("heartbeat"))).timestamp()
            except ValueError:
                beat = 0
        return time.time() - beat > self.stale_s

    def holder(self) -> dict | None:
        """别的活进程正占着 → 锁内容；没人占 / 陈旧锁 / 本进程自己 → None。"""
        raw, info = self.read()
        if raw is None:
            return None
        if self.is_stale(info):
            return None
        if info and info.get("pid") == os.getpid():
            return None
        return info or {"owner": "另一个任务"}

    def _payload(self, owner: str, started: str) -> str:
        return json.dumps({"pid": os.getpid(), "owner": owner, "started": started,
                           "heartbeat": _now_iso(), "heartbeat_ts": time.time()}, ensure_ascii=False)

    def try_take(self, owner: str) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = _now_iso()
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raw, info = self.read()
                if raw is None:
                    continue  # 刚被放掉
                if not self.is_stale(info):
                    return False
                # 陈旧锁：先挪走再抢。os.rename 只有一个进程能成功；挪到手的内容和刚才判陈旧的不一样
                # （别人抢先换上了新锁）就原样放回去。
                aside = self.path.with_name(f"{self.path.name}.{os.getpid()}.stale")
                try:
                    os.rename(self.path, aside)
                except OSError:
                    return False
                try:
                    moved = aside.read_text("utf-8")
                except OSError:
                    moved = raw
                if moved != raw:
                    try:
                        os.rename(aside, self.path)
                    except OSError:
                        pass
                    return False
                aside.unlink(missing_ok=True)
                print(f"[lock] 接管陈旧的锁「{self.name}」（{(info or {}).get('owner')} pid={(info or {}).get('pid')}）",
                      file=sys.stderr)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self._payload(owner, started))
            self.state()["started"] = started
            return True
        return False

    def _heartbeat(self, stop: threading.Event, owner: str, every: float) -> None:
        while not stop.wait(every):
            raw, info = self.read()
            if raw == "":
                continue  # 正在被改写的那一瞬，下一拍再看
            if not info or info.get("pid") != os.getpid():
                # 锁被当成陈旧的接管了（笔记本睡过 10 分钟等）：不去抢回来，但标记 lost，让持有方停手。
                self.state()["lost"] = True
                print(f"[lock] 锁「{self.name}」被别的任务接管了：本任务做完手上这一步就停", file=sys.stderr)
                return
            try:
                atomic_write_text(self.path, self._payload(owner, self.state().get("started") or _now_iso()))
            except OSError:
                pass  # 这一拍没写上，陈旧判定的余量够下一拍补

    def release(self) -> None:
        st = self.state()
        stop = st.get("stop")
        if stop:
            stop.set()
        _, info = self.read()
        if info and info.get("pid") == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass
        st.update(stop=None, thread=None, owner="", lost=False)

    # -- 1009：「我在等」标记。后台补跑这类可以晚点做的活拿锁前先看有没有别人在等，有就让（polite）。
    def _want_path(self, pid: int | None = None) -> Path:
        return self.path.with_name(f"{self.path.name}.want-{pid or os.getpid()}")

    def _announce(self, owner: str) -> Path | None:
        p = self._want_path()
        try:
            atomic_write_text(p, json.dumps({"pid": os.getpid(), "owner": owner, "ts": time.time()}, ensure_ascii=False))
            return p
        except OSError:
            return None

    def wanted_by_others(self) -> list[dict]:
        """别的活进程正在等这把锁（它们留了「我在等」标记）。死进程 / 两小时前的旧标记顺手清掉。"""
        out = []
        try:
            marks = list(self.path.parent.glob(self.path.name + ".want-*"))
        except OSError:
            return out
        for p in marks:
            try:
                info = json.loads(p.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            pid = info.get("pid") if isinstance(info, dict) else None
            if pid == os.getpid():
                continue
            ts = info.get("ts") if isinstance(info.get("ts"), (int, float)) else 0
            if self.pid_state(pid) == "dead" or time.time() - ts > 2 * 3600:
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            out.append(info)
        return out

    @contextlib.contextmanager
    def hold(self, owner: str = "", wait_s: float = 0, on_wait=None, *, polite: bool = False):
        """拿锁（同一进程可重入）。wait_s 内拿不到 → LockBusy。on_wait(holder, 剩余秒) 第一次要等时调一次。

        1009：要等的时候留一个「我在等」标记（拿到锁 / 放弃时撤掉）；polite=True（后台补跑）的一方看到别人的标记就先不抢、
        自己也不留标记——同步、夜跑、导入这些她在等结果的活优先。"""
        owner = owner or f"pid {os.getpid()}"
        st = self.state()
        deadline = time.monotonic() + max(0.0, float(wait_s or 0))
        mutex = st["mutex"]
        got = mutex.acquire(timeout=float(wait_s)) if wait_s and wait_s > 0 else mutex.acquire(blocking=False)
        if not got:
            raise LockBusy(self.name, {"pid": os.getpid(), "owner": st.get("owner") or "本进程的另一个任务",
                                       "started": st.get("started", "")})
        try:
            with _HELD_GUARD:
                nested = bool(st["count"])
                if nested:
                    st["count"] += 1
            if nested:
                try:
                    yield self
                finally:
                    with _HELD_GUARD:
                        st["count"] -= 1
                return
            yield from self._hold_file(st, owner, deadline, on_wait, polite)
        finally:
            mutex.release()

    def _hold_file(self, st: dict, owner: str, deadline: float, on_wait, polite: bool):
        """本线程第一次拿：抢锁文件 + 起心跳（已在 mutex 里，同进程别的线程进不来）。"""
        told = False
        want: Path | None = None
        try:
            while not ((not polite or not self.wanted_by_others()) and self.try_take(owner)):
                left = deadline - time.monotonic()
                if left <= 0:
                    raise LockBusy(self.name, self.holder())
                if want is None and not polite:
                    want = self._announce(owner)
                if not told and on_wait:
                    on_wait(self.holder() or {}, left)
                    told = True
                time.sleep(min(self.poll_s, max(0.05, left)))
        finally:
            if want is not None:
                try:
                    want.unlink()
                except OSError:
                    pass
        stop = threading.Event()
        thread = threading.Thread(target=self._heartbeat, args=(stop, owner, self.heartbeat_s), daemon=True,
                                  name=f"lock-heartbeat-{self.name}")
        with _HELD_GUARD:
            st.update(count=1, stop=stop, thread=thread, owner=owner, lost=False)
        thread.start()
        try:
            yield self
        finally:
            with _HELD_GUARD:
                st["count"] = 0
            self.release()


def file_lock(name: str, wait_s: float = 0, *, owner: str = "", path: Path | None = None, **kw):
    """`with storage.file_lock("catalog-build", wait_s=120): ...`——跨进程互斥（同一进程可重入）。

    锁文件默认 `locks_dir()/<name>.lock`；wait_s 内拿不到抛 LockBusy。kw 透传给 FileLock（stale_s 等）。"""
    lock = FileLock(path or (locks_dir() / f"{name}.lock"), name=name, **kw)
    return lock.hold(owner or name, wait_s)


def locked(name: str, wait_s: float = 0):
    """装饰器版：整个函数在锁里跑（catalog.build 用：只在函数外面加一行，不动函数体）。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            with file_lock(name, wait_s=wait_s, owner=f"{fn.__module__}.{fn.__name__}"):
                return fn(*a, **k)
        return wrapper
    return deco
