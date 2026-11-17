from pathlib import Path
import sys,csv,json,collections,difflib,hashlib,pickle
from openpyxl import load_workbook
sys.path.insert(0,'/mnt/data/iko_final_work/project')
from src.pipeline import build_pipeline
root=Path('/mnt/data/iko_final_work/project');out=Path('/mnt/data/iko_final_work'); ret=build_pipeline(root/'data/research_corpus',170,45)
byid={c.chunk_id:c for c in ret.chunks}
questions=[]
with open(root/'H1_50_QUESTIONS_FOR_RETRIEVAL.csv',encoding='utf-8-sig',newline='') as f:questions+=list(csv.DictReader(f))
with open(root/'IKO_Auto_V8_3_Frozen_Question_Pool/02_QUESTIONS_FOR_EVALUATION.jsonl',encoding='utf-8') as f:questions += [json.loads(x) for x in f if x.strip()]
qm={x['question']:x['question_id'] for x in questions}
by=collections.defaultdict(list)
for c in ret.chunks:by[(c.source_path,c.page,c.text)].append(c.chunk_id)

def read_reviews(path):
 w=load_workbook(path,read_only=True); ws=w['Review']; ws.reset_dimensions(); return [r for r in ws.values][1:]
a=read_reviews('/mnt/data/IKO_Auto_Blind_Review_Author_A(1).xlsx'); b=read_reviews('/mnt/data/IKO_Auto_Blind_Review_Author_B(1).xlsx')
assert len(a)==len(b)==301
new={};reasons={};aud=[]
for x,y in zip(a,b):
 rid,ins,q,source,page,txt,grA,rsn,initial=x
 assert x[:6]==y[:6] and grA==y[6] and grA in (0,1,2)
 qid=qm[q]
 matches=by[(source,int(page),txt)]
 quality='exact';sim=1
 if not matches:
  can=sorted([(difflib.SequenceMatcher(None,txt,c.text,autojunk=False).ratio(),c.chunk_id) for c in ret.chunks if c.source_path==source and c.page==int(page)],reverse=True)
  if not can or can[0][0]<0.99 or (len(can)>1 and can[0][0]-can[1][0]<0.1):raise ValueError((rid,can[:2]))
  matches=[can[0][1]]; quality='near-exact';sim=can[0][0]
 assert len(matches)==1
 k=(qid,matches[0]);
 if k in new and new[k]!=grA:raise ValueError((rid,k,new[k],grA))
 new[k]=grA
 reasons[k]=(rid,quality,sim)
 aud.append(dict(annotation_id=rid,question_id=qid,chunk_id=matches[0],grade=int(grA),match_type=quality,similarity=round(sim,6)))
old={}
with open(root/'H1_SOURCE_INPUTS/H1_FINAL_ADJUDICATED_RELEVANCE_533.csv',newline='',encoding='utf-8-sig') as f:
 for x in csv.DictReader(f):
  k=x['question_id'],x['chunk_id'];old[k]=int(x['relevance']);assert x['text']==byid[x['chunk_id']].text
with open(root/'IKO_Auto_V8_3_Frozen_Question_Pool/IKO_Auto_Recalculated_Results/IKO_Auto_Recalculated_Rank_Details.csv',encoding='utf-8-sig',newline='') as f:
 for x in csv.DictReader(f):
  k=x['question_id'],x['chunk_id'];v=int(x['relevance'])
  assert k not in old or old[k]==v
  old[k]=v
old_dev={k:v for k,v in old.items() if k[0].startswith('V8')}; old_h1={k:v for k,v in old.items() if k[0].startswith('H1')}
overlap={k:(old[k],new[k]) for k in new if k in old};diff={k:v for k,v in overlap.items() if v[0]!=v[1]}
print('orig qrels',len(old_dev),len(old_h1),'old total',len(old))
print('new keys',len(new),'overlap',len(overlap),'diff',len(diff),'new adds',len(new)-len(overlap))
print('by set',collections.Counter(k[0][:2] for k in new))
print('match types',collections.Counter(x['match_type'] for x in aud));print('grade by match',collections.Counter((x['grade'],x['match_type']) for x in aud))
print('overlap examples',list(overlap.items())[:8]);print('diff examples',list(diff.items())[:15])
merged={**old,**new}
print('merged',sum(k[0].startswith('V8') for k in merged),sum(k[0].startswith('H1') for k in merged))
with open(out/'qrels_revised.pkl','wb') as f:pickle.dump(dict(old=old,new=new,merged=merged,aud=aud,diff=diff),f)
with open(out/'annotation_mapping_audit.csv','w',newline='',encoding='utf-8') as f:
 wr=csv.DictWriter(f,fieldnames=['annotation_id','question_id','chunk_id','grade','match_type','similarity']);wr.writeheader();wr.writerows(aud)
