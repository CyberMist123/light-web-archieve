"""r5 补测：定时同步的计划任务半边（纯函数喂假 PowerShell 输出；绝不起 powershell 进程）。"""
from __future__ import annotations

import json
from datetime import datetime

from link_brain import sync_schedule as ss


def test_norm_time_accepts_house_styles():
    assert ss._norm_time("") == ss.AT and ss._norm_time(None) == ss.AT   # 空 = 默认凌晨 4 点
    assert ss._norm_time("4:00AM") == "4:00AM" and ss._norm_time("04:00") == "04:00"
    assert ss._norm_time("16:30") == "16:30" and ss._norm_time("9:05 pm") == "9:05 pm"
    assert ss._norm_time("13:00AM") is None      # AM/PM 只配 1–12 点
    assert ss._norm_time("24:00") is None and ss._norm_time("abc") is None


def test_kind_hm_days_decoding():
    assert ss._kind("MSFT_TaskDailyTrigger") == "Daily" and ss._kind("MSFT_TaskWeeklyTrigger") == "Weekly"
    assert ss._hm("2026-10-03T17:05:00") == "17:05" and ss._hm("") == ""
    assert ss._days(2 | 4) == ["Monday", "Tuesday"]        # 位掩码按周内顺序解
    assert ss._days(1) == ["Sunday"] and ss._days("垃圾") == []
    assert ss._rep_hours("PT4H") == 4 and ss._rep_hours("pt2h") == 2
    assert ss._rep_hours("P1D") is None and ss._rep_hours("") is None


def test_describe_trigger_phrases():
    assert ss.describe_trigger({"cls": "MSFT_TaskDailyTrigger", "start": "T04:00", "interval": 1}) == "每天 04:00"
    assert ss.describe_trigger({"cls": "MSFT_TaskDailyTrigger", "start": "T04:00", "interval": 2}) == "每 2 天 04:00"
    assert ss.describe_trigger({"cls": "MSFT_TaskWeeklyTrigger", "start": "T08:00", "interval": 1,
                                 "days": 2 | 16}) == "每周 周一、周四 08:00"
    assert ss.describe_trigger({"cls": "MSFT_TaskTimeTrigger", "start": "2026-10-03T17:00"}) == "一次性 2026-10-03 17:00"
    assert ss.describe_trigger({"cls": "MSFT_TaskLogonTrigger"}) == "登录时"
    assert ss.describe_trigger({"cls": "MSFT_TaskLogonTrigger", "enabled": False}) == "登录时（已停用）"


def _ps_out(trs, state="Running", **kw):
    return json.dumps({"state": state, "last_run": kw.get("last_run", ""), "last_result": kw.get("last_result", 0),
                       "next_run": kw.get("next_run", ""), "triggers": trs}, ensure_ascii=False)


def test_parse_state_none_and_garbage():
    assert ss.parse_state("none") == {"task": ss.TASK, "freq": "none", "enabled": False}
    bad = ss.parse_state("读不懂的输出")
    assert bad["freq"] == "none" and bad["enabled"] is False and "读不懂" in bad["error"]


def test_parse_state_picks_tagged_and_describes_others():
    out = ss.parse_state(_ps_out([
        {"cls": "MSFT_TaskDailyTrigger", "start": "T04:00", "enabled": True, "id": "LWA-1", "interval": 1},
        {"cls": "MSFT_TaskLogonTrigger", "enabled": True, "id": ""},
    ]))
    assert out["freq"] == "daily" and out["time"] == "04:00" and out["mine"] == [0]
    assert out["trigger_count"] == 2 and out["others"] == ["登录时"]   # 别人的触发器只描述、不冒充
    assert "每天 04:00" in out["summary"]
    # 只有别人的触发器：不冒充每天
    unknown = ss.parse_state(_ps_out([{"cls": "MSFT_TaskLogonTrigger", "enabled": True, "id": ""}]))
    assert unknown["freq"] == "unknown" and "自定义触发器（登录时），未改动" == unknown["summary"]
    # 旧数据没打标：第一个启用的每日 / 每周间隔 1 也认
    legacy = ss.parse_state(_ps_out([{"cls": "MSFT_TaskWeeklyTrigger", "start": "T08:00", "enabled": True,
                                      "id": "", "interval": 1, "days": 2}]))
    assert legacy["freq"] == "weekly" and legacy["day"] == "Monday"


def test_parse_state_custom_freq_for_multi_times():
    out = ss.parse_state(_ps_out([
        {"cls": "MSFT_TaskDailyTrigger", "start": "T16:00", "enabled": True, "id": "LWA-2", "interval": 1},
        {"cls": "MSFT_TaskDailyTrigger", "start": "T04:00", "enabled": True, "id": "LWA-1", "interval": 1},
    ]))
    assert out["freq"] == "custom"                       # 一天多次：旧的下拉表达不了
    assert out["rules"] == [{"kind": "daily", "times": ["04:00", "16:00"]}]   # 并成一条、时刻排序
    assert "每天 04:00、16:00" in out["summary"]
    hourly = ss.parse_state(_ps_out([{"cls": "MSFT_TaskDailyTrigger", "start": "T00:00", "enabled": True,
                                      "id": "LWA-1", "rep": "PT4H", "interval": 1}]))
    assert hourly["freq"] == "custom" and hourly["rules"] == [{"kind": "hourly", "hours": 4, "from": "00:00"}]


