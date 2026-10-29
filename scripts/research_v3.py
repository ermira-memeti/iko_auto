"""Paper A V3 CLI: inventory, pool, agreement, run, and comparison.

No scientific results are bundled; use synthetic demo solely to validate code.
"""
import argparse
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import build_pipeline
from src.embeddings import DEFAULT_EMBEDDER
from src.research_eval import (METHODS, questions_from, read_labels, read_rater_labels,
    rater_agreement, method_runs, candidate_pool_rows, write_csv, score_runs,
    paired_bootstrap, save_json, corpus_manifest, snapshot_chunks, category_summary, factorial_ablation)

DEMO = ROOT / "data" / "demo_auto_graph"
DEMO_GRAPH = ROOT / "ontology" / "instances" / "iko_auto_demo_v2.ttl"


def arguments():
    p = argparse.ArgumentParser(description="IKO-Auto V3: reproducible retrieval evaluation")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("inventory", "pool", "evaluate"):
        s = sub.add_parser(name)
        s.add_argument("--docs", default=str(DEMO))
        s.add_argument("--out", default=str(ROOT / "outputs" / f"v3_{name}"))
        s.add_argument("--chunk-words", type=int, default=170)
        s.add_argument("--overlap-words", type=int, default=45)
        s.add_argument("--model", default=DEFAULT_EMBEDDER)
        s.add_argument("--graph", default="", help="Optional compatible instance RDF graph; explicit for your own corpus")
        if name != "inventory":
            s.add_argument("--questions", required=True, help="JSONL with question_id, question, category, split")
            s.add_argument("--methods", nargs="+", choices=sorted(METHODS), default=["bm25", "bm25_synonyms", "bm25_relations", "bm25_full"])
            s.add_argument("--top-k", type=int, default=5)
            s.add_argument("--pool-size", type=int, default=50)
            s.add_argument("--alpha", type=float, default=0.6)
        if name == "evaluate":
            s.add_argument("--qrels", required=True, help="ADJUDICATED CSV, one rating 0/1/2 per question x chunk")
            s.add_argument("--allow-incomplete", action="store_true", help="Explicitly exclude queries with unjudged hits; comparisons use shared complete subset")
            s.add_argument("--compare-to", default="bm25", choices=sorted(METHODS))
            s.add_argument("--bootstrap-reps", type=int, default=1000)
            s.add_argument("--seed", type=int, default=42)
    a = sub.add_parser("agreement")
    a.add_argument("--ratings", required=True, help="Combined independent CSV: question_id,chunk_id,annotator_id,relevance")
    a.add_argument("--annotators", nargs=2, required=True)
    a.add_argument("--out", default=str(ROOT / "outputs" / "v3_agreement.json"))
    return p.parse_args()


