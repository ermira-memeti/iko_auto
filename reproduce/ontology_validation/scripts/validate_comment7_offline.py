#!/usr/bin/env python3
"""IKO-Auto Comment 7 offline reproducible checks using RDFLib.

IMPORTANT: The included checker evaluates exactly the SHACL Core components in
shapes/iko_auto_evidence_shapes.ttl and its SHACL-SPARQL constraint. It is NOT a
certified general-purpose SHACL engine nor an OWL 2 DL consistency reasoner.
Install pySHACL/OWL-RL and use run_standard_engines.py for independent verification.
The frozen experimental graphs are never modified on disk.
"""
from __future__ import annotations
from pathlib import Path
import hashlib, json, platform, collections, sys
from rdflib import Graph, Namespace, Literal, URIRef, BNode
from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS, OWL, SH, XSD

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'source'; OUT=ROOT/'results'
NS=Namespace('https://example.org/iko-auto/v2#')
CV=Namespace('https://example.org/iko-auto/comment7/validation#')
REL=(NS.hasVersion,NS.hasCoverage,NS.hasExclusion,NS.hasException,NS.hasDeductible,NS.hasLimit,NS.hasClaimCondition)


def name(t, g=None):
    if isinstance(t,URIRef):
        if str(t).startswith(str(NS)): return 'iko:'+str(t).split('#')[-1]
        if str(t).startswith(str(CV)): return 'cv:'+str(t).split('#')[-1]
        if g is not None: return g.namespace_manager.normalizeUri(t)
    return str(t)


def inherited_types(g, individual):
    explicit=set(g.objects(individual,RDF.type)); closure=set(explicit); todo=list(explicit)
    while todo:
        current=todo.pop()
        for sup in g.objects(current,RDFS.subClassOf):
            if sup not in closure:
                closure.add(sup); todo.append(sup)
    return closure


def focus_nodes(data, shape):
    targets=set()
    for klass in shape.objects(None,SH.targetClass):
        for subj in set(data.subjects(RDF.type, None)):
            if klass in inherited_types(data,subj): targets.add(subj)
    for prop in shape.objects(None,SH.targetSubjectsOf): targets.update(data.subjects(prop,None))
    for node in shape.objects(None,SH.targetNode): targets.add(node)
    return sorted(targets, key=str)


def truthy_literal(v):
    return str(v).lower() in ('true','1')


