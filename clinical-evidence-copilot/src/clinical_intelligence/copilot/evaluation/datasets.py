"""Case/original-note grouping and immutable development/final split manifests."""
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from ...clinical_notes.dataset import write_json
from ..models import digest

VERSION = 'copilot-dataset-split/v1'
SEED = 20261013
AUGMENTED_REVISION = 'c1cb55e3fb2a08bef749c0de59500ef97ca582b6'
AUGMENTED_SHA256 = '2301347522a517df6ecf4799955fef5993cc679d9fabbf44d92714331fb6f389'
ACI_REVISION = 'b909b2bb9cf1d19de08df15cddde7bd0179665e4'


def file_hash(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''): sha.update(block)
    return sha.hexdigest()


def normalized_note(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip().casefold()


def rows(path):
    with Path(path).open(encoding='utf-8') as f:
        for index, line in enumerate(f):
            yield index, json.loads(line)


def group_records(records):
    """Transitive connected components across identity, full and truncated notes."""
    parent, owner, metadata = [], {}, []
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for index, row in records:
        position = len(parent)
        parent.append(position)
        identity = str(row['idx'])
        full = digest(normalized_note(row['full_note']))
        note = digest(normalized_note(row['note']))
        keys = ['case:'+identity, 'note:'+full, 'note:'+note]
        for key in keys:
            if key in owner:
                a,b = find(position),find(owner[key])
                parent[max(a,b)] = min(a,b)
            else:
                owner[key] = position
        metadata.append(dict(row_index=index,case_id=identity,full_note_hash=full,note_group_hash=note,
            conversation_hash=digest(row['conversation']),note_hash=digest(row['note']),
            full_input_hash=digest(row['full_note']),reference_hash=digest(row['summary'])))
    grouped = defaultdict(list)
    for i,item in enumerate(metadata): grouped[find(i)].append(item)
    result = []
    for members in grouped.values():
        group_id = digest(sorted({m['case_id']+':'+m['full_note_hash']+':'+m['note_group_hash'] for m in members}))
        result.append(dict(group_id=group_id,members=members))
    return sorted(result,key=lambda g:g['group_id'])


def freeze_augmented(path, output, *, used_ids=(), seed=SEED, development_size=200, final_size=200, expected_rows=30000, expected_hash=AUGMENTED_SHA256):
    checksum = file_hash(path)
    if expected_hash is not None and checksum != expected_hash:
        raise ValueError('Pinned augmented dataset checksum mismatch')
    groups = group_records(rows(path))
    total = sum(len(g['members']) for g in groups)
    if expected_rows is not None and total != expected_rows:
        raise ValueError('Frozen record denominator mismatch')
    used = set(map(str,used_ids))
    exposed = [g for g in groups if any(m['case_id'] in used for m in g['members'])]
    eligible = sorted((g for g in groups if g not in exposed),key=lambda g:digest([seed,g['group_id']]))
    if len(eligible) < development_size+final_size:
        raise ValueError('Insufficient disjoint original-note/case groups')
    dev,final = eligible[:development_size],eligible[development_size:development_size+final_size]
    def selected(items):
        return [{**g,'selected_row_index':min(m['row_index'] for m in g['members']),
                 'input_kind':'dialogue' if i%2==0 else 'note'} for i,g in enumerate(items)]
    manifest = dict(schema_version=VERSION,dataset='AGBonnet/augmented-clinical-notes',revision=AUGMENTED_REVISION,
        source_sha256=checksum,seed=seed,record_denominator=total,group_denominator=len(groups),
        grouping='transitive case idx OR normalized full_note OR normalized note; NFKC+whitespace+casefold',
        label_type='GPT-4 generated structured summary from source note; not physician gold',
        note_input='full_note',dialogue_input='original conversation; reference-note-only content must not be called an omission',
        known_exposed_ids=sorted(used),excluded_exposed_groups=len(exposed),
        development=selected(dev),final=selected(final),final_status='sealed_until_candidate_freeze')
    manifest['manifest_hash'] = digest(manifest)
    write_json(Path(output),manifest,immutable=True)
    return manifest


def freeze_aci(folder, output, *, used_encounters=()):
    names = dict(train='train.csv',validation='valid.csv',test1='clinicalnlp_taskB_test1.csv',
                 test2='clinicalnlp_taskC_test2.csv',test3='clef_taskC_test3.csv')
    counts = dict(train=67,validation=20,test1=40,test2=40,test3=40)
    splits, seen = {}, set()
    for split,name in names.items():
        path=Path(folder)/name
        with path.open(encoding='utf-8-sig',newline='') as f: data=list(csv.DictReader(f))
        identities=[r['encounter_id'] for r in data]
        if len(data)!=counts[split] or len(set(identities))!=len(data) or seen&set(identities):
            raise ValueError('ACI official split identity/count overlap')
        seen.update(identities)
        # Freeze hashes/IDs only. Test text is never emitted or used for development.
        splits[split]=dict(file=name,sha256=file_hash(path),denominator=len(data),
            encounters=[dict(encounter_id=r['encounter_id'],dialogue_hash=digest(r['dialogue']),
                reference_hash=digest(r['note']),prior_used=r['encounter_id'] in used_encounters) for r in data])
    manifest=dict(schema_version=VERSION,dataset='ACI-BENCH',revision=ACI_REVISION,
        label_type='published reference clinical notes; structured normalization needs separate provenance',
        splits=splits,final_status='official tests sealed_until_candidate_freeze',
        original_splits_preserved=True)
    manifest['manifest_hash']=digest(manifest)
    write_json(Path(output),manifest,immutable=True)
    return manifest


def verify_manifest(manifest):
    if digest({k:v for k,v in manifest.items() if k!='manifest_hash'})!=manifest['manifest_hash']:
        raise ValueError('Split manifest was changed')
    return manifest


def load_augmented_partition(path, manifest, partition='development', *, candidate=None):
    verify_manifest(manifest)
    if file_hash(path)!=manifest['source_sha256']:
        raise ValueError('Dataset changed after split freeze')
    if partition not in {'development','final'}: raise ValueError('Unknown partition')
    if partition=='final':
        if candidate is None or candidate.get('split_manifest_hash')!=manifest['manifest_hash'] or not candidate.get('candidate_hash'):
            raise ValueError('Final evaluation requires a frozen candidate tied to this split')
        from .candidate import verify_candidate
        verify_candidate(candidate,manifest)
    wanted={g['selected_row_index']:g for g in manifest[partition]}
    for index,row in rows(path):
        if index not in wanted: continue
        g=wanted[index]
        member=next(m for m in g['members'] if m['row_index']==index)
        if digest(row['summary'])!=member['reference_hash'] or digest(row['conversation'])!=member['conversation_hash'] or digest(row['full_note'])!=member['full_input_hash']:
            raise ValueError('Frozen selected record changed')
        yield dict(case_id=str(row['idx']),group_id=g['group_id'],input_kind=g['input_kind'],
            text=row['conversation'] if g['input_kind']=='dialogue' else row['full_note'],
            reference=row['summary'],reference_type=manifest['label_type'],reference_note=row['note'],
            full_note=row['full_note'],partition=partition,source_revision=manifest['revision'])
