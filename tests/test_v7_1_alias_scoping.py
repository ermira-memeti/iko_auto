"""Regression tests: generic alias of another insurer must not empty results."""
import pytest
rdflib=pytest.importorskip('rdflib')
from src.graph_builder import IKO_BASE
from src.graph_retrieval import GraphIndex
from src.models import Chunk
from src.retrieval import InsuranceRetriever
from rdflib import Namespace,RDF,RDFS,Literal


def demo_stub():
    ns=Namespace(IKO_BASE)
    graph=rdflib.Graph()
    pol={}; ver={}; cover={}; docs={}
    for insurer in ('AXA','Admiral','Aviva','Direct Line','esure'):
        key=insurer.replace(' ','')
        policy=ns['P'+key]; version=ns['V'+key]; coverage=ns['C'+key]
        pol[insurer]=policy; ver[insurer]=version; cover[insurer]=coverage
        docs[insurer]=key.lower()+'.txt'
        graph.add((policy,RDF.type,ns.AutoPolicy))
        graph.add((policy,RDFS.label,Literal(insurer+' Car Insurance')))
        graph.add((policy,ns.alias,Literal(insurer)))
        graph.add((policy,ns.hasVersion,version))
        graph.add((version,ns.hasCoverage,coverage))
        graph.add((coverage,RDFS.label,Literal('Coverage '+insurer)))
    graph.add((cover['AXA'],ns.alias,Literal('damage')))
    graph.add((cover['AXA'],ns.alias,Literal('vehicle damage')))
    graph.add((cover['Direct Line'],ns.alias,Literal('accident')))
    graph.add((cover['Aviva'],ns.alias,Literal('vehicle damage')))
    graph.add((cover['Admiral'],ns.alias,Literal('motor protection')))
    # 'collision' remains a discriminative alias, prohibited under esure
    graph.add((cover['AXA'],ns.alias,Literal('collision')))
    index=GraphIndex.__new__(GraphIndex)
    index.g=graph;index.IKO=ns;index.RDFS=RDFS;index.policies=list(pol.values())
    index.policy_sources={pol[k]:{src} for k,src in docs.items()}
    index.assertions={};index.evidence_to_chunks={}
    return index

@pytest.mark.parametrize('question,expected_policy',[
    ('Does Admiral cover damage resulting from ordinary wear and tear?','Admiral'),
    ('What repair or replacement options exist for Direct Line accidental vehicle damage?','Direct Line'),
    ('What losses are described under esure Section 04 car-damage cover?','esure'),
    ('Does esure insure an accident deliberately staged by an insured driver?','esure'),
])
def test_generic_alias_of_other_insurer_does_not_block_named_policy(question,expected_policy):
    i=demo_stub();plan=i.plan(question)
    assert not plan.strict_no_match,plan.warnings
    assert plan.scoped_docs=={expected_policy.replace(' ','').lower()+'.txt'}


def test_discriminative_coverage_still_blocks_wrong_policy():
    plan=demo_stub().plan('Does esure cover collision?')
    assert plan.strict_no_match


def test_unmodeled_relation_falls_back_to_scoped_baseline():
    i=demo_stub()
    chunks=[Chunk(chunk_id='a:1',doc_id='a',source_path='axa.txt',page=1,start_word=0,end_word=6,
                  text='AXA car insurance damage policy and terms'),
            Chunk(chunk_id='e:1',doc_id='e',source_path='esure.txt',page=1,start_word=0,end_word=10,
                  text='esure accident deliberately staged may be excluded from car cover')]
    retriever=InsuranceRetriever(chunks)
    retriever.graph_index=i
    i.by_chunk={c.chunk_id:c for c in chunks}
    hits=retriever.search('Does esure insure an accident deliberately staged by an insured driver?',ontology_mode='graph')
    assert hits and all(h.chunk.source_path=='esure.txt' for h in hits)


def test_staged_insurance_question_uses_exclusion_relationship():
    i=demo_stub();ns=i.IKO
    c=ns['Cesure'];exclusion=ns['stageExclusion'];source=ns['sourcePage18']
    i.g.add((c,ns.hasExclusion,exclusion))
    i.g.add((exclusion,i.RDFS.label,Literal('Deliberately staged accident excluded')))
    i.g.add((exclusion,ns.alias,Literal('staged accident')))
    i.g.add((source,ns.sourceQuote,Literal('Any deliberately staged accident is not covered')))
    i.assertions[(c,ns.hasExclusion,exclusion)]=(source,)
    i.evidence_to_chunks[source]=['esure-p18-c1']
    plan=i.plan('Does esure insure an accident deliberately staged by an insured driver?')
    assert not plan.strict_no_match
    assert plan.scores.get('esure-p18-c1')==1.0
