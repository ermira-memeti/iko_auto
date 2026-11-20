# Reviewer 1 Comment 8 baseline reproduction
This directory preserves the original `comment8.py` under a self-contained
research subtree with code snapshots, questions, graph, original ranking references,
and source-file hashes. Original source PDFs are intentionally excluded.

Reproduction (with appropriate local PDFs and Python dependencies installed):
`python reproduce/supplementary_baselines/comment8.py verify`
`python reproduce/supplementary_baselines/comment8.py run`

Re-running models additionally requires torch, sentence-transformers and their
model downloads. The published summary `results/supplementary_baselines/` is
the archived result of earlier runs, not proof those scripts have been executed
by this update package.

The file `comment8_rankings_top20_no_text.csv` contains IDs, ranks and scores,
but deliberately omits raw PDF text. It contains five method outputs, including
a *custom* GRAPH_NEIGHBOR baseline. This is NOT the published KG2RAG method.
Retain label-coverage uncertainty in all newly compared methods.
