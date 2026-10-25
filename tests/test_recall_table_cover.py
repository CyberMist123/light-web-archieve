"""recall_table 的补充用例：只测不调模型的纯函数——select_count / parse_verdicts / judge_text /
markdown / _cell / apply_judge（judge 用假的替身，不走 ask.call_text）。

gather / judge_select 会拉起真召回链路和判定模型，不在本文件盖（端到端归 tests/tools 与 ask 系列）。
"""

from __future__ import annotations

from link_brain import ask, recall_table as rt


def test_select_count():
    assert rt.select_count(0, 0) == 0        # 全 reject → 不送读
    assert rt.select_count(0, 9) == 2        # 没 deep：送沾边的前 2 篇
    assert rt.select_count(1, 9) == 3        # deep 不到 2：deep + 最多 2 篇 tentative
    assert rt.select_count(2, 9) == 2        # deep ≥ 2：tentative 不再补
    assert rt.select_count(9, 0) == min(9, ask.SELECT_HARD_MAX) == 8   # 送读上限 SELECT_HARD_MAX


def test_parse_verdicts_strict_lines():
    text = "\n".join([
        "1|deep_read|整篇就是 做法",
        "2 ｜ 剔除 ｜ 评论区    提到",
        "3|keep|顺带",
        "4|nope|不认识的话",
        "`5|deep_read|带反引号`",
        "1000|deep_read|编号超三位",
        "hello world",
        "6|reject|",                          # 空理由
    ])
    out = rt.parse_verdicts(text)
    assert out[1] == ("deep_read", "整篇就是 做法")     # 理由空白归一成单空格
    assert out[2] == ("reject", "评论区 提到")          # 全角竖线、两侧空白都认
    assert out[3] == ("deep_read", "顺带")              # keep → deep_read
    assert out[4] == ("tentative", "不认识的话")        # 判定词不在词表 → 记待定
    assert out[5] == ("deep_read", "带反引号")          # 行首尾的反引号剥掉
    assert out[6] == ("reject", "")
    assert 1000 not in out and len(out) == 6            # 只认 1–3 位编号；别的行整行丢
    assert rt.parse_verdicts("") == {} and rt.parse_verdicts(None) == {}


def test_judge_text_layout_and_cap():
    result = {"question": "问个菜谱", "understanding": {"goal": "找做法", "core": "低油"},
              "core_words": ["低油", "菜谱"],
              "rows": [
                  {"rank": 1, "title": "低油版红烧肉", "author": "阿珍", "kind": "视频", "summary": "步骤很多",
                   "hits": [{"label": "正文", "loc": "p3", "text": "细" * 260}]},
                  {"rank": 2, "title": "顺带提了一句", "author": "", "kind": "", "summary": "", "hits": []},
              ]}
    out = rt.judge_text(result, cap=40)
    assert out.splitlines()[0] == "问题：问个菜谱"
    assert "系统理解：目标=找做法；核心=低油；核心词=低油、菜谱" in out
    assert "候选：" in out
    assert "1. 《低油版红烧肉》 作者 阿珍 · 视频" in out      # 有作者/类型用原值
    assert "2. 《顺带提了一句》 作者 未知 · 图文" in out      # 缺省回落 未知 / 图文
    assert "概要：步骤很多" in out and "概要：无" in out
    assert "[正文·p3]「" + "细" * rt.HIT_CHARS + "」" in out   # 命中原文截到 HIT_CHARS
    assert "细" * (rt.HIT_CHARS + 1) + "」" not in out
    assert "（无字面命中，靠语义 / 扩词进来）" in out           # 无命中篇的占位说明
    assert rt.judge_text(result, cap=1).count("《") == 1       # cap 之外的篇不给模型看


def _row(rank, id_, title, *, verdict="", production="related", author="", kind="",
         hits=None, routes=(), reason=""):
    return {"rank": rank, "id": id_, "title": title, "author": author, "kind": kind, "summary": "s",
            "hits": hits or [], "routes": list(routes), "production": production,
            "verdict": verdict, "reason": reason}


def test_markdown_table():
    result = {
        "question": "哪款扫地机", "understanding": {"goal": "挑一款", "core": "扫地机"},
        "core_words": ["扫地机"], "expansion": ["扫拖一体"],
        "candidates_total": 12, "window": 6, "found_mode": "standalone", "filters_used": ["作者"],
        "production": {"mode": "direct", "mode_reason": "命中直接答", "primary_n": 2,
                       "select_reason": "named", "strong": 1},
        "rows": [
            _row(1, "a", "横评 A", verdict="deep_read", production="primary", author="老王", kind="图文",
                 hits=[{"label": "正文", "loc": "p2", "text": "实测对比|x"}], routes=["原词#1", "语义#2"],
                 reason="就是比较"),
            _row(2, "b", "顺带提到", verdict="reject"),
            _row(3, "c", "空白判定", verdict=""),
        ],
    }
    out = rt.markdown(result)
    assert out.splitlines()[0] == "# 召回表：哪款扫地机"
    assert "- 理解：目标 挑一款 · 核心「扫地机」 · 核心词 扫地机 · 过滤 作者" in out
    assert "追问模式" not in out                                  # standalone 不标追问
    assert "- 扩词：扫拖一体" in out
    assert "- 候选：全量 12 篇，首屏窗口 6 篇，下表列前 3 篇" in out
    assert "- 生产现在会：档位 **direct**（命中直接答），送读 **2** 篇（named），真命中 1" in out
    assert "模型判定" not in out                                  # 没跑 judge 就不出这行
    assert "| # | 判定 | 生产 | 篇 | 检出路 | 命中 | 理由 |" in out
    assert ("| 1 | 深读 | 主要依据 | **横评 A**<br>老王 · 图文 | 原词#1、语义#2 | 正文·p2：「实测对比｜x」 | 就是比较 |"
            in out)                                               # 命中里的 | 换成全角
    assert "| 2 | 剔除 | 其他相关 | **顺带提到** | - | （语义 / 扩词） |  |" in out
    assert "| 3 | — | 其他相关 |" in out                          # 没判定过 → —
    assert out.endswith("\n")


