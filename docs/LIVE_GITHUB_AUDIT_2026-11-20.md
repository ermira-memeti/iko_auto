# Live GitHub comparison (20 November 2026)

Repository: https://github.com/ermira-memeti/iko_auto
Default branch: `main`; visibility: public.

At audit: 179 tracked file blobs and 208 git tree entries, with 179 unique file paths. Core `src`, `tests`, `questions`, `outputs/v6`, `outputs/v8_2`, `labels` and the original `results` files were already present, along with Comment 3 coverage artifacts.

The incremental update carries previously absent folders for:
* `ontology/validation`
* `reproduce/ontology_validation`
* `results/ontology_validation`
* `reproduce/supplementary_baselines`
* `results/supplementary_baselines`
* `reproduce/task_c`
* `labels/deep_pool` (instructions only)
* additional `docs` and reproducibility metadata.

The repository root `.gitignore` already exists and is intentionally **excluded** from this package.

Main root README currently starts with `IKO-Auto: research reproducibility release (2026-11-17)` and describes itself as a public-upload candidate. After adding this package, update that opening description to identify the repository as an existing public reproducibility release and summarize the additional validated artifacts.

Important outstanding files (NOT included or fabricated): finalized grade provenance export `labels/deep_pool/final_3384.csv`; SQL schema/data/query comparison scripts for §7.4; third-party PDF permissions; executed published KG2RAG implementation and result files.

The original `.gitignore` and already committed historical results should not be overwritten. The package is an add-on, not an independent standalone research repository. Verify the GitHub tree again before uploading if other collaborators have pushed changes since this audit.
