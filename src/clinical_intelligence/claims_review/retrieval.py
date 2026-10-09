"""Stream original Synthea CSV records with an explicit retrieval/availability scope."""
import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen
from pydantic import model_validator
from .contracts import Contract, ClaimInput, ReviewContext, CaseInput, SourceInput
from .prepare import digest, prepare_case
from .review import load_policy

VERSION = 'claims-review-retrieval/0.1'
URL = 'https://synthetichealth.github.io/synthea-sample-data/downloads/latest/synthea_sample_data_csv_latest.zip'
# A deliberately finite source-code vocabulary, not a billing crosswalk.
CODES = {'observations.csv': {'4548-4'}, 'conditions.csv': {'44054006', '46635009'},
         'medications.csv': {'860975'}, 'procedures.csv': {'43396009'}}
TYPES = {'observations.csv': 'observation', 'conditions.csv': 'condition',
         'medications.csv': 'medication_order', 'procedures.csv': 'procedure', 'encounters.csv': 'encounter'}


class RetrievalQuery(Contract):
    schema_version: str
    case_id: str
    claim: ClaimInput
    review_context: ReviewContext

    @model_validator(mode='after')
    def supported(self):
        if self.schema_version != VERSION:
            raise ValueError('Unsupported retrieval query version')
        return self


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def download(path):
    """Bound the official sample download; never overwrite an existing archive."""
    path = Path(path)
    if path.exists():
        raise ValueError('Archive exists; use it explicitly or choose a new immutable destination')
    path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(URL, timeout=60) as response:
        raw = response.read(12_000_001)
        if len(raw) > 12_000_000:
            raise ValueError('Official sample exceeded the 12 MB download bound')
        metadata = {'url': URL, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                    'sha256': sha(raw), 'bytes': len(raw),
                    'last_modified': response.headers.get('Last-Modified'),
                    'etag': response.headers.get('ETag')}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(m.file_size for m in archive.infolist()) > 150_000_000:
            raise ValueError('Uncompressed archive exceeds this sample workflow bound')
    path.write_bytes(raw)
    path.with_suffix('.download.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    return metadata


def records(raw):
    """Preserve field strings and physical CSV row spans, including multiline rows."""
    lines = raw.splitlines(keepends=True)
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    reader.fieldnames
    previous = reader.line_num
    for number, row in enumerate(reader, 1):
        if None in row or any(v is None for v in row.values()):
            raise ValueError('Malformed CSV row')
        yield number, row, previous+1, reader.line_num, sha(b''.join(lines[previous:reader.line_num]))
        previous = reader.line_num


def source_date(value):
    if not value:
        return None
    try:
        # Printed date component; no timezone/receipt conversion.
        if len(value)>10:
            datetime.fromisoformat(value.replace('Z','+00:00'))
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def retrieve(path, query, *, snapshot_available_at=None, metadata=None):
    started = perf_counter()
    path = Path(path)
    archive_sha = sha(path.read_bytes())
    overrides = metadata or {}
    discovered = []; excluded = []; auxiliary = []; members = []; encounters = set()
    with zipfile.ZipFile(path) as archive:
        if sum(m.file_size for m in archive.infolist()) > 150_000_000:
            raise ValueError('Uncompressed archive exceeds sample workflow bound')
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive member names')
        missing = set(TYPES) - set(names)
        if missing:
            raise ValueError(f'Missing required original tables: {sorted(missing)}')
        # First discover clinical records, then resolve encounter/claim references.
        order = list(CODES) + ['encounters.csv', 'claims.csv']
        for name in order + sorted(set(names)-set(order)):
            raw = archive.read(name)
            member = {'path': name, 'sha256': sha(raw), 'bytes': len(raw), 'rows': 0}
            members.append(member)
            if not name.endswith('.csv'):
                member['retrieval_role'] = 'unsupported_file';continue
            for number, row, start, end, row_sha in records(raw):
                member['rows'] += 1
                if name not in order:
                    member['retrieval_role'] = 'outside_finite_clinical_table_scope';continue
                sid = f'SYNTHEA-{Path(name).stem.upper()}-{number}'
                pid = row.get('PATIENT', row.get('PATIENTID'))
                enc = row.get('ENCOUNTER', row.get('APPOINTMENTID'))
                column = 'DATE' if name == 'observations.csv' else 'START' if name != 'claims.csv' else 'CURRENTILLNESSDATE'
                day = source_date(row.get(column))
                loc = dict(source_file=name, source_file_sha256=member['sha256'], archive_sha256=archive_sha,
                           data_record_number=number, physical_line_start=start, physical_line_end=end,
                           original_row_sha256=row_sha, date_column=column,
                           date_interpretation='printed source date component, not a timezone conversion', original_ehr_available_at=None)
                identity = dict(source_id=sid, patient_id=pid, encounter_id=enc, event_date=day.isoformat() if day else None, locator=loc)
                reason = 'patient_mismatch' if pid != query.claim.patient_id else None
                if not reason and name in CODES and row.get('CODE') not in CODES[name]:
                    reason = 'outside_declared_source_code_scope'
                if not reason and name == 'medications.csv' and day is not None and day < query.review_context.history_start:
                    reason = 'medication_outside_requested_history_window'
                if not reason and name in {'encounters.csv', 'claims.csv'} and (row.get('Id') if name=='encounters.csv' else enc) not in encounters:
                    reason = 'not_referenced_by_relevant_clinical_record'
                if reason:
                    excluded.append({**identity, 'reason': reason});continue
                if name == 'claims.csv':
                    auxiliary.append({**identity, 'raw_content': row,
                                      'role': 'same-patient encounter-associated claim; HbA1c billing identity NOT VERIFIED',
                                      'counted_as_test': False});continue
                override = overrides.get(sid, {})
                if override and (override.get('patient_id') != pid or not override.get('evidence')):
                    raise ValueError('Row metadata needs matching patient identity and explicit evidence')
                available = source_date(override.get('available_at')) if 'available_at' in override else snapshot_available_at
                if override.get('available_at') is not None and 'available_at' in override and available is None:
                    raise ValueError('Invalid explicit availability date')
                link = override.get('event_link_id')
                # Same encounter never establishes a shared test event.
                source = SourceInput.model_validate_json(json.dumps(dict(
                    source_id=sid, patient_id=pid, encounter_id=(row.get('Id') if name=='encounters.csv' else enc) or None,
                    available_at=available.isoformat() if available else None, origin='synthea_export',
                    source_kind='structured_record', recorded_at=None, event_date=day.isoformat() if day else None,
                    record_type=TYPES[name], event_link_id=link, content=row,
                    availability_basis='explicit_case_metadata' if override else 'export_snapshot_received' if available else 'unknown',
                    original_locator={**loc, 'scope_metadata_evidence': override.get('evidence'),
                                      'code_scope': sorted(CODES.get(name, []))})))
                discovered.append(source)
                if name in CODES and enc:
                    encounters.add(enc)
        if set(overrides) - {s.source_id for s in discovered}:
            raise ValueError('Metadata references rows not discovered in the declared patient/code scope')
    case = CaseInput(schema_version='claims-review-prep/0.1', case_id=query.case_id,
                     claim=query.claim, review_context=query.review_context, sources=discovered)
    prepared = prepare_case(case, load_policy(), input_label='retrieved-original-archive')
    excluded += [{'source_id': e['source_ref']['source_id'], 'locator': next(s.original_locator for s in discovered if s.source_id == e['source_ref']['source_id']),
                  'reason': e['reason'], 'stage': 'preparation'} for e in prepared['excluded_sources']]
    download_file = path.with_suffix('.download.json')
    download_meta = json.loads(download_file.read_text(encoding='utf-8')) if download_file.exists() else None
    if download_meta and download_meta['sha256'] != archive_sha:
        raise ValueError('Archive differs from its recorded download identity')
    return dict(version=VERSION, query=query.model_dump(mode='json'), archive={'sha256':archive_sha,
                'bytes':path.stat().st_size,'members':members,'download':download_meta},
                case=case.model_dump(mode='json'), case_sha256=digest(case.model_dump(mode='json')),
                prepared=prepared, matched_source_ids=[s['source_id'] for s in prepared['source_candidates']],
                excluded_sources=excluded, linked_records=auxiliary, latency_seconds=perf_counter()-started,
                scope={'source_codes':{k:sorted(v) for k,v in CODES.items()}, 'full_archive_scanned':True,
                       'clinical_history_completeness':'not inferred from archive completeness',
                       'original_ehr_availability':None,'snapshot_available_at':snapshot_available_at.isoformat() if snapshot_available_at else None,
                       'independent_event_linkage':'unknown unless explicitly evidenced in separate metadata',
                       'real_model_calls':0})