def test_markdown_judge_line_and_followup_mode():
    result = {"question": "Q", "understanding": {}, "core_words": [], "expansion": [],
              "candidates_total": 0, "window": 0, "found_mode": "history", "filters_used": [],
              "production": {"mode": "direct", "mode_reason": None, "primary_n": 0,
                             "select_reason": "error:X", "strong": None},
              "rows": [], "judge": {"status": "ok", "judged": 3, "error": "模型没按格式输出"}}
    out = rt.markdown(result)
    assert "- 理解：目标 - · 核心「」 · 核心词 无 · 追问模式 history" in out   # 空值回落 - / 无；非 standalone 标追问
    assert "- 扩词：无" in out
    assert "下表列前 0 篇" in out
    assert "- 模型判定：ok，判了 3 篇（模型没按格式输出）" in out               # judge 有 error 时带括号说明


def test_cell_normalizes_and_swaps_pipe():
    assert rt._cell("a|b") == "a｜b"
    assert rt._cell("  x \n y  z ") == "x y z"
    assert rt._cell(None) == "" and rt._cell("") == ""
    assert rt._cell("已 是｜全角") == "已 是｜全角"          # 全角竖线不动，只归一空白


def test_apply_judge_writes_model_selection(monkeypatch):
    rows = [_row(1, "a", "A"), _row(2, "b", "B"), _row(3, "c", "C")]
    seen = []

    def fake_judge(sub, settings, cap):
        seen.append((sub, settings, cap))
        by_id = {"a": ("deep_read", "就是做法"), "b": ("tentative", "沾边"), "c": ("reject", "无关")}
        for r in sub["rows"]:
            r["verdict"], r["reason"] = by_id[r["id"]]
        return {"status": "ok", "judged": 3}

    monkeypatch.setattr(rt, "judge", fake_judge)
    result = {"question": "Q", "understanding": {}, "core_words": [], "rows": rows,
              "production": {"primary_n": 0, "select_reason": "rule"}}
    info = rt.apply_judge(result, {"k": 1})
    assert info["status"] == "ok" and result["judge"] is info
    assert seen[0][1] == {"k": 1} and seen[0][2] == rt.JUDGE_CAP   # settings / cap 原样传给 judge
    assert seen[0][0]["rows"][0] is rows[0]                        # 同一批行 dict，判定直接写回结果
    assert rows[0]["verdict"] == "deep_read" and rows[0]["reason"] == "就是做法"
    assert [r["production"] for r in rows] == ["primary", "primary", "related"]  # n=select_count(1,1)=2
    assert result["production"]["primary_n"] == 2
    assert result["production"]["select_reason"] == "judge:1/3"


def test_apply_judge_failure_and_cap(monkeypatch):
    base = {"rank": 1, "id": "a", "title": "A", "author": "", "kind": "", "summary": "",
            "hits": [], "routes": [], "production": "related"}

    def fake_fail(sub, settings, cap):
        return {"status": "failed", "judged": 0, "error": "没配模型"}

    monkeypatch.setattr(rt, "judge", fake_fail)
    rows = [dict(base)]
    result = {"question": "Q", "understanding": {}, "core_words": [], "rows": rows,
              "production": {"primary_n": 0, "select_reason": "rule"}}
    info = rt.apply_judge(result, {})
    assert info == {"status": "failed", "judged": 0, "error": "没配模型"}
    assert result["judge"] is info
    assert rows[0]["production"] == "related" and "verdict" not in rows[0]   # 失败不回写任何判定
    assert result["production"] == {"primary_n": 0, "select_reason": "rule"}

    rows2 = [dict(base, rank=i + 1, id=f"r{i}") for i in range(3)]

    def fake_ok(sub, settings, cap):
        assert len(sub["rows"]) == 1                       # cap=1：只送第一篇去判
        sub["rows"][0]["verdict"], sub["rows"][0]["reason"] = "deep_read", "x"
        return {"status": "ok", "judged": 1}

    monkeypatch.setattr(rt, "judge", fake_ok)
    result2 = {"question": "Q", "understanding": {}, "core_words": [], "rows": rows2,
               "production": {"primary_n": 0, "select_reason": "rule"}}
    assert rt.apply_judge(result2, {}, cap=1)["judged"] == 1
    assert [r.get("verdict") for r in rows2] == ["deep_read", None, None]   # cap 外的篇不动
    assert [r["production"] for r in rows2] == ["primary", "related", "related"]
    assert result2["production"]["select_reason"] == "judge:1/1"
