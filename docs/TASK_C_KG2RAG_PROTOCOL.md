# Task C: Published KG2RAG comparator (NOT YET RUN)

Citation: Xiangrong Zhu, Yuexiang Xie, Yi Liu, Yaliang Li and Wei Hu,
"Knowledge Graph-Guided Retrieval Augmented Generation," NAACL 2025,
https://aclanthology.org/2025.naacl-long.449/ . Official code:
https://github.com/nju-websoft/KG2RAG (GPL-3.0).

## Goal
Evaluate the **published three-stage KG2RAG mechanism** (semantic seed
retrieval, knowledge-graph-guided chunk expansion, graph-based context
filtering/organization), not just a local one-hop approximation. Do not claim
an official KG2RAG reproduction before the actual paper implementation is
adapted and executed. Use retrieval-only outputs; generated answers are not
evaluated in IKO-Auto.

## Frozen comparison material
Five PDFs -> 717 distinct 170-word/45-overlap, page-bounded chunks, 232 PDF
pages; development 50 + H1 50 questions. The same source hashes/IDs should
be used throughout; original M2, M8 rankings must never be rewritten.

## Experiment steps
1. From repository root, run `python reproduce/task_c/preflight.py --root .`.
   This compares all 100 archived M2 Top-5 lists against the existing reproduced
   rankings. Stop on ANY mismatch. It also checks the newer Comment8 outputs.
2. `git clone https://github.com/nju-websoft/KG2RAG.git` into a LOCAL separate
   folder and record the commit SHA and its GPL-3.0 license. Do NOT confuse
   `GRAPH_NEIGHBOR` with this official implementation.
3. Adapt the official HotpotQA-centric loader: convert the original 717 chunks
   into records with immutable `chunk_id`, insurer, PDF source, one-based
   PDF page and original text. Map 50+50 query IDs; preserve metadata.
4. Reproduce its query-independent chunk-to-entity/relation graph construction,
   using source text alone (never relevance labels, target pages, H1 question
   answers, or the 15 graph-selected complex questions). Freeze LLM, prompts,
   extraction seed, model versions, failures, graph triples, and chunk links.
   Keep policy-specific facts scoped to the correct insurer/document.
5. Run official-style semantic seeds -> graph guided traversal/expansion ->
   KG-based filtering and organization. Export the order of original chunk IDs.
   If the original reranker/model is changed, label the configuration
   **KG2RAG-inspired adaptation**, not 'faithful KG2RAG replication'.
6. Run control conditions with the SAME embedding model, candidates and budget:
   seed-only, seed + expansion, full KG2RAG, and optionally same KG2RAG method
   using IKO-Auto's frozen G+ to assess graph-coverage limitations.
7. For each split, export `results/task_c/kg2rag_rankings.csv` with columns
   `split,method,question_id,rank,chunk_id` and preferably all Top-20 ranks.
   Max five output chunks are scored at Top-5. Do not mix retrieval passages
   with generated responses; keep each 170/45 indexed chunk as evaluation unit.
8. Reuse FINAL reconciled 3,384-row qrels, not only the 533 H1 labels, nor a
   reconstructed file silently promoted to final. Calculate coverage of newly
   retrieved chunks. Missing judgments must be marked UNKNOWN, never 0.
   Evaluate partial lower/upper Hit@5/MRR@5 when necessary. Compute full
   P@5/nDCG@5 only when judgments support them.
9. Use fixed evaluation code and consider five-policy document clustering.
   Present descriptive paired differences and limitations, not population-level
   causal claims. Output per-question ranks, full config, model hashes,
   evaluation summary, and code for reproducibility.
10. Once tested, add Section 6.18 or another clearly placed supplementary
    subsection with new Table 14j after Table 14i; do not insert Table 14j
    before the earlier tables. Compare M2, M8, dense-only, KG2RAG seed-only,
    full KG2RAG and a KG2RAG expansion-only control. Update discussion and refs.

## Fairness and integrity requirements
* One insurer-specific booklet per source; prevent cross-insurer contractual
  answers from being misclassified relevant.
* Pre-register seed K, hop count, reranking, organization, LLM models/prompts;
  tuning is permitted only on Development, with H1 frozen for reporting.
* Keep ALL model-derived KG relations traceable to their original chunk.
* Separate the 15 pre-existing graph-derived complex questions; they are not
  independently selected test questions for KG2RAG.
* If reproducing the official method needs GPU/Ollama BGE or licenses, record
  these facts; do not publish numbers from an unrun adapter.

## Expected command after KG2RAG returns rankings
`python reproduce/task_c/score_rankings.py --root . --rankings results/task_c/kg2rag_rankings.csv --qrels labels/deep_pool/final_3384.csv`

This script provides strict pool-relative Top-5 scores when all retrieved
candidates are judged and conservative bounds when they are not.