def check_core(data, shapes):
    findings=[]
    checks=0
    counts={}
    def err(component,focus,path=None,value=None,source=None,detail=None):
        findings.append({'component':name(component,shapes),'focus':name(focus,data),
              'path':name(path,data) if path else None,'value':name(value,data) if value is not None else None,
              'source_shape':name(source,shapes) if source else None, 'detail':detail})
    for shape in sorted(set(shapes.subjects(RDF.type,SH.NodeShape)),key=str):
        focus=focus_nodes(data, GraphSlice(shapes,shape))
        counts[name(shape,shapes)]=len(focus)
        for node in focus:
            for prop_shape in shapes.objects(shape, SH.property):
                path=shapes.value(prop_shape,SH.path)
                if not isinstance(path, URIRef): raise ValueError('offline checker only supports direct-IRI paths')
                vals=list(data.objects(node,path));n=len(vals)
                min_count=shapes.value(prop_shape,SH.minCount);max_count=shapes.value(prop_shape,SH.maxCount)
                if min_count is not None:
                    checks+=1
                    if n<int(min_count):err(SH.MinCountConstraintComponent,node,path,source=shape,detail=f'{n} < {int(min_count)}')
                if max_count is not None:
                    checks+=1
                    if n>int(max_count):err(SH.MaxCountConstraintComponent,node,path,source=shape,detail=f'{n} > {int(max_count)}')
                kind=shapes.value(prop_shape,SH.nodeKind)
                cls=shapes.value(prop_shape,SH['class'])
                dtype=shapes.value(prop_shape,SH.datatype)
                min_len=shapes.value(prop_shape,SH.minLength)
                min_incl=shapes.value(prop_shape,SH.minInclusive)
                in_list=shapes.value(prop_shape,SH['in'])
                values_in=set(Collection(shapes,in_list)) if in_list is not None else None
                for v in vals:
                    if kind is not None:
                        checks+=1
                        valid=((kind==SH.IRI and isinstance(v,URIRef)) or
                               (kind==SH.Literal and isinstance(v,Literal)) or
                               (kind==SH.BlankNode and isinstance(v,BNode)))
                        if not valid:err(SH.NodeKindConstraintComponent,node,path,v,shape,'Wrong RDF node kind')
                    if cls is not None:
                        checks+=1
                        if cls not in inherited_types(data,v):err(SH.ClassConstraintComponent,node,path,v,shape,'Value not typed as required class, including subclass closure')
                    if dtype is not None:
                        checks+=1
                        if not isinstance(v,Literal) or (v.datatype or XSD.string)!=dtype:
                            err(SH.DatatypeConstraintComponent,node,path,v,shape,'Datatype does not match')
                    if min_len is not None:
                        checks+=1
                        if len(str(v))<int(min_len):err(SH.MinLengthConstraintComponent,node,path,v,shape,'String too short')
                    if min_incl is not None:
                        checks+=1
                        try: valid=(isinstance(v,Literal) and float(v)>=float(min_incl))
                        except (ValueError,TypeError): valid=False
                        if not valid:err(SH.MinInclusiveConstraintComponent,node,path,v,shape,'Numeric value below minimum')
                    if values_in is not None:
                        checks+=1
                        if v not in values_in:err(SH.InConstraintComponent,node,path,v,shape,'Value not in permitted list')
            for sparql_blank in shapes.objects(shape, SH.sparql):
                query=shapes.value(sparql_blank,SH.select)
                if query is None:continue
                # Match standard SHACL-SPARQL by evaluating the SELECT once over all focus nodes.
                # The query's $this projected values are the violating focus nodes.
                rows=list(data.query(str(query)))
                bad=set()
                for row in rows:
                    try:bad.add(row['this'])
                    except Exception:
                        if len(row):bad.add(row[0])
                checks+=1
                if node in bad:
                    err(SH.SPARQLConstraintComponent,node,source=shape,detail=str(shapes.value(sparql_blank,SH.message)))
    return {'conforms':not findings,'findings':findings,'component_checks':checks,'focus_nodes_by_shape':counts}

class GraphSlice:
    def __init__(self,g,s):self.g=g;self.s=s
    def objects(self,subj,pred):
        if subj is None: return (self.g.objects(self.s,pred))
        return self.g.objects(subj,pred)


def assertion_integrity(g):
    count_missing_direct=0; count_missing_reification=0; violations=[]
    for a in g.subjects(RDF.type,NS.RelationshipAssertion):
        s=g.value(a,NS.assertionSubject);p=g.value(a,NS.assertionPredicate);o=g.value(a,NS.assertionObject)
        if s is None or p is None or o is None or (s,p,o) not in g:
            count_missing_direct+=1;violations.append('missing asserted triple for '+name(a,g))
    for p in REL:
        for s,o in g.subject_objects(p):
            good=False
            for a in g.subjects(NS.assertionSubject,s):
                if (a,RDF.type,NS.RelationshipAssertion) in g and (a,NS.assertionPredicate,p) in g and (a,NS.assertionObject,o) in g and list(g.objects(a,NS.supportedBy)):
                    good=True;break
            if not good:count_missing_reification+=1;violations.append('missing evidence-backed reification for '+name(s,g)+' '+name(p,g)+' '+name(o,g))
    return {'reified_assertions_missing_direct_triple':count_missing_direct,'direct_contract_relations_without_complete_evidence_assertion':count_missing_reification,'issues':violations}


