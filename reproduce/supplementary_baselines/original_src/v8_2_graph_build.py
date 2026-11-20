"""Source-verified V8.2 development ontology extension from frozen V6 RDF.

This module NEVER changes the original V6 graph. The five new coverage paths
were designed after V8 development queries failed, hence are NOT held-out tests.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .graph_builder import IKO_BASE, require_rdflib, save_graph, slug

ROOT=Path(__file__).resolve().parents[1]
ADDITIONS=ROOT/'data/research_v8_2/draft_additions.json'
FROZEN_V6_GRAPH_SHA256='34b350540630667a65c42277c52e29e5f669dc9899ab1c1380eb593f048f5ad7'
EXPECTED_SOURCE_HASHES={
    'axa_car_policy.pdf':'0c0356ad5424c433a0c07ea77b9d35259bea9468a84c8c73252c60144dd388f8',
    'admiral_car_policy.pdf':'fcbe3696d110630f27f1af8aff1dcc3964397166d4a60053dbb09ec13a4b3d77',
    'aviva_car_policy.pdf':'9b6b0774129e9821e33c217eda60054ef5ed7308a2f056c771d12d11227121db',
    'directline_car_policy.pdf':'b1b40c4ee2b78d96656782d12591b3f6a69f16397a5479cd47f8ff58959c7b8d',
    'esure_car_policy.pdf':'c88c00478abf625c59fffdd39043ac771c5cccc3c35ff2ba078476c84d02aeb3',
}

def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate_source_files(docs):
    folder=Path(docs).resolve()
    if not folder.is_dir():raise FileNotFoundError(folder)
    actual={}; named={}
    for filename, expected in EXPECTED_SOURCE_HASHES.items():
        found=[p for p in folder.rglob('*.pdf') if p.name==filename]
        if len(found)!=1:raise ValueError(f'Need exactly one source named {filename}; found {len(found)}')
        file=found[0].resolve()
        if not file.is_relative_to(folder):raise ValueError(f'Source path outside corpus: {file}')
        digest=sha256(file)
        if digest!=expected:raise ValueError(f'Wrong policy edition for {filename}: expected {expected}, got {digest}.')
        actual[file.relative_to(folder).as_posix()]=digest
        named[filename]=file
    return actual,named

def build_v8_2_graph(docs,out,base_graph=None,audit_out=None):
    """Add five proof-linked coverage paths to exact frozen V6 RDF graph.

    No prior triples are deleted or modified; original graph remains available
    for unchanged graph-only baselines.
    """
    sources,files=validate_source_files(docs)
    frozen=Path(base_graph) if base_graph else ROOT/'outputs/v6/iko_auto_five_insurers_v6.ttl'
    if not frozen.is_file() or sha256(frozen)!=FROZEN_V6_GRAPH_SHA256:
        raise ValueError('Original V6 RDF graph is missing or differs from the frozen V8.1 SHA-256. Do not replace it.')
    additions=json.loads(ADDITIONS.read_text(encoding='utf-8'))
    if len(additions['additions'])!=5:raise ValueError('Exactly five development additions expected')
    Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL=require_rdflib()
    g=Graph().parse(str(frozen),format='turtle')
    baseline=set(g)
    IKO=Namespace(IKO_BASE)
    from pypdf import PdfReader
    pages={}
    records=[]
    for record in additions['additions']:
        pid=record['policy_id']; coverage=record['coverage']; evidence=coverage['evidence']
        policy=next((s for s in g.subjects(RDF.type,IKO.AutoPolicy)
                     if str(g.value(s,IKO.policyIdentifier))==pid),None)
        if policy is None:raise ValueError(f'Original V6 policy missing {pid}')
        versions=list(g.objects(policy,IKO.hasVersion))
        if len(versions)!=1:raise ValueError(f'Expected exactly one version for {pid}')
        filename=Path(evidence['document']).name
        pdf=files[filename]
        page=evidence['page']
        if not isinstance(page,int) or page<1:raise ValueError('PDF evidence requires a 1-based page number')
        key=(filename,page)
        if key not in pages:
            reader=PdfReader(str(pdf))
            if page>len(reader.pages):raise ValueError(f'PDF page outside booklet: {filename} {page}')
            pages[key]=' '.join((reader.pages[page-1].extract_text() or '').split())
        quote=' '.join(evidence['quote'].split())
        if not quote or quote not in pages[key]:
            raise ValueError(f'Quote not in source PDF verbatim on {filename}, page {page}: {quote[:80]}')
        source_path=pdf.relative_to(Path(docs).resolve()).as_posix()
        qid=hashlib.sha256((source_path+'\n'+str(page)+'\n'+quote).encode()).hexdigest()[:20]
        passage=IKO[f'passage_{qid}']
        g.add((passage,RDF.type,IKO.SourcePassage))
        g.add((passage,IKO.sourceDocumentId,Literal(source_path)))
        g.add((passage,IKO.sourcePage,Literal(page)))
        g.add((passage,IKO.sourceQuote,Literal(quote)))
        uri=IKO[f'{slug(pid)}_coverage_{slug(coverage["id"])}']
        if (uri,None,None) in g:raise ValueError(f'Existing coverage URI would be overwritten: {uri}')
        g.add((uri,RDF.type,IKO.Coverage))
        g.add((uri,RDFS.label,Literal(coverage['name'])))
        for alias in coverage.get('aliases',[]):g.add((uri,IKO.alias,Literal(alias)))
        g.add((uri,IKO.supportedBy,passage))
        version=versions[0];pred=IKO.hasCoverage
        g.add((version,pred,uri))
        aid=hashlib.sha256((str(version)+str(pred)+str(uri)+str(passage)).encode()).hexdigest()[:20]
        assertion=IKO[f'assertion_{aid}']
        g.add((assertion,RDF.type,IKO.RelationshipAssertion))
        g.add((assertion,IKO.assertionSubject,version))
        g.add((assertion,IKO.assertionPredicate,pred))
        g.add((assertion,IKO.assertionObject,uri))
        g.add((assertion,IKO.supportedBy,passage))
        records.append({'policy_id':pid,'development_question':record['development_question'],
                        'coverage_id':coverage['id'],'source_document':source_path,'page':page,
                        'source_quote':quote,'source_sha256':EXPECTED_SOURCE_HASHES[filename]})
    if not baseline.issubset(set(g)):raise AssertionError('Original V6 statements were changed')
    dest=Path(out)
    if dest.resolve()==frozen.resolve() or dest.name=='iko_auto_five_insurers_v6.ttl':
        raise ValueError('Refusing to overwrite original V6 RDF graph')
    save_graph(g,dest)
    audit={'status':additions['status'],
           'review_status':'SOURCE_VERIFIED_DRAFT_NOT_INDEPENDENTLY_HUMAN_REVIEWED',
           'origin':additions['design_origin'],
           'original_v6_graph_sha256':FROZEN_V6_GRAPH_SHA256,
           'enhanced_graph_sha256':sha256(dest),
           'base_triples_preserved':len(baseline),'new_triples':len(g)-len(baseline),
           'source_pdf_sha256':sources,'draft_additions_sha256':sha256(ADDITIONS),
           'created_utc':datetime.now(timezone.utc).isoformat(),
           'new_coverages':records,
           'limitation':'Selected after inspecting the V8 50-question development benchmark; not independent held-out evidence.'}
    audit_path=Path(audit_out) if audit_out else dest.with_suffix('.audit.json')
    audit_path.parent.mkdir(parents=True,exist_ok=True)
    audit_path.write_text(json.dumps(audit,indent=2,ensure_ascii=False),encoding='utf-8')
    return audit
