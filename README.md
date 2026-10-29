# IKO-Auto: Policy-Scoped Ontology-Guided Evidence Retrieval for Motor Insurance

This repository contains the implementation and public research artifacts corresponding to the IKO-Auto paper.

IKO-Auto is a policy-scoped RDF/OWL evidence representation and retrieval prototype for motor insurance. The study separates two questions: (1) whether structured, source-linked contractual evidence improves traceability and inspectability, and (2) whether graph-guided retrieval improves passage ranking. The reported experiments evaluate eight BM25-centered retrieval configurations over five motor-insurance policy booklets.

## Evaluation scope

- **Corpus:** five policy booklets (AXA, Admiral, Aviva, Direct Line, esure), segmented into **717 passages**.
- **Development:** 50 development-informed questions, ten per insurer.
- **H1:** 50 subsequent questions on the **same five policy booklets**. H1 is a new-question evaluation on known documents, not an unseen-policy benchmark.
- **Primary relevance criterion:** grade 2 = direct passage-level support.
- **Reported H1 result:** insurer-filtered BM25 (M2) and section-aware BM25 (M3) tie for the strongest primary performance; selective graph activation (M8) improves over unconditional extended-graph use (M7) but does not outperform M2/M3.

## Repository layout

- `src/` — retrieval, graph, evaluation, chunking and pipeline implementation.
- `scripts/` — graph-building, evaluation and diagnostic scripts retained from the research project.
- `tests/` — project tests.
- `ontology/` — frozen schema, ontology configuration and competency-query definitions.
- `outputs/v6/` — original populated graph \(G_0\).
- `outputs/v8_2/` — extended populated graph \(G_+\) and audit output.
- `questions/` — public Development and H1 question sets.
- `labels/` — public, text-minimized relevance labels. Full policy passage text is intentionally omitted.
- `results/development/` — final Development summaries and a text-minimized rank-detail export.
- `results/h1/` — final H1 summaries, routing/fallback audits, per-question results and a text-minimized ranking export.
- `audits/` — public summaries of the Development and H1 source-evidence audits.
- `validation/` — ontology structural/provenance checks and public CQ1-CQ8 validation summaries.
- `reproduce/` — scripts for recalculating the public metrics and the H1 execution package.

## Third-party source documents

The five insurer policy PDFs are **not redistributed in this repository**. They are third-party documents. Their filenames and SHA-256 identifiers are recorded in `reproduce/h1/H1_MANIFEST.json` and `results/h1/H1_RUN_PROVENANCE.json` so that the source editions used in the experiment can be identified.

The RDF graphs contain selected short source quotations as provenance for modeled relationships. They do not contain the complete policy documents.

## Self-contained tests

The public release includes the self-contained V7.1/V8.1/V8.2/V8.3 tests that do not require third-party policy PDFs or omitted historical development folders. Run:

```bash
python -m pytest -q tests
```

## Recalculate reported metrics from public artifacts

From the repository root:

```bash
python reproduce/recalculate_development_public.py
python reproduce/recalculate_h1_public.py
```

These scripts use the text-minimized public ranking and relevance files and reproduce the primary binary Hit@5, P@5, MRR@5 and nDCG@5 tables.

## Re-execute H1 retrieval from the PDFs

A fresh PDF-to-ranking run additionally requires authorized/local copies of the same five source PDFs. Place them under:

```text
data/research_corpus/
```

Then, after installing the project dependencies, the recorded H1 runner can be inspected or executed. The runner expects the frozen graphs under `outputs/v6/` and `outputs/v8_2/`, which are retained in this repository.

Example inspection:

```bash
python reproduce/h1/H1_native_v83_runner.py --inspect --project .
```

Example execution:

```bash
python reproduce/h1/H1_native_v83_runner.py --run --project . --package-dir reproduce/h1 --output-dir H1_RESULTS_REPRODUCED
```

The historical H1 provenance records `rank_bm25.BM25Okapi` as the active lexical backend, 170-word chunks with 45-word overlap, 717 indexed passages and a Top-5 retrieval budget. Historical Python and dependency versions were not fully recorded, so an exact fresh PDF-to-ranking execution depends on a sufficiently matched environment.

## Public relevance files

The public label files intentionally omit the full passage text and evidence-quote columns to avoid republishing large extracts of third-party policy documents. Passage identity is preserved through `chunk_id`, `source_path` and page number.

For Development, the two retained reviewer files agree on all 519 question-passage pairs. The public derivative stores the agreed relevance value and omits the underlying passage text. For H1, the public file retains final and pre-adjudication reviewer grades while omitting the passage text.

## Ontology validation scope

The validation artifacts support RDF parsing, graph-preservation checks, source/provenance structure, deterministic structural constraints and execution of eight competency-query templates. CQ1-CQ5 return populated contractual paths. CQ6-CQ8 have no real claim/policyholder instances and were exercised only through synthetic smoke tests. No full SHACL-engine conformance run, OWL reasoner consistency proof or independent legal-semantic validation is claimed.

## Questions and benchmark status

`questions/development_questions_50.csv` contains the 50 development-informed questions. `questions/h1_questions_50.csv` contains the 50 subsequent H1 questions. Publishing these files improves transparency but does not change their experimental status.

## License

The repository currently uses an **all-rights-reserved** notice. Replace `LICENSE` with a standard open-source license such as MIT or Apache-2.0 before publication if you want to grant reuse rights for the code.

## Citation

See `CITATION.cff`. Update the repository URL, DOI and publication venue when they become available.