def ontology_profile(g,companion):
    merged=g+companion
    disjoint_pairs=set()
    for c,d in merged.subject_objects(OWL.disjointWith): disjoint_pairs.add(tuple(sorted((c,d),key=str)))
    bad=[]; inherited=0
    individual_nodes=set(merged.subjects(RDF.type,None))
    for node in individual_nodes:
        types=inherited_types(merged,node)
        inherited+=len(types)-len(set(merged.objects(node,RDF.type)))
        for c,d in disjoint_pairs:
            if c in types and d in types:
                bad.append({'individual':name(node,g),'type1':name(c,g),'type2':name(d,g)})
    inverses=[]
    for inverse,orig in merged.subject_objects(OWL.inverseOf):
        for s,o in g.subject_objects(orig):
            if (o,inverse,s) not in g:inverses.append((o,inverse,s))
    # Objects are not "wrong" under OWL open-world assumptions merely because
    # explicit type triples are missing; check typing against declared RDFS domain/range
    # and emit a count of inferences that could be made, not errors.
    infer_types=set()
    for p,domain in merged.subject_objects(RDFS.domain):
        for s,o in g.subject_objects(p):
            if domain not in inherited_types(merged,s):infer_types.add((s,domain))
    for p,rng in merged.subject_objects(RDFS.range):
        for s,o in g.subject_objects(p):
            if isinstance(o,URIRef) and rng not in (RDF.Property,RDFS.Class) and rng not in inherited_types(merged,o):infer_types.add((o,rng))
    return {'profile_disjoint_class_pairs':len(disjoint_pairs),'disjointness_clashes':bad,
            'new_inverse_triples_inferred_in_companion_only':len(set(inverses)),
            'inferred_type_assertions_from_existing_subclass_hierarchy':inherited,
            'domain_range_typing_consequences_not_explicitly_asserted':len(infer_types),
            'owl2_dl_consistency_proved':False,
            'note':'Targeted RDF/OWL vocabulary and inverse/disjointness checks only; full OWL 2 DL consistency reasoner was not executed.'}


def shacl_report(result):
    report=Graph();report.bind('sh',SH);report.bind('cv',CV)
    r=CV['OfflineSHACLReport'];report.add((r,RDF.type,SH.ValidationReport));report.add((r,SH.conforms,Literal(result['conforms'])))
    for i,f in enumerate(result['findings']):
        v=CV['Result'+str(i+1).zfill(3)];report.add((v,RDF.type,SH.ValidationResult));report.add((r,SH.result,v))
        report.add((v,SH.focusNode,URIRef(str(NS)+f['focus'].split(':',1)[1]) if f['focus'].startswith('iko:') else URIRef(f['focus'])))
        if f['path']:
            path=URIRef(str(NS)+f['path'].split(':',1)[1]) if f['path'].startswith('iko:') else URIRef(f['path']);report.add((v,SH.resultPath,path))
        report.add((v,SH.resultMessage,Literal(f['detail'] or 'Constraint violated')))
        component=URIRef(str(SH)+f['component'].split(':',1)[1]) if f['component'].startswith('sh:') else URIRef(f['component'])
        report.add((v,SH.sourceConstraintComponent,component))
    return report


def mutate_graph(g):
    def clone():return g+Graph()
    a=next(g.subjects(RDF.type,NS.RelationshipAssertion));sp=next(g.subjects(RDF.type,NS.SourcePassage))
    s=g.value(a,NS.assertionSubject);p=g.value(a,NS.assertionPredicate);o=g.value(a,NS.assertionObject)
    bad=[]
    h=clone();q=h.value(sp,NS.sourceQuote);h.remove((sp,NS.sourceQuote,q));bad.append(('missing_quote',h,'shacl'))
    h=clone();v=h.value(sp,NS.sourcePage);h.remove((sp,NS.sourcePage,v));h.add((sp,NS.sourcePage,Literal(0,datatype=XSD.integer)));bad.append(('zero_page',h,'shacl'))
    h=clone();h.remove((s,p,o));bad.append(('missing_direct_relation',h,'shacl'))
    h=clone();h.add((a,NS.assertionSubject,NS['invented_second_subject_for_negative_control']));bad.append(('duplicate_assertion_subject',h,'shacl'))
    h=clone();h.add((sp,RDF.type,NS.InsuranceEntity));bad.append(('disjoint_class_clash',h,'owl'))
    return bad


