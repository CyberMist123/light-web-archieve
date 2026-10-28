"""个人 Wiki 第一批后端（10-29）：PersonalWiki/*.md 的读写、历史、冲突、外部编辑、索引、导入、CLI。

conftest 已把 vault 指到 tmp；这里只用合成内容，不碰真库。
"""
import io
import json
import sys
import time

import pytest

from link_brain import cli, personal_wiki as pw, storage


@pytest.fixture()
def root():
    return pw.wiki_dir()


def last_json(capsys):
    out = capsys.readouterr().out.strip().splitlines()
    return json.loads(out[-1])


# ── 文件头 / 正文 ──────────────────────────────────────────────────────
def test_round_trip_keeps_fields_quotes_odd_titles_and_extra_props():
    page = {"id": "pw-1", "title": "#开头: 有冒号", "role": "topic", "index_tag": "ai-os", "order": ["pw-2", "pw-3"],
            "tags": ["ai-os", "记忆"], "created": "2026-10-29T10:00:00+08:00", "updated": "2026-10-29T10:00:00+08:00",
            "body": "第一段\n\n## 小节\n- [ ] 待办", "extra": ["aliases: [AIOS]"]}
    text = pw.render_page(page)
    assert 'title: "#开头: 有冒号"' in text   # Obsidian 按 YAML 读：# 开头要加引号，否则成了注释
    back = pw.parse_page(text)
    for k in ("id", "title", "role", "index_tag", "order", "tags", "created", "updated"):
        assert back[k] == page[k], k
    assert back["body"].startswith("第一段") and back["extra"] == ["aliases: [AIOS]"]


def test_reads_prototype_style_lists_and_pages_without_front_matter():
    p = pw.parse_page("---\nid: pw-stay\ntitle: 住宿偏好\ntags: [travel, hotels]\n---\n\n正文")
    assert p["tags"] == ["travel", "hotels"] and p["role"] == "page"
    bare = pw.parse_page("就一行字")
    assert bare["id"] == "" and bare["body"] == "就一行字"


def test_obsidian_block_style_lists_are_read_and_other_block_props_kept(root):
    """Codex 审查 #3：Obsidian 属性面板把列表写成块状；以前读成空列表，再保存就把标签丢了、文件头也写坏。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "块状.md").write_text(
        "---\nid: pw-block\ntitle: 块状\ntags:\n  - travel\n  - \"hotels\"\naliases:\n  - 别名一\n- 别名二\ncssclasses: wide\n---\n\n正文\n",
        encoding="utf-8")
    page = pw.get_page("pw-block")
    assert page["tags"] == ["travel", "hotels"]
    pw.save_page("pw-block", body="正文\n加一句", base_hash=page["hash"])
    text = (root / "块状.md").read_text("utf-8")
    assert 'tags: ["travel", "hotels"]' in text
    assert "aliases:\n  - 别名一\n- 别名二\ncssclasses: wide" in text      # 不认识的属性连续行原样留着
    assert pw.parse_page(text)["tags"] == ["travel", "hotels"]


def test_rename_that_cannot_move_the_file_changes_nothing(root, monkeypatch):
    """Codex 审查 #1 / 二轮 #4：改名以前是「写新名 + 删旧名」，删不掉就留两份同 id 的文件。
    现在先整个挪到新名字再写内容：挪不动就什么都没变，如实报失败。"""
    page = pw.create_page("占用中", body="原文")["page"]
    real_replace = pw.os.replace

    def busy(src, dst):
        if str(src).endswith("占用中.md"):
            raise PermissionError("被占用")
        return real_replace(src, dst)

    monkeypatch.setattr(pw.os, "replace", busy)
    monkeypatch.setattr(pw.time, "sleep", lambda s: None)
    with pytest.raises(pw.WikiError) as e:
        pw.save_page(page["id"], title="新名", base_hash=page["hash"])
    assert e.value.code == "WRITE_FAILED"
    assert sorted(p.name for p in root.glob("*.md")) == ["占用中.md"]
    assert pw.get_page(page["id"])["title"] == "占用中"
    assert len(pw.history(page["id"])) == 1


def test_index_is_written_while_holding_the_lock(monkeypatch):
    """Codex 审查 #2：写索引以前在锁外，先起的重建可能把更新的索引盖回去。"""
    pw.create_page("一页")
    held = {"n": 0}
    real_lock = pw.storage.file_lock

    class Tracking:
        def __init__(self, *a, **k):
            self.inner = real_lock(*a, **k)

        def __enter__(self):
            held["n"] += 1
            return self.inner.__enter__()

        def __exit__(self, *exc):
            held["n"] -= 1
            return self.inner.__exit__(*exc)

    seen = []
    real_write = pw.storage.write_json
    monkeypatch.setattr(pw.storage, "file_lock", Tracking)
    monkeypatch.setattr(pw.storage, "write_json", lambda path, data: (seen.append((path.name, held["n"])), real_write(path, data))[1])
    pw.build_index()
    assert (pw.INDEX_NAME, 1) in seen


