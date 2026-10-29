"""V7 development-pilot question authoring and source-pinned evaluation preparation.

Questions and expected source hints are AUTHOR-DRAFTED DEVELOPMENT MATERIAL,
NOT held-out test questions, relevance judgments, or independent evaluations.
All claims are anchored to the previously PDF-verified V6 candidate annotations.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .research_eval import (METHODS, GRAPH_MODES, candidate_pool_rows, method_runs,
                            questions_from, write_csv, read_labels, score_runs,
                            category_summary, factorial_ablation)
from .v6_review import load_annotations, review_rows

# Ten distinct development prompts for each of the five insurer wordings.
# Each prompt has at least one quoted V6 source assertion, used only as an
# internal authoring trace. No passage or relevance labels are populated.
# fields: question, category, relation, target-substring (within one insurer).
SEEDS = {
 'AXA': [
  ('What damage is described as covered under AXA Section A?', 'coverage', 'hasCoverage','Accidental vehicle damage'),
  ('Does AXA Section A exclude ordinary wear and tear?', 'exclusion', 'hasExclusion','Wear and tear'),
  ('What does the AXA policy say about mechanical or electrical breakdown under Section A?', 'exclusion','hasExclusion','Mechanical and electrical'),
  ('Is damage from using the wrong fuel excluded from AXA accidental damage cover?', 'exclusion','hasExclusion','Incorrect fuel'),
  ('Where is the amount of the AXA accidental-damage excess specified?', 'deductible','hasDeductible','Excess specified'),
  ('Does the AXA sample wording provide a fixed excess amount for every customer?', 'deductible','hasDeductible','Excess specified'),
  ('What does AXA require concerning notification of a policy incident?', 'claim_condition','hasClaimCondition','General policy incident'),
  ('Is deterioration treated as an accidental-damage loss under AXA Section A?', 'exclusion','hasExclusion','Wear and tear'),
  ('What limitation applies to failures of electrical components under AXA Section A?', 'exclusion','hasExclusion','Mechanical and electrical'),
  ('For AXA Section A, what policy document determines the claim excess?', 'deductible','hasDeductible','Excess specified'),
 ],
 'Admiral': [
  ('What kinds of damage fall under Admiral Section 2 vehicle cover?', 'coverage','hasCoverage','Damage to your vehicle'),
  ('Does Admiral cover damage resulting from ordinary wear and tear?', 'exclusion','hasExclusion','Wear and tear'),
  ('What does Admiral exclude for mechanical or electrical breakdown?', 'exclusion','hasExclusion','Mechanical, electrical'),
  ('Are certain cyber-related failures excluded from Admiral Section 2?', 'exclusion','hasExclusion','Mechanical, electrical'),
  ('Where would the Admiral policyholder find their excess amount?', 'deductible','hasDeductible','Excess specified'),
  ('Does this Admiral guide specify one fixed deductible for all policies?', 'deductible','hasDeductible','Excess specified'),
  ('Within what time should an Admiral policyholder report an accident?', 'claim_condition','hasClaimCondition','Notice to insurer'),
  ('Must an Admiral driver notify the insurer even when they do not intend to claim?', 'claim_condition','hasClaimCondition','Notice to insurer'),
  ('Is damage to a vehicle from an accident described under Admiral Section 2?', 'coverage','hasCoverage','Damage to your vehicle'),
  ('How does Admiral treat deterioration compared with accident damage?', 'exclusion','hasExclusion','Wear and tear'),
 ],
 'Aviva': [
  ('Under Aviva Signature motor insurance, what happens if the insured vehicle is damaged?', 'coverage','hasCoverage','Section 1:'),
  ('Which gradual-damage or breakdown losses does Aviva Section 1 exclude?', 'exclusion','hasExclusion','Gradual damage'),
  ('Does Aviva exclude loss occurring during a track day?', 'exclusion','hasExclusion','Track-day'),
  ('Under what qualification does Aviva treat use of a car without permission?', 'exclusion','hasExclusion','Use without permission'),
  ('Where are the excess amounts for Aviva vehicle damage stated?', 'deductible','hasDeductible','Excesses defined'),
  ('What limit is specified for Aviva vehicle damage settlement?', 'limit','hasLimit','market value'),
  ('Is the Aviva courtesy vehicle benefit conditional on the policy schedule?', 'coverage','hasCoverage','courtesy vehicle'),
  ('Will Aviva supply a courtesy vehicle when using a non-approved repairer?', 'exclusion','hasExclusion','non-approved repairer'),
  ('What is the maximum stated duration of Aviva courtesy-car cover if the car is stolen and cannot be recovered?', 'limit','hasLimit','28 days'),
  ('When should an Aviva insured driver report an incident?', 'claim_condition','hasClaimCondition','Report the incident'),
 ],
 'Direct Line': [
  ('What repair or replacement options exist for Direct Line accidental vehicle damage?', 'coverage','hasCoverage','accidental damage'),
  ('Does Direct Line Section 4 pay to remove or replace incorrect fuel?', 'exclusion','hasExclusion','incorrect fuel'),
  ('Is ordinary wear and tear covered as accidental loss by Direct Line?', 'exclusion','hasExclusion','wear and tear'),
  ('How does Direct Line address mechanical or computer failure?', 'exclusion','hasExclusion','mechanical, electrical'),
  ('Where are the claim excess amounts stated for a Direct Line customer?', 'deductible','hasDeductible','Excess specified'),
  ('What kinds of events are included in Direct Line fire and theft cover?', 'coverage','hasCoverage','Fire and theft'),
  ('Is theft covered if a Direct Line insured car is left unattended and unlocked?', 'exclusion','hasExclusion','unattended unlocked'),
  ('What restriction applies when a car is taken by a fraudulent buyer under Direct Line?', 'exclusion','hasExclusion','fraudulent buyer'),
  ('What happens if a required tracking device is not operating for Direct Line theft claims?', 'exclusion','hasExclusion','tracking device'),
  ('Should a Direct Line driver report an accident even if no claim will be made?', 'claim_condition','hasClaimCondition','Report accident'),
 ],
 'esure': [
  ('What losses are described under esure Section 04 car-damage cover?', 'coverage','hasCoverage','loss or damage to car'),
  ('Does esure insure an accident deliberately staged by an insured driver?', 'exclusion','hasExclusion','Deliberately staged'),
  ('What is esure policy treatment of mechanical or computer failure?', 'exclusion','hasExclusion','Mechanical, electrical'),
  ('Is everyday wear and tear excluded under esure vehicle damage?', 'exclusion','hasExclusion','Everyday wear'),
  ('What additional excess applies with an esure non-recommended repairer?', 'deductible','hasDeductible','additional GBP 200'),
  ('What kinds of vehicle-glass damage are covered by esure Section 05?', 'coverage','hasCoverage','windscreen and other glass'),
  ('Does esure glass cover pay to replace a convertible hood or roof structure?', 'exclusion','hasExclusion','hood/roof'),
  ('Are sunroof or glass roof panels included in esure glass-damage cover?', 'exclusion','hasExclusion','Sunroofs'),
  ('What is esure maximum glass repair contribution when a customer chooses their own repairer?', 'limit','hasLimit','GBP 100'),
  ('How quickly should a driver tell esure about an incident?', 'claim_condition','hasClaimCondition','Report incidents'),
 ],
}

DEFAULT_METHODS = ['bm25','bm25_metadata','bm25_metadata_section','bm25_graph','bm25_metadata_graph']


def sha256(path: str | Path) -> str:
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def author_pilot(annotations: str | Path):
    """Return 50 DEV-only questions and separate internal, source-linked hints."""
    rows = review_rows(annotations)
    by_insurer={}
    for pol in load_annotations(annotations)['policies']:
        insurer = ('Direct Line' if 'Direct Line' in pol['name'] else
                   'AXA' if pol['name'].startswith('AXA') else
                   'Admiral' if pol['name'].startswith('Admiral') else
                   'Aviva' if pol['name'].startswith('Aviva') else 'esure')
        by_insurer[insurer] = [r for r in rows if r['policy_id']==pol['id']]
    questions=[]; hints=[]
    for insurer, drafts in SEEDS.items():
        assert len(drafts)==10, insurer
        for number,(question,category,relation,substring) in enumerate(drafts, 1):
            matching = [r for r in by_insurer[insurer] if r['relation']==relation and substring.casefold() in r['target'].casefold()]
            if len(matching)!=1:
                raise ValueError(f'Ambiguous source anchor: {insurer} {number} {relation} {substring}: {len(matching)} candidates')
            source=matching[0]
            qid=f'V7P_{insurer.replace(" ","").upper()}_{number:02d}'
            questions.append({'question_id':qid,'question':question,'insurer':insurer,
                              'category':category,'split':'dev','gold_exhaustive':False,
                              'policy_family':source['policy_id'], 'authoring_status':'draft_requires_question_review'})
            hints.append({'question_id':qid,'insurer':insurer,'category':category,
                          'source_document':source['source_document'], 'pdf_page':source['pdf_page'],
                          'anchor_assertion_id':source['assertion_id'],
                          'proposed_relation':source['relation'], 'proposed_target':source['target'],
                          'source_quote':source['evidence_quote'],
                          'source_sha256':source['source_sha256'],
                          'note':'Researcher authoring aid only. NOT a relevance label or a sufficient-answer guarantee.'})
    assert len(questions)==50 and len({q['question_id'] for q in questions})==50
    return questions,hints


def validate_pilot_questions(questions: list[dict], real_only=True) -> dict:
    errors=[]
    expected={q['question_id']:q for q in questions}
    if len(expected)!=len(questions): errors.append('Duplicate question identifiers')
    for q in questions:
        if q.get('split') != 'dev': errors.append(f"{q.get('question_id')}: pilot must be dev, never held-out test")
        if q.get('gold_exhaustive') is not False: errors.append(f"{q.get('question_id')}: no exhaustive gold labels exist")
        if q.get('insurer') not in SEEDS: errors.append(f"{q.get('question_id')}: unknown insurer")
        if not q.get('question','').strip(): errors.append(f"{q.get('question_id')}: empty question")
    counts=dict(Counter(q.get('insurer') for q in questions))
    if real_only and any(counts.get(i)!=10 for i in SEEDS): errors.append('Pilot must contain 10 questions per insurer')
    return {'passed':not errors,'errors':errors,'n_questions':len(questions),'insurer_counts':counts,
            'n_dev':sum(q.get('split')=='dev' for q in questions),
            'n_test':sum(q.get('split')=='test' for q in questions),
            'warning':'All questions are development pilots. They are NOT independent held-out test questions.'}


def validate_source_hints(hints: list[dict], docs_dir: str | Path) -> dict:
    """Match filenames/hashes and exact page text, without trusting filename alone."""
    from pypdf import PdfReader
    root=Path(docs_dir).resolve()
    pdf_files=list(root.rglob('*.pdf'))
    hashes={}
    for p in pdf_files:
        hashes.setdefault(sha256(p), []).append(p)
    errors=[]
    cache={}
    for hint in hints:
        matches=hashes.get(hint['source_sha256'],[])
        if len(matches)!=1:
            errors.append(f"{hint['question_id']}: expected exactly one source PDF by SHA-256; found {len(matches)}")
            continue
        path=matches[0]
        key=(str(path),int(hint['pdf_page']))
        try:
            if key not in cache:
                page=PdfReader(str(path)).pages[key[1]-1]
                cache[key]=' '.join((page.extract_text() or '').split()).casefold()
            normalized=' '.join(hint['source_quote'].split()).casefold()
            if normalized not in cache[key]:
                # Quotes are V6-verified using an extraction normalization method
                # that may differ in punctuation; avoid a false negative by
                # deferring to graph-builder verification when formatting differs.
                errors.append(f"{hint['question_id']}: page text did not exactly contain source quote; inspect extraction")
        except Exception as exc:
            errors.append(f"{hint['question_id']}: cannot inspect PDF: {exc}")
    return {'passed':not errors,'errors':errors,'n_hints':len(hints),'n_source_pdfs':len(pdf_files)}


def questions_jsonl(questions:list[dict]) -> str:
    return '\n'.join(json.dumps(q,ensure_ascii=False) for q in questions)+'\n'


def csv_data(rows:list[dict]) -> str:
    if not rows: raise ValueError('Empty records')
    out=io.StringIO(newline='')
    writer=csv.DictWriter(out,fieldnames=list(rows[0]),lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue()


def manifest_for(docs:str | Path, graph:str | Path | None, questions:list[dict], methods:list[str],
                 chunk_words:int, overlap_words:int, k:int, pool_size:int, alpha:float,
                 model:str, q_content:str) -> dict:
    root=Path(docs).resolve()
    files=sorted(p for p in root.rglob('*') if p.suffix.lower() in {'.pdf','.txt','.md'} and p.is_file())
    sources={p.relative_to(root).as_posix():sha256(p) for p in files}
    return {'schema':'iko-auto-v7-pilot-1','created_utc':datetime.now(timezone.utc).isoformat(),
            'mode':'DEVELOPMENT_PILOT_NOT_HELDOUT',
            'ontology_validation':'USER_REPORTED_POSITIVE_SPECIALIST_FEEDBACK_NOT_ITEM_LEVEL_AUDITED',
            'corpus_path':str(root), 'source_sha256':sources,
            'graph_path':str(Path(graph).resolve()) if graph else None,
            'graph_sha256':sha256(graph) if graph else None,
            'questions_sha256':hashlib.sha256(q_content.encode('utf-8')).hexdigest(),
            'n_questions':len(questions), 'split_counts':dict(Counter(q['split'] for q in questions)),
            'methods':methods,'parameters':{'chunk_words':chunk_words,'overlap_words':overlap_words,
                     'top_k':k,'pool_size':pool_size,'alpha':alpha,'embedding_model':model},
            'reporting_restrictions':['Questions are development-only and seen during ontology construction.',
              'Neither human passage relevance nor independent held-out test results are available.',
              'Do not calculate test metrics from these prompts or relabel dev as test.',
              'PDF sources have not been cleared for redistribution by this application.']}


def verify_manifest(manifest:dict, docs: str | Path, graph: str | Path | None) -> dict:
    root=Path(docs).resolve()
    issues=[]
    if root!=Path(manifest['corpus_path']): issues.append('Changed corpus root')
    current={p.relative_to(root).as_posix():sha256(p) for p in root.rglob('*') if p.is_file() and p.suffix.lower() in {'.pdf','.txt','.md'}}
    if current!=manifest['source_sha256']: issues.append('Document set or checksums have changed')
    if (str(Path(graph).resolve()) if graph else None)!=manifest['graph_path']:
        issues.append('RDF graph path changed')
    if graph and sha256(graph)!=manifest['graph_sha256']: issues.append('RDF graph contents changed')
    return {'passed':not issues,'errors':issues}


def prepare_pilot_bundle(retriever, docs: str | Path, graph: str | Path | None,
                         questions:list[dict], methods:list[str], k:int=5,
                         pool_size:int=10,alpha:float=0.6,
                         chunk_words:int=170,overlap_words:int=45,
                         model:str='sentence-transformers/all-MiniLM-L6-v2') -> dict:
    """Build retrieval outputs and BLANK review sheets; never invent judgments."""
    from .annotation_workflow import SHEET_COLUMNS
    check=validate_pilot_questions(questions,real_only=False)
    if not check['passed']: raise ValueError('; '.join(check['errors']))
    if not 1<=k<=pool_size<=50: raise ValueError('Require 1 <= top_k <= pool_size <= 50')
    if not methods or len(methods)!=len(set(methods)) or set(methods)-set(METHODS):
        raise ValueError('Methods must be distinct and supported')
    if (set(methods)&GRAPH_MODES) and not graph:
        raise ValueError('Graph modes require a matching RDF file')
    names={q['insurer'] for q in questions}
    from .policy_catalog import allowed_sources
    for insurer in names:
        if not allowed_sources(retriever.chunks,insurer):
            raise ValueError(f'No indexed files for insurer: {insurer}')
    qtxt=questions_jsonl(questions)
    run=method_runs(retriever, questions, methods, k, alpha, pool_size)
    pool=candidate_pool_rows(questions,run,retriever.chunks)
    if not pool: raise ValueError('No candidate passages retrieved')
    # Reviewer exports hide method names and internal researcher source hints.
    blinded=[]
    for r in pool:
        blinded.append({col:r.get(col,'') for col in SHEET_COLUMNS})
    manifest=manifest_for(docs,graph,questions,methods,chunk_words,overlap_words,k,pool_size,alpha,model,qtxt)
    manifest['n_pool_pairs']=len(pool)
    manifest['pool_sha256']=hashlib.sha256(csv_data(pool).encode('utf-8')).hexdigest()
    manifest['runs_sha256']=hashlib.sha256(json.dumps(run,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    manifest['n_indexed_chunks']=len(retriever.chunks)
    return {'questions':questions, 'runs':run,'pool':pool,'blinded':blinded, 'manifest':manifest,
            'summary':{'questions':len(questions),'candidate_pairs':len(pool),'methods':methods,'dev_questions':len(questions),
            'test_questions':0,'labels':0,'note':'No human judgments, no accuracy metrics. Development pilot only.'}}


def write_pilot_outputs(out_dir:str | Path, bundle:dict, hints:list[dict] | None=None) -> list[str]:
    from .annotation_workflow import SHEET_COLUMNS
    folder=Path(out_dir)
    if folder.exists() and any(folder.iterdir()): raise FileExistsError('Output folder is not empty. Select a fresh folder to preserve study history.')
    folder.mkdir(parents=True,exist_ok=True)
    generated=[]
    def add(name:str, contents:str):
        p=folder/name;p.write_text(contents,encoding='utf-8-sig' if p.suffix=='.csv' else 'utf-8');generated.append(str(p))
    add('questions_DEV_ONLY.jsonl',questions_jsonl(bundle['questions']))
    if hints: add('RESEARCHER_ONLY_source_hints.csv',csv_data(hints))
    add('INTERNAL_pool_with_method_origins.csv',csv_data(bundle['pool']))
    for rid in ('Reviewer_A','Reviewer_B'):
        rows=[{**r,'annotator_id':rid,'relevance':'','evidence_quote':'','notes':''} for r in bundle['blinded']]
        add(f'{rid}_BLINDED_BLANK.csv',csv_data(rows))
    add('manifest_DEVELOPMENT.json',json.dumps(bundle['manifest'],ensure_ascii=False,indent=2))
    add('runs_DEVELOPMENT.json',json.dumps(bundle['runs'],ensure_ascii=False,indent=2))
    add('START_HERE_V7.txt',
        'IKO-Auto V7: DEVELOPMENT PILOT, NOT A HELD-OUT TEST.\n\n'
        'Reviewer_A and Reviewer_B must be separate humans.\n'
        'They independently fill relevance=0/1/2 for EVERY row, and exact evidence_quote for 1/2.\n'
        'Do NOT share INTERNAL_pool_with_method_origins or RESEARCHER_ONLY_source_hints with reviewers.\n'
        'Do NOT fabricate reviewer decisions or report scientific performance from unlabeled data.\n'
        'When both reviewers finish, run merge-ratings and a human adjudicator completes the worklist.\n'
        'Retain unchanged corpus, graph and chunking between pooling and evaluation.\n')
    return generated


def bundle_zip_bytes(bundle:dict,hints:list[dict]|None=None) -> bytes:
    from .annotation_workflow import SHEET_COLUMNS
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('questions_DEV_ONLY.jsonl',questions_jsonl(bundle['questions']))
        if hints: z.writestr('RESEARCHER_ONLY_source_hints.csv',csv_data(hints))
        z.writestr('INTERNAL_pool_with_method_origins.csv',csv_data(bundle['pool']))
        for rid in ('Reviewer_A','Reviewer_B'):
            rows=[{**r,'annotator_id':rid,'relevance':'','evidence_quote':'','notes':''} for r in bundle['blinded']]
            z.writestr(f'{rid}_BLINDED_BLANK.csv',csv_data(rows))
        z.writestr('manifest_DEVELOPMENT.json',json.dumps(bundle['manifest'],ensure_ascii=False,indent=2))
        z.writestr('runs_DEVELOPMENT.json',json.dumps(bundle['runs'],ensure_ascii=False,indent=2))
        z.writestr('INSTRUCTIONS.txt','DEVELOPMENT PILOT only. Two independent human reviewers must label all rows. No results exist yet. Do not share INTERNAL files with raters. No policy PDFs included.')
    return mem.getvalue()


def evaluate_reviewed_pilot(*, docs: str | Path, graph: str | Path | None,
                            manifest_path: str | Path, questions_path: str | Path,
                            runs_path: str | Path, qrels_path: str | Path,
                            pool_path: str | Path, reviewer_a_path: str | Path,
                            reviewer_b_path: str | Path, worklist_path: str | Path) -> dict:
    """Validate the full two-reviewer->human-adjudication chain before scoring DEV."""
    from .annotation_workflow import _keys, _read_csv, _verify_rating
    import hashlib as _hashlib
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest.get('schema')!='iko-auto-v7-pilot-1': raise ValueError('Not a V7 pilot manifest')
    if manifest.get('mode')!='DEVELOPMENT_PILOT_NOT_HELDOUT': raise ValueError('Invalid study mode')
    verified=verify_manifest(manifest,docs,graph)
    if not verified['passed']: raise ValueError('Corpus or graph changed: '+str(verified['errors']))
    qtext=Path(questions_path).read_text(encoding='utf-8-sig')
    if _hashlib.sha256(qtext.encode('utf-8')).hexdigest()!=manifest['questions_sha256']:
        raise ValueError('Question file changed since pooling')
    qrows=questions_from(questions_path)
    check=validate_pilot_questions(qrows,real_only=False)
    if not check['passed']: raise ValueError('; '.join(check['errors']))
    if len(qrows)!=manifest['n_questions']: raise ValueError('Question count differs from manifest')
    runs=json.loads(Path(runs_path).read_text(encoding='utf-8'))
    if list(runs)!=manifest['methods']: raise ValueError('Method configuration differs from manifest')
    if hashlib.sha256(json.dumps(runs,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()!=manifest['runs_sha256']:
        raise ValueError('Retrieval run identifiers were modified after pooling')
    pool_rows=_read_csv(pool_path)
    if hashlib.sha256(csv_data(pool_rows).encode('utf-8')).hexdigest()!=manifest['pool_sha256']:
        raise ValueError('The original candidate pool was modified after pooling')
    pool=_keys(pool_rows,'Candidate pool')
    if len(pool)!=manifest['n_pool_pairs']: raise ValueError('Candidate pool size differs from original manifest')
    left=_keys(_read_csv(reviewer_a_path),'Reviewer A')
    right=_keys(_read_csv(reviewer_b_path),'Reviewer B')
    work=_keys(_read_csv(worklist_path),'Human adjudication')
    if not set(pool)==set(left)==set(right)==set(work):
        raise ValueError('Reviewer and adjudication rows must exactly match pooled question–passage pairs')
    reviewer_ids=[]
    for rater in (left,right):
        ids={rec.get('annotator_id','').strip() for rec in rater.values()}
        if len(ids)!=1 or not next(iter(ids)):
            raise ValueError('Reviewer ID must be nonblank and consistent in each file')
        reviewer_ids.append(next(iter(ids)))
    if reviewer_ids[0]==reviewer_ids[1]: raise ValueError('Two distinct reviewer IDs required')
    for key in pool:
        original=pool[key]
        for rated,suffix,identity in ((left,'a',reviewer_ids[0]),(right,'b',reviewer_ids[1])):
            row=rated[key]
            _verify_rating(row,0,identity)
            for col in ('question','text','source_path','page','chunk_id','question_id'):
                if str(row.get(col,''))!=str(original.get(col,'')):
                    raise ValueError(f'Reviewer changed source {col} for {key}')
            if str(work[key][f'rater_{suffix}_label']).strip()!=str(row['relevance']).strip():
                raise ValueError(f'Adjudication does not match original reviewer {suffix} for {key}')
            if str(work[key][f'rater_{suffix}_id']).strip()!=identity:
                raise ValueError(f'Adjudication changed reviewer identity for {key}')
        if str(work[key].get('text',''))!=str(original.get('text','')):
            raise ValueError(f'Adjudication altered passage text for {key}')
    adjudicated=read_labels(qrels_path)
    if set(adjudicated)!=set(pool):
        raise ValueError('Every pooled question–passage pair requires one final relevance judgment')
    for key,item in work.items():
        if item.get('final_relevance','').strip()!=str(adjudicated[key]) or not item.get('adjudicator_id','').strip():
            raise ValueError(f'Final relevance lacks an explicit human adjudicator for {key}')
        if item.get('agreement','').strip()=='no' and not item.get('decision_notes','').strip():
            raise ValueError(f'Unexplained rating disagreement at {key}')
    from .pipeline import build_pipeline
    params=manifest['parameters']
    retriever=build_pipeline(docs,params['chunk_words'],params['overlap_words'],params['embedding_model'],graph)
    result=score_runs(qrows,runs,adjudicated,params['top_k'],strict=True,
                      corpus_ids={c.chunk_id for c in retriever.chunks})
    result['category_summary']=category_summary(result)
    result['ablation_dev_descriptive']=factorial_ablation(result,split='dev')
    result['reporting_status']='DEVELOPMENT_PILOT_ONLY_NOT_HELDOUT'
    result['ontology_review_status']='USER_REPORTED_POSITIVE_SPECIALIST_FEEDBACK_NOT_ITEM_LEVEL_AUDITED'
    result['annotator_ids']=reviewer_ids
    result['n_adjudicated_pairs']=len(adjudicated)
    return result
