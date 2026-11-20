"""V3 reproducible *retrieval-only* research evaluation.

Strict pooling: a question/method is only scored when EVERY retrieved top-k
passage has an adjudicated relevance label. Unjudged is NOT negative.
Recall requires corpus-exhaustive judged positives (explicitly declared).
This module intentionally excludes LLM answer-quality metrics.
"""
from __future__ import annotations
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

METHODS = {
    "bm25": ("bm25", "none"),
    "dense": ("dense", "none"),
    "hybrid": ("hybrid", "none"),
    "bm25_synonyms": ("bm25", "synonyms"),
    "bm25_relations": ("bm25", "relations"),
    "bm25_full": ("bm25", "full"),
    "bm25_graph": ("bm25", "graph"),
    "bm25_graph_full": ("bm25", "graph_full"),
    "hybrid_graph": ("hybrid", "graph"),
    "hybrid_graph_full": ("hybrid", "graph_full"),
    # V5 controlled metadata and document-heading interventions, evaluated
    # against unchanged global corpus and original BM25 index/IDF.
    "bm25_metadata": ("bm25", "none"),
    "bm25_metadata_section": ("bm25", "none"),
    "bm25_metadata_graph": ("bm25", "graph"),
    # V8.1: separate experimental intervention; original graph modes unchanged.
    "bm25_metadata_graph_fallback": ("bm25", "graph"),
    # V8.2 additive SOURCE-VERIFIED draft graph, NOT a replacement of V6 baselines.
    "bm25_metadata_graph_v8_2": ("bm25", "graph"),
    # V8.3: eighth method; explicit concept/insurer gate, V6 otherwise.
    "bm25_metadata_graph_intent_v8_3": ("bm25", "graph"),
}
GRAPH_MODES = {key for key, (_, mode) in METHODS.items() if mode.startswith("graph")}
ML_MODES = {key for key, (method, _) in METHODS.items() if method in ("dense", "hybrid")}
LABELS = {0, 1, 2}  # 0 not relevant; 1 partially; 2 directly sufficient


def read_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def questions_from(path: str | Path) -> list[dict]:
    rows = read_jsonl(path)
    if not rows:
        raise ValueError("Question set is empty")
    seen = set()
    for i, row in enumerate(rows, start=1):
        qid = str(row.get("question_id", "")).strip()
        if not qid or qid in seen or not str(row.get("question", "")).strip():
            raise ValueError(f"Question row {i}: require unique question_id and nonempty question")
        seen.add(qid)
        if str(row.get("split", "")).strip() not in {"dev", "test"}:
            raise ValueError(f"Question {qid}: split must be dev or test")
        if not str(row.get("category", "")).strip():
            raise ValueError(f"Question {qid}: category is required")
        if not isinstance(row.get("gold_exhaustive", False), bool):
            raise ValueError(f"Question {qid}: gold_exhaustive must be boolean")
    return rows


def read_labels(path: str | Path, field: str = "relevance") -> dict[tuple[str, str], int]:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"No relevance judgments in {path}")
    result = {}
    for n, row in enumerate(rows, 2):
        key = (row.get("question_id", "").strip(), row.get("chunk_id", "").strip())
        raw = row.get(field, "").strip()
        if not all(key) or raw not in {"0", "1", "2"}:
            raise ValueError(f"{path} line {n}: require question_id, chunk_id and relevance 0/1/2")
        if key in result:
            raise ValueError(f"Duplicate judgment {key}")
        result[key] = int(raw)
    return result


def read_rater_labels(path: str | Path) -> dict[tuple[str, str, str], int]:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    result = {}
    for n, row in enumerate(rows, 2):
        key = (row.get("question_id", "").strip(), row.get("chunk_id", "").strip(), row.get("annotator_id", "").strip())
        value = row.get("relevance", "").strip()
        if not all(key) or value not in {"0", "1", "2"}:
            raise ValueError(f"Line {n}: require question_id, chunk_id, annotator_id, relevance 0/1/2")
        if key in result:
            raise ValueError(f"Duplicate rater row: {key}")
        result[key] = int(value)
    return result