def test_edit_made_in_obsidian_after_scan_is_not_overwritten(root, monkeypatch):
    """Codex 二轮 #1：扫描之后、写盘之前 Obsidian 改了这页，以前会被悄悄盖掉、历史里也没有。"""
    page = pw.create_page("竞态", body="原文")["page"]
    path = root / "竞态.md"
    real_scan = pw.scan

    def scan_then_obsidian_writes(*a, **k):
        out = real_scan(*a, **k)
        path.write_text(path.read_text("utf-8") + "Obsidian 刚写的\n", encoding="utf-8")
        return out

    monkeypatch.setattr(pw, "scan", scan_then_obsidian_writes)
    with pytest.raises(pw.WikiError) as e:
        pw.save_page(page["id"], body="Wiki 里写的", base_hash=page["hash"])
    assert e.value.code == "CONFLICT"
    assert "Obsidian 刚写的" in path.read_text("utf-8")
    monkeypatch.setattr(pw, "scan", real_scan)
    vers = pw.history(page["id"])
    assert vers[0]["kind"] == "external"                       # 它那版记进了历史
    assert "Obsidian 刚写的" in pw.version_text(page["id"], vers[0]["ver"])["body"]


def test_windows_device_names_are_never_used_as_files_or_ids(root):
    """Codex 二轮 #2：标题 / id 叫 COM1、NUL 这类，以前写到一半才失败、留下残文件。"""
    p = pw.create_page("COM1")["page"]
    assert p["file"] == "_COM1.md" and (root / "_COM1.md").is_file()
    assert pw.file_name_for("nul.txt", "x") == "_nul.txt.md"
    with pytest.raises(pw.WikiError) as e:
        pw.create_page("别的", page_id="COM1")
    assert e.value.code == "BAD_ARGS"
    assert sorted(x.name for x in root.glob("*.md")) == ["_COM1.md"]
    res = pw.import_pages([pw.render_page({"id": "LPT1", "title": "导入的", "role": "page", "tags": [], "body": "x"})])
    assert res[0]["status"] == "ok" and res[0]["id"] != "LPT1"   # 不合法的 id 换一个新的


def test_unchanged_save_of_page_without_id_still_writes_the_id(root):
    """Codex 二轮 #3：Obsidian 里建的页原样保存，以前返回「没有改动」、文件里还是没有 id。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "无id.md").write_text("---\ncreated: 2026-10-01T00:00:00+08:00\n---\n\n内容\n", encoding="utf-8")
    [entry] = pw.list_pages()
    res = pw.save_page(entry["id"], body="内容")
    assert res["changed"] is True
    assert (root / "无id.md").read_text("utf-8").startswith("---\nid: " + entry["id"])


def test_save_rejects_wrong_types_instead_of_splitting_strings():
    """Codex 二轮 #5：tags 传成 "travel" 以前被拆成 t r a v e l。"""
    page = pw.create_page("类型")["page"]
    for kw in ({"tags": "travel"}, {"order": "pw-1"}, {"tags": [1]}, {"body": 3}, {"title": ["x"]}):
        with pytest.raises(pw.WikiError) as e:
            pw.save_page(page["id"], **kw)
        assert e.value.code == "BAD_ARGS", kw
    assert pw.get_page(page["id"])["tags"] == []


def test_unknown_block_properties_keep_their_blank_lines(root):
    """Codex 二轮 #6：`summary: |` 中间的空行以前保存一次就没了。"""
    root.mkdir(parents=True, exist_ok=True)
    fm = "---\nid: pw-sum\ntitle: 摘要\nsummary: |\n  第一段\n\n  第二段\ntags: []\n---\n\n正文\n"
    (root / "摘要.md").write_text(fm, encoding="utf-8")
    page = pw.get_page("pw-sum")
    pw.save_page("pw-sum", body="正文改了", base_hash=page["hash"])
    assert "summary: |\n  第一段\n\n  第二段\n" in (root / "摘要.md").read_text("utf-8")


