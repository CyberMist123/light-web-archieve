"""1001 审计 C-2 / ui-1：不可信文本 → Markdown 清洗。

规则用例与插件 JS 版共用 tests/fixtures/mdsafe_cases.json（node tests/test_mdsafe.cjs）。
端到端：走生产入口（ingest → render 的 agent.md、pdf2md 的附件全文、ask.answer、导出包），
断言落盘 / 返回的 Markdown 里不再有 Dataview 会执行的形态。
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from link_brain import ask, export_bundle, mdsafe, pdftext, storage
from link_brain import attachments as attachments_mod

CASES = json.loads((Path(__file__).parent / "fixtures" / "mdsafe_cases.json").read_text(encoding="utf-8"))

DVJS = "```dataviewjs\nrequire('child_process').exec('calc')\n```"
INLINE = "`$=require('fs').readdirSync('/')`"
INLINE_DQL = "`= this.file.name`"


def executable_shapes(md: str) -> list[str]:
    """Dataview 在本库设置下会执行的形态（围栏语言名 / <code> 文字以 = 或 $= 开头）。"""
    hits = []
    for m in re.finditer(r"(`{3,}|~{3,})([^\n`]*)", md):
        word = m.group(2).strip().strip("{}.").split(" ")[0].lower()
        if word in {"dataview", "dataviewjs"}:
            hits.append(m.group(0))
    for m in re.finditer(r"(?<!`)(`+)([^`]+?)\1(?!`)", md):  # 行内代码
        if m.group(2).strip().startswith(("=", "$=")):
            hits.append(m.group(0))
    for m in re.finditer(r"(?m)^[ \t>]*(\$?=.*)$", md):  # 代码块内容（inlineQueriesInCodeblocks=true）
        hits.append(m.group(1))
    hits += re.findall(r"(?i)<code[\s>/]", md)
    return hits


def test_shared_cases_match_and_are_idempotent():
    for case in CASES:
        out = mdsafe.neutralize(case["input"])
        assert out == case["expected"], case["name"]
        assert mdsafe.neutralize(out) == out, case["name"]
        assert not executable_shapes(out), (case["name"], executable_shapes(out))


def test_checker_sees_the_raw_payloads():
    # 自检：没清洗时检查器确实能抓到，免得上面那条恒真
    for name in ("fence_dataviewjs", "inline_js", "html_code", "codeblock_content_starts_with_prefix"):
        raw = next(c["input"] for c in CASES if c["name"] == name)
        assert executable_shapes(raw), name


def test_plain_text_is_visually_unchanged():
    text = "普通文字 a=b，`code`，```python\nprint(1)\n```\n公式 x = 1"
    assert mdsafe.neutralize(text) == text
    assert mdsafe.neutralize(None) == ""


def test_agent_md_from_real_ingest_path_is_neutralized(tmp_path, monkeypatch):
    from tests.test_render import load_fixture, setup_env, _get_item_id
    from link_brain import cli

    setup_env(tmp_path, monkeypatch)
    raw = load_fixture()
    raw["data"]["note"]["desc"] = "正文教程：\n" + DVJS + "\n行内 " + INLINE
    raw["data"]["comments"]["list"][0]["content"] = "评论里藏 " + INLINE + " 和 " + INLINE_DQL
    from link_brain.adapters import xiaohongshu as xhs
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: raw)
    assert cli.main(["ingest", "https://example.invalid/share"]) in (0, 2)
    _, source, source_id = _get_item_id(tmp_path)
    agent = (storage.derived_dir(source, source_id) / "agent.md").read_text(encoding="utf-8")
    assert "require('child_process')" in agent  # 内容还在（AI 照样读得到）
    assert "readdirSync" in agent
    assert not executable_shapes(agent), executable_shapes(agent)


def test_pdf2md_output_and_old_files_are_neutralized(tmp_path, monkeypatch):
    obj = storage.object_dir("xiaohongshu", "abc")
    (obj / "attachments").mkdir(parents=True)
    pdf = obj / "attachments" / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(attachments_mod, "load_downloaded", lambda s, i: {"d1": {"file": "a.pdf"}})
    monkeypatch.setattr(pdftext, "attachment_to_markdown",
                        lambda path, **kw: {"status": "ok", "markdown": "# 附件\n" + DVJS, "method": "text", "note": ""})
    rows = pdftext.convert_object_attachments("xiaohongshu", "abc")
    out = Path(rows[0]["path"])
    assert rows[0]["status"] == "ok" and not executable_shapes(out.read_text(encoding="utf-8"))
    # 清洗上线前转出来的旧 md：下次 pdf2md 不重转，只补洗
    out.write_text("旧版 " + INLINE + "\n" + DVJS, encoding="utf-8")
    import os
    os.utime(out, (pdf.stat().st_mtime + 10,) * 2)
    rows = pdftext.convert_object_attachments("xiaohongshu", "abc")
    assert rows[0]["status"] == "already"
    assert not executable_shapes(out.read_text(encoding="utf-8"))


def test_ask_answer_markdown_is_neutralized(monkeypatch):
    items = [{"id": "a", "title": "做梦 " + INLINE, "note": "a.md", "summary": "",
              "search_fields": {"body": "做梦的实验记录。" * 5}, "tags": [], "url": "", "github_urls": [],
              "suggested_links": [], "ts": "2026-09-10T00:00:00+08:00"}]
    monkeypatch.setattr(ask, "load_items", lambda: items)
    monkeypatch.setattr(ask.ai_config, "load", lambda: ask.ai_config._deep_merge(ask.ai_config.DEFAULTS, {}))
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: {"status": "ok", "text": "原文：\n" + DVJS + "\n[来源1]"})
    r = ask.answer("做梦")
    assert r["status"] == "ok" and "require('child_process')" in r["markdown"]
    assert not executable_shapes(r["markdown"])
    assert not executable_shapes(r["history"][-1]["content"])


def test_export_bundle_neutralizes_answer_and_agent_md(tmp_path):
    vault = storage.vault_root()
    agent = vault / "_archive/xiaohongshu/x/derived/agent.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("# 旧机读版\n" + DVJS, encoding="utf-8")
    storage.write_json(vault / "_archive/catalog-data.json", {"items": [
        {"id": "x", "title": "t", "agent_md": "_archive/xiaohongshu/x/derived/agent.md", "note": "t.md", "url": ""}]})
    res = export_bundle.export_bundle(["x"], include_images=False, answer="答 " + INLINE, question="q")
    with zipfile.ZipFile(res["path"]) as z:
        for name in z.namelist():
            assert not executable_shapes(z.read(name).decode("utf-8")), name
