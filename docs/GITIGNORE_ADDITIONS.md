# Preserve existing repository `.gitignore`

The **live** `iko_auto/.gitignore` already excludes `.venv`, Python caches, OS/editor files, `H1_RESULTS`, generated logs, and `*.pdf`. It is safer to **retain this file unchanged** rather than replacing it with the first prepared package version, which did not contain the global PDF rule.

When new local experiment output folders are added, consider appending these patterns to the existing `.gitignore`:

```
.env
.env.*
*.pem
*.p12
*.key
reproduce/supplementary_baselines/data/policies/*.pdf
reproduce/task_c/local_policies/
results/task_c/local_cache/
external/
*.npy
*.npz
```

Review the last two patterns before adding if you intentionally track binary model artifacts. Note that `.gitignore` does **not** remove files that were already tracked by Git. Do not commit source policy PDFs, reviewer originals, credentials or confidential research records.
