"""Descriptive AI-JUDGED development analysis from a FROZEN V7 pilot package.

THIS IS NOT THE HUMAN REVIEWER / ADJUDICATION WORKFLOW.
Never reuse output as independent expert labels or held-out results.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,sys,zipfile
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.pilot_v7 import csv_data
from src.research_eval import score_runs


def reader(buf):
    return list(csv.DictReader(io.StringIO(buf.decode('utf-8-sig'))))


def write_csv(path,rows,fields=None):
    fields=fields or (list(rows[0]) if rows else [])
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)


def analyze(pilot_zip,labels_csv,out_folder):
    out=Path(out_folder)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Destination is not empty. Choose a new output folder to preserve previous analyses.')
    out.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(pilot_zip) as z:
        if z.testzip():raise ValueError('Pilot archive damaged')
        names={'manifest_DEVELOPMENT.json','questions_DEV_ONLY.jsonl','runs_DEVELOPMENT.json','INTERNAL_pool_with_method_origins.csv','RESEARCHER_ONLY_source_hints.csv'}
        if not names.issubset(z.namelist()):raise ValueError('Not a complete frozen V7 pilot archive')
        manifest=json.loads(z.read('manifest_DEVELOPMENT.json'))
        if manifest.get('mode')!='DEVELOPMENT_PILOT_NOT_HELDOUT':raise ValueError('Never treat held-out/test results as this development diagnostic')
        qcontent=z.read('questions_DEV_ONLY.jsonl').decode('utf-8-sig')
        questions=[json.loads(s) for s in qcontent.splitlines() if s.strip()]
        runs=json.loads(z.read('runs_DEVELOPMENT.json'))
        pool=reader(z.read('INTERNAL_pool_with_method_origins.csv'))
        hints=reader(z.read('RESEARCHER_ONLY_source_hints.csv'))
        if hashlib.sha256(qcontent.encode()).hexdigest()!=manifest['questions_sha256']:raise ValueError('Questions do not match frozen manifest')
        if hashlib.sha256(csv_data(pool).encode()).hexdigest()!=manifest['pool_sha256']:raise ValueError('Pool changed after freeze')
        if hashlib.sha256(json.dumps(runs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()!=manifest['runs_sha256']:raise ValueError('Retrieval run changed after freeze')
        if len(pool)!=manifest['n_pool_pairs'] or len(questions)!=manifest['n_questions']:raise ValueError('Question/pool count mismatch')
        if any(q.get('split')!='dev' for q in questions):raise ValueError('Only DEV questions may be analyzed')
        if list(runs)!=manifest['methods']:raise ValueError('Changed comparison method list')
    with Path(labels_csv).open('r',encoding='utf-8-sig',newline='') as f:
        labels=list(csv.DictReader(f))
    keyed_pool={(r['question_id'],r['chunk_id']):r for r in pool}
    keyed_labels={(r['question_id'],r['chunk_id']):r for r in labels}
    if len(keyed_pool)!=len(pool) or len(keyed_labels)!=len(labels) or set(keyed_pool)!=set(keyed_labels):
        raise ValueError('Every original question/passage needs exactly one AI draft judgment')
    qrels={}
    for key,r in keyed_labels.items():
        original=keyed_pool[key]
        for col in ('question','text','source_path','page','start_word','end_word'):
            if r.get(col)!=original.get(col):raise ValueError(f'Source field changed: {key}/{col}')
        if r.get('annotator_id')!='AI_Assisted_Researcher_DRAFT':
            raise ValueError('This utility ONLY accepts explicitly marked provisional AI judgments')
        if r.get('researcher_confirmed','').strip():
            raise ValueError('User confirmation cannot be conflated with AI-only judgments')
        if r.get('relevance') not in {'0','1','2'}:raise ValueError(f'Invalid proposed rating: {key}')
        qrels[key]=int(r['relevance'])
        if qrels[key] > 0 and (not r.get('evidence_quote') or r['evidence_quote'] not in original['text']):
            raise ValueError(f'Positive passage missing a verbatim quoted span: {key}')
    results=score_runs(questions,runs,qrels,manifest['parameters']['top_k'],strict=True)
    results['status']='AI_ASSISTED_DEVELOPMENT_DIAGNOSTIC_ONLY'
    results['human_annotators']=0
    results['human_adjudications']=0
    results['independent_expert_validation']='NOT_PROVIDED_IN_THIS_DATA'
    results['corpus_hashes_from_frozen_manifest_ONLY']=manifest['source_sha256']
    results['new_code_or_graph_must_regenerate_pool']=True
    results['metric_note']='Precision counts relevance 1 or 2; nDCG uses graded 0/1/2 with only pooled judgments, not exhaustive gold; recall is unavailable.'
    sums=[{**r,'status':results['status']} for r in results['summary']]
    write_csv(out/'01_AI_ONLY_METHOD_SUMMARY_DEV.csv',sums)
    detail_rows=[{k:(json.dumps(v) if isinstance(v,(dict,list)) else v) for k,v in row.items()} for row in results['details']]
    write_csv(out/'02_AI_ONLY_PER_QUESTION_METHOD_DEV.csv',detail_rows)
    issue_rows=[]
    hmap={r['question_id']:r for r in hints}
    for q in questions:
        qid=q['question_id'];r=[rr for rr in labels if rr['question_id']==qid]
        counts=Counter(int(rr['relevance']) for rr in r)
        h=hmap[qid]
        anchor_found=sum(h['source_quote'] in x['text'] for x in r)
        empty_graph=[method for method in runs if 'graph' in method and not runs[method][qid]]
        issue_rows.append({'question_id':qid,'insurer':q['insurer'],'category':q['category'],
                           'question':q['question'],'n_pooled':len(r),
                           'ai_direct_2':counts[2],'ai_partial_1':counts[1],'ai_irrelevant_0':counts[0],
                           'expected_document':h['source_document'],'expected_pdf_page':h['pdf_page'],
                           'expected_anchor_quote':h['source_quote'],'anchor_exactly_in_pool_count':anchor_found,
                           'graph_methods_empty':'; '.join(empty_graph),
                           'diagnosis':('source_quote_not_in_pool' if anchor_found==0 else 'source_anchor_found')})
    write_csv(out/'03_SOURCE_ANCHOR_AND_RETRIEVAL_GAPS.csv',issue_rows)
    summary={'status':results['status'],'source_zip':str(Path(pilot_zip).name),
             'n_questions':len(questions),'n_pooled':len(pool),'labels':dict(sorted(Counter(qrels.values()).items())),
             'n_with_source_anchor_missing':sum(r['anchor_exactly_in_pool_count']==0 for r in issue_rows),
             'graph_method_empty_question_count':sum(bool(r['graph_methods_empty']) for r in issue_rows),
             'reported_metrics_are_ai_rated_pilot_only':True}
    (out/'04_AI_ONLY_SCORES_DEV.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'05_SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'START_HERE.md').write_text('''# IKO-Auto V7 | AI-assisted development diagnostics

These are **all 88 AI-proposed ratings**, checked against the *frozen* original pilot passages. All positive quotations are verbatim within their candidate passages.

**Not independent human annotation.** No two-rater agreement, human adjudication, or held-out performance claim is provided. The earlier reported positive ontology specialist consultation concerns ontology semantics, not these passage relevance judgments.

The metrics files are **descriptive debugging aids** for the old V7 retrieval run, NOT Paper A Results. Precision counts 1 and 2 as relevant, nDCG is pooled-judgment-based, and recall is unavailable. Empty graph runs are counted as misses.

## Contents

- `01_AI_ONLY_METHOD_SUMMARY_DEV.csv`: side-by-side DEV-only metrics.
- `02_AI_ONLY_PER_QUESTION_METHOD_DEV.csv`: individual run diagnostics and ranks.
- `03_SOURCE_ANCHOR_AND_RETRIEVAL_GAPS.csv`: source quote presence and graph empty-run warnings.
- `04_AI_ONLY_SCORES_DEV.json`: complete reproducible exploratory computation.
- `05_SUMMARY.json`: counts and provenance status.

## Next steps already resolved in the companion project patch

The V7.1 graph fix prevents other-insurer generic coverage aliases from wrongly emptying four graph queries. The patch must be rerun on the actual original PDF corpus and the updated retrieval pool must be annotated **separately**. It does not retroactively change these archived V7 scores.

**Caution:** The original pilot manifest pins PDF SHA-256 values. A differently downloaded or edited copy—even of the same insurer—must not be silently substituted. Report specialists' informal advice as consultation unless item-level decisions and identities are documented.
''',encoding='utf-8')
    return summary,results

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--pilot-zip',required=True)
    p.add_argument('--ai-labels',required=True)
    p.add_argument('--out-folder',required=True)
    a=p.parse_args();sm,_=analyze(a.pilot_zip,a.ai_labels,a.out_folder)
    print(json.dumps(sm,indent=2))
