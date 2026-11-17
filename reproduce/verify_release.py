#!/usr/bin/env python3
"""Recompute paper-facing metrics from text-minimized ranking and qrel exports.

No source policy PDFs or reviewer-identity files needed. Python standard library.
For full PDF->ranking reproduction, obtain original third-party corpus separately.
"""
import argparse, csv, json, hashlib, math, sys
from pathlib import Path
from collections import defaultdict, Counter
ROOT=Path(__file__).resolve().parent.parent

def records(rel):
 with (ROOT/rel).open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def read_labels(rel):
 d={}
 for r in records(rel):
  key=(r['question_id'],r['chunk_id']);val=int(r['relevance'])
  if key in d and d[key]!=val:raise ValueError('Conflicting grade for '+str(key))
  d[key]=val
 return d

def measure(qids,rank_rows,labels):
 by=defaultdict(list)
 for r in rank_rows:
  if not r.get('chunk_id') or int(r['rank'])<=0:continue
  by[r['question_id']].append((int(r['rank']),r['chunk_id']))
 pos=defaultdict(int)
 for (q,c),g in labels.items():
  if g==2:pos[q]+=1
 stats={k:0 for k in ['hit5','p5','p1','mrr5','ndcg5','empty']}
 for q in qids:
  order=[cid for _,cid in sorted(by.get(q,[]))][:5]
  gr=[labels.get((q,c),None) for c in order]
  if None in gr:raise ValueError(f'Unjudged returned passage {q}: {order}')
  bits=[x==2 for x in gr]
  stats['hit5']+=int(any(bits))
  stats['p5']+=sum(bits)/5
  stats['p1']+=int(bits[0]) if bits else 0
  stats['mrr5']+=next((1/(i+1) for i,b in enumerate(bits) if b),0)
  dcg=sum((1/math.log2(i+2) if b else 0) for i,b in enumerate(bits))
  ideal=sum(1/math.log2(i+2) for i in range(min(5,pos[q])))
  stats['ndcg5']+=dcg/ideal if ideal else 0
  stats['empty']+=int(not order)
 for k in stats:
  if k!='empty':stats[k]/=len(qids)
 return stats

def near(a,b,tol=.0006):
 if abs(float(a)-float(b))>tol:raise AssertionError(f'Metric mismatch: calculated={a}, archived={b}')

def historic(kind):
 qpath=f'questions/{"development_questions_50.csv" if kind=="development" else "h1_questions_50.csv"}'
 lpath=f'labels/{"development_adjudicated_519_public.csv" if kind=="development" else "h1_adjudicated_533_public.csv"}'
 rpath=f'results/{kind}/{"DEV_RANKINGS_PUBLIC.csv" if kind=="development" else "H1_RANKINGS_PUBLIC.csv"}'
 apath=f'results/{kind}/{"DEV_EIGHT_METHODS.csv" if kind=="development" else "H1_FINAL_EIGHT_METHODS.csv"}'
 qids=[q['question_id'] for q in records(qpath)]
 labels=read_labels(lpath)
 ranked=records(rpath)
 assert len(qids)==50
 assert len(labels)==(519 if kind=='development' else 533)
 archived={r['method']:r for r in records(apath)}
 print('\n'+kind.upper()+' 50 questions / '+str(len(labels))+' labels')
 for m in [f'M{i}' for i in range(1,9)]:
  s=measure(qids,[r for r in ranked if r['method']==m],labels)
  a=archived[m]
  if kind=='development':
   print(' ',m,'Hit',round(s['hit5'],3),'MRR',round(s['mrr5'],3),'nDCG',round(s['ndcg5'],3))
  else:
   near(s['hit5'],a['hit5']);near(s['p5'],a['precision5'])
   near(s['mrr5'],a['mrr5']);near(s['ndcg5'],a['ndcg5'])
   if int(s['empty'])!=int(a['empty_questions']):raise AssertionError((m,'empty',s,a))
   print(' ',m,'Hit',round(s['hit5'],3),'MRR',round(s['mrr5'],3),'nDCG',round(s['ndcg5'],3))
 # Development aggregate source may use different abbreviated keys; assert gold control values.
 if kind=='development':
  for m,h,mrr in [('M2',0.440,0.414),('M5',0.380,0.170),('M8',0.440,0.230)]:
   s=measure(qids,[r for r in ranked if r['method']==m],labels)
   near(s['hit5'],h);near(s['mrr5'],mrr)


