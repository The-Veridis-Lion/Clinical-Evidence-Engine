"""Actual source extraction -> explicit intake -> real HTTP readiness/audit.

Attachment indices are supplied request associations, never inferred by clinical
concept or source phrase. Existing valid extraction is final and reused.
"""
import json
from datetime import date
from pathlib import Path
from typing import Literal
from pydantic import Field

from .contracts import Contract, Identifier, Case, ClinicalBinding, Requirement
from .clinical_context import prepared_context
from .extraction import extract_document
from .evaluation.batch import source_for
from .evaluation.corpus import canonical, write_once
from .scheduler import CallLedger
from .engine import evaluate
from .workflow import run_http_workflow
from .requirement_support import atomic_support_review, ATOMIC_REVIEW_VERSION


class AttachmentSelection(Contract):
    binding_id: Identifier
    binding_source_id: Identifier
    requirement: Requirement
    fact_indices: list[int] = Field(min_length=1)
    document_role: Literal['clinical_summary'] | None = None
    clinical_purpose: Literal['therapeutic','diagnostic','unknown'] = 'unknown'
    # Optional independent source judgments, never an approval/reviewer stamp.
    # The shared verifier checks their original identities and exact spans.
    independent_reviews: list[dict] = Field(default_factory=list)


def run_source_workflow(database, output, document_path, case_path, attachments_path,
                        cache, ledger_path, *, received_at=None, provider=None):
    # A requested historical snapshot cannot manufacture evidence availability.
    # Validate before files, reservation or dispatch. This date is explicit intake
    # provenance; it does not authenticate the receiving institution.
    try:
        receipt_date = date.fromisoformat(received_at).isoformat()
    except (TypeError, ValueError):
        raise ValueError('An independent receipt date (YYYY-MM-DD) is required') from None
    record = json.loads(Path(document_path).read_text(encoding='utf-8'))
    # Only the raw source contract enters Luna; no intake/reference/expected state.
    raw = json.loads(Path(case_path).read_text(encoding='utf-8'))
    raw_targets = json.loads(Path(attachments_path).read_text(encoding='utf-8'))
    targets = [AttachmentSelection.model_validate_json(canonical(t)) for t in raw_targets]
    if not targets:
        raise ValueError('Explicit attachment selections are required; no relevance is inferred')
    original = Case.model_validate_json(canonical(raw))
    if original.request.patient_id != 'DATASET:'+record['case_group']:
        raise ValueError('Original document group does not match explicit request patient')
    if original.request.encounter_id is not None and original.request.encounter_id != record['case_group']:
        raise ValueError('Original source encounter does not match the explicit request encounter')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    ledger = CallLedger(ledger_path)
    before_attempts = len(ledger.attempts())
    result = extract_document(record, cache, ledger, provider=provider)
    source = source_for(record,result['extraction'],received_at=receipt_date)
    augmented = {**raw, 'sources': [*raw['sources'],source],
                 'clinical_context': [*raw.get('clinical_context',[]),
                    {'source_id':source['source_id'],'extraction':result['extraction']}]}
    case = Case.model_validate_json(canonical(augmented))
    context = next(c for c in prepared_context(case) if c['source_id']==source['source_id'])
    binding_sources,bindings,source_reviews = [],[],[]
    original_source = next(s for s in case.sources if s.source_id == source['source_id'])
    for target, supplied in zip(targets,raw_targets):
        if len(target.fact_indices)!=len(set(target.fact_indices)) or any(
                type(i) is not int or not 0<=i<len(context['facts']) for i in target.fact_indices):
            raise ValueError('Attachment needs unique, existing original fact indices')
        binding = ClinicalBinding(binding_id=target.binding_id,binding_source_id=target.binding_source_id,
            patient_id=case.request.patient_id,request_id=case.request.request_id,
            service_code=case.request.service_code,code_system=case.request.code_system,
            requirement=target.requirement,clinical_fact_ids=[context['facts'][i]['context_fact_id'] for i in target.fact_indices],
            document_role=target.document_role,clinical_purpose=target.clinical_purpose).model_dump(mode='json')
        bindings.append(binding)
        reviews = [atomic_support_review(original_source, context['facts'][i],
            requirement=target.requirement, reviews=target.independent_reviews) for i in target.fact_indices]
        source_reviews.extend(reviews)
        binding_sources.append({'source_id':target.binding_source_id,'patient_id':case.request.patient_id,
            'encounter_id':case.request.encounter_id,'available_at':receipt_date,
            'recorded_at':None,'event_date':None,'event_link_id':None,'record_type':'order',
            'source_kind':'structured_record','origin':'request_intake',
            'content':{'clinical_binding':binding,'original_attachment_selection':supplied,
                       'atomic_support_reviews':reviews,
                       'original_document_id':record['document_id'],'source_sha256':result['identity']['source_sha256']}})
    write_once(root/'atomic-source-reviews.json',(canonical(source_reviews)+'\n').encode('utf-8'))
    packet = evaluate(case)
    update = {'expected_revision':1,'sources':binding_sources,'facts':[],'clinical_bindings':bindings,
              'intake':{'actor_id':'source-workflow-intake','actor_type':'intake_service','basis_revision':1,
                        'basis_packet_sha256':packet['packet_sha256'],
                        'reason':'Explicit request attachments received; no clinical reviewer opinion is inferred.'}}
    write_once(root/'case.json',(canonical(case.model_dump(mode='json'))+'\n').encode('utf-8'))
    write_once(root/'update.json',(canonical(update)+'\n').encode('utf-8'))
    receipt = run_http_workflow(database,root/'http',root/'case.json',root/'update.json')
    current = [r for r in ledger.attempts()[before_attempts:] if r['document_id']==record['document_id']]
    receipt.update({'document_id':record['document_id'],'source_sha256':result['identity']['source_sha256'],
                    'source_receipt':{'version':'careflow-source-receipt/1','received_at':receipt_date,
                        'review_as_of':case.review_as_of.isoformat(),
                        'basis':'independently_supplied_receipt_date'},
                    'clinical_facts':len(result['extraction']['facts']),'actual_new_attempts':len(current),
                    'extraction_identity':result['identity'],'accepted_attempt':result['attempt'],
                    'extraction_usage':result['usage'],'review_calls':0,
                    'source_verification':{'atomic_review_version':ATOMIC_REVIEW_VERSION,
                        'proof_count':len(source_reviews),'actual_new_verification_model_calls':0,
                        'status_counts':{s:sum(r['source_verification']['status']==s for r in source_reviews)
                            for s in sorted({r['source_verification']['status'] for r in source_reviews})},
                        'risk_route_counts':{s:sum(r['source_verification']['risk_route']==s for r in source_reviews)
                            for s in sorted({r['source_verification']['risk_route'] for r in source_reviews})},
                        'boundary':'Shared source-support verification, not independent clinical gold or source-signature authentication.'},
                    'attachment_association':'explicit input selection, not inferred relevance',
                    'readiness_boundary':'Documentation engineering; no clinical approval or insurer eligibility.'})
    write_once(root/'receipt.json',(canonical(receipt)+'\n').encode('utf-8'))
    return receipt
