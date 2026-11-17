"""V8 independence-labeling, leakage, source integrity, and no-fabrication tests."""
from __future__ import annotations
import csv
import io
import json
import zipfile
from pathlib import Path
import pytest

from src.heldout_v8 import (COLUMNS,template_csv,load_question_csv,audit_questions,
                             to_eval_questions,prepare_bundle,bundle_zip,
                             verify_bundle_files,evaluate_with_human_judgments)
from src.pilot_v7 import SEEDS, author_pilot
from src.pipeline import build_pipeline


def item(insurer='AXA',author_type='independent_human',independent='yes',id='V8Q_01'):
    return dict(question_id=id,insurer=insurer,category='claims',
                question=f'In the {insurer} insurance booklet, is an incident involving a wild animal handled differently from a glass-only claim?',
                author_id='EXTERNAL_AUTHOR_ID',author_type=author_type,
                created_without_access_to_ontology=independent,source_document=f'{insurer}_policy.pdf',notes='')


def test_blank_template_has_five_insurers_and_fifty_no_generated_questions():
    rows=load_question_csv(template_csv())
    assert len(rows)==50
    assert {r['insurer'] for r in rows}==set(SEEDS)
    assert all(r['question']=='' and r['author_id']=='' for r in rows)
    assert len(set(r['question_id'] for r in rows))==50


def test_researcher_or_ai_author_cannot_claim_independent_test():
    for source in ('researcher','ai_assisted'):
        r=item(author_type=source)
        audit=audit_questions([r],dev_questions=[])
        assert audit['passed'] and audit['evaluation_tier']=='DEVELOPMENT_OR_DRAFT_ONLY'
        assert to_eval_questions([r],audit['evaluation_tier'])[0]['split']=='dev'


def test_independent_author_is_only_self_declared_seen_policy():
    r=item()
    audit=audit_questions([r],dev_questions=[])
    assert audit['passed'] and audit['evaluation_tier'].startswith('CANDIDATE_QUESTION_HOLDOUT')
    assert to_eval_questions([r],audit['evaluation_tier'])[0]['split']=='test'
    assert 'SEEN' in audit['evaluation_tier']


def test_reusing_v7_question_is_blocked():
    originals,_=author_pilot(Path(__file__).resolve().parents[1]/'data/research_v6/annotations/review_required_five_insurers.json')
    row=item()
    row['question']=originals[0]['question']
    result=audit_questions([row],dev_questions=originals)
    assert not result['passed'] and result['near_duplicate_development']


def test_repeated_questions_and_missing_provenance_are_rejected():
    row=item()
    twin=dict(row,question_id='V8Q_02')
    res=audit_questions([row,twin],dev_questions=[])
    assert not res['passed']
    row['author_id']=''
    assert not audit_questions([row],dev_questions=[])['passed']


def test_prepare_blinded_and_freeze_detects_alterations(tmp_path):
    data=tmp_path/'policies';data.mkdir()
    (data/'AXA_car_policy.txt').write_text('Wild animal accidents are investigated. We check glass claims and collision damage.',encoding='utf-8')
    retriever=build_pipeline(data,170,45)
    r=item(author_type='researcher',independent='no')
    # Unlike the source question author, our test fixture can work with a short toy text.
    pack=prepare_bundle(retriever,data,None,[r],['bm25'],5,5)
    assert pack['summary']['status']=='DEVELOPMENT_OR_DRAFT_ONLY'
    assert pack['summary']['questions']==1
    z=bundle_zip(pack)
    with zipfile.ZipFile(io.BytesIO(z)) as archive:
        assert archive.testzip() is None
        assert 'BLINDED_reviewer_A_BLANK.csv' in archive.namelist()
        sheet=list(csv.DictReader(io.StringIO(archive.read('BLINDED_reviewer_A_BLANK.csv').decode())))
        assert sheet and sheet[0]['relevance']=='' and sheet[0]['evidence_quote']==''
        assert 'retrieved_by' not in sheet[0]
        saved=tmp_path/'saved';saved.mkdir()
        for n in ('02_QUESTIONS_FOR_EVALUATION.jsonl','INTERNAL_RETRIEVAL_RUNS.json','INTERNAL_POOLED_PASSAGES.csv'):
            (saved/n).write_bytes(archive.read(n))
        frozen=json.loads(archive.read('04_FROZEN_MANIFEST.json'))
    assert verify_bundle_files(frozen,data,None,saved/'02_QUESTIONS_FOR_EVALUATION.jsonl',
                               saved/'INTERNAL_RETRIEVAL_RUNS.json',saved/'INTERNAL_POOLED_PASSAGES.csv')['verified']
    (data/'AXA_car_policy.txt').write_text('Changed meaning',encoding='utf-8')
    with pytest.raises(ValueError,match='changed'):
        verify_bundle_files(frozen,data,None,saved/'02_QUESTIONS_FOR_EVALUATION.jsonl',
                             saved/'INTERNAL_RETRIEVAL_RUNS.json',saved/'INTERNAL_POOLED_PASSAGES.csv')


def test_no_scores_without_two_complete_human_rater_sheets(tmp_path):
    data=tmp_path/'docs';data.mkdir()
    (data/'AXA_car_policy.txt').write_text('Wild animal collisions are covered. Glass damage is separately addressed.',encoding='utf-8')
    pack=prepare_bundle(build_pipeline(data,170,45),data,None,
                        [item(author_type='researcher',independent='no')],['bm25'])
    z=bundle_zip(pack)
    files=tmp_path/'f';files.mkdir()
    with zipfile.ZipFile(io.BytesIO(z)) as archive:
        for name in archive.namelist(): (files/name).write_bytes(archive.read(name))
    with pytest.raises((FileNotFoundError,ValueError)):
        evaluate_with_human_judgments(docs=data,graph=None,
            manifest_path=files/'04_FROZEN_MANIFEST.json',
            questions_path=files/'02_QUESTIONS_FOR_EVALUATION.jsonl',
            runs_path=files/'INTERNAL_RETRIEVAL_RUNS.json',
            pool_path=files/'INTERNAL_POOLED_PASSAGES.csv',
            reviewer_a=files/'BLINDED_reviewer_A_BLANK.csv',
            reviewer_b=files/'BLINDED_reviewer_B_BLANK.csv',
            worklist_path=files/'missing_human_adjudication.csv',qrels_path=files/'missing_qrels.csv')
