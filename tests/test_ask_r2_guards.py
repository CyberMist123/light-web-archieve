"""Lot R2 核心的保守护栏：深读不误伤泛问 / 留来源重答；相关卡摘录逐字；Mermaid 原文折叠块排版。"""
from link_brain import ask, render, retrieval


def _pool(*titles):
    return [{'id': str(i), 'title': t} for i, t in enumerate(titles)]


def test_pinned_reanswer_never_deep_reads():
    pool = _pool('黑椒牛肉意面配方', '别的', '再别的')
    assert ask.prompt_count('黑椒牛肉意面配方讲了什么', pool, 8000, 8)[1] is True
    assert ask.prompt_count('黑椒牛肉意面配方讲了什么', pool, 8000, 8, pinned=True) == (3, False)


def test_common_title_fragment_is_not_naming_one_post():
    # 「ai记忆」一大片标题都带：是泛问，不收窄成一篇
    pool = _pool('AI记忆系列03', 'AI记忆系列01', 'AI记忆怎么写', 'AI记忆系统构想', '其他')
    assert not ask.deep_read_wanted('AI记忆怎么做权重衰减', pool)
    # 独特片段才算点名；紧跟着也被点名的至多再收 2 篇
    pool = _pool('会生长的AI伴侣记忆系统', '会生长的AI伴侣·续篇', '无关', '无关二')
    assert ask.prompt_count('会生长的AI伴侣记忆系统讲了什么', pool, 8000, 8) == (2, True)


def test_score_gap_ignored_for_listing_questions():
    pool = [{'title': '甲', '_fused_score': 4}, {'title': '乙', '_fused_score': 1}]
    assert ask.deep_read_wanted('担担面有没有汤', pool)
    assert not ask.deep_read_wanted('有哪些担担面做法', pool)


def test_no_fused_score_means_no_score_trigger():
    # 无 key / 无语义 / 无扩词：没有融合分，只剩标题点名一条路（行为与改前一致）
    pool = [{'title': '甲'}, {'title': '乙'}]
    assert not ask.deep_read_wanted('问点别的', pool)


def test_related_excerpt_verbatim_and_fail_open(monkeypatch):
    item = {'id': 'x', 'summary': '概要不算', 'search_fields': {
        'body': '开头。' * 50 + 'ＡＩ吵架以后要回避吗' + '结尾。' * 50, 'comments': '吵架'}}
    snippet = retrieval.lexical_excerpt(item, ['ai', '回避'])
    assert snippet['field'] == 'body' and snippet['text'] in item['search_fields']['body']
    assert 'ＡＩ吵架' in snippet['text'] and len(snippet['text']) <= 120
    assert retrieval.lexical_excerpt(item, []) == {'field': '', 'text': ''}
    monkeypatch.setattr(retrieval, 'lexical_excerpt', lambda *a: 1 / 0)
    card = ask.related_card(item, 3, ['ai'])
    assert card['excerpt'] == '' and card['tier'] == 'related' and card['rank'] == 3


def test_mermaid_raw_ocr_block_stays_inside_list_item():
    text = render.render_agent_md(source={'note': {'title': 't', 'body': 'b'}, 'comments': []},
        meta={'item_id': 'xhs-1', 'current_version': 1},
        vision={'images': [{'asset': 'image-001.webp', 'status': 'ok',
            'refined': {'status': 'ok', 'kind': 'diagram', 'text': '```mermaid\nflowchart TD\nA-->B\n```'},
            'lines': [{'text': '第一步'}, {'text': ''}, {'text': '小贴士 & 注意'}]}]})
    block = text[text.index('<details>'):text.index('</details>') + 10].splitlines()
    assert all(row.strip() for row in block)                       # HTML 块里不留空行，不被拆断
    assert '\n\n<details>' in text and '### 第1张（图1 · image-001.webp）' in text
    assert '小贴士 &amp; 注意</pre>' in text
    # 非流程图（表格 / 文字）不附
    text = render.render_agent_md(source={'note': {'title': 't', 'body': 'b'}, 'comments': []},
        meta={'item_id': 'xhs-1', 'current_version': 1},
        vision={'images': [{'asset': 'image-001.webp', 'status': 'ok',
            'refined': {'status': 'ok', 'kind': 'table', 'text': '| a |\n|---|'}, 'lines': [{'text': '原文'}]}]})
    assert '<details>' not in text
