"""Ensure V8.3 is an additive eighth method, never an undocumented baseline change."""
from types import SimpleNamespace
import hashlib,io,json,zipfile
import pytest
from src.v8_3_intent import METHOD,route_intent
from src.research_eval import METHODS,method_runs
from src.v8_3_compare import compare_v8_2_v8_3,OLD_METHODS

@pytest.mark.parametrize('insurer,question,topic',[
    ('AXA','How much does AXA pay for windscreen repair?','windscreen'),
    ('Admiral','Does Admiral recalibrate ADAS after replacement?','windscreen_adas'),
    ('Aviva','Does Aviva allow glass work before approval?','glass_adas'),
    ('Direct Line','What is the Direct Line windscreen supplier limit?','windscreen'),
    ('Direct Line','How long does Direct Line provide a Guaranteed Hire Car?','hire_car'),
])
def test_targeted_intents(insurer,question,topic):
    decision=route_intent(question,insurer)
    assert decision['topic']==topic and decision['route']=='enhanced_v8_2'

@pytest.mark.parametrize('insurer,question',[
    ('AXA','AXA personalised number plate after a total loss'),
    ('AXA','AXA borrowed-car third party liability'),
    ('Admiral','Admiral uninsured motorist no-claims bonus'),
    ('Aviva','Aviva electric vehicle charging point cover'),
    ('Direct Line','Direct Line car-sharing with paying passengers'),
    ('Direct Line','Direct Line stolen car replacement conditions'),
    ('esure','esure accidental third-party property damage'),
    ('AXA','Does Admiral cover windscreen damage?'),
    ('AXA','Does AXA and Admiral cover windscreen damage?'),
])
def test_off_topic_and_cross_insurer_not_enhanced(insurer,question):
    assert route_intent(question,insurer)['route']=='original_v6'

class DualGraphFake:
    def __init__(self):
        self.original=object();self.extended=object()
        self.graph_index=self.original;self.last_graph_plan=None
        self.chunks=[SimpleNamespace(chunk_id='base',source_path='AXA/policy.pdf'),
                     SimpleNamespace(chunk_id='extended',source_path='AXA/policy.pdf')]
    def search(self,query,method='bm25',top_k=5,alpha=.6,candidate_pool=50,
               ontology_mode='none',allowed_sources=None,section_boost=False):
        if query.startswith('RAISE') and self.graph_index is self.extended:
            raise RuntimeError('synthetic failure')
        cid='base' if self.graph_index is self.original else 'extended'
        return [SimpleNamespace(chunk=c) for c in self.chunks if c.chunk_id==cid]

def test_eighth_method_gates_and_restores_graph():
    r=DualGraphFake()
    qs=[{'question_id':'target','insurer':'AXA','question':'AXA windscreen supplier','category':'glass','split':'dev'},
        {'question_id':'unrelated','insurer':'AXA','question':'AXA number plate write-off','category':'other','split':'dev'}]
    audit=[]
    methods=['bm25_metadata_graph','bm25_metadata_graph_v8_2',METHOD]
    output=method_runs(r,qs,methods,5,enhanced_graph_index=r.extended,intent_audit=audit)
    assert output[METHOD]['target']==output['bm25_metadata_graph_v8_2']['target']==['extended']
    assert output[METHOD]['unrelated']==output['bm25_metadata_graph']['unrelated']==['base']
    assert r.graph_index is r.original
    assert len(audit)==2
    assert METHODS[METHOD]==('bm25','graph')

def _zip(runs,extra=False,break_old=False):
    q='{"question_id":"q","question":"Does AXA cover windscreen repair?","insurer":"AXA"}\n'
    pool='question_id,chunk_id\nq,a\n'
    qsha=hashlib.sha256(q.encode()).hexdigest()
    psha=hashlib.sha256(pool.encode()).hexdigest()
    meta={'status':'DEVELOPMENT_OR_DRAFT_ONLY','questions_sha256':qsha,
          'submitted_questions_sha256':'same','source_sha256':{'axa.pdf':'same'},
          'graph_sha256':'base-sha','enhanced_graph_sha256':'enhanced-sha',
          'n_questions':1,'pool_sha256':psha,'parameters':{'top_k':5,'pool_size':5,'alpha':.6,'chunk_words':170,'overlap_words':45,'embedding_model':'test'},
          'runs_sha256':hashlib.sha256(json.dumps(runs,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    audit=[]
    if extra:
        decision=route_intent('Does AXA cover windscreen repair?','AXA')
        audit=[{**decision,'question_id':'q','method':METHOD,'n_returned':1,'result_chunk_ids':['a']}]
        meta.update(intent_gate_method=METHOD,intent_audit_sha256=hashlib.sha256(json.dumps(audit,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('04_FROZEN_MANIFEST.json',json.dumps(meta))
        z.writestr('INTERNAL_RETRIEVAL_RUNS.json',json.dumps(runs))
        z.writestr('02_QUESTIONS_FOR_EVALUATION.jsonl',q)
        z.writestr('INTERNAL_POOLED_PASSAGES.csv',pool)
        if extra:z.writestr('INTERNAL_INTENT_GATE_AUDIT.json',json.dumps(audit))
    return out.getvalue()

def test_comparator_verifies_all_seven_prior_outputs_and_gate():
    base={m:{'q':['a']} for m in OLD_METHODS}
    cur={**base,METHOD:{'q':['a']}}
    report=compare_v8_2_v8_3(_zip(base),_zip(cur,extra=True))
    assert report['safeguards_passed']
    assert report['enhanced_graph_routed_questions']==1
    tampered={**cur,'bm25_metadata':{'q':[]}}
    report=compare_v8_2_v8_3(_zip(base),_zip(tampered,extra=True))
    assert not report['safeguards_passed']
    assert len(report['baseline_deviations'])==1
