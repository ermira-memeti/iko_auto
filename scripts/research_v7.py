"""V7 real-policy *development pilot*: seeds -> retrieval pool -> independent judgments.

No scripts auto-populate relevance labels. No provisional pilot may be called
independent held-out test evidence. V4 'freeze' workflow remains available.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.pilot_v7 import (DEFAULT_METHODS,author_pilot,validate_pilot_questions,
                         validate_source_hints,prepare_pilot_bundle,write_pilot_outputs,
                         verify_manifest,questions_jsonl)
from src.research_eval import (questions_from,read_labels,score_runs,category_summary,
                               factorial_ablation,paired_bootstrap)
from src.annotation_workflow import merge_independent_ratings,finalize_human_adjudication

ANN=ROOT/'data/research_v6/annotations/review_required_five_insurers.json'
DOC=ROOT/'data/research_corpus'
GRAPH=ROOT/'outputs/v6/iko_auto_five_insurers_v6.ttl'


def selected_pilot(n:int) -> tuple[list[dict],list[dict]]:
    questions,hints=author_pilot(ANN)
    if n not in {10,25,50}: raise ValueError('Pilot size must be 10,25 or 50')
    count=n//5
    keep={q['question_id'] for q in questions if int(q['question_id'].rsplit('_',1)[-1])<=count}
    return [q for q in questions if q['question_id'] in keep],[x for x in hints if x['question_id'] in keep]


def validate_real_folder(docs,graph,hints):
    from src.policy_catalog import scan_duplicates
    if not Path(docs).is_dir(): raise FileNotFoundError(docs)
    dup=scan_duplicates(docs)
    if dup['skipped_aliases']:
        raise ValueError('Corpus has exact duplicate documents; remove copies: '+str(dup['skipped_aliases']))
    proof=validate_source_hints(hints,docs)
    if not proof['passed']:
        raise ValueError('Source-hint validation failed: '+'; '.join(proof['errors'][:5]))
    from src.graph_builder import build_graph_from_annotations
    # Reverify the underlying draft graph against the original PDFs.
    build_graph_from_annotations(ANN,docs,ROOT/'ontology/iko_auto_v6.ttl')
    if graph is not None and not Path(graph).is_file(): raise FileNotFoundError(graph)
    return proof


def parser():
    p=argparse.ArgumentParser(description='IKO-Auto V7 development-only real-policy evaluation')
    sub=p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('seed',help='Export only 10/25/50 DEVELOPMENT questions and researcher evidence hints')
    s.add_argument('--size',type=int,default=50,choices=[10,25,50])
    s.add_argument('--out',default=str(ROOT/'outputs/v7/seeds'))
    s=sub.add_parser('prepare',help='Create immutable pilot pool, two blank blinded reviewer sheets, manifest and run IDs')
    s.add_argument('--docs',default=str(DOC));s.add_argument('--graph',default=str(GRAPH))
    s.add_argument('--size',type=int,default=10,choices=[10,25,50])
    s.add_argument('--out',default=str(ROOT/'outputs/v7/pilot_run_01'))
    s.add_argument('--top-k',type=int,default=5);s.add_argument('--pool-size',type=int,default=5)
    s.add_argument('--chunk-words',type=int,default=170);s.add_argument('--overlap-words',type=int,default=45)
    s.add_argument('--alpha',type=float,default=0.6)
    s.add_argument('--model',default='sentence-transformers/all-MiniLM-L6-v2')
    s.add_argument('--methods',nargs='+',default=DEFAULT_METHODS)
    s=sub.add_parser('verify',help='Check corpus and graph hashes against a V7 run manifest')
    s.add_argument('--manifest',required=True);s.add_argument('--docs',default=str(DOC));s.add_argument('--graph',default=str(GRAPH))
    s=sub.add_parser('merge-raters',help='Calculate agreement; output BLANK human adjudication worklist')
    s.add_argument('--pool',required=True);s.add_argument('--a',required=True);s.add_argument('--b',required=True)
    s.add_argument('--out',required=True)
    s=sub.add_parser('finalize',help='Require each final label and human adjudicator ID')
    s.add_argument('--pool',required=True);s.add_argument('--worklist',required=True);s.add_argument('--out',required=True)
    s=sub.add_parser('evaluate',help='Score fully human-adjudicated DEV labels; held-out test is not in this pilot')
    s.add_argument('--docs',default=str(DOC));s.add_argument('--graph',default=str(GRAPH))
    s.add_argument('--manifest',required=True);s.add_argument('--questions',required=True)
    s.add_argument('--runs',required=True);s.add_argument('--qrels',required=True)
    s.add_argument('--pool',required=True);s.add_argument('--a',required=True);s.add_argument('--b',required=True)
    s.add_argument('--worklist',required=True);s.add_argument('--out',required=True)
    return p


def main():
    p=parser();args=p.parse_args()
    if args.cmd in {'seed','prepare'}:
        qs,hints=selected_pilot(args.size)
        if args.cmd=='seed':
            folder=Path(args.out)
            if folder.exists() and any(folder.iterdir()): raise FileExistsError(folder)
            folder.mkdir(parents=True,exist_ok=True)
            (folder/'questions_DEV_ONLY.jsonl').write_text(questions_jsonl(qs),encoding='utf-8')
            from src.pilot_v7 import csv_data
            (folder/'RESEARCHER_ONLY_source_hints.csv').write_text(csv_data(hints),encoding='utf-8-sig')
            result={'status':'DEV_SEEDS_ONLY_NO_LABELS','size':len(qs),'path':str(folder.resolve())}
        else:
            graph=Path(args.graph) if args.graph.strip() else None
            validate_real_folder(args.docs,graph,hints)
            from src.pipeline import build_pipeline
            retriever=build_pipeline(args.docs,args.chunk_words,args.overlap_words,args.model,graph)
            bundle=prepare_pilot_bundle(retriever,args.docs,graph,qs,args.methods,args.top_k,
                                        args.pool_size,args.alpha,args.chunk_words,args.overlap_words,args.model)
            output=write_pilot_outputs(args.out,bundle,hints)
            result={**bundle['summary'],'output_folder':str(Path(args.out).resolve()),'files':output}
    elif args.cmd=='verify':
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        result=verify_manifest(manifest,args.docs,args.graph or None)
        if not result['passed']: print(json.dumps(result,indent=2));raise SystemExit(2)
    elif args.cmd=='merge-raters':
        result=merge_independent_ratings(args.pool,args.a,args.b,args.out)
    elif args.cmd=='finalize':
        result=finalize_human_adjudication(args.worklist,args.out,args.pool)
    else:
        from src.pilot_v7 import evaluate_reviewed_pilot
        details=evaluate_reviewed_pilot(
            docs=args.docs,graph=args.graph or None,
            manifest_path=args.manifest,questions_path=args.questions,
            runs_path=args.runs,qrels_path=args.qrels,pool_path=args.pool,
            reviewer_a_path=args.a,reviewer_b_path=args.b,worklist_path=args.worklist)
        dest=Path(args.out)
        if dest.exists(): raise FileExistsError(dest)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(details,indent=2,ensure_ascii=False),encoding='utf-8')
        result={'output':str(dest.resolve()),'n_question_method_records':len(details['details']),
                'split':'DEV_ONLY','status':'PRELIMINARY_DESCRIPTIVE_NOT_PUBLICATION_RESULTS'}
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,ImportError) as e:
        print('V7 workflow error:',e,file=sys.stderr)
        raise SystemExit(1)
