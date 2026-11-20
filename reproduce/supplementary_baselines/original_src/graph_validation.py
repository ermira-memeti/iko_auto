"""Structural and source-grounding checks; NOT OWL logical consistency tests."""
from rdflib import RDF

def validate_graph(index) -> dict:
    g, iko = index.g, index.IKO
    findings = []
    errors = []
    for a in g.subjects(RDF.type, iko.RelationshipAssertion):
        s = g.value(a, iko.assertionSubject)
        p = g.value(a, iko.assertionPredicate)
        o = g.value(a, iko.assertionObject)
        evs = list(g.objects(a, iko.supportedBy))
        if (s, p, o) not in g:
            errors.append(f"Assertion triple is absent: {a}")
        if not evs:
            errors.append(f"Assertion missing source citation: {a}")
        for ev in evs:
            if not index.evidence_to_chunks.get(ev):
                errors.append(f"Source quote is not anchored to a chunk: {ev}")
    # Check every instance-level domain edge has an explicit assertion, not
    # just that the existing assertion nodes happen to be well formed.
    documented_predicates = (iko.hasVersion, iko.hasCoverage, iko.hasExclusion,
                             iko.hasException, iko.hasDeductible, iko.hasLimit,
                             iko.hasClaimCondition)
    for pred in documented_predicates:
        for sub, obj in g.subject_objects(pred):
            if (sub, pred, obj) not in index.assertions:
                errors.append(f"Instance relationship lacks evidence assertion: {sub} / {pred} / {obj}")
    for policy in index.policies:
        versions = list(g.objects(policy, iko.hasVersion))
        if not versions:
            errors.append(f"Policy has no version: {index.label(policy)}")
        for v in versions:
            if not list(g.objects(v, iko.hasCoverage)):
                errors.append(f"Version lacks coverage facts: {index.label(v)}")
    q = '''PREFIX iko: <https://example.org/iko-auto/v2#>
            SELECT (COUNT(?c) AS ?n) WHERE {
              ?policy iko:hasVersion ?version . ?version iko:hasCoverage ?c . }'''
    try:
        coverage_count = int(next(iter(g.query(q)))[0])
        findings.append(f"SPARQL competency check: {coverage_count} policy-specific coverages are queryable")
    except Exception as exc:
        errors.append(f"SPARQL competency query failed: {exc}")
        coverage_count = 0
    findings.append(f"{len(index.assertions)} source-linked relationship assertions")
    findings.append(f"{len(index.evidence_to_chunks)} quoted source passages anchored to indexed chunks")
    return {"passed": not errors, "errors": errors, "checks": findings,
            "policies": len(index.policies), "coverages": coverage_count,
            "relationship_assertions": len(index.assertions),
            "source_passages": len(index.evidence_to_chunks),
            "triples": len(g),
            "limitations": "Structural, SPARQL, and source-string checks only. Does not validate OWL logical consistency, domain truth, expert agreement, or retrieval performance."}
