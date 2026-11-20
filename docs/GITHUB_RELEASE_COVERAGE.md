# Upload coverage against the prior GitHub release package
Audited local input: `IKO_Auto_RAG_Starter(1).zip` (20 Nov 2026).
Compared with: `IKO_Auto_GitHub_Upload_20261117.zip` (previously prepared
release archive, NOT direct live GitHub inspection).

Already in that earlier release: code in src, tests, M1-M8 outputs, historical
labels for Development/H1, original ontology and its G0/G+ graphs, question
CSVs, fusion/gate plots and results. This archive does not duplicate them.

Added here: Comment7 SHACL shapes and standard-engine results; Comment8
stronger baselines, chunk/parameter diagnostics and public text-free Top20
rank lists; Task C validation/scoring scripts; provenance-release guidance.

Still missing from provided full local folder, so NOT fabricated:
- source and verified final decision export for 11 reconstructed deep-pool
  labels in `C4_MASTER_3384_OBSERVED_VS_RECONSTRUCTED.csv`;
- seven reproducible SQL/SPARQL query pairs plus SQLite normalized control
  (no `.sqlite`, `.db`, or `.sql` found outside `.venv` in uploaded ZIP);
- faithful KG2RAG run and outputs.

Preserve archived historical and deep-pool numerical results separately.
Do not overwrite original run artifacts with posthoc results.
