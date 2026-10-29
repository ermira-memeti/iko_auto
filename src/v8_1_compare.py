"""Audit-only comparison of frozen V8 and V8.1 retrieval runs.

This is NOT a passage-relevance evaluation. It never treats unjudged passages
as negatives, does not compute accuracy, and never modifies frozen ZIPs.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

NEW_METHOD = 'bm25_metadata_graph_fallback'
ORIGINAL_METHODS = ('bm25','bm25_metadata','bm25_metadata_section',
                    'bm25_graph','bm25_metadata_graph')


def _load(data: bytes | str):
    if isinstance(data, str):
        with open(data, 'rb') as file:
            data = file.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    if z.testzip() is not None:
        raise ValueError('Corrupt frozen benchmark ZIP')
    manifest = json.loads(z.read('04_FROZEN_MANIFEST.json'))
    runs = json.loads(z.read('INTERNAL_RETRIEVAL_RUNS.json'))
    actual = hashlib.sha256(json.dumps(runs,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    if manifest.get('runs_sha256') != actual:
        raise ValueError('Frozen retrieval-run checksum mismatch')
    for key,file_name in [('questions_sha256','02_QUESTIONS_FOR_EVALUATION.jsonl'),
                          ('pool_sha256','INTERNAL_POOLED_PASSAGES.csv')]:
        actual = hashlib.sha256(z.read(file_name)).hexdigest()
        if manifest.get(key) != actual:
            raise ValueError(f'Frozen {key} mismatch')
    return z,manifest,runs


def compare_frozen_packages(original: bytes | str, newer: bytes | str) -> dict:
    """Both runs must use identical question text, PDFs, graph and settings.

    New method may increase non-empty output, but NOT necessarily relevance.
    Separate version hashes are expected (source code is an intervention).
    """
    old_zip, a, old = _load(original)
    new_zip, b, new = _load(newer)
    if not all(m in old and m in new for m in ORIGINAL_METHODS):
        raise ValueError('Both runs must include the original five retrieval methods')
    if NEW_METHOD not in new:
        raise ValueError('V8.1 run is missing the separately named fallback method')
    for field in ('questions_sha256','source_sha256','graph_sha256','status'):
        if a.get(field) != b.get(field):
            raise ValueError(f'Cannot compare: {field} changed between freezes')
    for field in ('top_k','pool_size','alpha','chunk_words','overlap_words','embedding_model'):
        if a['parameters'].get(field) != b['parameters'].get(field):
            raise ValueError(f'Cannot compare: experiment parameter {field} changed')
    if a['n_questions'] != b['n_questions']:
        raise ValueError('Question count changed')
    qids = set(old['bm25'])
    if set(new[NEW_METHOD]) != qids or any(set(old[m]) != qids or set(new[m]) != qids for m in ORIGINAL_METHODS):
        raise ValueError('Question IDs differ between method runs')
    deviations = []
    for method in ORIGINAL_METHODS:
        for qid in sorted(qids):
            if old[method][qid] != new[method][qid]:
                deviations.append({'method':method,'question_id':qid,
                                   'original_count':len(old[method][qid]),
                                   'new_count':len(new[method][qid])})
    source = 'bm25_metadata_graph'
    graph_empty = sorted(qid for qid in qids if not new[source][qid])
    restored = [qid for qid in graph_empty if new[NEW_METHOD][qid]]
    unexpected = [qid for qid in qids if new[source][qid] and
                  new[source][qid] != new[NEW_METHOD][qid]]
    mismatch_scope = [qid for qid in restored if any(
        cid not in new['bm25_metadata'][qid]
        for cid in new[NEW_METHOD][qid])]
    if 'INTERNAL_FALLBACK_AUDIT.json' not in new_zip.namelist():
        raise ValueError('V8.1 package has no internal fallback provenance audit')
    events = json.loads(new_zip.read('INTERNAL_FALLBACK_AUDIT.json'))
    event_hash = hashlib.sha256(json.dumps(events,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    if event_hash != b.get('fallback_audit_sha256'):
        raise ValueError('V8.1 fallback audit checksum mismatch')
    logged = {e['question_id'] for e in events if e['fallback_used']}
    if logged != {e['question_id'] for e in events if e['reason']=='EMPTY_GRAPH_RESULT'}:
        raise ValueError('Fallback event provenance is inconsistent')
    return {'comparison':'OUTPUT_COVERAGE_NOT_RELEVANCE',
            'status':b['status'],'n_questions':len(qids),
            'old_graph_empty_questions':sum(not old[source][qid] for qid in qids),
            'new_graph_empty_questions':len(graph_empty),
            'new_fallback_nonempty_questions':sum(bool(new[NEW_METHOD][qid]) for qid in qids),
            'restored_graph_empty_questions':restored,
            'fallback_events_logged':sorted(logged),
            'baseline_regressions':deviations,
            'baseline_methods_unchanged':not deviations,
            'unexpected_graph_result_changes':unexpected,
            'fallback_not_contained_in_metadata_baseline':mismatch_scope,
            'safeguards_passed':not (deviations or unexpected or mismatch_scope or logged != set(graph_empty)),
            'limitation':'No human judgments or accuracy measures; queries are AI-assisted and original five PDFs are seen policies.'}
