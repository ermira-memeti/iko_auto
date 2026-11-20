#!/usr/bin/env python3
"""IK0-Auto Task C input/readiness audit. Python stdlib only; NEVER executes KG2RAG."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def rows(path: Path):
    with path.open(encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def sha(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def check(root: Path) -> dict:
    errors, warnings, files = [], [], {}

    def require(rel):
        p = root/rel
        if not p.is_file():
            errors.append(f'MISSING required file: {rel}')
            return None
        files[rel] = {'bytes': p.stat().st_size, 'sha256': sha(p)}
        return p

    qs = {}
    for split, filename in [('Development','development_questions_50.csv'),('H1','h1_questions_50.csv')]:
        p=require('questions/'+filename)
        if p:
            d=rows(p); ids=[r.get('question_id','') for r in d]
            if len(d)!=50 or len(set(ids))!=50:errors.append(f'{split}: expected 50 unique questions, found {len(d)}')
            cohorts=Counter(r.get('insurer','').lower() for r in d)
            if len(cohorts)!=5 or sorted(cohorts.values()) != [10]*5:
                warnings.append(f'{split}: expected five insurer groups with 10 questions each; found {dict(cohorts)}')
            qs[split]=set(ids)

    archived={}
    for split,rel in [('Development','results/development/DEV_RANKINGS_PUBLIC.csv'),('H1','results/h1/H1_RANKINGS_PUBLIC.csv')]:
        p=require(rel)
        if p:
            d=rows(p)
            archived[split] = {(r['question_id'],int(r['rank'])):r['chunk_id'] for r in d if r.get('method')=='M2' and r.get('chunk_id','').strip()}
            if len(archived[split])!=250:
                errors.append(f'{split}: M2 historical Top-5 contained {len(archived[split])} question-ranks; expected 250')

    p=require('results/supplementary_baselines/comment8_rankings_top20_no_text.csv')
    if p:
        d=rows(p)
        if len(d)!=10000:errors.append(f'Comment8 total rows {len(d)} != 10000')
        methods=Counter(x.get('method') for x in d)
        expected={'M2_REPRODUCED','DENSE_MINILM','HYBRID_RRF60','BM25_CROSSENCODER','GRAPH_NEIGHBOR'}
        if set(methods)!=expected or any(v!=2000 for v in methods.values()):
            errors.append(f'Unexpected method inventory: {dict(methods)}')
        reproduced=defaultdict(dict)
        rankcheck=Counter()
        for row in d:
            split=row.get('split')
            try: rank=int(row['rank'])
            except (ValueError,TypeError,KeyError):
                errors.append('Bad rank in Comment8 row');continue
            key=(split,row.get('method'),row.get('question_id'),rank)
            if rank<1 or rank>20:
                errors.append(f'Rank outside 1..20: {key}')
            rankcheck[key]+=1
            if split not in qs or row.get('question_id') not in qs[split]:
                errors.append(f'Unexpected question in Comment8 rankings: {key}')
            if row.get('method')=='M2_REPRODUCED' and rank<=5:
                reproduced[split][(row['question_id'],rank)]=row['chunk_id']
        duplicates=[k for k,v in rankcheck.items() if v!=1]
        if duplicates:errors.append(f'Comment8 has {len(duplicates)} duplicate (split,method,question,rank) keys')
        for split in ['Development','H1']:
            expected_r=archived.get(split,{});observed_r=reproduced.get(split,{})
            discrepancies=[k for k in set(expected_r)|set(observed_r) if expected_r.get(k)!=observed_r.get(k)]
            if discrepancies:errors.append(f'{split}: M2 Top-5 differs at {len(discrepancies)} positions (first {discrepancies[:3]})')
            if not discrepancies and len(expected_r)==250: print(f'PASS: {split}: all 50 archived M2 Top-5 rankings reproduced exactly')

    graph=root/'ontology/validation/frozen/Gplus_extended_frozen.ttl'
    if graph.is_file():files['ontology/validation/frozen/Gplus_extended_frozen.ttl']={'sha256':sha(graph),'bytes':graph.stat().st_size}
    else:warnings.append('Graph G+ validation copy missing (optional for preflight)')
    qrels=root/'labels/deep_pool/final_3384.csv'
    qrels_state='NOT SUPPLIED (baseline can be run; cannot report complete final rescored metrics)'
    if qrels.is_file():
        d=rows(qrels)
        aliases={'split','dataset'};keyset=set(); grades=Counter()
        for row in d:
            split=row.get('dataset') or row.get('split') or ''
            if split.lower() in {'dev','development'}:split='Development'
            elif split.lower()=='h1':split='H1'
            key=(split,row.get('question_id',''),row.get('chunk_id',''))
            if key in keyset:errors.append(f'Final qrels contain duplicate key {key}')
            keyset.add(key)
            if split not in qs or row.get('question_id') not in qs[split]:errors.append(f'Final qrels unexpected question key {key}')
            grade=row.get('relevance','')
            grades[grade]+=1
        if len(d)!=3384 or grades!={'0':3029,'1':243,'2':112}:
            errors.append(f'Final qrels inventory differs: records={len(d)}, grade_counts={dict(grades)}')
        else:qrels_state='3384 records / grades 3029,243,112: STRUCTURAL COUNT CHECK PASSED (does not certify human provenance)'
        files['labels/deep_pool/final_3384.csv']={'sha256':sha(qrels),'bytes':qrels.stat().st_size}
    else:
        warnings.append('Final resolved 3384-row qrels not found; do not treat C4 reconstructed grades as final')

    return {'status':'PASS_WITH_WARNINGS' if not errors and warnings else ('PASS' if not errors else 'FAIL'),
            'archived_M2_exact_rank_reproduction': not any('M2 Top-5 differs' in e for e in errors),
            'reference_status':qrels_state,'errors':errors,'warnings':warnings,'audited_files':files}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);ap.add_argument('--output',type=Path,default=None)
    args=ap.parse_args();result=check(args.root.resolve())
    print(json.dumps({k:v for k,v in result.items() if k!='audited_files'},indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    if result['status']=='FAIL':sys.exit(2)

if __name__=='__main__':main()
