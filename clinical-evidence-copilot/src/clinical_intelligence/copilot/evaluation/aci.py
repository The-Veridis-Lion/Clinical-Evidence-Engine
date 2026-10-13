"""Published ACI development inputs and source-grounded AI label normalization."""
import csv
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

from ..models import digest
from .datasets import file_hash,verify_manifest
from .matching import ReferenceFact,structured_match


LABEL_TYPE='ACI published reference note + Luna/high structured normalization; AI-assisted, not independent clinical gold'


def load_aci_development(folder,manifest,split='validation'):
    verify_manifest(manifest)
    if split not in {'train','validation'}:
        raise ValueError('ACI final test text is sealed; development loader permits train/validation only')
    frozen=manifest['splits'][split]; path=Path(folder)/frozen['file']
    if file_hash(path)!=frozen['sha256']: raise ValueError('ACI official file changed after freeze')
    with path.open(encoding='utf-8-sig',newline='') as f: records=list(csv.DictReader(f))
    if len(records)!=frozen['denominator']: raise ValueError('ACI frozen denominator changed')
    expected={r['encounter_id']:r for r in frozen['encounters']}
    if len(expected)!=len(records) or set(expected)!={r['encounter_id'] for r in records}:
        raise ValueError('ACI frozen encounter identities changed')
    for row in records:
        identity=row['encounter_id']; item=expected[identity]
        if digest(row['dialogue'])!=item['dialogue_hash'] or digest(row['note'])!=item['reference_hash']:
            raise ValueError('ACI frozen input/reference content changed')
        yield dict(case_id=identity,group_id='ACI:'+identity,input_kind='dialogue',text=row['dialogue'],
            reference=row['note'],reference_type=LABEL_TYPE,partition='development',source_revision=manifest['revision'],
            official_split=split,prior_used=item['prior_used'])


def reference_extraction_record(record):
    # Explicit separate document: its note never enters the dialogue extractor.
    return {**record,'case_id':'reference-note:'+record['case_id'],'input_kind':'note','text':record['reference']}


def packet_references(packet):
    packet.verify()
    evidence={e.evidence_id:e.model_dump() for e in packet.evidence}
    result=[]
    for item in packet.facts:
        f=item.assertion
        fields={key:getattr(f,key) for key in ['polarity','temporality','experiencer','assertion_basis','clinical_status']}
        if f.attributes:
            fields.update({'attributes.'+k:v for k,v in f.attributes.model_dump().items()})
        fields={k:v for k,v in fields.items() if v is not None}
        result.append(ReferenceFact(reference_id='ref-'+digest([packet.content_hash,item.fact_id])[:16],
            concept=f.concept or f.original_term,allowed_categories=[f.category],fields=fields,
            reference_type=LABEL_TYPE,raw_reference=dict(reference_packet_hash=packet.content_hash,
                source_sha256=packet.source.sha256,source_fact_id=item.fact_id,
                original_fact=item.original_fact,assertion=f.model_dump(),
                evidence=[evidence[e] for e in item.evidence_ids],extraction_metadata=packet.extraction_metadata)))
    return result


def run_aci_development(folder,manifest,root,*,slots_path,review=True,luna_provider=None,sol_provider=None):
    from ...clinical_notes.dataset import write_json
    from ...clinical_notes.runner import SingleDispatchProvider
    from ...provider import ProviderConfig
    from ..models import now
    from .execution import CONFIG,AttemptLedger,freeze_run,run_extraction,run_adjudication,aggregate
    from .concurrency import LunaSlots
    records=list(load_aci_development(folder,manifest))
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    # All original dialogue and label-normalization note inputs frozen before calls.
    identity=freeze_run(root,records+[reference_extraction_record(r) for r in records],manifest)
    ledger=AttemptLedger(root/'requests.sqlite3',identity);slots=LunaSlots(slots_path)
    if luna_provider is None: SingleDispatchProvider(ProviderConfig(model='gpt-6-luna',reasoning_effort='high')).preflight()
    if review and sol_provider is None: SingleDispatchProvider(ProviderConfig(model='gpt-6.1-sol',reasoning_effort='high')).preflight()
    lock=root/'runner.lock'
    with lock.open('x',encoding='utf-8') as f:f.write(json.dumps({'started_at':now(),'kind':'aci_validation'}))
    def progress(results):
        value=aggregate(results,ledger,expected_denominator=len(records))
        value['reference_projection_failures']=sum(r['reference_packet_status']!='valid' for r in results)
        value['acceptance_passed']=value['acceptance_passed'] and value['reference_projection_failures']==0
        value['input_extraction_denominator']=len(records)*2
        value['reference_normalization_method']=LABEL_TYPE
        return value
    results=[]
    try:
        def extract(record):
            note=run_extraction(reference_extraction_record(record),root,identity,ledger,slots,provider=luna_provider)
            p=run_extraction(record,root,identity,ledger,slots,provider=luna_provider)
            match=structured_match(p,packet_references(note))
            dest=root/'cases'/digest(record['case_id'])[:20]
            write_json(dest/'reference-provenance.json',dict(published_note=record['reference'],
                published_note_sha256=digest(record['reference']),normalization_packet_hash=note.content_hash,
                normalization_source_hash=note.source.sha256,normalization_status=note.extraction_status,
                label_type=LABEL_TYPE,official_split=record['official_split']),immutable=True)
            write_json(dest/'raw-match.json',match,immutable=True)
            return record,p,note,match
        with ThreadPoolExecutor(max_workers=CONFIG['luna_workers']) as pool:
            inputs=list(pool.map(extract,records))
        def adjudicate(item):
            record,p,note,match=item
            assisted=run_adjudication(record,p,match,root,identity,ledger,provider=sol_provider) if review else None
            return dict(case_id=record['case_id'],packet_status=p.extraction_status,
                reference_packet_status=note.extraction_status,match=match,assisted=assisted)
        with ThreadPoolExecutor(max_workers=CONFIG['sol_workers']) as pool:
            for future in as_completed([pool.submit(adjudicate,item) for item in inputs]):
                results.append(future.result());write_json(root/'progress.json',progress(results))
                print(json.dumps({'stage':'aci_adjudication','completed':len(results),'denominator':len(records)}),flush=True)
        results.sort(key=lambda r:r['case_id'])
        write_json(root/'case-results.json',results,immutable=True)
        value=progress(results);value.update(run_hash=identity['run_hash'],partition='development',dataset='ACI-BENCH',official_split='validation')
        write_json(root/'results.json',value,immutable=True)
        return value
    finally:lock.unlink(missing_ok=True)
