"""AI-only diagnostic must not allow false human/test claims."""
import csv,io,json,zipfile
from pathlib import Path
import pytest
from scripts.research_v7_ai_diagnostic import analyze
from src.pilot_v7 import csv_data


def make_fixture(tmp_path):
    # Construct only a deliberately small valid DEV pilot with fixed hashes.
    q={'question_id':'Q1','question':'What is covered?','category':'coverage','insurer':'AXA',
       'split':'dev','gold_exhaustive':False}
    pool=[{'question_id':'Q1','chunk_id':'c1','question':q['question'],'category':'coverage','split':'dev',
           'source_path':'axa.txt','page':'1','start_word':'0','end_word':'4',
           'text':'The insured car is covered.','retrieved_by':'bm25:1',
           'relevance':'','evidence_quote':'','notes':''}]
    runs={'bm25':{'Q1':['c1']}}
    qc=json.dumps(q,ensure_ascii=False)+'\n'
    import hashlib
    sha=lambda s:hashlib.sha256(s.encode('utf-8')).hexdigest()
    manifest={'mode':'DEVELOPMENT_PILOT_NOT_HELDOUT','questions_sha256':sha(qc),
              'pool_sha256':sha(csv_data(pool)), 'runs_sha256':sha(json.dumps(runs,ensure_ascii=False,sort_keys=True)),
              'n_questions':1,'n_pool_pairs':1,'methods':['bm25'],'parameters':{'top_k':1},'source_sha256':{}}
    path=tmp_path/'pilot.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('questions_DEV_ONLY.jsonl',qc)
        z.writestr('INTERNAL_pool_with_method_origins.csv',csv_data(pool))
        z.writestr('runs_DEVELOPMENT.json',json.dumps(runs))
        z.writestr('manifest_DEVELOPMENT.json',json.dumps(manifest))
        z.writestr('RESEARCHER_ONLY_source_hints.csv',csv_data([{
            'question_id':'Q1','source_document':'axa.txt','pdf_page':'1','source_quote':'The insured car is covered.'}]))
    return path,pool


def test_ai_dev_scores_only_valid_provisional_labels(tmp_path):
    path,pool=make_fixture(tmp_path)
    labels=[dict(pool[0],annotator_id='AI_Assisted_Researcher_DRAFT',relevance='2',
                 evidence_quote='car is covered',researcher_confirmed='')]
    csvfile=tmp_path/'ai.csv';csvfile.write_text(csv_data(labels))
    info,detail=analyze(path,csvfile,tmp_path/'out')
    assert detail['status']=='AI_ASSISTED_DEVELOPMENT_DIAGNOSTIC_ONLY'
    assert detail['human_annotators']==0 and len(detail['summary'])==1


def test_ai_dev_rejects_fabricated_human_id(tmp_path):
    path,pool=make_fixture(tmp_path)
    labels=[dict(pool[0],annotator_id='Reviewer_A',relevance='2',evidence_quote='car is covered',researcher_confirmed='')]
    csvfile=tmp_path/'ai.csv';csvfile.write_text(csv_data(labels))
    with pytest.raises(ValueError,match='ONLY accepts'):
        analyze(path,csvfile,tmp_path/'out')
