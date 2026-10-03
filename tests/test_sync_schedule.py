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
    # 10-03：改走规则——去掉我们那个（下标 1，没打标的旧每日触发器），一次性原样留着，新的打标 LWA-1 追加
    assert "if(@(1) -notcontains $i){$keep+=$list[$i]}" in write and "$list.Count -ne 2" in write, "只换下标 1（每日那个），一次性保留"
    assert "-Daily -At ([datetime]::Today.AddHours(5).AddMinutes(30))" in write and "-Trigger $keep" in write
    assert "$new.Id='LWA-1';" in write and "Disable-ScheduledTask" not in write


def test_save_appends_when_no_managed_trigger(fake):
    f = fake(ps_out([ONCE, LOGON]))
    r = ss.set_schedule("weekly", "22:30", "Friday")
    assert r["ok"] is True
    write = f.cmds[-1]
    assert "@(-1) -notcontains $i" in write and "$keep+=$new;" in write
    assert "-Weekly -DaysOfWeek Friday -At ([datetime]::Today.AddHours(22).AddMinutes(30))" in write
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


# ---------------------------------------------------------------- 10-03：灵活定时（规则）

from datetime import datetime as _dt

T_HOURLY = {"cls": "MSFT_TaskDailyTrigger", "start": "2026-10-03T00:00:00", "enabled": True, "days": 0, "interval": 1,
            "id": "LWA-1", "rep": "PT4H"}
T_MON = {"cls": "MSFT_TaskWeeklyTrigger", "start": "2026-10-03T08:00:00", "enabled": True, "days": 2, "interval": 1,
         "id": "LWA-2", "rep": ""}
T_D4 = {"cls": "MSFT_TaskDailyTrigger", "start": "2026-10-03T04:00:00", "enabled": True, "days": 0, "interval": 1,
        "id": "LWA-3", "rep": ""}
T_D16 = {**T_D4, "start": "2026-10-03T16:00:00", "id": "LWA-4"}
T_ONCE = {"cls": "MSFT_TaskTimeTrigger", "start": "2026-10-09T17:00:00", "enabled": True, "days": 0, "interval": 1,
          "id": "LWA-5", "rep": ""}


def test_tagged_triggers_read_back_as_rules_and_one_line(fake):
    fake(json.dumps({"state": "Ready", "next_run": "2026-10-06T08:00:00",
                     "triggers": [LOGON, T_HOURLY, T_MON, T_D16, T_D4, T_ONCE]}))
    st = ss.get_schedule()
    assert st["mine"] == [1, 2, 3, 4, 5] and st["others"] == ["登录时"], "只认打了 LWA 标的；登录时那个不是我们的"
    assert st["freq"] == "custom"
    assert st["rules"] == [{"kind": "daily", "times": ["04:00", "16:00"]},
                           {"kind": "weekly", "days": ["Monday"], "times": ["08:00"]},
                           {"kind": "hourly", "hours": 4, "from": "00:00"},
                           {"kind": "once", "at": "2026-10-09 17:00"}]
    assert st["summary"] == "每天 04:00、16:00 · 每周一 08:00 · 每 4 小时一次 · 10/09 17:00 一次 · 下次 10/06 08:00"


def test_untagged_legacy_trigger_still_counts_as_ours(fake):
    fake(ps_out([ONCE, DAILY]))
    st = ss.get_schedule()
    assert st["mine"] == [1] and st["rules"] == [{"kind": "daily", "times": ["04:00"]}] and st["freq"] == "daily"
    assert st["summary"].startswith("每天 04:00")
    fake(ps_out([DAILY], state="Disabled"))
    assert ss.get_schedule()["summary"] == "已关闭"


def test_normalize_rules_validates_everything():
    now = _dt(2026, 10, 3, 12, 0)
    ok, err = ss.normalize_rules([{"kind": "daily", "times": ["16:00", "4:00", "04:00"]},
                                  {"kind": "weekly", "days": ["Thursday", "Monday", "Funday"], "times": ["8:00"]},
                                  {"kind": "once", "at": "2026-10-3T17:00"}, {"kind": "hourly", "hours": "6"}], now=now)
    assert err == ""
    assert ok == [{"kind": "daily", "times": ["04:00", "16:00"]}, {"kind": "weekly", "times": ["08:00"], "days": ["Monday", "Thursday"]},
                  {"kind": "once", "at": "2026-10-03 17:00"}, {"kind": "hourly", "hours": 6, "from": "00:00"}]
    for bad, why in [([], "至少要有一条"), ([{"kind": "hourly", "hours": 7}], "1–6"), ([{"kind": "hourly", "hours": 0}], "1–6"),
                     ([{"kind": "once", "at": "2026-10-03 11:00"}], "已经过了"), ([{"kind": "once", "at": "明天"}], "时间不对"),
                     ([{"kind": "daily", "times": ["25:00"]}], "时间格式不对"), ([{"kind": "daily", "times": ["04:00'; rm x"]}], "时间格式不对"),
                     ([{"kind": "weekly", "days": [], "times": ["08:00"]}], "至少选一天"), ([{"kind": "monthly"}], "不认识"),
                     ([{"kind": "daily", "times": [f"{h:02d}:00" for h in range(17)]}], "太多")]:
        assert why in ss.normalize_rules(bad, now=now)[1], bad


