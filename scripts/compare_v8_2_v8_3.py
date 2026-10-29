"""Compare original frozen V8.2 ZIP to the new V8.3 ZIP, without judgments."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.v8_3_compare import compare_v8_2_v8_3

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--v8-2',required=True,dest='previous')
    parser.add_argument('--v8-3',required=True,dest='current')
    parser.add_argument('--out',default='')
    args=parser.parse_args()
    report=compare_v8_2_v8_3(args.previous,args.current)
    result=json.dumps(report,indent=2,ensure_ascii=False)
    if args.out:Path(args.out).write_text(result,encoding='utf-8')
    print(result)
    if not report['safeguards_passed']:raise SystemExit(2)
