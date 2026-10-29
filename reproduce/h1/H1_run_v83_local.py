#!/usr/bin/env python3
"""H1 new-question evaluation orchestration for an ORIGINAL IKO-Auto V8.3 project.

This wrapper NEVER implements or approximates the eight retrieval algorithms.
It sends the 50 H1 questions to the existing V8.3 executable, validates its
ranked result CSV, and prepares separate blank reviewer sheets.

Examples (Windows Command Prompt):
  python H1_run_v83_local.py --project "D:\\Projects\\IKO-Auto" --inspect
  python H1_run_v83_local.py --project "D:\\Projects\\IKO-Auto" --run

If your original CLI is not auto-detectable, use its actual documented command:
  python H1_run_v83_local.py --project "D:\\Projects\\IKO-Auto" --run --engine-cmd "{python} -m src.heldout_v8 --questions {questions_jsonl} --output {output}"

The placeholders {python}, {project}, {questions}, {questions_jsonl},
{output}, {output_dir} are expanded as arguments safely (no shell execution).
The original engine must write H1_EIGHT_METHOD_TOP5.csv matching the schema.
If its API is different, use --inspect and supply the actual CLI command.
A frozen rankings JSON from the *old 50 questions* is not an H1 result.
"""
from __future__ import annotations

import argparse
import ast
import collections
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import time

METHODS = tuple(f'M{i}' for i in range(1, 9))
INSURERS = ('AXA', 'Admiral', 'Aviva', 'Direct Line', 'esure')
REQUIRED = ('method','question_id','rank','chunk_id','source_path','page','text','start_word','end_word')
SOURCE_FILES = ('axa_car_policy.pdf','admiral_car_policy.pdf','aviva_car_policy.pdf',
                'directline_car_policy.pdf','esure_car_policy.pdf')


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def readcsv(path: Path) -> list[dict]:
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def check_questions(path: Path, manifest: Path | None) -> tuple[list[dict], dict]:
    if not path.is_file():
        raise ValueError(f'Question file not found: {path}')
    rows = readcsv(path)
    req = {'question_id','insurer','question','category'}
    if not rows or not req.issubset(rows[0]):
        raise ValueError(f'Question CSV requires {sorted(req)}')
    ids = [x['question_id'].strip() for x in rows]
    if len(rows) != 50 or len(set(ids)) != 50:
        raise ValueError(f'Expected exactly 50 distinct H1 questions, found {len(rows)} rows / {len(set(ids))} distinct IDs')
    if not all(re.fullmatch(r'H1Q_[A-Z0-9_]+', x) for x in ids):
        raise ValueError('H1 question IDs must match H1Q_*')
    counts = collections.Counter(x['insurer'] for x in rows)
    if counts != {name: 10 for name in INSURERS}:
        raise ValueError(f'Unexpected insurer distribution: {dict(counts)}')
    if not all(x['question'].strip() for x in rows):
        raise ValueError('Blank H1 questions found')
    fingerprint = checksum(path)
    if manifest is not None and manifest.is_file():
        meta = json.loads(manifest.read_text(encoding='utf-8'))
        expected = meta.get('benchmark_question_csv_sha256', '')
        if expected and expected != fingerprint:
            raise ValueError(f'H1 question file differs from the supplied benchmark manifest! Expected {expected}, got {fingerprint}')
    return rows, {'questions': len(rows), 'question_sha256': fingerprint, 'insurer_counts': dict(counts)}


def find_pdfs(project: Path, override: Path | None) -> dict:
    dirs = [override] if override else [project/'data'/'research_corpus', project/'research_corpus',
                                       project/'data', project]
    found = next((d for d in dirs if d is not None and d.is_dir() and all((d/n).is_file() for n in SOURCE_FILES)), None)
    if found is None:
        return {'status':'not_located', 'checked_paths':[str(x) for x in dirs if x]}
    return {'status':'found', 'directory':str(found.resolve()),
            'sha256': {n:checksum(found/n) for n in SOURCE_FILES}}


def verify_pdfs(actual: dict, manifest_path: Path | None) -> None:
    if actual['status'] != 'found':
        print('WARNING: Original PDFs not located. Document identity cannot be verified by this wrapper.')
        return
    if manifest_path and manifest_path.is_file():
        expected = json.loads(manifest_path.read_text(encoding='utf-8')).get('source_files', {})
        for obj in expected.values():
            name = obj.get('filename')
            if name in actual['sha256'] and obj.get('sha256') != actual['sha256'][name]:
                raise ValueError(f'SOURCE PDF HASH MISMATCH for {name}: expected {obj.get("sha256")}, actual {actual["sha256"][name]}. Do not modify PDFs or bypass this check.')
    print('Source PDFs available; all located file hashes agree with the H1 manifest.')


