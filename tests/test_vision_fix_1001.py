"""1001 审计 media/vision-2、vision-4：Mermaid 校验误判；接口故障不计入第二层的重试次数。"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx

from link_brain import render as render_mod, storage, vision, visual

from test_vision_refine import _entry

F = "`" * 3


def _mm(*lines: str) -> str:
    return F + "mermaid\nflowchart TD\n" + "\n".join("  " + l for l in lines) + "\n" + F


def test_mermaid_brackets_inside_quotes_are_fine():
    assert visual.mermaid_problem(_mm('n1["用户(手机端)"] --> n2["服务"]')) == ""
    assert visual.mermaid_problem(_mm('n1["embedding(1024)"]')) == ""
    assert visual.mermaid_problem(_mm('b2["Qwen3 embedding[打码]"]')) == ""
    assert visual.mermaid_problem(_mm('subgraph s1["客户端(手机)"]', 'n1["a"]', "end")) == ""


def test_mermaid_really_broken_still_rejected():
    assert "引号" in visual.mermaid_problem(_mm("n1[用户(手机端)] --> n2"))
    assert "引号" in visual.mermaid_problem(_mm("n1(服务)"))
    assert "引号不成对" in visual.mermaid_problem(_mm('n1["abc] --> n2["d"]'))
    assert "闭合" in visual.mermaid_problem(_mm('subgraph s1["x"]', 'n1["a(b)"]'))


def test_mermaid_interaction_directives_rejected():
    assert "交互" in visual.mermaid_problem(_mm('n1["a"]', 'click n1 "https://example.invalid"'))
    assert "交互" in visual.mermaid_problem(_mm('n1["a"]', "click n1 call evil()"))
    assert "交互" in visual.mermaid_problem(_mm('n1["a"]', 'href n1 "x"'))
    init = F + 'mermaid\n%%{init: {"securityLevel": "loose"}}%%\nflowchart TD\n  n1["a"]\n' + F
    assert "交互" in visual.mermaid_problem(init)
    assert visual.mermaid_problem(_mm("%% 普通注释照常放过", 'n1["a"]')) == ""


def test_refine_accepts_quoted_parens_from_model(tmp_path, monkeypatch):
    """生产路径：visual.refine 收到带括号节点字的好图，算成功（以前判坏、3 次后永久放弃）。"""
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG")
    good = _mm('n1["用户(手机端)"] --> n2["Qwen3 embedding[打码]"]')
    monkeypatch.setattr(visual, "_chat", lambda *a, **k: {"status": "ok", "text": good, "finish": "stop",
                                                          "tokens": [1, 1], "cost_yuan": 0.0})
    out = visual.refine(img, [{"text": "用户"}], "diagram", {"model": "m", "endpoint": "x"})
    assert out["status"] == "ok" and out["kind"] == "diagram"


def _setup(tmp_path, monkeypatch, n=1):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(render_mod, "render_object", lambda *a, **k: None)
    monkeypatch.setattr(vision, "REFINE_GAP_SECONDS", (0, 0))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    entries = []
    for i in range(n):
        e = _entry()
        e["asset"] = f"raw/v0001/assets/image-{i:03d}.webp"
        vision.mark_refine(e, "流程图且字多")
        entries.append(e)
    obj = storage.object_dir("xiaohongshu", "abc")
    (obj / "raw/v0001/assets").mkdir(parents=True, exist_ok=True)
    for e in entries:
        (obj / e["asset"]).write_bytes(b"\x89PNG")
    vpath = storage.derived_dir("xiaohongshu", "abc") / "vision.json"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(vpath, {"schema_version": 1, "version": 1, "images": entries})
    return vpath


def _http(status: int | None):
    def post(url, headers=None, content=None, timeout=None):
        if status is None:
            raise httpx.ConnectTimeout("握手超时")
        return httpx.Response(status, request=httpx.Request("POST", url), json={"error": "x"})
    return post


def test_api_outage_does_not_burn_tries(tmp_path, monkeypatch, capsys):
    """连着几晚接口不通（限额 / 欠费 / 断网）：待补图留在 pending，不会第 3 晚被永久放弃。"""
    vpath = _setup(tmp_path, monkeypatch, n=5)
    monkeypatch.setenv("LWA_GEMINI_KEYS", "k1")
    fallback = {"model": "qwen3.8-max", "endpoint": "https://example.invalid/v1/chat"}
    monkeypatch.setattr(vision, "strong_config", lambda: fallback)

    def outage(url, headers=None, content=None, timeout=None):
        if "generativelanguage" in url:
            return _http(429)(url)
        return _http(None)(url)  # 兜底也连不上

    monkeypatch.setattr(visual.httpx, "post", outage)
    for _night in range(4):
        capsys.readouterr()
        vision.run_refine(SimpleNamespace(limit=0))
    out = json.loads(capsys.readouterr().out)
    assert out["api_errors"] == 3 and out["failed"] == 0, "连着 3 张接口故障就收手"
    refs = [e["refine"] for e in storage.read_json(vpath)["images"]]
    assert all(r["status"] == "pending" and r.get("tries", 0) == 0 for r in refs)


def test_server_errors_are_api_faults_but_bad_requests_count(tmp_path, monkeypatch):
    vpath = _setup(tmp_path, monkeypatch)
    cfg = {"model": "m", "endpoint": "https://example.invalid/v1/chat"}
    monkeypatch.setattr(visual.httpx, "post", _http(503))
    vision.refine_object("xiaohongshu", "abc", cfg)
    assert storage.read_json(vpath)["images"][0]["refine"].get("tries", 0) == 0

    monkeypatch.setattr(visual.httpx, "post", _http(400))  # 这张图的请求本身有问题：算一次
    vision.refine_object("xiaohongshu", "abc", cfg)
    assert storage.read_json(vpath)["images"][0]["refine"]["tries"] == 1
