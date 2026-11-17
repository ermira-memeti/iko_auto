"""V7 development-only benchmark safeguards; NO fabricated human evaluations."""
from pathlib import Path
import csv
import json
import pytest

from src.pilot_v7 import (SEEDS,author_pilot,validate_pilot_questions,
                          questions_jsonl,verify_manifest,evaluate_reviewed_pilot,
                          bundle_zip_bytes,manifest_for,sha256)
from src.annotation_workflow import merge_independent_ratings,finalize_human_adjudication
from scripts.research_v7 import selected_pilot

BASE=Path(__file__).resolve().parents[1]
ANN=BASE/'data/research_v6/annotations/review_required_five_insurers.json'


def test_fifty_source_linked_development_prompts_and_no_gold():
    questions,hints=author_pilot(ANN)
    result=validate_pilot_questions(questions)
    assert result['passed']
    assert len(questions)==50 and len(hints)==50
    assert result['n_dev']==50 and result['n_test']==0
    assert all(q['gold_exhaustive'] is False and q['split']=='dev' for q in questions)
    assert all('relevance' not in q and 'correct_answer' not in q for q in questions)
    assert {q['insurer'] for q in questions}==set(SEEDS)
    assert all(h['source_quote'] and h['source_sha256'] and h['anchor_assertion_id'] for h in hints)
    assert all(h['pdf_page']>=1 for h in hints)


@pytest.mark.parametrize('size', [10,25,50])
def test_balanced_progressive_pilot_size(size):
    questions,hints=selected_pilot(size)
    assert len(questions)==len(hints)==size
    assert {q['insurer'] for q in questions}==set(SEEDS)
    assert all(sum(q['insurer']==insurer for q in questions)==size//5 for insurer in SEEDS)
    assert validate_pilot_questions(questions,real_only=False)['passed']


def test_no_heldout_relabeling_allowed():
    questions,_=selected_pilot(10)
    questions[0]['split']='test'
    assert not validate_pilot_questions(questions,real_only=False)['passed']


def test_ontology_feedback_document_marks_user_report_only():
    report=json.loads((BASE/'data/research_v7/ontology_review_USER_REPORTED.json').read_text())
    assert report['item_level_decisions_supplied'] is False
    assert report['cohen_kappa_available'] is False
    assert len(report['specialists_reported'])==2


def test_blank_reviewers_cannot_be_merged_or_adjudicated(tmp_path):
    from src.pilot_v7 import csv_data
    pool=[{'question_id':'Q1','chunk_id':'cid-1','question':'Question?', 'text':'Covered car damage.',
           'source_path':'axa.pdf','page':'1'}]
    src=tmp_path/'pool.csv';src.write_text(csv_data(pool),encoding='utf-8')
    reviewer=[dict(pool[0],annotator_id='A',relevance='',evidence_quote='',notes='')]
    a=tmp_path/'a.csv';a.write_text(csv_data(reviewer),encoding='utf-8')
    reviewer[0]['annotator_id']='B'
    b=tmp_path/'b.csv';b.write_text(csv_data(reviewer),encoding='utf-8')
    with pytest.raises(ValueError,match='explicit relevance'):
        merge_independent_ratings(src,a,b,tmp_path/'merge')
    from src.annotation_workflow import WORKLIST_COLUMNS
    work={key:'' for key in WORKLIST_COLUMNS}
    work.update(question_id='Q1',chunk_id='cid-1',text='Covered car damage.',agreement='yes')
    worklist=tmp_path/'worklist.csv';worklist.write_text(csv_data([work]),encoding='utf-8')
    with pytest.raises(ValueError,match='Human adjudicator'):
        finalize_human_adjudication(worklist,tmp_path/'qrels.csv',src)


def test_manifest_detects_modification_of_documents(tmp_path):
    corpus=tmp_path/'corpus';corpus.mkdir()
    (corpus/'axa.txt').write_text('Original text',encoding='utf-8')
    q,_=selected_pilot(10)
    m=manifest_for(corpus,None,q,['bm25'],170,45,5,5,0.6,'fake-model',questions_jsonl(q))
    assert verify_manifest(m,corpus,None)['passed']
    (corpus/'axa.txt').write_text('Changed text',encoding='utf-8')
    assert not verify_manifest(m,corpus,None)['passed']


def test_result_evaluation_rejects_nonexistent_provenance(tmp_path):
    with pytest.raises(FileNotFoundError):
        evaluate_reviewed_pilot(docs=tmp_path,graph=None,manifest_path=tmp_path/'missing.json',
            questions_path=tmp_path/'q.jsonl',runs_path=tmp_path/'run.json',qrels_path=tmp_path/'qrels.csv',
            pool_path=tmp_path/'pool.csv',reviewer_a_path=tmp_path/'a.csv',
            reviewer_b_path=tmp_path/'b.csv',worklist_path=tmp_path/'adjudication.csv')
