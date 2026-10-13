"""Optional original-byte verification, separate from clinical meaning and retrieval recall."""
import zipfile
from pathlib import Path
from .retrieval import records, sha, source_date, TYPES

VERSION = 'claims-review-archive-verification/1'


def verify_archive(retrieved, archive_path):
    path = Path(archive_path)
    if not path.is_file():
        raise ValueError('Original archive unavailable: original archive not reverified')
    archive_sha = sha(path.read_bytes())
    if archive_sha != retrieved['archive']['sha256']:
        raise ValueError('Original archive SHA mismatch')
    sources = retrieved['case']['sources']
    groups = {}
    for source in sources:
        loc = source.get('original_locator') or {}
        name = loc.get('source_file')
        if name not in TYPES or source['source_kind'] != 'structured_record' or source['origin'] != 'synthea_export':
            raise ValueError('Source has no supported original CSV locator')
        groups.setdefault(name, []).append(source)
    manifest = {m['path']: m for m in retrieved['archive']['members']}
    if len(manifest) != len(retrieved['archive']['members']):
        raise ValueError('Duplicate manifest members')
    with zipfile.ZipFile(path) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Duplicate original archive members')
        for name, selected in groups.items():
            if name not in z.namelist() or name not in manifest:
                raise ValueError('Original member missing')
            raw = z.read(name); member_sha = sha(raw)
            if member_sha != manifest[name]['sha256'] or len(raw) != manifest[name]['bytes']:
                raise ValueError('Original member SHA/size mismatch')
            needed = {}
            for source in selected:
                number = source['original_locator'].get('data_record_number')
                if type(number) is not int or number < 1:
                    raise ValueError('Invalid original data-record locator')
                needed.setdefault(number, []).append(source)
            found = set(); count = 0
            for number, row, start, end, row_sha in records(raw):
                count += 1
                for source in needed.get(number, []):
                    found.add(number); loc = source['original_locator']
                    column = 'DATE' if name == 'observations.csv' else 'START'
                    day = source_date(row.get(column))
                    enc = (row.get('Id') if name == 'encounters.csv' else row.get('ENCOUNTER')) or None
                    expected_id = f'SYNTHEA-{Path(name).stem.upper()}-{number}'
                    valid = (loc.get('archive_sha256') == archive_sha and loc.get('source_file_sha256') == member_sha
                             and loc.get('original_row_sha256') == row_sha
                             and loc.get('physical_line_start') == start and loc.get('physical_line_end') == end
                             and loc.get('date_column') == column and source['source_id'] == expected_id
                             and source['content'] == row and source['patient_id'] == row.get('PATIENT')
                             and source['encounter_id'] == enc and source['record_type'] == TYPES[name]
                             and source['event_date'] == (day.isoformat() if day else None))
                    if not valid:
                        raise ValueError(f'Original row/content/identity mismatch: {source["source_id"]}')
            if found != set(needed) or count != manifest[name]['rows']:
                raise ValueError('Original row missing or member count mismatch')
    return {'version': VERSION, 'mode': 'verified_archive', 'original_archive_reverified': True,
            'archive_sha256': archive_sha, 'verified_source_count': len(sources),
            'scope': 'All supplied clinical CSV source content, row bytes, locators, patient/encounter and printed event dates.',
            'availability_and_event_link_metadata_verified': False,
            'retrieval_completeness_verified': False, 'official_origin_authenticated': False}
