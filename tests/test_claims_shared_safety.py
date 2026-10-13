"""Generic malformed-link coverage and archive bounds across all shared entries."""
import csv
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from clinical_intelligence.claims_engine.archive import ArchiveIndex
from clinical_intelligence.claims_engine.split import create_split
from clinical_intelligence.claims_engine.verification import verify_saved
from clinical_intelligence.claims_engine.workflow import process
from test_general_claims import archive


def replace_table(path, table, rows):
    with zipfile.ZipFile(path) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    entries[table] = stream.getvalue().encode()
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as result:
        for name, raw in entries.items():
            result.writestr(name, raw)


@pytest.mark.parametrize('linkage', ['blank', 'absent', 'ambiguous'])
@pytest.mark.parametrize('patient', ['P1', 'P2'])
def test_all_claims_roundtrip_preserves_unassigned_original_rows(tmp_path, linkage, patient):
    path = archive(tmp_path)
    patients = [{'Id': 'P1'}, {'Id': 'P2'}]
    if linkage == 'ambiguous':
        patients.append({'Id': patient})
    replace_table(path, 'patients.csv', patients)
    claims = [{'Id': 'CLAIM-A', 'PATIENTID': 'P1', 'APPOINTMENTID': 'E1'},
              {'Id': 'CLAIM-B', 'PATIENTID': 'P2', 'APPOINTMENTID': 'E2'},
              {'Id': 'CLAIM-UNASSIGNED', 'PATIENTID': '' if linkage == 'blank' else 'UNKNOWN' if linkage == 'absent' else patient,
               'APPOINTMENTID': ''}]
    replace_table(path, 'claims.csv', claims)
    index = ArchiveIndex(path)
    split = create_split(index, tmp_path / 'split.json')
    summary, ledger = process(index, split, output=tmp_path / 'batch')
    assert summary['metrics']['accounted_claim_rows'] == 3
    report = verify_saved(path, tmp_path / 'batch', split)
    assert report['status'] == 'PASS' and report['accounted_claims'] == 3
    assert report['unassigned_claim_rows'] == (2 if linkage == 'ambiguous' else 1)
    for partition, members in split['partitions'].items():
        selected = verify_saved(path, tmp_path / 'batch', split, partition=partition)
        assert selected['accounted_claims'] == sum(len(e['claim_ids']) for e in members)


@pytest.mark.parametrize('member_kind', ['clinical.csv', 'non-clinical.bin'])
@pytest.mark.parametrize('entry', ['index', 'saved-verifier', 'retrieval', 'source-verifier'])
def test_every_shared_entry_rejects_oversized_members_before_decompression(tmp_path, monkeypatch, member_kind, entry):
    from clinical_intelligence import archive_bounds
    from clinical_intelligence.claims_review.retrieval import retrieve, sha
    from clinical_intelligence.claims_review.archive_verification import verify_archive
    path = archive(tmp_path)
    with zipfile.ZipFile(path, 'a', compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(member_kind, b'x' * 4096)
    monkeypatch.setattr(archive_bounds, 'DEFAULT_LIMITS', archive_bounds.ArchiveLimits(member_bytes=2048))
    def forbidden(*args, **kwargs):
        raise AssertionError('A rejected archive must never open a decompressed member')
    monkeypatch.setattr(zipfile.ZipFile, 'open', forbidden)
    checksum = sha(path.read_bytes())
    actions = {'index': lambda: ArchiveIndex(path),
        'saved-verifier': lambda: verify_saved(path, tmp_path / 'unused', {'archive_sha256': checksum}),
        'retrieval': lambda: retrieve(path, SimpleNamespace()),
        'source-verifier': lambda: verify_archive({'archive': {'sha256': checksum}, 'case': {'sources': []}}, path)}
    with pytest.raises(ValueError, match='MEMBER_SIZE_LIMIT'):
        actions[entry]()


@pytest.mark.parametrize('limit,error', [('total_bytes', 'TOTAL_SIZE_LIMIT'),
    ('archive_bytes', 'COMPRESSED_SIZE_LIMIT'), ('member_count', 'MEMBER_COUNT_LIMIT')])
def test_other_archive_bounds_are_checked_before_read(tmp_path, monkeypatch, limit, error):
    from clinical_intelligence import archive_bounds
    path = archive(tmp_path)
    monkeypatch.setattr(archive_bounds, 'DEFAULT_LIMITS', archive_bounds.ArchiveLimits(**{limit: 1}))
    with pytest.raises(ValueError, match=error):
        ArchiveIndex(path)


def test_verified_snapshot_survives_source_path_replacement(tmp_path):
    from clinical_intelligence.archive_bounds import BoundedArchive
    path = archive(tmp_path)
    with BoundedArchive(path) as original:
        saved = original.read('patients.csv')
        path.write_bytes(b'not a zip anymore')
        assert original.read('patients.csv') == saved