def test_history_prune_keeps_first_version_and_never_reuses_numbers(monkeypatch):
    monkeypatch.setattr(pw, "KEEP_VERSIONS", 3)
    page = pw.create_page("裁剪", body="0")["page"]
    for i in range(1, 6):
        pw.save_page(page["id"], body=str(i), kind="manual")
    vers = [v["ver"] for v in pw.history(page["id"])]
    assert vers == [6, 5, 1]                                    # 第一版留着，编号不回收
    assert pw.version_text(page["id"], 1)["body"].strip() == "0"


def test_stale_hash_blocks_title_only_order_only_restore_and_delete():
    f = pw.create_page("夹子", role="topic")["page"]
    stale = f["hash"]
    pw.save_page(f["id"], body="改过一次")
    for call in (lambda: pw.save_page(f["id"], title="新夹子", base_hash=stale),
                 lambda: pw.save_page(f["id"], order=["pw-x"], base_hash=stale),
                 lambda: pw.restore(f["id"], 1, base_hash=stale),
                 lambda: pw.delete_page(f["id"], base_hash=stale)):
        with pytest.raises(pw.WikiError) as e:
            call()
        assert e.value.code == "CONFLICT"
    assert pw.get_page(f["id"])["title"] == "夹子"


# ── 新建 / 保存 / 历史 ─────────────────────────────────────────────────
def test_create_writes_file_and_first_version(root):
    res = pw.create_page("住宿偏好", folder="travel", body="为什么记")
    page = res["page"]
    path = root / "住宿偏好.md"
    assert path.is_file() and page["file"] == "住宿偏好.md"
    assert page["tags"] == ["travel"] and page["hash"] == pw.content_hash(path.read_text("utf-8"))
    vers = pw.history(page["id"])
    assert [v["kind"] for v in vers] == ["create"]


def test_create_topic_uses_title_as_index_tag_and_rejects_duplicate_title():
    t = pw.create_page("AI OS", role="topic")["page"]
    assert t["role"] == "topic" and t["index_tag"] == "AIOS" and t["tags"] == ["AIOS"]
    with pytest.raises(pw.WikiError) as e:
        pw.create_page("ai os")   # 不分大小写
    assert e.value.code == "TITLE_TAKEN"


def test_typing_merges_auto_snapshots_but_manual_save_is_its_own_version():
    page = pw.create_page("记忆")["page"]
    h1 = pw.save_page(page["id"], body="一", base_hash=page["hash"])["page"]["hash"]
    h2 = pw.save_page(page["id"], body="一二", base_hash=h1)["page"]["hash"]
    kinds = [v["kind"] for v in pw.history(page["id"])]
    assert kinds == ["auto", "create"]                     # 2 分钟内连着打字 = 一条
    pw.save_page(page["id"], body="一二三", base_hash=h2, kind="manual", note="定稿")
    vers = pw.history(page["id"])
    assert [v["kind"] for v in vers] == ["manual", "auto", "create"] and vers[0]["note"] == "定稿"
    assert vers[0]["add"] == 1 and vers[0]["del"] == 1


def test_auto_snapshot_after_merge_window_is_new(monkeypatch):
    page = pw.create_page("召回")["page"]
    h = pw.save_page(page["id"], body="a")["page"]["hash"]
    real = time.time
    monkeypatch.setattr(pw.time, "time", lambda: real() + pw.MERGE_S + 5)
    pw.save_page(page["id"], body="ab", base_hash=h)
    assert [v["kind"] for v in pw.history(page["id"])] == ["auto", "auto", "create"]


def test_unchanged_save_writes_nothing():
    page = pw.create_page("梦境", body="x")["page"]
    res = pw.save_page(page["id"], body="x", base_hash=page["hash"])
    assert res["changed"] is False and len(pw.history(page["id"])) == 1


def test_stale_base_hash_is_rejected_and_file_untouched(root):
    page = pw.create_page("冲突")["page"]
    pw.save_page(page["id"], body="另一个窗口写的", base_hash=page["hash"])
    before = (root / "冲突.md").read_text("utf-8")
    with pytest.raises(pw.WikiError) as e:
        pw.save_page(page["id"], body="旧窗口写的", base_hash=page["hash"])
    assert e.value.code == "CONFLICT"
    assert (root / "冲突.md").read_text("utf-8") == before


def test_rename_moves_file_keeps_id_and_history(root):
    page = pw.create_page("旧名字")["page"]
    res = pw.save_page(page["id"], title="新名字", base_hash=page["hash"])
    assert not (root / "旧名字.md").exists() and (root / "新名字.md").is_file()
    assert res["page"]["id"] == page["id"] and len(pw.history(page["id"])) == 2
    other = pw.create_page("别的页")["page"]
    with pytest.raises(pw.WikiError) as e:
        pw.save_page(other["id"], title="新名字")
    assert e.value.code == "TITLE_TAKEN"


