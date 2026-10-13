"""Bounded adapter around PR #3's index; native records remain context only."""
from datetime import date
from pathlib import Path
import tempfile
import zipfile

from ..claims_engine.archive import ArchiveIndex, event_start
from ..claims_review.contracts import SourceInput
from ..claims_review.retrieval import source_date

TYPES = {'encounters.csv': 'encounter', 'observations.csv': 'observation',
         'conditions.csv': 'condition', 'procedures.csv': 'procedure',
         'medications.csv': 'medication_order'}


def safe_index(path, *, allowed_patients=None, max_archive_bytes=12_000_000,
               max_member_bytes=60_000_000, max_total_bytes=150_000_000):
    """Check all members before existing indexing, using a bounded immutable copy.

    The copy closes the path replacement race between preflight and ArchiveIndex.
    This does not alter or fix the shared unmerged PR's own CLI entry points.
    """
    with Path(path).open('rb') as stream:
        raw = stream.read(max_archive_bytes + 1)
    if len(raw) > max_archive_bytes:
        raise ValueError('COMPRESSED_SIZE_LIMIT')
    import io
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if any(member.file_size > max_member_bytes for member in members):
            raise ValueError('MEMBER_SIZE_LIMIT')
        if sum(member.file_size for member in members) > max_total_bytes:
            raise ValueError('TOTAL_SIZE_LIMIT')
    with tempfile.TemporaryDirectory(prefix='careflow-archive-') as root:
        snapshot = Path(root) / 'verified.zip'
        snapshot.write_bytes(raw)
        index = ArchiveIndex(snapshot, allowed_patients=allowed_patients)
    # All original field/byte hashes already live in the existing in-memory index.
    index.path = Path(path)
    return index


def retrieve_context(index, request, *, received_at: date):
    patient, status = index.unique('patients.csv', request.patient_id)
    if patient is None:
        raise ValueError(f'REQUEST_PATIENT_{status}')
    result = {
        'schema_version': 'careflow-archive-context/1', 'request_id': request.request_id,
        'patient_id': request.patient_id, 'encounter_id': request.encounter_id,
        'archive_sha256': index.archive_sha256, 'received_at': received_at.isoformat(),
        'source_association': 'ENCOUNTER_CONTEXT_ONLY', 'sources': [], 'facts': [],
        'missing_information': ['Original notes, request-specific intent and documentary requirements are not established by CSV context.'],
        'boundary': 'No claim conversion, billing-code mapping, automatic clinical assertion, or ready judgment.',
    }
    if request.encounter_id is None:
        result['missing_information'].append('Explicit encounter identity is missing; no encounter context is borrowed.')
        return result
    encounter, status = index.unique('encounters.csv', request.encounter_id, request.patient_id)
    if encounter is None:
        raise ValueError(f'REQUEST_ENCOUNTER_{status}')
    rows = [encounter]
    for table in TYPES:
        if table != 'encounters.csv':
            rows += index.by_encounter.get((table, request.patient_id, request.encounter_id), [])
    for row in rows:
        locator = row.model_dump(mode='json')
        locator.pop('fields')
        locator.update(source_file=row.table, date_column='DATE' if row.table == 'observations.csv' else 'START')
        source = SourceInput(
            source_id=row.source_id, patient_id=request.patient_id, encounter_id=row.encounter_id,
            available_at=received_at, origin='synthea_export', source_kind='structured_record',
            recorded_at=None, event_date=source_date(event_start(row.fields)), record_type=TYPES[row.table],
            event_link_id=None, content=row.fields, availability_basis='export_snapshot_received',
            original_locator=locator,
        )
        result['sources'].append(source.model_dump(mode='json'))
    return result


def verify_context(index, context):
    """Reuse the existing independent original-byte verifier via its legacy envelope.

    Only its required legacy source label is projected; CareFlow/PR #3 IDs stay
    unchanged in saved packets. Original fields and byte locations are untouched.
    """
    from copy import deepcopy
    from ..claims_review.archive_verification import verify_archive
    sources = deepcopy(context['sources'])
    for source in sources:
        loc = source['original_locator']
        source['source_id'] = f"SYNTHEA-{Path(loc['source_file']).stem.upper()}-{loc['data_record_number']}"
    return verify_archive({'archive': {'sha256': context['archive_sha256'], 'members': index.members},
                           'case': {'sources': sources}}, index.path)
