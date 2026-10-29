"""IKO-Auto V6 five-insurer source-pinned graph and human review CLI."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.graph_builder import build_graph_from_annotations,save_graph
from src.graph_retrieval import GraphIndex
from src.graph_validation import validate_graph
from src.pipeline import build_pipeline
from src.v6_review import load_annotations,review_rows,sheet_csv,read_reviewed_csv,comparison

DEFAULT_ANNOTATIONS=ROOT/'data/research_v6/annotations/review_required_five_insurers.json'
DEFAULT_SCHEMA=ROOT/'ontology/iko_auto_v6.ttl'
DEFAULT_OUT=ROOT/'outputs/v6/iko_auto_five_insurers_v6.ttl'


def main():
    parser=argparse.ArgumentParser(description='IKO-Auto V6 five-insurer RDF and review workflow')
    subs=parser.add_subparsers(dest='action',required=True)
    for action in ('build-graph','review-sheets','check-review'):
        s=subs.add_parser(action)
        s.add_argument('--annotations',default=str(DEFAULT_ANNOTATIONS))
        if action=='build-graph':
            s.add_argument('--docs',default=str(ROOT/'data/research_corpus'))
            s.add_argument('--out',default=str(DEFAULT_OUT))
            s.add_argument('--chunk-words',type=int,default=170)
            s.add_argument('--overlap-words',type=int,default=45)
        elif action=='review-sheets':
            s.add_argument('--out-dir',default=str(ROOT/'outputs/v6/review'))
        else:
            s.add_argument('--reviewer-a',required=True)
            s.add_argument('--reviewer-b',required=True)
    args=parser.parse_args()
    if args.action=='build-graph':
        graph=build_graph_from_annotations(args.annotations,args.docs,DEFAULT_SCHEMA)
        outfile=save_graph(graph,args.out)
        try:
            retriever=build_pipeline(args.docs,args.chunk_words,args.overlap_words,graph_file=outfile)
            report=validate_graph(retriever.graph_index)
            if not report['passed']:
                raise RuntimeError('; '.join(report['errors']))
        except Exception:
            outfile.unlink(missing_ok=True)
            raise
        print(json.dumps({'output':str(outfile.resolve()),'status':'SHA256_AND_PAGE_QUOTES_VERIFIED_EXPERT_REVIEW_PENDING',**report},indent=2,ensure_ascii=False))
    elif args.action=='review-sheets':
        out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
        ann=load_annotations(args.annotations)
        for r in ('A','B'):
            dest=out/f'v6_ontology_reviewer_{r}.csv'
            dest.write_text(sheet_csv(ann, f'Reviewer {r}'),encoding='utf-8-sig')
            print(dest.resolve())
        print('Candidate decisions intentionally BLANK; separate reviewers must inspect evidence and mark decisions.')
    else:
        candidates=review_rows(args.annotations)
        a=read_reviewed_csv(Path(args.reviewer_a).read_bytes())
        b=read_reviewed_csv(Path(args.reviewer_b).read_bytes())
        result=comparison(candidates,a,b)
        print(json.dumps(result,indent=2,ensure_ascii=False))
        if not result['valid']:
            raise SystemExit(2)

if __name__=='__main__':
    main()
