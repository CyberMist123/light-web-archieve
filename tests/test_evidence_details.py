from link_brain.retrieval import excerpts


def test_deep_topic_section_beats_generic_ai_introduction():
    item = {'search_fields': {
        'body': 'AI 系统项目介绍。' * 100,
        'attachments': ('AI 系统拥有记忆，会做梦。' * 100
                        + '\n8. Dream 做梦\n距上次梦超过20小时，距用户最后说话超过3小时，一日一次。'
                        + '素材来自近期聊天和重要记忆。' * 15),
    }}
    result = excerpts(item, ['ai', '系统', '做梦'], 800)
    assert result[0]['field'] == 'attachments'
    assert '超过20小时' in result[0]['text']
    assert sum(len(part['text']) for part in result) <= 800


def test_ocr_dream_details_are_not_replaced_by_body_feature_list():
    item = {'search_fields': {
        'body': 'AI系统介绍\n8. Dream Context\n仅列出更新功能。',
        'ocr': ('AI系统介绍与使用方法。' * 100
                + '\n11 | Dream、MCP 工具\n梦分成两层，可配置 gateway / breath 是否参与共振。'
                + '这是图片里的细节。' * 15),
    }}
    result = excerpts(item, ['ai', '系统', '做梦'], 800)
    assert any('是否参与共振' in part['text'] for part in result)


def test_generic_only_query_still_has_evidence():
    result = excerpts({'search_fields': {'body': 'AI系统提供本地搜索和可编辑笔记。'}}, ['ai', '系统'], 200)
    assert '本地搜索' in result[0]['text']


def test_short_author_post_keeps_adjacent_update_context():
    body = '1. 做梦新增小睡，换窗口触发。\n' + '其他更新说明。' * 25 + '\n2. Dream 做梦\n夜间自动建边和剪枝。'
    result = excerpts({'search_fields': {'body': body}}, ['做梦'], 500)
    assert result[0]['text'] == body
    assert len(result) == 1
