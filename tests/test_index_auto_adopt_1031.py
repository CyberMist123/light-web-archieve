"""1031 作者：「索引分类倾向于打标——全自动，之后再手动调整；有新增就默认放入」「≥10 篇才建」。

- 「建议新增」够 AUTO_ADOPT_MIN 篇的，按内容归类跑完就直接写进 索引.md（和点「加进索引」一样），每条只自动加一次；
- 用户删掉的不会被加回来；
- 按内容归类临时没成：第一次不挂警告（下次自己再跑），连着两次才记 streak=2 让页面说。
"""

from __future__ import annotations

from link_brain import indexai, indextree as it

from test_indexai_1011 import ITEMS, OWNER, fake, vault, write_catalog, write_index  # noqa: F401 - pytest 夹具


def test_proposals_over_threshold_are_written_once(vault, fake, monkeypatch):
    monkeypatch.setattr(it, "AUTO_ADOPT_MIN", 5)
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    r = indexai.run(vault)
    assert r["ok"] and r["adopted"] == ["空洞骑士"], r            # 6 篇 ≥5；澳洲超市 / 风景随拍不够
    assert "新建了 1 个分类：空洞骑士" in r["message"]
    raw = (vault / "索引.md").read_text(encoding="utf-8")
    assert "\t\t\t空洞骑士\n" in raw
    data = it.load(vault, fresh=False)
    assert data["auto_adopted"]["nodes"] == [{"path": "游戏/游戏/空洞骑士", "name": "空洞骑士", "count": 6}]
    assert "空洞骑士" not in {p["name"] for p in data["proposals"]}
    # 用户把这一行删了：建议会回来，但不再自动加
    write_index(vault, OWNER)
    r2 = indexai.run(vault)
    assert r2["adopted"] == [] and "\t\t\t空洞骑士\n" not in (vault / "索引.md").read_text(encoding="utf-8")
    assert it.load(vault, fresh=False)["auto_adopted"] == {}


def test_default_threshold_is_ten(vault, fake):
    assert it.AUTO_ADOPT_MIN == 10
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    assert indexai.run(vault)["adopted"] == []                       # 合成数据里最多 6 篇：一个都不建


def test_transient_failure_streak(vault, fake, monkeypatch):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    monkeypatch.setattr(indexai, "_call", lambda *a, **k: {"status": "error", "code": "TRANSIENT.STEP_TIMEOUT", "error": "超过 180 秒没有答完"})
    indexai.run(vault)
    assert indexai.load_cache(vault)["last_error"]["streak"] == 1
    indexai.run(vault)
    assert indexai.load_cache(vault)["last_error"]["streak"] == 2
    assert it.load(vault)["classify"]["error"]["streak"] == 2
    monkeypatch.setattr(indexai, "_call", fake)
    indexai.run(vault)
    assert "last_error" not in indexai.load_cache(vault)
