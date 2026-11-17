import json
from pathlib import Path
import pytest
from src.models import SourceDocument
from src.chunking import simple_chunk, chunk_document
from src.retrieval import InsuranceRetriever, normalize_score_map
from src.data_ingest import load_documents
from src.evaluation import compute_question_metrics, evaluate
from src.pipeline import build_pipeline

ROOT = Path(__file__).resolve().parents[1]


def test_character_chunk_overlap_is_real():
    assert simple_chunk("abcdefghij", chunk_size=6, overlap=2) == ["abcdef", "efghij"]


def test_chunk_word_overlap_and_metadata():
    doc = SourceDocument("test.txt", " ".join(f"word{i}" for i in range(11)), "test.txt")
    chunks = chunk_document(doc, chunk_words=5, overlap_words=2)
    assert len(chunks) == 3
    assert chunks[0].text.split()[-2:] == chunks[1].text.split()[:2]
    assert chunks[1].text.split()[-2:] == chunks[2].text.split()[:2]
    assert chunks[-1].end_word == 11
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_document(SourceDocument("x", "a b c", "x"), 3, 3)


def test_extract_loads_demo_auto_only():
    docs = load_documents(ROOT / "data" / "demo_auto")
    assert len(docs) == 1
    assert "auto" in docs[0].doc_id
    assert "racing" in docs[0].text.lower()


def test_bm25_search_relevant_and_empty_query():
    r = build_pipeline(ROOT / "data" / "demo_auto")
    assert len(r.chunks) >= 1
    hits = r.search("racing exclusion", method="bm25", top_k=5)
    assert hits
    assert "racing" in hits[0].chunk.text.lower()
    assert r.search("  ") == []
    with pytest.raises(ValueError):
        r.search("test", method="not_a_method")


def test_chunk_order_tie_determinism():
    docs = [SourceDocument("x", "apples and oranges", "x"), SourceDocument("y", "bananas only", "y")]
    chunks = [chunk_document(doc)[0] for doc in docs]
    r = InsuranceRetriever(chunks)
    hits = r.search("bananas", method="bm25")
    assert len(hits) == 1 and hits[0].chunk.doc_id == "y"


def test_score_normalization():
    assert normalize_score_map({1: 0.0, 2: 1.0}) == {1: 0.0, 2: 1.0}
    assert normalize_score_map({1: 0.2, 2: 0.2}) == {1: 1.0, 2: 1.0}
    assert normalize_score_map({1: 0, 2: 0}) == {1: 0, 2: 0}


def test_metrics_only_claim_recall_if_exhaustive():
    result = compute_question_metrics(["a", "b", "c"], {"b", "d"}, k=5)
    assert result == {"hit_at_k": 1, "precision_at_k": 0.2, "mrr_at_k": 0.5}
    assert compute_question_metrics(["a", "b"], {"b", "d"}, k=5, gold_exhaustive=True)["recall_at_k"] == 0.5


def test_evaluation_rejects_empty_gold(tmp_path):
    qpath = tmp_path / "questions.jsonl"
    qpath.write_text(json.dumps({"question_id": "q1", "question": "fire?", "relevant_chunk_ids": []}) + "\n")
    r = build_pipeline(ROOT / "data" / "demo_auto")
    with pytest.raises(ValueError):
        evaluate(r, qpath)


def test_pdf_page_origin(tmp_path):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    # Make an empty PDF page and ensure it is not treated as a document with extractable text.
    docdir = tmp_path / "sources"
    docdir.mkdir()
    w = PdfWriter()
    w.add_blank_page(width=400, height=600)
    with (docdir / "blank.pdf").open("wb") as fp:
        w.write(fp)
    with pytest.raises(ValueError):
        load_documents(docdir)


def test_hybrid_uses_two_branches_without_model_download():
    docs = [SourceDocument("a", "racing damage exclusion", "a"),
            SourceDocument("b", "hail storm coverage", "b")]
    chunks = [chunk_document(doc)[0] for doc in docs]
    retriever = InsuranceRetriever(chunks)
    # Controlled stub isolates hybrid-fusion logic from external model downloads.
    retriever._dense_scores = lambda _query, _n: {0: 0.20, 1: 0.95}
    hits = retriever.search("racing exclusion", method="hybrid", alpha=0.6)
    assert [h.chunk.doc_id for h in hits] == ["b", "a"]
    assert hits[0].dense_score == 0.95
    assert hits[1].bm25_score is not None