def cohen_kappa(a: list[int], b: list[int]) -> float | None:
    if len(a) != len(b) or not a:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / len(a)
    ca, cb = Counter(a), Counter(b)
    chance = sum(ca[c] * cb[c] for c in LABELS) / len(a)**2
    return (observed - chance) / (1 - chance) if chance < 1 else (1.0 if observed == 1 else None)


def rater_agreement(raters: dict[tuple[str, str, str], int], ids: tuple[str, str]) -> dict:
    left = {(q, c): value for (q, c, a), value in raters.items() if a == ids[0]}
    right = {(q, c): value for (q, c, a), value in raters.items() if a == ids[1]}
    common = sorted(left.keys() & right.keys())
    if not common:
        raise ValueError("No overlapping ratings for the requested annotator IDs")
    a = [left[key] for key in common]
    b = [right[key] for key in common]
    return {"annotators": list(ids), "n_paired": len(common),
            "n_agree": sum(x == y for x, y in zip(a, b)),
            "percent_agreement": sum(x == y for x, y in zip(a, b)) / len(common),
            "cohen_kappa_unweighted": cohen_kappa(a, b),
            "n_disagree": sum(x != y for x, y in zip(a, b)),
            "unmatched_ratings": len(left.keys() ^ right.keys()),
            "disagreements": [{"question_id": q, "chunk_id": c,
                               ids[0]: left[(q, c)], ids[1]: right[(q, c)]}
                              for q, c in common if left[(q, c)] != right[(q, c)]]}


def method_runs(retriever, questions: list[dict], methods: list[str], k: int,
                alpha: float = 0.6, pool_size: int = 50,
                fallback_audit: list[dict] | None = None,
                enhanced_graph_index=None, intent_audit: list[dict] | None = None) -> dict:
    if k < 1 or pool_size < k:
        raise ValueError("Require 1 <= k <= pool_size")
    bad = set(methods) - set(METHODS)
    if bad:
        raise ValueError(f"Unknown method(s): {sorted(bad)}")
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("Provide distinct retrieval methods")
    if set(methods) & GRAPH_MODES and retriever.graph_index is None:
        raise ValueError("Graph methods require a source-compatible --graph RDF file. No demo graph is applied to unrelated documents.")
    if ({"bm25_metadata_graph_v8_2", "bm25_metadata_graph_intent_v8_3"} & set(methods)) and enhanced_graph_index is None:
        raise ValueError("V8.2 enhanced graph method requires the SOURCE-VERIFIED V8.2 RDF graph")
    # Graph mode may set retriever.last_graph_plan; record paths per search before the next query.
    runs = {}
    for method in methods:
        retrieval, expansion = METHODS[method]
        runs[method] = {}
        for item in questions:
            scoped_sources = None
            section_boost = False
            if method in {"bm25_metadata", "bm25_metadata_section", "bm25_metadata_graph",
                          "bm25_metadata_graph_fallback", "bm25_metadata_graph_v8_2",
                          "bm25_metadata_graph_intent_v8_3"}:
                from .policy_catalog import allowed_sources, INSURER_ALIASES
                named = str(item.get("insurer", "")).strip()
                if named not in INSURER_ALIASES:
                    raise ValueError(f"{item['question_id']}: metadata methods need a registered insurer field "
                                     f"(one of {list(INSURER_ALIASES)}), not {named!r}")
                scoped_sources = allowed_sources(retriever.chunks, named)
                if not scoped_sources:
                    raise ValueError(f"{item['question_id']}: no indexed sources for insurer {named!r}")
                section_boost = method == "bm25_metadata_section"
            # V8.2 always uses the enhanced graph; V8.3 gates its use by
            # specific question topic AND insurer. Earlier methods untouched.
            gate = None
            if method == "bm25_metadata_graph_intent_v8_3":
                from .v8_3_intent import route_intent
                gate = route_intent(item["question"], item["insurer"])
            if method == "bm25_metadata_graph_v8_2" or (gate and gate["route"] == "enhanced_v8_2"):
                original_index = retriever.graph_index
                try:
                    retriever.graph_index = enhanced_graph_index
                    hits = retriever.search(item["question"], method=retrieval, top_k=pool_size,
                                            alpha=alpha, candidate_pool=max(pool_size, 50), ontology_mode=expansion,
                                            allowed_sources=scoped_sources, section_boost=section_boost)
                finally:
                    retriever.graph_index = original_index
            else:
                hits = retriever.search(item["question"], method=retrieval, top_k=pool_size,
                                        alpha=alpha, candidate_pool=max(pool_size, 50), ontology_mode=expansion,
                                        allowed_sources=scoped_sources, section_boost=section_boost)
            if gate is not None and intent_audit is not None:
                intent_audit.append({**gate, "question_id":item["question_id"],
                                     "method":method, "n_returned":len(hits),
                                     "result_chunk_ids":[h.chunk.chunk_id for h in hits]})
            if method == "bm25_metadata_graph_fallback":
                from .policy_catalog import named_insurers
                mentioned = named_insurers(item["question"])
                # A single-policy benchmark cannot silently answer a question
                # about a different or multiple named insurers. Fail closed.
                safe_scope = not mentioned or mentioned == [item["insurer"]]
                graph_plan = retriever.last_graph_plan
                graph_strict = bool(graph_plan and graph_plan.strict_no_match)
                used_fallback = False
                if not hits and safe_scope:
                    hits = retriever.search(item["question"], method="bm25", top_k=pool_size,
                                            alpha=alpha, candidate_pool=max(pool_size, 50),
                                            ontology_mode="none", allowed_sources=scoped_sources)
                    used_fallback = True
                if fallback_audit is not None:
                    fallback_audit.append({
                        "question_id": item["question_id"],
                        "insurer": item["insurer"],
                        "method": method,
                        "fallback_used": used_fallback,
                        "reason": ("EMPTY_GRAPH_RESULT" if used_fallback else
                                   "BLOCKED_CONFLICTING_INSURER" if not safe_scope and not hits else
                                   "GRAPH_RETURNED_PASSAGES" if hits else "NO_PASSAGES"),
                        "graph_strict_no_match": graph_strict,
                        "n_returned": len(hits),
                        "result_chunk_ids": [h.chunk.chunk_id for h in hits],
                        "safe_insurer_scope": safe_scope,
                        "policy_scope": item["insurer"],
                    })
            runs[method][item["question_id"]] = [hit.chunk.chunk_id for hit in hits]
    return runs


