"""Build RDF/TTL graph from user-verified annotated policy facts and sources."""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.graph_builder import build_graph_from_annotations, save_graph

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", default=str(ROOT / "ontology/instances/demo_annotations.json"))
    parser.add_argument("--docs", default=str(ROOT / "data/demo_auto_graph"))
    parser.add_argument("--schema", default=str(ROOT / "ontology/iko_auto_v2.ttl"))
    parser.add_argument("--output", default=str(ROOT / "ontology/instances/iko_auto_demo_v2.ttl"))
    args = parser.parse_args()
    g = build_graph_from_annotations(args.facts, args.docs, args.schema)
    dest = save_graph(g, args.output)
    print(f"Built {len(g)} RDF triples at {dest}")
    print("Quotations verified verbatim against source files. No logical reasoner validation performed.")

if __name__ == "__main__":
    main()
