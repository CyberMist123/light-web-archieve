"""1017 阶段 0/1：召回表模式 + opencode 命令行模型加固 + 远程 ask 限额可放开。离线、不调模型。"""
from __future__ import annotations

import json

from link_brain import recall_table, text_stream
from link_brain.remote import server as rserver


def _item(i, title, body, **fs):
    return {"id": f"xhs-{i}", "title": title, "author": f"作者{i}", "kind": "image", "tags": [], "cats": [],
            "summary": f"{title}的概要", "search_fields": {"body": body, **fs}}


ITEMS = [
    _item("a" * 24, "溏心蛋拉面店同款做法", "溏心蛋做法：水开后中火煮5分30秒，冰水冷却，味玉汁腌6到12小时。"),
    _item("b" * 24, "悉尼徒步公交攻略", "Watsons Bay 轮渡，380 到 Bondi，333 回城。", comments="评论：溏心蛋也好吃\n楼主：谢谢"),
    _item("c" * 24, "长寿防病人生指南", "第一章 饮食。第二章 运动。第三章 法律红线。"),
]
SETTINGS = {"textAI": {}, "retrieval": {"totalCharLimit": 8000, "topK": 8}}


def test_gather_rows_follow_pool_and_mark_production(monkeypatch):
    result = recall_table.gather("溏心蛋怎么做", ITEMS, SETTINGS)
    assert result["rows"], "有命中的篇应进首屏窗口"
    first = result["rows"][0]
    assert first["title"] == "溏心蛋拉面店同款做法"
    assert first["production"] == "primary"
    assert first["hits"] and first["hits"][0]["type"] == "body"
    assert any(t.startswith("原词#") for t in first["routes"])
    assert result["production"]["mode"] in ("direct", "toc")
    assert "候选" in recall_table.judge_text(result)


def test_judge_parses_only_well_formed_lines(monkeypatch):
    from link_brain import ask
    canned = {"status": "ok", "text": "好的，判定如下：\n1|deep_read|正文就是她问的做法\n2 ｜ 剔除 ｜ 只有评论区顺带提了一句\n乱七八糟的一行\n9|keep|不存在的编号"}
    monkeypatch.setattr(ask, "call_text", lambda *a, **k: canned)
    result = recall_table.gather("溏心蛋怎么做", ITEMS, SETTINGS)
    info = recall_table.judge(result, SETTINGS)
    assert info["status"] == "ok" and info["judged"] == 3
    by_rank = {r["rank"]: r for r in result["rows"]}
    assert by_rank[1]["verdict"] == "deep_read"
    if 2 in by_rank:
        assert by_rank[2]["verdict"] == "reject"
    md = recall_table.markdown(result)
    assert "| # | 判定 | 生产 |" in md and "深读" in md


def test_judge_without_model_is_skipped_not_crash(monkeypatch):
    from link_brain import ask
    monkeypatch.setattr(ask, "call_text", lambda *a, **k: {"status": "skipped", "text": None, "error": "没配"})
    result = recall_table.gather("溏心蛋怎么做", ITEMS, SETTINGS)
    info = recall_table.judge(result, SETTINGS)
    assert info["status"] == "skipped"
    assert all(r.get("verdict", "") == "" for r in result["rows"])
    assert recall_table.markdown(result)


def test_parse_verdicts_aliases():
    got = recall_table.parse_verdicts("1|深读|a\n2|tentative|b\n3|drop|c\n4|whatever|d")
    assert got[1][0] == "deep_read" and got[2][0] == "tentative" and got[3][0] == "reject" and got[4][0] == "tentative"


def test_harden_opencode_adds_pure_and_strips_auto():
    cmd = text_stream.harden_command(["opencode", "run", "-m", "opencode/x", "--auto"])
    assert "--pure" in cmd and "--auto" not in cmd
    assert cmd.count("--pure") == 1
    assert text_stream.harden_command(["opencode", "run", "--pure"]).count("--pure") == 1


def test_cli_env_denies_opencode_tools_only_for_opencode(monkeypatch):
    monkeypatch.delenv("OPENCODE_PERMISSION", raising=False)
    env = text_stream.cli_env(["opencode", "run"])
    perm = json.loads(env["OPENCODE_PERMISSION"])
    for tool in ("bash", "edit", "write", "webfetch"):
        assert perm[tool] == "deny"
    assert "read" not in perm, "只读工具不能拒：免费层会把没有只读工具的调用判成不在 OpenCode 里用"
    assert "OPENCODE_PERMISSION" not in text_stream.cli_env(["codex", "exec", "-"])
    monkeypatch.setenv("OPENCODE_PERMISSION", '{"bash":"ask"}')
    assert text_stream.cli_env(["opencode", "run"])["OPENCODE_PERMISSION"] == '{"bash":"ask"}'


def test_rate_window_zero_means_unlimited():
    w = rserver.Window(0, 3600)
    assert all(w.hit("k") for _ in range(100))
    w2 = rserver.Window(2, 3600)
    assert w2.hit("k") and w2.hit("k") and not w2.hit("k")
