"""V6 real-ontology metadata and human-review controls, no insurer PDFs in ZIP."""
from __future__ import annotations
import csv
import io
import json
from pathlib import Path
import pytest
from src.v6_review import load_annotations,review_rows,sheet_csv,read_reviewed_csv,comparison,check_review_sheet
from src.graph_builder import build_graph_from_annotations,save_graph
from src.graph_validation import validate_graph
from src.pipeline import build_pipeline

ROOT=Path(__file__).resolve().parents[1]
ANNOTATIONS=ROOT/'data/research_v6/annotations/review_required_five_insurers.json'
SCHEMA=ROOT/'ontology/iko_auto_v6.ttl'


def test_five_insurer_annotations_have_reviews_and_do_not_claim_approval():
    ann=load_annotations(ANNOTATIONS)
    assert len(ann['policies'])==5
    assert {p['id'].split('_')[0] for p in ann['policies']}=={'axa','admiral','aviva','directline','esure'}
    assert all(p['claim_conditions'] for p in ann['policies'])
    assert all('sha256' in cov['evidence'] and cov['evidence']['page']>0 for p in ann['policies'] for cov in p['coverages'])
    assert len(review_rows(ann))==49


def test_blinded_reviews_leave_every_decision_blank():
    sheet=sheet_csv(ANNOTATIONS,'Reviewer A')
    rows=read_reviewed_csv(sheet)
    assert len(rows)==49
    assert all(r['decision']=='' for r in rows)
    assert all(r['reviewer_id']=='Reviewer A' for r in rows)
    result=check_review_sheet(review_rows(ANNOTATIONS),rows)
    assert result['valid'] and result['unreviewed']==49 and result['approved']==0


def test_review_sheet_detects_modified_provenance_and_duplicates():
    base=review_rows(ANNOTATIONS)
    rows=read_reviewed_csv(sheet_csv(ANNOTATIONS))
    rows[0]['source_sha256']='0'*64
    assert not check_review_sheet(base,rows)['valid']
    rows=read_reviewed_csv(sheet_csv(ANNOTATIONS))
    rows[1]['assertion_id']=rows[0]['assertion_id']
    assert not check_review_sheet(base,rows)['valid']


def test_review_disagreement_requires_human_decision():
    base=review_rows(ANNOTATIONS)
    rowsa=read_reviewed_csv(sheet_csv(ANNOTATIONS))
    rowsb=read_reviewed_csv(sheet_csv(ANNOTATIONS))
    rowsa[0]['decision']='approve'
    rowsb[0]['decision']='reject'
    result=comparison(base,rowsa,rowsb)
    assert result['valid']
    assert result['reviewed_by_both']==1
    assert len(result['disagreements'])==1
    assert result['disagreements'][0]['adjudicated_decision']==''


def test_schema_extends_policy_level_claim_conditions():
    import rdflib
    g=rdflib.Graph().parse(str(SCHEMA),format='turtle')
    ns=rdflib.Namespace('https://example.org/iko-auto/v2#')
    assert (ns.hasClaimCondition, rdflib.RDF.type,rdflib.OWL.ObjectProperty) in g
    assert (ns.ClaimCondition,rdflib.RDF.type,rdflib.OWL.Class) in g


def test_claim_condition_provenance_with_generated_pdf(tmp_path):
    reportlab=pytest.importorskip('reportlab')
    from reportlab.pdfgen import canvas
    import hashlib
    pdf=tmp_path/'my.pdf'
    c=canvas.Canvas(str(pdf))
    c.drawString(35,760,'Cover: Accident damage is included under section A.')
    c.drawString(35,739,'Exception: Wear and tear is excluded.')
    c.drawString(35,718,'Claims: Notify insurer within 48 hours of an accident.')
    c.showPage();c.save()
    ev=lambda quote:dict(document='my.pdf',page=1,sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),quote=quote)
    obj={'policies':[{'id':'test','name':'AXA demo test','aliases':['axa'], 'version':'test',
         'claim_conditions':[dict(id='claim_notice',name='Notice within 48 hours',aliases=['notification'],
                                  evidence=ev('Notify insurer within 48 hours of an accident.'))],
         'coverages':[dict(id='damage',name='Accident damage',aliases=['accident damage'],
                            evidence=ev('Accident damage is included under section A.'),
                            exclusions=[dict(id='wear',name='Wear and tear',
                                  evidence=ev('Wear and tear is excluded.'))])]}]}
    path=tmp_path/'candidate.json'
    path.write_text(json.dumps(obj))
    g=build_graph_from_annotations(path,tmp_path,SCHEMA)
    ttl=save_graph(g,tmp_path/'instances.ttl')
    r=build_pipeline(tmp_path,graph_file=ttl)
    check=validate_graph(r.graph_index)
    assert check['passed']
    from rdflib import RDF,Namespace
    iko=Namespace('https://example.org/iko-auto/v2#')
    assert len(list(g.triples((None,iko.hasClaimCondition,None))))==1
    evidence=r.search('How soon must AXA notify the insurer?',ontology_mode='graph')
    assert any(h.graph_score for h in evidence)
