"""r4-d1 补测：粘 key 认提供商（_accepts 打桩，不出网；价格表只读包内默认 + tmp 覆盖）。"""
from __future__ import annotations

import json

from link_brain import keyprobe, pricing


def test_guess_orders_by_prefix():
    assert keyprobe.guess("AIzaSyABC-xyz") == ["google"]
    assert keyprobe.guess(" AIzaSy padded ") == ["google"]  # 先 strip 再看前缀
    assert keyprobe.guess("sk-ant-api3-x") == []  # Anthropic 不支持，直接不试
    assert keyprobe.guess("sk-1234567890") == ["deepseek", "aliyun", "openai"]
    assert keyprobe.guess("") == ["deepseek", "aliyun", "openai"]  # 没前缀线索就按默认顺序全试


def test_detect_rejects_bad_and_unsupported_keys(monkeypatch):
    called = []
    monkeypatch.setattr(keyprobe, "_accepts", lambda p, k, timeout=8.0: called.append(p) or True)
    assert keyprobe.detect("")["code"] == "SKIPPED.BAD_INPUT"
    assert keyprobe.detect("   ")["code"] == "SKIPPED.BAD_INPUT"
    assert keyprobe.detect("abc def")["code"] == "SKIPPED.BAD_INPUT"  # 中间有空格不像一把 key
    r = keyprobe.detect("sk-ant-api3-xyz")
    assert r["code"] == "SKIPPED.UNSUPPORTED" and r["ok"] is False and "Anthropic" in r["message"]
    assert called == []  # 这三类都不出网问


def test_detect_reports_auth_failed_when_nobody_accepts(monkeypatch):
    monkeypatch.setattr(keyprobe, "_accepts", lambda p, k, timeout=8.0: False)
    r = keyprobe.detect("sk-plainkey")
    assert r["ok"] is False and r["code"] == "NEEDS_HUMAN.AUTH_FAILED"
    for label in ("DeepSeek", "通义千问", "OpenAI"):
        assert label in r["message"]  # 消息里列出试过的三家


def test_detect_picks_first_accepting_in_guess_order(monkeypatch):
    seen = []

    def fake(provider, key, timeout=8.0):
        seen.append((provider, key))
        return provider == "aliyun"

    monkeypatch.setattr(keyprobe, "_accepts", fake)
    r = keyprobe.detect("sk-whatever")
    assert r["ok"] is True and r["provider"] == "aliyun" and r["name"] == "通义千问"
    assert seen[0] == ("deepseek", "sk-whatever")  # key 整把原样送去问
    assert r["fills"] == keyprobe.fills_for("aliyun")
    assert r["key_url"].startswith("https://")  # 从价格表 providers 段带出

    # AIza 前缀只问 Google 一家
    seen.clear()
    monkeypatch.setattr(keyprobe, "_accepts", lambda p, k, timeout=8.0: seen.append(p) or True)
    r2 = keyprobe.detect("AIzaSyXYZ")
    assert r2["provider"] == "google" and seen == ["google"]


def test_fills_for_default_table(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))  # 没有 pricing.json 覆盖
    t = keyprobe._pricing()
    prov = t["providers"]

    ds = keyprobe.fills_for("deepseek")
    assert set(ds) == {"textAI"}  # 推荐就是 DeepSeek 的模型；概要跟问收藏走，summaryAI 被 pop 掉
    assert ds["textAI"]["endpoint"] == prov["DeepSeek"]["endpoint"]

    ali = keyprobe.fills_for("aliyun")
    assert set(ali) == {"textAI", "visionAI", "embedAI"}
    assert ali["embedAI"] == keyprobe.EMBED["aliyun"]  # 只有 aliyun 给 embed 填法
    assert ali["textAI"]["endpoint"] == prov["通义千问"]["endpoint"]

    for pid in ("openai", "google"):
        f = keyprobe.fills_for(pid)
        assert set(f) == {"textAI", "visionAI"} and "summaryAI" not in f
        assert all(f[c]["endpoint"] == prov[keyprobe.PROVIDERS[pid][0]]["endpoint"] for c in f)


def test_fills_for_reads_user_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    t = pricing.table()
    # 覆盖：问收藏的推荐换成千问的模型（深合并只动这一个键）
    qwen_ask = next(m for m, info in t["models"].items()
                    if info.get("provider") == "通义千问" and m not in ("qwen3.8-flash",))
    (tmp_path / "pricing.json").write_text(json.dumps({"recommended": {"ask": qwen_ask}}), encoding="utf-8")
    f = keyprobe.fills_for("aliyun")
    assert f["textAI"]["model"] == (t["models"][qwen_ask].get("api_model") or qwen_ask)
    # 覆盖同样作用于别家：问收藏换成千问后 DeepSeek 填不了 textAI，
    # 但概要的推荐没被动、还是 deepseek-flash，于是单独给 summaryAI（概要只在问收藏填不了时才单独填）
    assert keyprobe.fills_for("deepseek") == {"summaryAI": {"endpoint": "https://api.deepseek.com/chat/completions",
                                                            "model": "deepseek-flash"}}
