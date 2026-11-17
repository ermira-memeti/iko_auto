# IKO-Auto ontology v1 (research draft)

- `iko_auto_v1.ttl`: OWL 2 ontology serialized as Turtle; draft classes, subclass declarations, object and datatype properties.
- `synonyms.json`: small, hand-curated demonstration synonym lexicon; not learned from the corpus.
- `retrieval_relations.json`: **hand-curated retrieval cue expansion** informed by ontology relations; **not** RDF graph traversal, logical inference, or policy-specific reasoning.
- `competency_questions.md`: proposed questions; `cq_schema.rq` illustrates schema inspection.
- `validate_ontology.py`: optional RDF parsing and structural validation using `rdflib`; this does not prove logical consistency or domain correctness.

`https://example.org/iko-auto/v1#` is a placeholder namespace, not a hosted public artifact. This schema and lexicon are original proposed additions; neither was present in the supplied projects. No claim of expert validation, formal reasoner consistency, or empirical retrieval improvement is made.