def test_file_name_is_sanitised_and_collisions_get_suffix(root):
    a = pw.create_page("a/b:c?")["page"]
    assert a["file"] == "a-b-c.md"
    (root / "a-b-c-x.md").write_text("---\ntitle: 别的标题\n---\n占位", encoding="utf-8")
    b = pw.create_page("a-b-c-x")["page"]   # 文件名被一个标题不同的散文件占了
    assert b["file"] == "a-b-c-x (2).md"


def test_external_edit_is_recorded_before_next_save(root):
    page = pw.create_page("外部")["page"]
    path = root / "外部.md"
    path.write_text(path.read_text("utf-8") + "在 Obsidian 里加的一行\n", encoding="utf-8")
    fresh = pw.get_page(page["id"])
    pw.save_page(page["id"], body=fresh["body"] + "\nWiki 里又写一行", base_hash=fresh["hash"])
    assert [v["kind"] for v in pw.history(page["id"])] == ["auto", "external", "create"]


def test_build_index_records_external_edit_too(root):
    page = pw.create_page("外部2")["page"]
    path = root / "外部2.md"
    path.write_text(path.read_text("utf-8") + "改了\n", encoding="utf-8")
    pw.build_index()
    assert [v["kind"] for v in pw.history(page["id"])][0] == "external"
    pw.build_index()   # 第二次没变化，不再多记
    assert len(pw.history(page["id"])) == 2


def test_restore_writes_new_version_and_keeps_later_history():
    page = pw.create_page("恢复", body="v1")["page"]
    h = pw.save_page(page["id"], body="v2", kind="manual")["page"]["hash"]
    res = pw.restore(page["id"], 1, base_hash=h)
    assert pw.get_page(page["id"])["body"].strip() == "v1"
    vers = pw.history(page["id"])
    assert [v["kind"] for v in vers] == ["restore", "manual", "create"] and "第 1 版" in vers[0]["note"]
    assert res["version"]["kind"] == "restore"
    with pytest.raises(pw.WikiError):
        pw.version_text(page["id"], 99)


def test_delete_moves_to_trash_and_keeps_history(root):
    page = pw.create_page("要删的", body="内容")["page"]
    res = pw.delete_page(page["id"])
    assert not (root / "要删的.md").exists()
    trashed = root / pw.TRASH_DIR / res["trashed"]
    assert "内容" in trashed.read_text("utf-8") and len(pw.history(page["id"])) == 1
    with pytest.raises(pw.WikiError) as e:
        pw.get_page(page["id"])
    assert e.value.code == "NOT_FOUND"


def test_bad_ids_are_rejected_before_touching_paths():
    for bad in ("../x", "a/b", "", "x" * 65):
        with pytest.raises(pw.WikiError) as e:
            pw.history(bad)
        assert e.value.code == "BAD_ARGS"


def test_page_written_in_obsidian_without_id_gets_derived_id_then_real_front_matter(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "随手.md").write_text("Obsidian 里直接建的\n", encoding="utf-8")
    [entry] = pw.list_pages()
    assert entry["id"].startswith("pf-") and entry["title"] == "随手"
    res = pw.save_page(entry["id"], body="Obsidian 里直接建的\n补一句")
    text = (root / "随手.md").read_text("utf-8")
    assert text.startswith("---\nid: " + entry["id"]) and res["page"]["id"] == entry["id"]


# ── 索引 ──────────────────────────────────────────────────────────────
def test_index_folders_order_loose_tags_cites_heads_and_lead():
    f = pw.create_page("旅行", role="topic")["page"]
    a = pw.create_page("住宿", folder="旅行", body="- [京都町屋](lwa:x-101) — 想住\n- [ ] 预算上限\n\n## 小节\n#待定 一句")["page"]
    b = pw.create_page("交通卡", folder="旅行", body="短途不用周游券")["page"]
    pw.create_page("冷泡茶", body="1 克茶 : 50 毫升水 #3")
    pw.save_page(f["id"], order=[b["id"], a["id"]])
    data = pw.build_index()
    assert storage.read_json(pw.index_path())["schema"] == pw.SCHEMA
    [folder] = data["folders"]
    assert folder["pages"] == [b["id"], a["id"]]          # 拖好的顺序
    by_id = {p["id"]: p for p in data["pages"]}
    assert [by_id[i]["title"] for i in data["loose"]] == ["冷泡茶"]
    pa = by_id[a["id"]]
    assert pa["cites"] == ["x-101"] and data["cites"]["x-101"] == [a["id"]]
    assert "待定" in pa["all_tags"] and "3" not in by_id[data["loose"][0]]["all_tags"]   # #3 是数字，不算标签
    assert pa["heads"] == [{"level": 2, "text": "小节", "line": 3}] and pa["open_tasks"] == 1
    assert pa["lead"] == "京都町屋 — 想住"                 # 以列表开头取第一条
    assert by_id[b["id"]]["lead"] == "短途不用周游券"
    assert "body" not in pa


