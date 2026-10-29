"""Audit a V8.2 ontology-only intervention against frozen V8.1.

NO human judgments or performance metrics inferred. Only output differences,
source/version integrity and unchanged six prior method rankings are compared.
"""
from __future__ import annotations
from .v8_1_compare import _load

NEW_METHOD='bm25_metadata_graph_v8_2'
BASELINES=('bm25','bm25_metadata','bm25_metadata_section',
           'bm25_graph','bm25_metadata_graph','bm25_metadata_graph_fallback')


def compare_v8_1_v8_2(original,new):
    za,a,old=_load(original)
    zb,b,nxt=_load(new)
    if any(m not in old or m not in nxt for m in BASELINES):
        raise ValueError('Both freezes need all SIX original V8.1 methods')
    if NEW_METHOD not in nxt or b.get('enhanced_graph_method')!=NEW_METHOD or not b.get('enhanced_graph_sha256'):
        raise ValueError('V8.2 freeze missing separate evidence-linked ontology method or SHA-256')
    for field in ('questions_sha256','submitted_questions_sha256','source_sha256',
                  'graph_sha256','status','n_questions'):
        if a.get(field)!=b.get(field):raise ValueError(f'Cannot compare: {field} differs')
    if a['graph_sha256']==b['enhanced_graph_sha256']:
        raise ValueError('V8.2 graph did not differ from V6 baseline')
    for field in ('top_k','pool_size','alpha','chunk_words','overlap_words','embedding_model'):
        if a['parameters'].get(field)!=b['parameters'].get(field):
            raise ValueError(f'Experiment parameter differs: {field}')
    qids=set(old['bm25'])
    if set(nxt[NEW_METHOD])!=qids:
        raise ValueError('Question sets differ')
    deviations=[{'method':m,'question_id':qid,'old':old[m][qid],'new':nxt[m][qid]}
                for m in BASELINES for qid in sorted(qids) if old[m][qid]!=nxt[m][qid]]
    changes=[{'question_id':qid,'old_graph_count':len(nxt['bm25_metadata_graph'][qid]),
              'new_graph_count':len(nxt[NEW_METHOD][qid]),
              'new_ranked_ids':nxt[NEW_METHOD][qid],
              'new_evidence_not_in_original_graph':[
                  cid for cid in nxt[NEW_METHOD][qid] if cid not in nxt['bm25_metadata_graph'][qid]]}
             for qid in sorted(qids) if nxt['bm25_metadata_graph'][qid]!=nxt[NEW_METHOD][qid]]
    abstentions=sorted(qid for qid in qids if not nxt['bm25_metadata_graph'][qid])
    restored=[qid for qid in abstentions if nxt[NEW_METHOD][qid]]
    return {
        'comparison':'ONTOLOGY_GRAPH_PATH_ABLATION_OUTPUTS_NOT_RELEVANCE',
        'status':b['status'],'n_questions':len(qids),
        'source_and_input_checksums_equal':True,
        'old_graph_sha256':a['graph_sha256'],
        'new_graph_sha256':b['enhanced_graph_sha256'],
        'baseline_methods_unchanged':not deviations,
        'baseline_deviations':deviations,
        'new_method_nonempty_questions':sum(bool(nxt[NEW_METHOD][qid]) for qid in qids),
        'new_method_empty_questions':[qid for qid in sorted(qids) if not nxt[NEW_METHOD][qid]],
        'original_graph_abstentions':abstentions,
        'original_graph_abstentions_restored':restored,
        'changed_ontology_method_rankings':changes,
        'safeguards_passed':not deviations,
        'critical_limitation':'Enhanced ontology was designed from observed failures on the SAME AI-assisted development questions; any gains on those questions are IN-SAMPLE, not generalizable accuracy.'}
