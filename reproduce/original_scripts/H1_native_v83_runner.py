#!/usr/bin/env python3
"""IKO-Auto H1 new-question evaluation using ORIGINAL src.research_eval.method_runs.

This does not reimplement M1-M8, BM25, graph traversal, or indexing.
It refuses to score if the local project's original retriever cannot be
initialized reliably or if the corpus does not contain exactly 717 chunks.

Usage: python H1_native_v83_runner.py --project . --run
       python H1_native_v83_runner.py --project . --inspect
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib
import inspect
import json
from collections import Counter
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

METHOD_NAMES = [
    'bm25','bm25_metadata','bm25_metadata_section','bm25_graph',
    'bm25_metadata_graph','bm25_metadata_graph_fallback',
    'bm25_metadata_graph_v8_2','bm25_metadata_graph_intent_v8_3',
]
PDF_NAMES = ('axa_car_policy.pdf','admiral_car_policy.pdf','aviva_car_policy.pdf',
             'directline_car_policy.pdf','esure_car_policy.pdf')

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda: f.read(1<<20),b''):h.update(part)
    return h.hexdigest()

def load_csv(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def save_csv(path,rows,fields):
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def maybe_import(name):
    try:return importlib.import_module(name)
    except ImportError as ex:
        # Don't hide missing dependencies from actual Python source.
        if ex.name == name: return None
        raise RuntimeError(f'Could not import {name}: missing dependency {ex.name}. Install the original project requirements.') from ex

def inspect_bootstrap(project):
    print('Original project:',project)
    for fname in ('src/retrieval.py','src/pipeline.py','src/data_ingest.py','src/chunking.py','src/models.py','src/policy_catalog.py',
                  'src/cli.py','src/main.py','src/app.py','src/__main__.py'):
        p=project/fname
        if not p.is_file():continue
        import ast
        root=ast.parse(p.read_text(encoding='utf-8-sig'))
        print('\n'+fname)
        for node in root.body:
            if isinstance(node,ast.ClassDef):
                print(' CLASS',node.name)
                for method in node.body:
                    if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)) and method.name=='__init__':
                        print('   __init__(', ','.join(x.arg for x in method.args.args),')')
            if isinstance(node,ast.FunctionDef):
                print(' FUNCTION',node.name,'(',','.join(x.arg for x in node.args.args),')')
    print('\nThe original retrieval implementation is NOT modified by this diagnostic.')

def find_pdfs(project):
    for root in (project/'data'/'research_corpus',project/'research_corpus',project/'data',project):
        if root.is_dir() and all((root/name).is_file() for name in PDF_NAMES):return root
    raise RuntimeError('Cannot locate the five original PDFs. Expected data/research_corpus/ under --project.')

def verify_inputs(folder,project):
    question_path=folder/'H1_50_QUESTIONS_FOR_RETRIEVAL.csv'
    manifest_path=folder/'H1_MANIFEST.json'
    prep_path=folder/'H1_prepare_and_evaluate.py'
    for p in (question_path,manifest_path,prep_path):
        if not p.is_file():raise RuntimeError(f'H1 package file not found: {p}')
    rows=load_csv(question_path)
    if len(rows)!=50 or len(set(q['question_id'] for q in rows))!=50:
        raise RuntimeError('H1 input must contain exactly 50 distinct questions.')
    if Counter(q['insurer'] for q in rows)!=Counter({x:10 for x in ('AXA','Admiral','Aviva','Direct Line','esure')}):
        raise RuntimeError('H1 insurer balance is not 10 questions per insurer.')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    expected=manifest.get('benchmark_question_csv_sha256')
    if expected and digest(question_path)!=expected:
        raise RuntimeError('H1 question CSV hash differs from H1 manifest; do not run edited questions.')
    pdf_dir=find_pdfs(project)
    for insurer,data in manifest['source_files'].items():
        name=data['filename']
        if digest(pdf_dir/name)!=data['sha256']:
            raise RuntimeError(f'SOURCE PDF SHA-256 MISMATCH: {name}. The experiment must use the registered source edition.')
    for p in ('src/research_eval.py','src/graph_retrieval.py','src/v8_3_intent.py'):
        if not (project/p).is_file():raise RuntimeError(f'Missing original V8.3 component: {p}')
    graph=project/'outputs/v6/iko_auto_five_insurers_v6.ttl'
    enhanced=project/'outputs/v8_2/iko_auto_extended_v8_2.ttl'
    if not graph.is_file() or not enhanced.is_file():
        raise RuntimeError('V6/V8.2 RDF graph files are required in outputs/v6 and outputs/v8_2.')
    questions=[dict(question_id=q['question_id'],insurer=q['insurer'],question=q['question'],
                    category=q['category'],split='test',gold_exhaustive=False)
               for q in rows]
    return questions, question_path, prep_path, pdf_dir, graph, enhanced

# Exact native constructor identified in the uploaded original src/pipeline.py.
# This invokes the original loader, chunker and InsuranceRetriever unchanged.
def bootstrap_retriever(project, pdf_dir, graph):
    pipeline = maybe_import('src.pipeline')
    if pipeline is None or not callable(getattr(pipeline, 'build_pipeline', None)):
        raise RuntimeError('Cannot import original src.pipeline.build_pipeline. '
                           'Run this script from the original V8.3 project, with src/ and its dependencies present.')
    factory = pipeline.build_pipeline
    signature = inspect.signature(factory)
    print('Original pipeline:', 'src.pipeline.build_pipeline' + str(signature), flush=True)
    required = {'folder', 'chunk_words', 'overlap_words', 'graph_file'}
    if not required.issubset(signature.parameters):
        raise RuntimeError('Original build_pipeline signature changed; expected '
                           'folder, chunk_words, overlap_words, graph_file. STOP rather than guessing.')
    try:
        retriever = factory(folder=pdf_dir, chunk_words=170, overlap_words=45,
                            graph_file=None)
    except Exception as exc:
        raise RuntimeError('Original build_pipeline failed while reading the PDFs and chunking '
                           'the corpus. Check original dependencies and source folder; '
                           f'underlying error: {type(exc).__name__}: {exc}') from exc
    if not all(hasattr(retriever, attr) for attr in ('chunks', 'search', 'graph_index')):
        raise RuntimeError('Original build_pipeline did not return an InsuranceRetriever-like object.')
    backend = getattr(retriever, 'bm25_backend', 'not-reported-by-project')
    print('Original BM25 backend:', backend, flush=True)
    print('Original pipeline produced chunks:', len(retriever.chunks), flush=True)
    return retriever

def run(project,folder,output_dir):
    questions,qcsv,prep,pdf_dir,graph,enhanced=verify_inputs(folder,project)
    sys.path.insert(0,str(project))
    from src.research_eval import method_runs, METHODS, candidate_pool_rows
    from src.graph_retrieval import GraphIndex
    from src.v8_2_graph_build import FROZEN_V6_GRAPH_SHA256
    if digest(graph) != FROZEN_V6_GRAPH_SHA256:
        raise RuntimeError('V6 graph hash differs from original frozen V8.1/V8.2 graph. STOP.')
    if any(name not in METHODS for name in METHOD_NAMES):
        raise RuntimeError('Original research_eval does not implement all frozen eight methods.')
    retriever=bootstrap_retriever(project,pdf_dir,graph)
    if len(retriever.chunks)!=717 or len({c.chunk_id for c in retriever.chunks})!=717:
        raise RuntimeError(f'Original retriever did not produce 717 distinct chunks; got {len(retriever.chunks)}. STOP.')
    if not all(hasattr(c,a) for c in retriever.chunks for a in ('chunk_id','source_path','page','start_word','end_word','text')):
        raise RuntimeError('Original chunk model is missing required provenance fields.')
    # Crucially use ORIGINAL graph parser and indexing, not a new implementation.
    retriever.graph_index=GraphIndex(graph,retriever.chunks)
    enhanced_index=GraphIndex(enhanced,retriever.chunks)
    audit_paths=[graph,enhanced]+[project/name for name in (
        'src/research_eval.py','src/graph_retrieval.py','src/v8_3_intent.py',
        'src/retrieval.py','src/pipeline.py','src/models.py','src/policy_catalog.py',
        'src/v8_2_graph_build.py','src/heldout_v8.py') if (project/name).is_file()]
    root_hashes={str(p.relative_to(project)):digest(p) for p in audit_paths}
    fallback_audit=[]; intent_audit=[]
    print('Running ORIGINAL M1-M8 with k=5, pool_size=5, alpha=0.6 (50 H1 questions)')
    runs=method_runs(retriever,questions,METHOD_NAMES,k=5,alpha=0.6,pool_size=5,
        fallback_audit=fallback_audit,enhanced_graph_index=enhanced_index,intent_audit=intent_audit)
    if list(runs)!=METHOD_NAMES or any(set(runs[m])!={q['question_id'] for q in questions} for m in METHOD_NAMES):
        raise RuntimeError('Incomplete method_runs output')
    index={c.chunk_id:c for c in retriever.chunks}
    ranked=[]; unique_pairs=set()
    for idx,method in enumerate(METHOD_NAMES,1):
        for q in questions:
            qid=q['question_id']; ids=runs[method][qid]
            if len(ids)>5 or len(ids)!=len(set(ids)):
                raise RuntimeError(f'Invalid original engine ranking for {method}/{qid}')
            if not ids:
                ranked.append(dict(method=f'M{idx}',question_id=qid,rank=0,chunk_id='',
                                   source_path='',page='',text='',start_word='',end_word=''))
            for rank,cid in enumerate(ids,1):
                if cid not in index:raise RuntimeError(f'Unknown chunk {cid}')
                c=index[cid]; unique_pairs.add((qid,cid))
                ranked.append(dict(method=f'M{idx}',question_id=qid,rank=rank,chunk_id=cid,
                    source_path=c.source_path,page=c.page or '',text=c.text,
                    start_word=c.start_word,end_word=c.end_word))
    output_dir.mkdir(parents=True,exist_ok=True)
    fields=['method','question_id','rank','chunk_id','source_path','page','text','start_word','end_word']
    ranking_path=output_dir/'H1_EIGHT_METHOD_TOP5.csv'
    if ranking_path.exists():raise RuntimeError(f'Output already exists; preserve prior evaluation: {ranking_path}')
    save_csv(ranking_path,ranked,fields)
    (output_dir/'H1_ORIGINAL_METHOD_RUNS.json').write_text(json.dumps(runs,indent=2),encoding='utf-8')
    (output_dir/'H1_FALLBACK_AUDIT.json').write_text(json.dumps(fallback_audit,indent=2),encoding='utf-8')
    (output_dir/'H1_INTENT_GATE_AUDIT.json').write_text(json.dumps(intent_audit,indent=2),encoding='utf-8')
    after={str(p.relative_to(project)):digest(p) for p in audit_paths}
    if after!=root_hashes:raise RuntimeError('Original source/graph changed during run; do not use resulting output.')
    provenance={
       'description':'50 AI-assisted new questions on five previously seen insurance policies',
       'date_utc':datetime.now(timezone.utc).isoformat(),
       'engine':'unmodified src.research_eval.method_runs and src.graph_retrieval.GraphIndex',
       'methods':METHOD_NAMES,'method_ids':{f'M{i}':m for i,m in enumerate(METHOD_NAMES,1)},
       'n_questions':len(questions),'n_index_chunks':len(retriever.chunks),
       'bm25_backend':getattr(retriever,'bm25_backend','not-reported-by-project'),
       'chunk_constructor':'src.pipeline.build_pipeline(folder=original_pdf_dir, chunk_words=170, overlap_words=45, graph_file=None)',
       'n_distinct_pooled_pairs':len(unique_pairs),'top_k':5,'pool_size':5,'alpha':0.6,
       'original_files_sha256':root_hashes,'questions_sha256':digest(qcsv),
       'corpus_sha256':{p.name:digest(p) for p in sorted(pdf_dir.glob('*.pdf'))},
       'retrieval_csv_sha256':digest(ranking_path),
       'interpretation':'Not an unseen-document evaluation. Human judgments still required.'}
    (output_dir/'H1_RUN_PROVENANCE.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    subprocess.run([sys.executable,str(prep),'prepare',str(ranking_path),str(qcsv)],check=True)
    print('SUCCESS:',ranking_path)
    print('NEXT: independently grade H1_REVIEWER_A_BLINDED_BLANK.csv and H1_REVIEWER_B_BLINDED_BLANK.csv')

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--project',default='.',help='original IKO-Auto project root')
    p.add_argument('--package-dir',default=None,help='directory with H1 question CSV, corrected manifest and reviewer tool')
    p.add_argument('--output-dir',default='H1_RESULTS',help='new evaluation output folder')
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run',action='store_true')
    mode.add_argument('--inspect',action='store_true')
    a=p.parse_args()
    project=Path(a.project).resolve()
    folder=Path(a.package_dir).resolve() if a.package_dir else Path(__file__).resolve().parent
    try:
        if a.inspect:inspect_bootstrap(project)
        else:run(project,folder,Path(a.output_dir).resolve())
    except Exception as exc:
        print('\nSTOPPED:',str(exc),file=sys.stderr)
        sys.exit(1)
if __name__=='__main__':main()
