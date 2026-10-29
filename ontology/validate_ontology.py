from pathlib import Path
try:
    from rdflib import Graph, RDF, OWL, RDFS
except ImportError as exc:
    raise SystemExit("Install ontology extras: python -m pip install -r requirements-ontology.txt") from exc
path = Path(__file__).with_name("iko_auto_v1.ttl")
g = Graph().parse(path, format="turtle")
classes = set(g.subjects(RDF.type, OWL.Class))
properties = set(g.subjects(RDF.type, OWL.ObjectProperty))
assert len(classes) >= 20 and len(properties) >= 15
for prop in properties:
    assert any(g.objects(prop, RDFS.domain)), f"Missing domain: {prop}"
    assert any(g.objects(prop, RDFS.range)), f"Missing range: {prop}"
print(f"Parsed {len(g)} RDF triples; {len(classes)} classes; {len(properties)} object properties.")
print("Schema structural checks passed; this is NOT OWL reasoner consistency validation.")
