"""V5 metadata, exact-source grounding, deduplication and evaluation controls."""
import hashlib
import json
from pathlib import Path
import pytest
from src.models import Chunk
from src.policy_catalog import insurer_from_name, named_insurers, allowed_sources, scan_duplicates
from src.data_ingest import load_documents
from src.pipeline import build_pipeline
from src.section_aware import page_section, section_signal
from src.research_eval import method_runs
from src.graph_builder import build_graph_from_annotations, save_graph


def test_recognize_insurers_and_avoid_fuzzy_false_positive():
    assert insurer_from_name('AXA/AXA Car Insurance Sample Policy Wording.pdf') == 'AXA'
    assert insurer_from_name('DirectLine/car-insurance-policy-document.pdf') == 'Direct Line'
    assert insurer_from_name('esure_car_policy.pdf') == 'esure'
    assert insurer_from_name('my_axiom.txt') is None
    assert named_insurers('What exclusions apply under AXA car insurance?') == ['AXA']
    assert named_insurers('Compare AXA and Admiral') == ['AXA','Admiral']
    assert named_insurers('AXAordinary') == []


def test_exact_content_dedup_and_original_files_unmodified(tmp_path):
    (tmp_path/'AXA').mkdir()
    (tmp_path/'AXA'/'copy.txt').write_text('One policy line.\n', encoding='utf8')
    (tmp_path/'AXA'/'copy2.txt').write_text('One policy line.\n', encoding='utf8')
    (tmp_path/'Admiral').mkdir()
    (tmp_path/'Admiral'/'unrelated.txt').write_text('A distinct insurer.', encoding='utf8')
    before={p.name:p.read_bytes() for p in tmp_path.rglob('*.txt')}
    audit=scan_duplicates(tmp_path)
    assert audit['indexed_canonical_files']==2
    assert len(audit['skipped_aliases'])==1
    docs=load_documents(tmp_path)
    assert len(docs)==2
    assert len(load_documents(tmp_path,deduplicate=False))==3
    assert all(p.read_bytes()==before[p.name] for p in tmp_path.rglob('*.txt'))


def test_metadata_filter_preserves_global_bm25_ranking(tmp_path):
    for name in ('AXA','Admiral'):
        (tmp_path/name).mkdir()
        (tmp_path/name/'policy.txt').write_text(
            f'{name} cover excludes damage to wheels. Exclusions and limits are stated here. '+('red '*20 if name=='Admiral' else 'green '*20),encoding='utf8')
    r=build_pipeline(tmp_path,chunk_words=25,overlap_words=0)
    q='What AXA exclusions apply to damage?'
    global_hits=r.search(q,top_k=len(r.chunks))
    axa=allowed_sources(r.chunks,'AXA')
    scoped=r.search(q,top_k=len(r.chunks),allowed_sources=axa)
    assert [h.chunk.chunk_id for h in scoped] == [h.chunk.chunk_id for h in global_hits if h.chunk.source_path in axa]
    assert all(h.chunk.source_path.startswith('AXA/') for h in scoped)
    assert any(h.chunk.source_path.startswith('Admiral/') for h in global_hits)


def test_section_headings_exclude_contents_and_only_target_section():
    assert page_section('Contents page\nSection A – Damage\nSection B – Fire and theft') == ''
    section=page_section('AXA Car Insurance\nSection A – Damage\nWhat is not covered')
    assert section == 'Section A – Damage'
    c=Chunk('x','d','Exclusions','AXA/axa.pdf',10,0,4,section=section)
    from src.models import SearchHit
    h=SearchHit(c,4.0,'bm25')
    assert section_signal('What exclusions apply to accidental damage?',h)==1.0
    assert section_signal('What cover applies to windscreens?',h)==0


def test_v5_method_names_and_metadata_required(tmp_path):
    (tmp_path/'AXA').mkdir()
    (tmp_path/'AXA'/'one.txt').write_text('Accidental damage is covered. Mechanical damage is excluded.',encoding='utf8')
    ret=build_pipeline(tmp_path)
    qs=[{'question_id':'q1','question':'What exclusions apply to AXA damage?', 'split':'test','category':'exclusions','insurer':'AXA'}]
    runs=method_runs(ret,qs,['bm25','bm25_metadata','bm25_metadata_section'],k=1,pool_size=1)
    assert set(runs)=={'bm25','bm25_metadata','bm25_metadata_section'}
    with pytest.raises(ValueError,match='registered insurer'):
        method_runs(ret,[{**qs[0],'insurer':''}],['bm25_metadata'],1,pool_size=1)


def test_real_graph_rejects_unknown_named_insurer_and_demo_still_works():
    root=Path(__file__).resolve().parents[1]
    r=build_pipeline(root/'data/demo_auto_graph',graph_file=root/'ontology/instances/iko_auto_demo_v2.ttl')
    result=r.search('What exclusions does AXA have?',ontology_mode='graph')
    assert result == []
    assert r.last_graph_plan.strict_no_match
    assert r.search('Compare AXA and Admiral exclusions',ontology_mode='graph') == []
    assert r.last_graph_plan.strict_no_match
    assert r.search('What exclusions apply to Orange Insurance collision coverage?',ontology_mode='graph')


def test_pdf_sha_pinning_and_quote_page_enforced(tmp_path):
    pytest.importorskip('reportlab')
    from reportlab.pdfgen import canvas
    pdf=tmp_path/'real.pdf'
    cv=canvas.Canvas(str(pdf))
    cv.drawString(40,750,'Insurance Coverage: Accidental damage is covered by this policy.')
    cv.drawString(40,730,'Exclusion: Wear and tear is not covered by this policy.')
    cv.showPage()
    cv.save()
    expected=hashlib.sha256(pdf.read_bytes()).hexdigest()
    cover={'document':'real.pdf','page':1,'sha256':expected,
           'quote':'Accidental damage is covered by this policy.'}
    excluded={'document':'real.pdf','page':1,'sha256':expected,
              'quote':'Wear and tear is not covered by this policy.'}
    payload={'policies':[{'id':'real_test','name':'AXA Example (unit test)','aliases':['axa'],
                         'version':'version_unconfirmed','coverages':[{'id':'damage','name':'Damage',
                         'aliases':['damage'], 'evidence':cover,
                         'exclusions':[{'id':'wear','name':'Wear exclusion','evidence':excluded}]}]}]}
    path=tmp_path/'annotations.json'
    path.write_text(json.dumps(payload),encoding='utf8')
    g=build_graph_from_annotations(path,tmp_path)
    ttl=save_graph(g,tmp_path/'graph.ttl')
    from src.graph_retrieval import GraphIndex
    from src.graph_validation import validate_graph
    ix=GraphIndex(ttl,build_pipeline(tmp_path).chunks)
    assert validate_graph(ix)['passed']
    wrong={**payload}
    wrong=json.loads(json.dumps(payload));wrong['policies'][0]['coverages'][0]['evidence']['page']=2
    path.write_text(json.dumps(wrong))
    with pytest.raises(ValueError,match='Page 2 outside'):
        build_graph_from_annotations(path,tmp_path)
    wrong=json.loads(json.dumps(payload));wrong['policies'][0]['coverages'][0]['evidence']['sha256']='0'*64
    path.write_text(json.dumps(wrong))
    with pytest.raises(ValueError,match='hash missing or ambiguous'):
        build_graph_from_annotations(path,tmp_path)
