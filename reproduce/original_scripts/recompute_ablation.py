from __future__ import annotations
import csv,sys,json,collections,pickle, math, statistics
from pathlib import Path
from functools import lru_cache
sys.path.insert(0,'/mnt/data/iko_final_work/project')
from src.pipeline import build_pipeline
from src.graph_retrieval import GraphIndex,phrase_in_text
from src.policy_catalog import allowed_sources
from src.v8_3_intent import route_intent
from src.retrieval import tokenize
root=Path('/mnt/data/iko_final_work/project');out=Path('/mnt/data/iko_final_work')
ret=build_pipeline(root/'data/research_corpus',170,45);g0=GraphIndex(root/'outputs/v6/iko_auto_five_insurers_v6.ttl',ret.chunks);g1=GraphIndex(root/'outputs/v8_2/iko_auto_extended_v8_2.ttl',ret.chunks)
idx={c.chunk_id:i for i,c in enumerate(ret.chunks)};source={c.chunk_id:c.source_path for c in ret.chunks}
with open(root/'H1_50_QUESTIONS_FOR_RETRIEVAL.csv',encoding='utf-8-sig',newline='') as f:h1=list(csv.DictReader(f))
with open(root/'IKO_Auto_V8_3_Frozen_Question_Pool/02_QUESTIONS_FOR_EVALUATION.jsonl',encoding='utf-8') as f:dev=[json.loads(x) for x in f if x.strip()]
qs=dev+h1;qmap={q['question_id']:q for q in qs}
with open(out/'qrels_revised.pkl','rb') as f:labelinfo=pickle.load(f)
qrels=labelinfo['merged']
per_q=collections.defaultdict(list)
for (qid,cid),rel in qrels.items():per_q[qid].append(rel)
plans={}
lexical={}
for q in qs:
 qid=q['question_id'];text=q['question']
 scores=ret._bm25.get_scores(tokenize(text));lex=[i for i in range(len(scores)) if scores[i]>0]
 lex.sort(key=lambda i:(-float(scores[i]),i))
 lexical[qid]=(scores,lex)
 for label,g in [('g0',g0),('g1',g1)]:plans[(qid,label)]=g.plan(text)

def one(q,method,lam=0.7,default_off=False,mode='weighted',score_only=False):
 qid=q['question_id'];strt=q['question'];ins=q['insurer'];scores,lexglobal=lexical[qid];allow=allowed_sources(ret.chunks,ins)
 if method=='M2':return [ret.chunks[i].chunk_id for i in lexglobal if ret.chunks[i].source_path in allow][:5]
 gl='g1' if method=='M7' else 'g1' if (method=='M8' and route_intent(strt,ins)['route']=='enhanced_v8_2') else 'g0'
 plan=plans[(qid,gl)]
 if plan.strict_no_match:return []
 lex=[i for i in lexglobal if plan.scoped_docs is None or ret.chunks[i].source_path in plan.scoped_docs]
 ranks={ret.chunks[i].chunk_id:1/(pos+1) for pos,i in enumerate(lex)}
 bm25={ret.chunks[i].chunk_id:float(scores[i]) for i in lex}
 gs=dict(plan.scores)
 if default_off:
  hascov=any(phrase_in_text(x,strt) for x in ['cover','covers','covered','coverage','eligible'])
  if not hascov:
   # Original planner only adds these coverage traces through the default branch.
   gs={cid:max((trace.weight for trace in plan.traces.get(cid,[]) if trace.relation!='hasCoverage'),default=0.0) for cid in gs}
   gs={cid:x for cid,x in gs.items() if x>0}
 candidates=set(ranks)|set(plan.scores if score_only else gs)
 if plan.scoped_docs is not None:candidates={cid for cid in candidates if source[cid] in plan.scoped_docs}
 if mode=='weighted':
  if not gs:vals={cid:round(ranks.get(cid,0),6) for cid in candidates}
  else:vals={cid:round(lam*gs.get(cid,0)+(1-lam)*ranks.get(cid,0),6) for cid in candidates}
  ordered=sorted(candidates,key=lambda cid:(-vals[cid],idx[cid]))
 elif mode=='lexical_first':
  # Priority to every positive-scoring BM25 candidate, then graph-only.
  ordered=sorted(candidates,key=lambda cid:(0,-bm25[cid],-gs.get(cid,0),idx[cid]) if cid in bm25 else (1,0,-gs.get(cid,0),idx[cid]))
 elif mode=='rrf':
  graph_pos=sorted({v for v in gs.values() if v>0},reverse=True)
  gr={v:1+sum(1 for c in gs if gs[c]>v) for v in graph_pos}
  vals={cid:(1/(60+round(1/ranks[cid])) if cid in ranks else 0) + (1/(60+gr[gs[cid]]) if gs.get(cid,0)>0 else 0) for cid in candidates}
  ordered=sorted(candidates,key=lambda cid:(-vals[cid],idx[cid]))
 else:raise ValueError(mode)
 return [cid for cid in ordered if source[cid] in allow][:5]