def test_rules_script_keeps_others_tags_ours_and_uses_local_clock():
    rules, _ = ss.normalize_rules([{"kind": "weekly", "days": ["Monday", "Friday"], "times": ["08:00"]},
                                   {"kind": "daily", "times": ["04:00", "16:00"]}, {"kind": "hourly", "hours": 4, "from": "06:30"},
                                   {"kind": "once", "at": "2026-10-09 17:00"}], now=_dt(2026, 10, 3))
    ps = ss.build_rules_ps(rules, [1, 3], ["MSFT_TaskDailyTrigger", "MSFT_TaskWeeklyTrigger"], 4)
    assert "if($list.Count -ne 4){throw 'LWA_TRIGGERS_CHANGED'}" in ps
    assert "[string]$list[1].CimClass.CimClassName -notlike '*DailyTrigger'" in ps
    assert "[string]$list[3].CimClass.CimClassName -notlike '*WeeklyTrigger'" in ps
    assert "if(@(1,3) -notcontains $i){$keep+=$list[$i]}" in ps, "别的触发器原样留着"
    assert "-Weekly -DaysOfWeek Monday,Friday -At ([datetime]::Today.AddHours(8).AddMinutes(0))" in ps
    assert ps.count("New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(") == 3, "每天两次 = 两个触发器 + 每 N 小时那个"
    assert "-RepetitionInterval (New-TimeSpan -Hours 4) -RepetitionDuration (New-TimeSpan -Days 1)" in ps
    assert "AddHours(6).AddMinutes(30)" in ps
    assert "-Once -At ([datetime]::new(2026,10,9,17,0,0))" in ps
    assert [f"$new.Id='LWA-{n}';" in ps for n in range(1, 6)] == [True] * 5 and "LWA-6" not in ps
    assert ps.count(ss.LOCAL_FIX) == 5, "每个新触发器都改成本机钟点（夏令时不漂）"
    assert ps.index("$new.Id='LWA-1';") < ps.index(ss.LOCAL_FIX) < ps.index("$keep+=$new;")
    assert ps.endswith("Enable-ScheduledTask -TaskName 'XhsFavSync' -ErrorAction Stop | Out-Null;'ok'")


def test_set_rules_reads_then_writes_once(fake):
    f = fake(json.dumps({"state": "Ready", "triggers": [LOGON, T_HOURLY]}))
    r = ss.set_rules([{"kind": "weekly", "days": ["Monday"], "times": ["08:00"]}, {"kind": "hourly", "hours": 3}])
    assert r["ok"] is True and r["detail"] == "已保存：每周一 08:00 · 每 3 小时一次"
    assert len(f.cmds) == 2 and "@(1) -notcontains $i" in f.cmds[1] and "-Hours 3" in f.cmds[1]
    f = fake(json.dumps({"state": "Ready", "triggers": [T_HOURLY]}))
    r = ss.set_rules([{"kind": "hourly", "hours": 9}])
    assert r["ok"] is False and "1–6" in r["error"] and len(f.cmds) == 0, "格式不对不读不写"
    fake("none")
    assert "找不到" in ss.set_rules([{"kind": "daily", "times": ["04:00"]}])["error"]


def test_cli_rules(fake, capsys):
    from link_brain import cli
    fake(json.dumps({"state": "Ready", "triggers": [T_D4]}))
    rc = cli.main(["sync-schedule", "--rules", json.dumps([{"kind": "daily", "times": ["05:00", "17:00"]}])])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and out["ok"] and out["rules"] == [{"kind": "daily", "times": ["05:00", "17:00"]}]
    rc = cli.main(["sync-schedule", "--rules", "不是 JSON"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 1 and "不是 JSON" in out["error"]
