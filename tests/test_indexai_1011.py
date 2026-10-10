"""索引树 10-11：解析器认她的真实写法 + 按内容归类（假模型）+ 建议新增 / AI 建子类 + 手动改归属 + 空节点。

全部走 tmp vault，模型一律换成假的（`indexai._call`），按标题里的关键词给答案，同时记下每次调用（验「不重复花钱」）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from link_brain import cli, indexai, indextree as it, storage


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "_archive").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(storage.ENV_VAULT, str(v))
    return v


def item(n, title, tags=(), summary=None, **kw):
    return {"id": f"xhs-{n:04d}", "title": title, "tags": list(tags), "summary": summary if summary is not None else f"{title}。",
            "date": "2026-10-01", "ts": f"2026-10-01T00:{n % 60:02d}:00+10:00", **kw}


def write_catalog(vault: Path, items, built_at="2026-10-10T01:00:00+11:00"):
    (vault / "_archive" / "catalog-data.json").write_text(
        json.dumps({"built_at": built_at, "items": items}, ensure_ascii=False), encoding="utf-8")


def write_index(vault: Path, text: str):
    (vault / "索引.md").write_bytes(text.encode("utf-8"))


# 照她真文件的样子：前面一句需求、Tab 缩进的树、括号说明、占位、第 4 级、后面几行零散说明
OWNER = (
    "%%\n写法说明\n%%\n\n"
    "需求：最多3级分类，分类可以兼容，一个帖子可以多个分类\n\n"
    "\t美食\n"
    "\t\t菜谱\n"
    "\t\t\t锅包肉\n"
    "\t\t\t...\n"
    "\t\t综合\n"
    "\t同人\n"
    "\t\t瓶邪\n"
    "\t\t（其他主题）\n"
    "\t游戏\n"
    "\t\t游戏\n"
    "\t\t\t宫崎英高\n"
    "\t\t\t\t血源\n"
    "\t\t\t\t黑魂\n"
    "\t\t游戏推荐\n"
    "\t工程\n"
    "\t\tai前沿消息（不属于ai记忆、人格的放这里）\n"
    "\t\t\t模型\n"
    "\t\t工程管理\n"
    "\tAI\n"
    "\t\tai功能\n"
    "\t\t\t游戏\n"
    "\t\t\t社区\n"
    "\t\t\t\t小机知道\n"
    "\t\t\t\t...\n"
    "\n"
    "同步的tag：fun、art、self-improvement、coding、news\n"
    "娱乐、欣赏指向gallary\n"
    "self-improvement\n"
)


# ── 解析器 ──

def test_parse_owner_file_prose_parens_placeholders_and_depth():
    p = it.parse(OWNER)
    paths = [n.path for n in p.walk()]
    assert not any(x.startswith(("需求", "同步的tag", "娱乐", "欣赏", "self-improvement")) for x in paths), paths
    assert paths[:2] == ["美食", "美食/菜谱"]
    assert set(r.name for r in p.roots) == {"美食", "同人", "游戏", "工程", "AI"}
    ai_news = p.find("工程/ai前沿消息")
    assert ai_news is not None and ai_news.desc == "不属于ai记忆、人格的放这里"   # 括号 = 说明，不按「、」拆
    assert p.find("工程/人格的放这里）") is None and p.find("工程/ai前沿消息/模型") is not None
    assert p.find("美食/菜谱").open and p.find("同人").open and p.find("同人").open_hint == "其他主题"
    assert not [n for n in p.walk() if n.name in ("...", "（其他主题）", "其他主题")]
    gong = p.find("游戏/游戏/宫崎英高")
    assert gong.hints == ["血源", "黑魂"] and not gong.children                      # 第 4 级并进第 3 级当关键词
    assert p.find("AI/ai功能/社区").hints == ["小机知道"] and p.find("AI/ai功能/社区").open
    assert max(n.depth for n in p.walk()) == 3
    texts = [c["text"] for c in p.comments]
    assert texts[0].startswith("需求") and any(t.startswith("同步的tag") for t in texts) and "self-improvement" in texts
    assert any("第 4 级" in w["text"] and "宫崎英高" in w["text"] for w in p.warnings)


def test_parse_backward_compat_name_tags_and_col0_blocks():
    text = "- 美食：家常菜, 烘焙\n\n- 旅游\n  - 成都：火锅\n\n- 数码\n- 注意：这一行是说明\n"
    p = it.parse(text)
    assert [n.path for n in p.walk()] == ["美食", "旅游", "旅游/成都", "数码"]   # 第一级顶格、空行分块照样都是节点
    assert p.find("美食").tags == ["家常菜", "烘焙"] and p.find("旅游/成都").explicit
    assert [c["line"] for c in p.comments] == [7]
    # 括号里的冒号逗号不算写法；名字：标签 后面带括号也行
    p2 = it.parse("- 健身（含：瑜伽、跑步）\n- 菜谱：红烧肉（家常），甜品\n")
    assert p2.find("健身").desc == "含：瑜伽、跑步" and not p2.find("健身").explicit
    assert p2.find("菜谱").tags == ["红烧肉", "甜品"] and p2.find("菜谱").desc == "家常"


def test_prose_detection_is_conservative():
    for s in ("一个人旅行", "社会化沟通技巧", "动漫番剧漫画", "猫狗萌物", "AI 玩机"):
        assert not it.is_prose(s), s
    for s in ("需求：最多3级分类", "说明：随便写", "娱乐、欣赏指向gallary", "不属于这里的都放到下面去吧。"):
        assert it.is_prose(s), s


def test_edit_new_root_goes_after_last_tree_line_not_after_trailing_notes():
    out = it.edit_new_node(OWNER, "", "健康")
    lines = out.split("\n")
    i = lines.index("\t健康")
    assert lines[i - 1] == "\t\t\t\t..." and lines[i + 1] == ""                   # 插在树的最后一行后面
    assert it.parse(out).find("健康") is not None and out.endswith("self-improvement\n")


def test_edit_remove_node_and_split_line_with_parens():
    text = "- 工程\n  - 前端（含设计、交互）, 后端\n  - 管理\n    - 进度\n- AI\n"
    out = it.edit_remove_node(text, "工程/管理")
    assert out == "- 工程\n  - 前端（含设计、交互）, 后端\n- AI\n"
    out2 = it.edit_remove_node(text, "工程/前端")
    assert "后端" in out2 and "前端" not in out2 and it.parse(out2).find("工程/后端") is not None
    added = it.edit_add_tags(text, "工程/前端", ["vue"])
    assert it.parse(added).find("工程/前端").tags == ["前端", "vue"] and "（含设计、交互）" in added


# ── 假模型 ──

ITEMS = [
    item(1, "家常锅包肉做法", ["锅包肉"]),
    item(2, "空气炸锅鸡翅", ["空气炸锅"]),
    item(3, "空气炸锅薯条", ["空气炸锅"]),
    item(4, "空气炸锅烤红薯", ["空气炸锅"]),
    item(5, "瓶邪同人图", ["瓶邪"]),
    item(6, "空洞骑士 丝之歌速通", ["游戏"]),
    item(7, "空洞骑士 白宫攻略", ["游戏"]),
    item(8, "空洞骑士 苦痛之路", ["游戏"]),
    item(9, "血源 老猎人DLC", ["血源"]),
    item(10, "让 AI 陪我打游戏的插件", ["ai"]),
    item(11, "GPT-6 发布", ["模型"]),
    item(12, "Coles 本周半价", ["澳洲超市"]),
    item(13, "Woolworths 必买零食", ["澳洲超市"]),
    item(14, "随便一张风景", ["风景"]),
    item(15, "空气炸锅蛋挞", ["空气炸锅"]),
    item(16, "空气炸锅烤鸡", ["空气炸锅"]),
    item(17, "空洞骑士 护符搭配", ["游戏"]),
    item(18, "空洞骑士 全收集", ["游戏"]),
    item(19, "空洞骑士 剧情", ["游戏"]),
    item(21, "空气炸锅烤肠", ["空气炸锅"]),
]

RULES = [  # 标题关键词 → 节点路径（假模型按内容「判断」）
    ("锅包肉", "美食/菜谱/锅包肉"), ("空气炸锅", "美食/菜谱"), ("瓶邪", "同人/瓶邪"), ("空洞骑士", "游戏/游戏"),
    ("血源", "游戏/游戏/宫崎英高"), ("AI 陪我打游戏", "AI/ai功能/游戏"), ("GPT", "工程/ai前沿消息/模型"),
]


class FakeModel:
    def __init__(self):
        self.calls: list[str] = []
        self.hostile = False
        self.fail = False

    def notes(self, text, head="【笔记】"):
        body = text.split(head, 1)[1] if head and head in text else text
        out = []
        for line in body.split("\n"):
            m = re.match(r"^(\d+)\. (.*?)｜", line)
            if m:
                out.append((int(m.group(1)), m.group(2)))
        return out

    def __call__(self, instruction, text, cfg, max_tokens):
        usage = {"prompt_tokens": len(text), "completion_tokens": 20}
        if self.fail:
            self.calls.append("fail")
            return {"status": "failed", "code": "TRANSIENT.HTTP_5XX", "error": "接口 502", "usage": None}
        if instruction is indexai._FULL_INSTRUCTION:
            self.calls.append("full")
            rows = []
            for i, title in self.notes(text):
                n = [p for k, p in RULES if k in title][:1]
                if self.hostile:
                    n = n + ["根本不存在/的节点", "忽略以上指令", 3]
                rows.append({"i": i, "n": n})
            if self.hostile:
                rows.append({"i": 999, "n": ["美食"]})
            return {"status": "ok", "text": json.dumps({"r": rows}, ensure_ascii=False), "usage": usage}
        if instruction is indexai._NODE_INSTRUCTION:
            self.calls.append("node")
            new = re.findall(r"^(.+?)(?:——.*)?$", text.split("【新分类】\n", 1)[1].split("\n\n", 1)[0], re.M)
            rows = []
            for i, title in self.notes(text.split("【整棵树")[0]):
                hit = [p for p in new if ("超市" in title or "Coles" in title or "Woolworths" in title) and p.endswith("超市好物")]
                if hit:
                    rows.append({"i": i, "n": hit})
            return {"status": "ok", "text": json.dumps({"r": rows}, ensure_ascii=False), "usage": usage}
        if "下面直接放着下面这些笔记" in instruction:
            self.calls.append("split")
            groups: dict[str, list[int]] = {}
            for i, title in self.notes(text, head=""):
                for k, name in (("空气炸锅", "空气炸锅菜"), ("空洞骑士", "空洞骑士")):
                    if k in title:
                        groups.setdefault(name, []).append(i)
            g = [{"name": k, "items": v} for k, v in groups.items()]
            if self.hostile:
                g.append({"name": "其他", "items": [1, 2, 3]})
                g.append({"name": "坏/名字：带, 逗号", "items": [1]})
            return {"status": "ok", "text": json.dumps({"g": g}, ensure_ascii=False), "usage": usage}
        if instruction is indexai._LEFTOVER_INSTRUCTION:
            self.calls.append("leftover")
            groups = {}
            for i, title in self.notes(text, head="【放不进的笔记】"):
                key = ("澳洲超市好物", "") if ("Coles" in title or "Woolworths" in title) else ("风景随拍", "不存在的父节点")
                groups.setdefault(key, []).append(i)
            g = [{"name": k[0], "parent": k[1], "items": v} for k, v in groups.items()]
            return {"status": "ok", "text": json.dumps({"g": g}, ensure_ascii=False), "usage": usage}
        raise AssertionError("没见过的调用")


@pytest.fixture
def fake(monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(indexai, "_call", m)
    monkeypatch.setattr(indexai, "classifier_ai", lambda: ({"model": "fake-flash", "cap": "textAI", "mode": "http"}, ""))
    monkeypatch.setattr(indexai, "price", lambda model, tin, tout: (tin * 1.0 + tout * 4.0) / 1e6)
    monkeypatch.setattr(indexai, "SETTLE_SEC", 0)
    return m


def rows(data):
    return {n["path"]: n for n in data["nodes"]}


def test_full_run_classifies_by_content_virtual_children_proposals_and_caches(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    before = it.public(it.build(vault))
    assert before["classify"]["pending"] == len(ITEMS) and before["classify"]["ai_ok"]
    # 还没跑 AI：名字字面兜底（「游戏」节点把带游戏标签的都收了）照旧
    assert rows(before)["AI/ai功能/游戏"]["count"] >= 5
    r = indexai.run(vault)
    assert r["ok"] and r["full"] == len(ITEMS) and "花了" in r["message"]
    assert fake.calls.count("full") == 1 and "split" in fake.calls and fake.calls.count("leftover") == 1
    data = json.loads((vault / "_archive" / "index-data.json").read_text(encoding="utf-8"))
    R = rows(data)
    # 有 AI 结果的篇不再按名字字面找：普通游戏攻略不进「AI/ai功能/游戏」
    assert R["AI/ai功能/游戏"]["items"] == ["xhs-0010"]
    assert R["游戏/游戏/宫崎英高"]["items"] == ["xhs-0009"]
    # 菜谱下面写了 `...` = 允许 AI 建：空气炸锅 6 篇直接挂成子类（virtual），不进 索引.md
    v = R["美食/菜谱/空气炸锅菜"]
    assert v["virtual"] and v["count"] == 6 and v["proposal"] and v["line"] == 0
    assert "空气炸锅菜" not in (vault / "索引.md").read_text(encoding="utf-8")
    # 「游戏/游戏」没写 `...`：空洞骑士 6 篇 → 建议新增（写清放在哪）
    props = {p["name"]: p for p in data["proposals"]}
    assert props["空洞骑士"]["parent"] == "游戏/游戏" and props["空洞骑士"]["count"] == 6 and props["空洞骑士"]["kind"] == "split"
    # 放不进的：澳洲超市分一组（第一级），父节点对不上的那组退到第一级
    assert props["澳洲超市好物"]["parent"] == "" and props["澳洲超市好物"]["loose"] == 2
    assert props["风景随拍"]["parent"] == "" and data["unclassified"]["count"] == 3
    assert data["classify"]["done"] == len(ITEMS) and data["classify"]["work"] == 0
    assert data["classify"]["spent"]["calls"] == len(fake.calls)
    assert data["assign"]["xhs-0006"] == ["游戏/游戏"]
    # 再跑 / 再保存（只改格式）：一分钱不花
    n = len(fake.calls)
    assert indexai.run(vault)["message"].startswith("没有要归的")
    write_index(vault, OWNER.replace("\t\t综合\n", "\t\t综合 \n") + "\n\n")
    it.build(vault)
    indexai.run(vault)
    assert len(fake.calls) == n


def test_new_node_only_asks_about_that_node_and_new_note_only_itself(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    indexai.run(vault)
    n = len(fake.calls)
    # 她加了一个节点：只问「哪些属于它」，不整篇重判
    write_index(vault, OWNER.replace("\t\t综合\n", "\t\t综合\n\t\t澳洲超市好物\n"))
    est = indexai.estimate(vault)
    assert est["full"] == 0 and est["changed"] == ["美食/澳洲超市好物"] and est["work"] >= len(ITEMS)
    indexai.run(vault)
    new_calls = fake.calls[n:]
    assert "full" not in new_calls and "node" in new_calls
    data = it.load(vault, fresh=False)
    assert rows(data)["美食/澳洲超市好物"]["items"] == ["xhs-0012", "xhs-0013"]
    assert data["unclassified"]["count"] == 1 and "澳洲超市好物" not in {p["name"] for p in data["proposals"]}
    # 新收一篇：只判这一篇
    n = len(fake.calls)
    write_catalog(vault, ITEMS + [item(20, "空洞骑士 新DLC", ["游戏"])], built_at="2026-10-11T01:00:00+11:00")
    assert indexai.estimate(vault)["full"] == 1
    indexai.run(vault)
    assert fake.calls[n:].count("full") == 1
    assert "xhs-0020" in rows(it.load(vault, fresh=False))["游戏/游戏"]["items"]


def test_removed_node_reclassifies_only_its_notes(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    indexai.run(vault)
    write_index(vault, OWNER.replace("\t\t瓶邪\n", ""))
    est = indexai.estimate(vault)
    assert est["full"] == 1                       # 只有瓶邪那一篇没地方了
    n = len(fake.calls)
    indexai.run(vault)
    assert fake.calls[n:].count("full") == 1


def test_hostile_output_is_validated(vault, fake):
    fake.hostile = True
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    indexai.run(vault)
    data = it.load(vault, fresh=False)
    paths = {n["path"] for n in data["nodes"]}
    assert not any("不存在" in p or "忽略" in p for p in paths)
    for ps in data["assign"].values():
        assert all(p in paths for p in ps) and len(ps) <= indexai.MAX_PICK
    assert not any(n["name"] in ("其他",) or "：" in n["name"] or "," in n["name"] for n in data["nodes"])


def test_api_failure_records_error_and_retries_later(vault, fake):
    fake.fail = True
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    r = indexai.run(vault)
    assert not r["ok"] and r["code"] == "TRANSIENT.HTTP_5XX" and "接口 502" in r["message"]
    data = it.load(vault, fresh=False)
    assert data["classify"]["error"]["error"] == "接口 502" and data["classify"]["pending"] == len(ITEMS)
    fake.fail = False
    assert indexai.run(vault)["ok"]
    assert "error" not in it.load(vault, fresh=False)["classify"]


def test_auto_run_respects_budget(vault, fake, monkeypatch):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    monkeypatch.setattr(indexai, "AUTO_MAX_YUAN", 0.000001)
    r = indexai.run(vault, auto=True)
    assert "超过自动上限" in r["message"] and fake.calls == []
    data = it.load(vault, fresh=False)
    assert data["classify"]["blocked"]["pending"] == len(ITEMS)
    assert it.maybe_classify(vault, data) == "over-budget"
    assert indexai.run(vault)["full"] == len(ITEMS)           # 她手动点：不受自动上限管


def test_no_model_configured_keeps_rules_and_says_why(vault, monkeypatch):
    monkeypatch.setattr(indexai, "classifier_ai", lambda: (None, "文本 AI没有 key"))
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    data = it.public(it.build(vault))
    assert data["classify"]["ai_ok"] is False and data["classify"]["why"] == "文本 AI没有 key"
    assert it.maybe_classify(vault, data) == "skipped"
    r = indexai.run(vault)
    assert r["code"] == "SKIPPED.NOT_CONFIGURED"
    assert rows(data)["同人/瓶邪"]["items"] == ["xhs-0005"]   # 名字兜底照旧


def test_manual_move_add_remove_undo_win_over_ai(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    indexai.run(vault)
    r = indexai.assign(["xhs-0006"], "move", "AI/ai功能/游戏", vault)
    assert r["ok"] and "只放这一类" in r["message"] and r["undo"]
    data = it.load(vault, fresh=False)
    assert data["assign"]["xhs-0006"] == ["AI/ai功能/游戏"] and "xhs-0006" not in rows(data)["游戏/游戏"]["items"]
    indexai.assign(["xhs-0006"], "add", "游戏/游戏推荐", vault)
    assert sorted(it.load(vault, fresh=False)["assign"]["xhs-0006"]) == ["AI/ai功能/游戏", "游戏/游戏推荐"]
    # AI 重跑也压不过她（换了内容让它重判）
    items2 = [dict(x, summary="改过的概要") if x["id"] == "xhs-0006" else x for x in ITEMS]
    write_catalog(vault, items2, built_at="2026-10-11T02:00:00+11:00")
    indexai.run(vault)
    assert sorted(it.load(vault, fresh=False)["assign"]["xhs-0006"]) == ["AI/ai功能/游戏", "游戏/游戏推荐"]
    r2 = indexai.assign(["xhs-0001", "xhs-0005"], "remove", "美食", vault)    # 从父节点拿掉 = 连子孙一起拿掉
    data = it.load(vault, fresh=False)
    assert "xhs-0001" not in rows(data)["美食"]["items"] and "xhs-0001" in data["unclassified"]["items"]
    indexai.assign([], "undo", r2["undo"], vault)
    assert "xhs-0001" in rows(it.load(vault, fresh=False))["美食/菜谱/锅包肉"]["items"]
    bad = indexai.assign(["xhs-0001"], "move", "没有这个节点", vault)
    assert not bad["ok"] and bad["code"] == "PERMANENT.STEP_ARGS"
    virt = indexai.assign(["xhs-0001"], "add", "美食/菜谱/空气炸锅菜", vault)
    assert not virt["ok"] and "保留" in virt["message"]


def test_accept_proposal_and_virtual_write_index_keep_format_and_no_rebilling(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER.replace("\n", "\r\n"))
    indexai.run(vault)
    data = it.load(vault, fresh=False)
    prop = next(p for p in data["proposals"] if p["name"] == "空洞骑士")
    n = len(fake.calls)
    r = it.accept_proposal(prop["id"], vault)
    assert r["ok"] and r["path"] == "游戏/游戏/空洞骑士", r
    raw = (vault / "索引.md").read_bytes().decode("utf-8")
    assert "\t\t\t空洞骑士\r\n" in raw and "\n\t\t\t空洞骑士" in raw and raw.count("\r\n") == raw.count("\n")
    assert raw.startswith("%%\r\n写法说明") and "需求：最多3级分类" in raw and raw.rstrip().endswith("self-improvement")
    data = it.load(vault, fresh=False)
    R = rows(data)
    assert R["游戏/游戏/空洞骑士"]["count"] == 6 and R["游戏/游戏"]["count"] == 7
    assert "空洞骑士" not in {p["name"] for p in data["proposals"]}
    assert list((vault / "_archive" / "index-history").glob("索引-*-accept.txt"))
    # AI 建的子类「保留」：写进 索引.md，篇数不变
    vid = R["美食/菜谱/空气炸锅菜"]["proposal"]
    r2 = it.accept_proposal(vid, vault)
    assert r2["ok"], r2
    R2 = rows(it.load(vault, fresh=False))
    assert not R2["美食/菜谱/空气炸锅菜"].get("virtual") and R2["美食/菜谱/空气炸锅菜"]["count"] == 6
    # 根上的建议：插在树的最后一行后面（不插到她末尾的说明下面）
    root = next(p for p in it.load(vault, fresh=False)["proposals"] if p["name"] == "澳洲超市好物")
    assert it.accept_proposal(root["id"], vault)["ok"]
    raw = (vault / "索引.md").read_bytes().decode("utf-8")
    assert raw.index("\t澳洲超市好物") < raw.index("同步的tag")
    indexai.run(vault)
    assert "full" not in fake.calls[n:] and "node" not in fake.calls[n:]       # 写进去的新节点不再花钱核一遍
    assert it.accept_proposal("nope", vault)["code"] == "PERMANENT.STEP_ARGS"


def test_dismiss_proposal_and_empty_nodes(vault, fake):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)
    indexai.run(vault)
    data = it.load(vault, fresh=False)
    pid = next(p["id"] for p in data["proposals"] if p["name"] == "风景随拍")
    indexai.dismiss(pid, vault)
    assert "风景随拍" not in {p["name"] for p in it.load(vault, fresh=False)["proposals"]}
    R = rows(it.load(vault, fresh=False))
    assert R["工程/工程管理"]["count"] == 0
    assert indexai.keep_empty("工程/工程管理", vault)["ok"]
    assert rows(it.load(vault, fresh=False))["工程/工程管理"]["keep_empty"] is True
    r = it.remove_empty("工程/工程管理", vault)
    assert r["ok"] and r["backup"]
    assert "工程管理" not in (vault / "索引.md").read_text(encoding="utf-8")
    assert not it.remove_empty("美食", vault)["ok"]                           # 有篇数的不删


def test_cli_classify_estimate_assign_accept_shapes(vault, fake, capsys):
    write_catalog(vault, ITEMS)
    write_index(vault, OWNER)

    def run_cli(*argv):
        code = cli.main(list(argv))
        out = capsys.readouterr().out.strip().splitlines()
        return code, json.loads(out[-1])

    code, j = run_cli("index", "classify", "--estimate")
    assert code == 0 and j["ok"] and j["work"] and "要" in j["message"]
    code, j = run_cli("index", "classify", "--progress")
    assert code == 0 and j["ok"] and j["full"] == len(ITEMS)
    code, j = run_cli("index", "build")
    assert code == 0 and j["classify"] in ("skipped", "skipped-test")
    code, j = run_cli("index", "assign", "--item", "xhs-0001", "--op", "move", "--path", "同人")
    assert code == 0 and j["ok"] and j["undo"]
    code, j = run_cli("index", "assign", "--op", "undo", "--path", j["undo"])
    assert code == 0 and j["message"] == "已撤销"
    pid = next(p["id"] for p in it.load(vault, fresh=False)["proposals"] if p["name"] == "空洞骑士")
    code, j = run_cli("index", "accept", "--id", pid)
    assert code == 0 and j["ok"] and j["path"] == "游戏/游戏/空洞骑士"
    code, j = run_cli("index", "empty", "--path", "工程/工程管理", "--keep")
    assert code == 0 and j["ok"]
    code, j = run_cli("index", "accept", "--id", "nope")
    assert code == 2 and not j["ok"]
