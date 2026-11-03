"""1103 懒人安装收敛（docs/PLAN-INSTALL-1103.md）：
目录先有；每步按到它时最新的选择；语音组件不进自动安装；每装完一项报一条结果；
没登录小红书不算失败（见 test_setup_run_1009）；check 只答装没装；同步中边存边建目录；目录待重建记号并发不丢。"""
from __future__ import annotations

import json

from link_brain import ai_config, catalog, comment_fill, storage
from link_brain.setup import components, pipeline


def _settings(selected, **extra):
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(p, {"setup": {"selected": selected, "aiSynced": True}, **extra})


def _run(monkeypatch, *, child=None, check=None, install=None):
    monkeypatch.setattr(components, "check", check or (lambda ids: {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]}))
    if install:
        monkeypatch.setattr(components, "install", install)
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True, "started": True})
    events = []
    out = pipeline.run(events.append, child=child or (lambda args, **k: (0, False)), account_check=lambda: ("", ""), bili_check=lambda: False)
    return out, events


def test_catalog_first_runs_before_install_and_login(monkeypatch):
    _settings(["core", "reader", "ocr"])
    order = []
    out, events = _run(monkeypatch, child=lambda args, **k: (order.append(args[0]) or (0, False)))
    ids = [s["id"] for s in out["stages"]]
    assert ids[:3] == ["catalog_first", "install", "login"]
    assert order[0] == "catalog"
    first = next(e for e in events if e.get("stage") == "catalog_first" and e.get("state") == "ok")
    assert first["label"] == "生成目录页"


def test_voice_components_never_installed_by_run(monkeypatch):
    _settings(["core", "reader", "ocr", "asr", "capslock"])
    seen = []
    _run(monkeypatch, check=lambda ids: seen.append(list(ids)) or {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]})
    assert seen and all("asr" not in ids and "capslock" not in ids for ids in seen)


def test_each_installed_component_reports_a_result(monkeypatch):
    _settings(["core", "reader", "ocr"])
    check = lambda ids: {"ok": True, "results": [{"item_id": i, "status": "missing" if i in ("reader", "ocr") else "ready", "fix": "auto"} for i in ids]}
    install = lambda cid, emit: {"ok": cid == "reader", "status": "ready" if cid == "reader" else "partial",
                                 "message": "好了" if cid == "reader" else "OCR 模型没下完"}
    out, events = _run(monkeypatch, check=check, install=install)
    results = [e for e in events if e.get("stage") == "install" and e.get("component") and e.get("state") in ("ok", "failed")]
    assert [(e["component"], e["state"], e["status"]) for e in results] == [("reader", "ok", "ready"), ("ocr", "failed", "partial")]
    assert {s["id"]: s["state"] for s in out["stages"]}["install"] == "failed"


def test_selection_is_reread_at_each_step(monkeypatch):
    """边跑边选：同步途中用户打开了 AI，后面补概要 / 建索引那几步按新的选择跑。"""
    _settings(["core", "reader", "ocr"])
    monkeypatch.setattr(pipeline, "_ai_on", lambda sel, cap: "ai_text" in sel)
    calls = []

    def child(args, **k):
        calls.append(args[0])
        if args[0] == "sync-favorites":
            _settings(["core", "reader", "ocr", "ai_text"])
        return 0, False
    out, _ = _run(monkeypatch, child=child)
    assert calls == ["catalog", "sync-favorites", "enrich", "albums", "catalog", "embed"]
    assert out["selected"] == ["core", "reader", "ocr", "ai_text"]


def test_state_file_records_this_runs_vault(monkeypatch):
    _settings(["core", "reader", "ocr"])
    _run(monkeypatch)
    st = json.loads(pipeline.state_path().read_text("utf-8"))
    assert st["vault"] == str(storage.vault_root())