def candidate_pool_rows(questions: list[dict], runs: dict, chunks: list) -> list[dict]:
    lookup = {chunk.chunk_id: chunk for chunk in chunks}
    result = []
    for item in questions:
        qid = item["question_id"]
        seen = {}
        for method, by_question in runs.items():
            for rank, cid in enumerate(by_question[qid], 1):
                seen.setdefault(cid, []).append(f"{method}:{rank}")
        for cid in sorted(seen):
            chunk = lookup[cid]
            result.append({"question_id": qid, "question": item["question"],
                           "category": item["category"], "split": item["split"],
                           "chunk_id": cid, "source_path": chunk.source_path,
                           "page": chunk.page or "", "start_word": chunk.start_word,
                           "end_word": chunk.end_word, "text": chunk.text,
                           "retrieved_by": ";".join(seen[cid]),
                           "relevance": "", "evidence_quote": "", "notes": ""})
    return result


def write_csv(path: str | Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    path = Path(path)
    if not rows and not columns:
        raise ValueError("Need rows or columns")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns or list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _dcg(labels: list[int]) -> float:
    return sum((2**int(rel) - 1) / math.log2(index + 2) for index, rel in enumerate(labels))


def question_metrics(ids: list[str], judgments: dict[str, int], k: int, exhaustive: bool = False) -> dict:
    if any(cid not in judgments for cid in ids[:k]):
        missing = [cid for cid in ids[:k] if cid not in judgments]
        raise ValueError(f"Unjudged retrieved evidence: {missing}. Add explicit 0/1/2 ratings; unjudged is not negative.")
    relevant = [int(judgments[cid] > 0) for cid in ids[:k]]
    gains = [judgments[cid] for cid in ids[:k]]
    first = next((i for i, hit in enumerate(relevant, 1) if hit), None)
    ideal = sorted(judgments.values(), reverse=True)[:k]
    normalizer = _dcg(ideal)
    result = {"hit_at_k": float(bool(first)), "precision_at_k": sum(relevant) / k,
              "mrr_at_k": 1 / first if first else 0.0,
              "ndcg_at_k": _dcg(gains) / normalizer if normalizer else 0.0,
              "ndcg_basis": "full_gold" if exhaustive else "pooled_judgments"}
    if exhaustive:
        n = sum(rel > 0 for rel in judgments.values())
        result["recall_at_k"] = sum(relevant) / n if n else None
    return result


def score_runs(questions: list[dict], runs: dict, adjudicated: dict[tuple[str, str], int],
               k: int, strict: bool = True, corpus_ids: set[str] | None = None) -> dict:
    if not 0 < k:
        raise ValueError("k must be positive")
    question_ids = {item["question_id"] for item in questions}
    if any(qid not in question_ids for qid, _ in adjudicated):
        raise ValueError("Judgments contain question IDs missing from questions file")
    if corpus_ids is not None and any(cid not in corpus_ids for _, cid in adjudicated):
        raise ValueError("Judgment chunk ID does not exist in indexed corpus. Regenerate and re-annotate after changing chunking.")
    details, omissions = [], []
    for method, by_q in runs.items():
        for question in questions:
            qid = question["question_id"]
            if qid not in by_q:
                raise ValueError(f"Missing run question: {method} / {qid}")
            ids = by_q[qid][:k]
            qlabels = {cid: score for (q, cid), score in adjudicated.items() if q == qid}
            missing = [cid for cid in ids if cid not in qlabels]
            if missing:
                omissions.append({"method": method, "question_id": qid, "unjudged_chunks": missing})
                continue
            exhaustive = question.get("gold_exhaustive", False)
            if exhaustive and (corpus_ids is None or set(qlabels) != corpus_ids):
                raise ValueError(f"{qid}: gold_exhaustive=true requires judgments for every indexed corpus chunk")
            metrics = question_metrics(ids, qlabels, k, exhaustive)
            details.append({"method": method, "question_id": qid,
                            "category": question["category"], "split": question["split"],
                            "retrieved_ids": ids, **metrics})
    if omissions and strict:
        raise ValueError(f"Unjudged top-{k} results: {len(omissions)} question/method pairs. "
                         "Run 'pool' and complete adjudicated qrels. First: " + str(omissions[0]))
    # Only question IDs scored for *every* requested method may contribute to comparisons.
    common = set.intersection(*(set(x["question_id"] for x in details if x["method"] == m)
                               for m in runs)) if runs else set()
    details = [row for row in details if row["question_id"] in common]
    summaries = []
    for method in runs:
        for split in ("dev", "test"):
            subset = [x for x in details if x["method"] == method and x["split"] == split]
            if not subset:
                continue
            row = {"method": method, "split": split, "n_questions": len(subset)}
            for metric in ("hit_at_k", "precision_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k"):
                vals = [x[metric] for x in subset if x.get(metric) is not None]
                row[metric] = sum(vals) / len(vals) if len(vals) == len(subset) else None
            row["ndcg_basis"] = "full_gold" if all(x["ndcg_basis"] == "full_gold" for x in subset) else "pooled_judgments"
            summaries.append(row)
    return {"k": k, "details": details, "summary": summaries, "unjudged": omissions,
            "comparable_question_ids": sorted(common), "excluded_for_missing_judgments": len(omissions)}


def paired_bootstrap(results: dict, baseline: str, challenger: str, split: str = "test",
                     metric: str = "precision_at_k", reps: int = 2000, seed: int = 42) -> dict:
    if baseline == challenger or not reps:
        raise ValueError("Choose two different methods and positive repetitions")
    if metric not in {"hit_at_k", "precision_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k"}:
        raise ValueError("Unknown metric")
    a = {r["question_id"]: r[metric] for r in results["details"] if r["method"] == baseline and r["split"] == split}
    b = {r["question_id"]: r[metric] for r in results["details"] if r["method"] == challenger and r["split"] == split}
    keys = sorted(a.keys() & b.keys())
    if len(keys) < 2 or any(a[x] is None or b[x] is None for x in keys):
        raise ValueError("Need >=2 paired questions with defined metrics on the same split")
    deltas = [b[x] - a[x] for x in keys]
    rng = random.Random(seed)
    draws = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas) for _ in range(reps))
    def quantile(p):
        at = p * (len(draws) - 1)
        low = math.floor(at)
        high = math.ceil(at)
        return draws[low] * (high - at) + draws[high] * (at - low) if high > low else draws[low]
    # Paired random sign-flip, two-sided Monte Carlo test of mean delta = 0.
    observed = abs(sum(deltas) / len(deltas))
    large = sum(abs(sum(d * (1 if rng.random() < 0.5 else -1) for d in deltas) / len(deltas))
                >= observed - 1e-12 for _ in range(reps))
    return {"baseline": baseline, "challenger": challenger, "split": split, "metric": metric,
            "n_paired": len(keys), "mean_difference": sum(deltas) / len(deltas),
            "bootstrap_95ci": [quantile(.025), quantile(.975)],
            "paired_signflip_mc_p_two_sided": (large + 1) / (reps + 1),
            "repetitions": reps, "seed": seed,
            "caveat": "Exploratory paired question-level resampling; does not correct for multiple comparisons or insurer clustering."}


