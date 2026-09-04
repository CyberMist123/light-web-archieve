"""Lot 3：render 幂等性 + comments 层保护、vision.json、文件名 sanitizer。

用 `tests/fixtures/mcp_raw_sanitized.json`（脱敏样本），monkeypatch `fetch_detail`，
不碰网络、不碰真 vault（`LINK_BRAIN_VAULT` 指到 tmp_path）。图片下载指向 example.invalid，
会失败（不影响本文件要测的东西），vision.run_ocr 用 monkeypatch 避免调真的 media.py。
"""

from __future__ import annotations

import json
from pathlib import Path

from link_brain import cli, index as index_mod, render as render_mod, storage, vision as vision_mod
from link_brain.adapters import xiaohongshu as xhs

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_raw_sanitized.json"
NOTE_ID = "0000000000000000deadbeef"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fake_parsed(text: str = "https://example.invalid/share") -> dict:
    return {
        "note_id": NOTE_ID,
        "xsec_token": "FAKE_TOKEN_FOR_TESTS",
        "canonical_url": xhs.CANONICAL_FMT.format(note_id=NOTE_ID),
        "input_url": text,
        "input_kind": "url",
    }


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(xhs, "parse_input", lambda text, client=None: fake_parsed(text))
    monkeypatch.setattr(xhs, "fetch_detail", lambda *a, **k: load_fixture())
    # 避免测试真的 subprocess 调 media.py
    monkeypatch.setattr(
        vision_mod, "run_ocr", lambda path, timeout=120: {"status": "ok", "ocr": "test ocr", "error": None}
    )


def _get_item_id(tmp_path):
    conn = index_mod.connect()
    try:
        rows = conn.execute("SELECT item_id, source, source_id FROM objects").fetchall()
        return rows[0]["item_id"], rows[0]["source"], rows[0]["source_id"]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 文件名 sanitizer
# --------------------------------------------------------------------------