def test_check_answers_installed_not_enabled(monkeypatch):
    """设置里关着 OCR / CapsLock 不算「没装好」——开没开由界面按设置判断。"""
    monkeypatch.setattr(components, "_has", lambda m: True)
    monkeypatch.setattr(components, "_ocr_settings", lambda: ("small", "", "off"))
    monkeypatch.setattr(components.sys, "platform", "linux")
    assert components._ocr()["row"]["status"] == "ready"
    _settings(["core"], voice={"capsLock": False})
    row = components._capslock({"client_exe": "x.exe"})["row"]
    assert row["status"] == "ready"


def test_catalog_tick_builds_every_few_new_notes(monkeypatch):
    from link_brain.sources.xiaohongshu import favorites
    built = []
    monkeypatch.setattr(catalog, "ensure_fresh", lambda wait_s=0: built.append(wait_s) or "built")
    assert [favorites._catalog_tick(n) for n in range(0, 7)] == ["skip", "skip", "skip", "built", "skip", "skip", "built"]
    assert built == [0, 0], "拿不到锁不等（wait_s=0）"


def test_settings_with_bom_are_still_read_and_patched():
    """1103 虚拟机实测：data.json 带 BOM（Windows PowerShell 5 存的）时以前整份读失败、悄悄退回默认——
    选择变回轻量版（多装了读取组件），OCR 装完写不回 modelDir、装完再检查说「模型还没下」。"""
    from link_brain.setup.common import apply_settings_patch
    p = ai_config.data_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"setup": {"selected": ["core", "ocr"]}}).encode("utf-8"))
    assert pipeline.selected() == ["core", "ocr"]
    out = apply_settings_patch({"ocr": {"modelDir": "D:/m"}})
    assert out["written"] is True
    assert ai_config.load()["ocr"]["modelDir"] == "D:/m" and ai_config.load()["setup"]["selected"] == ["core", "ocr"]


def test_dirty_mark_survives_clear_from_an_older_build(tmp_path):
    """建目录开始时看到 seq=1；建的过程中另一边又记了一笔（seq=2）→ 收尾时不删记号，下一次还会重建。"""
    vault = tmp_path / "v"
    catalog.mark_dirty("a", vault)
    seen = catalog.dirty_state(vault)
    catalog.mark_dirty("b", vault)
    catalog._clear_dirty(vault, seen)
    st = catalog.dirty_state(vault)
    assert st is not None and st["seq"] == 2 and st["reasons"] == ["a", "b"]
    catalog._clear_dirty(vault, st)
    assert catalog.dirty_state(vault) is None


# ---------------------------------------------------------------- 1103 虚拟机实测：读取组件刚启动、没登录却报「已登录」
def test_fresh_reader_session_without_login_flag_is_not_logged_in(monkeypatch):
    """读取组件刚拉起时 /login/session 的 logged_in 是空的（还没实测过）。以前落到「能用」→ setup run 没走等扫码、直接同步。
    现在：空 = 不知道 → 深查一次；深查说游客 → NOT_LOGGED_IN；说登录了才放行；查不清 → BUSY。不真起读取组件。"""
    from link_brain.sources.xiaohongshu import accounts as acc
    from link_brain.sources.xiaohongshu import comment_fill as xcf
    monkeypatch.setattr(acc, "ensure_reader", lambda **k: {"state": "idle", "risk_hold": None})
    for deep_state, want in (("guest", "NOT_LOGGED_IN"), ("logged_in", ""), ("unknown", "BUSY")):
        monkeypatch.setattr(xcf, "_deep_check", {"at": None, "state": ""})
        monkeypatch.setattr(acc, "status_report", lambda s=deep_state, **kw: ({}, s))
        assert xcf.account_wait_reason()[0] == want, deep_state


