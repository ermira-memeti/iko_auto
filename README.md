# IKO-Auto: research reproducibility release (2026-11-17)

This folder is a **public-upload candidate** assembled from the preserved IKO-Auto project,
the final expanded-fusion evaluation, and the finalized extension-topic gate diagnostic.
It does not assert that these files have already been uploaded to GitHub or independently
verified on the remote repository.

## Data and experimental separation

1. **Historical Development:** 50 questions; 519 adjudicated question-passage pairs.
   See `questions/development_questions_50.csv`, `labels/development_adjudicated_519_public.csv`,
   `results/development/`.
2. **Historical H1:** 50 questions on the same five policies; 533 adjudicated pairs.
   See `questions/h1_questions_50.csv`, `labels/h1_adjudicated_533_public.csv`, `results/h1/`.
3. **Post-hoc fusion ablations:** 658 Development and 667 H1 labeled pairs, including
   301 additional independently graded/regraded pairs; see `labels/fusion_expanded_relevance_public.csv`
   and `results/fusion/`. Results are **not** a new holdout evaluation.
4. **Post-hoc extension-topic gate diagnostic:** 50 AI-assisted topic-balanced questions;
   EU and BK separately evaluated routing and 327 question-passage pairs, with 48 grounded
   questions contributing to reported gate/retrieval metrics. See `questions/GATE26_50_Candidate_Questions.csv`,
   `labels/gate/`, `results/gate/`, `provenance/gate/`.
   The two ambiguous questions remain in the public question and judgment files, but do not
   contribute to the primary metric denominator. These are **not** naturally occurring user queries.

## Reproduction from saved outputs

Run `python reproduce/verify_release.py --section all` to recompute and cross-check the
main reported retrieval metrics, confusion matrix, and experiment counts against the
text-minimized rankings and relevance labels. The check does **not** reproduce the
original PDF -> chunking -> retrieval execution because that requires the original
third-party PDFs and the exact environment; historic software dependency versions
were not completely recorded.

This release includes original evaluation and retrieval source files in `src/`,
`ontology/`, and the **unchanged G0 and G+** graph exports in `outputs/`.
Historical research scripts are preserved under `reproduce/original_scripts/` with
their original hard-coded research working-directory paths; they are archived for
provenance, not advertised as portable one-command rerun tools.

## Text-minimization and privacy

- Public ranked outputs preserve method, question ID, rank, and passage ID, **not copied
  insurance policy passage text**. The expert judgment outputs include final grades
  but not raw identifiable reviewer worksheets, private notes, or AI-proposal workbooks.
- The original five insurer policy PDFs are third-party documents and have **not** been
  included. See `source_documents/SOURCE_POLICY_SHA256.json` for frozen source hashes.
  Obtain the identical PDFs legally and check redistribution rights before publishing them.
- RDF source quotations still appear in the ontology graph exports. Their reuse and
  redistribution should be checked against source-document rights before public upload.
- The candidate question file and graph artifacts do not constitute evidence of transfer
  to new insurers or unseen policy documents.

## Documentation consistency

The manuscript's Appendix A uses shorthand filenames in some rows. The complete
repository-relative paths are listed in `APPENDIX_A_PATH_MAP.md`. In particular,
`GATE26_Run_Provenance.json` ends in `.json`, **not** `.jso`.

The frozen candidate manifest's original input-file hashes refer to the historical
unmodified internal files. Public ranking/pool CSVs in this release omit policy passages
for redistribution; their own hashes are recorded separately in `PUBLIC_ARTIFACT_MANIFEST.json`.

## Before public upload

1. Review `UPLOAD_CHECKLIST.md` and the graph quotation rights.
2. Compare these additions with existing GitHub files before overwriting; the remote
   repository was not accessible for verification when this package was made.
3. Publish all files in this folder, preserving directory paths, not the outer ZIP file.
4. Link a fixed Git commit/release from the manuscript, update the Data Availability Statement,
   and archive the submission version of `PUBLIC_ARTIFACT_MANIFEST.json`.
5. Do not upload `.venv`, cached Python packages, draft experiments, raw reviewer workbooks,
   AI screening suggestions, unlicensed policy PDFs, or manuscript drafts under review.
