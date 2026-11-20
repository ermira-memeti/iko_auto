"""Retrieval-only evaluation. Requires human-verified gold chunk IDs.

Hit/Precision/MRR are reported when gold matches are available. Recall is
omitted unless annotations explicitly declare exhaustive relevance judgments.
"""
import json
from pathlib import Path


def compute_question_metrics(retrieved_ids: list[str], gold_ids: set[str], k: int = 5,
                             gold_exhaustive: bool = False) -> dict:
    if not gold_ids:
        raise ValueError("At least one verified relevant chunk ID is required")
    ids = retrieved_ids[:k]
    hits = [i for i, cid in enumerate(ids, 1) if cid in gold_ids]
    result = {"hit_at_k": float(bool(hits)), "precision_at_k": len(hits) / k,
              "mrr_at_k": (1 / hits[0] if hits else 0.0)}
    if gold_exhaustive:
        result["recall_at_k"] = len(set(ids) & gold_ids) / len(gold_ids)
    return result


def evaluate(retriever, questions_path: str | Path, method: str = "bm25", k: int = 5,
             alpha: float = 0.6) -> dict:
    rows = [json.loads(line) for line in Path(questions_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("No annotated questions found; this project does not ship made-up results.")
    details = []
    for item in rows:
        gold = set(item.get("relevant_chunk_ids", []))
        if not gold:
            raise ValueError(f"Question {item.get('question_id')} has no gold chunk IDs")
        hits = retriever.search(item["question"], method=method, top_k=k, alpha=alpha)
        retrieved = [hit.chunk.chunk_id for hit in hits]
        metrics = compute_question_metrics(retrieved, gold, k=k,
                                           gold_exhaustive=bool(item.get("gold_exhaustive", False)))
        details.append({"question_id": item["question_id"], "question": item["question"],
                        "category": item.get("category", "unspecified"),
                        "gold_ids": sorted(gold), "retrieved_ids": retrieved, **metrics})
    metrics = [key for key in ("hit_at_k", "precision_at_k", "mrr_at_k", "recall_at_k")
               if all(key in r for r in details)]
    summary = {key: round(sum(row[key] for row in details) / len(details), 6) for key in metrics}
    return {"method": method, "top_k": k, "n_questions": len(details),
            "summary": summary, "questions": details}
