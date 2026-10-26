"""r5 补测：谁收的（转发 domain 规则 + relabel 的 tmp vault / tmp 索引行为；目录重建打桩）。"""
from __future__ import annotations

import json

from link_brain import domain, provenance
from link_brain import index as index_mod


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path / "home"))


def _stub_catalog(monkeypatch):
    """目录重建是有副作用的大动作：打桩记调用，索引 UPDATE 照真跑。"""
    from link_brain import catalog
    calls = {"dirty": [], "fresh": 0}
    monkeypatch.setattr(catalog, "mark_dirty", lambda reason: calls["dirty"].append(reason))
    monkeypatch.setattr(catalog, "ensure_fresh", lambda *, wait_s=0: calls.__setitem__("fresh", calls["fresh"] + 1) or "built")
    return calls


def _mk_object(vault, sid, meta):
    obj = vault / "_archive" / "xiaohongshu" / sid
    obj.mkdir(parents=True)
    (obj / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return obj


def _mk_relation(item_id, origin, actor):
    conn = index_mod.connect()
    conn.execute("INSERT OR REPLACE INTO objects (item_id, source, source_id, canonical_url, kind, title,"
                 " first_archived_at, last_checked_at, current_version, object_dir) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (item_id, "xiaohongshu", item_id[4:], "https://x/" + item_id, "image", "t",
                  "2026-01-01", "2026-01-01", 1, "_archive/xiaohongshu/" + item_id[4:]))
    conn.execute("INSERT INTO relations (item_id, origin, actor, ingest_kind, created_at) VALUES (?,?,?,?,?)",
                 (item_id, origin, actor, "favorite", "2026-01-01"))
    conn.commit()
    conn.close()


def test_reexports_and_legacy_name():
    assert provenance.FABLE is domain.FABLE == "fable"
    assert provenance.collected_by is domain.collected_by
    assert provenance.clean_project is domain.clean_project and provenance.via is domain.via
    assert provenance.CHAT_SHARE == "聊天分享"   # 旧分组名只留给认旧值的地方


def test_relabel_missing_refs_report_and_no_rebuild(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    calls = _stub_catalog(monkeypatch)
    out = provenance.relabel(["xhs-没有这篇", "也不是id"])
    assert out == [{"item_id": "xhs-没有这篇", "status": "missing"}, {"item_id": "也不是id", "status": "missing"}]
    assert calls["dirty"] == [] and calls["fresh"] == 0   # 一篇都没改成：不碰目录


def test_relabel_updates_meta_and_relation_row(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    calls = _stub_catalog(monkeypatch)
    vault = tmp_path / "vault"
    _mk_object(vault, "abc1", {"item_id": "xhs-abc1", "origin": "tg", "actor": "cc", "favorited_by": []})
    _mk_relation("xhs-abc1", "tg", "cc")
    out = provenance.relabel(["xhs-abc1"], project="graph")
    assert out[0]["status"] == "ok" and out[0]["item_id"] == "xhs-abc1"
    assert out[0]["src"] == "graph"          # collected_by：非收藏、actor cc、有项目 → 项目名
    meta = json.loads((vault / "_archive" / "xiaohongshu" / "abc1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["project"] == "graph" and meta["origin"] == "tg" and meta["actor"] == "cc"  # 只动给定的键
    conn = index_mod.connect()
    row = conn.execute("SELECT origin, actor FROM relations WHERE item_id = 'xhs-abc1'").fetchone()
    conn.close()
    assert tuple(row) == ("tg", "cc")        # actor 没给：索引行原样（UPDATE 按旧值匹配写回同样的值）
    assert calls["dirty"] == ["改来源"] and calls["fresh"] == 1   # 改成了就标脏并重建
    # 她自己后来收藏了同一篇 → 回主收藏（collected_by 的回卷规则，src 立刻反映）
    meta["favorited_by"] = ["u1"]
    (vault / "_archive" / "xiaohongshu" / "abc1" / "meta.json").write_text(json.dumps(meta, ensure_ascii=False),
                                                                          encoding="utf-8")
    out2 = provenance.relabel(["xhs-abc1"], actor="ai:gpt", project="")
    assert out2[0]["status"] == "ok" and out2[0]["src"] == ""
    meta2 = json.loads((vault / "_archive" / "xiaohongshu" / "abc1" / "meta.json").read_text(encoding="utf-8"))
    assert meta2["actor"] == "ai:gpt" and "project" not in meta2   # project="" = 清掉项目名


def test_relabel_bare_ref_falls_back_to_xhs(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    calls = _stub_catalog(monkeypatch)
    vault = tmp_path / "vault"
    _mk_object(vault, "bare9", {"item_id": "xhs-bare9", "origin": "", "actor": "human", "favorited_by": []})
    _mk_relation("xhs-bare9", "", "human")
    out = provenance.relabel(["bare9"], origin="tg")   # 不是 <前缀>-<id> 形状：当小红书 source_id
    assert out[0]["status"] == "ok" and out[0]["src"] == "fable"   # human + origin=tg → Fable 组
    meta = json.loads((vault / "_archive" / "xiaohongshu" / "bare9" / "meta.json").read_text(encoding="utf-8"))
    assert meta["origin"] == "tg"


def test_clean_project_limits():
    assert domain.clean_project("  a / b \\ c  ") == "a - b - c"    # 去空白、路径分隔符换掉
    assert domain.clean_project("字" * 50) == "字" * 40             # 限长 40
    assert domain.clean_project(None) == "" and domain.clean_project("") == ""