# verify original method ranks against original runner and control
with open(out/'baseline_runs.pkl','rb') as f:baseline=pickle.load(f)
for setname,qlist in [('dev',dev),('h1',h1)]:
 for m,n in [('M2','bm25_metadata'),('M5','bm25_metadata_graph'),('M7','bm25_metadata_graph_v8_2'),('M8','bm25_metadata_graph_intent_v8_3')]:
  mismatches=[q['question_id'] for q in qlist if one(q,m)!=baseline[setname][n][q['question_id']][:5]]
  print('baseline',setname,m,'mismatches',len(mismatches),mismatches[:8],flush=True)

def metric(qlist,rankings):
 per=[]
 for q in qlist:
  qid=q['question_id'];ids=rankings[qid];relev=[];missing=[]
  for cid in ids:
   if (qid,cid) not in qrels:missing.append(cid)
   relev.append(qrels.get((qid,cid),None))
  positive=[r==2 for r in relev]
  hit=float(any(positive))
  p5=sum(positive)/5
  mr=next((1/i for i,yes in enumerate(positive,1) if yes),0.)
  p1=float(positive[0]) if positive else 0.0
  dcg=sum((1/math.log2(i+1) if yes else 0) for i,yes in enumerate(positive,1))
  ideal=sum(1/math.log2(i+1) for i in range(1,min(5,sum(x==2 for x in per_q[qid]))+1))
  ndcg=dcg/ideal if ideal>0 else 0.0
  per.append(dict(qid=qid,hit=hit,p5=p5,mrr=mr,p1=p1,ndcg=ndcg,missing=len(missing),empty=int(not ids),n_returned=len(ids)))
 return ({key:sum(row[key] for row in per)/len(per) if key!='empty' and key!='missing' else sum(row[key] for row in per) for key in ['hit','p5','mrr','p1','ndcg','missing','empty']},per)
configs=[]
for m in ['M2','M5','M7','M8']:configs.append((m,dict(method=m)))
for m in ['M7','M8']:
 configs.extend([(f'{m}_default_off',dict(method=m,default_off=True)),(f'{m}_score_only',dict(method=m,default_off=True,score_only=True))])
 for mode in ['lexical_first','rrf']:
  configs.append((f'{m}_{mode}',dict(method=m,mode=mode)))
 for d in [False,True]:
  for lam in [0,0.1,0.3,0.5,0.7,1.0]:
   configs.append((f'{m}_lambda_{lam:.1f}_{"off" if d else "on"}',dict(method=m,lam=lam,default_off=d)))
rows=[];perrows=[];missingrows=[];allrank=[]
for setname,qlist in [('Development',dev),('H1',h1)]:
 for name,kwargs in configs:
  ranking={q['question_id']:one(q,**kwargs) for q in qlist}
  scores,per=metric(qlist,ranking)
  rows.append(dict(dataset=setname,condition=name,**scores))
  perrows.extend(dict(dataset=setname,condition=name,**x) for x in per)
  for q in qlist:
   qid=q['question_id']
   for i,cid in enumerate(ranking[qid],1):
    allrank.append(dict(dataset=setname,condition=name,question_id=qid,rank=i,chunk_id=cid,relevance=qrels.get((qid,cid),'')))
    if (qid,cid) not in qrels:missingrows.append((setname,name,qid,cid))
with open(out/'final_all_metrics.csv','w',encoding='utf-8',newline='') as f:
 wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
with open(out/'final_per_question_metrics.csv','w',encoding='utf-8',newline='') as f:
 wr=csv.DictWriter(f,fieldnames=list(perrows[0]));wr.writeheader();wr.writerows(perrows)
with open(out/'final_all_rankings.csv','w',encoding='utf-8',newline='') as f:
 wr=csv.DictWriter(f,fieldnames=list(allrank[0]));wr.writeheader();wr.writerows(allrank)
print('config count',len(configs),'rowcount',len(rows),'missing',len(missingrows),'uniquemissing',len(set((x[2],x[3]) for x in missingrows)))
for x in rows:
 if x['condition'] in ['M2','M5','M7','M8','M7_default_off','M8_default_off','M8_lexical_first','M8_rrf','M7_lambda_0.3_on','M8_lambda_0.3_on']:
  print(x['dataset'],x['condition'], 'Hit',round(x['hit'],3),'P',round(x['p5'],3),'MRR',round(x['mrr'],3),'P1',round(x['p1'],3),'nDCG',round(x['ndcg'],3),'missing',x['missing'])
if missingrows:
 print('MISSING',missingrows[:20])
