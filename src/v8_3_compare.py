"""Compare V8.3 frozen outputs with V8.2 without using relevance judgments.

The seven earlier runs must be identical, questions, source documents,
original graph and enhanced graph checksums must match. The eighth method
must equal one of the corresponding original graph rankings BY QUESTION,
according to the independently logged question-intent gate decision.
"""
from __future__ import annotations
import hashlib
import json
from .v8_1_compare import _load
from .v8_3_intent import METHOD, route_intent

OLD_METHODS = ('bm25','bm25_metadata','bm25_metadata_section','bm25_graph',
               'bm25_metadata_graph','bm25_metadata_graph_fallback','bm25_metadata_graph_v8_2')


def compare_v8_2_v8_3(previous, current) -> dict:
    zold,old_meta,old_runs=_load(previous)
    znew,new_meta,new_runs=_load(current)
    if set(OLD_METHODS)-set(old_runs) or set(OLD_METHODS)-set(new_runs):
        raise ValueError('Both frozen packages need all seven V8.2 methods')
    if METHOD not in new_runs or new_meta.get('intent_gate_method')!=METHOD:
        raise ValueError('New freeze lacks distinct V8.3 intent-gated method')
    for field in ('questions_sha256','submitted_questions_sha256','source_sha256',
                  'graph_sha256','status','n_questions','enhanced_graph_sha256'):
        if old_meta.get(field)!=new_meta.get(field):
            raise ValueError(f'Frozen inputs differ: {field}')
    for p in ('top_k','pool_size','alpha','chunk_words','overlap_words','embedding_model'):
        if old_meta['parameters'].get(p)!=new_meta['parameters'].get(p):
            raise ValueError(f'Parameter differs: {p}')
    qids=set(old_runs['bm25'])
    if set(new_runs[METHOD])!=qids or any(set(old_runs[m])!=qids or set(new_runs[m])!=qids for m in OLD_METHODS):
        raise ValueError('Question ID sets mismatch')
    deviations=[{'question_id':qid,'method':m,'original':old_runs[m][qid],
                 'v8_3':new_runs[m][qid]} for m in OLD_METHODS for qid in sorted(qids)
                if old_runs[m][qid]!=new_runs[m][qid]]
    if 'INTERNAL_INTENT_GATE_AUDIT.json' not in znew.namelist():
        raise ValueError('Missing V8.3 intent routing audit')
    audit=json.loads(znew.read('INTERNAL_INTENT_GATE_AUDIT.json'))
    digest=hashlib.sha256(json.dumps(audit,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    if digest!=new_meta.get('intent_audit_sha256'):
        raise ValueError('Intent-gate audit checksum mismatch')
    if len(audit)!=len(qids) or {r['question_id'] for r in audit}!=qids:
        raise ValueError('Intent audit missing or duplicate question IDs')
    # Do not trust self-reported routes: recalculate from the submitted questions.
    questions={r['question_id']:r for r in [json.loads(s) for s in
               znew.read('02_QUESTIONS_FOR_EVALUATION.jsonl').decode('utf-8').splitlines() if s.strip()]}
    inconsistent=[]
    for entry in audit:
        qid=entry['question_id']
        expected=route_intent(questions[qid]['question'],questions[qid]['insurer'])
        if any(expected[k]!=entry.get(k) for k in ('insurer','route','reason','topic','gate_version')):
            inconsistent.append({'question_id':qid,'reason':'gate decisions do not match current rules'})
        source=('bm25_metadata_graph_v8_2' if expected['route']=='enhanced_v8_2'
                else 'bm25_metadata_graph')
        if new_runs[METHOD][qid]!=new_runs[source][qid]:
            inconsistent.append({'question_id':qid,'reason':f'gate output differs from {source}'})
        if entry['result_chunk_ids']!=new_runs[METHOD][qid]:
            inconsistent.append({'question_id':qid,'reason':'gate logged chunk IDs differ from frozen run'})
    changed=[qid for qid in sorted(qids) if new_runs[METHOD][qid]!=new_runs['bm25_metadata_graph_v8_2'][qid]]
    routed=sorted(r['question_id'] for r in audit if r['route']=='enhanced_v8_2')
    return {'comparison':'V8_2_V8_3_SEVEN_BASELINES_FROZEN_AND_RULES_VERIFIED',
            'status':new_meta['status'],'n_questions':len(qids),
            'original_seven_methods_unchanged':not deviations,
            'baseline_deviations':deviations,
            'gate_audit_consistent':not inconsistent,
            'gate_inconsistencies':inconsistent,
            'enhanced_graph_routed_questions':len(routed),
            'enhanced_graph_question_ids':routed,
            'new_method_nonempty_questions':sum(bool(new_runs[METHOD][qid]) for qid in qids),
            'new_method_empty_question_ids':[qid for qid in sorted(qids) if not new_runs[METHOD][qid]],
            'changed_new_method_questions':len(changed),
            'changed_question_ids':changed,
            'safeguards_passed':not (deviations or inconsistent),
            'evaluation_limitations':'Output comparison only; AI-assisted questions and ontology extensions were tuned on the same development set. No independent judgments or final accuracy are included.'}
