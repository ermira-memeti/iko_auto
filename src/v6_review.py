"""V6 candidate ontology relationship review sheets.

A source-exact quotation is not expert confirmation. Decisions intentionally
start blank and no completion or adjudication is manufactured by this module.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path

COLUMNS = (
    'assertion_id','policy_id','policy_name','relation','subject','target',
    'source_document','pdf_page','source_sha256','evidence_quote',
    'reviewer_id','decision','review_notes',
)
DECISIONS = {'approve','reject','needs_revision'}


def load_annotations(path: str | Path) -> dict:
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data.get('policies'), list) or not data['policies']:
        raise ValueError('No policies in candidate annotations')
    return data


def review_rows(annotations: dict | str | Path) -> list[dict]:
    if not isinstance(annotations,dict):
        annotations=load_annotations(annotations)
    rows=[]
    def emit(policy,relation,subject,target,evidence):
        proof = f"{policy['id']}\n{relation}\n{subject}\n{target}\n{evidence['sha256']}\n{evidence['page']}\n{evidence['quote']}"
        aid = hashlib.sha256(proof.encode('utf-8')).hexdigest()[:20]
        rows.append(dict(zip(COLUMNS,[
            aid,policy['id'],policy['name'],relation,subject,target,
            evidence['document'],evidence['page'],evidence['sha256'],evidence['quote'],
            '','',''
        ])))
    for pol in annotations['policies']:
        first = pol['coverages'][0]['evidence']
        emit(pol,'hasVersion',pol['name'],pol['version'],first)
        for condition in pol.get('claim_conditions',[]):
            emit(pol,'hasClaimCondition',pol['version'],condition['name'],condition['evidence'])
        for cov in pol['coverages']:
            emit(pol,'hasCoverage',pol['version'],cov['name'],cov['evidence'])
            for excl in cov.get('exclusions',[]):
                emit(pol,'hasExclusion',cov['name'],excl['name'],excl['evidence'])
                for exc in excl.get('exceptions',[]):
                    emit(pol,'hasException',excl['name'],exc['name'],exc['evidence'])
            for key,relation in [('deductible','hasDeductible'),('limit','hasLimit')]:
                if cov.get(key):
                    obj=cov[key]
                    emit(pol,relation,cov['name'],obj['name'],obj['evidence'])
    if len(rows)!=len({r['assertion_id'] for r in rows}):
        raise ValueError('Duplicate relationship assertion identifier')
    return rows


def sheet_csv(annotations, reviewer_hint='') -> str:
    records=review_rows(annotations)
    buffer=io.StringIO(newline='')
    writer=csv.DictWriter(buffer,fieldnames=COLUMNS,lineterminator='\n')
    writer.writeheader()
    for record in records:
        entry={**record, 'reviewer_id':reviewer_hint, 'decision':'','review_notes':''}
        writer.writerow(entry)
    return buffer.getvalue()


def read_reviewed_csv(stream: str | bytes) -> list[dict]:
    if isinstance(stream,bytes):
        stream=stream.decode('utf-8-sig')
    return list(csv.DictReader(io.StringIO(stream)))


def check_review_sheet(candidate_rows, submitted_rows):
    expected={r['assertion_id']:r for r in candidate_rows}
    errors=[]; statuses={}
    if len(submitted_rows)!=len(expected):
        errors.append(f'Expected {len(expected)} rows, received {len(submitted_rows)}')
    seen=set()
    fixed = set(COLUMNS)-{'reviewer_id','decision','review_notes'}
    for r in submitted_rows:
        aid=r.get('assertion_id','')
        if aid in seen:
            errors.append(f'Duplicate assertion id {aid}')
            continue
        seen.add(aid)
        if aid not in expected:
            errors.append(f'Unknown assertion id {aid}')
            continue
        baseline=expected[aid]
        if any(str(r.get(k,''))!=str(baseline[k]) for k in fixed):
            errors.append(f'Candidate source fields were modified for {aid}')
        status=(r.get('decision') or '').strip().lower().replace(' ','_')
        if status and status not in DECISIONS:
            errors.append(f'Unrecognized reviewer decision {status} for {aid}')
        statuses[aid]=status
    for missing in sorted(set(expected)-seen):
        errors.append(f'Missing assertion {missing}')
    return {'valid':not errors, 'errors':errors, 'n_rows':len(submitted_rows),
            'approved':sum(s=='approve' for s in statuses.values()),
            'rejected':sum(s=='reject' for s in statuses.values()),
            'needs_revision':sum(s=='needs_revision' for s in statuses.values()),
            'unreviewed':sum(not s for s in statuses.values())}


def comparison(candidate_rows, reviewer_a, reviewer_b):
    ra=check_review_sheet(candidate_rows,reviewer_a)
    rb=check_review_sheet(candidate_rows,reviewer_b)
    if not (ra['valid'] and rb['valid']):
        return {'valid':False,'reviewer_a':ra,'reviewer_b':rb,'error':'Complete and correct both sheets before comparing them'}
    a={r['assertion_id']:r for r in reviewer_a}
    b={r['assertion_id']:r for r in reviewer_b}
    differences=[]; fully_reviewed=0; agreements=0
    for expected in candidate_rows:
        key=expected['assertion_id']
        da=a[key]['decision'].strip().lower().replace(' ','_')
        db=b[key]['decision'].strip().lower().replace(' ','_')
        if da and db:
            fully_reviewed+=1
            agreements+=(da==db)
            if da!=db:
                differences.append({**expected,'reviewer_a':da,'reviewer_b':db,'adjudicated_decision':''})
    return {'valid':True,'reviewer_a':ra,'reviewer_b':rb,'reviewed_by_both':fully_reviewed,
            'agreement_count':agreements,'raw_agreement': agreements/fully_reviewed if fully_reviewed else None,
            'disagreements':differences,
            'note':'Raw agreement only. Blank adjudication fields require human decision; this is not an independent expert-validation claim.'}
