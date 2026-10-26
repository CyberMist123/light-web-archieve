"""1026 她：追问 = 接着这段聊，不重新检索（mode=chat）——带最近几轮对话直接问模型，可用模型自己的知识。"""
from link_brain import ask


def test_chat_follow_skips_retrieval_and_sends_history(monkeypatch):
    calls = []
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: calls.append((p, t)) or {"status": "ok", "text": "接着说。[来源1]"})
    monkeypatch.setattr(ask, "_text_ai_missing", lambda s: "")
    monkeypatch.setattr(ask, "load_items", lambda: (_ for _ in ()).throw(AssertionError("追问不该检索")))
    history = [{"role": "user", "content": "好奇"}, {"role": "assistant", "content": "先看 Topic Pool。[来源1]"}]
    r = ask.answer("那怎么做？", history, mode="chat")
    assert r["status"] == "ok" and r["mode"] == "chat" and r["markdown"] == "接着说。[来源1]" and r["sources"] == []
    prompt, text = calls[0]
    assert "自己的知识" in prompt and "来源导读" in prompt
    assert "先看 Topic Pool" in text and text.endswith("她这一问：那怎么做？")


def test_chat_follow_reports_missing_model(monkeypatch):
    monkeypatch.setattr(ask, "_text_ai_missing", lambda s: "文本 AI 没配置")
    r = ask.answer("那怎么做？", [], mode="chat")
    assert r["status"] == "error" and r["error_kind"] == "not_configured" and r["model_called"] is False
