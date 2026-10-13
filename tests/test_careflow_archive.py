"""Archive boundaries and context-only reuse of the original claims index."""
from datetime import date
import json
import zipfile

import pytest

from clinical_intelligence.careflow.archive import safe_index, retrieve_context, verify_context
from clinical_intelligence.careflow.contracts import Case
from clinical_intelligence.careflow.demo import referral_case
from clinical_intelligence.careflow.engine import evaluate
from test_general_claims import archive


@pytest.mark.parametrize('kind,pid,enc', [('referral', 'P1', 'E1'), ('prior_authorization', 'P2', 'E2')])
def test_original_context_is_isolated_and_never_automatically_satisfies_documentation(tmp_path, kind, pid, enc):
    path = archive(tmp_path)
    index = safe_index(path)
    raw = referral_case(patient=pid, request='ARCHIVE-REQUEST', request_type=kind)
    raw['request']['encounter_id'] = enc
    request = Case.model_validate_json(json.dumps(raw)).request
    result = retrieve_context(index, request, received_at=date(2026, 10, 10))
    assert result['sources'] and not result['facts']
    assert result['source_association'] == 'ENCOUNTER_CONTEXT_ONLY'
    assert verify_context(index, result)['original_archive_reverified']
    assert all(s['patient_id'] == pid and s['encounter_id'] == enc for s in result['sources'])
    assert all(s['original_locator']['archive_sha256'] == index.archive_sha256 for s in result['sources'])
    original = {s.source_id: s for s in index.sources.values()}
    for source in result['sources']:
        assert source['content'] == original[source['source_id']].fields
        assert source['original_locator']['original_row_sha256'] == original[source['source_id']].original_row_sha256
    raw['sources'] += result['sources']
    packet = evaluate(Case.model_validate_json(json.dumps(raw)))
    assert packet['readiness'] == 'NEEDS_EVIDENCE'
    assert next(c for c in packet['checks'] if c['requirement'] == 'clinical_summary')['status'] == 'INSUFFICIENT_EVIDENCE'


def test_existing_original_byte_verifier_rejects_changed_fields(tmp_path):
    index = safe_index(archive(tmp_path))
    raw = referral_case(patient='P1')
    raw['request']['encounter_id'] = 'E1'
    request = Case.model_validate_json(json.dumps(raw)).request
    context = retrieve_context(index, request, received_at=date(2026, 10, 10))
    context['sources'][0]['content']['CODE'] = 'ALTERED'
    with pytest.raises(ValueError, match='Original row/content/identity mismatch'):
        verify_context(index, context)


@pytest.mark.parametrize('pid,enc', [('UNKNOWN-PATIENT', 'E1'), ('P1', 'E2')])
def test_archive_rejects_unresolved_identity(tmp_path, pid, enc):
    raw = referral_case(patient=pid)
    raw['request']['encounter_id'] = enc
    request = Case.model_validate_json(json.dumps(raw)).request
    with pytest.raises(ValueError):
        retrieve_context(safe_index(archive(tmp_path)), request, received_at=date(2026, 10, 10))


def test_missing_encounter_retains_gap_instead_of_borrowing_context(tmp_path):
    raw = referral_case(patient='P1')
    raw['request']['encounter_id'] = None
    request = Case.model_validate_json(json.dumps(raw)).request
    result = retrieve_context(safe_index(archive(tmp_path)), request, received_at=date(2026, 10, 10))
    assert not result['sources'] and result['missing_information']


@pytest.mark.parametrize('kind', ['csv', 'non_csv'])
def test_archive_limits_include_every_member_before_indexing(tmp_path, kind):
    path = archive(tmp_path)
    with zipfile.ZipFile(path, 'a', compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr('oversized.csv' if kind == 'csv' else 'oversized.bin', b'0' * 4096)
    with pytest.raises(ValueError, match='MEMBER_SIZE_LIMIT'):
        safe_index(path, max_member_bytes=3000)
    with pytest.raises(ValueError, match='TOTAL_SIZE_LIMIT'):
        safe_index(path, max_total_bytes=5000)
    with pytest.raises(ValueError, match='COMPRESSED_SIZE_LIMIT'):
        safe_index(path, max_archive_bytes=32)