def main():
    OUT.mkdir(exist_ok=True)
    shapes=Graph().parse(ROOT/'shapes/iko_auto_evidence_shapes.ttl',format='turtle')
    companion=Graph().parse(ROOT/'semantic_profile/iko_auto_semantic_profile_PROPOSED.ttl',format='turtle')
    schema=Graph().parse(SRC/'iko_auto_v6.ttl',format='turtle')
    source_paths={'G0':SRC/'G0_original_frozen.ttl','Gplus':SRC/'Gplus_extended_frozen.ttl'}
    stats={}; negatives={}
    for key,path in source_paths.items():
        g=Graph().parse(path,format='turtle')
        out=check_core(g,shapes); assertc=assertion_integrity(g); owl=ontology_profile(g,companion)
        print(key,'triples',len(g),'core conforms',out['conforms'],'violations',len(out['findings']), 'OWL proposed clashes',len(owl['disjointness_clashes']))
        stats[key]={'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'triple_count':len(g),
              'class_instances':{name(c):len(set(g.subjects(RDF.type,c))) for c in (NS.AutoPolicy,NS.PolicyVersion,NS.Coverage,NS.Exclusion,NS.Exception,NS.Deductible,NS.CoverageLimit,NS.ClaimCondition,NS.SourcePassage,NS.RelationshipAssertion)},
              'shacl_offline':out,'assertion_integrity':assertc,'owl_targeted_companion':owl,
              'source_page_datatype_property_declaration_present':(NS.sourcePage,RDF.type,OWL.DatatypeProperty) in g,
              'source_chunk_id_values':len(list(g.triples((None,NS.sourceChunkId,None)))),
              'effective_date_values':len(list(g.triples((None,NS.effectiveDate,None))))}
        report=shacl_report(out);report.serialize(OUT/(key+'_offline_shacl_report.ttl'),format='turtle')
        for t,mutant,kind in mutate_graph(g):
            if kind=='shacl':
                test=check_core(mutant,shapes); detected=not test['conforms'];details=[v['component'] for v in test['findings']]
            else:
                test=ontology_profile(mutant,companion);detected=bool(test['disjointness_clashes']);details=test['disjointness_clashes']
            negatives[key+'/'+t]={'detected':detected,'violations':details}
            if not detected:raise AssertionError(f'negative control was missed: {key}/{t}')
    result={'research_scope':'IKO-Auto Reviewer 1 Comment 7; original G0/Gplus retained byte-identically',
           'offline_execution':{'engine':'RDFLib self-contained SHACL Core COMPONENT-SUBSET and SHACL-SPARQL checker',
                'rdflib_version':__import__('rdflib').__version__,'python_version':platform.python_version(),
                'general_purpose_shacl_engine_run':False,'full_owl_2_dl_reasoner_run':False,
                'limitations':'Validation follows the published shape constraints and graph integrity checks; certified pySHACL and OWL-RL rerun supplied separately, requires dependency installation.'},
           'source_schema':{'triples':len(schema), 'owl_classes':len(set(schema.subjects(RDF.type,OWL.Class))),
                'owl_object_properties':len(set(schema.subjects(RDF.type,OWL.ObjectProperty))),
                'owl_datatype_properties':len(set(schema.subjects(RDF.type,OWL.DatatypeProperty))),
                'owl_restrictions':len(set(schema.subjects(RDF.type,OWL.Restriction))),
                'owl_disjoint_with_triples':len(list(schema.triples((None,OWL.disjointWith,None)))),
                'owl_inverse_of_triples':len(list(schema.triples((None,OWL.inverseOf,None)))),
                'owl_cardinality_statements':sum(len(list(schema.triples((None,p,None)))) for p in [OWL.cardinality,OWL.minCardinality,OWL.maxCardinality,OWL.qualifiedCardinality,OWL.minQualifiedCardinality,OWL.maxQualifiedCardinality]),
                'sourcePage_declaration_missing':(NS.sourcePage,RDF.type,OWL.DatatypeProperty) not in schema},
           'shapes_total_triples':len(shapes), 'companion_owl_profile_triples':len(companion),
           'graphs':stats,'negative_controls':negatives}
    (OUT/'comment7_validation_offline.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    (OUT/'negative_controls.json').write_text(json.dumps(negatives,indent=2,ensure_ascii=False),encoding='utf-8')
    print('PASS: All 10 mutation controls detected.')
    print('Saved results:',OUT)

if __name__=='__main__': main()
