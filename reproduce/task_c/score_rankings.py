#!/usr/bin/env python3
"""Pool-relative KG2RAG/M2/M8 Top-5 scorer with unknown-judgment bounds.

Does not turn unjudged candidates into non-relevant passages. No model execution.
"""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
from collections import defaultdict,Counter


def readcsv(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_qrels(path):
    d=readcsv(path);q={}; grades=Counter()
    for r in d:
        split=(r.get('dataset') or r.get('split') or '').strip()
        if split.lower() in ('dev','development'):split='Development'
        elif split.lower()=='h1':split='H1'
        g=r.get('relevance','').strip()
        if g not in {'0','1','2'}:raise ValueError(f'Bad relevance grade: {g!r}')
        key=(split,r['question_id'].strip(),r['chunk_id'].strip())
        if key in q:raise ValueError('Duplicate qrels key '+str(key))
        q[key]=int(g);grades[g]+=1
    if len(q)!=3384 or grades!=Counter({'0':3029,'1':243,'2':112}):
        raise ValueError('The 3384-row reference does not match manuscript counts; use the FINAL reconciled qrels export')
    return q


def score_one(split,question_id,ranked_ids,qrels):
    ids=ranked_ids[:5]
    labels=[qrels.get((split,question_id,cid),None) for cid in ids]
    known_positive=[i+1 for i,g in enumerate(labels) if g==2]
    unknown=[i+1 for i,g in enumerate(labels) if g is None]
    earliest=min(known_positive) if known_positive else None
    optimistic=min(known_positive+unknown) if known_positive or unknown else None
    p_low=len(known_positive)/5
    p_high=(len(known_positive)+len(unknown))/5
    # Pool relative nDCG: only defined when every retrieved top5 rank is judged.
    pos_in_pool=sum(1 for (s,q,c),g in qrels.items() if s==split and q==question_id and g==2)
    ideal=sum(1/math.log2(i+2) for i in range(min(5,pos_in_pool)))
    dcg=sum(1/math.log2(i+2) for i,g in enumerate(labels) if g==2)
    ndcg=(dcg/ideal if ideal else 0.0) if not unknown else None
    return {'known_grade2':len(known_positive), 'unjudged_top5':len(unknown),
            'hit5_lower':int(bool(known_positive)), 'hit5_upper':int(bool(known_positive or unknown)),
            'p5_lower':p_low,'p5_upper':p_high,
            'mrr5_lower':1/earliest if earliest else 0.0,
            'mrr5_upper':1/optimistic if optimistic else 0.0,
            'ndcg5_pool_relative_if_complete':ndcg}


def evaluate(root,rank_file,qrel_file,out_dir):
    questions={}
    for split,file in [('Development','questions/development_questions_50.csv'),('H1','questions/h1_questions_50.csv')]:
        data=readcsv(root/file)
        if len(data)!=50 or len({r['question_id'] for r in data})!=50:raise ValueError(f'Invalid question set for {split}')
        questions[split]=[r['question_id'] for r in data]
    qrels=load_qrels(qrel_file)
    ranked=defaultdict(dict); methods=set();declared_empty=set()
    for r in readcsv(rank_file):
        split=(r.get('split') or r.get('dataset') or '').strip()
        if split.lower() in ('dev','development'):split='Development'
        elif split.lower()=='h1':split='H1'
        method=r['method'].strip(); qid=r['question_id'].strip()
        if split not in questions or qid not in questions[split]:raise ValueError(f'Unexpected question: {split}/{qid}')
        if not method:raise ValueError('Empty method name')
        methods.add(method)
        rankval=(r.get('rank') or '').strip();chunk_id=(r.get('chunk_id') or '').strip()
        if not rankval and not chunk_id and (r.get('status','').lower().strip()=='empty'):
            declared_empty.add((split,method,qid));continue
        if not rankval or not chunk_id:raise ValueError(f'Need rank and chunk_id, or an explicit empty result marker: {r}')
        rank=int(rankval)
        if rank<1 or rank>20:raise ValueError(f'Rank must be between 1 and 20: {r}')
        key=(split,method,qid)
        if rank in ranked[key]:raise ValueError(f'Duplicate rank in {key}: {rank}')
        ranked[key][rank]=chunk_id
    if not methods:raise ValueError('No methods in ranking file')
    detailed=[]
    for split,qs in questions.items():
        for method in sorted(methods):
            for qid in qs:
                key=(split,method,qid)
                ranks=ranked.get(key,{})
                if not ranks and key not in declared_empty:
                    raise ValueError(f'Missing output for {key}; use a row with status=empty to declare empty results')
                if ranks:
                    if sorted(ranks)!=list(range(1,max(ranks)+1)):
                        raise ValueError(f'Noncontiguous ranks for {key}')
                    if len(set(ranks.values()))!=len(ranks):
                        raise ValueError(f'Duplicate chunk_id within question ranking {key}')
                score=score_one(split,qid,[ranks[i] for i in sorted(ranks)],qrels)
                detailed.append({'split':split,'method':method,'question_id':qid,'retrieved':len(ranks),**score})
    grouped=defaultdict(list)
    for row in detailed:grouped[row['split'],row['method']].append(row)
    summary=[]
    for (split,m),rr in sorted(grouped.items()):
        z={'split':split,'method':m,'n_questions':len(rr),'unjudged_top5_total':sum(x['unjudged_top5'] for x in rr),
           'complete_judged_questions':sum(x['unjudged_top5']==0 for x in rr)}
        for met in ['hit5','p5','mrr5']:
            for lim in ['lower','upper']:
                key=f'{met}_{lim}';z[key]=round(sum(x[key] for x in rr)/len(rr),6)
        z['ndcg5_pool_relative'] = (round(sum(x['ndcg5_pool_relative_if_complete'] for x in rr)/len(rr),6)
                                    if all(x['ndcg5_pool_relative_if_complete'] is not None for x in rr) else '')
        summary.append(z)
    out_dir.mkdir(parents=True,exist_ok=True)
    for path,data in [(out_dir/'task_c_per_question.csv',detailed),(out_dir/'task_c_summary.csv',summary)]:
        with path.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    meta={'mode':'source-anchored-pool-relative graded Top5 (never treat unknown=0)',
          'reference':str(qrel_file),'rankings':str(rank_file),
          'any_incomplete_new_rankings':any(x['unjudged_top5']>0 for x in detailed),
          'warning':'If unknown grades exist, report only interval bounds. nDCG values omitted for affected methods.'}
    (out_dir/'task_c_score_manifest.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    return summary


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);ap.add_argument('--rankings',type=Path,required=True);ap.add_argument('--qrels',type=Path,default=Path('labels/deep_pool/final_3384.csv'));ap.add_argument('--out',type=Path,default=Path('results/task_c'))
    a=ap.parse_args();root=a.root.resolve()
    resolve=lambda p: p if p.is_absolute() else root/p
    res=evaluate(root,resolve(a.rankings),resolve(a.qrels),resolve(a.out));print(json.dumps(res,indent=2))

if __name__=='__main__':main()
