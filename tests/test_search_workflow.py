import json

from link_brain import retrieval, attachments, storage, ask


def test_bilingual_weights_and_source_windows():
    title = {"title": "Music collection", "tags": [], "search_fields": {}}
    comment = {"title": "其他", "tags": [], "search_fields": {"comments": "music"}}
    for term in ["音乐", "音", "music"]:
        assert retrieval.score(title, [term]) > retrieval.score(comment, [term]) > 0
    item = {"title": "教程", "search_fields": {"attachments": "无关前言" * 1000 + "音乐合成的准确步骤：先采样，再混音。"}}
    excerpts = retrieval.excerpts(item, ["music"], 300)
    assert excerpts[0]["field"] == "attachments"
    assert "先采样，再混音" in excerpts[0]["text"]


def test_partial_attachments_and_deleted_bytes(tmp_path):
    raw = tmp_path / "raw/v0001"
    raw.mkdir(parents=True)
    meta = {"item_id": "xhs-a", "current_version": 1}
    storage.write_json(raw / "source.json", {"note": {"attachments": [{"doc_id": "1", "name": "one.pdf"}, {"doc_id": "2", "name": "two.pdf"}]}})
    storage.write_json(tmp_path / "attachments.json", {"files": [{"doc_id": "1", "file": "one.pdf"}]})
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments/one.pdf").write_bytes(b"downloaded")
    report = attachments.inventory(tmp_path, meta)
    assert report["missing"] == 1 and report["status"] == "metadata_only"
    (tmp_path / "attachments/one.pdf").unlink()
    assert attachments.inventory(tmp_path, meta)["missing"] == 2


def test_context_finds_late_ocr_and_respects_cap(monkeypatch):
    item = {"id": "x", "title": "配方", "search_fields": {"ocr": "前言" * 3000 + "鸡肉 200 克，蒸 20 分钟。"}}
    monkeypatch.setattr(ask, "load_items", lambda: [item])
    monkeypatch.setattr(ask.ai_config, "load", lambda: {"retrieval": {"totalCharLimit": 600, "fragChars": 300}})
    seen = []
    monkeypatch.setattr(ask, "call_text", lambda p, t, s: (seen.append(t) or {"status": "ok", "text": "鸡肉 200 克。[来源1]"}))
    assert ask.answer("chicken")["sources"][0]["id"] == "x"
    context = seen[0].split("【原始材料】")[1]
    assert "200 克" in context and len(context) <= 601


def test_channel_delivery_defaults_to_body_and_only_sends_real_cited_files(tmp_path):
    pdf = tmp_path / "原始文件.pdf"
    pdf.write_bytes(b"actual file")
    result = {"markdown": "回答来自材料。[来源1]", "sources": [
        {"id": "a", "title": "材料", "citation": 1, "url": "https://example.com/a", "agent_md": "a.md",
         "attachments": [{"file": str(pdf), "markdown": "converted.md"}, {"file": str(tmp_path / "missing.pdf")}]},
        {"id": "b", "title": "未引用", "citation": 2, "url": "https://example.com/b", "attachments": []},
    ]}
    assert ask.delivery_payload(result) == {"body": "回答来自材料。"}
    parts = ask.delivery_payload(result, ["links", "files"])
    assert len(parts["links"]) == 1 and parts["links"][0]["source_id"] == "a"
    assert len(parts["files"]) == 1 and parts["files"][0]["path"] == str(pdf.resolve())
    assert parts["files"][0]["markdown_path"] == "converted.md"


def test_json_request_stdin_supports_channel_parts_and_history(monkeypatch, capsys):
    import io
    from link_brain import cli
    monkeypatch.setattr(ask, "answer", lambda question, history, include: {
        "status": "ok", "delivery": {"body": question, "links": include}, "history": history})
    request = {"question": "继续", "history": [{"role": "user", "content": "前题"}], "include": ["links", "files"]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request)))
    assert cli.main(["ask", "--request-stdin"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["delivery"] == {"body": "继续", "links": ["links", "files"]}
    assert result["history"] == request["history"]