def corpus_manifest(doc_folder: str | Path, retriever) -> list[dict]:
    root = Path(doc_folder).resolve()
    chunks_by_source: dict[str, list] = defaultdict(list)
    for chunk in retriever.chunks:
        chunks_by_source[chunk.source_path].append(chunk)
    result = []
    for name, chunks in sorted(chunks_by_source.items()):
        path = root / name
        result.append({"document_id": name, "relative_file": name,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "indexed_chunks": len(chunks), "insurer": "", "policy_id": "",
                       "policy_version": "", "jurisdiction": "", "source_url": "",
                       "publication_date": "", "access_date": "", "license_or_permission": "",
                       "document_type": "", "dataset_split": "", "notes": ""})
    return result


def snapshot_chunks(retriever) -> list[dict]:
    return [{"chunk_id": c.chunk_id, "document_id": c.doc_id, "source_path": c.source_path,
             "page": c.page or "", "start_word": c.start_word, "end_word": c.end_word,
             "text": c.text} for c in retriever.chunks]


def save_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def category_summary(results: dict) -> list[dict]:
    """Macro-mean per category and split; descriptive, not inferential."""
    grouped = defaultdict(list)
    for row in results["details"]:
        grouped[(row["method"], row["split"], row["category"])].append(row)
    out = []
    for (method, split, category), rows in sorted(grouped.items()):
        item = {"method": method, "split": split, "category": category, "n_questions": len(rows)}
        for name in ("hit_at_k", "precision_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k"):
            vals = [row.get(name) for row in rows]
            item[name] = sum(vals) / len(vals) if vals and all(v is not None for v in vals) else None
        out.append(item)
    return out


