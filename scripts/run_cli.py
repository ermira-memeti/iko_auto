"""A working no-install BM25 demo; ML retrieval is optional."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import build_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Search provided insurance documents")
    parser.add_argument("--docs", default=str(ROOT / "data" / "demo_auto"))
    parser.add_argument("--query", default="What exclusions apply to the auto policy?")
    parser.add_argument("--method", choices=["bm25", "dense", "hybrid"], default="bm25")
    parser.add_argument("--ontology-mode", choices=["none", "synonyms", "relations", "full", "graph", "graph_full"], default="none")
    parser.add_argument("--graph-file", default=None, help="RDF Turtle facts; graph modes need evidence for selected documents")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--alpha", type=float, default=0.6, help="Hybrid dense branch weight")
    parser.add_argument("--chunk-words", type=int, default=170)
    parser.add_argument("--overlap-words", type=int, default=45)
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--output", help="Optional JSON results path")
    args = parser.parse_args()
    graph_file = args.graph_file
    demo_folder = (ROOT / "data" / "demo_auto_graph").resolve()
    if args.ontology_mode in {"graph", "graph_full"} and not graph_file and Path(args.docs).resolve() == demo_folder:
        graph_file = str(ROOT / "ontology" / "instances" / "iko_auto_demo_v2.ttl")
    retriever = build_pipeline(args.docs, chunk_words=args.chunk_words,
                               overlap_words=args.overlap_words, embedding_model_name=args.model,
                               graph_file=graph_file)
    hits = retriever.search(args.query, method=args.method, top_k=args.top_k, alpha=args.alpha, ontology_mode=args.ontology_mode)
    output = {"question": args.query, "method": args.method, "ontology_mode": args.ontology_mode, "backend": retriever.bm25_backend,
              "n_chunks": len(retriever.chunks), "graph_file": graph_file,
              "graph_warnings": retriever.last_graph_plan.warnings if retriever.last_graph_plan else [], "results": [hit.as_dict() for hit in hits],
              "note": "Demo retrieval only; no evidence annotations or answer accuracy validation."}
    rendered = json.dumps(output, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
