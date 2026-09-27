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
            return {"status": "failed", "error": "HTTPStatusError: 429 Too Many Requests"}
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
