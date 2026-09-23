"""本机真实收藏评测；公开 fixture 只有问题与笔记 ID，不含内容和签名 URL。"""
import argparse,json,statistics,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from link_brain import ask
p=argparse.ArgumentParser();p.add_argument('--answers',action='store_true');p.add_argument('--out',required=True);a=p.parse_args()
items=ask.load_items();cases=json.loads((Path(__file__).parent/'fixtures/retrieval_bench.json').read_text(encoding='utf-8'))
results=[]
for case in cases:
 start=time.perf_counter();hits=ask.retrieve(items,ask.query_terms(case['question']))[:8];found={x['id'] for x in hits}
 results.append({**case,'recall_at_8':len(found.intersection(case['expected']))/len(case['expected']),'retrieval_ms':round((time.perf_counter()-start)*1000,2),'top8':[x['id'] for x in hits]})
timings=[]
if a.answers:
 for case in cases[:3]:
  start=time.perf_counter();first=[]
  r=ask.answer(case['question'],on_delta=lambda text:first.append(time.perf_counter()-start) if text and not first else None);elapsed=time.perf_counter()-start
  timings.append({'question':case['question'],'status':r['status'],'first_text_sec':round(first[0],3) if first else None,'total_sec':round(elapsed,3),'model_called':r.get('model_called')})
out={'note':'暂定工程评测题：会话和存档历史均为空，依据实际收藏构造，非 Owner 标注集。','recall_at_8':statistics.mean(x['recall_at_8'] for x in results),'results':results,'answer_timings':timings}
Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'recall_at_8':out['recall_at_8'],'timings':timings},ensure_ascii=False))
