# IKO-Auto V2: RDF instance graph and source provenance

This V2 prototype extends V1's **schema** with **manually curated RDF instances**. It is a functional implementation, not a validated ontology or a scientific evaluation.

## Files

- `iko_auto_v1.ttl`: original V1 draft schema, kept unchanged.
- `iko_auto_v2.ttl`: new V2 proposed OWL/RDF schema including source-linked relationship assertions.
- `instances/demo_annotations.json`: authored annotations describing *fabricated* insurance examples; each fact and relationship has a document path and verbatim quote.
- `instances/iko_auto_demo_v2.ttl`: materialized Turtle schema plus instance graph created with `scripts/build_graph.py`.
- `cq_v2_*.rq`: SPARQL competency queries for policy coverages, exclusions with possible exceptions and their supporting quotations, and deductibles.
- `validate_ontology.py`: older V1 schema structure check.
- `scripts/validate_graph.py`: V2 evidence anchoring, relationship reification, and SPARQL structural checks.

## Ontology-driven retrieval implementation

`src/graph_retrieval.py` reads the RDF instances using `rdflib` and traverses actual predicates in the data graph: `Policy -> hasVersion -> PolicyVersion -> hasCoverage -> Coverage`, followed by `hasExclusion`, `hasException`, `hasDeductible`, and `hasLimit`. It records evidence via source-linked `RelationshipAssertion` nodes using `assertionSubject / assertionPredicate / assertionObject` and `supportedBy` pointers to `SourcePassage`. Passages are matched against the loaded source chunks; changing chunk size causes evidence pointers to be rebuilt from exact quote spans.

Policy labels and aliases in RDF determine policy scope; named-policy questions do not mix other policies' retrieved passages. Unscoped questions are explicitly warned about and may return evidence from multiple documents. A named coverage absent from the named policy returns no graph result rather than borrowing a coverage from another provider. No hidden LLM, query-to-SPARQL translation, ontology logical inference, or automatic fact extraction is performed.

The `graph` experimental mode combines (a) graph-path relevance weight 0.7 and (b) an inverse-baseline-rank heuristic 0.3. If no graph path matches, retrieval uses the baseline ranking restricted to any explicitly identified policy. `graph_full` adds V1 synonym expansion on the baseline branch. These weights are **design choices for a demonstration**, not optimized parameters or measured improvements. Other baseline methods `none`, `synonyms`, `relations` and `full` are still present; V1 `relations` is just authored lexical cues.

## Rebuild or adapt the graph

1. Place permitted documents as plain `.txt` or `.md` inside a folder. Do not include a README `.md` in that folder because it would be indexed as source text.
2. Make a JSON file that follows the structure of `demo_annotations.json`, with **only verified facts** from your own documents and *exact matching source quotes*.
3. Build and validate source-linked RDF:

```cmd
python scripts\build_graph.py --docs data\demo_auto_graph --facts ontology\instances\demo_annotations.json --output ontology\instances\iko_auto_demo_v2.ttl
python scripts\validate_graph.py
```

For custom documents, pass the appropriate `--docs` and `--facts` and `--output` values to the builder and `--docs` and `--graph` to the validation script. In Streamlit select the same document folder and the matching TTL file. PDF source annotation ingestion is not yet supported by the JSON graph builder, even though the retrieval baseline reads text-based PDFs. A production pipeline needs page-aware evidence and annotation quality control.

## What the checks do **not** establish

Structural RDF parsing, exact quotation checks, and SPARQL answerability do **not** imply OWL consistency, SHACL constraint validity, insurer-specific legal correctness, gold-standard relevance, two independent human annotations, retrieval statistical significance, or answer faithfulness. The schema namespace `https://example.org/iko-auto/v2#` is illustrative and is not a published public ontology URI. See `PROJECT_STATUS.md` for remaining Paper A tasks.