def test_setup_run_waits_for_scan_when_fresh_reader_has_no_login(monkeypatch):
    """同一个场景走 setup run 的真实登录检查（pipeline._account_state）：记 waiting、同步跳过，不去同步。"""
    from link_brain.sources.xiaohongshu import accounts as acc
    from link_brain.sources.xiaohongshu import comment_fill as xcf
    _settings(["core", "reader", "ocr"])
    monkeypatch.setattr(acc, "ensure_reader", lambda **k: {"state": "idle"})
    monkeypatch.setattr(xcf, "_deep_check", {"at": None, "state": ""})
    monkeypatch.setattr(acc, "status_report", lambda **kw: ({}, "guest"))
    monkeypatch.setattr(components, "check", lambda ids: {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True})
    ran = []
    out = pipeline.run(lambda e: None, child=lambda args, **k: (ran.append(args[0]) or (0, False)), bili_check=lambda: False)
    st = {s["id"]: s["state"] for s in out["stages"]}
    assert st["login"] == "waiting" and st["sync"] == "skipped"
    assert "sync-favorites" not in ran


def test_albums_read_on_first_run_after_favorites_cool_down(monkeypatch):
    """1103 作者：小红书专辑第一次就读出来。同步完离读收藏不满 30 分钟 → 先等够（不连读），再读专辑，然后才整理目录。"""
    _settings(["core", "reader", "ocr"])
    monkeypatch.setattr(components, "check", lambda ids: {"ok": True, "results": [{"item_id": i, "status": "ready"} for i in ids]})
    monkeypatch.setattr(comment_fill, "spawn_worker", lambda: {"ok": True})
    order, slept = [], []
    out = pipeline.run(lambda e: None, child=lambda args, **k: (order.append(args[0]) or (0, False)),
                       account_check=lambda: ("", ""), bili_check=lambda: False, albums_wait=lambda: 600, sleep=slept.append)
    assert slept == [600]
    assert order.index("sync-favorites") < order.index("albums") < len(order) - 1 - order[::-1].index("catalog")
    assert {s["id"]: s["state"] for s in out["stages"]}["albums"] == "ok"
    # 没登录：不读专辑、不等
    slept.clear(); order.clear()
    out = pipeline.run(lambda e: None, child=lambda args, **k: (order.append(args[0]) or (0, False)),
                       account_check=lambda: ("NOT_LOGGED_IN", ""), bili_check=lambda: False, albums_wait=lambda: 600, sleep=slept.append)
    assert "albums" not in order and slept == []
    assert {s["id"]: s["state"] for s in out["stages"]}["albums"] == "skipped"


# ---------------------------------------------------------------- 1103：后端只写插件认得的页面块写法（作者本机：后端换了写法、插件还是旧的）
def test_page_block_mode_follows_what_the_plugin_declares(monkeypatch):
    monkeypatch.delenv(catalog.PAGE_BLOCK_ENV, raising=False)
    p = ai_config.data_json_path()
    if p.exists():
        p.unlink()
    assert catalog.page_block_mode() == "lb-page", "没有插件设置（纯命令行）：默认新写法"
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(p, {"setup": {}})
    assert catalog.page_block_mode() == "dataviewjs", "有设置却没声明 = 旧插件：只写它认得的旧写法"
    storage.write_json(p, {"pageFormats": ["lb-page", "dataviewjs"]})
    assert catalog.page_block_mode() == "lb-page"
    storage.write_json(p, {"pageFormats": ["dataviewjs", "lb-page"], "pageBlock": "dataviewjs"})
    assert catalog.page_block_mode() == "dataviewjs", "设置里选了旧写法、插件也认：照办"
    storage.write_json(p, {"pageFormats": ["dataviewjs"], "pageBlock": "lb-page"})
    assert catalog.page_block_mode() == "dataviewjs", "设置要新写法、插件却不认：不写"
    monkeypatch.setenv(catalog.PAGE_BLOCK_ENV, "lb-page")
    assert catalog.page_block_mode() == "lb-page", "环境变量显式指定：照办"
    # 批注块跟着走：旧插件那份 data.json 下渲染出的就是 dataviewjs
    monkeypatch.delenv(catalog.PAGE_BLOCK_ENV)
    storage.write_json(p, {"setup": {}})
    from link_brain import render
    assert render.annotate_block("xhs-x", "_archive/xiaohongshu/x/notes.json").startswith("```dataviewjs")
