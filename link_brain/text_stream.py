"""收藏问答的流式文本调用；凭据只读内存，不记录请求或鉴权。"""
import csv
import io
import json
import os
from pathlib import Path
import httpx
from . import llm

_CLIENT = httpx.Client(timeout=httpx.Timeout(120, connect=15))


def default_http_config(cfg):
    key = os.environ.get('DASHSCOPE_API_KEY', '').strip()
    base = os.environ.get('DASHSCOPE_OPENAI_BASE', '').strip()
    paths = sorted(Path(os.environ.get('LINK_BRAIN_MODELS_DIR', r'D:\AI\models')).glob('千问*apiKey*.csv'))
    if not key and paths:
        raw = paths[0].read_bytes()
        text = raw.decode('utf-8-sig') if raw.startswith(b'\xef\xbb\xbf') else raw.decode('gbk')
        data = {r[0].strip(): r[1].strip() for r in csv.reader(io.StringIO(text)) if len(r)>=2}
        key = data.get('apiKey','');base = base or data.get('openAiCompatible','')
    return {**cfg, 'apiKey':key, 'endpoint':(base or 'https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')+'/chat/completions',
            'model':cfg.get('model') or llm.load_config()['model']}


def call(instruction, text, cfg, on_delta=None):
    if cfg.get('mode') != 'http' or not cfg.get('endpoint'):
        cfg=default_http_config(cfg)
    return http_call(instruction,text,cfg,on_delta)


def http_call(instruction,text,cfg,on_delta=None):
    cfg = dict(cfg)
    if cfg.get('keyFile'):
        try:
            raw = Path(cfg['keyFile']).read_bytes()
            text_csv = raw.decode('utf-8-sig') if raw.startswith(b'\xef\xbb\xbf') else raw.decode('gbk')
            data = {r[0].strip():r[1].strip() for r in csv.reader(io.StringIO(text_csv)) if len(r)>=2}
            cfg['apiKey'] = data.get(cfg.get('keyField') or 'apiKey', '')
        except (OSError, UnicodeError):
            return {'status':'failed','error':'无法读取已配置的仓外密钥文件'}
    headers={'Content-Type':'application/json'}
    if cfg.get('apiKey'):headers['Authorization']='Bearer '+cfg['apiKey'].strip()
    body={'model':cfg.get('model') or llm.load_config().get('answer_model') or llm.load_config()['model'],
          'messages':[{'role':'system','content':instruction},{'role':'user','content':text}],
          'max_tokens':int(cfg.get('maxTokens') or 1200),'stream':True,'temperature':.3}
    if body['model'].startswith('deepseek'):
        body['thinking']={'type':'enabled' if cfg.get('thinking') else 'disabled'}
        if cfg.get('thinking'):body['reasoning_effort']='low'
    if cfg.get('responseFormat'):
        body['response_format']=cfg['responseFormat']
    chunks=[];usage=None;finish_reason=None
    try:
        with _CLIENT.stream('POST',cfg['endpoint'],headers=headers,json=body) as response:
            if response.status_code>=400:
                return {'status':'failed','error':f'模型接口 HTTP {response.status_code}；请检查模型权限或配置'}
            for line in response.iter_lines():
                if not line.startswith('data:'):continue
                data=line[5:].strip()
                if data=='[DONE]':break
                event=json.loads(data)
                if event.get('error'):return {'status':'failed','error':'模型流返回错误，回答未完成'}
                usage=event.get('usage') or usage
                choice=(event.get('choices') or [{}])[0]
                finish_reason=choice.get('finish_reason') or finish_reason
                delta=(choice.get('delta') or {}).get('content') or ''
                if delta:
                    chunks.append(delta)
                    if on_delta:on_delta(delta)
        return {'status':'ok','text':''.join(chunks),'usage':usage,'truncated':finish_reason=='length'}
    except (httpx.HTTPError,ValueError) as exc:
        return {'status':'failed','error':'模型连接失败：'+type(exc).__name__}
