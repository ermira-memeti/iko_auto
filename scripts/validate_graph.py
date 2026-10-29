"""Check quoted evidence, relationships, and SPARQL competency queries."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import build_pipeline
from src.graph_validation import validate_graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", default=str(ROOT / "data/demo_auto_graph"))
    parser.add_argument("--graph", default=str(ROOT / "ontology/instances/iko_auto_demo_v2.ttl"))
    parser.add_argument("--chunk-words", type=int, default=170)
    parser.add_argument("--overlap-words", type=int, default=45)
    args = parser.parse_args()
    retriever = build_pipeline(args.docs, chunk_words=args.chunk_words, overlap_words=args.overlap_words,
                               graph_file=args.graph)
    results = validate_graph(retriever.graph_index)
    print(json.dumps(results, indent=2))
    if not results["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
