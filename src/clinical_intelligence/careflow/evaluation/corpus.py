"""Identity/content grouped immutable corpora. No model or outcome selection."""
import csv
import hashlib
import json
from pathlib import Path
import re

from ...claims_review.prepare import digest


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def write_once(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError('Frozen artifact differs: ' + str(path))
    else:
        with path.open('xb') as stream:
            stream.write(content)


def load_acn(path):
    path = Path(path)
    source_sha = sha(path.read_bytes())
    result, seen = [], set()
    with path.open(encoding='utf-8') as stream:
        for row_number, line in enumerate(stream, 1):
            row = json.loads(line)
            identifier = str(row['idx'])
            if identifier in seen:
                raise ValueError('Duplicate original ACN idx')
            seen.add(identifier)
            try:
                summary = json.loads(row['summary']) if isinstance(row['summary'], str) else row['summary']
                reference_error = None
            except (ValueError, TypeError):
                summary = None
                reference_error = 'invalid_original_summary_json'
            # Keep full note, truncated note and generated conversation together.
            # Generated summary never becomes input text or an approval label.
            for field, kind in [('full_note', 'note'), ('note', 'truncated_note'), ('conversation', 'dialogue')]:
                text = row[field]
                if not isinstance(text, str):
                    raise ValueError('Original source field must be a string')
                result.append({
                    'document_id': f'acn:{identifier}:{field}', 'case_group': f'acn:{identifier}',
                    'dataset': 'AGBonnet/augmented-clinical-notes', 'input_kind': kind,
                    'text': text, 'reference': {'original_summary': summary, 'reference_error': reference_error},
                    'reference_origin': 'dataset_generated_silver', 'source_sha256': source_sha,
                    'original_row': row_number, 'original_idx': identifier, 'source_field': field,
                })
    return result


def load_aci(path, *, cached_encounters=()):
    path = Path(path)
    source_sha = sha(path.read_bytes())
    result = []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row_number, row in enumerate(csv.DictReader(stream), 1):
            encounter = row['encounter_id']
            result.append({
                'document_id': 'aci-bench:train:' + encounter, 'case_group': encounter,
                'dataset': 'ACI-BENCH', 'input_kind': 'dialogue', 'text': row['dialogue'],
                'reference': {'original_note': row['note']},
                'reference_origin': 'reference_note_not_structured_fact_gold',
                'source_sha256': source_sha, 'original_row': row_number,
                'prior_extraction_exposure': encounter in set(cached_encounters),
            })
    return result


def freeze_corpus(documents, root, *, development_groups, holdout_groups, source_metadata,
                  exposed_groups=(), seed='careflow-case-split/2'):
    if development_groups < 1 or holdout_groups < 1:
        raise ValueError('Nonempty development and holdout group counts required')
    documents = sorted(documents, key=lambda d: d['document_id'])
    if not documents or len({d['document_id'] for d in documents}) != len(documents):
        raise ValueError('Empty corpus or duplicate document identity')
    group_names = {d['case_group'] for d in documents}
    parent = {group: group for group in group_names}
    def find(group):
        if parent[group] != group:
            parent[group] = find(parent[group])
        return parent[group]
    def join(a, b):
        left, right = sorted((find(a), find(b)))
        parent[right] = left
    # Identical original text under different row IDs is one leakage component.
    owners = {}
    for doc in documents:
        normalized = re.sub(r'\s+', ' ', doc['text']).strip()
        if normalized:
            key = sha(normalized.encode('utf-8'))
            if key in owners:
                join(doc['case_group'], owners[key])
            owners[key] = doc['case_group']
    grouped = {}
    for doc in documents:
        grouped.setdefault(find(doc['case_group']), []).append(doc)
    groups = []
    for members in grouped.values():
        originals = sorted({d['case_group'] for d in members})
        group_id = 'group-' + digest(originals)
        groups.append({'group_id': group_id, 'original_case_groups': originals,
                       'document_ids': [d['document_id'] for d in members],
                       'previously_exposed': bool(set(originals) & set(exposed_groups))})
    ranked = sorted(groups, key=lambda g: digest([seed, g['group_id']]))
    exposed = [g for g in ranked if g['previously_exposed']]
    fresh = [g for g in ranked if not g['previously_exposed']]
    if len(exposed) > development_groups or len(groups) < development_groups + holdout_groups:
        raise ValueError('Not enough isolated groups or exposed groups exceed development capacity')
    development = exposed + fresh[:development_groups - len(exposed)]
    remaining = fresh[development_groups - len(exposed):]
    partitions = {'development': development, 'holdout': remaining[:holdout_groups], 'reserve': remaining[holdout_groups:]}
    raw = ('\n'.join(canonical(d) for d in documents) + '\n').encode('utf-8')
    manifest = {
        'schema_version': 'careflow-frozen-corpus/2', 'seed': seed,
        'source_metadata': source_metadata, 'documents_sha256': sha(raw),
        'document_count': len(documents), 'original_case_groups': len(group_names), 'isolated_groups': len(groups),
        'partition_selection': 'SHA-256 of seed/group identity only; exposed groups restricted to development',
        'grouping': 'original case identity plus connected components of whitespace-normalized duplicate source content',
        'partitions': partitions,
        'documents': [{'document_id': d['document_id'], 'case_group': d['case_group'],
                       'source_sha256': sha(d['text'].encode('utf-8')), 'reference_sha256': digest(d['reference']),
                       'reference_origin': d['reference_origin'], 'input_kind': d['input_kind']} for d in documents],
        'boundary': 'Source extraction only; no PA approval/completeness gold. Silver and reference-note labels require source review.',
    }
    manifest['manifest_sha256'] = digest(manifest)
    root = Path(root)
    write_once(root / 'documents.jsonl', raw)
    write_once(root / 'manifest.json', (canonical(manifest) + '\n').encode('utf-8'))
    return manifest


def load_frozen(root, partition, *, candidate_sha256=None):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    body = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    if digest(body) != manifest['manifest_sha256']:
        raise ValueError('Frozen manifest hash mismatch')
    raw = (root / 'documents.jsonl').read_bytes()
    if sha(raw) != manifest['documents_sha256']:
        raise ValueError('Frozen document hash mismatch')
    if partition == 'holdout' and not candidate_sha256:
        raise ValueError('Holdout requires a candidate freeze hash')
    if partition not in manifest['partitions']:
        raise ValueError('Unknown corpus partition')
    selected = {d for group in manifest['partitions'][partition] for d in group['document_ids']}
    return [json.loads(line) for line in raw.decode('utf-8').splitlines() if json.loads(line)['document_id'] in selected]
