"""个人 Wiki 10-31 整理（后端）：新页排进文件夹顺序、最近删除 / 找回、pwiki 轻入口（不载整套 cli）、让 AI 改（只回建议）。

conftest 已把 vault 指到 tmp；这里只用合成内容，不碰真库；AI 一律 monkeypatch 掉，不联网。
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from link_brain import personal_wiki as pw, storage, wiki_ai

ROOT = Path(__file__).resolve().parents[1]


def run_cli(argv, monkeypatch, capsys, stdin=""):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8"))
    code = pw.main_fast(argv)
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


def test_new_page_in_folder_goes_to_end_of_folder_order():
    t = pw.create_page("旅行", role="topic")["page"]
    a = pw.create_page("住宿", folder=t["index_tag"])["page"]
    b = pw.create_page("交通", folder=t["index_tag"])["page"]
    order = pw.get_page(t["id"])["order"]
    assert order == [a["id"], b["id"]]   # 以前不进 order：按修改时间排，改一下内容就换位置


def test_trash_lists_newest_first_and_undelete_puts_page_back():
    p = pw.create_page("京都", body="种草。")["page"]
    q = pw.create_page("大阪", body="吃。")["page"]
    pw.delete_page(p["id"])
    pw.delete_page(q["id"])
    rows = pw.list_trash()
    assert [r["title"] for r in rows] == ["大阪", "京都"] and rows[0]["id"] == q["id"] and rows[0]["at"]
    res = pw.undelete(rows[1]["name"])
    assert res["page"]["id"] == p["id"] and res["page"]["body"].startswith("种草")
    assert pw.get_page(p["id"])["title"] == "京都"
    assert [r["title"] for r in pw.list_trash()] == ["大阪"]
    assert pw.history(p["id"])[0]["kind"] == "restore"   # 找回也记一版


def test_undelete_when_title_or_id_taken_does_not_clobber():
    p = pw.create_page("京都", body="旧的。")["page"]
    pw.delete_page(p["id"])
    pw.create_page("京都", body="新的。")
    name = pw.list_trash()[0]["name"]
    res = pw.undelete(name)
    assert res["page"]["title"] == "京都（找回）"
    assert {x["title"] for x in pw.list_pages()} == {"京都", "京都（找回）"}
    with pytest.raises(pw.WikiError) as e:
        pw.undelete(name)
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(pw.WikiError) as e:
        pw.undelete("../x.md")
    assert e.value.code == "BAD_ARGS"


def test_cli_trash_and_undelete(monkeypatch, capsys):
    p = pw.create_page("京都")["page"]
    pw.delete_page(p["id"])
    code, j = run_cli(["trash"], monkeypatch, capsys)
    assert code == 0 and j["ok"] and j["pages"][0]["title"] == "京都"
    code, j = run_cli(["undelete", j["pages"][0]["name"]], monkeypatch, capsys)
    assert code == 0 and j["message"] == "已找回《京都》"


def test_fast_entry_does_not_import_the_whole_cli():
    """pwiki 每次保存都起一次 Python：轻入口只载 personal_wiki（以前整套 cli 连小红书 adapter / httpx 一起载，1.5 秒）。"""
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8", "LINK_BRAIN_VAULT": str(storage.vault_root())}   # 钉在测试库
    code = ("import sys, runpy; sys.argv = ['link_brain', 'pwiki', 'list'];\n"
            "try:\n    runpy.run_module('link_brain', run_name='__main__')\nexcept SystemExit:\n    pass\n"
            "bad = [m for m in ('link_brain.cli', 'link_brain.read', 'httpx') if m in sys.modules]\n"
            "print('LOADED', bad)")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    lines = r.stdout.strip().splitlines()
    assert json.loads(lines[-2])["ok"] is True, r.stdout + r.stderr
    assert lines[-1] == "LOADED []", lines[-1]


def test_fast_entry_unexpected_error_still_prints_one_json_line(monkeypatch, capsys):
    monkeypatch.setattr(pw, "list_pages", lambda: (_ for _ in ()).throw(RuntimeError("坏了")))
    code, j = run_cli(["list"], monkeypatch, capsys)
    assert code == 1 and j["ok"] is False and j["code"] == "TRANSIENT.STEP_CRASHED" and "坏了" in j["message"]


# ── 让 AI 改 ──────────────────────────────────────────────────────────
@pytest.fixture()
def fake_ai(monkeypatch):
    from link_brain import indextree, text_stream
    seen = {}
    monkeypatch.setattr(indextree, "text_ai", lambda: ({"mode": "cli", "model": "demo-model", "command": "demo"}, ""))

    def call(instruction, text, cfg, on_delta=None, **kw):
        seen.update(instruction=instruction, text=text, cfg=cfg, kw=kw)
        return {"status": "ok", "text": seen.get("reply", "改好了。")}
    monkeypatch.setattr(text_stream, "call", call)
    return seen


def write_catalog(items):
    d = storage.vault_root() / storage.ARCHIVE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "catalog-data.json").write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")


def test_ai_block_prompt_has_rules_task_context_and_returns_suggestion_only(fake_ai):
    p = pw.create_page("住宿偏好", body="为什么记：每次都从头翻。\n\n- [示例](lwa:xhs-a1) — 喜欢")["page"]
    before = pw.get_page(p["id"])["hash"]
    write_catalog([{"id": "xhs-a1", "title": "示例", "summary": "几家店", "search_fields": {"body": "咖啡 地图"}}])
    fake_ai["reply"] = "```\n为什么记：订房前总要从头翻收藏。\n```"
    res = wiki_ai.rewrite({"id": p["id"], "scope": "block", "text": "为什么记：每次都从头翻。", "preset": "polish", "instruction": "语气轻一点"})
    assert res["text"] == "为什么记：订房前总要从头翻收藏。"   # 包了代码块也剥掉
    assert res["model"] == "demo-model" and res["lost_cites"] == []
    ins = fake_ai["instruction"]
    assert "只输出改好的 Markdown 本身" in ins and "[标题](lwa:编号)" in ins   # 规矩
    assert "润色" in ins and "语气轻一点" in ins                              # 现成说法 + 她自己说的
    assert "《住宿偏好》" in ins and "整页" in ins                           # 上下文
    assert "为什么记：每次都从头翻。" in fake_ai["text"]
    assert fake_ai["cfg"]["noThinking"] is True and fake_ai["kw"].get("feature") == "other"
    assert pw.get_page(p["id"])["hash"] == before                             # 不写盘


def test_ai_page_from_cites_gets_materials_and_reports_lost_cites(fake_ai):
    body = "## 参考\n- [示例](lwa:xhs-a1) — 喜欢\n- [短的](lwa:b2)"
    p = pw.create_page("住宿偏好", body=body)["page"]
    write_catalog([{"id": "xhs-a1", "title": "示例", "summary": "几家店"}, {"id": "bili-b2", "title": "短 id 那篇", "summary": "视频"}])
    fake_ai["reply"] = "## 参考\n- 只剩一条 [示例](lwa:xhs-a1)"
    res = wiki_ai.rewrite({"id": p["id"], "scope": "page", "text": body, "preset": "from_cites"})
    assert "[示例](lwa:xhs-a1)：几家店" in fake_ai["instruction"]
    assert "[短 id 那篇](lwa:b2)：视频" in fake_ai["instruction"]   # 短 id 也认
    assert res["lost_cites"] == ["b2"]


def test_ai_errors_are_plain_words(fake_ai, monkeypatch):
    from link_brain import indextree, text_stream
    p = pw.create_page("页")["page"]
    with pytest.raises(pw.WikiError) as e:
        wiki_ai.rewrite({"id": p["id"], "scope": "block", "text": "x"})
    assert e.value.code == "BAD_ARGS" and "怎么改" in str(e.value)
    with pytest.raises(pw.WikiError) as e:
        wiki_ai.rewrite({"id": p["id"], "scope": "block", "text": "  ", "preset": "polish"})
    assert "空的" in str(e.value)
    monkeypatch.setattr(indextree, "text_ai", lambda: (None, "文本 AI 没配"))
    with pytest.raises(pw.WikiError) as e:
        wiki_ai.rewrite({"id": p["id"], "scope": "block", "text": "x", "preset": "fix"})
    assert e.value.code == "NOT_CONFIGURED" and "文本 AI 没配" in str(e.value)
    monkeypatch.setattr(indextree, "text_ai", lambda: ({"mode": "cli"}, ""))
    monkeypatch.setattr(text_stream, "call", lambda *a, **k: {"status": "failed", "code": "TRANSIENT.TIMEOUT", "error": "超时"})
    with pytest.raises(pw.WikiError) as e:
        wiki_ai.rewrite({"id": p["id"], "scope": "page", "text": "x", "preset": "draft"})
    assert e.value.code == "TRANSIENT.TIMEOUT" and "超时" in str(e.value)


def test_cli_ai_reads_stdin_and_never_writes(fake_ai, monkeypatch, capsys):
    p = pw.create_page("页", body="原文。")["page"]
    h0 = pw.get_page(p["id"])["hash"]
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({"id": p["id"], "scope": "block", "text": "原文。", "preset": "fix"}).encode("utf-8")), encoding="utf-8"))
    code = wiki_ai.main([])
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and j["ok"] and j["text"] == "改好了。" and j["message"] == "AI 改好了，看过再用"
    assert pw.get_page(p["id"])["hash"] == h0


def test_presets_match_the_page():
    """页面上那排按钮（wiki-view.js AI_PRESETS）和这里 PRESETS 同一套 key、同一套字。"""
    js = (ROOT / "link_brain" / "assets" / "wiki-view.js").read_text(encoding="utf-8")
    for scope, keys in (("block", wiki_ai.BLOCK_PRESETS), ("page", wiki_ai.PAGE_PRESETS)):
        expect = ", ".join(f"['{k}', '{wiki_ai.PRESETS[k][0]}']" for k in keys)
        assert f"{scope}: [{expect}]" in js, scope
