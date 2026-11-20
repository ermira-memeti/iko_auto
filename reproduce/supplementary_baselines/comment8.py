#!/usr/bin/env python3
"""IKO-Auto Comment 8: verified benchmark, stronger baselines, review queue, sensitivity.

RESEARCH SAFEGUARD: this creates new files under results/ and NEVER changes frozen
M1-M8 rankings, original PDFs, research graphs, or historical judgments.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, platform, re, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from original_src.data_ingest import load_documents
from original_src.chunking import chunk_documents
from original_src.policy_catalog import allowed_sources
from original_src.retrieval import InsuranceRetriever, tokenize
from original_src.research_eval import method_runs

MAIN_K = 5
POOL_K = 20
BM_POOL = 50
RRF_K = 60
EMBEDDER = 'sentence-transformers/all-MiniLM-L6-v2'
RERANKER = 'cross-encoder/ms-marco-MiniLM-L6-v2'
METHODS = ['M2_REPRODUCED','DENSE_MINILM','HYBRID_RRF60','BM25_CROSSENCODER','GRAPH_NEIGHBOR']
SPLITS = [('Development','development_questions_50.csv','DEV_RANKINGS_PUBLIC.csv'),
          ('H1','h1_questions_50.csv','H1_RANKINGS_PUBLIC.csv')]


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):
            h.update(block)
    return h.hexdigest()


def read_csv(p):
    with open(p,'r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def write_csv(p, rows, fields):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)


def write_json(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str),encoding='utf-8')


def verify_pdf_hashes():
    catalog=json.loads((ROOT/'data/SOURCE_POLICY_SHA256.json').read_text())['sha256']
    for name,expected in catalog.items():
        p=ROOT/'data/policies'/name
        if not p.exists():raise RuntimeError('Missing original source PDF: '+str(p))
        actual=sha(p)
        if actual!=expected:raise RuntimeError(f'STOP: source PDF mismatch: {name}: {actual} != {expected}')
    if set(p.name for p in (ROOT/'data/policies').glob('*.pdf'))!=set(catalog):
        raise RuntimeError('STOP: unexpected or missing policy PDFs in source directory')
    return catalog


def bootstrap():
    hashes=verify_pdf_hashes()
    docs=load_documents(ROOT/'data/policies')
    chunks=chunk_documents(docs,170,45)
    if len(chunks)!=717 or len(set(c.chunk_id for c in chunks))!=717 or len(docs)!=232:
        raise RuntimeError(f'STOP: frozen corpus mismatch: documents={len(docs)} chunks={len(chunks)}')
    retriever=InsuranceRetriever(chunks)
    if retriever.bm25_backend!='rank_bm25.BM25Okapi':
        raise RuntimeError('STOP: original rank_bm25.BM25Okapi unavailable. Install rank-bm25; built-in fallback is not the frozen backend.')
    return retriever,hashes


def questions():
    allq={}
    for split,qfile,_ in SPLITS:
        rows=read_csv(ROOT/'data'/qfile)
        if len(rows)!=50 or len({r['question_id'] for r in rows})!=50:
            raise RuntimeError('STOP: Expected 50 distinct questions in '+qfile)
        allq[split]=rows
    return allq


def verify():
    retriever,hashes=bootstrap()
    verified={}
    for split,qfile,rfile in SPLITS:
        qs=questions()[split]
        new=method_runs(retriever,qs,['bm25_metadata'],k=5,pool_size=5)['bm25_metadata']
        old=defaultdict(list)
        for r in read_csv(ROOT/'data/frozen_reference'/rfile):
            if r['method']=='M2' and r['chunk_id']:
                old[r['question_id']].append(r['chunk_id'])
        mismatches=[qid for qid,ids in new.items() if ids!=old[qid]]
        verified[split]={'questions':50,'exact_top5':50-len(mismatches),'mismatch_ids':mismatches}
        print(f'{split}: exact M2 Top-5 = {50-len(mismatches)}/50',flush=True)
        if mismatches:raise RuntimeError('STOP: M2 reproduction differs from the archived run: '+str(mismatches[:10]))
    files={'corpus':hashes,'ontology_Gplus':sha(ROOT/'data/ontology/iko_auto_extended_v8_2.ttl')}
    for split,qfile,rfile in SPLITS:
        files[qfile]=sha(ROOT/'data'/qfile)
        files[rfile]=sha(ROOT/'data/frozen_reference'/rfile)
    result={'status':'VERIFIED','split_checks':verified,'source_hashes':files,
            'backend':retriever.bm25_backend,'passages':717,'pdf_pages':232,
            'created_utc':datetime.now(timezone.utc).isoformat(),
            'interpretation':'Exact historical M2 Top-5 output reproduced on both question sets.'}
    write_json(ROOT/'results/01_baseline_verification.json',result)
    return retriever,verified


def scoped_indices(chunks, insurer):
    srcs=allowed_sources(chunks,insurer)
    if not srcs:raise ValueError('Unknown source scope: '+insurer)
    return [i for i,c in enumerate(chunks) if c.source_path in srcs]


def rank_scores(scores,eligible,positive_only=False,n=50):
    ids=sorted((i for i in eligible if not positive_only or float(scores[i])>0),
               key=lambda i:(-float(scores[i]),i))
    return ids[:n]


def rrf(ranklists,k=RRF_K):
    s=defaultdict(float)
    for ids in ranklists:
        for rank,i in enumerate(ids,1):s[i]+=1/(k+rank)
    return sorted(s,key=lambda i:(-s[i],i))


def build_graph_neighborhood(retriever):
    from original_src.graph_retrieval import GraphIndex
    gp=ROOT/'data/ontology/iko_auto_extended_v8_2.ttl'
    idx=GraphIndex(gp,retriever.chunks)
    # The frozen G+ is used as an explicit knowledge graph. No OWL inference.
    records=list(idx.assertions.items())
    ev2records=defaultdict(set)
    node2records=defaultdict(set)
    record2chunks=[]
    for j,((s,p,o),passages) in enumerate(records):
        node2records[s].add(j)
        node2records[o].add(j)
        connected=set()
        for ev in passages:
            connected.update(idx.evidence_to_chunks[ev])
        record2chunks.append(connected)
        for cid in connected: ev2records[cid].add(j)
    neighbors={i:(node2records[s]|node2records[o])-{i}
               for i,((s,p,o),_) in enumerate(records)}
    return {'ev2records':ev2records,'record2chunks':record2chunks,'neighbors':neighbors,
            'n_assertions':len(records),'n_sources':len(idx.evidence_to_chunks)}


def graph_neighbor_ranking(lexical_top50,eligible,chunk_ids,graph_state):
    """KG-neighborhood candidate expansion, distinct from IKO-Auto's weighted path planner.
    Anchor: source-provenance chunks among the top 20 BM25 passages.
    Expand: assertions sharing one subject/object endpoint with an anchored assertion.
    Ranking: lexical RRF rank + 0.4 x provenance-neighborhood RRF signal.
    This is a lightweight KG-RAG-style comparator, not the published KG2RAG algorithm.
    """
    eligible=set(eligible)
    pos={cid:i for i,cid in enumerate(chunk_ids)}
    graph_score=defaultdict(float)
    trace=defaultdict(set)
    anchors=set()
    for rank,candidate in enumerate(lexical_top50[:20],1):
        aid=chunk_ids[candidate]
        for a in graph_state['ev2records'].get(aid,()):
            anchors.add(a)
            for j,weight in [(a,1.0)]+[(b,0.5) for b in graph_state['neighbors'][a]]:
                for c in graph_state['record2chunks'][j]:
                    i=pos.get(c)
                    if i is not None and i in eligible:
                        graph_score[i]+=weight/(RRF_K+rank)
                        trace[i].add((a,j))
    lexical={i:1/(RRF_K+rank) for rank,i in enumerate(lexical_top50,1)}
    candidates=set(lexical)|set(graph_score)
    combined={i:lexical.get(i,0.0)+0.4*graph_score.get(i,0.0) for i in candidates}
    ranking=sorted(candidates,key=lambda i:(-combined[i],i))
    stats={'mapped_seed_assertions':len(anchors),'graph_candidate_chunks':len(graph_score),
           'graph_only_added_chunks':len(set(graph_score)-set(lexical)),
           'top20_graph_supported':sum(i in graph_score for i in ranking[:20])}
    return ranking,stats,combined


def run_methods(skip_models=False):
    retriever,verification=verify()
    qsets=questions()
    chunks=retriever.chunks; lookup={c.chunk_id:c for c in chunks}
    out=[];diag=[];model_versions={}
    def emit(split,method,q,ids,score_map,metadata=None):
        rowdata=metadata or {}
        diag.append({'split':split,'method':method,'question_id':q['question_id'],'returned':len(ids),**rowdata})
        for rank,i in enumerate(ids[:POOL_K],1):
            c=chunks[i]
            out.append({'split':split,'method':method,'question_id':q['question_id'],'insurer':q['insurer'],
                        'rank':rank,'chunk_id':c.chunk_id,'source_path':c.source_path,'page':c.page,
                        'score':f'{float(score_map.get(i,0)):.9f}', 'text':c.text})
    D=None;CE=None;dense_vectors=None
    if not skip_models:
        from sentence_transformers import SentenceTransformer,CrossEncoder
        import sentence_transformers
        model_versions['sentence_transformers']=sentence_transformers.__version__
        print('Loading dense model (download needed on first use):',EMBEDDER,flush=True)
        D=SentenceTransformer(EMBEDDER,device='cpu')
        # Do not use older, unmatched embeddings cached for another corpus/model.
        stamp=hashlib.sha256(('\n'.join(c.chunk_id+'|'+c.text for c in chunks)+EMBEDDER).encode()).hexdigest()
        cache=ROOT/'results/embeddings_minilm.npy';manifest=ROOT/'results/embeddings_manifest.json'
        if cache.exists() and manifest.exists() and json.loads(manifest.read_text()).get('cache_key')==stamp:
            dense_vectors=np.load(cache)
        else:
            if hasattr(D,'encode_document'):
                dense_vectors=D.encode_document([c.text for c in chunks],normalize_embeddings=True,batch_size=16,show_progress_bar=True)
            else:
                dense_vectors=D.encode([c.text for c in chunks],normalize_embeddings=True,batch_size=16,show_progress_bar=True)
            dense_vectors=np.asarray(dense_vectors,dtype='float32')
            np.save(cache,dense_vectors)
            write_json(manifest,{'cache_key':stamp,'model':EMBEDDER,'rows':len(chunks),
                                 'columns':int(dense_vectors.shape[1])})
        if dense_vectors.shape[0]!=717:raise RuntimeError('Dense cache dimension mismatch')
        print('Loading cross-encoder model:',RERANKER,flush=True)
        CE=CrossEncoder(RERANKER,device='cpu',max_length=512)
    graph_state=build_graph_neighborhood(retriever)
    allq=0
    for split,qset in qsets.items():
        print('Running split:',split,flush=True)
        for q in qset:
            allq+=1
            eligible=scoped_indices(chunks,q['insurer'])
            bm=np.asarray(retriever._bm25.get_scores(tokenize(q['question'])),dtype=float)
            bmrank=rank_scores(bm,eligible,positive_only=True,n=BM_POOL)
            bmids=bmrank[:POOL_K]
            emit(split,'M2_REPRODUCED',q,bmids,{i:float(bm[i]) for i in bmids})
            grank,ginfo,gscore=graph_neighbor_ranking(bmrank,eligible,[c.chunk_id for c in chunks],graph_state)
            emit(split,'GRAPH_NEIGHBOR',q,grank[:POOL_K],gscore,ginfo)
            if skip_models:continue
            if hasattr(D,'encode_query'):
                qvec=D.encode_query([q['question']],normalize_embeddings=True)[0]
            else:qvec=D.encode([q['question']],normalize_embeddings=True)[0]
            ds=np.asarray(dense_vectors @ qvec,dtype=float)
            drank=rank_scores(ds,eligible,n=BM_POOL)
            emit(split,'DENSE_MINILM',q,drank[:POOL_K],{i:float(ds[i]) for i in drank[:POOL_K]})
            hybrid=rrf([bmrank,drank])
            hs=defaultdict(float)
            for ranks in [bmrank,drank]:
                for k,i in enumerate(ranks,1):hs[i]+=1/(RRF_K+k)
            emit(split,'HYBRID_RRF60',q,hybrid[:POOL_K],hs)
            # Re-rank only the same top-50 BM25 candidate budget: no cross-insurer passages.
            if bmrank:
                pairs=[(q['question'],chunks[i].text) for i in bmrank]
                sc=np.asarray(CE.predict(pairs,batch_size=16,show_progress_bar=False),dtype=float).reshape(-1)
                reranked=sorted(zip(bmrank,sc),key=lambda t:(-t[1],t[0]))
                emit(split,'BM25_CROSSENCODER',q,[i for i,_ in reranked[:POOL_K]],dict(reranked))
        print('Completed',split,flush=True)
    outfile=ROOT/'results/comment8_rankings_top20.csv'
    write_csv(outfile,out,['split','method','question_id','insurer','rank','chunk_id','source_path','page','score','text'])
    write_csv(ROOT/'results/comment8_method_diagnostics.csv',diag,
              ['split','method','question_id','returned','mapped_seed_assertions','graph_candidate_chunks','graph_only_added_chunks','top20_graph_supported'])
    write_json(ROOT/'results/02_run_manifest.json',{
        'created_utc':datetime.now(timezone.utc).isoformat(),'state':'RANKINGS_ONLY_NOT_SCORED',
        'methods':sorted({r['method'] for r in out}),'n_queries':allq,'n_chunks':len(chunks),
        'topk_saved':POOL_K,'output_topk':MAIN_K,'candidate_budget':BM_POOL,
        'dense_model':EMBEDDER if not skip_models else None,
        'rerank_model':RERANKER if not skip_models else None,'model_packages':model_versions,
        'python':platform.python_version(),'source_pdfs_sha256':verify_pdf_hashes(),
        'rankings_sha256':sha(outfile),'label_warning':'Unjudged new passages must NOT be treated as grade 0',
        'graph_baseline':'One-hop explicit-assertion provenance-neighborhood expansion (not original KG2RAG implementation)'
    })
    print('Created',outfile,flush=True)
    return outfile


def load_current_qrels(user_path=None):
    # Current packaged labels predate the Comment-4 3,384-pair pool. If you have
    # later adjudicated qrels, supply them explicitly; do not silently mix versions.
    source=Path(user_path) if user_path else ROOT/'data/qrels/fusion_expanded_relevance_public.csv'
    if not source.is_file():raise FileNotFoundError('No qrels found: '+str(source))
    rows=read_csv(source)
    qrels={}
    for row in rows:
        key=(row.get('dataset',row.get('split','')).strip(),row['question_id'],row['chunk_id'])
        if key[0] in ('DEV','Dev','development'):key=('Development',key[1],key[2])
        if key[0].lower() in ('h1','test'):key=('H1',key[1],key[2])
        if key[0] not in ('Development','H1'):
            raise ValueError('qrels must contain dataset/split column containing Development or H1: '+str(key))
        raw=row.get('relevance','').strip()
        if raw not in ('0','1','2'):raise ValueError('Invalid relevance '+raw+' for '+str(key))
        if key in qrels and qrels[key]!=int(raw):raise ValueError('Conflicting qrels for '+str(key))
        qrels[key]=int(raw)
    return qrels,source


def create_pool(user_qrels=None,pool_depth=5):
    src=ROOT/'results/comment8_rankings_top20.csv'
    if not src.exists():raise FileNotFoundError('Run methods first: '+str(src))
    qrels,qp=load_current_qrels(user_qrels)
    qs={}
    for split,rows in questions().items():
        for r in rows:qs[(split,r['question_id'])]=r
    unique={}
    for r in read_csv(src):
        if int(r['rank']) > pool_depth:continue
        k=(r['split'],r['question_id'],r['chunk_id'])
        if k not in unique:
            unique[k]={**r,'contributed_by':{r['method']},'min_rank':int(r['rank'])}
        else:
            unique[k]['contributed_by'].add(r['method'])
            unique[k]['min_rank']=min(unique[k]['min_rank'],int(r['rank']))
    missing=[];overview=[];scored=[]
    for k,v in sorted(unique.items()):
        label=qrels.get(k)
        q=qs[(k[0],k[1])]
        if label is None:
            missing.append({'split':k[0],'question_id':k[1],'insurer':q['insurer'],
                            'question':q['question'],'chunk_id':k[2],'source_document':v['source_path'],
                            'physical_pdf_page':v['page'],'passage_text':v['text'],
                            'relevance_0_1_2':'','rationale':'','annotator_id':'','review_date':''})
        else:
            scored.append({'split':k[0],'question_id':k[1],'chunk_id':k[2],'relevance':label})
    write_csv(ROOT/'results/03_TO_REVIEW_BLIND.csv',missing,
              ['split','question_id','insurer','question','chunk_id','source_document',
               'physical_pdf_page','passage_text','relevance_0_1_2','rationale','annotator_id','review_date'])
    write_csv(ROOT/'results/03_REUSED_EXISTING_LABELS.csv',scored,
              ['split','question_id','chunk_id','relevance'])
    for split in ('Development','H1'):
        x={k for k in unique if k[0]==split}
        overview.append({'split':split,'unique_candidate_pairs':len(x),
                         'already_judged':sum(k in qrels for k in x),
                         'new_judgments_required':sum(k not in qrels for k in x)})
    write_csv(ROOT/'results/03_LABEL_COVERAGE_SUMMARY.csv',overview,
              ['split','unique_candidate_pairs','already_judged','new_judgments_required'])
    write_json(ROOT/'results/03_pool_info.json',{'existing_qrels_path':str(qp),'existing_qrels_sha256':sha(qp),
        'total_candidates':len(unique),'n_unjudged':len(missing),'n_reused':len(scored),'pool_depth':pool_depth,
        'warning':'Do NOT score unjudged candidate passages as irrelevant, and do NOT ask assessors to use model labels.'})
    print('Unique pooled pairs:',len(unique),'unjudged:',len(missing),'reused:',len(scored))
    return missing


def add_reviewed(qrels, reviewed_csv):
    if reviewed_csv is None:return qrels
    reviewed=read_csv(reviewed_csv)
    for r in reviewed:
        key=(r['split'],r['question_id'],r['chunk_id']);v=r['relevance_0_1_2'].strip()
        if v not in ('0','1','2'):raise ValueError('Unfilled or invalid human review grade for '+str(key))
        if key in qrels and qrels[key]!=int(v):raise ValueError('Human review conflicts with frozen reference '+str(key))
        qrels[key]=int(v)
    return qrels


def score(user_qrels=None,reviewed_csv=None):
    qrels,qp=load_current_qrels(user_qrels)
    qrels=add_reviewed(qrels,reviewed_csv)
    ranks=read_csv(ROOT/'results/comment8_rankings_top20.csv')
    by=defaultdict(list)
    for row in ranks:by[(row['split'],row['method'],row['question_id'])].append(row)
    missing=[];metrics=[]
    for split,qset in questions().items():
        for m in sorted(set(x['method'] for x in ranks)):
            vals=[]
            for q in qset:
                rr=sorted(by.get((split,m,q['question_id']),[]),key=lambda r:int(r['rank']))[:MAIN_K]
                for r in rr:
                    k=(split,q['question_id'],r['chunk_id'])
                    if k not in qrels:missing.append(k)
                if missing:continue
                grades=[qrels[(split,q['question_id'],r['chunk_id'])] for r in rr]
                dcg=sum((1 if g==2 else 0)/np.log2(i+2) for i,g in enumerate(grades))
                relevant_count=sum(v==2 for (s,qi,c),v in qrels.items() if s==split and qi==q['question_id'])
                ideal=sum(1/np.log2(i+2) for i in range(min(5,relevant_count)))
                vals.append({'hit':int(any(g==2 for g in grades)),
                             'p5':sum(g==2 for g in grades)/5,
                             'mrr':next((1/(i+1) for i,g in enumerate(grades) if g==2),0),
                             'ndcg':dcg/ideal if ideal else 0,'empty':int(not rr)})
            if not missing:
                metrics.append({'split':split,'method':m,'n_questions':50,
                   'Hit@5':np.mean([x['hit'] for x in vals]),
                   'P@5':np.mean([x['p5'] for x in vals]),
                   'MRR@5':np.mean([x['mrr'] for x in vals]),
                   'pool_relative_binary_nDCG@5':np.mean([x['ndcg'] for x in vals]),
                   'empty':sum(x['empty'] for x in vals)})
    if missing:
        u=sorted(set(missing));print('STOP: unjudged Top-5 passages',len(u),'(first five)',u[:5]);
        write_csv(ROOT/'results/04_UNJUDGED_BLOCKING_METRICS.csv',
                  [{'split':s,'question_id':q,'chunk_id':c} for s,q,c in u],
                  ['split','question_id','chunk_id'])
        raise RuntimeError('No valid performance table can be produced until these passages are independently judged.')
    write_csv(ROOT/'results/04_METRICS_AFTER_REVIEW.csv',metrics,
              ['split','method','n_questions','Hit@5','P@5','MRR@5','pool_relative_binary_nDCG@5','empty'])
    print('Metrics successfully calculated; note that nDCG is relative to supplied judgment pool')


def sensitivity():
    r,_=verify()
    from rank_bm25 import BM25Okapi
    chunks=r.chunks
    qs=questions()
    rows=[]
    for k1 in (0.9,1.5,2.0):
        for b in (0.3,0.75,1.0):
            model=BM25Okapi([tokenize(c.text) for c in chunks],k1=k1,b=b)
            for split,qset in qs.items():
                for q in qset:
                    e=scoped_indices(chunks,q['insurer'])
                    sc=np.asarray(model.get_scores(tokenize(q['question'])))
                    rank=rank_scores(sc,e,positive_only=True,n=POOL_K)
                    for pos,i in enumerate(rank,1):
                        rows.append({'split':split,'k1':k1,'b':b,'question_id':q['question_id'],
                                     'rank':pos,'chunk_id':chunks[i].chunk_id,
                                     'page':chunks[i].page,'source_path':chunks[i].source_path})
            print('BM25 grid completed:',k1,b,flush=True)
    write_csv(ROOT/'results/05_BM25_PARAMETER_GRID_TOP20.csv',rows,
              ['split','k1','b','question_id','rank','chunk_id','page','source_path'])
    docs=load_documents(ROOT/'data/policies')
    cr=[]
    for cw,overlap in [(120,30),(170,45),(240,60)]:
        candidate=chunk_documents(docs,cw,overlap)
        cr.append({'chunk_words':cw,'overlap_words':overlap,'n_chunks':len(candidate),
                   'n_unique_chunk_ids':len(set(c.chunk_id for c in candidate)),
                   'corpus_hash_note':'This is a NEW indexing condition: old chunk-ID qrels CANNOT be reused.'})
    write_csv(ROOT/'results/05_CHUNK_GRID_INVENTORY.csv',cr,
              ['chunk_words','overlap_words','n_chunks','n_unique_chunk_ids','corpus_hash_note'])
    print('Parameter grid and chunking inventory prepared; not a relevance-performance comparison yet.')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['verify','run','smoke','pool','score','sensitivity'])
    ap.add_argument('--qrels',default=None,help='Optional COMPLETE Comment-4 adjudicated CSV (dataset,question_id,chunk_id,relevance)')
    ap.add_argument('--reviewed',default=None,help='Filled CSV from results/03_TO_REVIEW_BLIND.csv')
    ap.add_argument('--pool-depth',type=int,default=5,choices=[5,20],help='Top-5 minimizes review workload; top-20 is optional')
    args=ap.parse_args()
    try:
        if args.command=='verify':verify()
        elif args.command in ('run','smoke'):run_methods(skip_models=(args.command=='smoke'))
        elif args.command=='pool':create_pool(args.qrels,args.pool_depth)
        elif args.command=='score':score(args.qrels,args.reviewed)
        elif args.command=='sensitivity':sensitivity()
    except Exception as ex:
        print('\nSTOPPED:',str(ex),file=sys.stderr)
        sys.exit(1)

if __name__=='__main__':main()
