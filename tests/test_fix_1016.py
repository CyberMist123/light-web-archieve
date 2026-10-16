"""1016：模型 403 不让夜跑 enrich 报「步骤出错」、主提供商坏了换备用并照实写、复读分段重识 / 截断保留、
续读里的 [NOTE_RESTRICTED] 改记到 note.restricted。"""
import json

import httpx
import pytest
from PIL import Image

from link_brain import ai_health, comment_fill, nightly, problems, restricted, storage, vision, visual

CFG = {"endpoint": "https://primary.invalid/v1/chat/completions", "model": "qwen3.8-flash", "apiKey": "bad"}
LINES = [{"text": "一行字", "score": 0.9, "box": [0, 0, 10, 10]}]



@pytest.fixture(autouse=True)
def _confirm_on_first_hit(monkeypatch):
    """1017 起撞见一次只算疑似、隔天再撞才确认；这里测的是「已确认」那条路，按一次即确认跑。"""
    from link_brain import restricted as _r
    monkeypatch.setattr(_r, "CONFIRM_DAYS", 1)

def _resp(url, status=200, text=None, content=None):
    req = httpx.Request("POST", url)
    if status != 200:
        return httpx.Response(status, text=text or "{}", request=req)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                     "usage": {}}, request=req)


def _img(tmp_path, h=1440):
    p = tmp_path / "image-002.png"
    Image.new("RGB", (1080, h), "white").save(p)
    return p


# ---------------------------------------------------------------- 1. enrich 退出码


def test_nightly_treats_enrich_registered_exit_as_not_a_crash():
    assert nightly.step_slug("enrich --pending") in nightly.REGISTERED_STEP
    assert nightly.REGISTERED_STEP["enrich-pending"] == "ai.summary"


# ---------------------------------------------------------------- 2. 识图换备用


def test_layer1_403_switches_to_free_key_and_panel_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("LWA_GEMINI_KEYS", "k1")
    monkeypatch.setattr(vision, "strong_config", lambda: None)
    hits = []

    def post(url, **kw):
        hits.append(url)
        if "primary" in url:
            return _resp(url, 403, '{"error":{"code":"AccessDenied"}}')
        return _resp(url, content="类型：图片\n一张书桌照片")

    monkeypatch.setattr(httpx, "post", post)
    entry = {"status": "ok", "lines": LINES, "asset": "raw/v0001/assets/image-002.png"}
    out = vision._understand(entry, _img(tmp_path), CFG, "web", "web-x1")
    assert out["visual"]["status"] == "ok" and "免费 key 1" in out["visual"]["switched_to"]
    assert "switched_from" not in out["visual"]
    rows = [r for r in problems.load(100) if r["step"] == "ai.vision"]
    assert rows and "已换用 Google" in rows[0]["reason"] and rows[0]["code"] == "NEEDS_HUMAN.AUTH_FAILED"
    assert ai_health.affected("visionAI") == []  # 补上了的不算「影响的篇」


def test_layer1_content_filtered_switches_and_resolves_old_400(monkeypatch, tmp_path):
    monkeypatch.setenv("LWA_GEMINI_KEYS", "k1")
    monkeypatch.setattr(vision, "strong_config", lambda: None)
    problems.report("vision.layer1", "PERMANENT.MODEL_OUTPUT_INVALID", "接口不接受这次请求（HTTP 400）", item_id="web-x2")
    flt = '{"error":{"code":"data_inspection_failed","message":"Input data may contain inappropriate content."}}'

    def post(url, **kw):
        return _resp(url, 400, flt) if "primary" in url else _resp(url, content="类型：截图文字\n正文")

    monkeypatch.setattr(httpx, "post", post)
    entry = {"status": "ok", "lines": LINES, "asset": "a.png"}
    out = vision._understand(entry, _img(tmp_path), CFG, "web", "web-x2")
    assert out["visual"]["status"] == "ok"
    assert not problems.is_open("vision.layer1", "web-x2", "PERMANENT.MODEL_OUTPUT_INVALID")


def test_backups_skip_same_endpoint_same_key(monkeypatch):
    monkeypatch.delenv("LWA_GEMINI_KEYS", raising=False)
    monkeypatch.setattr(vision, "strong_config", lambda: {**CFG, "model": "qwen3.8-max"})
    assert vision.vision_backups(CFG) == []


def test_layer1_api_failure_resolves_stale_400_row(monkeypatch, tmp_path):
    problems.report("vision.layer1", "PERMANENT.MODEL_OUTPUT_INVALID", "HTTP 400", item_id="web-x3")
    vision._layer1_problem({"status": "failed", "code": "NEEDS_HUMAN.AUTH_FAILED", "api_error": True}, "web", "web-x3", CFG)
    assert not problems.is_open("vision.layer1", "web-x3", "PERMANENT.MODEL_OUTPUT_INVALID")


# ---------------------------------------------------------------- 2. 概要换备用（DeepSeek）


