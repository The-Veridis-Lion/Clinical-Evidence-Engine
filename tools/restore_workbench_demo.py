"""Restore the retained synthetic demonstration, without any model dispatch.

The databases and responses are byte-checked copies of the real saved run. A
receipt permits later launches to reuse user revisions instead of resetting them.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/showcase-case-20261016/evidence'
DATABASES = {'copilot/cases.sqlite3', 'copilot/product-calls.sqlite3',
             'copilot/workbench-calls.sqlite3', 'careflow/cases.sqlite3'}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def filesystem_path(path):
    """Keep Windows staging paths usable beyond the legacy 260-character limit."""
    absolute = str(Path(path).resolve())
    if os.name == 'nt' and not absolute.startswith('\\\\?\\'):
        absolute = ('\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\')
                    else '\\\\?\\' + absolute)
    return Path(absolute)


def restore_demo(destination, *, evidence=EVIDENCE):
    # A separately authored showcase can reuse the same verified restoration
    # path without overwriting the original regression dataset or its receipt.
    evidence = Path(evidence).resolve()
    # Compare ordinary absolute paths before adding the Windows I/O prefix.
    destination = str(destination)
    if destination.startswith('\\\\?\\UNC\\'):
        destination = '\\\\' + destination[8:]
    elif destination.startswith('\\\\?\\'):
        destination = destination[4:]
    destination = Path(destination).resolve()
    if destination == ROOT or destination.is_relative_to(ROOT/'docs') or destination.is_relative_to(ROOT/'.git'):
        raise ValueError('Choose a dedicated working data directory outside docs and .git.')
    manifest_bytes = (evidence/'collection.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    dataset_hash = digest(manifest_bytes)
    destination_fs = filesystem_path(destination)
    receipt_path = destination_fs/'demo-restoration.json'
    if destination_fs.exists():
        if not receipt_path.is_file():
            raise ValueError('This data directory already exists without a demo receipt; use a new directory.')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('dataset_sha256') != dataset_hash or not all((destination_fs/p).is_file() for p in DATABASES):
            raise ValueError('Existing demo receipt or databases differ; they were not overwritten.')
        # Databases may contain legitimate revisions. Raw responses are immutable:
        # check them against the retained manifest, never silently restore over edits.
        for row in manifest['raw_files']:
            source = (evidence.parent/row['path']).resolve()
            if not source.is_relative_to(evidence/'requests'):
                raise ValueError('Request artifact escapes the retained request directory')
            path = destination_fs/'copilot'/source.relative_to(evidence/'requests')
            content = path.read_bytes() if path.is_file() else b''
            if len(content) != row['bytes'] or digest(content) != row['sha256']:
                raise ValueError('An immutable saved response is missing or changed; the workspace was not overwritten.')
        return {'reused': True, 'data_dir': str(destination), 'dataset_sha256': dataset_hash,
                'model_calls': 0}

    # Validate all inputs before exposing a usable workspace. Only known files
    # are restored; the manifest's original absolute developer paths are ignored.
    restored = {}
    for row in manifest['database_snapshots']:
        relative = row['path'].removeprefix('evidence/sqlite/').removesuffix('.gz')
        if relative not in DATABASES:
            raise ValueError('Unknown database in the saved demo manifest')
        source = (evidence.parent/row['path']).resolve()
        if not source.is_relative_to(evidence):
            raise ValueError('Demo artifact escapes its evidence directory')
        compressed = source.read_bytes()
        if digest(compressed) != row['sha256']:
            raise ValueError('Compressed demo snapshot hash mismatch')
        content = gzip.decompress(compressed)
        if len(content) != row['uncompressed_bytes'] or digest(content) != row['uncompressed_sha256']:
            raise ValueError('Demo database hash mismatch')
        restored[relative] = content
    if set(restored) != DATABASES:
        raise ValueError('The demo requires all four retained databases')
    for row in manifest['raw_files']:
        source = (evidence.parent/row['path']).resolve()
        if not source.is_relative_to(evidence/'requests'):
            raise ValueError('Request artifact escapes the retained request directory')
        content = source.read_bytes()
        if digest(content) != row['sha256'] or len(content) != row['bytes']:
            raise ValueError('Saved model request or response hash mismatch')
        relative = Path('copilot')/source.relative_to(evidence/'requests')
        restored[relative.as_posix()] = content

    destination_fs.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='workbench-demo-restore-', dir=destination_fs.parent) as temporary:
        stage = Path(temporary)/'workspace'
        stage.mkdir()
        for relative, content in restored.items():
            path = stage/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        receipt = {'contract': 'saved-synthetic-workbench-demo/1',
                   'restored_at': datetime.now(timezone.utc).isoformat(),
                   'dataset_sha256': dataset_hash, 'model_calls': 0,
                   'label': 'Synthetic demonstration using retained real Luna responses.',
                   'files': [{'path': name, 'sha256': digest(content), 'bytes': len(content)}
                             for name, content in sorted(restored.items())]}
        (stage/'demo-restoration.json').write_bytes((json.dumps(receipt, indent=2)+'\n').encode())
        stage.rename(destination_fs)
    return {'reused': False, 'data_dir': str(destination), 'dataset_sha256': dataset_hash,
            'restored_files': len(restored), 'model_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, default=EVIDENCE,
                        help='Retained synthetic evidence directory containing collection.json')
    args = parser.parse_args()
    print(json.dumps(restore_demo(args.data_dir, evidence=args.evidence), indent=2))
