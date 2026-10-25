"""ARCH-AUDIT 第 2 批：价格一处（pricing.py）、免费只认显式标记、预算默认只在后端、密钥只经 providers、CLI 和接口平级。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from link_brain import ai_config, ai_routes, budget, keyprobe, nightly, pricing, providers, storage, usage, visual
from link_brain.nightly import Nightly

BJ = timezone(timedelta(hours=8))
PY = sys.executable
QWEN_MAX = {"endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "model": "qwen3.8-max", "apiKey": "k-123456789"}
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    budget._cache.update(at=0.0, day="", spent=0.0)
    providers._POOL_CMD_CACHE.clear()
    monkeypatch.setattr(ai_config, "load", lambda: {"budget": {"dailyYuan": 1}})
    for name in ("LWA_GEMINI_KEYS", "LWA_GEMINI_KEYS_CMD", "LWA_GEMINI_KEYS_FILE"):
        monkeypatch.delenv(name, raising=False)
    yield


def _fake_vision_reply(monkeypatch, tin: int, tout: int):
    def post(url, headers=None, content=None, timeout=None):
        return httpx.Response(200, json={"choices": [{"message": {"content": "类型：截图文字\n一段字"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": tin, "completion_tokens": tout}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)


def _one_image(tmp_path: Path) -> Path:
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG fake")
    return img


# ---------------------------------------------------------------- 四处钱数相等

def test_same_call_same_money_everywhere(monkeypatch, tmp_path):
    """同一次识图：执行器回的 cost_yuan（夜跑「花费」就是它的和）、账本 usage.cost_of、预算 spent_today、
    设置页 ai_routes 显示的钱，四处是同一个数。"""
    tin, tout = 100_000, 20_000
    _fake_vision_reply(monkeypatch, tin, tout)
    with usage.tag("vision"):
        got = visual.understand(_one_image(tmp_path), [], QWEN_MAX)
    assert got["status"] == "ok"
    expect = (tin * 12.0 + tout * 36.0) / 1_000_000           # qwen3.8-max ¥12 / ¥36 每百万
    assert got["cost_yuan"] == pytest.approx(expect)          # 夜跑「花费」= 这些 cost_yuan 相加
    rows = usage.load(1)
    assert len(rows) == 1 and rows[0]["m"] == "qwen3.8-max"
    assert usage.cost_of(rows[0]) == pytest.approx(expect)
    assert budget.spent_today(fresh=True) == pytest.approx(expect)
    shown = ai_routes._entry(QWEN_MAX, "百炼 max", pricing.table(), (tin, tout), 1, "次")
    assert shown["yuan"] == pytest.approx(expect, abs=1e-4) and shown["free"] is False


def test_refine_tally_reports_unpriced_not_zero(monkeypatch, tmp_path, capsys):
    """夜跑那一行：查不到价的调用不当 0 元混进「花费」，单独说「N 次未计价」。"""
    job = Nightly(steps=[], workdir=tmp_path, log_path=tmp_path / "n.log", sleep=lambda s: None)
    out = json.dumps({"refined": 1, "failed": 0, "pending_left": 0, "cost_yuan": 0.0, "unpriced": 2, "models": {"x": 1}})
    monkeypatch.setattr(job, "run_step", lambda step, env_extra=None: nightly.StepResult(step.name, code=0, stdout=[out]))
    monkeypatch.setattr(job, "refine_keys", lambda: ("LWA_GEMINI_KEYS", []))
    job._refine(nightly.Step(nightly.REFINE_STEP, [], 1))
    assert "另 2 次的模型不在价格表里，未计价" in (tmp_path / "n.log").read_text("utf-8")


# ---------------------------------------------------------------- 未知模型 = 未计价，预算拦

def test_unknown_model_is_unpriced_everywhere_and_budget_blocks(monkeypatch, tmp_path):
    odd = {**QWEN_MAX, "model": "没听过的模型-x1"}
    _fake_vision_reply(monkeypatch, 1000, 100)
    with usage.tag("vision"):
        got = visual.understand(_one_image(tmp_path), [], odd)
    assert got["cost_yuan"] is None and got["unpriced"] is True          # 执行器（夜跑花费）
    row = usage.load(1)[-1]
    assert usage.cost_of(row) is None                                     # 账本
    assert usage.month_summary()["unpriced"] == 1                         # 目录页边栏
    shown = ai_routes._entry(odd, "x", pricing.table(), (1000, 100), 100, "张")
    assert shown["price"] == "—，未计价" and shown["free"] is False        # 设置页
    assert budget.is_paid(odd)                                            # 预算：按要钱的算
    # 到了上限：未计价的后台调用照样拦（宁可多拦）
    usage.record("visionAI", QWEN_MAX, {"prompt_tokens": 100_000, "completion_tokens": 0}, feature="vision")
    budget._cache.update(at=0.0)   # 账本缓存 60 秒：测试里直接作废
    with usage.tag("vision"):
        assert budget.blocked(odd)["code"] == "TRANSIENT.BUDGET"


def test_free_only_from_explicit_marks():
    table = pricing.table()
    gem = {"endpoint": GEMINI, "model": "gemini-3.5-flash", "apiKey": "g"}
    assert not pricing.is_free(gem, table) and pricing.is_paid(gem, table)       # 不在价格表里 / 价 null ≠ 免费
    assert pricing.is_free({**gem, "keyPool": "gemini"}, table)                  # 免费 key 池
    assert pricing.is_free({**gem, "free": True}, table)                         # 执行器标的（vision 免费 key）
    assert pricing.is_free({"mode": "cli", "command": "opencode run"}, table)    # 本机命令行
    assert pricing.is_free({"model": "m"}, {"models": {"m": {"free": True}}})    # 价格表写了 free
    assert pricing.cost_of({"p": "google", "m": "gemini-3.5-flash", "in": 9, "out": 9, "free": True}) == 0.0
    assert pricing.cost_of({"p": "google", "m": "gemini-3.5-flash", "in": 9, "out": 9}) is None


def test_gemini_pool_call_is_logged_free(monkeypatch, tmp_path):
    monkeypatch.setenv("LWA_GEMINI_KEYS", "g1")
    _fake_vision_reply(monkeypatch, 5000, 500)
    router = __import__("link_brain.vision", fromlist=["RefineRouter"]).RefineRouter(None)
    got = router.refine(_one_image(tmp_path), [], "text")
    assert got["cost_yuan"] == 0.0
    row = usage.load(1)[-1]
    assert row["m"] == "gemini-3.5-flash" and row.get("free") is True           # 账本 m 只写原始模型名
    assert usage.cost_of(row) == 0.0


# ---------------------------------------------------------------- 用户覆盖价格

def test_user_price_override_reaches_keyprobe_and_ledger():
    over = storage.link_brain_home() / "pricing.json"
    over.parent.mkdir(parents=True, exist_ok=True)
    over.write_text(json.dumps({"recommended": {"summary": "qwen3.7-flash", "ask": "qwen3.7-flash"},
                                "models": {"qwen3.8-max": {"input": 1.0, "output": 0.0}}}), "utf-8")
    fills = keyprobe.fills_for("aliyun")
    assert fills["textAI"]["model"] == "qwen3.7-flash"                          # keyprobe 读到覆盖（以前直读包内文件）
    row = {"p": "aliyun", "m": "qwen3.8-max", "in": 1_000_000, "out": 1_000_000}
    assert usage.cost_of(row) == pytest.approx(1.0)


# ---------------------------------------------------------------- 价格表本身

def test_pricing_table_resolves_recommended_and_runtime_models():
    table = pricing.table()
    for item, model in table["recommended"].items():
        assert pricing.price_of(model, table), (item, model)
    for item, models in table["alternatives"].items():
        for model in models:
            assert pricing.price_of(model, table), (item, model)
    # STATE.md 里写着的运行时模型：都在表里；Gemini 两个走免费 key 池时按免费记
    for model in ("gemini-3.5-flash", "gemini-embedding-2", "qwen3.7-flash", "qwen3.8-max", "deepseek-v4-flash",
                  "qwen3.7-text-embedding-flash", "qwen3-vl-plus", "qwen3.7-plus"):
        assert pricing.price_of(model, table), model
    for model in ("gemini-3.5-flash", "gemini-embedding-2"):
        assert pricing.is_free({"model": model, "keyPool": "gemini"}, table)


# ---------------------------------------------------------------- CLI 和接口平级

def test_cli_row_records_model_name_and_shows_free(monkeypatch):
    from link_brain import text_stream
    monkeypatch.setattr(text_stream, "cli_call", lambda *a, **k: {"status": "ok", "text": "好"})
    got = text_stream.call("写概要", "正文", {"mode": "cli", "preset": "opencode"}, cap="summaryAI", feature="summary")
    assert got["status"] == "ok"
    row = usage.load(1)[-1]
    assert row["p"] == "cli" and row["m"] == "opencode" and row["f"] == "summary"
    assert usage.cost_of(row) == 0.0
    shown = ai_routes._entry({"mode": "cli", "command": "claude -p --model sonnet"}, "Claude", pricing.table(), None, 100, "篇")
    assert shown["free"] is True and shown["price"] == "免费（本机）" and shown["model"] == "claude sonnet"
    assert ai_routes._label({"mode": "cli", "command": "opencode run --pure"}) == "本机 opencode"


def test_summary_can_pick_opencode_preset():
    settings = {**ai_config.DEFAULTS, "summaryAI": {"mode": "cli", "preset": "opencode"}}
    cfg = providers.resolve("summaryAI", settings)
    assert cfg and cfg["mode"] == "cli" and cfg["command"] == ai_config.cli_preset("opencode")["command"]
    table = ai_config.ai_table(settings)
    assert "cli" in table["caps"]["summaryAI"]["modes"] and "http" in table["caps"]["summaryAI"]["modes"]
    assert "opencode" in [c.get("preset") for c in table["cli"]]
    # 她自己在问收藏下拉里加的命令行，也列进去给概要选
    mine = ai_config.ai_table({"models": [{"name": "OpenCode DS", "mode": "cli", "command": "opencode run -m x/y"}]})
    assert any(c["command"] == "opencode run -m x/y" for c in mine["cli"])


def test_default_cli_models_only_carry_presets():
    for m in ai_config.DEFAULTS["models"]:
        if m.get("mode") == "cli":
            assert "command" not in m and ai_config.cli_preset(m["preset"])
    cfg, why = providers.finalize("textAI", {"mode": "cli", "preset": "claude"})
    assert cfg and "--strict-mcp-config" in cfg["command"], why


# ---------------------------------------------------------------- 预算默认只在后端

def test_budget_default_only_in_backend():
    st = budget.status({})
    assert st["daily_yuan"] == budget.DEFAULT_YUAN                              # 设置页显示的就是它
    plugin = Path(__file__).resolve().parents[1] / "obsidian-plugins" / "link-brain-actions"
    for name in ("settings-pages.js", "settings-v6.js"):
        text = (plugin / name).read_text("utf-8")
        assert "daily_yuan ?? 3" not in text and "dailyYuan : 3" not in text, name


# ---------------------------------------------------------------- 夜跑和 providers 拿同一组 key

def _job(tmp_path):
    return Nightly(steps=[], workdir=tmp_path, log_path=tmp_path / "n.log", sleep=lambda s: None, secret_timeout_sec=5)


@pytest.mark.parametrize("how", ["env", "cmd", "file", "file_env_path"])
def test_nightly_and_providers_get_same_gemini_keys(how, monkeypatch, tmp_path):
    conf: dict = {}
    if how == "env":
        monkeypatch.setenv("LWA_GEMINI_KEYS", "a1, a2,a1")
    elif how == "cmd":
        conf["gemini_keys_cmd"] = f'"{PY}" -c "print(\'# 注释\\nc1,c2\')"'
    else:
        keyfile = tmp_path / "keys.txt"
        keyfile.write_text("# 这是注释\nf1\nf2,f3\n", "utf-8")
        if how == "file":
            conf["gemini_keys_file"] = str(keyfile)
        else:
            monkeypatch.setenv("LWA_KEYDIR", str(tmp_path))
            conf["gemini_keys_file"] = "$LWA_KEYDIR/keys.txt"
    monkeypatch.setattr(storage, "user_config", lambda: conf)
    want = {"env": ["a1", "a2"], "cmd": ["c1", "c2"], "file": ["f1", "f2", "f3"], "file_env_path": ["f1", "f2", "f3"]}[how]
    assert providers.pool_keys("gemini") == want
    name, keys = _job(tmp_path).refine_keys()
    assert (name, keys) == ("LWA_GEMINI_KEYS", want)


def test_renamed_env_from_settings_is_used_by_both(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_config, "load", lambda: {"visionAI": {"refineKeysEnv": "MY_GEMINI"}})
    monkeypatch.setattr(storage, "user_config", lambda: {})
    monkeypatch.setenv("MY_GEMINI", "m1,m2")
    monkeypatch.setenv("LWA_GEMINI_KEYS", "wrong-pool")   # 1025 Codex 审：默认名同时设着也只认设置里改的名字
    assert providers.pool_keys("gemini") == ["m1", "m2"]
    assert _job(tmp_path).refine_keys() == ("MY_GEMINI", ["m1", "m2"])


def test_key_cmd_runs_once_per_process(monkeypatch, tmp_path):
    marker = tmp_path / "ran.txt"
    cmd = f'"{PY}" -c "open(r\'{marker}\', \'a\').write(\'x\'); print(\'k1\')"'
    monkeypatch.setattr(storage, "user_config", lambda: {"gemini_keys_cmd": cmd})
    for _ in range(3):
        assert providers.pool_keys("gemini") == ["k1"]
    assert marker.read_text() == "x"


# ---------------------------------------------------------------- 1025 复审补的两条

def test_key_cmd_failure_is_not_rerun_per_call(monkeypatch, tmp_path):
    """取 key 的命令失败（退出非 0 / 超时 / 起不来）也只跑一次：否则 keyPool 的每次 resolve_key、每张备用识图都再跑、再等一次超时。"""
    marker = tmp_path / "ran.txt"
    cmd = f'"{PY}" -c "open(r\'{marker}\', \'a\').write(\'x\'); raise SystemExit(3)"'
    monkeypatch.setattr(storage, "user_config", lambda: {"gemini_keys_cmd": cmd})
    for _ in range(3):
        got = providers.pool_load("gemini")
        assert got["keys"] == [] and got["source"] == "cmd" and "退出 3" in got["error"]
    assert marker.read_text() == "x"
    assert providers.pool_alive("gemini") == [] and marker.read_text() == "x"


def test_dropdown_cli_preset_not_overridden_by_text_ai_command():
    """问收藏下拉选「Codex」（只存 preset）时，哪怕 textAI 自己是另一条命令行，跑的也得是 Codex 的命令。"""
    settings = {**ai_config.DEFAULTS, "textAI": {"mode": "cli", "command": "opencode run --pure"},
                "models": [{"name": "Codex", "mode": "cli", "preset": "codex"}]}
    cfg = providers.finalize("textAI", ai_config.with_model(settings, "Codex")["textAI"])[0]
    assert cfg and cfg["command"] == ai_config.cli_preset("codex")["command"]
    # 反过来：条目自己写了命令，textAI 只存 preset，跑条目的命令
    settings = {**ai_config.DEFAULTS, "textAI": {"mode": "cli", "preset": "claude"},
                "models": [{"name": "OC", "mode": "cli", "command": "opencode run -m x/y"}]}
    cfg = providers.finalize("textAI", ai_config.with_model(settings, "OC")["textAI"])[0]
    assert cfg and cfg["command"].startswith("opencode run -m x/y")


def test_cli_entry_over_http_text_ai_is_logged_by_command_name(monkeypatch):
    """文本 AI 配 deepseek、下拉选 Codex：账本 m、设置页那格、概要取名都按实际命令（codex），不记继承来的 deepseek（1025 Codex 审）。"""
    from link_brain import text_stream
    settings = {**ai_config.DEFAULTS, "textAI": {"mode": "http", "endpoint": "https://api.deepseek.com/chat/completions",
                                                  "model": "deepseek-flash", "apiKey": "k-123456789"}}
    cfg = ai_config.with_model(settings, "Codex")["textAI"]
    assert cfg["mode"] == "cli" and cfg.get("model") == "deepseek-flash"      # 叠出来的配置确实还带着接口模型名
    monkeypatch.setattr(text_stream, "cli_call", lambda *a, **k: {"status": "ok", "text": "好"})
    assert text_stream.call("问", "正文", cfg, cap="textAI", feature="ask")["status"] == "ok"
    row = usage.load(1)[-1]
    assert row["p"] == "cli" and row["m"] == "codex"
    resolved = providers.finalize("textAI", cfg)[0]
    assert ai_routes._entry(resolved, "x", pricing.table(), None, 100, "篇")["model"] == "codex"
    assert ai_routes._label(resolved) == "本机 codex"
    assert usage.model_name({"mode": "http", "model": "deepseek-flash"}) == "deepseek-flash"