def test_rules_from_triggers_merge_and_sort():
    trs = [
        {"cls": "MSFT_TaskDailyTrigger", "start": "T16:00", "interval": 1},
        {"cls": "MSFT_TaskDailyTrigger", "start": "T04:00", "interval": 1},
        {"cls": "MSFT_TaskWeeklyTrigger", "start": "T08:00", "interval": 1, "days": 2},
        {"cls": "MSFT_TaskWeeklyTrigger", "start": "T09:00", "interval": 1, "days": 2},
        {"cls": "MSFT_TaskWeeklyTrigger", "start": "T07:00", "interval": 1, "days": 64},
        {"cls": "MSFT_TaskDailyTrigger", "start": "T00:00", "rep": "PT4H", "interval": 1},
        {"cls": "MSFT_TaskTimeTrigger", "start": "2026-12-02T09:30"},
        {"cls": "MSFT_TaskTimeTrigger", "start": "2026-11-01T08:00"},
    ]
    assert ss.rules_from_triggers(trs) == [
        {"kind": "daily", "times": ["04:00", "16:00"]},          # 每天的时刻并一条
        {"kind": "weekly", "days": ["Monday"], "times": ["08:00", "09:00"]},   # 同组周几并一条
        {"kind": "weekly", "days": ["Saturday"], "times": ["07:00"]},
        {"kind": "hourly", "hours": 4, "from": "00:00"},
        {"kind": "once", "at": "2026-11-01 08:00"},              # 一次性按时间排
        {"kind": "once", "at": "2026-12-02 09:30"},
    ]


def test_normalize_rules_validates_strictly():
    now = datetime(2026, 10, 26, 12, 0)
    assert ss.normalize_rules("不是列表") == ([], "至少要有一条定时（不想定时就选「关闭」）")
    assert ss.normalize_rules([])[1] == "至少要有一条定时（不想定时就选「关闭」）"
    ok, err = ss.normalize_rules([{"kind": "once", "at": "2026-10-27 9:05"}, {"kind": "daily", "times": ["16:00", "04:00"]},
                                  {"kind": "weekly", "days": ["Thursday", "Monday"], "times": "08:00"},
                                  {"kind": "hourly", "hours": 4}], now=now)
    assert err == "" and ok == [
        {"kind": "once", "at": "2026-10-27 09:05"},              # 规整成补零写法
        {"kind": "daily", "times": ["04:00", "16:00"]},
        {"kind": "weekly", "days": ["Monday", "Thursday"], "times": ["08:00"]},   # 周几按周内顺序
        {"kind": "hourly", "hours": 4, "from": "00:00"},
    ]
    assert ss.normalize_rules([{"kind": "once", "at": "2026-10-26 11:00"}], now=now)[1].endswith("已经过了")
    assert ss.normalize_rules([{"kind": "once", "at": "2026-13-99 10:00"}], now=now)[1].startswith("一次性的时间不对")
    assert "时间格式不对" in ss.normalize_rules([{"kind": "daily", "times": ["25:00"]}])[1]
    assert ss.normalize_rules([{"kind": "weekly", "days": [], "times": ["08:00"]}])[1] == "每周要至少选一天"
    assert ss.normalize_rules([{"kind": "hourly", "hours": 7}])[1] == "每几小时只能是 1–6"
    assert ss.normalize_rules([{"kind": "别的"}])[1] == "不认识的定时类型：别的"
    too_many = [{"kind": "daily", "times": [f"{h:02d}:00" for h in range(0, 17)]}]
    assert "最多 16" in ss.normalize_rules(too_many)[1]


def test_describe_rule_and_summary_text():
    assert ss.describe_rule({"kind": "daily", "times": ["04:00", "16:00"]}) == "每天 04:00、16:00"
    assert ss.describe_rule({"kind": "weekly", "days": ["Monday"], "times": ["08:00"]}) == "每周一 08:00"
    assert ss.describe_rule({"kind": "hourly", "hours": 4, "from": "00:00"}) == "每 4 小时一次"
    assert ss.describe_rule({"kind": "hourly", "hours": 2, "from": "06:30"}) == "每 2 小时一次（从 06:30 起）"
    assert ss.describe_rule({"kind": "once", "at": "2026-10-03 17:00"}) == "10/03 17:00 一次"
    assert ss.summary_text({"freq": "none"}) == "没有定时同步"
    assert ss.summary_text({"freq": "daily", "rules": []}, enabled=False) == "已关闭"
    st = {"freq": "custom", "rules": [{"kind": "weekly", "days": ["Monday"], "times": ["08:00"]},
                                      {"kind": "hourly", "hours": 4, "from": "00:00"}],
          "next_run": "2026-10-06T08:00:00"}
    assert ss.summary_text(st) == "每周一 08:00 · 每 4 小时一次 · 下次 10/06 08:00"
    assert ss.summary_text({"freq": "unknown", "rules": [], "others": ["登录时"]}) == "自定义触发器（登录时），未改动"
