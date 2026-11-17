from src.ontology_expansion import expand_query, load_map
from src.pipeline import build_pipeline
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_modes_are_deterministic():
    q = "What coverage applies to a collision?"
    assert expand_query(q, "none")[0] == q
    assert "crash" in expand_query(q, "synonyms")[0]
    assert "exclusion" in expand_query(q, "relations")[0]
    assert "crash" in expand_query(q, "full")[0]

def test_reverse_synonym():
    assert "collision" in expand_query("Was my car in a crash?", "synonyms")[0]

def test_query_expansion_integrates():
    r = build_pipeline(ROOT / "data" / "demo_auto")
    assert r.search("collision", ontology_mode="synonyms")
    assert r.search("coverage", ontology_mode="relations")

def test_maps_present():
    assert load_map("synonyms.json") and load_map("retrieval_relations.json")
