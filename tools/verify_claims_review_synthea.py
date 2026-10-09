"""Verify the supplied minimal slice, not the unavailable upstream archive."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from clinical_intelligence.claims_review.contracts import CaseInput


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'source_manifest.json').read_text(encoding='utf-8'))
    case = CaseInput.model_validate_json((directory / 'SYNTHEA-START-001.json').read_text(encoding='utf-8'))
    rows_by_locator = {}
    for table in manifest['exported_original_rows']:
        path = directory / table['path']
        if path.parent.resolve() != directory.resolve():
            raise ValueError('Subset path must remain within its directory')
        if hashlib.sha256(path.read_bytes()).hexdigest() != table['sha256']:
            raise ValueError(f'Subset digest mismatch: {path.name}')
        with path.open(encoding='utf-8', newline='') as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != table['data_rows'] or len(rows) != len(table['rows']):
            raise ValueError('Subset row count mismatch')
        for row, locator in zip(rows, table['rows'], strict=True):
            key = (locator['source_file'], locator['subset_data_record_number'])
            if key in rows_by_locator:
                raise ValueError('Duplicate row locator')
            rows_by_locator[key] = (row, locator)
    for source in case.sources:
        loc = source.original_locator
        row, original = rows_by_locator.pop((loc['source_file'], loc['subset_data_record_number']))
        if source.content != row or row['PATIENT'] != source.patient_id or row['ENCOUNTER'] != source.encounter_id:
            raise ValueError(f'Wrapper row/source identity mismatch: {source.source_id}')
        if any(loc[k] != v for k, v in original.items()):
            raise ValueError(f'Original locator changed: {source.source_id}')
        if loc['archive_sha256'] != manifest['archive']['sha256']:
            raise ValueError('Upstream archive identity mismatch')
        if source.event_date.isoformat() != row[loc['date_column']][:10]:
            raise ValueError('Printed source date changed')
        if source.availability_basis != 'export_snapshot_received' or loc['original_ehr_available_at'] is not None:
            raise ValueError('Export availability must not claim original EHR availability')
    if rows_by_locator:
        raise ValueError('Published slice contains unused rows')
    return {'status': 'PASSED', 'verified_subset_rows': len(case.sources),
            'subset_files': len(manifest['exported_original_rows']),
            'original_archive_redownload_or_hash_verification': 'NOT VERIFIED',
            'original_row_hashes': 'Preserved preparation provenance; not independently verified against the original archive.',
            'original_ehr_availability': None, 'clinical_validation': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('examples/claims_review/synthea'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(verify(args.directory), indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