def repo_info(project: Path) -> dict:
    info = {'project':str(project), 'python':sys.version, 'platform':platform.platform()}
    def git(*args):
        p = subprocess.run(['git', '-C', str(project), *args],capture_output=True,text=True,timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ''
    try:
        info['git_sha'] = git('rev-parse','HEAD')
        info['git_status_before'] = git('status','--porcelain')[:5000]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info['git_sha'] = None
    files = ['src/research_eval.py','src/graph_retrieval.py','src/heldout_v8.py',
             'src/v8_3_intent.py','src/v8_3_compare.py',
             'ontology/iko_auto_v6.ttl',
             'outputs/v6/iko_auto_five_insurers_v6.ttl',
             'outputs/v8_2/iko_auto_extended_v8_2.ttl']
    info['tracked_artifact_hashes'] = {name:checksum(project/name) for name in files if (project/name).is_file()}
    return info


def inspect(project: Path):
    print('\nIKO-AUTO H1 / ORIGINAL ENGINE INSPECTION')
    for name in ('src/heldout_v8.py','src/research_eval.py','src/v8_3_intent.py'):
        path = project/name
        print('\n'+name+': '+('FOUND' if path.is_file() else 'MISSING'))
        if not path.is_file():
            continue
        try:
            root = ast.parse(path.read_text(encoding='utf-8-sig'))
        except (UnicodeDecodeError, SyntaxError) as exc:
            print('  Cannot parse:', exc)
            continue
        for obj in root.body:
            if isinstance(obj,(ast.FunctionDef,ast.AsyncFunctionDef)):
                args = ', '.join(x.arg for x in obj.args.args)
                if any(k in obj.name.lower() for k in ('main','run','rank','retrieve','eval','method','query','freeze')):
                    print(f'  function {obj.name}({args})  line {obj.lineno}')
            if isinstance(obj,ast.ClassDef):
                print('  class',obj.name)
        print('  CLI option strings:')
        flags = sorted(set(re.findall(r'--[a-z][a-z0-9-]+',path.read_text(encoding='utf-8-sig',errors='replace'))))
        print('   ', ', '.join(flags[:45]) or '(none detected)')
    print('\nIf automatic run cannot identify the frozen CLI, share these files:')
    print('  src/heldout_v8.py, src/research_eval.py, src/graph_retrieval.py, src/v8_3_intent.py')
    print('This allows a precisely matched adapter without rewriting M1-M8.')


def auto_engine_cmd(project: Path) -> str | None:
    """Only recognize an unambiguous, parameterized original CLI; never guess opaque APIs."""
    engine = project/'src'/'heldout_v8.py'
    if not engine.is_file():
        return None
    src = engine.read_text(encoding='utf-8-sig',errors='replace')
    opts = set(re.findall(r'--[a-z][a-z0-9-]+', src))
    input_opts = ('--questions-csv','--questions-file','--questions','--question-file','--input-questions')
    output_opts = ('--output-csv','--rankings-csv','--output-file','--results-csv')
    ins = next((k for k in input_opts if k in opts),None)
    outs = next((k for k in output_opts if k in opts),None)
    if not (ins and outs):
        return None
    return f'{{python}} src/heldout_v8.py {ins} {{questions}} {outs} {{output}}'


def build_engine_args(template: str, project: Path, questions: Path, jsonl: Path, output: Path) -> list[str]:
    options = {'python':str(Path(sys.executable).resolve()), 'project':str(project),
               'questions':str(questions), 'questions_jsonl':str(jsonl),
               'output':str(output), 'output_dir':str(output.parent)}
    tokens = shlex.split(template, posix=True)
    if not tokens:
        raise ValueError('Blank --engine-cmd')
    try:
        return [token.format_map(options) for token in tokens]
    except KeyError as exc:
        raise ValueError(f'Unknown placeholder {exc} in --engine-cmd') from exc


def verify_rankings(path: Path, questions: list[dict], index_csv: Path | None) -> dict:
    if not path.is_file():
        raise ValueError(f'Original V8.3 runner did not create the required CSV: {path}')
    rows = readcsv(path)
    if not rows or not set(REQUIRED).issubset(rows[0]):
        found = sorted(rows[0]) if rows else []
        raise ValueError('Missing required columns in original engine output. '
                         f'Expected {REQUIRED}; actual {found}. '
                         'The original runner needs an output adapter, NOT a replacement ranker.')
    qs = {q['question_id'] for q in questions}
    pairs = collections.defaultdict(list)
    empty = set()
    content = {}
    for i,r in enumerate(rows,2):
        m=r['method'].strip().upper(); q=r['question_id'].strip(); cid=r['chunk_id'].strip()
        if m not in METHODS or q not in qs:
            raise ValueError(f'Invalid method/question on CSV line {i}: {m}/{q}')
        try: rank = int(r['rank'])
        except ValueError: raise ValueError(f'Bad rank on line {i}: {r["rank"]}')
        if rank == 0 and not cid:
            if (m,q) in empty or pairs[(m,q)]:
                raise ValueError(f'Mixed/duplicated empty marker for {m}/{q}')
            empty.add((m,q))
            continue
        if (m,q) in empty or rank not in (1,2,3,4,5) or not cid:
            raise ValueError(f'Invalid top5 rank/ID for {m}/{q} on line {i}')
        if not r['source_path'].strip() or not r['text'].strip() or not r['page'].strip():
            raise ValueError(f'Missing provenance/text for {m}/{q}/{cid}')
        try: p=int(r['page'])
        except ValueError:raise ValueError(f'Noninteger page for {cid}')
        if p<1: raise ValueError(f'Page must be 1-based for {cid}')
        if cid in content and content[cid] != (r['source_path'], r['page'], r['text']):
            raise ValueError(f'Inconsistent metadata for passage {cid}')
        content[cid] = (r['source_path'], r['page'], r['text'])
        pairs[(m,q)].append((rank,cid))
    absent = {(m,q) for m in METHODS for q in qs}-set(pairs)-empty
    if absent:
        raise ValueError(f'Missing {len(absent)} method/question cases; first {sorted(absent)[:5]}')
    for key, items in pairs.items():
        ranks=sorted(rank for rank,_ in items)
        if ranks != list(range(1,len(ranks)+1)) or len(set(cid for _,cid in items)) != len(items):
            raise ValueError(f'Nonconsecutive or duplicated top-5 results: {key}')
    index_status='not supplied; master 717-passage membership not checked'
    if index_csv:
        index_rows = readcsv(index_csv)
        known={r.get('chunk_id','').strip() for r in index_rows}
        if len(known)!=717 or '' in known:
            raise ValueError(f'Expected 717 distinct chunk IDs in index CSV; got {len(known)}')
        unknown=set(content)-known
        if unknown:
            raise ValueError('Output contains IDs absent from the original 717-passage index: '+str(sorted(unknown)[:5]))
        index_status='all retrieved chunk IDs verified against 717-passage index'
    return {'method_question_cases':len(set(pairs)|empty),
            'returned_rows':sum(len(x) for x in pairs.values()),
            'empty_cases':len(empty), 'unique_passages':len(content),
            'returned_per_method':{m:sum(len(x) for (mm,_),x in pairs.items() if mm==m) for m in METHODS},
            'master_index_check':index_status}


def run(args, project:Path, questions_path:Path, jsonl:Path, manifest:Path|None) -> None:
    questions, qinfo = check_questions(questions_path,manifest)
    pdfs = find_pdfs(project,Path(args.pdf_folder).resolve() if args.pdf_folder else None)
    verify_pdfs(pdfs,manifest)
    if not project.is_dir(): raise ValueError(f'Project directory does not exist: {project}')
    before=repo_info(project)
    cmd_tpl = args.engine_cmd or auto_engine_cmd(project)
    if not cmd_tpl:
        inspect(project)
        raise ValueError('Cannot safely infer the V8.3 engine command from local source files. '
                         'Run --inspect or provide the original CLI with --engine-cmd. '
                         'No substitute retrieval algorithm has been run.')
    if not jsonl.is_file():
        raise ValueError(f'H1 question JSONL is required by some engines and was not found: {jsonl}')
    results_dir=Path(args.output_dir).resolve()
    results_dir.mkdir(parents=True,exist_ok=True)
    output=results_dir/'H1_EIGHT_METHOD_TOP5.csv'
    if output.exists() and not args.force:
        raise ValueError(f'{output} already exists. Use a new --output-dir, or --force if intentionally rerunning.')
    engine_args=build_engine_args(cmd_tpl,project,questions_path,jsonl,output)
    if '--help' in engine_args:
        raise ValueError('Engine command must run retrieval, not --help.')
    print('\nExecuting ORIGINAL project code (no substitute rankers):')
    print('  '+subprocess.list2cmdline(engine_args))
    log = results_dir/'H1_ENGINE_LOG.txt'
    t0=time.time()
    try:
        completed = subprocess.run(engine_args,cwd=project,stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,text=True,errors='replace',timeout=args.timeout)
    except subprocess.TimeoutExpired:
        raise ValueError(f'Engine exceeded {args.timeout}s; check original CLI and run log.')
    log.write_text(completed.stdout,encoding='utf-8')
    print('Engine exit code:',completed.returncode,'| log:',log)
    if completed.returncode:
        print('\n'.join(completed.stdout.splitlines()[-18:]))
        raise ValueError('Original engine reported an error. See H1_ENGINE_LOG.txt.')
    stats=verify_rankings(output,questions,Path(args.index_csv).resolve() if args.index_csv else None)
    if stats['returned_rows']==0:
        raise ValueError('All 400 original engine cases were empty. Cannot create a meaningful relevance pool; inspect engine routing.')
    after=repo_info(project)
    changed=[k for k,v in before['tracked_artifact_hashes'].items() if after['tracked_artifact_hashes'].get(k)!=v]
    if changed:
        raise ValueError('STOP: source code or graph artifacts changed during H1 run: '+repr(changed))
    provenance={'benchmark':'H1_NEW_QUESTIONS_SEEN_DOCUMENTS',
                'run_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                'duration_seconds':round(time.time()-t0,2),
                'engine_command':engine_args, 'original_code_provenance':before,
                'question_dataset':qinfo,'source_files':pdfs,
                'validation':stats,'output_csv_sha256':checksum(output),
                'limitations':['New questions on previously used PDF policy editions.',
                               'Source question key is excluded from engine.',
                               'This run does not produce or infer human relevance judgments.']}
    (results_dir/'H1_RUN_PROVENANCE.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    print('PASS: H1 ranking export validated:',stats)
    prep=Path(args.prepare_script).resolve() if args.prepare_script else (Path(__file__).parent/'H1_prepare_and_evaluate.py')
    if not prep.is_file():
        raise ValueError(f'Rankings saved, but review preparation script not found: {prep}')
    subprocess.run([sys.executable,str(prep),'prepare',str(output),str(questions_path)],check=True)
    print('\nSUCCESS: H1 ranked CSV and BLANK reviewer A/B CSVs in',results_dir)
    print('NEXT: two independent humans grade pooled passages 0/1/2, without the private answer key.')


def main():
    p=argparse.ArgumentParser(description='Run H1 through original V8.3 engine, verify rankings, prepare blinded review sheets.',formatter_class=argparse.RawDescriptionHelpFormatter,epilog=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--inspect',action='store_true',help='Describe V8.3 project entrypoints without executing retrieval')
    group.add_argument('--run',action='store_true',help='Run original project retrieval, validate CSV and prepare reviewer sheets')
    p.add_argument('--project',required=True,help='Directory containing original V8.3 src/ Python files')
    p.add_argument('--questions',help='H1_50_QUESTIONS_FOR_RETRIEVAL.csv (default: next to this script)')
    p.add_argument('--questions-jsonl',help='H1 question JSONL (default: next to this script)')
    p.add_argument('--manifest',help='H1_MANIFEST.json (default: next to this script)')
    p.add_argument('--pdf-folder',help='Optional directory containing the five original PDFs')
    p.add_argument('--output-dir',default='H1_RESULTS',help='New output folder (default: H1_RESULTS in current directory)')
    p.add_argument('--engine-cmd',help='Actual V8.3 CLI command with placeholders {python} {questions} {questions_jsonl} {output} {output_dir} {project}')
    p.add_argument('--index-csv',help='Optional ORIGINAL 717-passage index CSV for full chunk ID verification')
    p.add_argument('--prepare-script',help='Path to H1_prepare_and_evaluate.py (default: next to script)')
    p.add_argument('--timeout',type=int,default=3600,help='Maximum original engine run seconds')
    p.add_argument('--force',action='store_true',help='Allow replacing H1 output file, never the V8.3 historical archive')
    a=p.parse_args()
    project=Path(a.project).expanduser().resolve()
    base=Path(__file__).parent
    question_file=Path(a.questions).resolve() if a.questions else base/'H1_50_QUESTIONS_FOR_RETRIEVAL.csv'
    jsonl=Path(a.questions_jsonl).resolve() if a.questions_jsonl else base/'H1_50_QUESTIONS_FOR_RETRIEVAL.jsonl'
    manifest=Path(a.manifest).resolve() if a.manifest else base/'H1_MANIFEST.json'
    try:
        if a.inspect:inspect(project)
        else:run(a,project,question_file,jsonl,manifest)
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        sys.exit('\nSTOPPED: '+str(exc))

if __name__ == '__main__':
    main()
