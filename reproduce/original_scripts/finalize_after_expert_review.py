#!/usr/bin/env python3
"""Finalize gate diagnostic ONLY after both experts return complete blind labels.

Usage:
  python finalize_after_expert_review.py --eu-route ...xlsx --bk-route ...xlsx \
     --eu-passages ...xlsx --bk-passages ...xlsx \
     [--route-adjudicated ./routing_resolution.csv] \
     [--passage-adjudicated ./passage_resolution.csv] --out-dir ./final_analysis

This script never guesses unresolved labels. Each file is checked against the
frozen question and passage pool. Disagreement reports must be resolved by a
human before scoring; no auto adjudication.
"""
from __future__ import annotations
import argparse,csv,json,math,statistics,hashlib,collections,sys
from pathlib import Path
from openpyxl import load_workbook
ROOT=Path(__file__).resolve().parent

def csvread(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def csvwrite(path,rows,fields=None):
 if fields is None:fields=list(rows[0]) if rows else []
 with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def xread(p,tab,keys,valcols,master):
 wb=load_workbook(p,read_only=True,data_only=True);ws=wb[tab];ws.reset_dimensions()
 result={};errors=[]
 for ridx,row in enumerate(ws.iter_rows(min_row=2,values_only=True),2):
  if not row or row[0] is None:continue
  key=tuple(str(row[i]).strip() for i in keys)
  if key not in master:errors.append(f'Unknown key {key} in {p} row {ridx}');continue
  if key in result:errors.append(f'Duplicate key {key} in {p} row {ridx}');continue
  result[key]={c:str(row[i]).strip() if len(row)>i and row[i] is not None else '' for c,i in valcols.items()}
 if set(result)!=set(master):errors.append(f'{p} misses {len(set(master)-set(result))} and has {len(set(result)-set(master))} extra rows')
 if errors:raise ValueError('\n'.join(errors[:12]))
 return result

def kappa(a,b):
 assert len(a)==len(b)>0;n=len(a)
 p=sum(x==y for x,y in zip(a,b))/n
 ca=collections.Counter(a);cb=collections.Counter(b)
 pc=sum(ca[k]*cb[k] for k in set(a)|set(b))/n**2
 if pc>=1:return 1 if p>=1 else None
 return (p-pc)/(1-pc)

def adjudicate(rows,path,key_cols,value_col,valid):
 if not rows:return{}
 if not path:return None
 data=csvread(path)
 pairs={tuple(row[k] for k in key_cols):row.get(value_col,'').strip() for row in data}
 need={tuple(row[k] for k in key_cols) for row in rows}
 if set(pairs)!=need:raise ValueError(f'{path} must contain exactly the {len(need)} disputed keys')
 if not set(pairs.values()).issubset(valid):raise ValueError(f'Invalid resolution value in {path}')
 return pairs

def run(args):
 out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
 qrows=csvread(ROOT/'GATE26_50_Candidate_Questions.csv')
 qmap={(x['question_id'],):x for x in qrows}
 pool=csvread(ROOT/'GATE26_Union_Passage_Pool_NO_LABELS.csv')
 pmap={(x['question_id'],x['chunk_id']):x for x in pool}
 routes={x['question_id']:x for x in csvread(ROOT/'GATE26_Gate_Predictions_NOT_FOR_REVIEWERS.csv')}
 runs=csvread(ROOT/'GATE26_Original_Method_Rankings.csv')
 qvals={'Grounded':3,'ExtensionRelevant':4}
 A=xread(args.eu_route,'Routing Labels',[0],qvals,qmap)
 B=xread(args.bk_route,'Routing Labels',[0],qvals,qmap)
 P=xread(args.eu_passages,'Passage Grades',[0,3],{'Grade':7},pmap)
 Q=xread(args.bk_passages,'Passage Grades',[0,3],{'Grade':7},pmap)
 missing=[]
 for qid in qmap:
  for name,R in [('EU',A),('BK',B)]:
   for field in ('Grounded','ExtensionRelevant'):
    if R[qid][field] not in ('Yes','No','Unclear'):missing.append(f'Routing {name} {qid} {field}')
 for k in pmap:
  for name,R in [('EU',P),('BK',Q)]:
   if R[k]['Grade'] not in ('0','1','2'):missing.append(f'Passage {name} {k}')
 if missing:
  (out/'INCOMPLETE_INPUTS.txt').write_text('\n'.join(missing),encoding='utf-8')
  raise ValueError(f'{len(missing)} missing/invalid assessments. See INCOMPLETE_INPUTS.txt; no performance metrics computed.')
 rg=[];pg=[]
 for (id,),q in qmap.items():
  for field in ('Grounded','ExtensionRelevant'):
   if A[(id,)][field]!=B[(id,)][field]:rg.append(dict(question_id=id,field=field,EU=A[(id,)][field],BK=B[(id,)][field],final_value=''))
 for k,p in pmap.items():
  if P[k]['Grade']!=Q[k]['Grade']:pg.append(dict(question_id=k[0],chunk_id=k[1],EU=P[k]['Grade'],BK=Q[k]['Grade'],final_grade=''))
 csvwrite(out/'routing_disagreements_for_adjudication.csv',rg,['question_id','field','EU','BK','final_value'])
 csvwrite(out/'passage_disagreements_for_adjudication.csv',pg,['question_id','chunk_id','EU','BK','final_grade'])
 rv=adjudicate(rg,args.route_adjudicated,('question_id','field'),'final_value',{'Yes','No','Unclear'})
 pv=adjudicate(pg,args.passage_adjudicated,('question_id','chunk_id'),'final_grade',{'0','1','2'})
 if rv is None or pv is None:
  raise ValueError(f'Unresolved disagreements: routing={len(rg)}, passage={len(pg)}. Explicit human adjudication is required; see CSV templates.')
 gold_q={}
 for (id,),q in qmap.items():
  g={field:(rv.get((id,field),A[(id,)][field])) for field in ('Grounded','ExtensionRelevant')}
  gold_q[id]=g
 grade={}
 for k in pmap:grade[k]=int(pv.get(k,P[k]['Grade']))
 valid=[id for id,d in gold_q.items() if d['Grounded']=='Yes']
 sem=[id for id in valid if gold_q[id]['ExtensionRelevant'] in ('Yes','No')]
 cm={'TP':0,'FP':0,'TN':0,'FN':0}
 for id in sem:
  actual=gold_q[id]['ExtensionRelevant']=='Yes';pred=routes[id]['gate_route']=='enhanced_v8_2'
  cm['TP' if actual and pred else 'FN' if actual else 'FP' if pred else 'TN']+=1
 denom=lambda n,d:n/d if d else None
 gate=dict(n_all=len(qrows),n_grounded=len(valid),n_scored=len(sem),n_unclear_or_invalid=len(qrows)-len(sem),confusion=cm,precision=denom(cm['TP'],cm['TP']+cm['FP']),recall=denom(cm['TP'],cm['TP']+cm['FN']),specificity=denom(cm['TN'],cm['TN']+cm['FP']),false_positive_rate=denom(cm['FP'],cm['TN']+cm['FP']),routing_agreement=kappa([A[k]['ExtensionRelevant'] for k in qmap],[B[k]['ExtensionRelevant'] for k in qmap]),routing_exact_agreement=sum(A[k]['ExtensionRelevant']==B[k]['ExtensionRelevant'] for k in qmap)/len(qmap),passage_kappa=kappa([int(P[k]['Grade']) for k in pmap],[int(Q[k]['Grade']) for k in pmap]),passage_exact_agreement=sum(P[k]['Grade']==Q[k]['Grade'] for k in pmap)/len(pmap),n_passage_pairs=len(pmap))
 (out/'gate_accuracy_and_agreement.json').write_text(json.dumps(gate,indent=2),encoding='utf-8')
 csvwrite(out/'final_routing_gold.csv',[{'question_id':id,**d,'predicted_route':routes[id]['gate_route'],'topic':routes[id]['gate_topic']} for id,d in gold_q.items()])
 csvwrite(out/'final_passage_labels.csv',[{'question_id':k[0],'chunk_id':k[1],'relevance':v} for k,v in grade.items()])
 # Calculate metrics ONLY for human-validated questions. All returned passages are grade-resolved.
 group=collections.defaultdict(list)
 for row in runs:
  group[(row['method'],row['question_id'])].append(row)
 per=[]
 for method in ('M2','M5','M7','M8'):
  for id in valid:
   ids=[r['chunk_id'] for r in sorted(group[(method,id)],key=lambda x:int(x['rank'])) if r['chunk_id']]
   ratings=[grade[(id,c)] for c in ids]
   binr=[int(v==2) for v in ratings]
   hits=sum(binr)>0
   rr=next((1/(i+1) for i,x in enumerate(binr) if x),0.0)
   dcg=sum(x/math.log2(i+2) for i,x in enumerate(binr))
   total=sum(int(v==2) for (qi,c),v in grade.items() if qi==id)
   ideal=sum(1/math.log2(i+2) for i in range(min(5,total)))
   n=dcg/ideal if ideal else 0.0
   per.append(dict(method=method,question_id=id,expert_extension_relevant=gold_q[id]['ExtensionRelevant'],hit5=int(hits),p5=sum(binr)/5,p1=binr[0] if binr else 0,mrr5=rr,ndcg5=n,empty=int(len(ids)==0),n_results=len(ids)))
 csvwrite(out/'per_question_retrieval_metrics.csv',per)
 grouped=collections.defaultdict(list)
 for row in per:
  grouped[(row['method'],'all_valid')].append(row)
  if row['expert_extension_relevant']=='Yes':grouped[(row['method'],'expert_Gplus_topic')].append(row)
  if row['expert_extension_relevant']=='No':grouped[(row['method'],'expert_other_topic')].append(row)
 agg=[]
 for (method,sub),rows in sorted(grouped.items()):
  agg.append(dict(method=method,subset=sub,n_questions=len(rows),Hit5=statistics.mean(x['hit5'] for x in rows),P5=statistics.mean(x['p5'] for x in rows),P1=statistics.mean(x['p1'] for x in rows),MRR5=statistics.mean(x['mrr5'] for x in rows),nDCG5=statistics.mean(x['ndcg5'] for x in rows),empty=sum(x['empty'] for x in rows)))
 csvwrite(out/'retrieval_results_by_expert_topic.csv',agg)
 print(json.dumps({'routing':gate,'retrieval_metrics_rows':len(agg),'scored_valid_questions':len(valid)},indent=2))

if __name__=='__main__':
 ap=argparse.ArgumentParser()
 for key in ('eu-route','bk-route','eu-passages','bk-passages'):ap.add_argument('--'+key,required=True)
 ap.add_argument('--route-adjudicated');ap.add_argument('--passage-adjudicated');ap.add_argument('--out-dir',default=str(ROOT/'final_analysis'))
 run(ap.parse_args())
