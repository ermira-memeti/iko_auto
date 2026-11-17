#!/usr/bin/env python3
"""H1 held-out evaluation runner for *new* questions on previously seen policy PDFs.

This script DOES NOT execute the V8.3 retrieval models. Use your frozen local V8.3
implementation to produce H1_EIGHT_METHOD_TOP5.csv in the documented schema.

Prepare blinded human review sheets (no model/grade data exposed):
 python H1_prepare_and_evaluate.py prepare H1_EIGHT_METHOD_TOP5.csv H1_50_QUESTIONS_FOR_RETRIEVAL.csv

After human ratings (0,1,2) have been independently completed:
 python H1_prepare_and_evaluate.py evaluate H1_EIGHT_METHOD_TOP5.csv H1_REVIEWER_A_FILLED.csv H1_REVIEWER_B_FILLED.csv

If reviewers disagree, output a disagreement list; an independently documented
adjudicated CSV is required; do not silently select A, B, or an AI suggestion.
"""
import csv,sys,hashlib,random,collections,math,json
from pathlib import Path

METHODS=['M1','M2','M3','M4','M5','M6','M7','M8']


def read_csv(path):
    for enc in ('utf-8-sig','cp1252','latin1'):
        try:
            with open(path,newline='',encoding=enc) as f:return list(csv.DictReader(f))
        except UnicodeDecodeError:continue
    raise ValueError('Unrecognized file encoding: '+str(path))


def write_csv(path,rows,fields):
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def load_rankings(path, expected_qids=None):
    rows=read_csv(path)
    need={'method','question_id','rank','chunk_id','source_path','page','text'}
    if rows and not need.issubset(rows[0]):raise ValueError('Missing required ranking CSV columns: '+str(sorted(need-set(rows[0]))))
    by=collections.defaultdict(list); passages={}; seen=set(); explicit_empty=set()
    for row in rows:
        m=row['method'].strip().upper();q=row['question_id'].strip();cid=row['chunk_id'].strip()
        if m not in METHODS:raise ValueError('Unexpected method '+m)
        if expected_qids is not None and q not in expected_qids:raise ValueError('Unknown question '+q)
        try:k=int(row['rank'])
        except ValueError:raise ValueError(f'Invalid rank {m}/{q}/{row["rank"]}')
        if k==0 and not cid:
            if by.get((m,q)):raise ValueError(f'Empty marker mixed with ranked passages: {m}/{q}')
            by[(m,q)]=[];explicit_empty.add((m,q));continue
        if not cid:raise ValueError(f'Blank passage id {m}/{q}')
        if (m,q) in explicit_empty:raise ValueError(f'Ranked item after empty marker: {m}/{q}')
        if k<1 or k>5:raise ValueError(f'Out-of-range rank {m}/{q}/{k}')
        if not row['text'].strip() or not row['source_path'].strip() or not row['page'].strip():
            raise ValueError(f'Missing passage text, document or page for {m}/{q}/{cid}')
        key=(m,q,k)
        if key in seen:raise ValueError('Duplicate (method, question, rank): '+str(key))
        seen.add(key);by[(m,q)].append((k,cid))
        if cid in passages:
            prior=passages[cid]
            if prior['text'].strip()!=row['text'].strip() or prior['source_path']!=row['source_path']:
                raise ValueError('Inconsistent passage content for '+cid)
        passages[cid]={k:row.get(k,'') for k in ['text','source_path','page','start_word','end_word']}
    for pair,items in by.items():
        ranks=sorted(k for k,_ in items)
        if ranks!=list(range(1,len(ranks)+1)):
            raise ValueError(f'Nonconsecutive ranks {pair}: {ranks}')
        if len({c for k,c in items})!=len(items):
            raise ValueError('Duplicate passage in ranked top5 for '+str(pair))
    return rows,by,passages


def prep(ranked_csv,questions_csv):
    questions=read_csv(questions_csv)
    if len(questions)!=50 or len({q['question_id'] for q in questions})!=50:
        raise ValueError('Expected 50 unique H1 questions.')
    qmap={q['question_id']:q for q in questions}
    _,by,passages=load_rankings(ranked_csv,set(qmap))
    all_methods={(m,q) for m in METHODS for q in qmap}
    # Explicit empty results must be represented as rank=0 with blank chunk_id.
    # Missing method/question combinations are not silently treated as empty.
    missing=all_methods-set(by)
    if missing:
        raise ValueError('Missing method-question combinations. Encode empty results as rank=0, blank chunk_id. First missing: '+repr(sorted(missing)[:5]))
    pairs={}
    for (_,q),items in by.items():
        for _,cid in items:
            z=passages[cid]
            pairs[(q,cid)]={'question_id':q,'insurer':qmap[q]['insurer'],'question':qmap[q]['question'],'category':qmap[q]['category'],
                            'chunk_id':cid,'source_path':z['source_path'],'page':z['page'],'text':z['text']}
    base=Path(ranked_csv).parent
    pool=[pairs[k] for k in sorted(pairs)]
    fields=list(pool[0])
    write_csv(base/'H1_POOLED_ANNOTATION_CANDIDATES.csv',pool,fields)
    for who,seed in [('A',40051),('B',70031)]:
        copy=pool.copy();random.Random(seed).shuffle(copy)
        wrows=[dict(x,annotator_id='REVIEWER_'+who,relevance='',evidence_quote='',notes='') for x in copy]
        write_csv(base/f'H1_REVIEWER_{who}_BLINDED_BLANK.csv',wrows,fields+['annotator_id','relevance','evidence_quote','notes'])
    print(f'PASS: {len(qmap)} questions, 8 methods, {len(pool)} unique pooled question-passage pairs.')
    print('Created two independent human review sheets. Hide model rankings and answer key from reviewers.')


