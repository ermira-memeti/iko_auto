"""Non-empirical functional verification of RDF graph traversal and grounding."""
from pathlib import Path
import json
import pytest

rdflib = pytest.importorskip("rdflib")
from src.graph_builder import build_graph_from_annotations, save_graph
from src.graph_retrieval import GraphIndex
from src.graph_validation import validate_graph
from src.pipeline import build_pipeline

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "demo_auto_graph"
FACTS = ROOT / "ontology" / "instances" / "demo_annotations.json"
SCHEMA = ROOT / "ontology" / "iko_auto_v2.ttl"
TTL = ROOT / "ontology" / "instances" / "iko_auto_demo_v2.ttl"

@pytest.fixture(scope="module")
def retriever():
    return build_pipeline(DOCS, graph_file=TTL)


def test_builder_parses_and_verifies_all_source_quotes():
    g = build_graph_from_annotations(FACTS, DOCS, SCHEMA)
    assert len(g) >= 350
    assert len(set(g.subjects(rdflib.RDF.type, rdflib.URIRef("https://example.org/iko-auto/v2#AutoPolicy")))) == 3


def test_builder_rejects_unsupported_quote(tmp_path):
    obj = json.loads(FACTS.read_text(encoding="utf-8"))
    obj["policies"][0]["coverages"][0]["exclusions"][0]["evidence"]["quote"] = "Not in the source document at all."
    changed = tmp_path / "bad.json"
    changed.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(ValueError, match="verbatim"):
        build_graph_from_annotations(changed, DOCS, SCHEMA)


def test_graph_provenance_and_sparql(retriever):
    report = validate_graph(retriever.graph_index)
    assert report["passed"] is True
    assert report["policies"] == 3
    assert report["relationship_assertions"] >= 15
    assert report["source_passages"] >= 14
    for f in ("cq_v2_policy_coverages.rq", "cq_v2_exclusion_exception_evidence.rq", "cq_v2_deductibles.rq"):
        assert list(retriever.graph_index.g.query((ROOT / "ontology" / f).read_text(encoding="utf-8")))


def test_orange_exclusion_uses_its_own_policy(retriever):
    hits = retriever.search("Which exclusions apply to Orange collision coverage?", ontology_mode="graph")
    assert hits and hits[0].chunk.source_path == "orange_exclusions.txt"
    assert all(h.chunk.source_path.startswith("orange_") for h in hits)
    assert "hasExclusion" in [t.relation for t in retriever.last_graph_plan.traces[hits[0].chunk.chunk_id]]
    assert hits[0].graph_score == 1.0


def test_blue_exception_traverses_two_edges(retriever):
    hits = retriever.search("What exception applies to Blue Shield collision ride-hailing?", ontology_mode="graph")
    assert hits and hits[0].chunk.source_path == "blue_exclusions.txt"
    assert all(h.chunk.source_path.startswith("blue_") for h in hits)
    paths = hits[0].graph_paths
    assert any("commercial-use endorsement" in p.lower() for p in paths)
    trace = retriever.last_graph_plan.traces[hits[0].chunk.chunk_id]
    assert any(t.relation == "hasException" for t in trace)


def test_green_fire_deductible(retriever):
    hits = retriever.search("Green Road fire deductible?", ontology_mode="graph")
    assert hits and hits[0].chunk.source_path == "green_exclusions.txt"
    assert all(h.chunk.source_path.startswith("green_") for h in hits)
    assert any(t.relation == "hasDeductible" for t in retriever.last_graph_plan.traces[hits[0].chunk.chunk_id])


def test_no_cross_policy_invented_coverage(retriever):
    hits = retriever.search("What collision coverage does Green Road Auto provide?", ontology_mode="graph")
    assert hits == []
    assert retriever.last_graph_plan.strict_no_match


def test_unscoped_is_explicitly_warned(retriever):
    retriever.search("Which collision exclusions apply?", ontology_mode="graph")
    assert any("No insurer/policy specified" in w for w in retriever.last_graph_plan.warnings)


def test_graph_synonyms_mode_and_v1_preserved(retriever):
    hits = retriever.search("What are Orange crash exclusions?", ontology_mode="graph_full")
    assert hits and all(h.chunk.source_path.startswith("orange_") for h in hits)
    assert retriever.search("racing", ontology_mode="synonyms")
    assert retriever.search("collision", ontology_mode="none")


def test_rdf_diagram_and_edges(retriever):
    index = retriever.graph_index
    pid, _ = index.policy_options()[0]
    rows = index.edges(pid)
    assert rows and all(r["source_document"] for r in rows)
    dot = index.graphviz_dot(pid)
    assert "digraph IKO" in dot and "hasCoverage" in dot


def test_missing_graph_mode_fails_cleanly():
    retriever = build_pipeline(DOCS)
    with pytest.raises(RuntimeError, match="compatible RDF graph"):
        retriever.search("Orange collision deductible?", ontology_mode="graph")


def test_builder_serialization_roundtrip(tmp_path):
    g = build_graph_from_annotations(FACTS, DOCS, SCHEMA)
    p = save_graph(g, tmp_path / "custom.ttl")
    assert len(rdflib.Graph().parse(p, format="turtle")) == len(g)


def test_quote_crossing_small_chunks_is_traced_without_guesswork():
    r = build_pipeline(DOCS, chunk_words=25, overlap_words=5, graph_file=TTL)
    assert len(r.chunks) > 8
    results = validate_graph(r.graph_index)
    assert results["passed"]
    hits = r.search("Orange collision exclusions", ontology_mode="graph")
    assert hits and all(h.chunk.source_path.startswith("orange_") for h in hits)
