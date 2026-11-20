#!/usr/bin/env python3
"""Optional independently verifiable standards-engine run for Comment 7.

Install with: python -m pip install rdflib pyshacl owlrl
Run: python scripts/run_standard_engines.py

This script FAILS if standard engines are missing. It will never silently substitute
our offline checker or claim a reasoner result that has not been produced.
"""
from pathlib import Path
import json, hashlib, sys
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, OWL

try:
    import pyshacl
    from pyshacl import validate
    import owlrl
    from owlrl import DeductiveClosure, OWLRL_Semantics
except ImportError as exc:
    print('ERROR: Required general-purpose engine unavailable:', exc, file=sys.stderr)
    print('Install: python -m pip install rdflib pyshacl owlrl', file=sys.stderr)
    sys.exit(2)

ROOT=Path(__file__).resolve().parents[1]
SHAPES=ROOT/'shapes/iko_auto_evidence_shapes.ttl'
PROFILE=ROOT/'semantic_profile/iko_auto_semantic_profile_PROPOSED.ttl'
OUT=ROOT/'results'/'standard_engines';OUT.mkdir(parents=True,exist_ok=True)
companion=Graph().parse(PROFILE,format='turtle')
results={
  'engines':{'pyshacl':getattr(pyshacl,'__version__','unknown'), 'owlrl':getattr(owlrl,'__version__','unknown')},
  'scope':'SHACL SPARQL + Core validation on frozen graphs; OWL-RL closure only on copies enriched with optional companion profile (not the published retrieval graphs)',
}
for stem in ['G0','Gplus']:
    source=ROOT/'source'/('G0_original_frozen.ttl' if stem=='G0' else 'Gplus_extended_frozen.ttl')
    data=Graph().parse(source,format='turtle')
    conformance, report_graph, report_text=validate(
        data_graph=data,
        shacl_graph=Graph().parse(SHAPES,format='turtle'),
        inference='rdfs',
        advanced=True,
        abort_on_first=False,
        meta_shacl=True,
        allow_warnings=False,
        allow_infos=False,
        serialize_report_graph=False,
    )
    report_graph.serialize(OUT/(stem+'_pyshacl_report.ttl'),format='turtle')
    (OUT/(stem+'_pyshacl_report.txt')).write_text(str(report_text),encoding='utf-8')
    # Explicit copy: the companion is diagnostic and MUST NOT alter the frozen input.
    combined=data+companion
    initial=set(combined)
    DeductiveClosure(OWLRL_Semantics, rdfs_closure=True).expand(combined)
    # The difference is already counted via len(combined) - len(initial).
    # RDFLib Graph has no .difference() method; do not call it.
    inferred_inverses=[]
    for prop,inv in companion.subject_objects(OWL.inverseOf):
        for subj,obj in data.subject_objects(inv):
            if (obj,prop,subj) in combined and (obj,prop,subj) not in initial:
                inferred_inverses.append((obj,prop,subj))
    clashes=[]
    # owlrl's deductions are a rules-based fragment, not full OWL 2 DL reasoning.
    for node in set(combined.subjects(RDF.type,None)):
        typs=set(combined.objects(node,RDF.type))
        for c,d in companion.subject_objects(OWL.disjointWith):
            if c in typs and d in typs:
                clashes.append({'individual':str(node),'type1':str(c),'type2':str(d)})
    owl_nothing=list(set(combined.subjects(RDF.type,OWL.Nothing)))
    results[stem]={
        'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'shacl_conforms':bool(conformance),
        'owl_rl_rule_closure_triples_total':len(combined),
        'owl_rl_additional_triples':len(combined)-len(initial),
        'owl_rl_missing_as_owl_nothing':len(owl_nothing),
        'owl_rl_profile_disjointness_conflicts':len(clashes),
        'companion_inverses_inferred':len(set(inferred_inverses)),
        'note':'OWL RL reasoning is not a full OWL 2 DL consistency check. Lack of conflicts under this profile does not prove semantic completeness or retrieval effectiveness.',
    }
    print(stem,'SHACL conforms:',bool(conformance),'OWL-RL disjointness clashes:',len(clashes),'new inferred triples:',len(combined)-len(initial))
    if not conformance or clashes or owl_nothing:
        print('Validation found issues. Review the reports.',file=sys.stderr)
        (OUT/'standard_engine_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        sys.exit(1)
(OUT/'standard_engine_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('Standard-engine validation complete. Raw reports written under results/standard_engines/')