def test_summary_403_switches_to_text_model(monkeypatch):
    from link_brain import llm as llm_mod
    alt = {"mode": "http", "endpoint": "https://api.deepseek.com/chat/completions", "model": "deepseek-v4-flash"}
    calls = []

    def fake(instruction, text, cfg):
        calls.append(cfg.get("model"))
        if cfg is alt:
            return {"status": "ok", "text": json.dumps({"summary": "好", "key_points": [], "tags": [], "links_worth_opening": [], "valuable_comments": [], "ads_or_noise": []})}
        return {"status": "failed", "code": "NEEDS_HUMAN.AUTH_FAILED", "error": "403", "api_error": True,
                "http_status": 403}

    monkeypatch.setattr(llm_mod, "call_model", fake)
    monkeypatch.setattr(llm_mod, "alternate_summary_config", lambda primary, settings: alt)
    sk, sid = _seed_object()
    from link_brain import providers
    monkeypatch.setattr(providers, "resolve", lambda cap, settings=None: dict(CFG) if cap == "summaryAI" else None)
    doc = llm_mod.extract(sk, sid, force=True)
    assert calls == ["qwen3.8-flash", "deepseek-v4-flash"]  # 403 不在主模型上白重试
    assert doc["status"] == "ok" and doc.get("fallback_model")
    rows = [r for r in problems.load(100) if r["step"] == "ai.summary"]
    assert rows and "已换用 DeepSeek deepseek-v4-flash" in rows[0]["reason"]


def _seed_object():
    sk, sid = "web", "fix1016"
    od = storage.object_dir(sk, sid)
    raw = storage.raw_dir(sk, sid, 1)
    raw.mkdir(parents=True, exist_ok=True)
    storage.write_json(od / "meta.json", {"current_version": 1, "item_id": f"{sk}-{sid}", "title": "t"})
    storage.write_json(raw / "source.json", {"note": {"title": "t", "desc": "正文"}, "comments": []})
    return sk, sid


# ---------------------------------------------------------------- 4. 复读


def test_salvage_keeps_valid_part_before_repeat():
    good = "这是一段有效的转录文字，" * 10
    text = good + "\n" + "复读复读复读复读复读复读" + visual.REPEAT_MARK
    kept = vision.salvage_repeat(text)
    assert kept.startswith(good) and vision.SALVAGE_NOTE in kept and visual.REPEAT_MARK not in kept
    assert vision.salvage_repeat("短" + visual.REPEAT_MARK) == ""
    assert vision.salvage_repeat("```mermaid\ngraph TD\n" + good + visual.REPEAT_MARK) == ""


def test_repeat_ladder_falls_to_tiles(monkeypatch, tmp_path):
    calls = []

    def fake_refine(path, lines, kind, cfg, timeout=None):
        calls.append(path.name)
        if path.name.startswith("tile"):
            return {"status": "ok", "kind": "text", "text": f"第{len(calls)}段", "model": cfg["model"], "cost_yuan": 0.01}
        return {"status": "failed", "text": "复读" + visual.REPEAT_MARK, "error": "出现复读",
                "code": "PERMANENT.MODEL_OUTPUT_INVALID", "model": cfg["model"]}

    monkeypatch.setattr(visual, "refine", fake_refine)
    monkeypatch.setattr(vision, "alternate_models", lambda used: [])
    got, tried = vision.refine_with_fallbacks(_img(tmp_path), LINES, "text", CFG)
    assert got["status"] == "ok" and got["tiles"] >= 2 and "段重识" in tried[-1]
    assert sum(1 for c in calls if c.startswith("tile")) == got["tiles"]


def test_old_repeat_failures_get_one_more_chance():
    assert vision.repeat_retry_due({"status": "failed", "error": "出现复读"})
    assert not vision.repeat_retry_due({"status": "failed", "error": "出现复读", "repeat_retry": 1})
    assert not vision.repeat_retry_due({"status": "failed", "error": "输出被截断"})


# ---------------------------------------------------------------- 5. NOTE_RESTRICTED 归类

ERR = ("AdapterError: MCP get_feed_detail 报错: 获取Feed详情失败: [NOTE_RESTRICTED] 详情页没渲染出这篇笔记"
       "（页面停在 /explore）")


def test_reclassify_old_fill_rows_to_note_restricted(monkeypatch):
    sid = "6a9c3d770000000011035233"
    item = f"xhs-{sid}"
    storage.object_dir("xiaohongshu", sid).mkdir(parents=True, exist_ok=True)
    comment_fill.save_state("xiaohongshu", sid, {"stuck": True, "no_progress": 3, "last_error": ERR,
                                                 "stuck_reason": "这篇读不出来：" + ERR})
    problems.report(comment_fill.STEP, comment_fill.CODE_INCOMPLETE, "评论续读连着 3 次没成：" + ERR, item_id=item)
    assert restricted.reclassify_fill_failures() == [item]
    assert not problems.is_open(comment_fill.STEP, item, comment_fill.CODE_INCOMPLETE)
    assert problems.is_open(restricted.STEP, item, restricted.CODE)
    st = comment_fill.load_state("xiaohongshu", sid)
    assert not st.get("stuck") and st["no_progress"] == 0
    assert restricted.reclassify_fill_failures() == []  # 幂等
    n = sum(1 for r in problems.load(100) if r.get("item_id") == item)
    assert n == 1  # 同篇只剩一条（note.restricted）


def test_note_failure_with_marker_marks_restricted(monkeypatch):
    from link_brain import index as index_mod
    sid = "6a92f6e6000000001803f8b6"

    class C:
        def close(self):
            pass

    monkeypatch.setattr(index_mod, "connect", lambda: C())
    monkeypatch.setattr(index_mod, "get_object", lambda conn, iid: {"source": "xiaohongshu", "source_id": sid})
    storage.object_dir("xiaohongshu", sid).mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        comment_fill.note_failure(f"xhs-{sid}", ERR)
    assert not problems.is_open(comment_fill.STEP, f"xhs-{sid}", comment_fill.CODE_INCOMPLETE)
    assert problems.is_open(restricted.STEP, f"xhs-{sid}", restricted.CODE)
    assert int(comment_fill.load_state("xiaohongshu", sid).get("no_progress") or 0) == 0
