"""Convert explicitly annotated policy facts into a provenance-linked RDF graph.

Only user-provided, manually checked annotations are encoded. This module does
NOT mine facts automatically and does not perform OWL reasoning.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

IKO_BASE = "https://example.org/iko-auto/v2#"


def require_rdflib():
    try:
        from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL
    except ImportError as exc:
        raise RuntimeError("Graph mode needs rdflib: python -m pip install -r requirements-ontology.txt") from exc
    return Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL


def slug(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not result:
        raise ValueError("An annotation ID cannot be empty")
    return result


def build_graph_from_annotations(annotations: str | Path, documents: str | Path, schema: str | Path | None = None):
    """Validate ALL supporting quotations against documents, build RDF Graph.

    The builder rejects references to missing source documents and quotes that
    are not exact substrings. No inferred/extracted policies are asserted.
    """
    Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL = require_rdflib()
    facts = json.loads(Path(annotations).read_text(encoding="utf-8"))
    root = Path(documents).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Source document directory does not exist: {root}")
    g = Graph()
    IKO = Namespace(IKO_BASE)
    g.bind("iko", IKO)
    g.bind("rdfs", RDFS)
    if schema is not None:
        g.parse(str(schema), format="turtle")
    cache: dict[tuple[str, int | None], str] = {}
    policy_records: list[dict] = []
    source_cache: dict[tuple[str, str], Path] = {}

    def resolved_evidence_file(evidence: dict) -> tuple[Path, str]:
        logical = evidence["document"]
        expected_hash = evidence.get("sha256", "").lower().strip()
        key = (logical, expected_hash)
        if key in source_cache:
            match = source_cache[key]
        else:
            match = (root / logical).resolve()
            if not match.is_relative_to(root):
                raise ValueError(f"Source path escapes document directory: {logical}")
            if expected_hash and (not match.is_file() or hashlib.sha256(match.read_bytes()).hexdigest() != expected_hash):
                matches = [p for p in root.rglob('*') if p.is_file() and
                           p.suffix.lower() in {'.pdf', '.txt', '.md'} and
                           hashlib.sha256(p.read_bytes()).hexdigest() == expected_hash]
                if len(matches) != 1:
                    raise ValueError(f"Source hash missing or ambiguous for {logical}. Expected SHA-256 {expected_hash}; "
                                     "use the exact audited PDF edition, not another version.")
                match = matches[0]
            if not match.is_file() or match.suffix.lower() not in {'.pdf', '.txt', '.md'}:
                raise ValueError(f"Missing/unsupported evidence document: {logical}")
            if expected_hash and hashlib.sha256(match.read_bytes()).hexdigest() != expected_hash:
                raise ValueError(f"Source SHA-256 mismatch for {logical}")
            source_cache[key] = match
        return match, match.relative_to(root).as_posix()

    def evidence_node(evidence: dict):
        quote = ' '.join(str(evidence['quote']).split())
        source_file, source = resolved_evidence_file(evidence)
        page = evidence.get('page')
        if source_file.suffix.lower() == '.pdf':
            if not isinstance(page, int) or page < 1:
                raise ValueError(f"PDF citation needs a positive 1-based page: {source}")
        elif page is not None:
            raise ValueError('Text evidence should omit page')
        cache_key = (source, page)
        if cache_key not in cache:
            if source_file.suffix.lower() == '.pdf':
                from pypdf import PdfReader
                reader = PdfReader(str(source_file))
                if page > len(reader.pages):
                    raise ValueError(f"Page {page} outside {source} ({len(reader.pages)} pages)")
                cache[cache_key] = ' '.join((reader.pages[page-1].extract_text() or '').split())
            else:
                cache[cache_key] = ' '.join(source_file.read_text(encoding='utf-8-sig').split())
        if not quote.strip() or quote not in cache[cache_key]:
            raise ValueError(f"Evidence quote does not appear verbatim after whitespace normalization on "
                             f"{source} page {page}: {quote!r}")
        key = hashlib.sha256((source + "\n" + str(page) + "\n" + quote).encode()).hexdigest()[:20]
        node = IKO[f"passage_{key}"]
        g.add((node, RDF.type, IKO.SourcePassage))
        g.add((node, IKO.sourceDocumentId, Literal(source)))
        if page is not None:
            g.add((node, IKO.sourcePage, Literal(page)))
        g.add((node, IKO.sourceQuote, Literal(quote)))
        return node

    def entity(policy_id: str, kind: str, data: dict, evidence: dict | None = None):
        uri = IKO[f"{slug(policy_id)}_{slug(kind)}_{slug(data['id'])}"]
        g.add((uri, RDF.type, getattr(IKO, kind)))
        g.add((uri, RDFS.label, Literal(data["name"])))
        for alias in data.get("aliases", []):
            g.add((uri, IKO.alias, Literal(alias)))
        if evidence:
            g.add((uri, IKO.supportedBy, evidence_node(evidence)))
        return uri

    def relation(s, predicate, o, evidence: dict):
        # The relationship itself, not only the target node, is source-linked.
        p = getattr(IKO, predicate)
        ev = evidence_node(evidence)
        g.add((s, p, o))
        key = hashlib.sha256((str(s) + str(p) + str(o) + str(ev)).encode()).hexdigest()[:20]
        assertion = IKO[f"assertion_{key}"]
        g.add((assertion, RDF.type, IKO.RelationshipAssertion))
        g.add((assertion, IKO.assertionSubject, s))
        g.add((assertion, IKO.assertionPredicate, p))
        g.add((assertion, IKO.assertionObject, o))
        g.add((assertion, IKO.supportedBy, ev))

    for policy in facts["policies"]:
        pid = slug(policy["id"])
        policy_uri = entity(pid, "AutoPolicy", {"id": "policy", "name": policy["name"], "aliases": policy.get("aliases", [])})
        g.add((policy_uri, IKO.policyIdentifier, Literal(policy["id"])))
        ver_uri = entity(pid, "PolicyVersion", {"id": policy["version"], "name": f"{policy['name']} version {policy['version']}", "aliases": [policy["version"]]})
        g.add((ver_uri, IKO.policyVersionIdentifier, Literal(policy["version"])))
        if not policy.get("coverages"):
            raise ValueError(f"Policy has no annotated coverages: {pid}")
        # Link the conceptual document edition to a verified quotation. Edition
        # identifiers are descriptive user labels, NOT independently verified dates.
        relation(policy_uri, "hasVersion", ver_uri, policy["coverages"][0]["evidence"])
        policy_records.append({"policy_id": policy["id"], "label": policy["name"], "uri": str(policy_uri)})
        # V6: notification/reporting requirements are policy-edition clauses, not
        # exclusions or facts about any particular customer schedule.
        for condition in policy.get("claim_conditions", []):
            condition_uri = entity(pid, "ClaimCondition", condition, condition["evidence"])
            relation(ver_uri, "hasClaimCondition", condition_uri, condition["evidence"])
        for coverage in policy["coverages"]:
            cov_uri = entity(pid, "Coverage", coverage, coverage["evidence"])
            relation(ver_uri, "hasCoverage", cov_uri, coverage["evidence"])
            for exclusion in coverage.get("exclusions", []):
                excl_uri = entity(pid, "Exclusion", exclusion, exclusion["evidence"])
                relation(cov_uri, "hasExclusion", excl_uri, exclusion["evidence"])
                for exception in exclusion.get("exceptions", []):
                    exc_uri = entity(pid, "Exception", exception, exception["evidence"])
                    relation(excl_uri, "hasException", exc_uri, exception["evidence"])
            for name, prop, kind in (("deductible", "hasDeductible", "Deductible"), ("limit", "hasLimit", "CoverageLimit")):
                if coverage.get(name):
                    obj = coverage[name]
                    obj_uri = entity(pid, kind, obj, obj["evidence"])
                    relation(cov_uri, prop, obj_uri, obj["evidence"])
    if len(policy_records) != len({p["policy_id"] for p in policy_records}):
        raise ValueError("Duplicate policy identifiers")
    return g


def save_graph(graph, target: str | Path) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(path), format="turtle")
    return path
