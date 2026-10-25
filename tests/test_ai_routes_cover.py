"""ai_routes 的补充用例（现有 test_console_1018.py 只盖了「有 key 的正常形状」一条）。

只断言 link_brain/ai_routes.py 里能直接读出的行为；不出网，账本 / 健康状态都落在
conftest 指到的 tmp LINK_BRAIN_HOME 里。
"""

from __future__ import annotations

from link_brain import ai_health, ai_routes as ar, pricing, providers
from tests.test_console_1018 import PAID


def test_state_matrix():
    assert ar._state({}, "textAI", False, False, []) == ("off", "关着")
    assert ar._state({}, "textAI", True, False, []) == ("off", "没配好")
    assert ar._state({}, "textAI", True, False, [{}]) == ("ok", "正常")
    assert ar._state({"textAI": {"code": "TRANSIENT.BUDGET"}}, "textAI", True, False, [{}]) == \
        ("budget", "今天到上限，只用免费的")
    # budget_over 时任何 TRANSIENT 都按「到上限」说
    assert ar._state({"textAI": {"code": "TRANSIENT.NETWORK"}}, "textAI", True, True, [{}])[0] == "budget"
    assert ar._state({"textAI": {"code": "TRANSIENT.NETWORK"}}, "textAI", True, False, [{}]) == \
        ("waiting", "暂时不通，好了自动补")
    assert ar._state({"textAI": {"code": "PERMANENT.RATE", "switched_to": "备用A"}}, "textAI", True, False, [{}]) == \
        ("backup", "主用的暂时不行，备用A 顶着")
    assert ar._state({"textAI": {"code": "NEEDS_HUMAN.AUTH_FAILED", "detail": "key 被拒"}}, "textAI", True, False, [{}]) == \
        ("down", "停了：key 被拒")
    assert ar._state({"textAI": {"code": "NEEDS_HUMAN.AUTH_FAILED"}}, "textAI", True, False, [{}]) == \
        ("down", "停了：key 用不了")


def test_collapse_pool_merges_adjacent_and_keeps_gap():
    chain = [{"label": "Google gemini（免费 key 1）", "key": "g1"},
             {"label": "Google gemini（免费 key 2）", "key": "g2"},
             {"label": "DeepSeek", "key": "d"},
             {"label": "Google gemini（免费 key 3）", "key": "g3"}]
    out = ar._collapse_pool(chain)
    assert [c["label"] for c in out] == ["Gemini 免费（2 把 key）", "DeepSeek", "Gemini 免费"]
    assert out[0]["key"] == "2 把轮流用" and out[2]["key"] == "1 把轮流用"
    assert all("_pool" not in c and "_n" not in c for c in out)
    assert chain[0]["label"] == "Google gemini（免费 key 1）"       # 原链不被改


def test_avg_tokens_filters_and_averages():
    rows = [{"f": "ask", "ok": True, "in": 100, "out": 50},
            {"f": "ask", "ok": True, "in": 300, "out": 10},
            {"f": "ask", "ok": False, "in": 999, "out": 999},    # 失败的不算
            {"f": "ask", "ok": True, "in": 0, "out": 5},         # in=0 的不算
            {"f": "vision", "ok": True, "in": 5, "out": 5}]      # 别的功能不算
    assert ar._avg_tokens(rows, "ask") == (200.0, 30.0)
    assert ar._avg_tokens(rows, "embed") is None
    assert ar._avg_tokens([], "ask") is None


def test_fallback_tokens_branches(monkeypatch):
    from link_brain.setup import estimate
    monkeypatch.setattr(estimate, "library_stats",
                        lambda: {"summary_in": 1200, "summary_out": 300, "vision_in": 900})
    assert ar._fallback_tokens("summary") == (1200.0, 300.0)
    assert ar._fallback_tokens("refine") == (900.0, 0.0)          # vision_out 缺 → 0
    assert ar._fallback_tokens("ask") is None                     # ask 没有兜底
    monkeypatch.setattr(estimate, "library_stats", lambda: {})
    assert ar._fallback_tokens("summary") is None
    def boom():
        raise RuntimeError("炸了")
    monkeypatch.setattr(estimate, "library_stats", boom)
    assert ar._fallback_tokens("summary") is None                 # 估算炸了 → 没有兜底


def test_label_three_shapes():
    assert ar._label({"label": "我的链"}) == "我的链"
    assert ar._label({"mode": "cli", "model": "codex"}) == "本机 codex"
    cfg = dict(PAID)
    assert ar._label(cfg) == f"{ai_health.provider_name(cfg)} qwen3.8-max".strip()


def test_entry_cli_free_and_unpriced():
    table = pricing.table()
    out = ar._entry({"mode": "cli", "model": "codex"}, "问收藏", table, (100.0, 50.0), 1, "次")
    assert out["provider"] == "cli" and out["free"] is True
    assert out["price"] == "免费（本机）" and out["key"] == "本机已登录的账号"
    out = ar._entry({"endpoint": "https://example.com/v1/chat/completions", "model": "查无此模型", "apiKey": "k"},
                    "识图", table, None, 100, "张")
    assert out["free"] is False and out["unpriced"] is True and out["price"] == "—，未计价"


def test_entry_key_pool_and_price_formats(monkeypatch):
    monkeypatch.setattr(providers, "pool_keys", lambda name: ["a", "b", "c"])
    table = pricing.table()
    cfg = {"endpoint": PAID["endpoint"], "model": "qwen3.8-max", "keyPool": "paid-pool"}
    out = ar._entry(cfg, "概要 · 打标签", table, (100.0, 50.0), 100, "篇")
    assert out["key"] == "3 把轮流用" and out["free"] is False
    assert out["price"].startswith("约 ¥") and isinstance(out["yuan"], float)
    out = ar._entry(dict(cfg), "概要 · 打标签", table, None, 100, "篇")
    assert out["price"] == "按用量" and "yuan" not in out


def test_routes_defaults_when_nothing_configured(monkeypatch):
    out = ar.routes({})
    fids = [f["id"] for f in out["features"]]
    assert fids == ["ask", "summary", "vision", "refine", "embed"]
    assert all(f["on"] is True for f in out["features"])           # 没选过功能 = 全算开着
    assert all(f["state"] == "off" and f["state_text"] == "没配好" for f in out["features"])
    assert out["features"][0]["choices"] == [] and out["features"][0]["active"] == ""
    assert "budget" in out


def test_routes_fail_open_when_chains_explode(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("配置读不出来")
    monkeypatch.setattr(providers, "resolve", boom)
    out = ar.routes({})
    assert out["features"] == [] and out["error"].startswith("读不出各功能的配置")