def main():
    a = arguments()
    if a.command == "agreement":
        report = rater_agreement(read_rater_labels(a.ratings), tuple(a.annotators))
        save_json(a.out, report)
        print(json.dumps({k: v for k, v in report.items() if k != "disagreements"}, indent=2))
        print("Full disagreement list:", a.out)
        return
    docs = Path(a.docs).resolve()
    graph = str(Path(a.graph).resolve()) if a.graph else None
    if graph is not None and graph == str(DEMO_GRAPH.resolve()) and docs != DEMO.resolve():
        raise ValueError("Bundled synthetic RDF graph cannot be used for a different corpus")
    if graph is None and docs == DEMO.resolve() and a.command != "inventory":
        if any(name in ("bm25_graph", "bm25_graph_full", "hybrid_graph", "hybrid_graph_full") for name in a.methods):
            raise ValueError("Graph mode requires --graph ontology/instances/iko_auto_demo_v2.ttl for the demo")
    retriever = build_pipeline(docs, a.chunk_words, a.overlap_words, a.model, graph_file=graph)
    root = Path(a.out)
    root.mkdir(parents=True, exist_ok=True)
    write_csv(root / "document_inventory.csv", corpus_manifest(docs, retriever))
    write_csv(root / "chunk_inventory.csv", snapshot_chunks(retriever))
    if a.command == "inventory":
        print("Indexed", len(retriever.chunks), "chunks; saved inventories to", root)
        return
    questions = questions_from(a.questions)
    runs = method_runs(retriever, questions, a.methods, a.top_k, a.alpha, a.pool_size)
    save_json(root / "runs.json", runs)
    pool = candidate_pool_rows(questions, runs, retriever.chunks)
    write_csv(root / "annotation_pool.csv", pool,
              ["question_id", "question", "category", "split", "chunk_id", "source_path", "page",
               "start_word", "end_word", "text", "retrieved_by", "relevance", "evidence_quote", "notes"])
    blinded_cols = ["question_id", "question", "category", "split", "chunk_id", "source_path",
                    "page", "start_word", "end_word", "text", "relevance", "evidence_quote", "notes", "annotator_id"]
    write_csv(root / "annotation_blinded_FOR_EACH_RATER.csv", pool, blinded_cols)
    def file_sha256(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    versions = {}
    for dependency in ("rank-bm25", "rdflib", "pypdf", "sentence-transformers", "faiss-cpu", "streamlit"):
        try:
            versions[dependency] = version(dependency)
        except PackageNotFoundError:
            versions[dependency] = "not-installed"
    config = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "package_versions": versions,
              "questions_sha256": file_sha256(a.questions),
              "graph_sha256": file_sha256(graph) if graph else None, "python": platform.python_version(),
              "docs": str(docs), "graph": graph, "questions": str(Path(a.questions).resolve()),
              "methods": a.methods, "k": a.top_k, "pool_size": a.pool_size,
              "chunk_words": a.chunk_words, "overlap_words": a.overlap_words,
              "model": a.model, "alpha": a.alpha, "questions_count": len(questions),
              "chunks_count": len(retriever.chunks),
              "synthetic_demonstration": docs == DEMO.resolve(),
              "no_owl_entailment": True,
              "notes": "BM25 uses rank_bm25 when installed and corpus size >=5; otherwise builtin BM25. Dense/hybrid require ML dependencies. Run --help for all options."}
    save_json(root / "run_config.json", config)
    if a.command == "pool":
        print("Pool rows:", len(pool), "across", len(questions), "questions and", len(a.methods), "methods.")
        print("Annotate copied annotation_pool.csv independently; DO NOT label in shared file.")
        print("Saved to", root)
        return
    qrels = read_labels(a.qrels)
    config["qrels_sha256"] = file_sha256(a.qrels)
    config["qrels"] = str(Path(a.qrels).resolve())
    save_json(root / "run_config.json", config)
    result = score_runs(questions, runs, qrels, a.top_k, strict=not a.allow_incomplete,
                        corpus_ids={c.chunk_id for c in retriever.chunks})
    report = {"configuration": config, **result}
    report["by_category"] = category_summary(result)
    report["factorial_ablation"] = {split: factorial_ablation(result, split) for split in ("dev", "test")}
    report["comparisons"] = []
    for method in a.methods:
        if method == a.compare_to:
            continue
        for split in ("dev", "test"):
            for metric in ("precision_at_k", "ndcg_at_k"):
                try:
                    report["comparisons"].append(paired_bootstrap(result, a.compare_to, method, split,
                                                                   metric, a.bootstrap_reps, a.seed))
                except ValueError:
                    pass
    save_json(root / "results.json", report)
    write_csv(root / "by_category.csv", report["by_category"], ["method", "split", "category", "n_questions", "hit_at_k", "precision_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k"])
    write_csv(root / "per_question.csv", result["details"])
    write_csv(root / "summary.csv", result["summary"], ["method", "split", "n_questions", "hit_at_k",
             "precision_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k", "ndcg_basis"])
    print("\nSYNTHETIC CODE CHECK - NOT PUBLICATION RESULTS" if config["synthetic_demonstration"] else "\nEVALUATION OUTPUT - REVIEW ANNOTATION AND PROVENANCE BEFORE REPORTING")
    print(json.dumps(result["summary"], indent=2))
    print("Saved to", root)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, RuntimeError, ImportError) as error:
        print("ERROR:", error, file=sys.stderr)
        raise SystemExit(2)
