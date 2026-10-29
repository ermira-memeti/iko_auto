"""V8 CLI: external authored test-intake, integrity checks and human-gated evaluation."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.heldout_v8 import (DEFAULT_METHODS,template_csv,load_question_csv,audit_questions,
                            prepare_bundle,bundle_zip,verify_bundle_files,
                            evaluate_with_human_judgments)


def cli():
    p=argparse.ArgumentParser(description='IKO-Auto V8 external question intake; no generated relevance labels')
    subs=p.add_subparsers(dest='action',required=True)
    sp=subs.add_parser('template',help='Create BLANK 50-question authoring sheet');sp.add_argument('--out',required=True)
    sp=subs.add_parser('audit',help='Report V7 question overlap and author status');sp.add_argument('--questions',required=True)
    sp=subs.add_parser('prepare',help='Freeze retrieval and two BLANK reviewer sheets')
    sp.add_argument('--questions',required=True);sp.add_argument('--docs',required=True)
    sp.add_argument('--graph',default='');sp.add_argument('--enhanced-graph',default='');sp.add_argument('--out',required=True)
    sp.add_argument('--top-k',type=int,default=5);sp.add_argument('--pool-size',type=int,default=5)
    sp.add_argument('--chunk-words',type=int,default=170);sp.add_argument('--overlap-words',type=int,default=45)
    sp.add_argument('--model',default='sentence-transformers/all-MiniLM-L6-v2')
    sp.add_argument('--methods',nargs='+',default=DEFAULT_METHODS)
    sp=subs.add_parser('verify',help='Verify original V8 freeze integrity')
    sp.add_argument('--docs',required=True);sp.add_argument('--graph',default='');sp.add_argument('--enhanced-graph',default='')
    for name in ('manifest','questions','runs','pool'): sp.add_argument('--'+name,required=True)
    sp.add_argument('--fallback-audit',default='');sp.add_argument('--intent-audit',default='')
    sp=subs.add_parser('evaluate',help='Only score completed TWO HUMAN reviewer+adjudication records')
    sp.add_argument('--docs',required=True);sp.add_argument('--graph',default='');sp.add_argument('--enhanced-graph',default='')
    for name in ('manifest','questions','runs','pool','a','b','worklist','qrels','out'):
        sp.add_argument('--'+name,required=True)
    sp.add_argument('--fallback-audit',default='');sp.add_argument('--intent-audit',default='')
    return p


def main():
    args=cli().parse_args()
    if args.action=='template':
        path=Path(args.out)
        if path.exists():raise FileExistsError(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(template_csv(10),encoding='utf-8-sig')
        result={'template':str(path),'questions_written':0,'slots':50}
    elif args.action=='audit':
        result=audit_questions(load_question_csv(Path(args.questions)))
    elif args.action=='prepare':
        rows=load_question_csv(Path(args.questions))
        graph=Path(args.graph) if args.graph else None
        from src.pipeline import build_pipeline
        retriever=build_pipeline(args.docs,args.chunk_words,args.overlap_words,args.model,graph)
        bundle=prepare_bundle(retriever,args.docs,graph,rows,args.methods,args.top_k,args.pool_size,
                              chunk_words=args.chunk_words,overlap_words=args.overlap_words,model=args.model,
                              enhanced_graph=args.enhanced_graph or None)
        out=Path(args.out)
        if out.exists():raise FileExistsError(out)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(bundle_zip(bundle))
        result={'package':str(out),'summary':bundle['summary']}
    elif args.action=='verify':
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        result=verify_bundle_files(manifest,args.docs,args.graph or None,args.questions,args.runs,args.pool,
                                   args.fallback_audit or None,args.enhanced_graph or None,args.intent_audit or None)
    else:
        result=evaluate_with_human_judgments(docs=args.docs,graph=args.graph or None,
                  manifest_path=args.manifest,questions_path=args.questions,
                  runs_path=args.runs,pool_path=args.pool,reviewer_a=args.a,reviewer_b=args.b,
                  worklist_path=args.worklist,qrels_path=args.qrels,
                  fallback_audit_path=args.fallback_audit or None,enhanced_graph=args.enhanced_graph or None,
                  intent_audit_path=args.intent_audit or None)
        out=Path(args.out)
        if out.exists():raise FileExistsError(out)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        result={'saved':str(out),'status':result['status'],'n_rated_pairs':result['n_rated_pairs']}
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,ImportError) as e:
        print('IKO V8 error:',e,file=sys.stderr)
        raise SystemExit(1)
