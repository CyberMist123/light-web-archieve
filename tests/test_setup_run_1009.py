"""1009 她：装好插件 → 填 API（可选）→ 点一次「一键装好 / 跑完」→ 同步、OCR / 识图、概要、目录、索引一口气跑完；
不填 API 也一口气跑完轻量版。`setup run` 的步骤编排（子进程用替身，不起真进程、不碰号）。"""

from __future__ import annotations

import json

from link_brain import ai_config, comment_fill, storage
from link_brain.setup import components, pipeline


def _settings(selected, **extra):
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(p, {"setup": {"selected": selected, "aiSynced": True}, **extra})


def _fake_env(monkeypatch, *, account=("", ""), rc=None):
    calls = []

    def child(args, *, timeout_min, on_line, env_extra=None):
        calls.append(list(args))
        on_line(f"[fake] {args[0]} 跑着")
        return (rc or {}).get(args[0], 0), False
    monkeypatch.setattr(components, "check", lambda ids: {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    events = []
    out = pipeline.run(events.append, child=child, account_check=lambda: account)
    return out, calls, events


def test_light_mode_runs_sync_catalog_and_hands_comments_to_background(monkeypatch):
    _settings(["core", "reader", "dataview", "ocr"])
    out, calls, events = _fake_env(monkeypatch)
    assert out["ok"] is True and "轻量版" in out["message"]
    assert [c[0] for c in calls] == ["sync-favorites", "catalog"]  # 没开 AI：不跑概要 / 索引
    assert calls[0] == ["sync-favorites", "--limit", "0", "--extract"]
    st = {s["id"]: s["state"] for s in out["stages"]}
    assert st == {"install": "ok", "login": "ok", "sync": "ok", "enrich": "skipped", "catalog": "ok", "embed": "skipped",
                  "comments": "ok"}
    assert any(e.get("type") == "progress" and e.get("stage") == "sync" and "跑着" in e.get("text", "") for e in events)


def test_ai_selected_and_configured_adds_enrich_and_embed(monkeypatch):
    _settings(["core", "reader", "dataview", "ocr", "ai_text", "ai_vision"])
    monkeypatch.setattr(pipeline, "_ai_on", lambda sel, cap: True)
    out, calls, _ = _fake_env(monkeypatch)
    assert [c[0] for c in calls] == ["sync-favorites", "enrich", "catalog", "embed"]
    assert out["ok"] is True and "轻量版" not in out["message"]


def test_not_logged_in_skips_account_steps_but_still_tidies_and_says_what_to_do(monkeypatch):
    _settings(["core", "reader", "dataview", "ocr"])
    out, calls, _ = _fake_env(monkeypatch, account=("NOT_LOGGED_IN", "小红书掉登录了：扫码登录"))
    assert [c[0] for c in calls] == ["catalog"]
    assert out["ok"] is False and out["code"] == "NEEDS_HUMAN" and "扫码登录" in out["message"]
    st = {s["id"]: s["state"] for s in out["stages"]}
    assert st["sync"] == "skipped" and st["comments"] == "skipped" and st["login"] == "failed"


def test_failed_step_is_reported_plainly_and_the_rest_still_runs(monkeypatch):
    _settings(["core", "reader", "dataview", "ocr"])
    out, calls, _ = _fake_env(monkeypatch, rc={"sync-favorites": 1})
    assert [c[0] for c in calls] == ["sync-favorites", "catalog"]
    assert out["ok"] is False and "同步收藏" in out["message"]


def test_cli_streams_events_then_result(monkeypatch, capsys):
    from link_brain import cli
    _settings(["core", "reader", "dataview", "ocr"])
    monkeypatch.setattr(pipeline, "run", lambda emit: (emit({"type": "progress", "stage": "sync", "state": "running"}) or
                                                       {"type": "result", "ok": True, "code": "", "message": "都跑完了", "stages": []}))
    assert cli.main(["setup", "run"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    assert lines[0]["type"] == "progress" and lines[-1]["type"] == "result" and lines[-1]["message"] == "都跑完了"