def factorial_ablation(results: dict, split: str = "test", metric: str = "ndcg_at_k") -> dict | None:
    """2x2 ablation: no expansion, synonym only, RDF-graph only, both.

    Contrast is descriptive: it is not a causal estimate with this prototype.
    """
    required = ("bm25", "bm25_synonyms", "bm25_graph", "bm25_graph_full")
    values = {(row["method"], row["question_id"]): row[metric]
              for row in results["details"] if row["split"] == split and row["method"] in required}
    qs = set.intersection(*(set(qid for method, qid in values if method == m) for m in required)) if values else set()
    if not qs or any(values.get((m, q)) is None for m in required for q in qs):
        return None
    means = {m: sum(values[(m, q)] for q in qs) / len(qs) for m in required}
    return {"split": split, "metric": metric, "n_paired": len(qs), "cells": means,
            "synonym_only_minus_baseline": means["bm25_synonyms"] - means["bm25"],
            "graph_only_minus_baseline": means["bm25_graph"] - means["bm25"],
            "both_minus_baseline": means["bm25_graph_full"] - means["bm25"],
            "interaction_difference_of_differences": means["bm25_graph_full"] - means["bm25_graph"] - means["bm25_synonyms"] + means["bm25"],
            "caveat": "Descriptive V3 ablation; graph mode uses instance-path evidence weights and policy scope; this is not OWL entailment or a causal effect."}
