import io
import json
import httpx
from link_brain import ask, storage, text_stream, serve


def test_query_keeps_compound_and_single_character():
    terms=ask.query_terms('从收藏里整理蒜香鱼片的做法')
    assert '蒜香' in terms and '鱼片' in terms and '做法' not in terms
    assert ask.query_terms('鱼')==['鱼']


def test_excerpt_prefers_late_dense_evidence():
    from link_brain.retrieval import excerpts
    item={'search_fields':{'body':'蒜香'+('无关背景。'*300)+'鱼片蒜香鱼片蒜香，腌制十分钟，再下锅。'}}
    result=excerpts(item,['蒜香','鱼片','腌制'],240)
    assert '腌制十分钟' in result[0]['text']
    assert sum(len(x['text']) for x in result)<=240


def test_intent_does_not_turn_explanation_into_links():
    assert ask.detect_intent('给我根据原文解释所有步骤并提供链接')=='qa'


def test_catalog_mtime_invalidates_cache(tmp_path,monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT,str(tmp_path))
    p=tmp_path/'_archive/catalog-data.json'
    storage.write_json(p,{'items':[{'id':'old'}]})
    one=ask.load_items();assert ask.load_items() is one
    storage.write_json(p,{'items':[{'id':'updated'}]})
    assert ask.load_items()[0]['id']=='updated'


def test_sse_delivers_chunks_and_system_prompt(monkeypatch):
    seen=[]
    def handler(request):
        body=json.loads(request.content)
        assert body['stream'] is True and body['max_tokens']==1200
        assert body['messages'][0]=={'role':'system','content':'规则'}
        data='data: '+json.dumps({'choices':[{'delta':{'content':'你好'}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n'
        return httpx.Response(200,text=data)
    monkeypatch.setattr(text_stream,'_CLIENT',httpx.Client(transport=httpx.MockTransport(handler)))
    r=text_stream.http_call('规则','问题',{'model':'test','endpoint':'https://example.invalid'},seen.append)
    assert r['text']=='你好' and seen==['你好']


def test_stdio_worker_correlates_multiple_requests(monkeypatch,capsys):
    monkeypatch.setattr('sys.stdin',io.StringIO('{"id":"a","question":"a"}\n{"id":"b","question":"b"}\n'))
    def answer(q,h,i,on_delta):
        on_delta(q);return {'status':'ok','markdown':q}
    monkeypatch.setattr(ask,'answer',answer)
    assert serve.run(None)==0
    events=[json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [(e['id'],e['type']) for e in events]==[('a','start'),('a','delta'),('a','result'),('b','start'),('b','delta'),('b','result')]


def test_fable_retrieves_transcript_without_model(monkeypatch):
    from link_brain import retrieval
    items=[{'id':str(i),'title':'视频 '+str(i),'note':f'Web/{i}.md','search_fields':{'transcript':'蒜香鱼片腌制十分钟。'*200}} for i in range(10)]
    monkeypatch.setattr(ask,'load_items',lambda:items)
    monkeypatch.setattr(ask,'call_text',lambda *args:(_ for _ in ()).throw(AssertionError('must not call model')))
    r=retrieval.retrieve_payload('蒜香鱼片')
    assert r['model_called'] is False and len(r['results'])==8
    assert all(x['has_transcript'] and x['web_url'] and x['obsidian_url'] for x in r['results'])
    assert sum(len(p['text']) for x in r['results'] for p in x['excerpts'])<=2500


def test_format_instructions_and_hyphens_are_not_search_topics():
    terms=ask.query_terms('ai记忆项目-现有-给重要细节，请给我一级标题和二级标题的报告')
    assert '-' not in terms and '报告' not in terms and '重要' not in terms
    assert '记忆' in terms and '做梦' in ask.query_terms('AI做梦')
    assert ask.query_terms('请只根据收藏')==[]


def test_category_only_jokes_return_original_ending():
    from link_brain import retrieval
    item={'id':'joke','title':'一次误会','cats':['笑话'],'search_fields':{'body':'开始误会。'+('故事发展。'*100)+'原来是请她结婚。'}}
    assert retrieval.rank([item],ask.query_terms('列一下笑话'))[0][1]['id']=='joke'
    parts=retrieval.excerpts(item,['笑话'],200)
    assert '原来是请她结婚。' in parts[-1]['text']


def test_multitopic_candidates_keep_each_subject():
    from link_brain import retrieval
    items=[{'id':str(i),'title':'记忆项目','search_fields':{'body':'长期记忆系统'}} for i in range(10)]
    items += [{'id':'food','title':'空气炸锅菜谱'},{'id':'game','title':'Steam文字游戏'}]
    hits=retrieval.rank_query(items,'改善长期记忆；空气炸锅；Steam文字游戏，给我一级标题和二级标题的报告')[:8]
    assert {'food','game'}.issubset({it['id'] for _,it in hits})


def test_selector_obeys_validated_ids_and_does_not_stream_its_json(monkeypatch):
    items=[{'id':str(i),'title':'项目 '+str(i),'search_fields':{'body':'项目说明'}} for i in range(5)]
    def model(prompt,text,settings):
        assert ask._ON_DELTA.get() is None
        assert settings['textAI']['responseFormat']=={'type':'json_object'}
        return {'status':'ok','text':'{"selected":[3,1,3]}'}
    monkeypatch.setattr(ask,'call_text',model)
    chosen,count=ask._select_sources('推荐项目',items,['项目'],{'textAI':{}},5)
    assert [it['id'] for it in chosen]==['2','0'] and count==5


def test_output_limit_is_not_silently_complete(monkeypatch):
    def handler(request):
        payload={'choices':[{'delta':{'content':'未完'},'finish_reason':'length'}]}
        return httpx.Response(200,text='data: '+json.dumps(payload)+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(text_stream,'_CLIENT',httpx.Client(transport=httpx.MockTransport(handler)))
    r=text_stream.http_call('规则','问题',{'endpoint':'https://example.invalid','model':'test'})
    assert r['truncated'] is True
