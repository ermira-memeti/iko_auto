"""Build a NEW evidence-grounded RDF overlay. Never modifies the V6 graph."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.v8_2_graph_build import build_v8_2_graph


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--docs',default=str(ROOT/'data/research_corpus'))
    p.add_argument('--base-graph',default=str(ROOT/'outputs/v6/iko_auto_five_insurers_v6.ttl'))
    p.add_argument('--out',default=str(ROOT/'outputs/v8_2/iko_auto_extended_v8_2.ttl'))
    args=p.parse_args()
    print(json.dumps(build_v8_2_graph(args.docs,args.out,base_graph=args.base_graph),indent=2,ensure_ascii=False))
if __name__=='__main__':main()
