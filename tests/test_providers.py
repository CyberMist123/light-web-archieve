"""provider 接口（CONVENTIONS §4，第 1B 批）：resolve / key 来源顺序 / HTTP 状态 → 故障码 / 旧 media 配置的内存换算 /
零 key 路径 / 设置页「测试」按钮测的是生产同一个函数。全部不联网（httpx 走 MockTransport 或替身）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from link_brain import ai_config, ask, llm, problems, providers, storage, text_stream


def settings_with(**caps):
    return ai_config._deep_merge(ai_config.DEFAULTS, caps)


def write_data_json(raw: dict) -> Path:
    path = ai_config.data_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# resolve
# --------------------------------------------------------------------------

def test_fresh_install_has_nothing_configured_except_local_caps():
    s = settings_with()
    for cap in ("textAI", "summaryAI", "visionAI", "visionAI.refine", "embedAI"):
        assert providers.resolve(cap, s) is None, cap
        assert providers.why_not(cap, s), cap
    assert providers.resolve("ocr", s)["mode"] == "local"
    assert providers.resolve("docConvert", s)["mode"] == "local"
    asr_cfg = providers.resolve("asrAI", s)
    assert asr_cfg["mode"] == "capswriter" and asr_cfg["port"] == 6016 and asr_cfg["host"] == "127.0.0.1"
    for cap in providers.CAPS:  # §4.5：超时都有默认值
        assert float(providers._timeout(providers.raw_config(cap, s), cap)) > 0


def test_key_source_order_apikey_then_keyfile_then_env(tmp_path, monkeypatch):
    keyfile = tmp_path / "keys.csv"
    keyfile.write_text("apiKey,FROM-FILE\nother,OTHER\n", encoding="utf-8")
    monkeypatch.setenv("LWA_TEST_KEY", "FROM-ENV")
    base = {"mode": "http", "endpoint": "https://x.invalid/v1/chat/completions", "model": "m"}
    both = {**base, "apiKey": "INLINE", "keyFile": str(keyfile), "apiKeyEnv": "LWA_TEST_KEY"}
    assert providers.resolve("textAI", settings_with(textAI=both))["apiKey"] == "INLINE"
    assert providers.resolve("textAI", settings_with(textAI={**both, "apiKey": ""}))["apiKey"] == "FROM-FILE"
    assert providers.resolve("textAI", settings_with(textAI={**both, "apiKey": "", "keyField": "other"}))["apiKey"] == "OTHER"
    env_only = {**base, "apiKeyEnv": "LWA_TEST_KEY"}
    assert providers.resolve("textAI", settings_with(textAI=env_only))["apiKey"] == "FROM-ENV"
    missing = {**base, "keyFile": str(tmp_path / "nope.csv"), "requireKey": True}
    assert providers.resolve("textAI", settings_with(textAI=missing)) is None
    assert "密钥文件" in providers.why_not("textAI", settings_with(textAI=missing))


def test_summary_inherits_text_ai_and_can_override_model_or_turn_off():
    text = {"mode": "http", "endpoint": "https://x.invalid/v1/chat/completions", "model": "big", "apiKey": "k"}
    cfg = providers.resolve("summaryAI", settings_with(textAI=text))
    assert cfg["endpoint"] == text["endpoint"] and cfg["model"] == "big" and cfg["apiKey"] == "k"
    assert cfg["maxTokens"] == ai_config.DEFAULTS["summaryAI"]["maxTokens"]
    cfg = providers.resolve("summaryAI", settings_with(textAI=text, summaryAI={"model": "small"}))
    assert cfg["model"] == "small" and cfg["endpoint"] == text["endpoint"]
    off = settings_with(textAI=text, summaryAI={"mode": "off"})
    assert providers.resolve("summaryAI", off) is None and "关闭" in providers.why_not("summaryAI", off)


def test_refine_uses_vision_endpoint_with_refine_model():
    vis = {"mode": "http", "endpoint": "https://v.invalid/v1/chat/completions", "model": "flash", "apiKey": "k"}
    assert providers.resolve("visionAI.refine", settings_with(visionAI=vis))["model"] == "flash"
    cfg = providers.resolve("visionAI.refine", settings_with(visionAI={**vis, "refineModel": "max"}))
    assert cfg["model"] == "max" and cfg["timeoutSec"] == ai_config.DEFAULTS["visionAI"]["refineTimeoutSec"]


@pytest.mark.parametrize("status,body,code", [
    (429, "", "TRANSIENT.HTTP_429"), (401, "", "NEEDS_HUMAN.AUTH_FAILED"), (403, "", "NEEDS_HUMAN.AUTH_FAILED"),
    (402, "", "NEEDS_HUMAN.QUOTA_EXCEEDED"), (400, '{"code":"Arrearage","message":"欠费"}', "NEEDS_HUMAN.QUOTA_EXCEEDED"),
    (500, "", "TRANSIENT.HTTP_5XX"), (503, "", "TRANSIENT.HTTP_5XX"), (400, "bad model", "PERMANENT.MODEL_OUTPUT_INVALID"),
    (404, "", "PERMANENT.MODEL_OUTPUT_INVALID"),
])
def test_http_status_to_fault_code(status, body, code):
    assert providers.http_code(status, body) == code
    assert problems.normalize(code) in problems.STATE_REGISTRY


def test_text_stream_translates_http_errors(monkeypatch):
    cfg = {"mode": "http", "endpoint": "https://x.invalid/v1/chat/completions", "model": "m", "apiKey": "k"}
    for status, code in ((401, "NEEDS_HUMAN.AUTH_FAILED"), (429, "TRANSIENT.HTTP_429"), (502, "TRANSIENT.HTTP_5XX")):
        monkeypatch.setattr(text_stream, "_CLIENT", httpx.Client(transport=httpx.MockTransport(
            lambda request, s=status: httpx.Response(s, text="nope"))))
        out = text_stream.call("i", "t", cfg)
        assert out["status"] == "failed" and out["code"] == code and out["api_error"] is True
    monkeypatch.setattr(text_stream, "_CLIENT", httpx.Client(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("down")))))
    out = text_stream.call("i", "t", cfg)
    assert out["code"] == "TRANSIENT.NETWORK"
    assert text_stream.call("i", "t", {"mode": "http", "endpoint": ""})["status"] == "skipped"


# --------------------------------------------------------------------------
# 旧配置（mode=media）在内存里换算，不改 data.json
# --------------------------------------------------------------------------

def legacy_raw(keyfile: Path | None):
    raw = {
        "textAI": {"mode": "http", "model": "", "endpoint": "https://api.deepseek.com/chat/completions", "apiKey": "",
                   "maxTokens": 2400},
        "ocr": {"mode": "media", "via": "local", "model": "", "endpoint": "", "apiKey": ""},
        "visionAI": {"mode": "media", "model": "qwen3.8-flash", "endpoint": "", "apiKey": "", "videoScreenText": False,
                     "refineModel": "qwen3.8-max"},
        "asrAI": {"mode": "media", "model": "whisper-1", "endpoint": "", "apiKey": ""},
        "models": [{"name": "DeepSeek", "mode": "http", "endpoint": "https://api.deepseek.com/chat/completions",
                    "model": "", "apiKey": ""}],
        "activeModel": "DeepSeek",
    }
    if keyfile:
        raw["textAI"].update(keyFile=str(keyfile), keyField="ds")
    return raw


def test_legacy_media_config_is_mapped_in_memory(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_OPENAI_BASE", raising=False)
    keyfile = tmp_path / "keys.csv"
    keyfile.write_text("apiKey,QWEN-KEY\nopenAiCompatible,https://ws-fake.example.invalid/compatible-mode/v1\n"
                       "ds,DS-KEY\n", encoding="utf-8")
    path = write_data_json(legacy_raw(keyfile))
    before = path.read_bytes()

    s = ai_config.load()
    assert path.read_bytes() == before, "只在内存里换算，不改她的文件"
    text = providers.resolve("textAI", ai_config.with_model(s))
    assert text["model"] == "deepseek-v4-flash" and text["apiKey"] == "DS-KEY"
    vis = providers.resolve("visionAI", s)
    assert vis["endpoint"] == "https://ws-fake.example.invalid/compatible-mode/v1/chat/completions"
    assert vis["apiKey"] == "QWEN-KEY" and vis["model"] == "qwen3.8-flash" and vis["videoScreenText"] is False
    assert providers.resolve("visionAI.refine", s)["model"] == "qwen3.8-max"
    summ = providers.resolve("summaryAI", s)
    assert summ["model"] == "qwen3.7-flash" and summ["apiKey"] == "QWEN-KEY" and summ["endpoint"] == vis["endpoint"]
    emb = providers.resolve("embedAI", s)
    assert emb["endpoint"] == "https://ws-fake.example.invalid/compatible-mode/v1/embeddings" and emb["apiKey"] == "QWEN-KEY"
    assert providers.resolve("asrAI", s)["mode"] == "capswriter"
    assert providers.resolve("ocr", s)["mode"] == "local"

    ai_config.load()  # 再读一次：说明只记一条
    rows = [r for r in problems.load() if r["step"] == "config"]
    assert len(rows) == 1 and rows[0]["code"] == "SKIPPED.LEGACY_CONFIG" and rows[0]["action"] == "skipped"
    assert "CapsWriter" in rows[0]["reason"] and "QWEN-KEY" not in rows[0]["reason"]


def test_legacy_media_without_any_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    write_data_json(legacy_raw(None))
    s = ai_config.load()
    for cap in ("visionAI", "summaryAI", "embedAI"):
        assert providers.resolve(cap, s) is None, cap
        assert "key" in providers.why_not(cap, s)
    raw = legacy_raw(None)
    raw["visionAI"]["mode"] = "media"
    monkeypatch.setenv("DASHSCOPE_API_KEY", "ENV-KEY")
    write_data_json(raw)
    vis = providers.resolve("visionAI", ai_config.load())
    assert vis["apiKey"] == "ENV-KEY" and vis["endpoint"].startswith(ai_config.LEGACY_DASHSCOPE_BASE)


def test_new_style_config_is_left_alone():
    write_data_json({"textAI": {"mode": "http", "endpoint": "https://x.invalid/v1/chat/completions", "model": "m"},
                     "visionAI": {"mode": "off"}, "asrAI": {"mode": "off"}, "ocr": {"mode": "local"}})
    s = ai_config.load()
    assert providers.resolve("visionAI", s) is None and providers.resolve("summaryAI", s)["model"] == "m"
    assert not [r for r in problems.load() if r["step"] == "config"]


# --------------------------------------------------------------------------
# 零 key（P11）：不配任何 AI 时归档完整，概要标 SKIPPED，问题记录里有一条
# --------------------------------------------------------------------------

def test_zero_key_ingest_archives_and_marks_summary_skipped(tmp_path, monkeypatch, capsys):
    from link_brain import cli, enrich, index as index_mod
    from link_brain.adapters import xiaohongshu as xhs
    fixture = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    note_id = "0000000000000000deadbeef"
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: {
        "note_id": note_id, "xsec_token": "FAKE", "canonical_url": xhs.CANONICAL_FMT.format(note_id=note_id),
        "input_url": text, "input_kind": "url"})
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: payload)
    for key in [k for k in __import__("os").environ if k.startswith(("LINK_BRAIN_MEDIA", "DASHSCOPE"))]:
        monkeypatch.delenv(key)

    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)  # 2 = 样例里有张图下不到（不联网）
    conn = index_mod.connect()
    row = conn.execute("SELECT item_id, source, source_id FROM objects").fetchone()
    conn.close()
    obj = storage.object_dir(row["source"], row["source_id"])
    assert (obj / "meta.json").is_file()
    capsys.readouterr()

    assert cli.main(["enrich", "--item", row["item_id"]]) == 0, "没配 AI 不是失败"
    doc = llm.load_extracted(row["source"], row["source_id"])
    assert doc["status"] == "skipped" and doc["code"] == "SKIPPED.NOT_CONFIGURED"
    assert "summary" not in enrich.needs(row["source"], row["source_id"])
    rows = [r for r in problems.load() if r["step"] == "enrich.summary"]
    assert len(rows) == 1 and rows[0]["code"] == "SKIPPED.NOT_CONFIGURED" and rows[0]["item_id"] is None
    assert problems.summary()["needs_human"] == 0

    # 之后配上了模型：这篇重新算「缺概要」，夜里会补
    write_data_json({"textAI": {"mode": "http", "endpoint": "https://x.invalid/v1/chat/completions", "model": "m"}})
    assert "summary" in enrich.needs(row["source"], row["source_id"])


# --------------------------------------------------------------------------
# 设置页「测试」：测的就是生产那一个函数
# --------------------------------------------------------------------------

def test_selftest_unconfigured_is_skipped_not_error(capsys):
    from link_brain import cli
    for kind in ("text", "summary", "vision"):
        out = ask.selftest(kind)
        assert out["ok"] is False and out["skipped"] is True and out["detail"], kind
    assert cli.main(["selftest", "summary"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["skipped"] is True


def test_selftest_text_uses_the_dropdown_model(monkeypatch):
    seen = []
    monkeypatch.setattr(ask, "call_text", lambda instr, text, settings: seen.append(settings["textAI"]) or
                        {"status": "ok", "text": "ok"})
    write_data_json({"textAI": {"mode": "http", "endpoint": "https://x.invalid/v1/chat/completions", "model": "m"},
                     "models": [{"name": "Codex", "mode": "cli", "command": "codex exec -"}], "activeModel": "Codex"})
    assert ask.selftest("text")["ok"] is True
    assert seen[0]["mode"] == "cli", "测的是问答页下拉选中的模型，不是只测文本 AI"


def test_selftest_summary_runs_the_production_call_and_schema(monkeypatch):
    calls = []
    good = {"summary": "番茄炒蛋做法", "key_points": [], "tags": ["菜谱"], "links_worth_opening": [],
            "valuable_comments": [], "ads_or_noise": []}
    monkeypatch.setattr(llm, "call_model", lambda i, t, cfg: calls.append(cfg) or
                        {"status": "ok", "text": json.dumps(good, ensure_ascii=False)})
    write_data_json({"textAI": {"mode": "http", "endpoint": "https://x.invalid/v1/chat/completions", "model": "big"},
                     "summaryAI": {"model": "small"}})
    out = ask.selftest("summary")
    assert out["ok"] is True and "番茄炒蛋" in out["detail"] and calls[0]["model"] == "small"
    monkeypatch.setattr(llm, "call_model", lambda i, t, cfg: {"status": "ok", "text": "不是 JSON"})
    out = ask.selftest("summary")
    assert out["ok"] is False and out["code"] == "PERMANENT.MODEL_OUTPUT_INVALID"


def test_selftest_vision_runs_layer1_understand(monkeypatch):
    from link_brain import visual
    write_data_json({"visionAI": {"mode": "http", "endpoint": "https://v.invalid/v1/chat/completions",
                                  "model": "vl", "apiKey": "k"}})
    sent = {}

    def post(url, headers=None, content=None, timeout=None):
        sent.update(url=url, body=json.loads(content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "类型：截图文字\nOCR TEST"},
                                                      "finish_reason": "stop"}], "usage": {}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(visual, "available", lambda: False)
    out = ask.selftest("vision")
    assert out["ok"] is True and "截图文字" in out["detail"] and sent["body"]["model"] == "vl"
    assert sent["url"] == "https://v.invalid/v1/chat/completions"
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(401, text="bad key", request=httpx.Request("POST", url)))
    out = ask.selftest("vision")
    assert out["ok"] is False and out["code"] == "NEEDS_HUMAN.AUTH_FAILED"


# --------------------------------------------------------------------------
# 代码里没有作者本机的默认路径（§4.3）
# --------------------------------------------------------------------------

def test_no_private_default_paths_in_code():
    root = Path(__file__).resolve().parents[1]
    patterns = [r"[A-Za-z]:\\\\?Users\\\\?[^\\\s'\"]+\\\\?(Documents|AppData)", r"LINK_BRAIN_MEDIA", r"\bmedia\.py",
                r"D:\\\\?AI\b", r"LINK_BRAIN_MODELS_DIR"]
    local = root / ".githooks" / "private-patterns.local.txt"
    if local.is_file():
        patterns += [re.escape(line.strip()) for line in local.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("#")]
    hits = []
    for base in (root / "link_brain", root / "obsidian-plugins"):
        for f in base.rglob("*"):
            if f.suffix not in (".py", ".js", ".json", ".yaml", ".css", ".md") or not f.is_file():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            hits += [f"{f.name}: {p}" for p in patterns if re.search(p, text, re.I)]
    assert hits == []
