"""Compare immutable original V8 vs V8.1 ZIP outputs; does not score relevance."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.v8_1_compare import compare_frozen_packages

def main():
    p=argparse.ArgumentParser(description='Compare original V8 to V8.1 same-question frozen retrieval, WITHOUT labels')
    p.add_argument('--original',required=True,help='Original V8 ZIP, unchanged')
    p.add_argument('--new',required=True,help='New V8.1 ZIP')
    p.add_argument('--out',required=True,help='JSON diagnostic report')
    args=p.parse_args()
    report=compare_frozen_packages(args.original,args.new)
    path=Path(args.out)
    if path.exists(): raise FileExistsError('Do not overwrite previous comparison: '+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2,ensure_ascii=False))
    if not report['safeguards_passed']:
        raise SystemExit('Baseline changed or provenance anomaly: investigate before reporting comparison')

if __name__=='__main__': main()
