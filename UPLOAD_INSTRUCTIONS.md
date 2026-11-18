# GitHub supplement — no manual folder creation required with GitHub Desktop

Copy the **contents** of the reviewer-comment-3 supplement ZIP into the local clone of `ermira-memeti/iko_auto` and merge folders. Do not delete any existing files. Commit and push. The following relative paths must exist for Appendix A to be accurate:

- `labels/graph_coverage/COMMENT3_SUBMITTED_100_SUPPORT_LABELS.csv`
- `results/graph_coverage/COMMENT3_GRAPH_SUPPORT_COUNTS.csv`
- `results/graph_coverage/COMMENT3_AUTHOR_SOURCE_CHECKS.csv`
- `results/graph_coverage/COMMENT3_FIVE_DIRECT_RETRIEVAL.csv`
- `reproduce/verify_comment3_coverage.py`

After upload, run `python reproduce/verify_comment3_coverage.py` from the repository root, and then update `PUBLIC_ARTIFACT_MANIFEST.json` with the SHA-256 checksums of all new files (if that manifest tracks the release as a whole). Do not upload raw assessor forms or third-party insurance PDFs without permission.
