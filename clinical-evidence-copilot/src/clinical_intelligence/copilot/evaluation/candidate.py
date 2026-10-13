"""Operational candidate freeze and one-candidate holdout access guard."""
import json
import sqlite3
from pathlib import Path

from ...clinical_notes.dataset import write_json
from ..models import digest, now
from .datasets import file_hash, verify_manifest


def verify_candidate(candidate, manifest):
    from .execution import CONFIG, implementation_hashes
    from .matching import VERSION
    verify_manifest(manifest)
    if candidate.get('candidate_hash') != digest({k:v for k,v in candidate.items() if k!='candidate_hash'}):
        raise ValueError('Invalid frozen candidate hash')
    if candidate.get('split_manifest_hash') != manifest['manifest_hash']:
        raise ValueError('Frozen candidate uses another split')
    if candidate.get('implementation') != implementation_hashes() or candidate.get('matcher_version') != VERSION or candidate.get('config') != CONFIG:
        raise ValueError('Code, matcher or model settings changed after candidate freeze')
    for item in candidate.get('development_evidence',[]):
        if file_hash(item['path']) != item['sha256']:
            raise ValueError('Candidate development evidence changed')
    if candidate.get('schema_version')!='copilot-candidate/v1' or len(candidate.get('development_evidence',[]))!=2:
        raise ValueError('Candidate lacks complete development evidence')
    return candidate


def freeze_candidate(manifest, development_root, output):
    from .execution import CONFIG, implementation_hashes
    from .matching import VERSION
    verify_manifest(manifest)
    root=Path(development_root).resolve()
    results_path=root/'results.json'; freeze_path=root/'execution-freeze.json'
    results=json.loads(results_path.read_text(encoding='utf-8'))
    freeze=json.loads(freeze_path.read_text(encoding='utf-8'))
    if freeze.get('run_hash')!=digest({k:v for k,v in freeze.items() if k!='run_hash'}):
        raise ValueError('Development execution freeze changed')
    expected=len(manifest['development'])
    if not results.get('acceptance_passed') or results.get('partition')!='development' or results.get('document_denominator')!=expected or results.get('evaluated_documents')!=expected or results.get('unprocessed_documents')!=0:
        raise ValueError('Candidate requires complete passing development evaluation')
    ai=results.get('ai_assisted') or {}
    if results.get('valid_documents')!=expected or results.get('mechanical_pass_rate')!=1 or results.get('unrecovered_documents')!=0 or ai.get('unresolved')!=0 or ai.get('critical_unsupported')!=0 or ai.get('precision',0)<.95 or ai.get('recall',0)<.9 or ai.get('f1',0)<.92:
        raise ValueError('Development counters and scores fail frozen targets')
    if results.get('run_hash')!=freeze['run_hash'] or freeze.get('split_manifest_hash')!=manifest['manifest_hash'] or freeze.get('denominator')!=expected:
        raise ValueError('Development evidence does not match this split/run')
    if freeze.get('implementation')!=implementation_hashes() or freeze.get('config')!=CONFIG or freeze.get('matcher_version')!=VERSION:
        raise ValueError('Candidate code/settings differ from validated development run')
    certificate=dict(schema_version='copilot-candidate/v1',created_at=now(),
        split_manifest_hash=manifest['manifest_hash'],implementation=implementation_hashes(),
        matcher_version=VERSION,config=CONFIG,development_run_hash=freeze['run_hash'],
        development_evidence=[dict(path=str(p),sha256=file_hash(p)) for p in (results_path,freeze_path)],
        targets=dict(precision=.95,recall=.90,f1=.92,mechanical_pass_rate=1,critical_unsupported=0),
        interpretation='Engineering freeze; AI-assisted labels are not independent clinical gold.')
    certificate['candidate_hash']=digest(certificate)
    write_json(Path(output),certificate,immutable=True)
    return verify_candidate(certificate,manifest)


def reserve_final(candidate,manifest,ledger_path,root):
    verify_candidate(candidate,manifest)
    path=Path(ledger_path); path.parent.mkdir(parents=True,exist_ok=True)
    run_root=str(Path(root).resolve())
    with sqlite3.connect(path,timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS final_access (split_hash TEXT PRIMARY KEY, candidate_hash TEXT, run_root TEXT, reserved_at TEXT)')
        db.execute("CREATE TRIGGER IF NOT EXISTS no_final_update BEFORE UPDATE ON final_access BEGIN SELECT RAISE(ABORT,'Final access immutable'); END")
        db.execute("CREATE TRIGGER IF NOT EXISTS no_final_delete BEFORE DELETE ON final_access BEGIN SELECT RAISE(ABORT,'Final access immutable'); END")
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT candidate_hash,run_root FROM final_access WHERE split_hash=?',(manifest['manifest_hash'],)).fetchone()
        if prior and prior!=(candidate['candidate_hash'],run_root):
            raise ValueError('Holdout already reserved; no new candidate or reset run root')
        if not prior:
            db.execute('INSERT INTO final_access VALUES (?,?,?,?)',(manifest['manifest_hash'],candidate['candidate_hash'],run_root,now()))
    return run_root
