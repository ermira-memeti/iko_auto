"""V5 real-insurer corpus audit, SHA-pinned PDF RDF builder and diagnostic search."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.policy_catalog import scan_duplicates, named_insurers, allowed_sources
from src.pipeline import build_pipeline
from src.graph_builder import build_graph_from_annotations, save_graph

ANNOTATIONS = ROOT / 'data/research_v5/annotations/review_required_axa_admiral_annotations.json'
SCHEMA = ROOT / 'ontology/iko_auto_v2.ttl'


def run(args):
    if args.action == 'audit':
        report = scan_duplicates(args.docs)
        from src.real_corpus import audit_corpus
        report['v4_document_audit'] = audit_corpus(args.docs, args.chunk_words, args.overlap_words)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    if args.action == 'build-graph':
        g = build_graph_from_annotations(args.annotations, args.docs, SCHEMA)
        out = save_graph(g, args.out)
        ret = build_pipeline(args.docs, args.chunk_words, args.overlap_words, graph_file=out)
        from src.graph_validation import validate_graph
        report = validate_graph(ret.graph_index)
        if not report['passed']:
            out.unlink(missing_ok=True)
            raise RuntimeError('Graph structurally invalid: ' + '; '.join(report['errors']))
        print(json.dumps({'output': str(out.resolve()), 'review_status': 'SOURCE_QUOTES_VERIFIED_HUMAN_SEMANTIC_APPROVAL_PENDING',
                          'policies_in_graph':report['policies'], 'source_passages':report['source_passages'],
                          'relationship_assertions':report['relationship_assertions'],
                          'validation':report['passed']}, indent=2))
        return
    if args.action == 'compare':
        graph_path = Path(args.graph)
        ret = build_pipeline(args.docs, args.chunk_words, args.overlap_words,
                             graph_file=graph_path if graph_path.is_file() else None)
        named = named_insurers(args.query)
        if len(named)>1:
            raise ValueError('Question mentions multiple insurers; choose an explicit individual insurer for scope')
        sources = allowed_sources(ret.chunks, named[0]) if named else None
        configurations = [('unfiltered_bm25', None, False, 'none'),
                          ('metadata_bm25', sources, False, 'none'),
                          ('metadata_section_bm25', sources, True, 'none')]
        if ret.graph_index:
            configurations.append(('graph_bm25', None, False, 'graph'))
        out=[]
        for label, restrict, section, ont in configurations:
            try:
                hits=ret.search(args.query, method='bm25', top_k=args.top_k,
                                ontology_mode=ont, allowed_sources=restrict,
                                section_boost=section)
                out.append({'method':label,'results':[{'source':h.chunk.source_path,
                           'page':h.chunk.page, 'chunk_id':h.chunk.chunk_id, 'score':h.score,
                           'excerpt':h.chunk.text[:180]} for h in hits]})
            except Exception as exc:
                out.append({'method':label,'error':str(exc)})
        print(json.dumps({'question':args.query, 'explicit_insurer':named,
                          'warning':'UNLABELED DIAGNOSTIC RANKINGS ONLY, NOT STUDY METRICS',
                          'runs':out}, indent=2, ensure_ascii=False))


def parse():
    p=argparse.ArgumentParser(description='IKO-Auto V5 corpus and verified-PDF graph tools')
    actions=p.add_subparsers(dest='action',required=True)
    for name in ('audit','build-graph','compare'):
        s=actions.add_parser(name)
        s.add_argument('--docs',required=True)
        s.add_argument('--chunk-words',type=int,default=170)
        s.add_argument('--overlap-words',type=int,default=45)
        if name == 'build-graph':
            s.add_argument('--annotations',default=str(ANNOTATIONS))
            s.add_argument('--out',default='outputs/v5/iko_auto_real_v5.ttl')
        if name == 'compare':
            s.add_argument('--graph',default='outputs/v5/iko_auto_real_v5.ttl')
            s.add_argument('--query',required=True)
            s.add_argument('--top-k',type=int,default=5)
    return p.parse_args()

if __name__=='__main__':
    run(parse())
