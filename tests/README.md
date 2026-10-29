# Self-contained public tests

This directory contains the self-contained tests that can run without the third-party insurer PDFs or historical private/demo data folders.

Run:

```bash
python -m pytest -q tests
```

The broader historical development test suite depended on local demo, annotation, and research-version folders that are intentionally not included in the public paper release.
