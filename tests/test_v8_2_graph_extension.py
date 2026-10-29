"""V8.2: new graph can be selected without mutating original six methods.

No fake labels, ratings, expert reviews or claims of held-out effectiveness.
"""
import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from src.research_eval import method_runs, METHODS
from src.v8_2_compare import compare_v8_1_v8_2
from src.v8_2_graph_build import FROZEN_V6_GRAPH_SHA256


class DualGraphFake:
    def __init__(self):
        self.original = object()
        self.extended = object()
        self.graph_index = self.original
        self.chunks = [SimpleNamespace(chunk_id='axa_passage',source_path='AXA/axa.pdf')]
        self.last_graph_plan = None

    def search(self, query, method='bm25', top_k=5, alpha=.6, candidate_pool=50,
               ontology_mode='none',allowed_sources=None,section_boost=False):
        assert self.graph_index in (self.original,self.extended)
        if ontology_mode == 'graph' and self.graph_index is self.original:
            chosen=[]
        else:
            chosen=self.chunks
        return [SimpleNamespace(chunk=c) for c in chosen
                if allowed_sources is None or c.source_path in allowed_sources][:top_k]


def test_separate_graph_selects_only_new_method_and_restores_original():
    r=DualGraphFake()
    q={'question_id':'q01','question':'Does AXA cover windscreen repairs?',
       'insurer':'AXA','category':'glass','split':'dev'}
    runs=method_runs(r,[q],['bm25_metadata_graph','bm25_metadata_graph_fallback',
                            'bm25_metadata_graph_v8_2'],k=5,pool_size=5,
                     enhanced_graph_index=r.extended)
    assert runs['bm25_metadata_graph']['q01']==[]
    assert runs['bm25_metadata_graph_fallback']['q01']==['axa_passage']
    assert runs['bm25_metadata_graph_v8_2']['q01']==['axa_passage']
    assert r.graph_index is r.original
    assert METHODS['bm25_metadata_graph_v8_2']==('bm25','graph')


def test_graph_variant_requires_distinct_index():
    r=DualGraphFake()
    q={'question_id':'q01','question':'Does AXA cover windscreen repairs?',
       'insurer':'AXA','category':'glass','split':'dev'}
    with pytest.raises(ValueError,match='V8.2 enhanced graph'):
        method_runs(r,[q],['bm25_metadata_graph_v8_2'],k=5,pool_size=5)
    assert r.graph_index is r.original


def _frozen_blob(runs, extended=False, changed=False):
    q='{"question_id":"q01"}\n'
    pool='question_id,chunk_id\nq01,axa_passage\n'
    common=('bm25','bm25_metadata','bm25_metadata_section','bm25_graph',
            'bm25_metadata_graph','bm25_metadata_graph_fallback')
    manifest={
        'status':'DEVELOPMENT_OR_DRAFT_ONLY','n_questions':1,
        'questions_sha256':hashlib.sha256(q.encode()).hexdigest(),
        'submitted_questions_sha256':'submitted-sha',
        'pool_sha256':hashlib.sha256(pool.encode()).hexdigest(),
        'source_sha256':{'axa.pdf':'fixed-policy-hash'},
        'graph_sha256':FROZEN_V6_GRAPH_SHA256,
        'parameters':{'top_k':5,'pool_size':5,'alpha':.6,'chunk_words':170,
                      'overlap_words':45,'embedding_model':'test-model'},
        'runs_sha256':hashlib.sha256(json.dumps(runs,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    }
    if extended:
        manifest.update(enhanced_graph_method='bm25_metadata_graph_v8_2',enhanced_graph_sha256='new-graph-hash')
    blob=io.BytesIO()
    with zipfile.ZipFile(blob,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('04_FROZEN_MANIFEST.json',json.dumps(manifest))
        z.writestr('INTERNAL_RETRIEVAL_RUNS.json',json.dumps(runs))
        z.writestr('02_QUESTIONS_FOR_EVALUATION.jsonl',q)
        z.writestr('INTERNAL_POOLED_PASSAGES.csv',pool)
    return blob.getvalue()


def test_v8_2_output_comparison_preserves_six_old_methods():
    six={m:{'q01':([] if m in ('bm25_graph','bm25_metadata_graph') else ['axa_passage'])}
         for m in ('bm25','bm25_metadata','bm25_metadata_section','bm25_graph',
                   'bm25_metadata_graph','bm25_metadata_graph_fallback')}
    new={**six,'bm25_metadata_graph_v8_2':{'q01':['axa_passage']}}
    report=compare_v8_1_v8_2(_frozen_blob(six),_frozen_blob(new,extended=True))
    assert report['safeguards_passed']
    assert report['original_graph_abstentions_restored']==['q01']
    assert report['new_method_nonempty_questions']==1
    changed={**new,'bm25_metadata':{'q01':[]}}
    report=compare_v8_1_v8_2(_frozen_blob(six),_frozen_blob(changed,extended=True))
    assert not report['safeguards_passed']
    assert len(report['baseline_deviations'])==1
