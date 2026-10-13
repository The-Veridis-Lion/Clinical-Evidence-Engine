"""Additive preservation of dataset labels, including malformed originals.

This is an inventory, not a clinical gold-generation or label-repair mechanism.
The pre-existing corpus manifest and original reference scores are untouched.
"""
import json
from pathlib import Path

from ...claims_review.prepare import digest
from .corpus import canonical, sha, write_once


def freeze_acn_reference_inventory(source_path, corpus_root, output):
    source_raw = Path(source_path).read_bytes()
    source_sha = sha(source_raw)
    corpus_root, output = Path(corpus_root), Path(output)
    manifest = json.loads((corpus_root / 'manifest.json').read_text(encoding='utf-8'))
    if digest({k: v for k, v in manifest.items() if k != 'manifest_sha256'}) != manifest['manifest_sha256']:
        raise ValueError('Frozen corpus manifest changed')
    corpus_raw = (corpus_root / 'documents.jsonl').read_bytes()
    if sha(corpus_raw) != manifest['documents_sha256']:
        raise ValueError('Frozen corpus documents changed')
    records = [json.loads(line) for line in corpus_raw.decode('utf-8').splitlines()]
    by_case = {}
    for record in records:
        if record['dataset'] != 'AGBonnet/augmented-clinical-notes' or record['source_sha256'] != source_sha:
            raise ValueError('Original source archive differs from frozen ACN corpus')
        by_case.setdefault(str(record['original_idx']), []).append(record)
    groups = {identifier: (partition, group['group_id']) for partition, entries in manifest['partitions'].items()
              for group in entries for identifier in group['document_ids']}
    rows = []
    for original in (json.loads(line) for line in source_raw.decode('utf-8').splitlines()):
        records = by_case.pop(str(original['idx']), None)
        if records is None:
            raise ValueError('Original case identity is absent or duplicated')
        for record in records:
            if record['text'] != original[record['source_field']]:
                raise ValueError('Original clinical text differs from frozen source binding')
        raw = original['summary']
        parsed, error, permissive = None, None, None
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError) as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
            # JSON's strict=False accepts literal control characters. It neither
            # fixes delimiters nor guesses a diagnosis. Keep this diagnostic view
            # separate; do not substitute it for the frozen strict reference.
            try:
                permissive = json.loads(raw, strict=False)
            except (ValueError, TypeError):
                pass
        original_reference = {'original_summary': parsed,
                              'reference_error': 'invalid_original_summary_json' if error else None}
        if any(r['reference'] != original_reference for r in records):
            raise ValueError('Original reference differs from existing frozen labels')
        partition, group_id = groups[records[0]['document_id']]
        rows.append({'reference_id': 'acn-original-summary:' + str(original['idx']), 'case_group': records[0]['case_group'],
            'partition': partition, 'group_id': group_id, 'document_ids': sorted(r['document_id'] for r in records),
            'raw_reference': raw, 'raw_reference_sha256': digest(raw), 'strict_reference': parsed,
            'strict_parse_error': error, 'permissive_diagnostic_reference': permissive,
            'diagnostic_used_for_scoring': False, 'reference_origin': 'dataset_generated_silver',
            'clinical_gold': False, 'pa_approval_gold': False})
    if by_case:
        raise ValueError('Frozen cases missing from original source archive')
    raw = ('\n'.join(canonical(r) for r in sorted(rows, key=lambda r: r['reference_id'])) + '\n').encode('utf-8')
    receipt = {'schema_version': 'careflow-original-reference-inventory/1', 'source_sha256': source_sha,
        'corpus_manifest_sha256': manifest['manifest_sha256'], 'references_sha256': sha(raw), 'cases': len(rows),
        'strict_json_valid': sum(r['strict_parse_error'] is None for r in rows),
        'strict_json_invalid': sum(r['strict_parse_error'] is not None for r in rows),
        'permissive_diagnostic_only': sum(r['permissive_diagnostic_reference'] is not None for r in rows),
        'unparsed': sum(r['strict_parse_error'] is not None and r['permissive_diagnostic_reference'] is None for r in rows),
        'model_calls': 0, 'original_manifest_modified': False,
        'boundary': 'Original labels preserved, including errors. No repaired gold, metric or clinical correctness claim.'}
    receipt['inventory_sha256'] = digest(receipt)
    write_once(output / 'references.jsonl', raw)
    write_once(output / 'manifest.json', (canonical(receipt) + '\n').encode('utf-8'))
    return receipt
