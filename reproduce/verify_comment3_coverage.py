#!/usr/bin/env python3
"""Verify Reviewer 1 Comment 3 de-identified coverage and Development-only metrics.
Usage: python reproduce/verify_comment3_coverage.py
Runs from an IKO-Auto repository containing archived Development labels/rankings.
Does not verify source-PDF text because booklets are not redistributed in the release.
"""
import csv,collections,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(path):
 with open(ROOT/path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
ratings=load('labels/graph_coverage/COMMENT3_SUBMITTED_100_SUPPORT_LABELS.csv')
assert len(ratings)==100 and len({r['question_id'] for r in ratings})==100
n=collections.Counter()
for ds in ('Development','H1','Both'):
 rr=[r for r in ratings if ds=='Both' or r['dataset']==ds]
 z0=collections.Counter(r['g0_grade_submitted'] for r in rr)
 zp=collections.Counter(r['gplus_grade_submitted'] for r in rr)
 vals={'G0_direct':z0['2'],'G0_partial':z0['1'],'G0_none':z0['0'],
  'Gplus_direct':zp['2'],'Gplus_partial':zp['1'],'Gplus_none':zp['0'],
  'Source_grounding_Unclear_subset_of_none':sum(r['source_grounding_submitted']=='Unclear' for r in rr),'N':len(rr)}
 n[ds]=vals
 assert sum(z0.values())==len(rr) and sum(zp.values())==len(rr)
expected=load('results/graph_coverage/COMMENT3_GRAPH_SUPPORT_COUNTS.csv')
for r in expected:
 for k,v in n[r['Dataset']].items():assert int(r[k])==v,(r['Dataset'],k,r[k],v)
qids={r['question_id'] for r in ratings if r['dataset']=='Development' and r['gplus_grade_submitted']=='2' and r['g0_grade_submitted']=='0'}
assert len(qids)==5
relevance={(r['question_id'],r['chunk_id']):int(r['relevance']) for r in load('labels/development_adjudicated_519_public.csv')}
positive=collections.Counter()
for (q,ch),g in relevance.items():positive[q]+=g==2
ranks=collections.defaultdict(list)
for r in load('results/development/DEV_RANKINGS_PUBLIC.csv'):
 if r['question_id'] in qids and r['method'] in ('M2','M5','M7','M8'):
  key=(r['question_id'],r['chunk_id'])
  assert key in relevance,key
  ranks[(r['method'],r['question_id'])].append((int(r['rank']),relevance[key]))
check={r['Method']:r for r in load('results/graph_coverage/COMMENT3_FIVE_DIRECT_RETRIEVAL.csv')}
for method in ('M2','M5','M7','M8'):
 hit=p5=p1=mrr=ndcg=empty=0
 for q in qids:
  values=[g for rank,g in sorted(ranks[(method,q)]) if rank<=5]
  binary=[int(g==2) for g in values]
  empty+=not binary;hit+=any(binary);p5+=sum(binary)/5
  p1+=binary[0] if binary else 0
  mrr+=next((1/(i+1) for i,b in enumerate(binary) if b),0)
  dcg=sum(b/math.log2(i+2) for i,b in enumerate(binary))
  idcg=sum(1/math.log2(i+2) for i in range(min(positive[q],5)))
  ndcg+=dcg/idcg if idcg else 0
 ntest=len(qids)
 scores={'Hit@5':hit/ntest,'P@5':p5/ntest,'P@1':p1/ntest,'MRR@5':mrr/ntest,'Binary nDCG@5':ndcg/ntest,'Empty':empty,'N':ntest}
 for k,v in scores.items():assert abs(float(check[method][k])-v)<1e-5,(method,k,v,check[method][k])
 print(method,{k:round(v,5) for k,v in scores.items()})
print('PASS: 100 ratings, all coverage counts and the 5-question retrieval comparison')
