import time

import pytest

from link_brain import ask, retrieval, render


def recipe():
    # 字段字数仿 10-04 实测黑椒那篇（body 173 / 评论 988 / OCR 1904 / 转写 559，合计 3624）
    return {'id': 'recipe', 'title': '黑椒意面做法汇编', 'summary': '不是证据的概要', 'search_fields': {
        'body': '配方说明。' * 35, 'comments': '评论讲解面汤用法。' * 110,
        'ocr': '黑椒意面小贴士和配料。' * 173, 'transcript': '转写说明翻炒。' * 80}}


def test_deep_read_concentrates_budget_and_preserves_all_fields():
    item = recipe()
    pool = [item] + [{'id': str(index), 'title': '其他食物'} for index in range(10)]
    count, deep = ask.prompt_count('黑椒意面做法汇编讲了什么', pool, 8000, 8)
    assert (count, deep) == (1, True)
    old_budget = ask.evidence_budget(8000, 800, 11)
    assert old_budget < 800
    budget = ask.evidence_budget(8000, 800, count, deep)
    parts = retrieval.evidence(item, ['黑椒意面'], budget, deep=deep, max_parts=8)
    assert {part['field'] for part in parts} == {'body', 'comments', 'ocr', 'transcript'}
    assert sum(len(part['text']) for part in parts) == sum(map(len, item['search_fields'].values()))
    assert sum(len(part['text']) for part in parts) > 3500


def test_deep_read_long_fields_have_proportional_windows():
    item = recipe()
    item['search_fields'] = {key: text * 10 for key, text in item['search_fields'].items()}
    parts = retrieval.evidence(item, ['面汤'], 4000, deep=True, max_parts=8)
    assert len(parts) == 4
    assert sum(len(part['text']) for part in parts) <= 4000
    assert all(part['text'] in item['search_fields'][part['field']] for part in parts)


def test_deep_heuristic_and_failure(monkeypatch):
    pool = [{'title': '甲', '_fused_score': 2}, {'title': '乙', '_fused_score': 1}]
    assert ask.deep_read_wanted('不带标题', pool)
    pool[0]['_fused_score'] = 1.99
    assert not ask.deep_read_wanted('不带标题', pool)
    pool[0]['_fused_score'] = 'invalid'
    assert not ask.deep_read_wanted('不带标题', pool)
    monkeypatch.setattr(ask, 'deep_read_wanted', lambda *args: 1 / 0)
    assert ask.prompt_count('问', pool, 8000, 8) == (2, False)


@pytest.mark.parametrize('field,word', [('comments', '担担面'), ('transcript', '红烧牛肉'), ('ocr', '知识图谱')])
def test_majority_field_cannot_be_crowded_out(field, word):
    item = {'id': 'fact', 'search_fields': {'body': '无关开场。' * 20, field: (word + '独有事实。') * 250}}
    sem = {'fact': {'score': 1, 'chunks': [{'field': 'body', 'text': '无关开场。' * 100}]}}
    parts = retrieval.evidence(item, [word], 700, sem, max_parts=4)
    assert any(part['field'] == field and word in part['text'] for part in parts)
    assert sum(len(part['text']) for part in parts) <= 700


def test_evidence_new_path_error_falls_back(monkeypatch):
    item = recipe()
    old = retrieval._evidence(item, ['面汤'], 700)
    monkeypatch.setattr(retrieval, '_content_fields', lambda item: 1 / 0)
    assert retrieval.evidence(item, ['面汤'], 700, deep=True) == old


def test_related_cards_are_fast_verbatim_single_field(monkeypatch):
    monkeypatch.setattr(retrieval, 'semantic_hits', lambda *args: pytest.fail('no semantic calls'))
    items = [{**recipe(), 'id': str(index)} for index in range(361)]
    started = time.perf_counter()
    cards = [ask.related_card(item, index + 1, ['面汤']) for index, item in enumerate(items[:80])]
    elapsed = time.perf_counter() - started
    assert elapsed < .5
    assert all(card['excerpt'] and len(card['excerpt']) <= 120 for card in cards)
    assert all(card['excerpt'] in items[index]['search_fields'][card['excerpt_field']] for index, card in enumerate(cards))
    assert ask.related_card(items[0], 1, ['完全没有的词'])['excerpt'] == ''


def test_mermaid_keeps_raw_ocr_collapsed():
    text = render.render_agent_md(source={'note': {'title': '合成流程', 'body': '正文'}, 'comments': []},
        meta={}, vision={'images': [{'asset': 'image-001.webp', 'status': 'ok',
            'refined': {'status': 'ok', 'kind': 'diagram', 'text': '```mermaid\ngraph TD\nA-->B\n```'},
            'lines': [{'text': '小贴士：逆纹切条'}, {'text': '<script>不可信内容</script>'}]}]})
    assert '```mermaid' in text and '<details>' in text and '<summary>一层 OCR 原文' in text
    assert '小贴士：逆纹切条' in text
    assert '<script>' not in text


def test_production_deep_prompt_reads_all_fields(monkeypatch):
    item = recipe()
    monkeypatch.setattr(ask, 'load_items', lambda: [item])
    monkeypatch.setattr(retrieval, 'semantic_hits', lambda *args: None)
    monkeypatch.setattr(ask, 'llm_expansions', lambda *args, **kwargs: {'terms': [], 'status': 'mock'})
    seen = []
    monkeypatch.setattr(ask, 'call_text', lambda prompt, text, settings: seen.append(text) or {'status': 'ok', 'text': '回答[来源1]'})
    result = ask.answer('黑椒意面做法汇编讲了什么')
    assert result['status'] == 'ok'
    for field in item['search_fields']:
        assert f'[{field}]' in seen[-1]
    assert len(result['sources']) == 1