def test_tags_inside_code_blocks_are_ignored():
    p = {"tags": [], "body": "```\n#不算\n```\n#算"}
    d = pw.derive(p)
    assert d["all_tags"] == ["算"]


# ── 导入 ──────────────────────────────────────────────────────────────
def test_import_from_prototype_local_js_skips_existing(tmp_path):
    pages = [pw.render_page({"id": "aios", "title": "AI OS", "role": "topic", "index_tag": "ai-os", "tags": ["ai-os"], "body": "索引"}),
             "---\nid: aios-memory\ntitle: 记忆\nrole: page\ntags: [ai-os]\n---\n\n- 一条"]
    src = tmp_path / "wiki-data.local.js"
    src.write_text("// 注释\nwindow.LWA_WIKI_LOCAL = " + json.dumps({"pages": pages, "items": []}, ensure_ascii=False) + ";\n", encoding="utf-8")
    res = pw.import_pages(pw.load_import_file(src))
    assert [r["status"] for r in res] == ["ok", "ok"]
    again = pw.import_pages(pw.load_import_file(src))
    assert [r["code"] for r in again] == ["EXISTS", "EXISTS"]
    assert [v["kind"] for v in pw.history("aios-memory")] == ["import"]


# ── CLI（插件消费：stdout 最后一行 JSON，退出码对上） ──────────────────
def test_cli_create_save_conflict_history(capsys, monkeypatch):
    assert cli.main(["pwiki", "create", "出境长线", "--folder", "travel"]) == 0
    made = last_json(capsys)
    assert made["ok"] and made["message"] == "已新建《出境长线》"
    pid, h = made["page"]["id"], made["page"]["hash"]

    def save(payload):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8"))
        return cli.main(["pwiki", "save"])

    assert save({"id": pid, "base_hash": h, "body": "## 欧洲\n- 法意"}) == 0
    saved = last_json(capsys)
    assert saved["ok"] and saved["message"] == "已保存" and saved["page"]["hash"] != h
    assert save({"id": pid, "base_hash": h, "body": "旧窗口"}) == 1
    conflict = last_json(capsys)
    assert conflict["ok"] is False and conflict["code"] == "CONFLICT" and "别处改过" in conflict["message"]
    assert cli.main(["pwiki", "history", pid]) == 0
    assert [v["kind"] for v in last_json(capsys)["versions"]] == ["auto", "create"]
    assert cli.main(["pwiki", "get", "no-such"]) == 2
    assert last_json(capsys)["code"] == "NOT_FOUND"
    assert cli.main(["pwiki", "index"]) == 0
    assert last_json(capsys)["pages"] == 1


def test_cli_bad_input_is_bad_args_exit_2(capsys, monkeypatch, tmp_path):
    page = pw.create_page("坏输入")["page"]
    for raw in ("{不是 json", json.dumps({"id": page["id"], "tags": "travel"})):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw.encode("utf-8")), encoding="utf-8"))
        assert cli.main(["pwiki", "save"]) == 2
        assert last_json(capsys)["code"] == "BAD_ARGS"
    bad = tmp_path / "bad.js"
    bad.write_text("window.X = {oops", encoding="utf-8")
    assert cli.main(["pwiki", "import", str(bad)]) == 2
    assert last_json(capsys)["code"] == "BAD_ARGS"


def test_cli_index_reports_history_it_could_not_record(capsys, root, monkeypatch):
    """Codex 二轮 #7：外部编辑的快照写不上，以前被吞掉、索引照报成功。"""
    page = pw.create_page("写不上")["page"]
    path = root / "写不上.md"
    path.write_text(path.read_text("utf-8") + "外部改的\n", encoding="utf-8")

    def disk_full(*a, **k):
        raise OSError("磁盘满了")

    monkeypatch.setattr(pw, "_snapshot", disk_full)
    assert cli.main(["pwiki", "index"]) == 1
    out = last_json(capsys)
    assert out["ok"] is False and out["code"] == "WRITE_FAILED" and out["history_failed"][0]["id"] == page["id"]
    assert pw.index_path().is_file()                             # 索引照样建好了
