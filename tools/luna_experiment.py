"""Cache-free, resumable real-Luna experiments with immutable per-request records.

Run from the repository root with PYTHONPATH=src. Gold is read only by this parent
process; the disabled-tool CLI runs in an empty directory with the request only.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter, sleep
import sys
import importlib.metadata

from clinical_intelligence.demo import corpus
from clinical_intelligence.domain import DocumentExtraction, RegisteredDocument
from clinical_intelligence.extraction import LangExtractExtractor, normalize_clock_fields
from clinical_intelligence.luna_candidates import CandidateExtractor
from clinical_intelligence.provider import CodexCLIProvider, ProviderConfig
from clinical_intelligence.reconcile import reconcile
from clinical_intelligence.query import query_patient, QuerySpec

ROOT = Path(__file__).resolve().parents[1]
SCORER_VERSION = "critical-fields-9"
CANDIDATES = {
    "baseline": dict(schema="string", reasoning="high"),
    "clinical_partition": json.loads((ROOT/'src/clinical_intelligence/contracts/luna_best.json').read_text(encoding='utf-8')),
}
CANDIDATES['semantic_resample'] = {
    **{k:v for k,v in CANDIDATES['clinical_partition'].items() if k != 'observation_scope'},
    'flow': 'resample_repair',
}


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def code_identity():
    paths=list((ROOT/'src/clinical_intelligence').glob('*.py'))+list((ROOT/'src/clinical_intelligence/contracts').glob('*.json'))
    paths += [ROOT/'tools'/name for name in ('luna_experiment.py','analyze_luna.py','luna_quality.py','luna_freeze.py')]
    return dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        packages={name:importlib.metadata.version(name) for name in ('langextract','pydantic','intervaltree')},
        cli_version=subprocess.check_output([__import__('shutil').which('codex'),'--version'],text=True,encoding='utf-8').strip())


def verify_freeze(path,candidates,code):
    frozen=json.loads(Path(path).read_text(encoding='utf-8'))
    for field in ('files','packages','cli_version'):
        if frozen['code'][field]!=code[field]:raise ValueError(f'Candidate freeze mismatch: {field}')
    if frozen['sealed_dataset_sha256']!=digest(datasets(['sealed'])):raise ValueError('Sealed data changed after freeze')
    if any(frozen['candidates'].get(c)!=CANDIDATES[c] for c in candidates):raise ValueError('Candidate not frozen')
    return digest(frozen)


class RecordingProvider(CodexCLIProvider):
    def __init__(self, config, output):
        super().__init__(config)
        self.output = output
        self.invocations = 0

    def run_cli(self, command, request, folder):
        # Retry only transport failures, never based on scores or clinical output.
        for attempt in range(3):
            self.invocations += 1
            # A prior failed attempt may have written its answer before transport
            # failed. A successful attempt must produce its own final response.
            if (folder/'answer.json').exists():(folder/'answer.json').unlink()
            call = self.output / f"call-{self.invocations:02d}"
            call.mkdir(exist_ok=False)
            (call / "prompt.txt").write_text(request, encoding="utf-8")
            schema = json.loads((folder / "schema.json").read_text(encoding="utf-8"))
            dump(call / "schema.json", schema)
            dump(call / "request.json", {"argv":command,"prompt_sha256":digest(request),"schema_sha256":digest(schema),
                 "requested_model":self.config.model,"reasoning":self.config.reasoning_effort,
                 "cli_version":self.cli_version,"backend_model":"unavailable: CLI events do not expose resolved backend snapshot",
                 "application_cache_hit":False,"attempt":attempt,"tools":"disabled","cwd_isolated":True})
            began = perf_counter()
            try:
                result = super().run_cli(command, request, folder)
            except subprocess.TimeoutExpired as error:
                dump(call / "transport.json", {"status":"timeout","seconds":perf_counter()-began})
                # A timed-out server generation can consume usage, but it is not
                # observable. Report it as unknown, never zero tokens.
                if attempt == 2:
                    raise
                sleep((5,15)[attempt])
                continue
            (call / "cli_events.jsonl").write_text(result.stdout,encoding="utf-8")
            (call / "stderr.txt").write_text(result.stderr,encoding="utf-8")
            if (folder / "answer.json").exists():
                (call / "answer.json").write_text((folder / "answer.json").read_text(encoding="utf-8"),encoding="utf-8")
            dump(call / "transport.json",{"status":"completed" if result.returncode==0 else "failed","exit":result.returncode,"seconds":perf_counter()-began})
            transient = result.returncode and any(word in (result.stderr+result.stdout).lower() for word in
                ("rate limit","429","temporarily unavailable","502","503","connection reset","stream disconnected"))
            if transient and attempt < 2:
                sleep((5,15)[attempt])
                continue
            return result


def datasets(splits, private=None):
    rows = []
    if "public" in splits:
        for item in corpus():
            rows.append(dict(id=item['declared_id'],group=item['patient']['patient_id'],source="public_synthetic",split="dev",
                text=item['text'],patient=item['patient'],declared_id=item['declared_id'],facts=item['claims'],exhaustive=True))
    for split in ("dev","validation","sealed"):
        if split in splits:
            rows += json.loads((ROOT / f"tests/fixtures/luna/{split}.json").read_text(encoding="utf-8"))
    if "original" in splits:
        if not private:
            raise ValueError("Original source requires a private, reviewed annotation file")
        rows += json.loads(Path(private).read_text(encoding="utf-8"))
    return rows


def normalized(fact):
    value = dict(fact)
    value.pop("quote",None)
    return normalize_clock_fields(value['kind'],value)


def field_equal(expected, actual, field):
    # Named roles use case-insensitive exact gold aliases. No model judge or Luna
    # self-evaluation participates in scoring.
    if field in {"reporter","experiencer"}:
        choices = expected if isinstance(expected,list) else [expected]
        name=re.sub(r",\s*(?:partner|patient|parent|LCSW|NP|LPC|PMHNP)$", "", str(actual), flags=re.I)
        return name.casefold() in {str(x).casefold() for x in choices}
    if field=='instrument':
        return str(expected).casefold()==str(actual).casefold()
    if field=='recorded_at' and expected and actual and isinstance(actual,str):
        return datetime.fromisoformat(expected).isoformat()==datetime.fromisoformat(actual).isoformat()
    if field in {"service_types"}:
        return sorted(expected)==sorted(actual or [])
    return expected==actual


def score(row, extraction):
    expected = [normalized(f) for f in row['facts']]
    raw = [c.model_dump(mode="json") for c in extraction.claims] if extraction else []
    actual = fact_view(raw)
    # The runtime contract explicitly allows person OR role. Normalize only
    # unambiguous patient/partner role aliases, without changing asserted facts.
    for fact in expected:
        for field in ('reporter','experiencer'):
            value=fact.get(field)
            if value==row['patient']['name']:
                fact[field]=[value,'patient',"the patient"]
            elif value=='partner':
                fact[field]=['partner',"patient's partner",'the partner']
    mismatches = []
    groups = {"identity": [0,0,0], "binding":[0,0,0], "time":[0,0,0], "semantics":[0,0,0], "relationships":[0,0,0], "grounding":[0,0,0]}
    def record(group, label, wanted, got, equal):
        groups[group][0 if equal else 2] += 1
        if not equal:
            if got is not None:
                groups[group][1] += 1
            mismatches.append(dict(field=label,expected=wanted,actual=got))
    for field,value in row['patient'].items():
        record("identity",field,value,extraction.patient.model_dump(mode="json").get(field) if extraction else None,
               bool(extraction) and extraction.patient.model_dump(mode="json").get(field)==value)
    record("identity","declared_id",row['declared_id'],extraction.declared_id if extraction else None,bool(extraction) and extraction.declared_id==row['declared_id'])
    # Match claims by kind, stable IDs and closest fact fields, without selecting
    # among model responses. All outputs are scored, unmatched claims penalized.
    used = set()
    for i,fact in enumerate(expected):
        fields = {k:v for k,v in fact.items() if k not in {"kind","statement","keywords"}}
        candidates=[]
        for j,claim in enumerate(actual):
            if j in used or claim['kind']!=fact['kind']:
                continue
            matches=sum(field_equal(v,claim.get(k),k) for k,v in fields.items())
            ids=sum(field_equal(v,claim.get(k),k) for k,v in fields.items() if k.endswith('_ref') or k=='target_encounter')
            meanings=sum(word.lower() in claim.get('statement','').lower() for word in fact.get('keywords',[]))
            candidates.append((ids*100+matches*10+meanings*2,j))
        chosen=max(candidates)[1] if candidates else None
        claim=actual[chosen] if chosen is not None else {}
        if chosen is not None:
            used.add(chosen)
        for field,wanted in fields.items():
            group="binding" if field.endswith('_ref') or field=='target_encounter' else "time" if 'date' in field or 'interval' in field or field in {'breaks','reported_minutes','recorded_at'} else "relationships" if fact['kind']=='relationship' else "semantics"
            record(group,f"{i}:{fact['kind']}.{field}",wanted,claim.get(field),chosen is not None and field_equal(wanted,claim.get(field),field))
        if fact.get('keywords'):
            statement=str(claim.get('statement','')).lower()
            equal=all(word.lower() in statement for word in fact['keywords'])
            record("semantics",f"{i}:meaning",fact['keywords'],statement if chosen is not None else None,equal)
    for j,claim in enumerate(actual):
        # Original annotation intentionally excludes scheduling callbacks with no
        # clinical contact; these administrative claims cannot establish therapy.
        supported_extra=any(claim['kind']==fact['kind'] and all(field_equal(v,claim.get(k),k) for k,v in fact.items() if k!='kind') for fact in row.get('allowed_extra_facts',[]))
        unscored = supported_extra or not row.get('exhaustive',True) and (claim['kind'] in {'observation','functional_action'} or
            (claim['kind']=='service' and claim.get('service_type')=='administrative'))
        if j not in used and not unscored:
            groups['semantics'][1]+=1
            mismatches.append(dict(field="extra_claim",actual=claim))
    for claim in raw:
        for passage in claim['passages']:
            equal=row['text'][passage['start']:passage['end']]==passage['quote']
            record('grounding','quote',True,equal,equal)
    tp=sum(g[0] for k,g in groups.items() if k!='grounding');fp=sum(g[1] for k,g in groups.items() if k!='grounding');fn=sum(g[2] for k,g in groups.items() if k!='grounding')
    return dict(version=SCORER_VERSION,tp=tp,fp=fp,fn=fn,groups=groups,precision=tp/(tp+fp) if tp+fp else 0,
                recall=tp/(tp+fn) if tp+fn else 0,document_correct=bool(extraction) and not mismatches,
                misleading_success=bool(extraction) and bool(mismatches),mismatches=mismatches)


def fact_view(claims):
    """Score equivalent compatible claim splitting without hiding alternatives.

    Only same-document service facts with the SAME explicit identity/date/type/
    evidence-kind are grouped. Empty optional fields contribute no invented fact.
    Incompatible scalar values remain explicit conflicts and cannot match gold.
    This view is for scoring only; deployed reconciliation sees original claims.
    """
    groups={};other=[]
    for claim in claims:
        if claim['kind']!='service' or not (claim.get('encounter_ref') or claim.get('appointment_ref')):
            other.append(claim);continue
        key=(claim.get('encounter_ref'),claim.get('appointment_ref'),claim.get('service_date'),claim.get('service_type'),claim.get('evidence_kind'))
        groups.setdefault(key,[]).append(claim)
    for values in groups.values():
        merged=dict(values[0])
        for field in ('actual_intervals','scheduled_intervals','unspecified_intervals','breaks'):
            intervals={json.dumps(v,sort_keys=True):v for c in values for v in c.get(field,[])}
            merged[field]=sorted(intervals.values(),key=lambda v:(v['start'],v['end']))
        for field in ('signed','patient_present','delivered','reported_minutes','recorded_at'):
            distinct={json.dumps(c.get(field),sort_keys=True):c.get(field) for c in values if c.get(field) is not None}
            merged[field]=next(iter(distinct.values())) if len(distinct)==1 else {'conflicting_values':list(distinct.values())} if distinct else None
        merged['statement']='; '.join(c.get('statement','') for c in values)
        other.append(merged)
    return other


def execute(row, candidate, repeat, run, cfg, code):
    out=run/candidate/f"repeat-{repeat:02d}"/row['id']
    if (out/'result.json').exists():
        return json.loads((out/'result.json').read_text(encoding='utf-8'))
    out.mkdir(parents=True,exist_ok=True)
    # Partial calls survive interruption. Resume uses a new attempt folder, never
    # overwrites or promotes an old answer to a new model repeat.
    attempt=1
    while (out/f"attempt-{attempt:02d}").exists():
        attempt+=1
    work=out/f"attempt-{attempt:02d}";work.mkdir()
    dump(work/'input.json',dict(text=row['text'],sample_id=row['id'],source=row['source']))
    provider=RecordingProvider(ProviderConfig(reasoning_effort=cfg.get('reasoning','high'),timeout_seconds=180),work)
    extractor=CandidateExtractor(provider,cfg)
    document=RegisteredDocument(document_id=hashlib.sha256(row['text'].encode()).hexdigest(),fingerprint=digest(row['text']),source_names=[row['id']+'.txt'],text=row['text'])
    started=perf_counter();extraction=None;error=None
    try:
        extraction=extractor.extract(document)
    except Exception as problem:
        error=str(problem)
    usage=extraction.usage.model_dump(mode='json') if extraction else provider.usage(perf_counter()-started).model_dump(mode='json')
    # Account for every actual CLI attempt, including failed transport attempts
    # hidden behind the provider's successful last retry.
    totals={};unknown=0
    for call in work.glob('call-*'):
        stream=call/'cli_events.jsonl';found=False
        if stream.exists():
            for line in stream.read_text(encoding='utf-8').splitlines():
                try:event=json.loads(line)
                except json.JSONDecodeError:continue
                if event.get('type')=='turn.completed' and event.get('usage'):
                    found=True
                    for key,value in event['usage'].items():
                        if isinstance(value,int):totals[key]=totals.get(key,0)+value
        if not found:unknown+=1
    usage['settings']['all_cli_attempt_usage']=totals
    usage['settings']['attempts_without_reported_usage']=unknown
    if unknown:
        usage['input_tokens']=usage['output_tokens']=usage['cached_tokens']=None
    else:
        usage['input_tokens']=totals.get('input_tokens');usage['output_tokens']=totals.get('output_tokens');usage['cached_tokens']=totals.get('cached_input_tokens')
    result=dict(experiment_id=run.name,candidate=candidate,configuration=cfg,configuration_id=digest(cfg),repeat=repeat,
        sample_id=row['id'],group=row['group'],source=row['source'],dataset_version=digest(row),code=code,
        validation='accepted' if extraction else 'failed',failure=error,seconds=perf_counter()-started,
        cli_invocations=provider.invocations,usage=usage,application_cache_hit=False,
        extraction=extraction.model_dump(mode='json') if extraction else None,score=score(row,extraction))
    dump(out/'result.json',result)
    return result


def summarize(results):
    by={}
    for r in results:
        bucket=by.setdefault(r['candidate']+'/'+r['source'],dict(documents=0,correct=0,accepted=0,misleading=0,calls=0,tp=0,fp=0,fn=0,seconds=0,input_tokens=0,output_tokens=0,tokens_unknown=0,groups={}))
        bucket['documents']+=1;bucket['correct']+=r['score']['document_correct'];bucket['accepted']+=r['validation']=='accepted'
        bucket['misleading']+=r['score']['misleading_success'];bucket['calls']+=r['cli_invocations'];bucket['seconds']+=r['seconds']
        for name in ('tp','fp','fn'):bucket[name]+=r['score'][name]
        for group,values in r['score']['groups'].items():
            total=bucket['groups'].setdefault(group,[0,0,0])
            for i,v in enumerate(values):total[i]+=v
        for name in ('input_tokens','output_tokens'):
            value=r['usage'].get(name)
            if value is None:bucket['tokens_unknown']+=1
            else:bucket[name]+=value
    for b in by.values():
        b['precision']=b['tp']/(b['tp']+b['fp']) if b['tp']+b['fp'] else 0
        b['recall']=b['tp']/(b['tp']+b['fn']) if b['tp']+b['fn'] else 0
    return by


def downstream(rows, results):
    output=[]
    combinations=sorted({(r['candidate'],r['repeat']) for r in results})
    for candidate,repeat in combinations:
        for group in sorted({r['group'] for r in rows}):
            expected_rows=[r for r in rows if r['group']==group]
            records=[r for r in results if r['candidate']==candidate and r['repeat']==repeat and r['group']==group]
            record=dict(candidate=candidate,repeat=repeat,group=group)
            if len(records)!=len(expected_rows) or any(r['validation']!='accepted' for r in records):
                record['status']='blocked_incomplete_evidence';record['answer']=None
            else:
                try:
                    abstractions=reconcile([DocumentExtraction.model_validate(r['extraction']) for r in records])
                    record['events']=[dict(encounter=e.encounter_ref,minutes=e.minute_options,state=str(e.state),countable=e.countable) for e in abstractions.events]
                    record['answer']=query_patient(abstractions,QuerySpec(family='utilization',start='2026-01-01',end='2026-12-31'))
                    record['clinical_progress']=query_patient(abstractions,QuerySpec(family='progress',start='2026-01-01',end='2026-12-31'))['result']
                    record['status']='answered'
                except Exception as error:
                    record['status']='query_failed';record['failure']=str(error)
            output.append(record)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True);parser.add_argument('--candidates',nargs='+',choices=CANDIDATES,required=True)
    parser.add_argument('--splits',nargs='+',default=['public','dev']);parser.add_argument('--private')
    parser.add_argument('--repeat',type=int,default=1);parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--samples',nargs='*');parser.add_argument('--allow-sealed',action='store_true');parser.add_argument('--freeze')
    args=parser.parse_args()
    if 'sealed' in args.splits and (not args.allow_sealed or not args.freeze):raise ValueError('Sealed input requires --freeze and --allow-sealed')
    run=ROOT/'artifacts/luna-20261008'/args.run;run.mkdir(parents=True,exist_ok=True)
    scratch=ROOT/'artifacts/luna-20261008/tmp';scratch.mkdir(parents=True,exist_ok=True)
    os.environ['TMP']=os.environ['TEMP']=str(scratch);tempfile.tempdir=str(scratch)
    rows=datasets(args.splits,args.private)
    if args.samples:rows=[r for r in rows if r['id'] in args.samples]
    code=code_identity()
    freeze_sha256=verify_freeze(args.freeze,args.candidates,code) if 'sealed' in args.splits else None
    manifest=dict(experiment=args.run,arguments=vars(args),dataset_sha256=digest(rows),samples=[{k:r[k] for k in ('id','source','group','split')} for r in rows],
                  code=code,scorer=SCORER_VERSION,candidates={c:CANDIDATES[c] for c in args.candidates},model='gpt-6-luna',application_cache='disabled',backend='unavailable',freeze_sha256=freeze_sha256)
    if (run/'manifest.json').exists():
        if json.loads((run/'manifest.json').read_text())!=manifest:raise ValueError('Cannot resume with different data/config/code; create a new run namespace')
    else:dump(run/'manifest.json',manifest)
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending=[pool.submit(execute,row,c,repeat,run,CANDIDATES[c],code) for c in args.candidates for repeat in range(1,args.repeat+1) for row in rows]
        for future in as_completed(pending):
            result=future.result();results.append(result)
            print(json.dumps({k:result[k] for k in ('candidate','repeat','sample_id','validation','failure','cli_invocations')},ensure_ascii=True),flush=True)
            dump(run/'checkpoint.json',dict(completed=len(results),total=len(pending),summary=summarize(results)))
    dump(run/'summary.json',summarize(results));dump(run/'downstream.json',downstream(rows,results))
    print(json.dumps(summarize(results)),flush=True)


if __name__=='__main__':main()
