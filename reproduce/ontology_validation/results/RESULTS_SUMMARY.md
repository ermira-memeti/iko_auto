# Executed Comment-7 checks on frozen graphs

| Item | G0 | G+ |
|---|---:|---:|
| Serialized graph triples | 932 | 1,029 |
| RelationshipAssertion focus nodes | 49 | 54 |
| SourcePassage focus nodes | 44 | 49 |
| SHACL-compatible component checks executed by the included RDFLib subset evaluator | 1,416 | 1,561 |
| Detected violations in original frozen data | 0 | 0 |
| Missing reified/direct contractual relationships | 0 | 0 |
| Mutated negative controls detected | 5/5 | 5/5 |
| Conflict across the four proposed disjointness pairs | 0 | 0 |
| Inverse-edge consequences from *proposed* companion OWL profile | 106 | 121 |

**Interpretation.** This reports the executed local RDFLib-based SHACL Core component subset and targeted OWL-related structural tests. A general-purpose pySHACL engine, an OWL-RL rule engine, and an OWL 2 DL consistency reasoner have **not** been executed here. Do not state that these engine runs passed. The necessary independent-engine driver is supplied under `scripts/run_standard_engines.py`.

**Fixed schema:** 28 classes, 22 object properties, seven datatype properties; zero explicit disjointness, inverse, cardinality or restriction axioms. The separate, proposed 28-triple semantic profile adds limited axioms without altering original experimental data.

**Scope.** Neither SHACL conformance to these shapes nor OWL typing/interoperability checks establishes contractual completeness, legal correctness, general ontology superiority, or a ranking improvement over BM25.
