# IKO-Auto — Competency-question and structural validation

## Evidence and scope

The tests in this package were run against the **unchanged** instance graphs contained in `IKO_Auto_Ontology_CQ_Inputs.zip` and their supplied V6 schema. The input file hashes were verified against the archive's own manifest before executing queries. No original graphs, retrieval rankings, reviewer judgments, or policy PDFs were modified.

**Correction to prior test plan:** the supplied file `ontology/competency_questions.md` defines **eight competency questions**, numbered 1–8. The older CQ1–CQ7 reference was incomplete. The file's caution that no instance dataset is included is inaccurate for *this particular ZIP*, which does include the V6 and V8.2 RDF instance graphs.

## Observed SPARQL query results

| CQ | Design question (abridged) | V6 rows | V8.2 rows | Evidence-bound interpretation |
|---|---|---:|---:|---|
| CQ1 | Policy version to coverage provisions | 8 | 13 | 5 policy versions are represented; 5 additional coverage links are present in V8.2 |
| CQ2 | Coverage to exclusions | 21 | 21 | The same selected exclusions are represented in both frozen graphs |
| CQ3 | Explicit exceptions to an exclusion | 1 | 1 | One expressly represented exception; absent graph edges do not imply no other exceptions exist |
| CQ4 | Coverage to deductible or limit | 9 | 9 | 6 deductible links and 3 limit links; some values point to schedules rather than numeric amounts |
| CQ5 | Evidence-backed coverage/exclusion links | 29 | 34 | 8+21 and 13+21 relationships respectively, each linked through a provenance assertion |
| CQ6 | Claims, claim events, accident causes | 0 | 0 | No claim instances; query was verified with separate synthetic test triples only |
| CQ7 | Claim damage categories and severities | 0 | 0 | No claim instances; query was verified with separate synthetic test triples only |
| CQ8 | Policyholder risk factors | 0 | 0 | No policyholder instances; query was verified with separate synthetic test triples only |

All eight queries executed without SPARQL errors against both instance graphs. The nonempty counts for CQ1–CQ5 match graph-internal expected counts identified during inspection; **this does not constitute independently annotated legal/semantic expected-answer evaluation**.

## Structural checks

- **V6:** 932 triples; 44 typed source passages; 49 reified relationship assertions; 49 relationship edges covered by those assertions.
- **V8.2:** 1,029 triples; 49 typed source passages; 54 reified relationship assertions; 54 relationship edges covered by those assertions.
- The extended V8.2 graph preserves all 932 V6 triples and adds 97, deleting none.
- The checks found **zero violations** for required source document/page/quotation fields, explicit domain/range types for the populated paths, correspondence between reified assertions and relationship triples, and the insurer-to-document association of each supporting passage.
- The earlier, separate PDF-level provenance report checked quotations in 44 V6 and 49 V8.2 passage records successfully. Those checks are not repeated in this ZIP because the PDFs are excluded.

## Gaps and cautions

1. `iko:sourcePage` occurs as an integer-valued predicate in source-passage instances, but the supplied schema does **not declare this property or its datatype/range**. A future, separately versioned ontology schema can declare it as an `owl:DatatypeProperty` with `rdfs:range xsd:integer`. Do **not** silently rewrite the frozen graphs or evaluation artifacts.
2. `iko:sourceChunkId` is declared in the schema but not populated on the 44/49 source-passage records. Page-and-quotation provenance is present, but there is no explicit passage-to-717-chunk identifier in the RDF nodes.
3. No policy-version instance has an `effectiveDate`. The available IDs identify uploaded booklet editions with dates not independently established; results should not be presented as verified time-effective policy terms.
4. No real `iko:Claim` or `iko:Policyholder` instances are present. Accordingly CQ6–CQ8 are **schema/query-capability tests only**, not empirically demonstrated answers from this corpus.
5. Formal SHACL conformance was **not executed** in this environment because `pyshacl` was not installed and package download was unavailable. The supplied `IKO_Auto_CQ_SHACL_Shapes.ttl` is a separate, valid Turtle shape specification and `run_iko_auto_formal_shacl.py` can execute it on a system with pySHACL installed. Programmatic SHACL-style checks did run.
6. No OWL DL/OWL RL reasoner was executed. Therefore **logical consistency, inferred entailment, and legal/business-domain correctness are not established**. A working RDF query is not proof that a modeled relationship is legally correct or complete.
7. Counts reflect selectively modeled contractual relationships, not comprehensive representation of each booklet. No out-of-corpus insurer generalization is demonstrated.

## Manuscript-ready wording (accurate for these results)

**Methods — ontology validation.** The original and extended IKO-Auto RDF instance graphs were evaluated using eight competency-question SPARQL templates derived from the ontology's documented design requirements. CQ1–CQ5 cover source-linked policy and contractual relationship paths; CQ6–CQ8 cover claims, damage and policyholder risk concepts. We also executed deterministic structural checks for typed relationship endpoints, mandatory source-passage metadata, reified assertion consistency and supporting-document scope. Input SHA-256 hashes and the preservation of the V6 triples in V8.2 were verified. A separate synthetic-data query test checked the executability of CQ6–CQ8 in the absence of real instances. These tests evaluate graph structure and query behavior, not insurance-law correctness or OWL logical consistency.

**Results — ontology validation.** The V6 graph comprised 932 triples, and the extended V8.2 graph comprised 1,029 triples, preserving all 932 original triples. CQ1–CQ5 returned 8/13 policy-coverage links, 21/21 coverage-exclusion links, 1/1 exclusion-exception link, 9/9 deductible-or-limit links, and 29/34 source-backed coverage-or-exclusion links in V6/V8.2, respectively. All tested assertion-link, typed endpoint and provenance-metadata constraints passed without recorded violations. CQ6–CQ8 returned no real-data results because the study's graphs do not contain claim or policyholder records; their query syntax and paths succeeded only in synthetic smoke tests. Remaining limitations include the undeclared `sourcePage` property, absence of `sourceChunkId` values and effective dates, and the lack of OWL reasoner, full SHACL engine and independent domain-semantic validation.

## Reproduction

1. Install Python packages: `python -m pip install rdflib openpyxl`.
2. Place `IKO_Auto_Ontology_CQ_Inputs.zip` and `run_iko_auto_cq_validation.py` in the same directory.
3. Run `python run_iko_auto_cq_validation.py --inputs IKO_Auto_Ontology_CQ_Inputs.zip --out-dir My_CQ_Results`.
4. Optional full SHACL validation: `python -m pip install pyshacl` and `python run_iko_auto_formal_shacl.py --inputs IKO_Auto_Ontology_CQ_Inputs.zip --shapes IKO_Auto_CQ_SHACL_Shapes.ttl`.

This validation does not modify the frozen development or H1 evaluation metrics.
