"""IKO-Auto V4: real corpus audit, independent annotation and frozen protocols."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.real_corpus import audit_corpus, read_registry, registry_template, validate_registry
from src.annotation_workflow import (create_reviewer_sheets, merge_independent_ratings,
                                     finalize_human_adjudication)
from src.research_eval import write_csv
from src.study_freeze import create_freeze, verify_freeze, verify_evaluation_config


def parse_args():
    p = argparse.ArgumentParser(description="IKO-Auto V4 reproducible corpus/annotation workflow")
    subs = p.add_subparsers(dest="command", required=True)
    s = subs.add_parser("audit", help="Inspect PDFs, source hashes and extractability; export source registry template")
    s.add_argument("--docs", required=True)
    s.add_argument("--out", default="outputs/v4_corpus_audit")
    s.add_argument("--chunk-words", type=int, default=170)
    s.add_argument("--overlap-words", type=int, default=45)
    s.add_argument("--registry", help="Filled source register to validate (instead of new empty template)")
    s.add_argument("--mode", choices=["demo", "real"], default="real")
    s = subs.add_parser("prepare-raters", help="Create two separate BLINDED rating sheets from V3 pool")
    s.add_argument("--pool", required=True)
    s.add_argument("--raters", nargs=2, default=["reviewer_A", "reviewer_B"])
    s.add_argument("--out", default="outputs/v4_reviewer_sheets")
    s = subs.add_parser("merge-raters", help="Validate complete independent ratings; calculate kappa; produce blank HUMAN adjudication worklist")
    s.add_argument("--pool", required=True)
    s.add_argument("--a", required=True)
    s.add_argument("--b", required=True)
    s.add_argument("--out", default="outputs/v4_human_adjudication")
    s = subs.add_parser("finalize", help="Convert completed HUMAN adjudication decisions to qrels")
    s.add_argument("--worklist", required=True)
    s.add_argument("--pool", required=True)
    s.add_argument("--out", default="outputs/v4_adjudicated_qrels.csv")
    s = subs.add_parser("freeze", help="Create non-overwriting hashed experiment manifest")
    s.add_argument("--docs", required=True)
    s.add_argument("--registry", required=True)
    s.add_argument("--questions", required=True)
    s.add_argument("--qrels", required=True)
    s.add_argument("--graph", default="")
    s.add_argument("--reviewer-a")
    s.add_argument("--reviewer-b")
    s.add_argument("--adjudication")
    s.add_argument("--mode", choices=["demo", "real"], default="real")
    s.add_argument("--chunk-words", type=int, default=170)
    s.add_argument("--overlap-words", type=int, default=45)
    s.add_argument("--primary-metric", choices=["precision_at_k", "hit_at_k", "mrr_at_k", "ndcg_at_k"], default="ndcg_at_k")
    s.add_argument("--top-k", type=int, default=5)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--pool-size", type=int, default=50)
    s.add_argument("--alpha", type=float, default=0.6)
    s.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    s.add_argument("--methods", nargs="+", default=["bm25", "bm25_synonyms"])
    s.add_argument("--out", default="outputs/v4_study_freeze.json")
    s = subs.add_parser("verify-freeze", help="Recompute file hashes and reject changed sources/judgments")
    s.add_argument("--freeze", required=True)
    s = subs.add_parser("verify-run", help="Compare V3 retrieval run_config.json against V4 frozen study")
    s.add_argument("--freeze", required=True)
    s.add_argument("--run-config", required=True)
    return p.parse_args()


def main():
    a = parse_args()
    if a.command == "audit":
        audit = audit_corpus(a.docs, a.chunk_words, a.overlap_words)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        if a.registry:
            result = validate_registry(audit, read_registry(a.registry), a.mode == "real")
        else:
            result = {"passed": False, "needs_filled_registry": True, "warning": "New registry template has EMPTY insurer/version/rights fields"}
            template = out / "source_registry_FILL_AND_VALIDATE.csv"
            if template.exists():
                raise FileExistsError(f"Registry template exists: {template}; choose another --out folder")
            write_csv(template, registry_template(audit), list(registry_template(audit)[0]))
        payload = {"files": audit["n_files"], "chunks": audit["n_chunks"],
                   "files_needing_review": audit["n_review_required"],
                   "warnings": audit["warnings"], "registry_check": result}
        (out / "corpus_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    elif a.command == "prepare-raters":
        payload = create_reviewer_sheets(a.pool, a.out, tuple(a.raters))
    elif a.command == "merge-raters":
        payload = merge_independent_ratings(a.pool, a.a, a.b, a.out)
        (Path(a.out) / "independent_agreement.json").write_text(json.dumps(payload["agreement_report"], indent=2), encoding="utf-8")
        payload.pop("agreement_report")
    elif a.command == "finalize":
        payload = finalize_human_adjudication(a.worklist, a.out, a.pool)
    elif a.command == "freeze":
        payload = create_freeze(a.docs, a.registry, a.questions, a.qrels, a.out,
                                mode=a.mode, chunk_words=a.chunk_words, overlap_words=a.overlap_words,
                                graph=a.graph or None, reviewer_a=a.reviewer_a,
                                reviewer_b=a.reviewer_b, adjudication=a.adjudication,
                                primary_metric=a.primary_metric, k=a.top_k, seed=a.seed,
                                methods=a.methods, pool_size=a.pool_size, alpha=a.alpha,
                                embedding_model=a.model)
        payload = {"saved": a.out, "mode": payload["mode"], "files_hashed": len(payload["file_sha256"])}
    elif a.command == "verify-run":
        payload = verify_evaluation_config(a.freeze, a.run_config)
        print(json.dumps(payload, indent=2))
        if not payload["passed"]:
            raise SystemExit(2)
        return
    elif a.command == "verify-freeze":
        payload = verify_freeze(a.freeze)
        print(json.dumps(payload, indent=2))
        if not payload["passed"]:
            raise SystemExit(2)
        return
    else:
        raise RuntimeError(a.command)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print("V4 workflow error:", exc, file=sys.stderr)
        raise SystemExit(1)
