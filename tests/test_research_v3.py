"""V3 real evaluators with synthetic test fixtures, never paper results."""
import csv
import json
from pathlib import Path
import pytest
from src.pipeline import build_pipeline
from src.research_eval import (read_labels, read_rater_labels, questions_from,
    cohen_kappa, rater_agreement, question_metrics, score_runs, candidate_pool_rows,
    method_runs, paired_bootstrap, corpus_manifest, snapshot_chunks)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "demo_auto_graph"
QPATH = ROOT / "data" / "research_v3" / "demo" / "questions_demo.jsonl"
QRELS = ROOT / "data" / "research_v3" / "demo" / "adjudicated_demo_AUTHOR_ONLY.csv"


def test_demo_questions_and_gold_complete():
    qs = questions_from(QPATH)
    labels = read_labels(QRELS)
    retriever = build_pipeline(DOCS)
    assert len(qs) == 10
    assert len(labels) == len(qs) * len(retriever.chunks)
    assert len({c.chunk_id for c in retriever.chunks}) == len(retriever.chunks)
    assert all(sum(v == 2 for (qid, _), v in labels.items() if qid == q["question_id"]) == 1 for q in qs)


def test_metrics_with_grades_at_fixed_k():
    labels = {"a": 0, "b": 2, "c": 1, "d": 0}
    values = question_metrics(["a", "b", "c"], labels, k=3, exhaustive=True)
    assert values["precision_at_k"] == pytest.approx(2 / 3)
    assert values["mrr_at_k"] == pytest.approx(.5)
    assert values["recall_at_k"] == 1
    assert 0 < values["ndcg_at_k"] < 1
    assert question_metrics([], labels, 5)["precision_at_k"] == 0
    with pytest.raises(ValueError, match="Unjudged"):
        question_metrics(["unknown"], labels, 5)


def test_cohen_kappa_and_disagreements():
    assert cohen_kappa([0, 1, 2, 0], [0, 1, 2, 0]) == 1
    assert cohen_kappa([], []) is None
    ratings = {("q1", "c1", "a"): 2, ("q1", "c1", "b"): 2,
               ("q1", "c2", "a"): 0, ("q1", "c2", "b"): 1}
    r = rater_agreement(ratings, ("a", "b"))
    assert r["n_disagree"] == 1
    assert r["percent_agreement"] == .5
    assert r["disagreements"][0]["chunk_id"] == "c2"


def test_unjudged_not_silent_zero():
    qs = [{"question_id": "q1", "question": "Q", "split": "test", "category": "coverage"}]
    runs = {"bm25": {"q1": ["c1", "c2"]}}
    with pytest.raises(ValueError, match="Unjudged"):
        score_runs(qs, runs, {("q1", "c1"): 2}, 5)
    result = score_runs(qs, runs, {("q1", "c1"): 2}, 5, strict=False)
    assert result["excluded_for_missing_judgments"] == 1
    assert result["summary"] == []


def test_exhaustive_claim_is_verified():
    qs = [{"question_id": "q1", "question": "Q", "split": "test",
           "category": "coverage", "gold_exhaustive": True}]
    runs = {"bm25": {"q1": ["c1"]}}
    with pytest.raises(ValueError, match="requires judgments"):
        score_runs(qs, runs, {("q1", "c1"): 2}, 5, corpus_ids={"c1", "c2"})


def test_candidate_pool_dedupes_across_methods():
    qs = [{"question_id": "q1", "question": "Q", "split": "test", "category": "claim"}]
    retriever = build_pipeline(DOCS)
    cids = [c.chunk_id for c in retriever.chunks]
    rows = candidate_pool_rows(qs, {"bm25": {"q1": cids[:2]}, "bm25_synonyms": {"q1": cids[1:3]}}, retriever.chunks)
    assert len(rows) == 3
    assert any("bm25:2" in r["retrieved_by"] and "bm25_synonyms:1" in r["retrieved_by"] for r in rows)


def test_all_six_lightweight_method_runs_and_comparisons():
    pytest.importorskip("rdflib")
    retriever = build_pipeline(DOCS, graph_file=ROOT / "ontology" / "instances" / "iko_auto_demo_v2.ttl")
    qs = questions_from(QPATH)
    methods = ["bm25", "bm25_synonyms", "bm25_relations", "bm25_full", "bm25_graph", "bm25_graph_full"]
    runs = method_runs(retriever, qs, methods, 5, pool_size=8)
    result = score_runs(qs, runs, read_labels(QRELS), 5, corpus_ids={c.chunk_id for c in retriever.chunks})
    assert len(result["summary"]) == 12
    assert len(result["details"]) == 60
    assert result["excluded_for_missing_judgments"] == 0
    for row in result["summary"]:
        assert 0 <= row["precision_at_k"] <= 1
        assert 0 <= row["ndcg_at_k"] <= 1
        assert row["recall_at_k"] is not None
    compare = paired_bootstrap(result, "bm25", "bm25_graph", "test", reps=100, seed=5)
    assert compare["n_paired"] == 5
    assert len(compare["bootstrap_95ci"]) == 2


def test_graph_methods_require_an_explicit_graph():
    qs = questions_from(QPATH)
    retriever = build_pipeline(DOCS)
    with pytest.raises(ValueError, match="require"):
        method_runs(retriever, qs, ["bm25_graph"], 5)


def test_manifest_hashes_source_files():
    retriever = build_pipeline(DOCS)
    rows = corpus_manifest(DOCS, retriever)
    assert len(rows) == 8
    assert all(len(x["sha256"]) == 64 for x in rows)
    assert len(snapshot_chunks(retriever)) == len(retriever.chunks)


def test_question_validation(tmp_path):
    path = tmp_path / "qs.jsonl"
    path.write_text(json.dumps({"question_id":"q1","question":"Test","category":"coverage","split":"banana"}) + "\n")
    with pytest.raises(ValueError, match="split"):
        questions_from(path)


def test_duplicate_labels_are_rejected(tmp_path):
    path = tmp_path / "qrels.csv"
    path.write_text("question_id,chunk_id,relevance\nq1,c1,1\nq1,c1,2\n")
    with pytest.raises(ValueError, match="Duplicate"):
        read_labels(path)