def evaluate(ranked_csv,review_a,review_b, adjudicated_csv=None):
    rows,by,_=load_rankings(ranked_csv)
    all_q=sorted({r['question_id'] for r in rows if r['question_id']})
    if len(all_q)!=50:raise ValueError('Expected 50 questions in new ranking CSV.')
    expected={(q,cid) for (m,q),items in by.items() for rank,cid in items}
    if {(m,q) for m in METHODS for q in all_q}-set(by):
        raise ValueError('Missing method-question results. Include every combination (empty results need explicit handling).')
    def ratings(p):
        a={}
        for row in read_csv(p):
            key=(row['question_id'].strip(),row['chunk_id'].strip())
            grade=row['relevance'].strip()
            if grade not in ('0','1','2'):raise ValueError('Unrated/invalid pair '+str(key)+' in '+str(p))
            if key in a:raise ValueError('Duplicate pair '+str(key))
            a[key]=int(grade)
        if set(a)!=expected:
            raise ValueError(f'Incomplete/extra reviewed pool in {p}: missing {len(expected-set(a))}, extra {len(set(a)-expected)}')
        return a
    a=ratings(review_a);b=ratings(review_b)
    mismatched=[dict(question_id=q,chunk_id=c,reviewer_A=a[(q,c)],reviewer_B=b[(q,c)]) for q,c in sorted(expected) if a[(q,c)]!=b[(q,c)]]
    base=Path(ranked_csv).parent
    write_csv(base/'H1_REVIEWER_DISAGREEMENTS.csv',mismatched,['question_id','chunk_id','reviewer_A','reviewer_B'])
    if mismatched:
        print(f'REVIEW REQUIRED: {len(mismatched)} disagreements. Preserve both originals and independently adjudicate.')
        if adjudicated_csv is None:return
        g=ratings(adjudicated_csv)
        for key in expected:
            if a[key]==b[key] and g[key]!=a[key]:
                raise ValueError('Adjudication changed an agreed grade without recorded correction: '+str(key))
    else:g=a
    relevance_by_q=collections.Counter(q for (q,c),v in g.items() if v==2)
    rowsq=[];summary=[]
    for method in METHODS:
        for q in all_q:
            ids=[cid for rank,cid in sorted(by[(method,q)])]
            binary=[int(g[(q,c)]==2) for c in ids]
            first=next((i+1 for i,x in enumerate(binary) if x),None)
            idcg=sum(1/math.log2(j+2) for j in range(min(relevance_by_q[q],5)))
            dcg=sum(x/math.log2(i+2) for i,x in enumerate(binary))
            rowsq.append(dict(method=method,question_id=q,hit5=int(any(binary)),precision5=sum(binary)/5,mrr5=1/first if first else 0,
                              ndcg5=dcg/idcg if idcg else 0,number_returned=len(ids),pool_grade2_count=relevance_by_q[q]))
        subset=[x for x in rowsq if x['method']==method]
        summary.append(dict(method=method,n=50,hit5=sum(x['hit5'] for x in subset)/50,precision5=sum(x['precision5'] for x in subset)/50,
                            mrr5=sum(x['mrr5'] for x in subset)/50,ndcg5=sum(x['ndcg5'] for x in subset)/50,question_hits=sum(x['hit5'] for x in subset)))
    write_csv(base/'H1_EIGHT_METHOD_METRICS_HUMAN.csv',summary,list(summary[0]))
    write_csv(base/'H1_PER_QUESTION_METRICS_HUMAN.csv',rowsq,list(rowsq[0]))
    bymq={(x['method'],x['question_id']):x for x in rowsq}
    delta=[dict(question_id=q,M7_hit5=bymq[('M7',q)]['hit5'],M8_hit5=bymq[('M8',q)]['hit5'],delta=bymq[('M8',q)]['hit5']-bymq[('M7',q)]['hit5']) for q in all_q]
    write_csv(base/'H1_M7_M8_DELTA.csv',delta,list(delta[0]))
    print('DONE - eight-method HUMAN-ADJUDICATED metrics saved; total pool grade2 questions:',sum(v>0 for v in relevance_by_q.values()))


if __name__=='__main__':
    if len(sys.argv)<2:sys.exit(__doc__)
    mode=sys.argv[1]
    try:
        if mode=='prepare' and len(sys.argv)==4:prep(Path(sys.argv[2]),Path(sys.argv[3]))
        elif mode=='evaluate' and len(sys.argv) in (5,6):evaluate(*map(Path,sys.argv[2:]))
        else:raise ValueError('Usage: prepare rankings.csv questions.csv OR evaluate rankings.csv reviewerA.csv reviewerB.csv [adjudicated.csv]')
    except (ValueError,FileNotFoundError) as exc:
        sys.exit('STOPPED: '+str(exc))
