"""0928 识图两层：第一层打标规则、Mermaid 检查、第二层补跑（成功写回 / 失败重试 2 次后放弃 / 手动点名）。"""

from __future__ import annotations

from link_brain import render as render_mod, storage, vision, visual

F = "`" * 3


def _entry(kind="diagram", chars=400, score=0.9, **visual_extra):
    text = "字" * chars
    return {"asset": "raw/v0001/assets/image-001.webp", "status": "ok",
            "lines": [{"text": text, "box": [0, 0, 10, 10], "score": score}],
            "visual": {"kind": kind, "status": "ok", "text": "要点", "v": visual.VISUAL_VERSION, **visual_extra}}


def test_refine_reason_rules():
    assert "流程图且字多" in vision.refine_reason(_entry("diagram", 400))
    assert vision.refine_reason(_entry("diagram", 100)) == ""
    assert vision.refine_reason(_entry("picture", 400)) == ""
    assert "复读" in vision.refine_reason(_entry("text", 50, shaky="出现复读"))
    assert "信心偏低" in vision.refine_reason(_entry("text", 50, score=0.5))


def test_mark_refine_respects_done_unless_manual():
    e = _entry()
    assert vision.mark_refine(e, "x")
    e["refine"]["status"] = "done"
    assert not vision.mark_refine(e, "y")
    assert vision.mark_refine(e, "手动点名", manual=True) and e["refine"]["status"] == "pending"


def test_mermaid_problem():
    ok = F + 'mermaid\nflowchart TD\n  subgraph s1["区"]\n  n1["a<br/>b"] -.-> n2["c"]\n  end\n' + F
    assert visual.mermaid_problem(ok) == ""
    assert "引号" in visual.mermaid_problem(F + 'mermaid\nflowchart TD\n  n1[/wake]\n' + F)
    assert "闭合" in visual.mermaid_problem(F + 'mermaid\nflowchart LR\n  subgraph s1["x"]\n  n1["a"]\n' + F)
    assert "不完整" in visual.mermaid_problem("flowchart TD")


def _setup(tmp_path, monkeypatch, entry):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(render_mod, "render_object", lambda *a, **k: None)
    monkeypatch.setattr(vision, "REFINE_GAP_SECONDS", (0, 0))
    vpath = storage.derived_dir("xiaohongshu", "abc") / "vision.json"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(vpath, {"schema_version": 1, "version": 1, "images": [entry]})
    return vpath


def test_refine_object_success_writes_back(tmp_path, monkeypatch):
    e = _entry()
    vision.mark_refine(e, "流程图且字多")
    vpath = _setup(tmp_path, monkeypatch, e)
    monkeypatch.setattr(visual, "refine", lambda *a, **k: {"status": "ok", "kind": "diagram", "text": "图",
                                                           "model": "m", "cost_yuan": 0.02})
    tally = vision.refine_object("xiaohongshu", "abc", {"model": "m"})
    got = storage.read_json(vpath)["images"][0]
    assert tally["done"] == 1 and got["refine"]["status"] == "done" and got["refined"]["text"] == "图"
    assert abs(tally["cost_yuan"] - 0.02) < 1e-9


def test_refine_object_gives_up_after_three_tries(tmp_path, monkeypatch):
    e = _entry()
    vision.mark_refine(e, "流程图且字多")
    vpath = _setup(tmp_path, monkeypatch, e)
    monkeypatch.setattr(visual, "refine", lambda *a, **k: {"status": "failed", "error": "Mermaid 引号不成对"})
    for _ in range(3):
        vision.refine_object("xiaohongshu", "abc", {"model": "m"})
    ref = storage.read_json(vpath)["images"][0]["refine"]
    assert ref["status"] == "failed" and ref["tries"] == 3
    # 放弃后夜里不再跑
    calls = []
    monkeypatch.setattr(visual, "refine", lambda *a, **k: calls.append(1) or {"status": "ok"})
    vision.refine_object("xiaohongshu", "abc", {"model": "m"})
    assert not calls


def test_router_rotates_keys_then_falls_back(monkeypatch):
    """429 换下一个 key；全不行退回千问兜底；内容不合格不换 key（算一次尝试）。"""
    monkeypatch.setenv("LWA_GEMINI_KEYS", "k1,k2")
    calls = []

    def fake(path, lines, kind, cfg):
        calls.append(cfg.get("apiKey") or cfg["model"])
        if cfg.get("apiKey"):
            return {"status": "failed", "code": "TRANSIENT.HTTP_429", "http_status": 429, "api_error": True,
                    "error": "接口限流（HTTP 429）"}
        return {"status": "ok", "kind": "diagram", "text": "图", "model": cfg["model"]}

    monkeypatch.setattr(visual, "refine", fake)
    r = vision.RefineRouter({"model": "qwen3.8-max", "endpoint": "x"})
    assert r.refine(None, [], "diagram")["status"] == "ok"
    assert calls == ["k1", "k2", "qwen3.8-max"]
    calls.clear()
    r.refine(None, [], "diagram")  # 今晚已用完的 key 不再试
    assert calls == ["qwen3.8-max"]

    monkeypatch.setattr(visual, "refine", lambda *a, **k: {"status": "failed", "error": "Mermaid 引号不成对"})
    r2 = vision.RefineRouter(None)
    assert "引号" in r2.refine(None, [], "diagram")["error"] and not r2.dead


# --------------------------------------------------------------------------
# 1008（L6·B2）：长段落 / 长气泡不是复读；真复读照样收、照样报；一篇里一张成功不消整篇的问题
# --------------------------------------------------------------------------