def test_sanitize_title_strips_illegal_chars_and_reserved_names():
    assert render_mod.sanitize_title('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert render_mod.sanitize_title("CON") == "CON_"
    assert render_mod.sanitize_title("  ") == "untitled"
    long_title = "字" * 100
    assert len(render_mod.sanitize_title(long_title)) <= 60


def test_visible_filename_is_clean_title(tmp_path):
    """Owner 2026-09-04：文件名不要 `__<id8>` 那截，只有撞名时才退回带后缀的。"""
    assert render_mod.visible_filename("标题") == "标题.md"
    assert render_mod.visible_filename("标题", "0000000000000000deadbeef") == "标题__deadbeef.md"

    vd = tmp_path / "Web"
    vd.mkdir()
    item = "xhs-0000000000000000deadbeef"
    # 干净名字没人占 → 用干净的
    assert render_mod.resolve_visible_path(vd, "标题", "0000000000000000deadbeef", item).name == "标题.md"

    # 自己上次写的那份 → 还是它，不要每次换名
    (vd / "标题.md").write_text(
        "---\ncssclasses: [link-brain]\nlink_brain:\n  item_id: " + item + "\n---\n",
        encoding="utf-8",
    )
    assert render_mod.resolve_visible_path(vd, "标题", "0000000000000000deadbeef", item).name == "标题.md"

    # Owner 手写的同名老文件（没有 link_brain 块）→ 退回后缀名，绝不覆盖她的东西
    (vd / "标题.md").write_text("我手写的笔记\n", encoding="utf-8")
    assert (
        render_mod.resolve_visible_path(vd, "标题", "0000000000000000deadbeef", item).name
        == "标题__deadbeef.md"
    )


def test_merge_existing_keeps_handwriting_from_both_files():
    """改名时同一个对象有两份 md：Owner 手写的 frontmatter 键和留言必须都活下来。"""
    primary = (
        "---\ntags: [claude]\ntime: \"20260902\"\n---\n\n"
        "<!-- link-brain:comments:start -->\n> 「20260902 人」笑死了\n<!-- link-brain:comments:end -->\n"
    )
    secondary = (
        "---\ntags: [人机恋]\nfinder: ler\n---\n\n"
        "<!-- link-brain:comments:start -->\n> 「20260903 人」另一边写的\n<!-- link-brain:comments:end -->\n"
    )
    merged = render_mod.merge_existing(primary, secondary)
    assert render_mod.existing_tags(merged) == ["claude", "人机恋"]
    extras = render_mod.parse_frontmatter(merged)
    assert extras["time"] == "20260902" and extras["finder"] == "ler"
    assert "笑死了" in merged and "另一边写的" in merged
    assert merged.count(render_mod.COMMENTS_START) == 1


# --------------------------------------------------------------------------
# render_object：可见 md 只有一份 + vision.json 结构
# --------------------------------------------------------------------------


def test_render_produces_single_visible_md_and_vision_json(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    code = cli.main(["ingest", "https://example.invalid/share"])
    assert code in (0, 2)  # 2 = 图片下载失败（fixture 指向不存在的域名），不影响本测试

    item_id, source, source_id = _get_item_id(tmp_path)
    visible_dir = storage.visible_dir()
    md_files = list(visible_dir.glob("*.md"))
    assert len(md_files) == 1, f"应只有 1 个可见 md，实际: {md_files}"

    vision_path = storage.derived_dir(source, source_id) / "vision.json"
    assert vision_path.exists()
    vision_doc = storage.read_json(vision_path)
    for image in vision_doc["images"]:
        assert "ocr" in image
        assert image["asset"].startswith("raw/v0001/assets/")


def test_rerender_is_idempotent(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _get_item_id(tmp_path)

    render_mod.render_item(source, source_id)
    visible_dir = storage.visible_dir()
    md_files = list(visible_dir.glob("*.md"))
    assert len(md_files) == 1
    first_text = md_files[0].read_text(encoding="utf-8")

    render_mod.render_item(source, source_id)
    md_files_2 = list(visible_dir.glob("*.md"))
    assert len(md_files_2) == 1, "rerender 不该产生第二个文件"
    second_text = md_files_2[0].read_text(encoding="utf-8")
    assert first_text == second_text, "两次渲染内容应完全一致（幂等）"


def test_rerender_preserves_hand_written_comments_layer(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _get_item_id(tmp_path)

    render_mod.render_item(source, source_id)
    visible_dir = storage.visible_dir()
    md_path = list(visible_dir.glob("*.md"))[0]
    text = md_path.read_text(encoding="utf-8")

    hand_written_line = "「20260904 人」这是我手写的一行留言"
    text = text.replace(
        render_mod.COMMENTS_END, f"{hand_written_line}\n{render_mod.COMMENTS_END}"
    )
    md_path.write_text(text, encoding="utf-8")

    render_mod.render_item(source, source_id)
    after_text = md_path.read_text(encoding="utf-8")
    assert hand_written_line in after_text, "rerender 后 comments 层手写行应原样保留"
    # content 层仍然存在且被重写（两栏容器；无图时容器带 lb-no-media 修饰类）
    assert 'class="lb-cols' in after_text
    assert render_mod.CONTENT_START in after_text and render_mod.CONTENT_END in after_text


# --------------------------------------------------------------------------
# read --brief / search 格式
# --------------------------------------------------------------------------


def test_read_brief_at_most_five_lines(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    item_id, source, source_id = _get_item_id(tmp_path)
    capsys.readouterr()

    code = cli.main(["read", item_id, "--brief"])
    out = capsys.readouterr().out
    assert code == 0
    lines = [line for line in out.splitlines() if line != ""]
    assert len(lines) <= 5


def test_search_output_has_five_pipe_fields(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    cli.main(["ingest", "https://example.invalid/share"])
    capsys.readouterr()

    code = cli.main(["search", ""])
    out = capsys.readouterr().out
    assert code == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, "应至少有一条结果"
    for line in lines:
        fields = line.split(" | ")
        assert len(fields) == 5, f"应是 5 个字段: {line!r}"
