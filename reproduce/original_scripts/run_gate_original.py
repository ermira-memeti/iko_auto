#!/usr/bin/env python3
"""Frozen-original V8.3 routing & 4-method retrieval for 50 *candidate* questions.

No human gold labels or relevance scores are inferred. This script refuses
changed PDFs/graphs/gate code and retains exact top-5 ranked evidence and pool.
"""
from pathlib import Path
from collections import Counter
import csv,sys,json,hashlib,datetime
OUT=Path('/mnt/data/iko_gate_work')
PROJECT=Path('/mnt/data/iko_final_work/project')
sys.path.insert(0,str(PROJECT))
from src.v8_3_intent import route_intent
from src.pipeline import build_pipeline
from src.graph_retrieval import GraphIndex
from src.research_eval import method_runs
from src.v8_2_graph_build import EXPECTED_SOURCE_HASHES,FROZEN_V6_GRAPH_SHA256
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=json.loads((OUT/'GATE26_Frozen_Candidate_Manifest.json').read_text(encoding='utf-8'))
qfile=OUT/'GATE26_50_Candidate_Questions.csv'
if sha(qfile)!=manifest['question_sha256']:raise ValueError('Question file changed after freeze')
for file,d in manifest['source_pdf_sha256'].items():
 p=PROJECT/'data/research_corpus'/file
 if sha(p)!=d or sha(p)!=EXPECTED_SOURCE_HASHES[file]:raise ValueError('Source PDF changed: '+file)
g0=PROJECT/'outputs/v6/iko_auto_five_insurers_v6.ttl'
gp=PROJECT/'outputs/v8_2/iko_auto_extended_v8_2.ttl'
if sha(g0)!=manifest['source_graph_sha256'] or sha(g0)!=FROZEN_V6_GRAPH_SHA256:raise ValueError('Original graph changed')
if sha(gp)!=manifest['extended_graph_sha256']:raise ValueError('Extended graph changed')
if sha(PROJECT/'src/v8_3_intent.py')!=manifest['gate_code_sha256']:raise ValueError('Gate code changed')
with qfile.open(encoding='utf-8-sig',newline='') as f:questions=list(csv.DictReader(f))
assert len(questions)==50
pred=[]
for q in questions:
 p=route_intent(q['question'],q['insurer'])
 pred.append({'question_id':q['question_id'],'insurer':q['insurer'],'question':q['question'],'gate_route':p['route'],'gate_topic':p['topic'] or '', 'gate_reason':p['reason'], 'gate_version':p['gate_version'],'mentioned_insurers':'|'.join(p['mentioned_insurers'])})
with (OUT/'GATE26_Gate_Predictions_NOT_FOR_REVIEWERS.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(pred[0]));w.writeheader();w.writerows(pred)
print('GATE_PREDICTIONS',Counter(p['gate_route'] for p in pred),flush=True)
print('Building native pipeline...',flush=True)
retriever=build_pipeline(folder=PROJECT/'data/research_corpus',chunk_words=170,overlap_words=45,graph_file=None)
print('CHUNKS',len(retriever.chunks),'BM25',retriever.bm25_backend,flush=True)
assert len(retriever.chunks)==len({x.chunk_id for x in retriever.chunks})==717
retriever.graph_index=GraphIndex(g0,retriever.chunks)
idxplus=GraphIndex(gp,retriever.chunks)
methods=['bm25_metadata','bm25_metadata_graph','bm25_metadata_graph_v8_2','bm25_metadata_graph_intent_v8_3']
name={'bm25_metadata':'M2','bm25_metadata_graph':'M5','bm25_metadata_graph_v8_2':'M7','bm25_metadata_graph_intent_v8_3':'M8'}
intent=[]
print('Executing unchanged M2, M5, M7, M8...',flush=True)
runs=method_runs(retriever,questions,methods,k=5,alpha=.6,pool_size=5,enhanced_graph_index=idxplus,intent_audit=intent)
index={c.chunk_id:c for c in retriever.chunks}
rank_rows=[];pool={}
for m in methods:
 for q in questions:
  ids=runs[m][q['question_id']]
  if not ids:
   rank_rows.append(dict(method=name[m],question_id=q['question_id'],rank=0,chunk_id='',source_path='',page='',passage_text='',insurer=q['insurer']))
  for j,cid in enumerate(ids,1):
   c=index[cid]
   row=dict(method=name[m],question_id=q['question_id'],rank=j,chunk_id=cid,source_path=Path(c.source_path).name,page=c.page,passage_text=c.text,insurer=q['insurer'])
   rank_rows.append(row)
   pool[(q['question_id'],cid)]=dict(question_id=q['question_id'],insurer=q['insurer'],question=q['question'],chunk_id=cid,source_document=Path(c.source_path).name,pdf_page=c.page,passage_text=c.text)
with (OUT/'GATE26_Original_Method_Rankings.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rank_rows[0]));w.writeheader();w.writerows(rank_rows)
poolrows=sorted(pool.values(),key=lambda x:(x['question_id'],x['source_document'],int(x['pdf_page']),x['chunk_id']))
with (OUT/'GATE26_Union_Passage_Pool_NO_LABELS.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(poolrows[0]));w.writeheader();w.writerows(poolrows)
assert len(intent)==50 and all(item['route']==route_intent(q['question'],q['insurer'])['route'] for item,q in zip(intent,questions))
# Method M8 is exactly M5 or M7, depending on original route; verify at question level.
for q in questions:
 id=q['question_id'];route=route_intent(q['question'],q['insurer'])['route']
 target='bm25_metadata_graph_v8_2' if route=='enhanced_v8_2' else 'bm25_metadata_graph'
 assert runs['bm25_metadata_graph_intent_v8_3'][id]==runs[target][id],id
stats={m:{'empty_questions':sum(not hits for hits in runs[m].values()),'distinct_rankings':len(set(tuple(x) for x in runs[m].values()))} for m in methods}
manifest_update=dict(run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_code_hashes={p:sha(PROJECT/p) for p in ('src/v8_3_intent.py','src/research_eval.py','src/retrieval.py','src/graph_retrieval.py','src/pipeline.py')},bm25_backend=retriever.bm25_backend,indexed_passages=len(retriever.chunks),question_sha256=sha(qfile),method_ids=name,per_method=stats,gate_route_counts=dict(Counter(p['gate_route'] for p in pred)),gate_topic_counts=dict(Counter(p['gate_topic'] for p in pred)),n_ranking_rows=len(rank_rows),n_unique_question_passage_pairs=len(poolrows),retrieval_score_status='NOT_SCORED_HUMAN_LABELS_MISSING',data_limitations=['AI-assisted author-written candidate questions are post-hoc and not external held-out queries.','Gate route is a software prediction; no independently determined semantic gold labels exist.','Ranked-passage relevance has not been independently graded.'])
(OUT/'GATE26_Run_Provenance.json').write_text(json.dumps(manifest_update,indent=2,ensure_ascii=False),encoding='utf-8')
print('RUN_COMPLETE',json.dumps({**manifest_update,'source_code_hashes':{}},indent=2),flush=True)
