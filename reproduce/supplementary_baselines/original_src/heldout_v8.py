"""Version 8: independent-question intake and audit-first, source-pinned evaluation.

No generated questions or judgments are called independent human evidence.  This module
accepts externally written questions, checks overlap with V7 development prompts,
and exports BLANK method-blinded relevance sheets.  Five existing insurers are SEEN
POLICIES: independent questions alone cannot establish unseen-policy generalization.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .pilot_v7 import SEEDS, author_pilot, csv_data, questions_jsonl, sha256, verify_manifest
from .research_eval import (METHODS, GRAPH_MODES, candidate_pool_rows, method_runs,
                            questions_from, read_labels, score_runs, category_summary,
                            paired_bootstrap)
from .annotation_workflow import SHEET_COLUMNS, merge_independent_ratings, finalize_human_adjudication

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / 'data/research_v6/annotations/review_required_five_insurers.json'
COLUMNS = ['question_id', 'insurer', 'category', 'question', 'author_id',
           'author_type', 'created_without_access_to_ontology', 'source_document', 'notes']
REVIEWER_COLUMNS = SHEET_COLUMNS
DEFAULT_METHODS = ['bm25','bm25_metadata','bm25_metadata_section','bm25_graph','bm25_metadata_graph','bm25_metadata_graph_fallback','bm25_metadata_graph_v8_2','bm25_metadata_graph_intent_v8_3']
ALLOWED_TYPES = {'independent_human', 'researcher', 'ai_assisted'}
INTEGRITY_SCHEMA = 'iko-auto-v8-question-intake-1'
FREEZE_CODE_FILES = ['src/heldout_v8.py','src/retrieval.py','src/graph_retrieval.py',
                     'src/research_eval.py','src/pipeline.py','src/pilot_v7.py',
                     'ontology/iko_auto_v6.ttl','src/v8_2_graph_build.py',
                     'data/research_v8_2/draft_additions.json','src/v8_3_intent.py',
                     'src/v8_3_compare.py']


def template_rows(per_insurer: int = 10) -> list[dict]:
    if not 1 <= per_insurer <= 100:
        raise ValueError('per_insurer must be 1..100')
    return [{**{key:'' for key in COLUMNS},'question_id': f'V8Q_{insurer.replace(" ", "").upper()}_{i:03d}',
             'insurer':insurer} for insurer in SEEDS for i in range(1, per_insurer + 1)]


def template_csv(per_insurer: int = 10) -> str:
    return _csv(template_rows(per_insurer), COLUMNS)


def _csv(rows: list[dict], cols: list[str]) -> str:
    mem=io.StringIO(newline='')
    writer=csv.DictWriter(mem,fieldnames=cols,extrasaction='ignore',lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return mem.getvalue()


def _norm(s: str) -> str:
    return ' '.join(re.findall(r'[a-z0-9]+', str(s).casefold()))


def _similarity(a: str, b: str) -> tuple[float, float]:
    a,b=_norm(a),_norm(b)
    tok_a,tok_b=set(a.split()),set(b.split())
    jacc=len(tok_a & tok_b)/max(1,len(tok_a | tok_b))
    return difflib.SequenceMatcher(None,a,b).ratio(),jacc


def load_question_csv(content: bytes | str | Path) -> list[dict]:
    if isinstance(content, bytes):
        txt=content.decode('utf-8-sig')
    elif isinstance(content, Path):
        txt=content.read_text(encoding='utf-8-sig')
    elif isinstance(content,str) and ('\n' in content or content.startswith('question_id,')):
        txt=content
    else:
        txt=Path(str(content)).read_text(encoding='utf-8-sig')
    reader=csv.DictReader(io.StringIO(txt))
    if not reader.fieldnames or set(COLUMNS)-set(reader.fieldnames):
        raise ValueError('Question CSV needs all columns: '+', '.join(COLUMNS))
    return [{key:str(row.get(key) or '').strip() for key in COLUMNS} for row in reader]


def audit_questions(rows: list[dict], dev_questions: list[dict] | None = None) -> dict:
    if dev_questions is None:
        dev_questions,_=author_pilot(ANN)
    problems=[]; warnings=[]; overlaps=[]; canonical=[]; ids=set(); previous={}
    if not rows:
        problems.append('No question rows were provided')
    for n,r in enumerate(rows, 1):
        qid,q,insurer=r['question_id'],r['question'],r['insurer']
        if not qid or qid in ids:
            problems.append(f'Row {n}: empty or duplicate question_id')
        ids.add(qid)
        if insurer not in SEEDS:
            problems.append(f'{qid}: insurer must be one of {list(SEEDS)}')
        if len(q) < 18 or q.lower().startswith(('question here','write a question')):
            problems.append(f'{qid}: question is missing or too short')
        if not r['category']:
            problems.append(f'{qid}: category is missing')
        if not r['author_id']:
            problems.append(f'{qid}: author_id is missing')
        if r['author_type'] not in ALLOWED_TYPES:
            problems.append(f'{qid}: author_type must be one of {sorted(ALLOWED_TYPES)}')
        if r['created_without_access_to_ontology'].lower() not in {'yes','no'}:
            problems.append(f'{qid}: created_without_access_to_ontology must be yes or no')
        key=_norm(q)
        if key in previous:
            problems.append(f'{qid}: repeated question text from {previous[key]}')
        previous[key]=qid
        for d in dev_questions:
            sequence,jaccard=_similarity(q,d['question'])
            if _norm(q)==_norm(d['question']) or sequence>=0.91 or (jaccard>=0.87 and sequence>=0.72):
                overlaps.append({'new_question_id':qid,'development_question_id':d['question_id'],
                                 'sequence_similarity':round(sequence,3),'token_jaccard':round(jaccard,3),
                                 'new_question':q,'development_question':d['question']})
                break
            if sequence>=0.75 or jaccard>=0.70:
                warnings.append(f'{qid} is conceptually close to development question {d["question_id"]}; review manually')
        canonical.append(r)
    if overlaps:
        problems.append(f'{len(overlaps)} near-duplicate(s) of V7 development questions; do not treat as held-out')
    independent=bool(rows) and all(
        r['author_type']=='independent_human' and r['created_without_access_to_ontology'].lower()=='yes'
        for r in rows)
    tier=('CANDIDATE_QUESTION_HOLDOUT_SEEN_POLICIES_SELF_REPORTED'
          if not problems and independent else 'DEVELOPMENT_OR_DRAFT_ONLY')
    if not independent:
        warnings.append('Some questions are researcher/AI-authored or author independence is not declared; not held-out.')
    warnings.append('The existing five insurers were used in ontology development: this is NEVER an unseen-policy holdout.')
    if len({r['insurer'] for r in rows})<5:
        warnings.append('Not all five known insurers are represented.')
    if any(not r['source_document'] for r in rows):
        warnings.append('Some questions have no original-policy document reference; source provenance should be recorded.')
    return {'passed':not problems,'evaluation_tier':tier,'n_questions':len(rows),
            'insurers':dict(Counter(r['insurer'] for r in rows)),
            'author_types':dict(Counter(r['author_type'] for r in rows)),
            'errors':problems,'warnings':list(dict.fromkeys(warnings))[:30],
            'near_duplicate_development':overlaps,'n_manual_overlap_warnings':sum('conceptually close to development' in w for w in warnings)}


def to_eval_questions(rows: list[dict], tier: str) -> list[dict]:
    if tier not in {'CANDIDATE_QUESTION_HOLDOUT_SEEN_POLICIES_SELF_REPORTED','DEVELOPMENT_OR_DRAFT_ONLY'}:
        raise ValueError('Invalid question-tier classification')
    split='test' if tier.startswith('CANDIDATE_') else 'dev'
    return [dict(question_id=r['question_id'],question=r['question'],insurer=r['insurer'],
                 category=r['category'],split=split,gold_exhaustive=False,
                 policy_family=f'{r["insurer"]}_seen_policy',author_id=r['author_id'],
                 question_author_type=r['author_type'],question_origin='external_csv_submission',
                 self_reported_no_ontology_access=r['created_without_access_to_ontology'].lower()=='yes')
            for r in rows]


def _source_checks(docs: str | Path, graph: str | Path | None) -> dict:
    root=Path(docs).resolve()
    if not root.is_dir(): raise FileNotFoundError(root)
    files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in {'.pdf','.txt','.md'})
    if not files: raise ValueError('Document corpus is empty')
    from .policy_catalog import scan_duplicates
    duplicated=scan_duplicates(root)
    if duplicated['skipped_aliases']:
        raise ValueError('Corpus contains duplicate policy files: '+str(duplicated['skipped_aliases']))
    if graph is not None and not Path(graph).is_file(): raise FileNotFoundError(graph)
    return {str(p.relative_to(root).as_posix()):sha256(p) for p in files}


def prepare_bundle(retriever, docs, graph, rows, methods, k=5, pool_size=5,
                   alpha=0.6,chunk_words=170,overlap_words=45,
                   model='sentence-transformers/all-MiniLM-L6-v2',
                   enhanced_graph=None) -> dict:
    audit=audit_questions(rows)
    if not audit['passed']: raise ValueError('Question audit failed: '+'; '.join(audit['errors'][:8]))
    if not methods or len(set(methods))!=len(methods) or set(methods)-set(METHODS):
        raise ValueError('Unsupported or repeated retrieval method')
    if not 1<=k<=pool_size<=30: raise ValueError('Require 1 <= top_k <= pool_size <= 30')
    if set(methods)&GRAPH_MODES and graph is None:
        raise ValueError('Graph retrieval requires an existing compatible RDF graph')
    files=_source_checks(docs,graph)
    from .policy_catalog import allowed_sources
    for insurer in {r['insurer'] for r in rows}:
        if not allowed_sources(retriever.chunks,insurer):
            raise ValueError(f'No indexed passages from {insurer}')
    questions=to_eval_questions(rows,audit['evaluation_tier'])
    enhanced_index = None
    enhanced_graph_hash = None
    if {'bm25_metadata_graph_v8_2','bm25_metadata_graph_intent_v8_3'} & set(methods):
        if not enhanced_graph or not Path(enhanced_graph).is_file():
            raise ValueError('Build V8.2 extended RDF graph before selecting the V8.2 method')
        from .graph_retrieval import GraphIndex
        from .v8_2_graph_build import FROZEN_V6_GRAPH_SHA256
        if graph is None or sha256(graph) != FROZEN_V6_GRAPH_SHA256:
            raise ValueError('V8.2 study requires the EXACT V8.1 frozen original V6 graph')
        enhanced_index=GraphIndex(enhanced_graph,retriever.chunks)
        enhanced_graph_hash=sha256(enhanced_graph)
    fallback_audit=[]
    intent_audit=[]
    runs=method_runs(retriever,questions,methods,k,alpha,pool_size,
                     fallback_audit=fallback_audit, enhanced_graph_index=enhanced_index,
                     intent_audit=intent_audit)
    pool=candidate_pool_rows(questions,runs,retriever.chunks)
    if not pool: raise ValueError('No candidate passages retrieved')
    questions_blob=questions_jsonl(questions)
    manifest={'schema':INTEGRITY_SCHEMA,'status':audit['evaluation_tier'],
              'scope':'SEEN_POLICY_QUESTION_HOLDOUT_NOT_UNSEEN_POLICY',
              'created_utc':datetime.now(timezone.utc).isoformat(),
              'questions_source':'externally_submitted_or_researcher_csv',
              'frozen_code_sha256':{key:sha256(ROOT/key) for key in FREEZE_CODE_FILES},
              'independence':'SELF_REPORTED_NOT_EXTERNALLY_VERIFIED',
              'corpus_path':str(Path(docs).resolve()),'source_sha256':files,
              'graph_path':str(Path(graph).resolve()) if graph else None,
              'graph_sha256':sha256(graph) if graph else None,
              'n_questions':len(questions),'n_pool_pairs':len(pool),
              'methods':list(methods),
              'parameters':dict(top_k=k,pool_size=pool_size,alpha=alpha,
                  chunk_words=chunk_words,overlap_words=overlap_words,embedding_model=model),
              'questions_sha256':hashlib.sha256(questions_blob.encode('utf-8')).hexdigest(),
              'submitted_questions_sha256':hashlib.sha256(_csv(rows,COLUMNS).encode('utf-8')).hexdigest(),
              'pool_sha256':hashlib.sha256(csv_data(pool).encode('utf-8')).hexdigest(),
              'runs_sha256':hashlib.sha256(json.dumps(runs,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest(),
              'fallback_audit_sha256':hashlib.sha256(json.dumps(fallback_audit,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest(),
              'fallback_method': 'bm25_metadata_graph_fallback' if 'bm25_metadata_graph_fallback' in methods else None,
              'enhanced_graph_method': 'bm25_metadata_graph_v8_2' if 'bm25_metadata_graph_v8_2' in methods else None,
              'intent_gate_method': 'bm25_metadata_graph_intent_v8_3' if 'bm25_metadata_graph_intent_v8_3' in methods else None,
              'intent_gate_version':'v8.3-explicit-insurer-topic-v1' if intent_audit else None,
              'intent_audit_sha256':hashlib.sha256(json.dumps(intent_audit,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest(),
              'enhanced_graph_path': str(Path(enhanced_graph).resolve()) if enhanced_index is not None else None,
              'enhanced_graph_sha256': enhanced_graph_hash,
              'enhanced_graph_status': 'SOURCE_VERIFIED_DEVELOPMENT_DRAFT_NOT_HUMAN_REVIEWED' if enhanced_index is not None else None,
              'labels':'NONE','metric_status':'NOT_COMPUTED','pdf_redistribution':'FORBIDDEN_WITHOUT_PERMISSION'}
    blinded=[{col:p.get(col,'') for col in REVIEWER_COLUMNS} for p in pool]
    return {'questions':questions,'submitted':rows,'audit':audit,'runs':runs,
            'pool':pool,'blinded':blinded,'manifest':manifest,'fallback_audit':fallback_audit,'intent_audit':intent_audit,
            'summary':{'questions':len(questions),'pool_pairs':len(pool),'methods':list(methods),
                       'status':audit['evaluation_tier'],'labels':0,
                       'fallback_count':sum(e['fallback_used'] for e in fallback_audit),
                       'intent_extended_count':sum(e['route']=='enhanced_v8_2' for e in intent_audit)}}


def bundle_zip(bundle: dict) -> bytes:
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('01_SUBMITTED_QUESTION_INTAKE.csv',_csv(bundle['submitted'],COLUMNS))
        z.writestr('02_QUESTIONS_FOR_EVALUATION.jsonl',questions_jsonl(bundle['questions']))
        z.writestr('03_QUESTION_AUDIT.json',json.dumps(bundle['audit'],indent=2,ensure_ascii=False))
        z.writestr('INTERNAL_POOLED_PASSAGES.csv',csv_data(bundle['pool']))
        for rid in ('reviewer_A','reviewer_B'):
            vals=[{**p,'annotator_id':rid,'relevance':'','evidence_quote':'','notes':''} for p in bundle['blinded']]
            z.writestr(f'BLINDED_{rid}_BLANK.csv',_csv(vals,REVIEWER_COLUMNS))
        z.writestr('04_FROZEN_MANIFEST.json',json.dumps(bundle['manifest'],indent=2,ensure_ascii=False))
        z.writestr('INTERNAL_RETRIEVAL_RUNS.json',json.dumps(bundle['runs'],indent=2,ensure_ascii=False))
        z.writestr('INTERNAL_FALLBACK_AUDIT.json',json.dumps(bundle.get('fallback_audit',[]),indent=2,ensure_ascii=False))
        z.writestr('INTERNAL_INTENT_GATE_AUDIT.json',json.dumps(bundle.get('intent_audit',[]),indent=2,ensure_ascii=False))
        z.writestr('READ_FIRST.txt',
          'IKO-Auto V8: frozen, method-blinded question-passage candidate pool.\n'
          'The two BLINDED files are intentionally BLANK. Only two actually distinct independent humans\n'
          'can produce a two-rater agreement estimate. AI-assisted annotations are DEVELOPMENT ONLY.\n'
          'Keep INTERNAL files from reviewers, and archive the original ZIP unchanged.\n'
          f'STATUS: {bundle["audit"]["evaluation_tier"]}\n'
          'The five insurers are SEEN policies (ontology was built with these documents).\n'
          'Independence of external authoring is SELF-REPORTED, not verified by software.\n'
          'No measured performance, human ratings, or adjudicated labels are bundled.\n'
          'V8.1 fallback is a DISTINCT method, invoked ONLY when original graph retrieval returns zero passages.\n'
          'No original V8 runs or scores have been overwritten. Check INTERNAL_FALLBACK_AUDIT.json.\n'
          'V8.2 adds a DISTINCT seventh ontology method; five source-provenance-checked new\n'
          'coverage relations were selected after development failure analysis. NOT held-out.\n'
          'V8.3 adds a DISTINCT eighth method: guarded concept activation vs original V6.\n'
          'See INTERNAL_INTENT_GATE_AUDIT.json. Rules designed on these development questions.\n')
    return out.getvalue()


def verify_bundle_files(manifest,docs,graph,questions_path,runs_path,pool_path,
                        fallback_audit_path=None, enhanced_graph=None, intent_audit_path=None):
    if manifest.get('schema')!=INTEGRITY_SCHEMA: raise ValueError('Wrong V8 manifest schema')
    check=verify_manifest(manifest,docs,graph)
    for key, expected in manifest.get('frozen_code_sha256',{}).items():
        if key not in FREEZE_CODE_FILES or sha256(ROOT/key)!=expected:
            raise ValueError(f'Implementation code changed after freeze: {key}')
    if set(manifest.get('frozen_code_sha256',{}))!=set(FREEZE_CODE_FILES):
        raise ValueError('Manifest lacks complete code-version hashes')
    if not check['passed']: raise ValueError('Corpus or graph changed: '+str(check['errors']))
    if manifest.get('enhanced_graph_method') or manifest.get('intent_gate_method'):
        if not enhanced_graph or not Path(enhanced_graph).is_file() or sha256(enhanced_graph)!=manifest.get('enhanced_graph_sha256'):
            raise ValueError('Enhanced V8.2 RDF graph missing or modified since the original freeze')
    questions_txt=Path(questions_path).read_text(encoding='utf-8-sig')
    if hashlib.sha256(questions_txt.encode('utf-8')).hexdigest()!=manifest['questions_sha256']:
        raise ValueError('Questions changed since freeze')
    run=json.loads(Path(runs_path).read_text(encoding='utf-8'))
    if list(run)!=manifest['methods'] or hashlib.sha256(json.dumps(run,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()!=manifest['runs_sha256']:
        raise ValueError('Retrieval runs modified')
    with Path(pool_path).open(encoding='utf-8-sig',newline='') as f: pool=list(csv.DictReader(f))
    if hashlib.sha256(csv_data(pool).encode('utf-8')).hexdigest()!=manifest['pool_sha256']:
        raise ValueError('Pooled passages modified')
    if len(pool)!=manifest['n_pool_pairs']: raise ValueError('Pool pair count mismatch')
    if manifest.get('fallback_method'):
        if fallback_audit_path is None:
            raise ValueError('V8.1 fallback manifest needs its INTERNAL_FALLBACK_AUDIT.json')
        audit=json.loads(Path(fallback_audit_path).read_text(encoding='utf-8'))
        checksum=hashlib.sha256(json.dumps(audit,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
        if checksum!=manifest.get('fallback_audit_sha256'):
            raise ValueError('Fallback provenance audit changed since freeze')
    if manifest.get('intent_gate_method'):
        if not intent_audit_path:
            raise ValueError('V8.3 intent-gate manifest requires INTERNAL_INTENT_GATE_AUDIT.json')
        audit=json.loads(Path(intent_audit_path).read_text(encoding='utf-8'))
        checksum=hashlib.sha256(json.dumps(audit,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
        if checksum!=manifest.get('intent_audit_sha256'):
            raise ValueError('V8.3 intent-routing audit changed since freeze')
        if len(audit)!=manifest.get('n_questions') or any(
            e.get('method')!=manifest['intent_gate_method'] or
            e.get('route') not in {'enhanced_v8_2','original_v6'}
            for e in audit):
            raise ValueError('V8.3 intent audit is incomplete or invalid')
    return {'verified':True,'n_pairs':len(pool),'status':manifest['status']}


def evaluate_with_human_judgments(*,docs,graph,manifest_path,questions_path,runs_path,
                                  pool_path,reviewer_a,reviewer_b,worklist_path,qrels_path,
                                  fallback_audit_path=None,enhanced_graph=None,intent_audit_path=None):
    """Reject blank/missing human reviews; validate immutable run before computing scores.

    Cannot verify actual human identity; only records that the two input sheets *claim*
    distinct reviewer IDs and contains independent ratings.  Never synthesize agreement.
    """
    from .annotation_workflow import _read_csv, _keys, _verify_rating
    import tempfile
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    verify_bundle_files(manifest,docs,graph,questions_path,runs_path,pool_path,
                        fallback_audit_path=fallback_audit_path, enhanced_graph=enhanced_graph,
                        intent_audit_path=intent_audit_path)
    questions=questions_from(questions_path)
    tier=manifest['status']
    if any(q['split'] != ('test' if tier.startswith('CANDIDATE_') else 'dev') for q in questions):
        raise ValueError('Question split differs from original source-of-authorship status')
    if tier.startswith('CANDIDATE_') and any(q.get('question_author_type')!='independent_human' or not q.get('self_reported_no_ontology_access') for q in questions):
        raise ValueError('Claimed independent authoring conflicts with question provenance')
    runs=json.loads(Path(runs_path).read_text(encoding='utf-8'))
    pool=_keys(_read_csv(pool_path),'Frozen pool')
    left=_keys(_read_csv(reviewer_a),'Reviewer A')
    right=_keys(_read_csv(reviewer_b),'Reviewer B')
    adjud=_keys(_read_csv(worklist_path),'Human adjudication')
    if set(pool)!=set(left) or set(pool)!=set(right) or set(pool)!=set(adjud):
        raise ValueError('Incomplete or modified reviewer/adjudication rows')
    aids={x.get('annotator_id','').strip() for x in left.values()}
    bids={x.get('annotator_id','').strip() for x in right.values()}
    if len(aids)!=1 or len(bids)!=1 or not next(iter(aids)) or not next(iter(bids)) or aids==bids:
        raise ValueError('Two distinct nonempty reviewer IDs required')
    aid,bid=next(iter(aids)),next(iter(bids))
    for key in pool:
        for sheet,identity in ((left,aid),(right,bid)):
            r=sheet[key]; _verify_rating(r,0,identity)
            for k in ('question','text','source_path','page','chunk_id','question_id'):
                if str(r.get(k,''))!=str(pool[key].get(k,'')):
                    raise ValueError(f'Reviewer changed source field {k} in {key}')
        row=adjud[key]
        if row.get('rater_a_id','').strip()!=aid or row.get('rater_b_id','').strip()!=bid:
            raise ValueError(f'Adjudication rater IDs modified for {key}')
        if row.get('rater_a_label','').strip()!=left[key]['relevance'].strip() or row.get('rater_b_label','').strip()!=right[key]['relevance'].strip():
            raise ValueError(f'Adjudication rater label differs from original sheets: {key}')
        if row.get('text','')!=pool[key].get('text',''):
            raise ValueError(f'Adjudication passage text changed for {key}')
    labels=read_labels(qrels_path)
    if set(labels)!=set(pool): raise ValueError('Adjudicated qrels must cover all pooled passage pairs')
    for key,row in adjud.items():
        if row.get('final_relevance','').strip()!=str(labels[key]) or not row.get('adjudicator_id','').strip():
            raise ValueError(f'Human adjudication missing label/identity for {key}')
        if row.get('agreement','')=='no' and not row.get('decision_notes','').strip():
            raise ValueError(f'Disagreement needs documented adjudication for {key}')
    scored=score_runs(questions,runs,labels,manifest['parameters']['top_k'],strict=True)
    scored['by_category']=category_summary(scored)
    scored['status']=manifest['status']
    scored['human_review_provenance']='REVIEWER_ID_SELF_DECLARED_NOT_VERIFIED'
    scored['dataset_scope']='SEEN_POLICIES_NOT_UNSEEN_POLICY_HOLDOUT'
    scored['n_rated_pairs']=len(labels)
    scored['publication_warning']='Independent reviewer identity and independence require external records. Do not treat AI labels as human.'
    return scored
