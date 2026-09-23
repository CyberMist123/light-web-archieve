"""本机真实收藏评测；公开 fixture 只有问题与笔记 ID，不含内容和签名 URL。

18 题金标（暂定工程题）+ paraphrase 集（换个说法，不冒充金标）。
词法 = ask.retrieve（纯 BM25）；hybrid = retrieval.rank_query（有 semantic.db + key 时
自动混排，否则退词法，两列数字相同即代表语义层未激活）。
"""
import argparse,json,statistics,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from link_brain import ask
from link_brain.retrieval import rank_query,semantic_hits
p=argparse.ArgumentParser();p.add_argument('--answers',action='store_true');p.add_argument('--out',required=True);a=p.parse_args()
items=ask.load_items();cases=json.loads((Path(__file__).parent/'fixtures/retrieval_bench.json').read_text(encoding='utf-8'))
gold=[c for c in cases if c.get('set')!='paraphrase'];para=[c for c in cases if c.get('set')=='paraphrase']

def bench(group):
 rows=[]
 for case in group:
  start=time.perf_counter();hits=ask.retrieve(items,ask.query_terms(case['question']))[:8];lex_ms=round((time.perf_counter()-start)*1000,2)
  start=time.perf_counter();hyb=[it for _,it in rank_query(items,case['question'])][:8];hyb_ms=round((time.perf_counter()-start)*1000,2)
  expected=set(case['expected'])
  rows.append({**case,
   'recall_at_8':len({x['id'] for x in hits}&expected)/len(expected),
   'hybrid_recall_at_8':len({x['id'] for x in hyb}&expected)/len(expected),
   'retrieval_ms':lex_ms,'hybrid_ms':hyb_ms,
   'top8':[x['id'] for x in hits],'hybrid_top8':[x['id'] for x in hyb]})
 return rows

results=bench(gold);para_results=bench(para)
semantic_active=semantic_hits(gold[0]['question']) is not None if gold else False
timings=[]
if a.answers:
 for case in gold[:3]:
  start=time.perf_counter();first=[]
  r=ask.answer(case['question'],on_delta=lambda text:first.append(time.perf_counter()-start) if text and not first else None);elapsed=time.perf_counter()-start
  timings.append({'question':case['question'],'status':r['status'],'first_text_sec':round(first[0],3) if first else None,'total_sec':round(elapsed,3),'model_called':r.get('model_called')})
summary={'recall_at_8':statistics.mean(x['recall_at_8'] for x in results),
 'hybrid_recall_at_8':statistics.mean(x['hybrid_recall_at_8'] for x in results),
 'paraphrase_recall_at_8':statistics.mean(x['recall_at_8'] for x in para_results) if para_results else None,
 'paraphrase_hybrid_recall_at_8':statistics.mean(x['hybrid_recall_at_8'] for x in para_results) if para_results else None,
 'semantic_active':semantic_active}
out={'note':'暂定工程评测题：金标依据实际收藏构造，非 Owner 标注集；paraphrase 集是换说法探针，不冒充金标。',
 **summary,'results':results,'paraphrase_results':para_results,'answer_timings':timings}
Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({**summary,'timings':timings},ensure_ascii=False))