def fusion():
 qs={x['question_id'] for x in records('questions/development_questions_50.csv')}
 hs={x['question_id'] for x in records('questions/h1_questions_50.csv')}
 ranked=records('results/fusion/final_all_rankings.csv')
 aggregate=records('results/fusion/final_all_metrics.csv')
 labels=read_labels('labels/fusion_expanded_relevance_public.csv')
 assert sum(q in qs for q,c in labels)==658
 assert sum(q in hs for q,c in labels)==667
 print('\nFUSION 658 Development / 667 H1 labeled pairs')
 for a in aggregate:
  d=a['dataset'];cond=a['condition'];qids=qs if d=='Development' else hs
  rs=[r for r in ranked if r['dataset']==d and r['condition']==cond]
  for r in rs:
   if labels[(r['question_id'],r['chunk_id'])]!=int(r['relevance']):raise AssertionError('Fusion label mismatch')
  s=measure(qids,rs,labels)
  for k,col in [('hit5','hit'),('p5','p5'),('mrr5','mrr'),('p1','p1'),('ndcg5','ndcg')]:
   near(s[k],a[col],tol=1e-8)
  if int(s['empty'])!=int(a['empty']):raise AssertionError((d,cond,'empty'))
  if cond in {'M2','M7','M8','M7_default_off','M8_default_off','M7_lexical_first','M8_lexical_first','M8_rrf'}:
   print(' ',d,cond,'Hit',round(s['hit5'],3),'P1',round(s['p1'],3),'MRR',round(s['mrr5'],3))
 print(' full weight grid:',len(aggregate),'metric rows verified')


def gate():
 qs=records('questions/GATE26_50_Candidate_Questions.csv')
 routing=records('labels/gate/final_routing_gold.csv')
 labels=read_labels('labels/gate/final_passage_labels.csv')
 ranks=records('results/gate/GATE26_Original_Method_Rankings.csv')
 metrics=records('results/gate/retrieval_results_by_expert_topic.csv')
 assert len(qs)==50 and len(routing)==50 and len(labels)==327
 grounded=[r for r in routing if r['Grounded']=='Yes']
 assert len(grounded)==48
 c=Counter()
 for r in grounded:
  expected=r['ExtensionRelevant']=='Yes'
  predicted=r['predicted_route']=='enhanced_v8_2'
  c['TP' if expected and predicted else 'FP' if not expected and predicted else 'FN' if expected else 'TN']+=1
 gold=json.loads((ROOT/'results/gate/gate_accuracy_and_agreement.json').read_text())
 assert c==gold['confusion'],(c,gold['confusion'])
 assert c=={'TP':24,'FP':4,'FN':1,'TN':19}
 print('\nGATE 50 questions / 48 grounded / 327 grades, confusion:',dict(c))
 for subset in ['all_valid','expert_Gplus_topic','expert_other_topic']:
  if subset=='all_valid':qids={r['question_id'] for r in grounded}
  elif subset=='expert_Gplus_topic':qids={r['question_id'] for r in grounded if r['ExtensionRelevant']=='Yes'}
  else:qids={r['question_id'] for r in grounded if r['ExtensionRelevant']=='No'}
  for m in ['M2','M5','M7','M8']:
   a=next((r for r in metrics if r['method']==m and r['subset']==subset),None)
   if a is None: raise KeyError((m,subset,[r['subset'] for r in metrics]))
   s=measure(qids,[r for r in ranks if r['method']==m],labels)
   for key,col in [('hit5','Hit5'),('p5','P5'),('p1','P1'),('mrr5','MRR5'),('ndcg5','nDCG5')]: near(s[key],a[col],tol=1e-8)
   assert int(s['empty'])==int(a['empty'])
   if subset=='all_valid': print(' ',m,'Hit',round(s['hit5'],3),'MRR',round(s['mrr5'],3),'Empty',s['empty'])
 print(' all 12 gate diagnostic comparison rows verified')


def manifest():
 p=ROOT/'PUBLIC_ARTIFACT_MANIFEST.json'
 data=json.loads(p.read_text())
 for rel,expected in data['sha256'].items():
  f=ROOT/rel
  if not f.is_file():raise FileNotFoundError(rel)
  actual=hashlib.sha256(f.read_bytes()).hexdigest()
  if actual!=expected:raise AssertionError(f'Checksum mismatch: {rel}')
 files={str(f.relative_to(ROOT).as_posix()) for f in ROOT.rglob('*') if f.is_file() and f!=p}
 assert files==set(data['sha256']),(files-set(data['sha256']),set(data['sha256'])-files)
 print('SHA-256 verified:',len(files),'files')

if __name__=='__main__':
 ar=argparse.ArgumentParser()
 ar.add_argument('--section',choices=['all','development','h1','fusion','gate','manifest'],default='all')
 args=ar.parse_args()
 if args.section in ('all','manifest'):manifest()
 if args.section in ('all','development'):historic('development')
 if args.section in ('all','h1'):historic('h1')
 if args.section in ('all','fusion'):fusion()
 if args.section in ('all','gate'):gate()
 print('\nPASS',args.section)
