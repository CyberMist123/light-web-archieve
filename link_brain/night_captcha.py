"""夜里撞验证：先不叫人，冷却后自查一次，没事就接着跑（1011，作者定「夜里正常跑就行」）。

事实（作者本机 10-06 / 10-08 / 10-10 / 10-11 夜跑）：读收藏一开页就弹滑块，但这个验证一阵子就消——10-10 04:02 撞上，
04:11 打开验证窗口已经什么都没有了。以前一撞就全晚停车、凌晨 4 点推给她、只有她能解，等于纯噪音。

现在，**只在没人看着的时候**（夜跑脚本 / 包内 nightly / 后台补评论设了 `LINK_BRAIN_UNATTENDED`）：
1. 撞到验证码（`CAPTCHA_REQUIRED`，或熔断起因是验证码的 `RISK_HOLD`）不当场推送：问题记录登记成
   `TRANSIENT.NIGHT_CAPTCHA`（只在列表里，「夜里弹了验证（不是掉登录），冷却后自己再看一眼」）；熔断照写、照拦。
2. 冷却 45 分钟（`LWA_CAPTCHA_COOLDOWN_MIN` / `--cooldown-min`）。冷却期间什么页都不开（夜跑只跑离线步骤）。
3. 冷却到点自查一次：经读取服务 `POST /api/v1/risk/probe`（只开一页本号主页，不点页签、不滚动；只认验证码类；
   服务端自己也守冷却下限、同一次熔断一晚一次）。拿着账号锁去查，别的任务不会同时开页。
   - 干净 → 读取服务解除熔断；这边把这件事标已解决（原因「冷却后自查无验证，自动恢复」，留痕不显示），
     夜跑接着跑剩下的步骤（不重读收藏列表）。
   - 还在 / 读不到 → 今晚就停（不推送）；**连着两晚**都这样才推一次 `NEEDS_HUMAN.CAPTCHA_REQUIRED`
     （「小红书弹了验证（不是掉登录）」）。
   - 是游客 → 掉登录，照旧当场推（不归这里管）。
4. 一晚只自查一次（这边按「夜跑日」记，读取服务按熔断记）：同一晚第二次撞验证，安静停到明晚。

掉登录、安全跳转（ACCOUNT_RISK）、登错号这些一律照旧：当场停、当场推、要人处理。
（1019 起白天撞的验证也走这套：先冷却自查，连着两晚自查都还在才叫她。）人工的 `risk/clear`（`login --clear-hold --by-owner`）语义不变；
这里自动解除走的是另一条有审计的路（读取服务 /risk/probe 自己判、自己解，原因写进熔断日志和问题记录）。

状态：`~/.link-brain/night-captcha.json`（`LINK_BRAIN_HOME` 可改）= {"nights": {"YYYY-MM-DD": {...}}}，只留最近 14 晚。
"夜跑日" = 当地时间往前推 3 小时的日期（03:00 换日：04:00 的夜跑和它白天续上的后台补评论算同一晚）。
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from . import storage
from .errtext import errtext

ENV_UNATTENDED = "LINK_BRAIN_UNATTENDED"
ENV_COOLDOWN = "LWA_CAPTCHA_COOLDOWN_MIN"
COOLDOWN_MIN_DEFAULT = 45.0
COOLDOWN_MIN_FLOOR = 30.0          # 和读取服务的下限一致：再小也按 30 分钟
STATE_NAME = "night-captcha.json"
NIGHTS_KEPT = 14
DAY_SHIFT_HOURS = 3
ESCALATE_NIGHTS = 2
STEP = "login"
CODE_DEFERRED = "TRANSIENT.NIGHT_CAPTCHA"
CODE_HUMAN = "NEEDS_HUMAN.CAPTCHA_REQUIRED"
CAPTCHA = "CAPTCHA_REQUIRED"
AUTO_CLEAR_REASON = "冷却后自查无验证，自动恢复"
SAY = "小红书弹了验证（不是掉登录）"
PROBE_TIMEOUT_S = 240              # 读取服务等锁 ≤60 秒 + 开页自查 ≤2 分钟，再留余量

# 结论 → (退出码, 一句话)。0 = 自查干净、已恢复（夜跑接着跑碰号步骤）；5 = 今晚就停；6 = 号被占着 / 浏览器被占着（没查）；1 = 出错
EXIT_OK, EXIT_ERROR, EXIT_STOP, EXIT_BUSY = 0, 1, 5, 6


def _now() -> datetime:
    return datetime.now().astimezone()


def unattended() -> bool:
    """这一趟有没有人看着：夜跑脚本 / 包内 nightly / 后台补评论会设 LINK_BRAIN_UNATTENDED。"""
    return bool(str(os.environ.get(ENV_UNATTENDED) or "").strip())


def set_unattended(tag: str) -> None:
    """进程内标记「没人看着」（子进程跟着继承）。"""
    os.environ[ENV_UNATTENDED] = tag or "1"


def cooldown_min(value: float | None = None) -> float:
    if value is None:
        try:
            value = float(os.environ.get(ENV_COOLDOWN) or COOLDOWN_MIN_DEFAULT)
        except ValueError:
            value = COOLDOWN_MIN_DEFAULT
    return max(COOLDOWN_MIN_FLOOR, float(value))


def night_key(now: datetime | None = None) -> str:
    return ((now or _now()) - timedelta(hours=DAY_SHIFT_HOURS)).date().isoformat()


# ---------------------------------------------------------------- 状态文件

def state_path():
    return storage.link_brain_home() / STATE_NAME


def load_state() -> dict[str, Any]:
    try:
        data = storage.read_json(state_path())
    except (OSError, ValueError):
        return {"nights": {}}
    if not isinstance(data, dict) or not isinstance(data.get("nights"), dict):
        return {"nights": {}}
    return data


def _update_night(key: str, **fields: Any) -> dict[str, Any]:
    """改一晚的记录（锁里读改写，只留最近 NIGHTS_KEPT 晚）。写不进去不抛（fail-open：最多少一次去重）。"""
    try:
        with storage.file_lock("night-captcha", wait_s=10, owner="night-captcha"):
            data = load_state()
            night = dict(data["nights"].get(key) or {})
            for k, v in fields.items():
                if k == "incidents_add":
                    night["incidents"] = int(night.get("incidents") or 0) + int(v)
                else:
                    night[k] = v
            data["nights"][key] = night
            keep = sorted(data["nights"])[-NIGHTS_KEPT:]
            data["nights"] = {k: data["nights"][k] for k in keep}
            storage.write_json(state_path(), data)
            return night
    except Exception as exc:  # noqa: BLE001
        print(f"[验证自查] 状态没写上（{errtext(exc)}）", file=sys.stderr)
        return dict(fields)


def _claim_probe(key: str, now: datetime) -> str | None:
    """自查之前先在锁里写下「今晚正在查」（probing_at）。返回 None = 写上了，可以查；
    "already" = 今晚已经查过 / 别人正在查；其他字符串 = 状态读不出来或写不进去的原因——这时不查（宁可今晚不查，不能一晚查两次）。"""
    try:
        with storage.file_lock("night-captcha", wait_s=10, owner="night-captcha"):
            p = state_path()
            data = storage.read_json(p) if p.exists() else {"nights": {}}
            if not isinstance(data, dict) or not isinstance(data.get("nights"), dict):
                return "状态文件格式不对"
            one = dict(data["nights"].get(key) or {})
            if one.get("probe_at") or one.get("probing_at"):
                return "already"
            one["probing_at"] = now.isoformat(timespec="seconds")
            data["nights"][key] = one
            keep = sorted(data["nights"])[-NIGHTS_KEPT:]
            data["nights"] = {k: data["nights"][k] for k in keep}
            storage.write_json(p, data)
            return None
    except Exception as exc:  # noqa: BLE001
        return errtext(exc)


def _unclaim(key: str) -> None:
    """这次其实没查成（号被占 / 读取服务说没查）：撤掉「正在查」，今晚还能再试。撤不掉 = 今晚不再查（安全的一边）。"""
    _update_night(key, probing_at=None)


def night(key: str | None = None) -> dict[str, Any]:
    return dict(load_state()["nights"].get(key or night_key()) or {})


# ---------------------------------------------------------------- 撞上时：要不要先不叫她

def _hold_code() -> str:
    try:
        from . import accounts
        return str((accounts._hold_file() or {}).get("code") or "")
    except Exception:  # noqa: BLE001
        return ""


def defer(code: str | None) -> bool:
    """这次撞的事要不要先不叫她：验证码（或熔断起因是验证码的 RISK_HOLD）。
    1019 她：非她本人不可的才叫她——白天撞的验证也一样先冷却自查（以前只在没人看着时；10-19 21:15 白天推了，22:00 自查无验证）。"""
    sub = str(code or "").rsplit(".", 1)[-1]
    if sub == CAPTCHA:
        return True
    return sub == "RISK_HOLD" and _hold_code() == CAPTCHA


def report_deferred(reason: str) -> dict[str, Any] | None:
    """撞上验证、先不叫她：登记一条 TRANSIENT（只在问题列表里），这一晚记一次出事。永不抛。"""
    from . import problems
    key = night_key()
    now = _now().isoformat(timespec="seconds")
    n = _update_night(key, incidents_add=1, last_at=now)
    if not n.get("first_at"):
        n = _update_night(key, first_at=now)
    probed = bool(n.get("probe_at"))
    tail = ("今晚已经自查过一次，先停到明晚（连着两晚都这样才叫你）" if probed else
            f"冷却 {cooldown_min():.0f} 分钟后自己再看一眼，没事就接着跑")
    text = f"{SAY}：{reason}"[:200] + f"。{tail}"
    try:
        return problems.report(STEP, "TRANSIENT.NIGHT_CAPTCHA", text)
    except Exception as exc:  # noqa: BLE001
        print(f"[验证自查] 问题记录没写上（{errtext(exc)}）", file=sys.stderr)
        return None


# ---------------------------------------------------------------- 冷却后自查

def _since(hold: dict[str, Any] | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str((hold or {}).get("since"))).astimezone()
    except (TypeError, ValueError):
        return None


def _out(result: str, exit_code: int, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": exit_code == EXIT_OK, "code": "" if exit_code == EXIT_OK else result, "message": message,
            "result": result, "exit": exit_code, **extra}


def _mark_unrecovered(key: str, why: str, *, now: datetime) -> dict[str, Any]:
    """今晚没恢复：记下；昨晚也没恢复 → 推一次 NEEDS_HUMAN（她要知道了）。返回 {escalated}。"""
    from . import problems
    _update_night(key, result="unrecovered", why=why[:160])
    prev_key = (datetime.fromisoformat(key) - timedelta(days=1)).date().isoformat()
    prev = load_state()["nights"].get(prev_key) or {}
    tonight = load_state()["nights"].get(key) or {}
    if tonight.get("escalated"):
        return {"escalated": False}  # 今晚已经叫过她了：不再登记
    if prev.get("result") != "unrecovered":
        problems.report(STEP, "TRANSIENT.NIGHT_CAPTCHA",
                        f"{SAY}：{why}。今晚先停（不叫你）；明晚冷却后再看一眼，连着两晚都这样才叫你")
        return {"escalated": False}
    _update_night(key, escalated=now.isoformat(timespec="seconds"))
    problems.resolve(STEP, None, CODE_DEFERRED)
    problems.report(STEP, "NEEDS_HUMAN.CAPTCHA_REQUIRED",
                    f"{SAY}：连着 {ESCALATE_NIGHTS} 晚冷却后自查验证都还在（{why}）。点「打开验证」，窗口打开后点一下"
                    "「收藏」页签；出现滑块就拖完再关窗，没出现就直接关窗")
    return {"escalated": True}


def _mark_recovered(key: str, hold: dict[str, Any] | None, *, now: datetime, waited_min: float) -> None:
    from . import problems, sync_state
    _update_night(key, result="recovered", recovered_at=now.isoformat(timespec="seconds"))
    since = _since(hold)
    when = f"{since:%H:%M} 弹的验证，" if since else ""
    # 留痕：同一把 key 记一行「自动恢复」再标已解决（列表里不显示已解决的；复制报错 / 问题记录里查得到）
    problems.report(STEP, "TRANSIENT.NIGHT_CAPTCHA", f"{AUTO_CLEAR_REASON}（{when}冷却 {waited_min:.0f} 分钟后打开本号主页没看到验证）")
    for code in (CODE_DEFERRED, "CAPTCHA_REQUIRED", "RISK_HOLD"):
        problems.resolve(STEP, None, code)
    try:
        sync_state.account_ok()
    except Exception:  # noqa: BLE001
        pass


def recover(*, cooldown: float | None = None, wait: bool = False, max_wait_min: float | None = None,
            sleep: Callable[[float], None] = time.sleep, now_fn: Callable[[], datetime] = _now,
            lock_wait_s: float = 300) -> dict[str, Any]:
    """冷却后自查一次（见模块说明）。返回 §1 形状 + result / exit。永不抛（读取服务不在 → result=error）。

    wait=True：冷却还没到就在这里等（每分钟醒一次；最多 max_wait_min 分钟，不给就等到冷却结束）；等的时候不开任何页。"""
    from . import accounts
    cool = cooldown_min(cooldown)
    key = night_key(now_fn())
    try:
        hold = accounts.risk_hold()
    except Exception as exc:  # noqa: BLE001
        return _out("error", EXIT_ERROR, f"读不到熔断状态：{exc}")
    if not hold:
        return _out("no_hold", EXIT_STOP, "现在没有风控暂停，不用自查（今晚停下的碰号步骤不自动补跑）")
    code = str(hold.get("code") or "")
    if accounts.is_rate_limited(hold):
        return _rate_limit_wait(hold, wait=wait, max_wait_min=max_wait_min, sleep=sleep, now_fn=now_fn)
    if code != CAPTCHA:
        return _out("not_captcha", EXIT_STOP, f"暂停的起因是 {code}，不是验证码：照旧等人处理", hold_code=code)
    if night(key).get("probe_at") or night(key).get("probing_at"):
        out = _mark_unrecovered(key, "同一晚又撞了一次验证（今晚已经自查过）", now=now_fn())
        return _out("already_tried", EXIT_STOP, "今晚已经自查过一次了，先停到明晚", **out)

    since = _since(hold) or now_fn()
    ready_at = since + timedelta(minutes=cool)
    left = (ready_at - now_fn()).total_seconds()
    if left > 0:
        cap = None if max_wait_min is None else max_wait_min * 60
        if not wait or (cap is not None and left > cap):
            return _out("cooling", EXIT_STOP, f"还在冷却：{ready_at:%H:%M} 之后才自查", retry_after_s=int(left) + 1,
                        ready_at=ready_at.isoformat(timespec="seconds"))
        print(f"[验证自查] {since:%H:%M} 弹的验证，冷却到 {ready_at:%H:%M} 再看一眼（这期间不开任何页）", file=sys.stderr)
        while left > 0:
            sleep(min(60.0, left))
            left = (ready_at - now_fn()).total_seconds()
        try:
            hold = accounts.risk_hold()
        except Exception as exc:  # noqa: BLE001
            return _out("error", EXIT_ERROR, f"读不到熔断状态：{exc}")
        if not hold or str(hold.get("code") or "") != CAPTCHA:
            return _out("no_hold" if not hold else "not_captcha", EXIT_STOP, "冷却期间暂停已经被处理了，不用自查")

    waited = (now_fn() - since).total_seconds() / 60
    claim = _claim_probe(key, now_fn())
    if claim == "already":
        return _out("already_tried", EXIT_STOP, "今晚已经自查过 / 正在自查，先停到明晚")
    if claim:
        return _out("error", EXIT_ERROR, f"「今晚正在自查」的记号写不进去，这次不自查（免得一晚查两次）：{claim}")
    try:
        with accounts.account_session("captcha-recover", wait_s=lock_wait_s):
            data = accounts.api("POST", "/api/v1/risk/probe", timeout=PROBE_TIMEOUT_S,
                                body={"cooldown_s": int(cool * 60), "reason": "night-captcha recover"})
    except accounts.AccountBusyError as exc:
        _unclaim(key)
        return _out("busy", EXIT_BUSY, f"号正被别的任务占着，这次没自查：{exc}")
    except accounts.ReaderError as exc:
        if str(exc.code).startswith("HTTP_404"):
            out = _mark_unrecovered(key, "读取组件版本太旧，不会冷却后自查", now=now_fn())
            _update_night(key, probe_at=now_fn().isoformat(timespec="seconds"))
            return _out("unsupported", EXIT_STOP, "读取组件还没有「冷却后自查」：今晚先停", **out)
        return _out("error", EXIT_ERROR, f"自查没发出去（{exc.code}）：{exc}")
    result = str((data or {}).get("result") or "")
    now = now_fn()
    if result in ("busy", "window_failed"):
        _unclaim(key)
        return _out("busy", EXIT_BUSY, "读取服务的浏览器正被别的操作占着，这次没自查")
    if result == "cooling":
        _unclaim(key)
        return _out("cooling", EXIT_STOP, "读取服务说还在冷却，先不查", retry_after_s=(data or {}).get("retry_after_s"))
    if result in ("no_hold", "not_captcha"):
        _unclaim(key)
        return _out(result, EXIT_STOP, "暂停已经不在 / 不是验证码类，不用自查")
    _update_night(key, probe_at=now.isoformat(timespec="seconds"), probe_result=result)
    if result == "cleared":
        _mark_recovered(key, hold, now=now, waited_min=waited)
        print(f"[验证自查] {AUTO_CLEAR_REASON}", file=sys.stderr)
        return _out("cleared", EXIT_OK, f"{AUTO_CLEAR_REASON}：接着跑", waited_min=round(waited, 1))
    if result == "not_logged_in":
        from . import problems
        _update_night(key, result="not_logged_in")
        problems.report_blocked(STEP, "NOT_LOGGED_IN", "冷却后自查：读取号成了游客（掉登录），要扫码登录")
        return _out("not_logged_in", EXIT_STOP, "自查发现掉登录了：要扫码登录（已提醒）")
    why = {"still_risk": "冷却后自查验证还在", "already_probed": "读取服务说今晚已经查过",
           "not_read": "冷却后自查没读到页面"}.get(result, f"冷却后自查没过（{result or '没回结论'}）")
    out = _mark_unrecovered(key, why, now=now)
    return _out(result or "unknown", EXIT_STOP, f"{why}：今晚先停" + ("，已提醒（连着两晚了）" if out.get("escalated") else "（不叫你）"),
                **out)


def _rate_limit_wait(hold: dict[str, Any], *, wait: bool, max_wait_min: float | None,
                     sleep: Callable[[float], None], now_fn: Callable[[], datetime]) -> dict[str, Any]:
    """1015：限频冷却（XHS_RATE_LIMITED）不用 /risk/probe——读取组件到点自己放行请求当自探、成功自动清。
    这里只等：冷却没到 → cooling（retry_after_s / ready_at）；wait=True 且能等到 → 等到点后回 cleared（退出 0，
    夜跑接着跑停下的碰号步骤，第一个请求就是自探）。不登记、不推送。"""
    from . import accounts
    until = accounts.rate_limit_until(hold)
    left = (until - now_fn()).total_seconds() if until else 0.0
    if left > 0:
        cap = None if max_wait_min is None else max_wait_min * 60
        if not wait or (cap is not None and left > cap):
            return _out("cooling", EXIT_STOP, accounts.rate_limit_text(hold), retry_after_s=int(left) + 1,
                        ready_at=until.isoformat(timespec="seconds"), hold_code=accounts.RATE_LIMIT_CODE)
        print(f"[限频冷却] 小红书说访问太频繁，等到 {until:%H:%M} 再接着跑（这期间不开任何页）", file=sys.stderr)
        while left > 0:
            sleep(min(60.0, left))
            left = (until - now_fn()).total_seconds()
    return _out("cleared", EXIT_OK, "限频冷却到点：接着跑（下一个用号请求就是自探，成功读取组件自动恢复）",
                hold_code=accounts.RATE_LIMIT_CODE)


# ---------------------------------------------------------------- CLI

def add_parser(sub) -> None:
    p = sub.add_parser("captcha-recover",
                       help="夜里撞验证后冷却自查一次（只认验证码类；干净就自动恢复，退出 0；今晚就停退出 5；号被占退出 6）")
    p.add_argument("--cooldown-min", dest="cooldown_min", type=float, default=None,
                   help=f"冷却几分钟（默认 {COOLDOWN_MIN_DEFAULT:g}，环境变量 {ENV_COOLDOWN}；最少 {COOLDOWN_MIN_FLOOR:g}）")
    p.add_argument("--wait", action="store_true", help="冷却没到就在这里等（不开任何页）")
    p.add_argument("--max-wait-min", dest="max_wait_min", type=float, default=None,
                   help="--wait 最多等几分钟（超过就不等、退出 5）")


def run(args) -> int:
    import contextlib
    from .read import dump_json
    with contextlib.redirect_stdout(sys.stderr):
        out = recover(cooldown=getattr(args, "cooldown_min", None), wait=bool(getattr(args, "wait", False)),
                      max_wait_min=getattr(args, "max_wait_min", None))
    print(f"captcha-recover: {out['message']}", file=sys.stderr)
    dump_json(out)
    return int(out["exit"])
