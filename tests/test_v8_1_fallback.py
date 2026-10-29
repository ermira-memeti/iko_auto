"""V8.1 regression tests: separate fallback, immutable original modes and policy scoping."""
import json
from types import SimpleNamespace
import pytest
from src.research_eval import method_runs, METHODS, GRAPH_MODES
from src.v8_1_compare import compare_frozen_packages

class RetrieverFake:
    def __init__(self, graph_hits=0):
        self.graph_hits=graph_hits
        self.chunks=[SimpleNamespace(chunk_id='AXA_1',source_path='AXA/axa.pdf'),
                     SimpleNamespace(chunk_id='Admiral_1',source_path='Admiral/admiral.pdf')]
        self.graph_index=object()
        self.last_graph_plan=None
        self.calls=[]
    def search(self,q,method='bm25',top_k=5,alpha=.6,candidate_pool=50,
               ontology_mode='none',allowed_sources=None,section_boost=False):
        self.calls.append((ontology_mode,allowed_sources))
        if ontology_mode.startswith('graph'):
            self.last_graph_plan=SimpleNamespace(strict_no_match=not bool(self.graph_hits))
            chosen=[self.chunks[0]] if self.graph_hits else []
        else:
            chosen=list(self.chunks)
        if allowed_sources is not None:
            chosen=[c for c in chosen if c.source_path in allowed_sources]
        return [SimpleNamespace(chunk=c) for c in chosen[:top_k]]

def question(q='How much does AXA pay for windscreen replacement?',insurer='AXA'):
    return {'question_id':'V8Q_AXA_006','question':q,'insurer':insurer,
            'category':'glass','split':'dev'}

def test_method_is_additive_and_requires_graph():
    assert METHODS['bm25_metadata_graph']==('bm25','graph')
    assert METHODS['bm25_metadata_graph_fallback']==('bm25','graph')
    assert 'bm25_metadata_graph_fallback' in GRAPH_MODES
    ret=RetrieverFake();ret.graph_index=None
    with pytest.raises(ValueError,match='Graph methods require'):
        method_runs(ret,[question()],['bm25_metadata_graph_fallback'],1)

def test_fallback_only_when_graph_returns_nothing_and_scope_is_same_insurer():
    ret=RetrieverFake(graph_hits=0); events=[]
    methods=['bm25','bm25_metadata','bm25_metadata_section','bm25_graph',
             'bm25_metadata_graph','bm25_metadata_graph_fallback']
    run=method_runs(ret,[question()],methods,k=1,pool_size=1,fallback_audit=events)
    assert run['bm25_graph']['V8Q_AXA_006']==[]
    assert run['bm25_metadata_graph']['V8Q_AXA_006']==[]
    assert run['bm25_metadata_graph_fallback']['V8Q_AXA_006']==['AXA_1']
    assert run['bm25_metadata_graph_fallback']['V8Q_AXA_006']==run['bm25_metadata']['V8Q_AXA_006']
    assert events[0]['fallback_used'] and events[0]['graph_strict_no_match']
    assert events[0]['policy_scope']=='AXA'
    assert events[0]['result_chunk_ids']==['AXA_1']

def test_graph_passages_are_unchanged_when_graph_has_results():
    ret=RetrieverFake(graph_hits=1);events=[]
    run=method_runs(ret,[question()],['bm25_metadata_graph','bm25_metadata_graph_fallback'],
                    k=1,pool_size=1,fallback_audit=events)
    assert run['bm25_metadata_graph']==run['bm25_metadata_graph_fallback']
    assert events[0]['fallback_used'] is False
    assert events[0]['reason']=='GRAPH_RETURNED_PASSAGES'
    assert len(ret.calls)==2 # No fallback lexical call.

def test_conflicting_named_insurers_fail_closed():
    ret=RetrieverFake(graph_hits=0);events=[]
    run=method_runs(ret,[question('Compare AXA and Admiral glass repair')],
                    ['bm25_metadata_graph_fallback'],k=1,pool_size=1,fallback_audit=events)
    assert run['bm25_metadata_graph_fallback']['V8Q_AXA_006']==[]
    assert not events[0]['fallback_used']
    assert events[0]['reason']=='BLOCKED_CONFLICTING_INSURER'
    assert len(ret.calls)==1

def test_wrong_insurer_question_fails_closed():
    ret=RetrieverFake(graph_hits=0);events=[]
    run=method_runs(ret,[question('Does Admiral pay for glass repair?',insurer='AXA')],
                    ['bm25_metadata_graph_fallback'],k=1,pool_size=1,fallback_audit=events)
    assert run['bm25_metadata_graph_fallback']['V8Q_AXA_006']==[]
    assert events[0]['reason']=='BLOCKED_CONFLICTING_INSURER'

def test_compare_rejects_changed_inputs():
    with pytest.raises((zipfile.BadZipFile,KeyError)):
        compare_frozen_packages(b'not a zip',b'not a zip')
import zipfile

def test_compare_original_and_fallback_addition_is_output_only():
    import hashlib
    import io
    import zipfile
    import json
    def blob(runs,new_run=False,modified_source=False):
        q='{"question_id":"test-q"}\n'
        pool='question_id,chunk_id\ntest-q,AXA_1\n'
        manifest={'questions_sha256':hashlib.sha256(q.encode()).hexdigest(),
                  'pool_sha256':hashlib.sha256(pool.encode()).hexdigest(),
                  'source_sha256':{'axa.pdf':'x' if not modified_source else 'y'},
                  'graph_sha256':'z','status':'DEVELOPMENT_OR_DRAFT_ONLY',
                  'n_questions':1,'parameters':{'top_k':5,'pool_size':5,'alpha':.6,
                  'chunk_words':170,'overlap_words':45,'embedding_model':'some-model'},
                  'runs_sha256':hashlib.sha256(json.dumps(runs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
        records=[]
        if new_run:
            records=[{'question_id':'test-q','fallback_used':True,
                     'reason':'EMPTY_GRAPH_RESULT','n_returned':1}]
            manifest['fallback_audit_sha256']=hashlib.sha256(json.dumps(records,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('04_FROZEN_MANIFEST.json',json.dumps(manifest))
            z.writestr('INTERNAL_RETRIEVAL_RUNS.json',json.dumps(runs))
            z.writestr('02_QUESTIONS_FOR_EVALUATION.jsonl',q)
            z.writestr('INTERNAL_POOLED_PASSAGES.csv',pool)
            if new_run:
                z.writestr('INTERNAL_FALLBACK_AUDIT.json',json.dumps(records))
        return stream.getvalue()
    five={m:{'test-q':[] if 'graph' in m else ['AXA_1']} for m in
          ('bm25','bm25_metadata','bm25_metadata_section','bm25_graph','bm25_metadata_graph')}
    newer={**five,'bm25_metadata_graph_fallback':{'test-q':['AXA_1']}}
    original=blob(five)
    changed=blob(newer,new_run=True)
    report=compare_frozen_packages(original,changed)
    assert report['safeguards_passed']
    assert report['restored_graph_empty_questions']==['test-q']
    assert report['baseline_regressions']==[]
    with pytest.raises(ValueError,match='source_sha256'):
        compare_frozen_packages(original,blob(newer,new_run=True,modified_source=True))
    broken={**five,'bm25':{'test-q':['CHANGED']},'bm25_metadata_graph_fallback':{'test-q':['AXA_1']}}
    report=compare_frozen_packages(original,blob(broken,new_run=True))
    assert not report['baseline_methods_unchanged']
    assert not report['safeguards_passed']
