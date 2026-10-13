"""Predeclared mechanical material oracles; this is fixture construction only.

No candidate engine is called while expectations are assembled or frozen.
Readiness labels are documentation states, never insurer approval labels.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from ...claims_engine.split import load_split
from ..archive import safe_index, retrieve_context, verify_context
from ..contracts import Case
from ..demo import referral_case, supplemental
from .acceptance import freeze_materials
from .corpus import canonical, write_once

SUMMARY = {
    'positive': ('SUPPORTED', 'DOCUMENTATION_READY'),
    'explicit_contrary': ('NOT_SUPPORTED', 'NOT_SUPPORTED'),
    'missing': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'unknown': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'conflict': ('CONFLICTED', 'CONFLICTED'),
    'wrong_patient': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'wrong_request': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'wrong_service': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'wrong_code_system': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'wrong_encounter': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'late_source': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'unknown_availability': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'invalid_locator': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'future_actual': ('INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'future_order': ('SUPPORTED', 'DOCUMENTATION_READY'),
    'authorized_amendment': ('SUPPORTED', 'DOCUMENTATION_READY'),
    'unknown_authority': ('CONFLICTED', 'CONFLICTED'),
    'false_authority': ('CONFLICTED', 'CONFLICTED'),
    'excluded_amendment': ('SUPPORTED', 'DOCUMENTATION_READY'),
}
CONDITIONAL = {
    'trigger_false': (False, None, 'NOT_APPLICABLE', 'DOCUMENTATION_READY'),
    'trigger_unknown': (None, True, 'INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'trigger_true_missing': (True, None, 'INSUFFICIENT_EVIDENCE', 'NEEDS_EVIDENCE'),
    'trigger_true_supported': (True, True, 'SUPPORTED', 'DOCUMENTATION_READY'),
    'trigger_true_contrary': (True, False, 'NOT_SUPPORTED', 'NOT_SUPPORTED'),
    'trigger_conflict': ('conflict', True, 'CONFLICTED', 'CONFLICTED'),
    'inapplicable_conflicting_material': (False, 'conflict', 'NOT_APPLICABLE', 'CONFLICTED'),
}


def freeze_original_material_demo(archive, split_path, output):
    split = load_split(split_path)
    patients = [row['patient_id'] for row in split['partitions']['development'][:6]]
    if len(patients) != 6:
        raise ValueError('Six original development patients required; no holdout/reserve source reuse')
    index = safe_index(archive, allowed_patients=set(patients))
    if index.archive_sha256 != split['archive_sha256']:
        raise ValueError('Source/split hash mismatch')
    cases, verified = [], []
    names = sorted(set(SUMMARY) | set(CONDITIONAL))
    for ordinal, patient in enumerate(patients):
        encounter = [s for s in index.tables['encounters.csv'] if s.patient_id == patient][-1].original_id
        for kind in ('referral', 'prior_authorization'):
            for structured in (False, True):
                for name in names:
                    case_id = f'MATERIAL-{ordinal}-{kind}-{int(structured)}-{name}'
                    request = 'REQUEST-' + case_id
                    raw = referral_case(patient=patient, request=request, case_id=case_id, request_type=kind, structured=structured)
                    raw['request']['encounter_id'] = encounter
                    for source in raw['sources']:
                        source['encounter_id'] = encounter
                    # Attach original context, but do not synthesize claims/facts from it.
                    context = retrieve_context(index, Case.model_validate_json(json.dumps(raw)).request,
                                               received_at=date(2026, 10, 10))
                    raw['sources'] += context['sources']
                    if name == names[0] and kind == 'referral' and not structured:
                        verified.append(verify_context(index, context))
                    def add(requirement, value, *, amendment=None, authority=None):
                        text = (f'{request}: {requirement} is explicitly present.' if value is True else
                                f'{request}: {requirement} is explicitly absent.' if value is False else
                                f'{request}: {requirement} is unknown in the supplied record.')
                        extra = supplemental(requirement, value, text, patient=patient, request=request,
                                             encounter=encounter, structured=structured, amends=amendment, authority=authority)
                        raw['sources'] += extra['sources']; raw['facts'] += extra['facts']
                        return extra
                    expected = {'CF-DOC-001': 'SUPPORTED', 'CF-DOC-002': 'SUPPORTED', 'CF-DOC-003': 'SUPPORTED',
                                'CF-DOC-004': 'NOT_APPLICABLE', 'CF-DOC-005': 'NOT_APPLICABLE'}
                    expected.update({'CF-REF-001': 'SUPPORTED'} if kind == 'referral' else
                                    {'CF-PA-001': 'SUPPORTED', 'CF-PA-002': 'SUPPORTED'})
                    if name in SUMMARY:
                        expected['CF-DOC-003'], overall = SUMMARY[name]
                        values = [] if name == 'missing' else [None] if name == 'unknown' else (
                            [True, False] if name == 'conflict' else [False] if name == 'explicit_contrary'
                            or name in {'authorized_amendment', 'unknown_authority', 'false_authority'} else [True])
                        additions = [add('clinical_summary', value) for value in values]
                        if name.startswith('wrong_'):
                            latest = additions[-1]
                            fact, source = latest['facts'][0], latest['sources'][0]
                            if name == 'wrong_encounter': source['encounter_id'] = 'UNRELATED-ENCOUNTER'
                            elif name == 'wrong_patient': fact['patient_id'] = source['patient_id'] = 'UNRELATED-PATIENT'
                            elif name == 'wrong_request': fact['request_id'] = 'UNRELATED-REQUEST'
                            elif name == 'wrong_service': fact['service_code'] = 'unrelated-service'
                            else: fact['code_system'] = 'unrelated-code-system'
                        if name == 'late_source': additions[-1]['sources'][0]['available_at'] = '2026-10-20'
                        if name == 'unknown_availability': additions[-1]['sources'][0]['available_at'] = None
                        if name == 'invalid_locator':
                            ref = additions[-1]['facts'][0]['evidence'][0]
                            ref['field' if structured else 'span_id'] = 'nonexistent-original-locator'
                        if name in {'future_actual', 'future_order'}:
                            latest = additions[-1]
                            source, fact = latest['sources'][0], latest['facts'][0]
                            source.update(source_kind='structured_record', record_type='observation' if name == 'future_actual' else 'order',
                                          event_date='2026-11-01', content={'statement': fact['statement'], 'documented': True})
                            fact['evidence'] = [{'source_id': source['source_id'], 'field': 'statement'}]
                        if name in {'authorized_amendment', 'unknown_authority', 'false_authority', 'excluded_amendment'}:
                            old = additions[-1]['facts'][0]
                            auth = True if name in {'authorized_amendment', 'excluded_amendment'} else None if name == 'unknown_authority' else False
                            new = add('clinical_summary', name != 'excluded_amendment', amendment=old['fact_id'], authority=auth)
                            if name == 'excluded_amendment': new['sources'][0]['available_at'] = '2026-10-20'
                    else:
                        add('clinical_summary', True)
                        # Replace the baseline explicit false trigger with independent new source text.
                        removed = {f['evidence'][0]['source_id'] for f in raw['facts'] if f['requirement'] == 'investigation_required'}
                        raw['facts'] = [f for f in raw['facts'] if f['requirement'] != 'investigation_required']
                        raw['sources'] = [s for s in raw['sources'] if s['source_id'] not in removed]
                        trigger, document, expected['CF-DOC-004'], overall = CONDITIONAL[name]
                        for value in [True, False] if trigger == 'conflict' else [trigger]:
                            add('investigation_required', value)
                        if document is not None:
                            for value in [True, False] if document == 'conflict' else [document]:
                                add('investigation_result', value)
                    cases.append({'scenario_id': case_id, 'partition': 'development' if ordinal < 3 else 'holdout',
                                  'case': raw, 'expected_checks': expected, 'expected_readiness': overall})
    root = Path(output)
    specification = {'schema_version': 'careflow-material-oracles/2', 'summary_scenarios': SUMMARY,
                     'conditional_scenarios': CONDITIONAL, 'scenario_names': names,
                     'patient_count': 6, 'request_types': ['referral', 'prior_authorization'], 'document_formats': ['text', 'structured'],
                     'selection': 'first six existing frozen general-claims development patients; first three material-dev, remainder material-holdout',
                     'original_archive_sha256': index.archive_sha256, 'original_source_verifications': verified,
                     'oracles_created_before_candidate_evaluation': True,
                     'boundary': 'Fixed source/rule mechanics only; constructed documents, no medical/insurance approval gold.'}
    write_once(root / 'specification.json', (canonical(specification) + '\n').encode('utf-8'))
    return freeze_materials(cases, root)
