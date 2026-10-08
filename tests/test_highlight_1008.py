"""批次 D · N10 划重点：只在标签外的文字里找（不再把 <mark> 插进 alt 属性）、几段一次写盘、CLI --json 外形和退出码。"""

import html.parser
import json

from link_brain import cli, render, storage

ALT_BODY = ('<div class="lb-note"><figure class="lb-slide"><img src="x.webp" alt="图片 1 / 3"></figure>'
            '<div class="lb-body"><p>第一段讲图片怎么拍。<br>第二段讲构图。</p></div></div>')


def _setup(tmp_path, monkeypatch, body=ALT_BODY):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    obj = tmp_path / "_archive" / "xiaohongshu" / "deadbeef01"
    obj.mkdir(parents=True)
    (obj / "meta.json").write_text(json.dumps({"visible_note": "Web/Xiaohongshu/n.md"}), encoding="utf-8")
    note = tmp_path / "Web" / "Xiaohongshu" / "n.md"
    note.parent.mkdir(parents=True)
    note.write_text(render.CONTENT_START + "\n" + body + "\n" + render.CONTENT_END + "\n", encoding="utf-8")
    return note


class _Strict(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.alts = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.alts.append(dict(attrs).get("alt"))


def test_highlight_skips_attributes(tmp_path, monkeypatch):
    note = _setup(tmp_path, monkeypatch)
    r = render.set_highlights("xhs-deadbeef01", ["图片"])
    assert r["changed"] == ["图片"]
    text = note.read_text(encoding="utf-8")
    assert 'alt="图片 1 / 3"' in text, "alt 属性原样"
    assert "第一段讲<mark>图片</mark>怎么拍" in text
    p = _Strict()
    p.feed(text)
    assert p.alts == ["图片 1 / 3"]


def test_reapply_skips_attributes():
    out = render.reapply_highlights(ALT_BODY, ["图片"])
    assert 'alt="图片 1 / 3"' in out and "讲<mark>图片</mark>怎么拍" in out
    assert render.reapply_highlights(out, ["图片"]) == out


def test_find_in_text_skips_existing_mark():
    s = "<p><mark>重点</mark>，再说一次重点</p>"
    assert render._find_in_text(s, "重点") == s.index("一次重点") + 2


def test_multi_phrases_one_write(tmp_path, monkeypatch):
    note = _setup(tmp_path, monkeypatch)
    writes = []
    real = storage.atomic_write_text
    monkeypatch.setattr(storage, "atomic_write_text", lambda p, t, *a, **k: (writes.append(p), real(p, t, *a, **k)))
    r = render.set_highlights("xhs-deadbeef01", ["第一段讲图片怎么拍。", "第二段讲构图。"])
    assert r["changed"] == ["第一段讲图片怎么拍。", "第二段讲构图。"] and len(writes) == 1
    text = note.read_text(encoding="utf-8")
    assert "<mark>第一段讲图片怎么拍。</mark><br><mark>第二段讲构图。</mark>" in text


def test_already_and_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    render.set_highlights("xhs-deadbeef01", ["构图"])
    r = render.set_highlights("xhs-deadbeef01", ["构图", "根本不存在"])
    assert r["already"] == ["构图"] and r["missing"] == ["根本不存在"] and r["changed"] == []


def test_cli_json_shape_and_exit(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    assert cli.main(["highlight", "xhs-deadbeef01", "构图", "怎么拍", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["message"] == "已划 2 处" and out["changed"] == ["构图", "怎么拍"] and out["code"] == ""
    assert cli.main(["highlight", "xhs-deadbeef01", "没有这句", "--json"]) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is False and out["message"] == "没找到这段原文" and out["missing"] == ["没有这句"]


def test_remove(tmp_path, monkeypatch, capsys):
    note = _setup(tmp_path, monkeypatch)
    render.set_highlights("xhs-deadbeef01", ["构图"])
    assert cli.main(["highlight", "xhs-deadbeef01", "构图", "--remove", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["message"] == "已取消 1 处"
    assert "<mark>" not in note.read_text(encoding="utf-8")
