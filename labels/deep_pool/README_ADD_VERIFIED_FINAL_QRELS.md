# Final 3,384-pair reference - publication gate
The uploaded local folder contains a 3,384-row **reconstruction** CSV with 7
source-anchor entries inferred and 4 Grade1-to-Grade2 harmonizations not
individually supported by original assessor-batch files. This working reconstruction
is NOT reproduced here or silently represented as a signed independent final label file.

When the already-completed human decisions have been reconciled, export the
FINAL file as `labels/deep_pool/final_3384.csv` using these columns:
`dataset,question_id,chunk_id,relevance`.

Expected rows: 3,384 unique (dataset,question_id,chunk_id) keys; grades
0:3029, 1:243, 2:112. This count check only establishes *internal consistency*,
not documentary or adjudication provenance. Keep private reviewer workbooks
and any unrestricted source quotations out of the public repository.

If the final 3,384-row file is unavailable, Task C can still compute judged
coverage and conservative Hit/MRR bounds; do not report unknown candidate
judgments as Grade 0 or publish fully pooled nDCG values.
