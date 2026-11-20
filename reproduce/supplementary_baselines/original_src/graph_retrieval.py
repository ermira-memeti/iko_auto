"""Actual instance-graph traversal and evidence linking for IKO-Auto V2.

Reads RDF, follows policy->version->coverage->exclusion->exception and
coverage->deductible/limit, then maps assertion provenance to indexed chunks.
No OWL entailment, automatic fact extraction or answer correctness claim.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path
import re
from .graph_builder import IKO_BASE, require_rdflib
from .models import Chunk


@dataclass
class EvidenceTrace:
    chunk_id: str
    policy: str
    path: str
    relation: str
    quote: str
    weight: float


@dataclass
class GraphPlan:
    scores: dict[str, float] = field(default_factory=dict)
    traces: dict[str, list[EvidenceTrace]] = field(default_factory=dict)
    scoped_docs: set[str] | None = None
    matched_policies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    strict_no_match: bool = False


def phrase_in_text(phrase: str, text: str) -> bool:
    if not phrase:
        return False
    return re.search(r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)", text.lower()) is not None


class GraphIndex:
    def __init__(self, graph_path: str | Path, chunks: list[Chunk]):
        Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL = require_rdflib()
        self.g = Graph().parse(str(graph_path), format="turtle")
        self.IKO = Namespace(IKO_BASE)
        self.RDF, self.RDFS = RDF, RDFS
        self.chunks = chunks
        self.by_chunk = {chunk.chunk_id: chunk for chunk in chunks}
        self.policies = sorted(self.g.subjects(RDF.type, self.IKO.AutoPolicy), key=str)
        if not self.policies:
            raise ValueError("The RDF graph has no policy individuals of type iko:AutoPolicy")
        self.evidence_to_chunks: dict[object, list[str]] = {}
        for passage in self.g.subjects(RDF.type, self.IKO.SourcePassage):
            source = self._literal(passage, self.IKO.sourceDocumentId)
            quote = self._literal(passage, self.IKO.sourceQuote)
            if not source or not quote:
                raise ValueError(f"Source passage lacks a document ID or quote: {passage}")
            page_value = self.g.value(passage, self.IKO.sourcePage)
            verified_page = int(page_value) if page_value is not None else None
            matched = [c.chunk_id for c in chunks if c.source_path == source
                       and (verified_page is None or c.page == verified_page) and quote in c.text]
            if not matched:
                # Source quote crossing chunk boundaries: reconstruct the
                # indexed document's word sequence and identify ALL chunks
                # intersecting the exact quote span. Never attach evidence
                # merely because a few leading words happen to match.
                same_document = [c for c in chunks if c.source_path == source
                                 and (verified_page is None or c.page == verified_page)]
                per_doc_id = {}
                for c in same_document:
                    per_doc_id.setdefault(c.doc_id, []).append(c)
                target_quote = " ".join(quote.split())
                for source_chunks in per_doc_id.values():
                    max_end = max(c.end_word for c in source_chunks)
                    words = [None] * max_end
                    for c in source_chunks:
                        words[c.start_word:c.end_word] = c.text.split()
                    if any(word is None for word in words):
                        continue
                    doc_text = " ".join(words)
                    at = doc_text.find(target_quote)
                    if at < 0:
                        continue
                    start_word = len(doc_text[:at].split())
                    end_word = start_word + len(target_quote.split())
                    matched.extend(c.chunk_id for c in source_chunks
                                   if c.start_word < end_word and c.end_word > start_word)
            if not matched:
                raise ValueError(f"RDF passage quote is not found in indexed chunks: {source} / {quote[:75]}")
            self.evidence_to_chunks[passage] = sorted(set(matched))
            for cid in matched:
                self.g.add((passage, self.IKO.sourceChunkId, Literal(cid)))
        self.assertions = {}
        for a in self.g.subjects(RDF.type, self.IKO.RelationshipAssertion):
            s = self.g.value(a, self.IKO.assertionSubject)
            p = self.g.value(a, self.IKO.assertionPredicate)
            o = self.g.value(a, self.IKO.assertionObject)
            evs = tuple(self.g.objects(a, self.IKO.supportedBy))
            if None in (s, p, o) or not evs:
                raise ValueError(f"Incomplete source-linked relationship assertion: {a}")
            if (s, p, o) not in self.g:
                raise ValueError(f"Assertion without the corresponding graph edge: {a}")
            self.assertions[(s, p, o)] = tuple(dict.fromkeys((*self.assertions.get((s, p, o), ()), *evs)))
        self.policy_sources: dict[object, set[str]] = {}
        for policy in self.policies:
            sources = set()
            for version in self.g.objects(policy, self.IKO.hasVersion):
                for condition in self.g.objects(version, self.IKO.hasClaimCondition):
                    for ev in self.g.objects(condition, self.IKO.supportedBy):
                        source = self._literal(ev, self.IKO.sourceDocumentId)
                        if source:
                            sources.add(source)
                for coverage in self.g.objects(version, self.IKO.hasCoverage):
                    for node in self._descendants(coverage):
                        for p in self.g.objects(node, self.IKO.supportedBy):
                            source = self._literal(p, self.IKO.sourceDocumentId)
                            if source:
                                sources.add(source)
            self.policy_sources[policy] = sources

    def _descendants(self, coverage):
        result = [coverage]
        for p in (self.IKO.hasExclusion, self.IKO.hasDeductible, self.IKO.hasLimit):
            for target in self.g.objects(coverage, p):
                result.append(target)
                if p == self.IKO.hasExclusion:
                    result.extend(self.g.objects(target, self.IKO.hasException))
        return result

    def _literal(self, node, pred):
        v = self.g.value(node, pred)
        return str(v) if v is not None else ""

    def label(self, node):
        return self._literal(node, self.RDFS.label) or str(node).split("#")[-1]

    def terms(self, node):
        return [self.label(node), *[str(s) for s in self.g.objects(node, self.IKO.alias)]]

    def policy_options(self):
        return [(self._literal(p, self.IKO.policyIdentifier), self.label(p)) for p in self.policies]

    def evidence_details(self, assertion):
        for ev in self.assertions.get(assertion, []):
            for chunk_id in self.evidence_to_chunks.get(ev, []):
                yield chunk_id, self._literal(ev, self.IKO.sourceQuote)

    def plan(self, query: str) -> GraphPlan:
        result = GraphPlan()
        lower = query.lower().strip()
        if not lower:
            return result
        explicitly_named = [p for p in self.policies if any(phrase_in_text(t, lower) for t in self.terms(p))]
        # A question naming another real insurer MUST NOT use AXA/Admiral
        # graph evidence simply because that insurer is absent from this graph.
        from .policy_catalog import named_insurers
        named = named_insurers(query)
        if len(named) > 1:
            result.strict_no_match = True
            result.warnings.append('Graph retrieval needs one specified insurer per question; multiple named insurers cannot be safely combined.')
            return result
        if named and not explicitly_named:
            result.strict_no_match = True
            result.warnings.append("Named insurer has no reviewed RDF policy instances in the selected graph. "
                                   "Select BM25 with metadata filtering instead; do not borrow another insurer's facts.")
            return result
        active = explicitly_named or self.policies
        if explicitly_named:
            result.scoped_docs = set().union(*(self.policy_sources[p] for p in active))
        else:
            result.warnings.append("No insurer/policy specified: graph evidence may span multiple annotated policies. Specify a policy to avoid ambiguity.")
        result.matched_policies = [self.label(p) for p in active]

        # V7.1: Scope coverage recognition to the policy actually named in the
        # question. Older logic searched every insurer for ambiguous one-word
        # coverage aliases ("damage", "accident") and incorrectly rejected
        # unrelated policy questions as unsupported, returning an empty result.
        all_coverages = {cov for pol in self.policies for v in self.g.objects(pol, self.IKO.hasVersion)
                         for cov in self.g.objects(v, self.IKO.hasCoverage)}
        active_coverages = {cov for pol in active for v in self.g.objects(pol, self.IKO.hasVersion)
                            for cov in self.g.objects(v, self.IKO.hasCoverage)}
        matched_active_coverages = {cov for cov in active_coverages
                                    if any(phrase_in_text(t, lower) for t in self.terms(cov))}
        claim_condition_intent = any(phrase_in_text(t, lower) for t in
            ["report", "reporting", "notify", "notification", "claim condition", "claim deadline", "how soon", "how quickly", "48 hours"])
        # Preserve strict rejection for *discriminative*, explicitly requested
        # kinds of cover absent from the selected policy. Never let an alias
        # like 'damage' or 'accident' belonging to a DIFFERENT insurer trigger
        # rejection. This is intentionally conservative; no cross-policy
        # statements or inferred provisions are added.
        generic_aliases = {"damage", "accident", "car damage", "vehicle damage",
                           "covered damage", "vehicle", "car", "loss", "cover",
                           "insurance", "vehicle cover", "accidental damage"}
        unmatched_specific_coverages = {cov for cov in all_coverages - active_coverages
                                        if any(len(t.split()) <= 5
                                               and t.casefold().strip() not in generic_aliases
                                               and phrase_in_text(t, lower)
                                               for t in self.terms(cov))}
        if explicitly_named and not matched_active_coverages and unmatched_specific_coverages and not claim_condition_intent:
            result.strict_no_match = True
            result.warnings.append("Named policy has no modeled match for an explicitly requested coverage type. "
                                   "No different insurer's provisions are substituted.")
            return result
        # A named insurer without an explicit coverage match searches *only*
        # its annotated coverage groups; if graph assertions do not fit, the
        # existing source-scoped lexical fallback is used.
        named_coverage_terms = matched_active_coverages
        ask_exclusions = (any(phrase_in_text(t, lower) for t in
                              ["exclusion", "exclusions", "exclude", "excluded", "not covered",
                               "excludes", "excluding", "does not cover", "not insured"])
                          or (any(phrase_in_text(t, lower) for t in ["staged", "deliberately", "fraudulent"])
                              and any(phrase_in_text(t, lower) for t in ["accident", "claim", "loss", "damage"])))
        ask_exceptions = any(phrase_in_text(t, lower) for t in ["exception", "exceptions", "endorsement", "unless"])
        ask_deductible = any(phrase_in_text(t, lower) for t in ["deductible", "excess", "out of pocket"])
        ask_limit = any(phrase_in_text(t, lower) for t in ["limit", "limits", "maximum payment", "maximum payout"])
        ask_coverage = any(phrase_in_text(t, lower) for t in ["cover", "covers", "covered", "coverage", "eligible"])
        ask_claim_condition = claim_condition_intent

        def record(s, p, o, policy, path, weight):
            assertion = (s, p, o)
            for chunk_id, quote in self.evidence_details(assertion):
                trace = EvidenceTrace(chunk_id, self.label(policy), path,
                                      str(p).split("#")[-1], quote, weight)
                result.scores[chunk_id] = max(result.scores.get(chunk_id, 0.0), weight)
                result.traces.setdefault(chunk_id, [])
                if not any(t.path == trace.path and t.quote == trace.quote for t in result.traces[chunk_id]):
                    result.traces[chunk_id].append(trace)

        for policy in active:
            for version in self.g.objects(policy, self.IKO.hasVersion):
                if ask_claim_condition:
                    for condition in self.g.objects(version, self.IKO.hasClaimCondition):
                        record(version, self.IKO.hasClaimCondition, condition, policy,
                               f"{self.label(policy)} -> {self.label(condition)}", 1.0)
                for coverage in self.g.objects(version, self.IKO.hasCoverage):
                    if named_coverage_terms and coverage not in named_coverage_terms:
                        continue
                    base_path = f"{self.label(policy)} -> {self.label(coverage)}"
                    exclusions = list(self.g.objects(coverage, self.IKO.hasExclusion))
                    matched_exclusions = [x for x in exclusions if any(phrase_in_text(t, lower) for t in self.terms(x))]
                    need_exclusions = ask_exclusions or ask_exceptions or bool(matched_exclusions)
                    relevant_exclusions = matched_exclusions if matched_exclusions and not ask_exclusions else exclusions
                    if ask_exceptions:
                        for x in relevant_exclusions:
                            for e in self.g.objects(x, self.IKO.hasException):
                                path = base_path + f" -> {self.label(x)} -> {self.label(e)}"
                                record(x, self.IKO.hasException, e, policy, path, 1.0)
                        for x in relevant_exclusions:
                            record(coverage, self.IKO.hasExclusion, x, policy,
                                   base_path + f" -> {self.label(x)}", 0.7)
                    elif need_exclusions:
                        for x in relevant_exclusions:
                            record(coverage, self.IKO.hasExclusion, x, policy,
                                   base_path + f" -> {self.label(x)}", 1.0)
                            for e in self.g.objects(x, self.IKO.hasException):
                                # When an exception qualifies an exclusion, do not
                                # hide the exception from the user's evidence.
                                record(x, self.IKO.hasException, e, policy,
                                       base_path + f" -> {self.label(x)} -> {self.label(e)}", 0.85)
                    if ask_deductible:
                        for d in self.g.objects(coverage, self.IKO.hasDeductible):
                            record(coverage, self.IKO.hasDeductible, d, policy,
                                   base_path + f" -> {self.label(d)}", 1.0)
                    if ask_limit:
                        for d in self.g.objects(coverage, self.IKO.hasLimit):
                            record(coverage, self.IKO.hasLimit, d, policy,
                                   base_path + f" -> {self.label(d)}", 1.0)
                    if ask_coverage or not (need_exclusions or ask_deductible or ask_limit or ask_claim_condition):
                        record(version, self.IKO.hasCoverage, coverage, policy, base_path,
                               0.55 if (need_exclusions or ask_deductible or ask_limit) else 1.0)
        if not result.scores:
            result.warnings.append("No source-grounded instance-graph path matched the requested relation; retrieval will fall back to lexical evidence within the policy scope.")
        return result

    def edges(self, policy_id: str | None = None):
        """Actual RDF edges (no invented visualization links)."""
        predicates = [self.IKO.hasVersion, self.IKO.hasCoverage, self.IKO.hasExclusion,
                      self.IKO.hasException, self.IKO.hasDeductible, self.IKO.hasLimit,
                      self.IKO.hasClaimCondition]
        selected = self.policies
        if policy_id:
            selected = [p for p in selected if self._literal(p, self.IKO.policyIdentifier) == policy_id]
        rows = []
        for policy in selected:
            for version in self.g.objects(policy, self.IKO.hasVersion):
                frontier = [policy, version]
                frontier.extend(self.g.objects(version, self.IKO.hasClaimCondition))
                for coverage in self.g.objects(version, self.IKO.hasCoverage):
                    frontier.append(coverage)
                    for exclusion in self.g.objects(coverage, self.IKO.hasExclusion):
                        frontier.append(exclusion)
                        frontier.extend(self.g.objects(exclusion, self.IKO.hasException))
                    frontier.extend(self.g.objects(coverage, self.IKO.hasDeductible))
                    frontier.extend(self.g.objects(coverage, self.IKO.hasLimit))
                for source in frontier:
                    for prop in predicates:
                        for target in self.g.objects(source, prop):
                            if target in frontier:
                                assertion = (source, prop, target)
                                proofs = [self._literal(ev, self.IKO.sourceDocumentId)
                                          for ev in self.assertions.get(assertion, ())]
                                rows.append({"policy": self.label(policy), "source": self.label(source),
                                             "relation": str(prop).split("#")[-1], "target": self.label(target),
                                             "source_document": "; ".join(sorted(set(proofs)))})
        return rows

    def graphviz_dot(self, policy_id: str | None = None):
        rows = self.edges(policy_id)
        import hashlib
        def nid(s):
            return 'n' + hashlib.sha256(s.encode()).hexdigest()[:12]
        def esc(s):
            return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
        out = ['digraph IKO {', 'rankdir=LR;', 'graph [bgcolor="transparent", pad="0.3"];',
               'node [shape="box",style="rounded",fontsize="10"];',
               'edge [fontsize="9"];']
        # Disambiguate repeated coverage labels across policies for graph drawing.
        for r in rows:
            left = r["policy"] + '|' + r["source"]
            right = r["policy"] + '|' + r["target"]
            out.append(f'{nid(left)} [label="{esc(r["source"])}"];')
            out.append(f'{nid(right)} [label="{esc(r["target"])}"];')
            out.append(f'{nid(left)} -> {nid(right)} [label="{esc(r["relation"])}"];')
        out.append('}')
        return "\n".join(out)
