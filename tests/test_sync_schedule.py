"""定时同步的触发器读写（第 5 批 4.4）：读全部触发器、只认每日 / 每周那一个、只替换它、其余原样保留；
认不出的不冒充「每天」。全部用假的 PowerShell 输出，不碰本机真计划任务。"""

from __future__ import annotations

import json

import pytest

from link_brain import sync_schedule as ss


def ps_out(triggers, state="Ready"):
    return json.dumps({"state": state, "last_run": "2026-10-02T04:00:00", "last_result": 0,
                       "next_run": "2026-10-03T04:00:00", "triggers": triggers})


DAILY = {"cls": "MSFT_TaskDailyTrigger", "start": "2026-09-16T04:00:00+08:00", "enabled": True, "days": 0, "interval": 1}
ONCE = {"cls": "MSFT_TaskTimeTrigger", "start": "2026-10-02T00:00:00", "enabled": True, "days": 0, "interval": 1}
WEEKLY = {"cls": "MSFT_TaskWeeklyTrigger", "start": "2026-09-16T22:30:00", "enabled": True, "days": 2 | 16, "interval": 1}
LOGON = {"cls": "MSFT_TaskLogonTrigger", "start": "", "enabled": True, "days": 0, "interval": 1}


class FakePS:
    """替身：第一条命令（读）回 read_out，之后的（写）记下来回 ok。"""

    def __init__(self, read_out, write_ok=True, write_out="ok"):
        self.read_out, self.write_ok, self.write_out = read_out, write_ok, write_out
        self.cmds = []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        if "ConvertTo-Json" in cmd:
            return True, self.read_out
        return self.write_ok, self.write_out


@pytest.fixture
def fake(monkeypatch):
    def install(read_out, **kw):
        f = FakePS(read_out, **kw)
        monkeypatch.setattr(ss, "_ps", f)
        return f
    return install


def test_once_plus_daily_reads_the_daily_not_the_first(fake):
    # 原 bug：Triggers[0] 是一次性的 → 显示成「每天 00:00」
    fake(ps_out([ONCE, DAILY]))
    st = ss.get_schedule()
    assert st["freq"] == "daily" and st["time"] == "04:00" and st["managed_index"] == 1
    assert st["trigger_count"] == 2 and st["others"] == ["一次性 2026-10-02 00:00"]


def test_weekly_days_are_decoded_from_bitmask(fake):
    fake(ps_out([WEEKLY]))
    st = ss.get_schedule()
    assert st["freq"] == "weekly" and st["day"] == "Monday,Thursday" and st["time"] == "22:30"


def test_only_custom_triggers_is_unknown_not_daily(fake):
    fake(ps_out([ONCE, LOGON]))
    st = ss.get_schedule()
    assert st["freq"] == "unknown" and st["managed_index"] is None and st["time"] == ""
    assert st["others"] == ["一次性 2026-10-02 00:00", "登录时"]
    every2 = {**DAILY, "interval": 2}
    fake(ps_out([every2]))
    st = ss.get_schedule()
    assert st["freq"] == "unknown" and st["others"] == ["每 2 天 04:00"], "每 2 天界面表达不了，不冒充每天"


def test_single_trigger_not_wrapped_in_array_and_disabled_task(fake):
    fake(ps_out(DAILY, state="Disabled"))
    st = ss.get_schedule()
    assert st["freq"] == "daily" and st["enabled"] is False and st["trigger_count"] == 1


def test_enabled_daily_preferred_over_disabled_one(fake):
    fake(ps_out([{**DAILY, "enabled": False}, {**WEEKLY}]))
    st = ss.get_schedule()
    assert st["managed_index"] == 1 and st["freq"] == "weekly" and st["others"] == ["每天 04:00（已停用）"]


def test_missing_task_and_garbage_output(fake):
    fake("none")
    assert ss.get_schedule()["freq"] == "none"
    fake("Get-ScheduledTask : something odd")
    st = ss.get_schedule()
    assert st["freq"] == "none" and st["error"]


def test_save_replaces_only_the_managed_trigger(fake):
    f = fake(ps_out([ONCE, DAILY]))
    r = ss.set_schedule("daily", "05:30")
    assert r["ok"] is True
    write = f.cmds[-1]
    assert "$list[1]=$new;" in write and "$list.Count -ne 2" in write, "只换下标 1（每日那个），一次性保留"
    assert "-Daily -At '05:30'" in write and "-Trigger $list" in write
    assert "$list[0]" not in write and "Disable-ScheduledTask" not in write


def test_save_appends_when_no_managed_trigger(fake):
    f = fake(ps_out([ONCE, LOGON]))
    r = ss.set_schedule("weekly", "22:30", "Friday")
    assert r["ok"] is True
    write = f.cmds[-1]
    assert "$list+=$new;" in write and "-Weekly -DaysOfWeek Friday -At '22:30'" in write
    assert "$list.Count -ne 2" in write


def test_save_reports_concurrent_change(fake):
    fake(ps_out([DAILY]), write_ok=False, write_out="LWA_TRIGGERS_CHANGED At line:1 ...")
    r = ss.set_schedule("daily", "04:00")
    assert r["ok"] is False and "别处改过" in r["detail"]


def test_off_disables_the_whole_task_only(fake):
    f = fake(ps_out([ONCE, DAILY]))
    r = ss.set_schedule("off")
    assert r["ok"] is True and len(f.cmds) == 1 and f.cmds[0].startswith("Disable-ScheduledTask")


def test_bad_time_is_rejected_not_passed_to_powershell(fake):
    f = fake(ps_out([DAILY]))
    for bad in ("4点", "25:00", "04:00'; Remove-Item x", "13:00PM"):
        r = ss.set_schedule("daily", bad)
        assert r["ok"] is False and "时间格式不对" in r["error"], bad
    assert f.cmds == []
    assert ss._norm_time("") == ss.AT and ss._norm_time("4:00AM") == "4:00AM" and ss._norm_time("16:30") == "16:30"


def test_save_without_task_says_not_found(fake):
    f = fake("none")
    r = ss.set_schedule("daily", "04:00")
    assert r["ok"] is False and "找不到" in r["error"] and len(f.cmds) == 1


def test_triggers_are_written_in_local_time_not_utc():
    """10-03：New-ScheduledTaskTrigger 记 UTC（…Z），夏令时一到 04:00 就漂成 05:00；写回前改成本地钟点。"""
    from link_brain import sync_schedule
    ps = sync_schedule.build_set_ps("New-ScheduledTaskTrigger -Daily -At '04:00'", 0, 1)
    assert sync_schedule.LOCAL_FIX in ps and ps.index("$new=") < ps.index(sync_schedule.LOCAL_FIX)


def test_nightly_install_registers_local_time_trigger():
    from link_brain import sync_schedule
    ps = sync_schedule.nightly_install_script("python.exe", ["-m", "link_brain", "nightly"], ".", 4, 0, 7)
    assert "$t.StartBoundary=([datetime]$t.StartBoundary).ToString('s');" in ps
    assert ps.index("$t=New-ScheduledTaskTrigger") < ps.index("$t.StartBoundary=") < ps.index("Register-ScheduledTask")
