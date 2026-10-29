import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.v8_2_compare import compare_v8_1_v8_2

def main():
    p=argparse.ArgumentParser(description='Read-only V8.1 versus V8.2 frozen benchmark integrity comparison')
    p.add_argument('--v81',required=True)
    p.add_argument('--v82',required=True)
    p.add_argument('--out',required=True)
    args=p.parse_args()
    report=compare_v8_1_v8_2(args.v81,args.v82)
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():raise FileExistsError(out)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'saved':str(out),'safeguards_passed':report['safeguards_passed'],
                      'new_method_nonempty_questions':report['new_method_nonempty_questions']},indent=2))
if __name__=='__main__':main()
