"""Evaluate with externally human-annotated gold chunk IDs (none are fabricated)."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import build_pipeline
from src.evaluation import evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", default=str(ROOT / "data" / "demo_auto"))
    parser.add_argument("--questions", required=True, help="Annotated JSONL file; see data/evaluation/README.md")
    parser.add_argument("--method", choices=["bm25", "dense", "hybrid"], default="bm25")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--alpha", type=float, default=0.6)
    parser.add_argument("--out", default=str(ROOT / "outputs" / "evaluation.json"))
    args = parser.parse_args()
    retriever = build_pipeline(args.docs)
    result = evaluate(retriever, args.questions, method=args.method, k=args.top_k, alpha=args.alpha)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print("Saved", out)


if __name__ == "__main__":
    main()
