# Ontology validation - self-contained reproduction tree

Frozen G0/G+ graphs, companion profile, shapes, scripts and reference results are preserved together.
With `rdflib`, `pyshacl`, and `owlrl` installed, run from the repository root:

```bash
python reproduce/ontology_validation/scripts/run_standard_engines.py
python reproduce/ontology_validation/scripts/validate_comment7_offline.py
```

The script output and frozen source graphs correspond to Section 7.7 of the manuscript.
The standalone browseable validation artifacts are also under `ontology/validation`.
This is not an OWL 2 DL soundness or contractual completeness proof.
