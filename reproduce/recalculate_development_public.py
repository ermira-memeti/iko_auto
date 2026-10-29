#!/usr/bin/env python3
import csv, math, collections, argparse
METHODS=[f"M{i}" for i in range(1,9)]
def read(p):
    with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--rankings',default='results/development/IKO_Auto_Recalculated_Rank_Details_PUBLIC.csv')
    ap.add_argument('--labels',default='labels/development_reviewed_519_public.csv')
    a=ap.parse_args(); ranks=read(a.rankings); labs=read(a.labels)
    grade={(x['question_id'],x['chunk_id']):int(x['relevance']) for x in labs}
    qs=sorted({x['question_id'] for x in labs}); pool2=collections.Counter(q for (q,c),g in grade.items() if g==2)
    by=collections.defaultdict(list)
    for x in ranks: by[(x['method'],x['question_id'])].append(x)
    print('method,hit5,p5,mrr5,ndcg5,empty')
    for m in METHODS:
        H=[];P=[];RR=[];N=[];empty=0
        for q in qs:
            rows=sorted(by[m,q],key=lambda z:int(z['rank']))
            if not rows: empty+=1
            rel=[1 if grade[(q,x['chunk_id'])]==2 else 0 for x in rows]
            H.append(int(any(rel)));P.append(sum(rel)/5)
            first=next((i+1 for i,v in enumerate(rel) if v),0); RR.append(1/first if first else 0)
            dcg=sum(v/math.log2(i+2) for i,v in enumerate(rel)); ideal=sum(1/math.log2(i+2) for i in range(min(5,pool2[q])))
            N.append(dcg/ideal if ideal else 0)
        print(f'{m},{sum(H)/len(qs):.3f},{sum(P)/len(qs):.3f},{sum(RR)/len(qs):.3f},{sum(N)/len(qs):.3f},{empty}')
if __name__=='__main__': main()
