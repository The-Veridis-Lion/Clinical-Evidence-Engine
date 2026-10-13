"""Frozen bounded clinical extraction and Sol discrepancy evaluation."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from time import perf_counter

from ...clinical_notes.dataset import write_json
from ...clinical_notes.runner import SingleDispatchProvider
from ...dialogue_first.contract import ProposedFact,identical
from ...provider import ProviderConfig
from ..models import Source,digest,now
from ..service import build_packet
from ..source_adapter import inspect,prompt,schema
from .concurrency import ConcurrencyBlocked,LunaSlots
from .datasets import file_hash,verify_manifest
from .matching import VERSION as MATCHER_VERSION,summary_references,structured_match,adjudication_task,verify_verdicts,assisted_metrics

CONFIG={'extractor_model':'gpt-6-luna','reviewer_model':'gpt-6.1-sol','reasoning_effort':'high',
    'luna_workers':25,'sol_workers':5,'max_attempts_per_stage':3,'timeout_seconds':300,
    'reference_mismatch_retry':False,'provider_internal_retries':0}


class AttemptLedger:
    def __init__(self,path,identity):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS identity (content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                  case_id TEXT,stage TEXT,attempt INTEGER CHECK(attempt BETWEEN 1 AND 3),
                  request_key TEXT UNIQUE,status TEXT,started_at TEXT,ended_at TEXT,
                  latency_seconds REAL,usage TEXT,error TEXT,dispatched INTEGER DEFAULT 0,
                  PRIMARY KEY(case_id,stage,attempt));
                CREATE TRIGGER IF NOT EXISTS no_terminal_update BEFORE UPDATE ON attempts
                  WHEN OLD.status!='reserved' BEGIN SELECT RAISE(ABORT,'terminal attempt immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_attempt_delete BEFORE DELETE ON attempts
                  BEGIN SELECT RAISE(ABORT,'attempt history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_identity_update BEFORE UPDATE ON identity
                  BEGIN SELECT RAISE(ABORT,'run identity immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_identity_delete BEFORE DELETE ON identity
                  BEGIN SELECT RAISE(ABORT,'run identity immutable'); END;''')
            encoded=json.dumps(identity,sort_keys=True)
            rows=db.execute('SELECT content FROM identity').fetchall()
            if rows and (len(rows)!=1 or rows[0][0]!=encoded): raise ValueError('Frozen execution identity changed')
            if not rows: db.execute('INSERT INTO identity VALUES (?)',(encoded,))

    def connect(self):
        db=sqlite3.connect(self.path,timeout=30); db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def rows(self,case_id=None,stage=None):
        with self.connect() as db:
            rows=db.execute('SELECT * FROM attempts WHERE (? IS NULL OR case_id=?) AND (? IS NULL OR stage=?) ORDER BY started_at,attempt',(case_id,case_id,stage,stage)).fetchall()
        return [dict(r) for r in rows]

    def reserve(self,case_id,stage,attempt,key):
        if stage not in {'luna_extraction','sol_adjudication'}: raise ValueError('Unplanned stage')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT attempt,status FROM attempts WHERE case_id=? AND stage=? ORDER BY attempt DESC LIMIT 1',(case_id,stage)).fetchone()
            if previous and (previous['status']=='reserved' or previous['status']=='valid'):
                raise ValueError('Successful or uncertain request cannot replay')
            if attempt!=(previous['attempt']+1 if previous else 1) or attempt>3:
                raise ValueError('Attempts must be sequential and at most three')
            if previous and previous['status'] not in {'upstream_failed','parse_failed','mechanically_invalid','partial'}:
                raise ValueError('Only eligible failure permits retry')
            db.execute('INSERT INTO attempts(case_id,stage,attempt,request_key,status,started_at) VALUES (?,?,?,?,?,?)',(case_id,stage,attempt,key,'reserved',now()))

    def dispatched(self,key):
        with self.connect() as db: db.execute('UPDATE attempts SET dispatched=1 WHERE request_key=?',(key,))

    def finish(self,key,status,latency,usage=None,error=None):
        with self.connect() as db:
            db.execute('UPDATE attempts SET status=?,ended_at=?,latency_seconds=?,usage=?,error=? WHERE request_key=?',
                (status,now(),latency,json.dumps(usage) if usage is not None else None,error,key))


def implementation_hashes():
    app=Path(__file__).resolve().parents[1]
    engine=app.parent
    selected=list(app.rglob('*.py'))+[engine/'dialogue_first'/'contract.py',engine/'dialogue_first'/'prompt.py',
        engine/'clinical_notes'/'runner.py',engine/'clinical_notes'/'schema.py',engine/'provider.py']
    return {str(p.relative_to(engine)):file_hash(p) for p in sorted(selected)}


def freeze_run(root,records,manifest,*,config=None):
    verify_manifest(manifest)
    config=config or CONFIG
    if config['extractor_model']!='gpt-6-luna' or config['reviewer_model']!='gpt-6.1-sol' or config['reasoning_effort']!='high':
        raise ValueError('Model roles/settings cannot change silently')
    if not 1<=config['luna_workers']<=25 or config['max_attempts_per_stage']!=3:
        raise ValueError('Concurrency/retry limits changed')
    identity=dict(version='copilot-evaluation-run/v1',config=config,split_manifest_hash=manifest['manifest_hash'],
        matcher_version=MATCHER_VERSION,implementation=implementation_hashes(),
        denominator=len(records),documents=[dict(case_id=r['case_id'],group_id=r['group_id'],input_kind=r['input_kind'],
            source_hash=digest(r['text']),reference_hash=digest(r['reference']),partition=r['partition']) for r in records])
    identity['run_hash']=digest(identity)
    write_json(Path(root)/'execution-freeze.json',identity,immutable=True)
    return identity


def preserving_repair(initial_raw,new_raw,initial,new,doc):
    """Generic structural-only safeguard: valid facts and clinical fields frozen."""
    old=json.loads(initial_raw); replacement=json.loads(new_raw)
    initial=inspect(initial_raw,doc)
    if len(old['facts'])!=len(replacement['facts']): raise ValueError('Mechanical repair changed assertion count')
    for i,item in enumerate(old['facts']):
        if i in initial['accepted_indices']:
            if not identical(item,replacement['facts'][i]): raise ValueError('Repair changed accepted fact')
        elif isinstance(item,dict):
            for key in ProposedFact.model_fields.keys()-{'evidence'}:
                if key in item and not identical(item[key],replacement['facts'][i].get(key)):
                    raise ValueError('Repair changed clinical fields')
    # Relationships are not adopted into SOAP, but valid proposals still stay frozen.
    if len(old['relationships'])!=len(replacement['relationships']): raise ValueError('Repair changed relationship count')
    from ...dialogue_first.contract import resolve_relationship,resolve_references,References
    from ..source_adapter import source_index
    catalogue={s['source_id']:s for s in source_index(doc)['source_catalogue']}
    mapping={raw_index:i for i,raw_index in enumerate(initial['accepted_indices'])}
    endpoints={'from_fact_index','to_fact_index'}
    for before,after in zip(old['relationships'],replacement['relationships']):
        if identical(before,after):continue
        try:resolve_relationship(before,doc,catalogue,mapping)
        except ValueError:
            if not isinstance(before,dict) or not isinstance(after,dict) or set(before)!=set(after):
                raise ValueError('Repair changed relationship fields')
            if any(not identical(before[k],after[k]) for k in before.keys()-endpoints):
                raise ValueError('Repair changed relationship meaning or evidence')
            resolve_references(References.model_validate(before['evidence']),doc,catalogue)
            invalid={k for k in endpoints if type(before[k]) is not int or before[k] not in mapping}
            if not invalid:raise ValueError('Only invalid relationship endpoints may be repaired')
            if any(not identical(before[k],after[k]) for k in endpoints-invalid):
                raise ValueError('Repair changed valid relationship endpoint')
            resolve_relationship(after,doc,catalogue,mapping)
        else:raise ValueError('Repair changed accepted relationship')
    return new


def run_extraction(record,root,identity,ledger,slots,*,provider=None):
    case_id=record['case_id']; folder=Path(root)/'cases'/digest(case_id)[:20]
    outcome=folder/'packet.json'
    if outcome.exists():
        from ..models import Packet
        return Packet.model_validate_json(outcome.read_text(encoding='utf-8')).verify()
    old=ledger.rows(case_id,'luna_extraction')
    if any(r['status']=='reserved' for r in old): raise ConcurrencyBlocked('Uncertain extraction reservation blocks replay')
    source=Source.create('evaluation:'+case_id,record['text'],record['input_kind'],origin='frozen_dataset:'+record['source_revision'])
    doc=source.document(); base_prompt=prompt(doc); initial_raw=None; initial=None; best=None
    if old:
        for r in old:
            saved=folder/f"luna-attempt-{r['attempt']}"/'raw-response.json'
            if saved.exists():
                candidate=saved.read_text(encoding='utf-8')
                result=inspect(candidate,doc)
                if result['status']=='PARTIAL': initial_raw,initial,best=candidate,result,result
    failure='No valid output'
    for attempt in range(len(old)+1,4):
        request_prompt=base_prompt
        if initial_raw and initial:
            request_prompt+='\nMECHANICAL REPAIR ONLY: retain every accepted fact and all clinical fields, count and order. Correct schema/source references only. Do not add facts or change interpretation.\n'+json.dumps({'previous_output':initial_raw,'mechanical_errors':initial['errors']},ensure_ascii=False)
        key=digest([identity['run_hash'],case_id,'luna_extraction',attempt])
        dest=folder/f'luna-attempt-{attempt}'; dest.mkdir(parents=True,exist_ok=True)
        write_json(dest/'schema.json',schema(doc),immutable=True)
        (dest/'prompt.txt').write_text(request_prompt,encoding='utf-8')
        start=perf_counter(); usage=None
        try:
            with slots.hold(key):
                ledger.reserve(case_id,'luna_extraction',attempt,key)
                ledger.dispatched(key)
                active=provider or SingleDispatchProvider(ProviderConfig(model='gpt-6-luna',reasoning_effort='high',timeout_seconds=CONFIG['timeout_seconds']))
                raw,usage=active.dispatch(doc,dest.resolve())
            try:
                json.loads(raw)
            except ValueError as exc:
                ledger.finish(key,'parse_failed',perf_counter()-start,usage,str(exc)); failure=str(exc); continue
            inspected=inspect(raw,doc)
            if initial_raw and initial:
                try: inspected=preserving_repair(initial_raw,raw,initial,inspected,doc)
                except (ValueError,KeyError,TypeError) as exc:
                    inspected=dict(status='INVALID',result=None,accepted_indices=[],errors=[str(exc)])
            if inspected['status']=='VALID':
                ledger.finish(key,'valid',perf_counter()-start,usage)
                p=build_packet(case_id,record['group_id'],source,inspected['result'],metadata={'mode':'frozen_evaluation','run_hash':identity['run_hash'],'attempts':attempt,'model':'gpt-6-luna','reasoning_effort':'high'})
                write_json(outcome,p.model_dump(mode='json'),immutable=True)
                return p
            status='partial' if inspected['status']=='PARTIAL' else 'mechanically_invalid'
            failure='; '.join(inspected['errors'])
            ledger.finish(key,status,perf_counter()-start,usage,failure)
            if inspected['status']=='PARTIAL': initial_raw,initial,best=raw,inspected,inspected
        except ConcurrencyBlocked:
            raise
        except Exception as exc:
            failure=f'{type(exc).__name__}: {exc}'
            if ledger.rows(case_id,'luna_extraction') and ledger.rows(case_id,'luna_extraction')[-1]['status']=='reserved':
                ledger.finish(key,'upstream_failed',perf_counter()-start,usage,failure)
            else: raise
    p=build_packet(case_id,record['group_id'],source,best['result'] if best else None,
        extraction_error=None if best else failure,metadata={'mode':'frozen_evaluation','run_hash':identity['run_hash'],'attempts':len(ledger.rows(case_id,'luna_extraction')),'model':'gpt-6-luna','reasoning_effort':'high','unrecovered_failure':True})
    if best:
        from ..runtime import mark_partial
        mark_partial(p,best['errors'])
    write_json(outcome,p.model_dump(mode='json'),immutable=True)
    return p


def run_adjudication(record,packet,match,root,identity,ledger,*,provider=None,prior_review_root=None):
    folder=Path(root)/'cases'/digest(record['case_id'])[:20]
    outcome=folder/'ai-assisted.json'
    if outcome.exists(): return json.loads(outcome.read_text(encoding='utf-8'))
    if not match['disputes']:
        metrics=assisted_metrics(match,[])
        write_json(outcome,metrics,immutable=True)
        return metrics
    task=adjudication_task(packet,match,record['reference'])
    request_prompt='Return exactly the supplied JSON schema. Do not use tools.\n'+json.dumps({k:v for k,v in task.items() if k!='output_schema'},ensure_ascii=False)
    if prior_review_root is not None and not ledger.rows(record['case_id'],'sol_adjudication'):
        prior=Path(prior_review_root).resolve()
        stop=json.loads((prior/'controller-stop.json').read_text(encoding='utf-8'))
        if not stop.get('process_tree_terminated'):
            raise ConcurrencyBlocked('Prior interrupted process tree termination is not established')
        with sqlite3.connect(prior/'requests.sqlite3') as db:
            db.row_factory=sqlite3.Row
            previous=[dict(r) for r in db.execute('SELECT * FROM attempts WHERE case_id=? AND stage=? ORDER BY attempt',(record['case_id'],'sol_adjudication'))]
        recovered=None; recovery_record=[]
        for row in previous:
            old_folder=prior/'cases'/digest(record['case_id'])[:20]/f"sol-attempt-{row['attempt']}"
            old_prompt=old_folder/'prompt.txt'
            if old_prompt.exists() and old_prompt.read_text(encoding='utf-8')!=request_prompt:
                raise ValueError('Prior reviewer task differs; cannot silently reset or reuse its budget')
            status=row['status']; validation_error=row['error']
            raw_path=old_folder/'raw-response.json'
            if raw_path.exists():
                try:
                    parsed=json.loads(raw_path.read_text(encoding='utf-8'))
                    valid_response=verify_verdicts(packet,match,parsed)
                    if recovered is None: recovered=valid_response
                    status='valid'; validation_error=None
                except ValueError as exc:
                    # A stopped local controller does not prove what the provider
                    # completed. A partial/invalid artifact cannot release an
                    # uncertain reservation for another paid request.
                    if status!='reserved': status='mechanically_invalid'
                    validation_error=str(exc)
            imported={**row,'status':status,'error':validation_error,'ended_at':row['ended_at'] or stop['recorded_at']}
            if status=='reserved': imported['ended_at']=row['ended_at']
            with ledger.connect() as db:
                fields=list(imported)
                db.execute('INSERT INTO attempts ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',[imported[k] for k in fields])
            recovery_record.append(dict(attempt=row['attempt'],original_status=row['status'],derived_status=status,
                raw_response_hash=file_hash(raw_path) if raw_path.exists() else None,request_key=row['request_key']))
        write_json(folder/'prior-review-recovery.json',dict(prior_root=str(prior),attempts=recovery_record,
            policy='Earliest mechanically valid response; all prior attempts consume the three-attempt budget; stopped/invalid reservations remain uncertain; original streams/ledger untouched'),immutable=True)
        if recovered is not None:
            write_json(folder/'verdicts.json',{'verdicts':[v.model_dump() for v in recovered]},immutable=True)
            metrics=assisted_metrics(match,recovered)
            metrics['reused_prior_review']=True
            write_json(outcome,metrics,immutable=True)
            return metrics
    old=ledger.rows(record['case_id'],'sol_adjudication')
    if any(r['status']=='reserved' for r in old): raise ConcurrencyBlocked('Uncertain Sol reservation blocks replay')
    for attempt in range(len(old)+1,4):
        key=digest([identity['run_hash'],record['case_id'],'sol_adjudication',attempt])
        dest=folder/f'sol-attempt-{attempt}'; dest.mkdir(parents=True,exist_ok=True)
        write_json(dest/'schema.json',task['output_schema'],immutable=True)
        (dest/'prompt.txt').write_text(request_prompt,encoding='utf-8')
        ledger.reserve(record['case_id'],'sol_adjudication',attempt,key)
        start=perf_counter(); usage=None
        try:
            ledger.dispatched(key)
            active=provider or SingleDispatchProvider(ProviderConfig(model='gpt-6.1-sol',reasoning_effort='high',timeout_seconds=CONFIG['timeout_seconds']))
            raw,usage=active.dispatch(packet.source.document(),dest.resolve())
            try: parsed=json.loads(raw)
            except ValueError as exc:
                ledger.finish(key,'parse_failed',perf_counter()-start,usage,str(exc)); continue
            try: verdicts=verify_verdicts(packet,match,parsed)
            except ValueError as exc:
                ledger.finish(key,'mechanically_invalid',perf_counter()-start,usage,str(exc)); continue
            ledger.finish(key,'valid',perf_counter()-start,usage)
            write_json(folder/'verdicts.json',parsed,immutable=True)
            metrics=assisted_metrics(match,verdicts)
            write_json(outcome,metrics,immutable=True)
            return metrics
        except Exception as exc:
            ledger.finish(key,'upstream_failed',perf_counter()-start,usage,f'{type(exc).__name__}: {exc}')
    metrics=assisted_metrics(match,[])
    metrics['adjudication_failed']=True
    write_json(outcome,metrics,immutable=True)
    return metrics


def aggregate(results,ledger,*,expected_denominator=None):
    denominator=len(results) if expected_denominator is None else expected_denominator
    raw_tp=sum(r['match']['raw_counts']['tp'] for r in results)
    pred=sum(r['match']['raw_counts']['prediction_denominator'] for r in results)
    ref=sum(r['match']['raw_counts']['reference_denominator'] for r in results)
    from .matching import counts
    raw=counts(raw_tp,pred,ref)
    comparable=[r['match']['semantic_comparison'] for r in results if r['match'].get('semantic_comparison')]
    semantic=None
    if comparable:
        semantic=dict(metric_version='copilot-comparable-schema-metrics/v1',
            counts=counts(sum(r['counts']['tp'] for r in comparable),
                sum(r['counts']['prediction_denominator'] for r in comparable),
                sum(r['counts']['reference_denominator'] for r in comparable)),
            original_prediction_denominator=sum(r['original_prediction_denominator'] for r in comparable),
            original_reference_denominator=sum(r['original_reference_denominator'] for r in comparable),
            not_comparable_predictions=sum(len(r['not_comparable_prediction_ids']) for r in comparable),
            not_comparable_references=sum(len(r['not_comparable_reference_ids']) for r in comparable),
            can_establish_clinical_acceptance=False)
        if not semantic['counts']['prediction_denominator'] or not semantic['counts']['reference_denominator']:
            if not semantic['counts']['prediction_denominator']: semantic['counts']['precision']=None
            if not semantic['counts']['reference_denominator']: semantic['counts']['recall']=None
            semantic['counts']['f1']=None
    reviewed=[r['assisted'] for r in results if r.get('assisted')]
    supported=sum(r['source_supported_predictions'] for r in reviewed)
    covered=sum(r['source_supported_covered_references'] for r in reviewed)
    eligible=sum(r['eligible_reference_denominator'] for r in reviewed)
    precision=supported/pred if pred else 0
    recall=covered/eligible if eligible else 0
    f1=2*precision*recall/(precision+recall) if precision+recall else 0
    attempts=ledger.rows()
    valid=sum(r['packet_status']=='valid' for r in results)
    unresolved=sum(r['unresolved_count'] for r in reviewed)
    critical=sum(len(r['critical_unsupported_disputes']) for r in reviewed)
    review_failures=sum(bool(r.get('assisted',{}).get('adjudication_failed')) for r in results if r.get('assisted'))
    unrecovered=sum(r['packet_status']!='valid' or bool((r.get('assisted') or {}).get('adjudication_failed')) for r in results)
    assisted=dict(precision=precision,recall=recall,f1=f1,prediction_denominator=pred,eligible_reference_denominator=eligible,
        supported_predictions=supported,covered_references=covered,unresolved=unresolved,critical_unsupported=critical,
        review_method='GPT-6.1 Sol/high AI-assisted; not independent clinical gold') if reviewed else None
    return dict(schema_version='copilot-evaluation-results/v2',document_denominator=denominator,evaluated_documents=len(results),valid_documents=valid,
        mechanical_pass_rate=valid/denominator if denominator else 0,raw=raw,semantic_comparison=semantic,ai_assisted=assisted,
        label_types=sorted({r['match']['reference_type'] for r in results}),
        model_calls=sum(r['dispatched'] for r in attempts),retries=sum(r['attempt']>1 for r in attempts),
        request_failures=sum(r['status'] not in {'valid','reserved'} for r in attempts),unrecovered_documents=unrecovered,
        adjudication_failed_documents=review_failures,active_or_uncertain_requests=sum(r['status']=='reserved' for r in attempts),
        unprocessed_documents=denominator-len(results),
        acceptance_passed=bool(denominator==len(results) and reviewed and len(reviewed)==len(results) and valid==len(results) and unresolved==0 and precision>=.95 and recall>=.9 and f1>=.92 and critical==0),
        note='Engineering acceptance only; source validity does not certify clinical interpretation. Final acceptance requires the frozen final partition, never development alone.')


def execute(records,root,manifest,*,slots_path,review=True,luna_provider=None,sol_provider=None):
    root=Path(root).resolve(); root.mkdir(parents=True,exist_ok=True)
    identity=freeze_run(root,records,manifest)
    ledger=AttemptLedger(root/'requests.sqlite3',identity)
    slots=LunaSlots(slots_path)
    if luna_provider is None:
        SingleDispatchProvider(ProviderConfig(model='gpt-6-luna',reasoning_effort='high')).preflight()
    if review and sol_provider is None:
        SingleDispatchProvider(ProviderConfig(model='gpt-6.1-sol',reasoning_effort='high')).preflight()
    lock=root/'runner.lock'
    with lock.open('x',encoding='utf-8') as f: f.write(json.dumps({'started_at':now(),'run_hash':identity['run_hash']}))
    results=[]
    try:
        def work(record):
            p=run_extraction(record,root,identity,ledger,slots,provider=luna_provider)
            refs=summary_references(record['reference'],record['reference_type'])
            match=structured_match(p,refs)
            folder=root/'cases'/digest(record['case_id'])[:20]
            write_json(folder/'raw-match.json',match,immutable=True)
            return record,p,match
        with ThreadPoolExecutor(max_workers=CONFIG['luna_workers']) as pool:
            futures=[pool.submit(work,r) for r in records]
            completed=[]
            for future in as_completed(futures):
                record,p,match=future.result(); completed.append((record,p,match))
                print(json.dumps({'stage':'extraction','case_id':record['case_id'],'completed':len(completed),'denominator':len(records),'status':p.extraction_status,'disputes':len(match['disputes'])}),flush=True)
        def adjudicate(item):
            record,p,match=item
            assisted=run_adjudication(record,p,match,root,identity,ledger,provider=sol_provider) if review else None
            return dict(case_id=record['case_id'],packet_status=p.extraction_status,match=match,assisted=assisted)
        with ThreadPoolExecutor(max_workers=CONFIG['sol_workers']) as pool:
            futures=[pool.submit(adjudicate,item) for item in completed]
            for future in as_completed(futures):
                results.append(future.result())
                write_json(root/'progress.json',aggregate(results,ledger,expected_denominator=len(records)))
                print(json.dumps({'stage':'adjudication','completed':len(results),'denominator':len(records)}),flush=True)
        results.sort(key=lambda r:r['case_id'])
        write_json(root/'case-results.json',results,immutable=True)
        summary=aggregate(results,ledger,expected_denominator=len(records))
        summary['run_hash']=identity['run_hash']; summary['partition']=records[0]['partition'] if records else None
        write_json(root/'results.json',summary,immutable=True)
        return summary
    finally:
        lock.unlink(missing_ok=True)


def rescore_cache(records,cache_root,root,manifest,*,review=True,sol_provider=None,prior_review_root=None):
    """New evaluator run, same frozen inputs and immutable prior extraction cache."""
    from ..models import Packet
    from .reference_format import decode_reference
    cache_root=Path(cache_root).resolve(); root=Path(root).resolve()
    if root==cache_root: raise ValueError('Rescore must have a separate output root')
    parent=json.loads((cache_root/'execution-freeze.json').read_text(encoding='utf-8'))
    if parent['split_manifest_hash']!=manifest['manifest_hash']:
        raise ValueError('Cache uses a different frozen split')
    requested=[dict(case_id=r['case_id'],group_id=r['group_id'],input_kind=r['input_kind'],
        source_hash=digest(r['text']),reference_hash=digest(r['reference']),partition=r['partition']) for r in records]
    if parent['documents']!=requested: raise ValueError('Cache source/reference identities or denominator differ')
    if (cache_root/'runner.lock').exists(): raise ValueError('Wait for extraction to finish before sealing cache')
    root.mkdir(parents=True,exist_ok=True)
    identity=freeze_run(root,records,manifest)
    identity={**identity,'parent_extraction_run_hash':parent['run_hash']}
    ledger=AttemptLedger(root/'requests.sqlite3',identity)
    with sqlite3.connect(cache_root/'requests.sqlite3') as db:
        parent_counts=dict(calls=db.execute('SELECT SUM(dispatched) FROM attempts').fetchone()[0],
            retries=db.execute('SELECT COUNT(*) FROM attempts WHERE attempt>1').fetchone()[0],
            request_failures=db.execute("SELECT COUNT(*) FROM attempts WHERE status!='valid'").fetchone()[0])
    write_json(root/'parent-extraction.json',{'run_hash':parent['run_hash'],**parent_counts},immutable=True)
    inputs=[]; strict_failures=0
    for record in records:
        folder=cache_root/'cases'/digest(record['case_id'])[:20]
        path=folder/'packet.json'
        p=Packet.model_validate_json(path.read_text(encoding='utf-8')).verify()
        if p.source.sha256!=digest(record['text']) or p.patient_id!=record['group_id']:
            raise ValueError('Cached packet source/case identity mismatch')
        target=root/'cases'/digest(record['case_id'])[:20]
        write_json(target/'packet.json',p.model_dump(mode='json'),immutable=True)
        _,format_record=decode_reference(record['reference'])
        strict_failures+=not format_record['original_strict_parse_passed']
        write_json(target/'reference-format.json',format_record,immutable=True)
        refs=summary_references(record['reference'],record['reference_type'])
        match=structured_match(p,refs)
        write_json(target/'raw-match.json',match,immutable=True)
        inputs.append((record,p,match))
    write_json(root/'reference-format-summary.json',dict(denominator=len(records),original_strict_failures=strict_failures,
        adapted_projection_successes=len(records),original_labels_unchanged=True,new_luna_calls=0),immutable=True)
    before={str(p.relative_to(cache_root)):file_hash(p) for p in cache_root.rglob('*') if p.is_file()}
    write_json(root/'parent-cache-hashes.json',before,immutable=True)
    if review and sol_provider is None:
        SingleDispatchProvider(ProviderConfig(model='gpt-6.1-sol',reasoning_effort='high')).preflight()
    lock=root/'runner.lock'
    with lock.open('x',encoding='utf-8') as f: f.write(json.dumps({'started_at':now(),'kind':'cache_rescore'}))
    results=[]
    try:
        def work(item):
            record,p,match=item
            assisted=run_adjudication(record,p,match,root,identity,ledger,provider=sol_provider,prior_review_root=prior_review_root) if review else None
            return dict(case_id=record['case_id'],packet_status=p.extraction_status,match=match,assisted=assisted)
        with ThreadPoolExecutor(max_workers=CONFIG['sol_workers']) as pool:
            futures=[pool.submit(work,item) for item in inputs]
            for future in as_completed(futures):
                results.append(future.result())
                progress=aggregate(results,ledger,expected_denominator=len(records))
                progress['selected_document_denominator']=len(records)
                progress['parent_luna_calls']=parent_counts['calls']
                write_json(root/'progress.json',progress)
                print(json.dumps({'stage':'cache_adjudication','completed':len(results),'denominator':len(records)}),flush=True)
        results.sort(key=lambda r:r['case_id'])
        write_json(root/'case-results.json',results,immutable=True)
        summary=aggregate(results,ledger,expected_denominator=len(records))
        summary.update(parent_luna_calls=parent_counts['calls'],parent_luna_retries=parent_counts['retries'],new_luna_calls=0,
            original_strict_reference_failures=strict_failures,parent_extraction_run_hash=parent['run_hash'],
            run_hash=identity['run_hash'],partition=records[0]['partition'] if records else None)
        after={str(p.relative_to(cache_root)):file_hash(p) for p in cache_root.rglob('*') if p.is_file()}
        if before!=after: raise ValueError('Original extraction cache changed during rescore')
        write_json(root/'cache-preservation.json',dict(files=len(before),unchanged=True,new_luna_calls=0),immutable=True)
        write_json(root/'results.json',summary,immutable=True)
        return summary
    finally:
        lock.unlink(missing_ok=True)