LONG_EN = ("Large language model agents increasingly rely on retrieval to ground their answers, yet the way an agent "
           "reads a document is rarely designed with the same care as the model itself. In this section we describe "
           "how we restructured the reading loop: instead of feeding whole pages, the agent first skims headings, "
           "then requests the paragraphs it believes are relevant, and finally verifies each quoted claim against the "
           "source span before it is allowed into the final response. We measured accuracy, latency and token usage "
           "across three benchmark suites and found that the staged approach reduced hallucinated citations by a wide "
           "margin while keeping median latency within two seconds of the baseline configuration we started from.")
LONG_ZH = ("今天把迁移方案又过了一遍：先把旧库的快照导出来，核对条数和校验和，再在测试环境里按新的表结构重建索引，"
           "跑完全量回放之后对比两边的查询结果，差异全部记进表格里逐条确认原因；确认没问题以后才切流量，"
           "切的时候保留旧库只读一周，万一新库出事可以在十分钟之内切回去。另外提醒一下，周四晚上机房要停电检修，"
           "所有定时任务记得提前暂停，检修结束后按顺序恢复，先恢复采集再恢复汇总，别让汇总读到半截数据。"
           "还有那份对外的说明文档，我改了第三节的措辞，把容易引起误会的几个说法换掉了，你有空看看行不行。") * 2


def test_long_paragraph_is_not_repetition():
    assert len(LONG_EN) > 605
    for text in (LONG_EN, LONG_ZH.replace("。还有", "。补充：还有", 1)):
        tidy = visual.tidy_output(text)
        assert visual.REPEAT_MARK not in tidy and "截断" not in tidy
        assert visual.shaky_reason(text, tidy, "stop") == ""


def test_true_repetition_still_flagged():
    for raw in ("[打码]" * 100, "前面正常的一句话。" + "这是同一段二十个字的复读内容反复出现了" * 30,
                "数据数据" + "".join(f"片段{i % 3}abcdefghijklmnopq" for i in range(60))):
        tidy = visual.tidy_output(raw)
        assert visual.shaky_reason(raw, tidy, "stop") == "出现复读", raw[:20]


def test_separator_line_is_not_repetition():
    raw = "━" * 300 + "\n" + "……" * 40
    assert visual.shaky_reason(raw, visual.tidy_output(raw), "stop") == ""


def test_hard_cap_reports_too_long():
    raw = "".join(chr(0x4e00 + i) for i in range(5000))
    tidy = visual.tidy_output(raw)
    assert visual.shaky_reason(raw, tidy, "stop") == "输出过长"


def test_refine_ladder_passes_long_paragraph(tmp_path, monkeypatch):
    """假模型回一段 700 字的合法长段落：精细识别 status=ok（以前判「出现复读」→ PERMANENT）。"""
    monkeypatch.setattr(visual, "_chat", lambda *a, **k: {"status": "ok", "text": LONG_EN + " " + LONG_EN[:100],
                                                           "finish": "stop", "tokens": 1, "cost_yuan": 0.01})
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    got = visual.refine(img, [], "text", {"model": "m", "endpoint": "https://example.invalid"})
    assert got["status"] == "ok", got.get("error")


def test_refine_run_retires_old_gave_up_row_1017(tmp_path, monkeypatch):
    """1017 作者裁决：精细识图放弃不是故障。以前登记的「AI 结果不可用」这篇一跑就按「已解决」口径收掉
    （同一篇别的图还 failed 也收——它不再是问题，改成机读版里标存疑）。"""
    from link_brain import problems
    ok_e, bad_e = _entry(), _entry()
    bad_e["asset"] = "raw/v0001/assets/image-006.webp"
    vision.mark_refine(ok_e, "x")
    bad_e["refine"] = {"status": "failed", "tries": 3, "reason": "x", "error": "出现复读"}
    _setup(tmp_path, monkeypatch, ok_e)
    vpath = storage.derived_dir("xiaohongshu", "abc") / "vision.json"
    doc = storage.read_json(vpath)
    doc["images"].append(bad_e)
    storage.write_json(vpath, doc)
    item = vision._item_id("xiaohongshu", "abc")
    problems.report("vision.refine", "PERMANENT.MODEL_OUTPUT_INVALID", "image-006.webp：坏", item_id=item)
    monkeypatch.setattr(visual, "refine", lambda *a, **k: {"status": "ok", "kind": "diagram", "text": "图", "model": "m"})
    vision.refine_object("xiaohongshu", "abc", {"model": "m"})
    assert not problems.is_open("vision.refine", item, "PERMANENT.MODEL_OUTPUT_INVALID")
    rows = [r for r in problems.load(100, include_resolved=True) if r["step"] == "vision.refine"]
    assert len(rows) == 1 and rows[0]["resolved_at"], "照 CONVENTIONS §2 追加 resolved 行，不删旧行"


def test_quote_mermaid_nodes_fixes_unquoted_labels_1009():
    """1009：超密架构图节点漏引号 → 判失败前自动补；已引的不动、补完能过检查、补两遍不变。"""
    from link_brain.visual import mermaid_problem, quote_mermaid_nodes
    s = ("```mermaid\nflowchart TD\n  subgraph S1[前端 层]\n  A[用户(手机端)] --> B((圆心))\n"
         "  B -->|调用| C{判断?}\n  C --> D(\"已引\") & E([胶囊])\n  end\n```")
    t = quote_mermaid_nodes(s)
    assert mermaid_problem(s) and mermaid_problem(t) == ""
    assert 'A["用户(手机端)"]' in t and 'B(("圆心"))' in t and 'D("已引")' in t and "|调用|" in t
    assert quote_mermaid_nodes(t) == t
