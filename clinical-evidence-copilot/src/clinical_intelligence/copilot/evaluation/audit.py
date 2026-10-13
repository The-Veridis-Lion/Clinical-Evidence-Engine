"""Finite, zero-call paired metric audit of completed saved review outcomes."""
import json
import sqlite3
from pathlib import Path

from ...clinical_notes.dataset import write_json
from ..models import Packet,digest,now
from .datasets import file_hash
from .execution import aggregate
from .matching import ReferenceFact,assisted_metrics,verify_verdicts,structured_match,counts,same_target,PREDICTION_FIELDS


def case_documents(freeze):
    # ACI freezes both dialogue and reference-note extraction inputs. A reference
    # normalization input is not a second patient encounter in accuracy metrics.
    return [d for d in freeze['documents'] if not d['case_id'].startswith('reference-note:')]


def audit_saved_reviews(root,output):
    root=Path(root).resolve()
    freeze=json.loads((root/'execution-freeze.json').read_text(encoding='utf-8'))
    if freeze['run_hash']!=digest({k:v for k,v in freeze.items() if k!='run_hash'}):
        raise ValueError('Original execution freeze changed')
    selected=[]; paired=[]; deferred=[]; input_hashes={}
    for document in case_documents(freeze):
        folder=root/'cases'/digest(document['case_id'])[:20]
        saved=folder/'ai-assisted.json'
        if not saved.exists(): continue
        paths=[folder/'packet.json',folder/'raw-match.json',saved]
        if (folder/'verdicts.json').exists(): paths.append(folder/'verdicts.json')
        try:
            texts={p:p.read_text(encoding='utf-8') for p in paths}
            original=json.loads(texts[saved]); match=json.loads(texts[folder/'raw-match.json'])
            packet=Packet.model_validate_json(texts[folder/'packet.json']).verify()
            if match['packet_hash']!=packet.content_hash or packet.source.sha256!=document['source_hash']:
                raise ValueError('Stored review no longer matches its frozen source/packet')
            verdicts=verify_verdicts(packet,match,json.loads(texts[folder/'verdicts.json'])) if folder/'verdicts.json' in texts else []
            derived=assisted_metrics(match,verdicts)
            if original.get('adjudication_failed'): derived['adjudication_failed']=True
        except json.JSONDecodeError:
            deferred.append(document['case_id']); continue  # Concurrent incomplete file stays pending.
        selected.append(dict(case_id=document['case_id'],packet_status=packet.extraction_status,match=match,assisted=derived))
        paired.append(dict(case_id=document['case_id'],original_saved_metrics=original,derived_metrics=derived))
        for p,text in texts.items(): input_hashes[str(p.relative_to(root))]=digest(text)
    class SnapshotLedger:
        def rows(self):
            with sqlite3.connect(root/'requests.sqlite3') as db:
                db.row_factory=sqlite3.Row
                return [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY started_at,attempt')]
    summary=aggregate(selected,SnapshotLedger(),expected_denominator=len(case_documents(freeze)))
    summary['input_extraction_denominator']=freeze['denominator']
    reference_failures=[]
    for item in selected:
        path=root/'cases'/digest(item['case_id'])[:20]/'reference-provenance.json'
        if path.exists():
            provenance=json.loads(path.read_text(encoding='utf-8'))
            if provenance['normalization_status']!='valid': reference_failures.append(item['case_id'])
    summary['reference_projection_failure_case_ids']=reference_failures
    summary['acceptance_passed']=summary['acceptance_passed'] and not reference_failures
    report=dict(schema_version='copilot-saved-metric-audit/v1',recorded_at=now(),
        parent_root=str(root),parent_run_hash=freeze['run_hash'],metric_version='copilot-assisted-metrics/v2',
        new_model_calls=0,original_artifacts_unchanged=True,input_hashes=input_hashes,
        pending_incomplete_files=deferred,summary=summary,paired_cases=paired,
        interpretation='Finite snapshot of completed cases; pending cases remain in full cohort. Original scores/verdicts retained. Not clinical accuracy improvement.')
    write_json(Path(output),report,immutable=True)
    return report


def audit_saved_matching(roots,output):
    """Reproduce frozen v2, diagnose v3, and retain original source reviews.

    Reads only indexed development packets. It opens no final data, writes no
    parent artifact or ledger, copies no packet tree and dispatches no provider.
    The single output records every input hash and every case, including failures.
    """
    runs=[]; input_hashes={}
    for location in roots:
        root=Path(location).resolve()
        freeze_path=root/'execution-freeze.json'
        freeze=json.loads(freeze_path.read_text(encoding='utf-8'))
        if freeze['run_hash']!=digest({k:v for k,v in freeze.items() if k!='run_hash'}):
            raise ValueError('Original execution freeze changed')
        documents=case_documents(freeze)
        if any(d['partition']!='development' for d in documents):
            raise ValueError('Saved matcher diagnosis permits development only; final remains sealed')
        paths=[freeze_path]; cases=[]; rows=[]; original_rows=[]; errors=[]; field_totals={}
        diagnostics=dict(references=0,references_with_legacy_fallback=0,
            references_with_unrepresentable_fields=0,legacy_auto_passes_with_unrepresentable_fields=0,
            unmatched_same_target_references=0,unmatched_same_target_with_legacy_fallback=0)
        for document in documents:
            folder=root/'cases'/digest(document['case_id'])[:20]
            packet_path=folder/'packet.json'; match_path=folder/'raw-match.json'
            if not packet_path.exists() or not match_path.exists():
                errors.append(dict(case_id=document['case_id'],status='MISSING_SAVED_PACKET_OR_MATCH',folder=str(folder)))
                continue
            paths.extend([packet_path,match_path])
            try:
                packet=Packet.model_validate_json(packet_path.read_text(encoding='utf-8')).verify()
                old=json.loads(match_path.read_text(encoding='utf-8'))
                if old['packet_hash']!=packet.content_hash or packet.source.sha256!=document['source_hash']:
                    raise ValueError('Stored match differs from frozen source/packet')
                references=[ReferenceFact.model_validate(r) for r in old['references']]
                new=structured_match(packet,references)
                if old['raw_counts']!=new['raw_counts'] or old.get('legacy_pairs',old['pairs'])!=new['legacy_pairs']:
                    raise ValueError('Historical v2 reproduction differs; do not silently rewrite baseline')
                matched_refs={p['reference_id'] for p in old['pairs']}
                for reference in references:
                    fallback=[k for k in reference.fields if not k.startswith('attributes.') and k not in
                        {'polarity','temporality','experiencer','assertion_basis'}]
                    diagnostics['references']+=1
                    diagnostics['references_with_legacy_fallback']+=bool(fallback)
                    unrepresentable=any(k not in PREDICTION_FIELDS for k in reference.fields)
                    diagnostics['references_with_unrepresentable_fields']+=unrepresentable
                    diagnostics['legacy_auto_passes_with_unrepresentable_fields']+=unrepresentable and reference.reference_id in matched_refs
                    for key in fallback: field_totals[key]=field_totals.get(key,0)+1
                    if reference.reference_id not in matched_refs and any(same_target(f,reference) for f in packet.facts):
                        diagnostics['unmatched_same_target_references']+=1
                        diagnostics['unmatched_same_target_with_legacy_fallback']+=bool(fallback)
                verdict_path=folder/'verdicts.json'; assisted_path=folder/'ai-assisted.json'
                original_assisted=json.loads(assisted_path.read_text(encoding='utf-8')) if assisted_path.exists() else None
                if assisted_path.exists(): paths.append(assisted_path)
                if original_assisted:
                    original_rows.append(dict(case_id=packet.case_id,packet_status=packet.extraction_status,
                        match=old,assisted=original_assisted))
                verdicts=[]
                if verdict_path.exists():
                    paths.append(verdict_path)
                    verdicts=verify_verdicts(packet,old,json.loads(verdict_path.read_text(encoding='utf-8')))
                source_metrics=assisted_metrics(new,verdicts)
                if original_assisted and original_assisted.get('adjudication_failed'):
                    source_metrics['adjudication_failed']=True
                # Missing review remains unresolved, never a successful clinical judgment.
                rows.append(dict(case_id=packet.case_id,packet_status=packet.extraction_status,match=new,assisted=source_metrics))
                semantic=new['semantic_comparison']
                critical=[v.model_dump() for v in verdicts if v.critical_unsupported]
                format_path=folder/'reference-format.json'
                reference_format=None
                if format_path.exists():
                    paths.append(format_path); reference_format=json.loads(format_path.read_text(encoding='utf-8'))
                cases.append(dict(case_id=packet.case_id,input_kind=packet.source.input_kind,folder=str(folder),
                    packet_status=packet.extraction_status,original_raw_counts=old['raw_counts'],
                    legacy_reproduced_exactly=True,semantic_counts=semantic['counts'],
                    not_comparable_reference_ids=semantic['not_comparable_reference_ids'],
                    not_comparable_prediction_ids=semantic['not_comparable_prediction_ids'],
                    comparable_pairs=new['pairs'],original_saved_source_metrics=original_assisted,
                    derived_source_metrics=source_metrics,reference_format=reference_format,
                    critical_saved_source_judgments=critical,
                    remaining_dispute_ids=[d['dispute_id'] for d in new['disputes']]))
            except (ValueError,KeyError,TypeError) as exc:
                errors.append(dict(case_id=document['case_id'],status='AUDIT_FAILURE_RETAINED',error=str(exc),folder=str(folder)))
        ledger_path=root/'requests.sqlite3'; paths.append(ledger_path)
        with sqlite3.connect(ledger_path.as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            attempts=[dict(row) for row in db.execute('SELECT * FROM attempts ORDER BY started_at,attempt')]
        class ReadOnlyLedger:
            def rows(self): return attempts
        summary=aggregate(rows,ReadOnlyLedger(),expected_denominator=len(documents))
        summary['input_extraction_denominator']=freeze['denominator']
        summary['saved_terminal_review_documents']=len(original_rows)
        summary['saved_complete_review_documents']=sum(bool(c['original_saved_source_metrics']) and
            not c['original_saved_source_metrics'].get('adjudication_failed',False) for c in cases)
        summary['source_review_pending_documents']=len(documents)-len(original_rows)
        summary['metric_scope']='Zero-call audit of all cached inputs; missing saved source judgments remain unresolved. The source-support metric is a conservative evidence lower bound, not a completed clinical accuracy evaluation.'
        summary['reference_projection_failure_case_ids']=[]
        for case in cases:
            path=Path(case['folder'])/'reference-provenance.json'
            if path.exists():
                paths.append(path); provenance=json.loads(path.read_text(encoding='utf-8'))
                if provenance['normalization_status']!='valid':
                    summary['reference_projection_failure_case_ids'].append(case['case_id'])
        summary['acceptance_passed']=summary['acceptance_passed'] and not summary['reference_projection_failure_case_ids'] and not errors
        for path in paths: input_hashes[str(path)]=file_hash(path)
        runs.append(dict(root=str(root),parent_run_hash=freeze['run_hash'],summary=summary,
            original_saved_review_subset=aggregate(original_rows,ReadOnlyLedger(),expected_denominator=len(documents)),
            matcher_diagnostics=diagnostics,legacy_fallback_fields=field_totals,
            reserved_attempts=[r for r in attempts if r['status']=='reserved'],errors=errors,cases=cases,
            source_review_scope='Reused mechanically valid saved Sol judgments plus deterministic comparable pairs; missing/new disputes remain unresolved. AI-assisted, not independent clinical gold.'))
    report=dict(schema_version='copilot-matcher-repair-audit/v1',recorded_at=now(),new_luna_calls=0,new_sol_calls=0,
        original_artifacts_unchanged=True,input_hashes=input_hashes,runs=runs,
        field_mapping=PREDICTION_FIELDS,
        interpretation='Raw v2 scores preserved exactly; incomparable attributes are unknown, not incorrect or automatically correct. Comparable-schema metrics cannot establish clinical acceptance. Source-review gaps and uncertain requests remain visible.')
    write_json(Path(output),report,immutable=True)
    return report
