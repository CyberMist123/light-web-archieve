"""r5 补测：回答质检的纯函数半边（喂小样例；分词用本机 jieba，不出网、不起进程）。"""
from __future__ import annotations

from link_brain import answer_check as ac


def test_sentences_split_skip_and_citation_merge():
    md = ("# 标题\n"
          "正文第一句[来源1]。第二句比较长一点[来源2]。\n"
          "- 列表项句子也会被拆出来哦\n"
          "> 引用被忽略\n```代码块忽略```\n"
          "## 缺口\n这里说的句子在缺口小节里。\n[来源1]\n")
    sents = ac.sentences(md)
    assert sents == [
        ("正文第一句[来源1]。", "# 标题", False),
        ("第二句比较长一点[来源2]。", "# 标题", False),
        ("列表项句子也会被拆出来哦", "# 标题", False),
        ("这里说的句子在缺口小节里。[来源1]", "## 缺口", True),   # 裸引用并回前一句；缺口小节标 skip
    ]
    assert ac.sentences("短。") == []          # 不足 6 个字的句子不进列表


def test_cite_re_both_forms():
    assert ac.CITE_RE.findall("两个引用[来源1]和[来源 3 段 2]都在") == ["1", "3"]


def test_source_text_pulls_all_parts():
    s = {"title": "标题Ａ", "excerpt": "摘录", "excerpts": [{"text": "片段一"}, {"text": ""}, "不是对象"]}
    item = {"id": "x1", "title": "标题Ａ", "tags": ["做饭"], "search_fields": {"body": "正文字段"}}
    text = ac.source_text(s, item)
    assert "标题a" in text and "摘录" in text and "片段一" in text and "正文字段" in text  # NFKC + casefold
    assert "不是对象" not in text and ac.source_text({}, None).strip() == ""


def test_run_alignment_aligned_and_unaligned():
    srcs = [{"citation": 1, "id": "x1", "title": "甲", "excerpt": "红烧肉要先焯水再炖", "author": ""}]
    good = ac.run("做红烧肉要先焯水然后炖烂[来源1]。", srcs)
    assert good["alignment"]["aligned"] == 1 and good["alignment"]["rate"] == 1.0
    bad = ac.run("这句话与来源毫无词汇交集纯凑字数用的句子[来源1]。", srcs)
    a = bad["alignment"]
    assert a["aligned"] == 0 and a["rate"] == 0.0
    assert a["unaligned"][0]["cites"] == [1] and a["unaligned"][0]["hits"] == 0
    # 没引用任何东西的直接答 + alignment 里 cited=0 → rate None
    none_cited = ac.run("这是一个没有任何引用标记的回答句子哦。", srcs, mode="direct")
    assert none_cited["alignment"]["rate"] is None


def test_run_leak_padding_no_citation():
    srcs = [{"citation": 1, "id": "x1", "title": "甲", "excerpt": "内容", "author": ""}]
    out = ac.run("本段含「机制、触发条件」这个词组[来源1]。", srcs)
    assert out["leak"] == {"found": ["机制、触发条件"]}
    assert "回答里漏出了提示词措辞：机制、触发条件" in out["warnings"] and out["ok"] is False
    # direct 模式有来源却一个引用都没有
    out2 = ac.run("这是一个没有任何引用标记的回答句子哦。", srcs, mode="direct")
    assert out2["padding"]["no_citation"] is True and "直接答却一个引用都没有" in out2["warnings"]


def test_run_uncited_ratio_only_counts_statements():
    srcs = [{"citation": 1, "id": "x1", "title": "甲", "excerpt": "红烧肉", "author": ""}]
    md = ("这是一条足够长的没有引用的陈述句内容哦。\n"
          "这是一条足够长的带着引用的陈述句内容哦[来源1]。\n"
          "这是一个足够长的疑问句会排除掉吗？\n")
    out = ac.run(md, srcs)
    assert out["uncited"] == {"sentences": 2, "uncited": 1, "ratio": 0.5}


def test_defense_check_allows_one_when_question_has_attribute():
    md = "以上仅供参考，请自行核实。还有一些句子内容凑数用的哦。"
    attr = ac.defense_check(md, question="价格多少钱")     # 问题带属性词 → 允许 1 句
    assert attr == {"hits": 1, "sentences": 2, "ratio": 0.5, "allowed": 1, "gap_headings": 0, "over": False,
                    "examples": ["以上仅供参考，请自行核实。"]}
    plain = ac.defense_check(md, question="随便聊聊")      # 普通问题不允许
    assert plain["allowed"] == 0 and plain["over"] is True
    two = ac.defense_check("以上仅供参考，请自行核实。详细情况请自行核实后再定论。", question="价格")
    assert two["hits"] == 2 and two["over"] is True        # 超过允许的 1 句
    gap = ac.defense_check("## 缺口\n这里有个标题就算超。\n正文句子长度足够被计入统计里。", question="")
    assert gap["gap_headings"] == 1 and gap["over"] is True  # 「缺口」标题本身就超


def test_warnings_phrases_from_checks():
    w = ac.warnings({
        "alignment": {"unaligned": [{"text": "某句超长没对上来源的例句" * 3, "cites": [1]}]},
        "absence": {"conflicts": [{"tier": "cited", "where": "来源1《甲》", "words": ["红烧肉", "焯水"]},
                                   {"tier": "related", "where": "其他相关《乙》", "words": ["x"]}]},
        "speaker": {"unknown": [{"name": "张三", "text": "…"}, {"name": "李四", "text": "…"}]},
        "leak": {"found": ["机制、触发条件"]},
        "padding": {"no_citation": True, "answer_chars": 100, "evidence_chars": 10},
        "must_not_text": {"hit": ["x"]},
    })
    assert w == [
        "1 句引用没对上来源原文（如「某句超长没对上来源的例句某句超长没对上来源的例句某句超长没对上来源的例句…」）",
        "说「没有」但 来源1《甲》 里出现了：红烧肉、焯水",   # 只报引用来源里的；其他相关只进 checks
        "点名的说话人不在来源里：张三、李四",
        "回答里漏出了提示词措辞：机制、触发条件",
        "直接答却一个引用都没有",                            # no_citation 优先于 padded
        "出现了题目禁止的内容",
    ]
    assert ac.warnings({}) == []
