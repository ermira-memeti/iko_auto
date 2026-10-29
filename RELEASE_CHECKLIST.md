# Before publishing the GitHub release

1. Replace `[INSERT GITHUB URL]` / `<URL>` placeholders in the manuscript with the real repository URL.
2. Create a fixed release or tag, recommended: `v1.0-paper`.
3. Add the release/tag or commit hash to the manuscript Data and Code Availability section.
4. Decide whether to keep the conservative all-rights-reserved `LICENSE` or replace it with an open-source license (for example MIT or Apache-2.0).
5. Do **not** upload the five insurer PDFs.
6. Run `python -m pytest -q tests`.
7. Run `python reproduce/recalculate_development_public.py` and `python reproduce/recalculate_h1_public.py`; verify they match Tables 6 and 7 in the paper.
8. Check `PUBLIC_ARTIFACT_MANIFEST.json` after any final file changes.
