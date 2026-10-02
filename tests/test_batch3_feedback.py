"""第 3 批：用户操作的结果如实反馈（RELEASE-BAR §2「用户点的每一个操作有明确结果」「AI 回答随时可停」）。

覆盖：问答的真实阶段事件、停止（ask → serve worker 协议）、删除逐条结果 + 中途失败也重建目录、回收站页按页头标记找。
全程不联网、不起真 claude / codex。
"""

from __future__ import annotations

import io
import json
import queue
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from link_brain import ask, catalog, remove, serve, storage, text_stream
from tests.test_ask import FAKE_ITEMS


@pytest.fixture
def fake_index(monkeypatch):
    monkeypatch.setattr(ask, "load_items", lambda: [dict(x) for x in FAKE_ITEMS])
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))


# ── 问答：阶段 + 停止 ─────────────────────────────────────────────

def test_answer_reports_real_phases_in_order(fake_index, monkeypatch):
    monkeypatch.setattr(ask, "call_text", lambda *a: {"status": "ok", "text": "dream 实验。[来源1]"})
    phases = []
    r = ask.answer("AI 做梦", on_phase=phases.append)
    assert r["status"] == "ok"
    assert phases[0] == "检索收藏" and phases[-1] == "生成回答"


def test_answer_stopped_mid_generation_returns_cancelled_with_partial(fake_index, monkeypatch):
    monkeypatch.setattr(ask, "call_text", lambda *a: {"status": "cancelled", "text": "写到一半"})
    r = ask.answer("AI 做梦")
    assert r["status"] == "cancelled" and r["markdown"] == "写到一半" and r["sources"]
    assert "delivery" not in r   # 停掉的不当成功回答处理


def test_answer_stopped_before_generation_does_not_call_model(fake_index, monkeypatch):
    monkeypatch.setattr(ask, "call_text", lambda *a: pytest.fail("停了就不该再调模型"))
    ev = threading.Event()
    ev.set()
    token = text_stream.CANCEL.set(ev)
    try:
        r = ask.answer("AI 做梦")
    finally:
        text_stream.CANCEL.reset(token)
    assert r["status"] == "cancelled"


class _Stdin:
    """serve.run 的 stdin：测试往里 put 行，put(None) = EOF。"""

    def __init__(self):
        self.q = queue.Queue()

    def put(self, obj):
        self.q.put(None if obj is None else json.dumps(obj, ensure_ascii=False) + "\n")

    def __iter__(self):
        while True:
            line = self.q.get()
            if line is None:
                return
            yield line


def test_worker_cancel_protocol(monkeypatch):
    """正在答的那条：cancel → 模型调用看到 CANCEL 被 set、回 cancelled；排队中的那条：轮到时直接回 cancelled；之后的照常答。"""
    started = threading.Event()

    def fake_answer(question, history=None, include=None, on_delta=None, model='', on_phase=None):
        on_phase("检索收藏")
        if question == "慢":
            started.set()
            ev = text_stream.CANCEL.get()
            on_delta("半截")
            assert ev is not None and ev.wait(10), "worker 应该把 cancel 递到 text_stream.CANCEL"
            return {"status": "cancelled", "markdown": "半截"}
        return {"status": "ok", "markdown": "答：" + question}

    monkeypatch.setattr(serve.ask, "answer", fake_answer)
    monkeypatch.setattr(serve, "_warm", lambda: None)
    stdin, out = _Stdin(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", out)
    worker = threading.Thread(target=serve.run, args=(SimpleNamespace(),), daemon=True)
    worker.start()
    stdin.put({"id": "1", "question": "慢"})
    stdin.put({"id": "2", "question": "排队后被取消"})
    stdin.put({"id": "3", "question": "正常"})
    assert started.wait(10)
    stdin.put({"id": "2", "type": "cancel"})
    stdin.put({"id": "1", "type": "cancel"})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and out.getvalue().count('"type": "result"') < 3:
        time.sleep(0.05)
    stdin.put(None)
    worker.join(5)
    events = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    results = {e["id"]: e["result"] for e in events if e["type"] == "result"}
    assert results["1"]["status"] == "cancelled" and results["1"]["markdown"] == "半截"
    assert results["2"]["status"] == "cancelled"
    assert results["3"] == {"status": "ok", "markdown": "答：正常"}
    assert {"id": "1", "type": "phase", "text": "检索收藏"} in events
    assert not any(e["id"] == "2" and e["type"] == "start" for e in events), "排队中被取消的不该开始作答"


# ── 删除：逐条结果、退出码与 JSON 一致、中途失败也重建目录 ──────────────

def test_delete_one_failure_does_not_swallow_others_and_catalog_still_rebuilds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    remove.index_mod.connect().close()
    calls = []

    def fake_delete(conn, item_id):
        if item_id == "bad":
            raise PermissionError("[WinError 32] 另一个程序正在使用此文件")
        return {"item_id": item_id, "status": "deleted", "note": item_id + ".md"}

    monkeypatch.setattr(remove, "delete_item", fake_delete)
    monkeypatch.setattr(catalog, "build", lambda *a, **k: calls.append("build"))
    code = remove.run(SimpleNamespace(command="delete", item_ids=["a", "bad", "c"]))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 1 and out["ok"] is False and out["deleted"] == 2
    assert [r["status"] for r in out["results"]] == ["deleted", "failed", "deleted"]
    assert "正在使用" in out["results"][1]["error"]
    assert out["message"].startswith("已删 2 篇；1 篇没删掉：")
    assert calls == ["build"]


def test_delete_all_ok_exits_zero_with_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    remove.index_mod.connect().close()
    monkeypatch.setattr(remove, "delete_item", lambda conn, i: {"item_id": i, "status": "deleted"})
    monkeypatch.setattr(catalog, "build", lambda *a, **k: None)
    assert remove.run(SimpleNamespace(command="delete", item_ids=["a"])) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["message"] == "已删 1 篇"


def test_delete_crash_before_any_result_still_rebuilds_catalog(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    calls = []
    monkeypatch.setattr(remove, "delete_items", lambda ids: (_ for _ in ()).throw(RuntimeError("库打不开")))
    monkeypatch.setattr(catalog, "build", lambda *a, **k: calls.append("build"))
    with pytest.raises(RuntimeError):
        remove.run(SimpleNamespace(command="delete", item_ids=["a"]))
    assert calls == ["build"]


# ── 回收站页：页头 lb-page: trash，改名后按标记重写 ───────────────────

def test_trash_page_has_marker_and_follows_rename(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    remove.index_mod.connect().close()
    remove.publish_trash(tmp_path)
    page = tmp_path / "回收站.md"
    assert page.read_text(encoding="utf-8").startswith("---\nlb-page: trash\n---\n")
    page.rename(tmp_path / "我的回收站.md")
    remove.publish_trash(tmp_path)
    assert not (tmp_path / "回收站.md").exists(), "改名后不该再冒出一份「回收站.md」"
    assert "lb-page: trash" in (tmp_path / "我的回收站.md").read_text(encoding="utf-8")


def test_old_trash_page_without_marker_is_recognised(tmp_path):
    (tmp_path / "旧回收站.md").write_text("# 回收站\n\n```dataviewjs\nread('_archive/trash-data.json')\n```\n", encoding="utf-8")
    assert catalog.library_pages(tmp_path)["trash"] == "旧回收站.md"
