"""V4 tamper-evident experiment manifest; does not certify academic validity.

Records SHA-256 hashes and frozen parameters. Verification detects edits before
results are interpreted, but cannot prove annotator independence or source rights.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .real_corpus import audit_corpus, read_registry, validate_registry
from .research_eval import questions_from, read_labels


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_question_families(questions: list[dict], registry: list[dict], real_mode: bool) -> list[str]:
    if not real_mode:
        return []
    problems = []
    actual = {(r.get("insurer", "").strip().casefold(), r.get("policy_family", "").strip().casefold())
              for r in registry}
    splits = {}
    for q in questions:
        qid = q["question_id"]
        group = (str(q.get("insurer", "")).strip().casefold(),
                 str(q.get("policy_family", "")).strip().casefold())
        if not all(group):
            problems.append(f"{qid}: insurer and policy_family required to audit question leakage")
        elif group not in actual:
            problems.append(f"{qid}: question policy family not registered in corpus")
        else:
            splits.setdefault(group, set()).add(q["split"])
    for group, split_set in sorted(splits.items()):
        if len(split_set) > 1:
            problems.append(f"Question split leakage: {group} used in dev and test")
    if {q["split"] for q in questions} != {"dev", "test"}:
        problems.append("Real study must include both dev and held-out test questions")
    return problems


def create_freeze(docs: str | Path, registry_file: str | Path, questions_file: str | Path,
                  qrels_file: str | Path, output_json: str | Path, *, mode: str = "demo",
                  chunk_words: int = 170, overlap_words: int = 45,
                  graph: str | Path | None = None,
                  reviewer_a: str | Path | None = None, reviewer_b: str | Path | None = None,
                  adjudication: str | Path | None = None,
                  primary_metric: str = "ndcg_at_k", k: int = 5, seed: int = 42,
                  methods: list[str] | None = None, pool_size: int = 50,
                  alpha: float = 0.6, embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict:
    from .research_eval import METHODS
    if mode not in {"demo", "real"}:
        raise ValueError("mode must be demo or real")
    if primary_metric not in {"precision_at_k", "hit_at_k", "mrr_at_k", "ndcg_at_k"}:
        raise ValueError("Choose a supported primary retrieval metric")
    if chunk_words < 1 or overlap_words < 0 or overlap_words >= chunk_words or k < 1 or pool_size < k or not 0 <= alpha <= 1:
        raise ValueError("Invalid chunking or top_k")
    methods = methods or ["bm25", "bm25_synonyms", "bm25_graph", "bm25_graph_full"]
    if not methods or set(methods) - set(METHODS):
        raise ValueError("Unknown methods")
    if any(m in {"bm25_graph", "bm25_graph_full", "hybrid_graph", "hybrid_graph_full"} for m in methods) and not graph:
        raise ValueError("Graph methods need a source-matched RDF graph file; choose non-graph methods otherwise")
    audit = audit_corpus(docs, chunk_words, overlap_words)
    registry = read_registry(registry_file)
    check = validate_registry(audit, registry, real_mode=mode == "real")
    if not check["passed"]:
        raise ValueError("Registry validation failed: " + "; ".join(check["errors"][:8]))
    questions = questions_from(questions_file)
    leakage = validate_question_families(questions, registry, real_mode=mode == "real")
    if leakage:
        raise ValueError("Question leakage/metadata errors: " + "; ".join(leakage[:8]))
    labels = read_labels(qrels_file)
    from .chunking import chunk_documents
    from .data_ingest import load_documents
    actual_ids = {c.chunk_id for c in chunk_documents(load_documents(docs), chunk_words, overlap_words)}
    unexpected = {chunk_id for _, chunk_id in labels if chunk_id not in actual_ids}
    if unexpected:
        raise ValueError("Qrels contain passage IDs missing from the frozen corpus/chunking: " + str(sorted(unexpected)[:3]))
    if not all(q["question_id"] in {qid for qid, _ in labels} for q in questions):
        raise ValueError("At least one question has no adjudicated judgments")
    paths = {"registry": Path(registry_file), "questions": Path(questions_file), "qrels": Path(qrels_file)}
    if graph:
        if mode == "real" and Path(graph).name == "iko_auto_demo_v2.ttl":
            raise ValueError("Synthetic V2 demonstration graph cannot be used to freeze a real study")
        paths["graph"] = Path(graph)
    if mode == "real":
        if not all((reviewer_a, reviewer_b, adjudication)):
            raise ValueError("Real freeze requires both original completed reviewer files and human adjudication worklist")
        paths.update(reviewer_a=Path(reviewer_a), reviewer_b=Path(reviewer_b), adjudication=Path(adjudication))
        from .annotation_workflow import _keys, _read_csv
        rows = _keys(_read_csv(adjudication), "Adjudication sheet")
        if set(rows) != set(labels):
            raise ValueError("Final qrels do not cover the entire adjudication sheet")
        for key, row in rows.items():
            if row.get("final_relevance", "").strip() != str(labels[key]) or not row.get("adjudicator_id", "").strip():
                raise ValueError(f"Qrels differ from human adjudication or lack adjudicator: {key}")
        rater_ids = []
        from .annotation_workflow import _verify_rating
        for which, suffix in ((reviewer_a, "a"), (reviewer_b, "b")):
            ratings = _keys(_read_csv(which), "Reviewer sheet")
            if set(ratings) != set(rows):
                raise ValueError("Reviewer file does not cover all adjudicated question-passage pairs")
            ids = {record.get("annotator_id", "").strip() for record in ratings.values()}
            if len(ids) != 1 or not next(iter(ids)):
                raise ValueError("Reviewer ID is missing or inconsistent")
            rid = next(iter(ids))
            rater_ids.append(rid)
            for key, row in ratings.items():
                _verify_rating(row, 0, rid)
                record = rows[key]
                if record.get(f"rater_{suffix}_id", "") != rid or record.get(f"rater_{suffix}_label", "") != row["relevance"]:
                    raise ValueError(f"Reviewer files and human worklist do not agree for {key}")
                if record.get("text", "") != row.get("text", ""):
                    raise ValueError(f"Reviewed passage altered for {key}")
        if rater_ids[0] == rater_ids[1]:
            raise ValueError("Reviewer identities are the same")
    for key, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Required {key} file is missing: {path}")
    # The synthetic demonstration can never be promoted by a mode flag.
    if mode == "real" and audit["synthetic_demo"]:
        raise ValueError("The included synthetic corpus is not real research data")
    sources = {str(Path(audit["root"]) / row["relative_file"]): row["sha256"] for row in audit["files"]}
    files = {str(path.resolve()): sha256(path) for path in paths.values()}
    files.update(sources)
    manifest = {
        "schema": "iko-auto-v4-freeze-1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode, "real_metadata_checked_not_independently_verified": mode == "real",
        "documents": audit["n_files"], "chunks": audit["n_chunks"],
        "questions": len(questions), "judgments": len(labels),
        "corpus_dir": audit["root"], "file_sha256": files,
        "parameters": {"chunk_words": chunk_words, "overlap_words": overlap_words,
                       "top_k": k, "pool_size": pool_size, "alpha": alpha,
                       "embedding_model": embedding_model,
                       "seed": seed, "primary_metric": primary_metric, "methods": methods},
        "cautions": ["SHA-256 detects file changes, not false metadata or invalid labels.",
                     "Human independence, licensing and ontology quality require external confirmation.",
                     "Only evaluate with the frozen document set, labels and hyperparameters."]}
    target = Path(output_json)
    if target.exists():
        raise FileExistsError(f"Freeze already exists: {target}; do not overwrite a registered study")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def verify_freeze(freeze_file: str | Path) -> dict:
    payload = json.loads(Path(freeze_file).read_text(encoding="utf-8"))
    if payload.get("schema") != "iko-auto-v4-freeze-1":
        raise ValueError("Unsupported freeze manifest schema")
    failures = []
    for filename, expected in payload.get("file_sha256", {}).items():
        path = Path(filename)
        if not path.is_file():
            failures.append({"path": filename, "problem": "missing"})
        elif sha256(path) != expected:
            failures.append({"path": filename, "problem": "changed_sha256"})
    return {"passed": not failures, "n_files_checked": len(payload.get("file_sha256", {})),
            "failures": failures, "mode": payload["mode"],
            "message": "Unchanged frozen files" if not failures else "Freeze violated; do not use results until reconciled"}


def verify_evaluation_config(freeze_file: str | Path, run_config_file: str | Path) -> dict:
    """Check that V3 evaluation parameters and inputs match the V4 frozen study."""
    freeze = json.loads(Path(freeze_file).read_text(encoding="utf-8"))
    if freeze.get("schema") != "iko-auto-v4-freeze-1":
        raise ValueError("Unsupported V4 freeze manifest")
    run = json.loads(Path(run_config_file).read_text(encoding="utf-8"))
    differences = []
    params = freeze["parameters"]
    links = {"chunk_words": "chunk_words", "overlap_words": "overlap_words",
             "top_k": "k", "pool_size": "pool_size", "alpha": "alpha",
             "embedding_model": "model", "methods": "methods"}
    for frozen, evaluated in links.items():
        if params[frozen] != run.get(evaluated):
            differences.append({"field": frozen, "expected": params[frozen], "actual": run.get(evaluated)})
    file_hashes = freeze["file_sha256"]
    for field, run_key in (("questions", "questions_sha256"), ("qrels", "qrels_sha256"),
                           ("graph", "graph_sha256")):
        if field == "graph" and not run.get("graph") and not any(Path(p).suffix.lower() == ".ttl" for p in file_hashes):
            continue
        filepath = run.get(field)
        actual_hash = run.get(run_key)
        if not filepath or filepath not in file_hashes or file_hashes.get(filepath) != actual_hash:
            differences.append({"field": field, "problem": "V3 run input was not frozen or hash differs"})
    if Path(run.get("docs", "")).resolve() != Path(freeze["corpus_dir"]).resolve():
        differences.append({"field": "docs", "problem": "Different document folder"})
    if run.get("synthetic_demonstration", False) and freeze["mode"] == "real":
        differences.append({"field": "mode", "problem": "Synthetic run cannot verify against real freeze"})
    manifest_check = verify_freeze(freeze_file)
    if not manifest_check["passed"]:
        differences.append({"field": "freeze", "problem": "Frozen files changed or vanished",
                            "details": manifest_check["failures"]})
    return {"passed": not differences, "differences": differences,
            "message": "Evaluation inputs match the frozen protocol" if not differences else
                       "Evaluation differs from frozen protocol; do not report until resolved"}
