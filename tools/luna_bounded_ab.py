"""Serial, persistent, hard-timeboxed prompt-only experiment. No transport retries.

Inputs/labels and complete audit stay in an ignored round directory. Prediction
never decodes labels. A terminated/in-flight reservation is retained, never rerun.
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from clinical_intelligence.claims_review.cli import live_provider
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.note_extractor import PROMPT, note_request, validate_proposal
from clinical_intelligence.claims_review.note_prompt_b import PROMPT_B
from clinical_intelligence.claims_review.prepare import prepare_case
from clinical_intelligence.claims_review.review import load_policy, run_review

VERSION = 'luna-bounded-ab/1'
TERMINAL = {'COMPLETED','BUDGET_STOP','TIMEBOX_STOP','BENCHMARK_INVALID','NEEDS_SEPARATE_CONTRACT_FIX','BLOCKED'}
ROOT = Path(__file__).resolve().parents[1]


def now():return datetime.now(timezone.utc)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(path)


def fixed_plan(seed=20261009):
    rng=random.Random(seed);plan=[]
    for split,repeats in [('dev',1),('confirm',2)]:
        for repeat in range(1,repeats+1):
            ids=list(range(1,9));rng.shuffle(ids)
            for number in ids:
                candidates=['A','B'];rng.shuffle(candidates)
                for candidate in candidates:
                    plan.append(dict(execution_id=f'{split}-{number:02d}-{candidate}-r{repeat}',
                        split=split,case_id=f'{split.upper()}-{number:02d}',candidate=candidate,repeat=repeat,status='pending',calls=[]))
    return plan


def frozen_files(round_dir):
    paths=[*sorted((ROOT/'src').rglob('*.py')),*sorted((ROOT/'src').rglob('*.json')),
           ROOT/'tools/luna_bounded_ab.py',ROOT/'tools/score_luna_ab.py',round_dir/'build_suite.py',
           round_dir/'semantic_contract.md',round_dir/'expected.json',*sorted((round_dir/'inputs').glob('*.json'))]
    return {str(p.resolve()):sha(p) for p in paths}


def freeze(round_dir):
    state=read(round_dir/'round_state.json')
    if (round_dir/'freeze.json').exists():raise ValueError('Already frozen; never overwrite')
    if state['attempts']!=0 or state['phase']!='PREPARING':raise ValueError('Preparation state required; never reset existing attempts')
    if now()>=datetime.fromisoformat(state['execution_deadline']):raise ValueError('Timebox expired')
    old=Path('D:/Codex/Take Home Excerise/clinical-evidence-review/artifacts/claims-review/live-budget.json')
    state['historical_ledger']={'path':str(old),'sha256':sha(old),'count':len(read(old)['calls']),'limit':read(old)['limit']}
    state.update(plan=fixed_plan(),phase='FROZEN',seed=20261009,attempts=0,calls=[],
        model='gpt-6-luna',reasoning='high',request_timeout_seconds=180,maximum_calls_per_execution=2)
    save(round_dir/'round_state.json',state)
    requests={}
    for p in sorted((round_dir/'inputs').glob('*.json')):
        case=CaseInput.model_validate_json(p.read_bytes());prepared=prepare_case(case,load_policy(),input_label=p.name)
        notes=[s for s in prepared['source_candidates'] if s['source_kind']=='synthetic_note']
        if len(notes)!=1:raise ValueError(f'{p}: exactly one eligible note required')
        for c in ['A','B']:
            prompt,schema=note_request(notes[0],case.claim.model_dump(mode='json'),prompt_variant=c)
            folder=round_dir/'requests'/p.stem/c;folder.mkdir(parents=True)
            (folder/'prompt.txt').write_text(prompt,encoding='utf-8');save(folder/'schema.json',schema)
            requests[f'{p.stem}-{c}']={'prompt':sha(folder/'prompt.txt'),'schema':sha(folder/'schema.json')}
    (round_dir/'prompt_A.txt').write_text(PROMPT,encoding='utf-8');(round_dir/'prompt_B.txt').write_text(PROMPT_B,encoding='utf-8')
    frozen={'version':VERSION,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'limits':{k:state[k] for k in ['start_utc','execution_deadline','delivery_deadline','max_provider_requests','model','reasoning']},
        'files':frozen_files(round_dir),'requests':requests,'prompts':{'A':sha(round_dir/'prompt_A.txt'),'B':sha(round_dir/'prompt_B.txt')},
        'plan_sha256':hashlib.sha256(json.dumps(fixed_plan(),sort_keys=True).encode()).hexdigest(),
        'method':'AI-assisted fact-first constructed cases; designer nonblind; inference receives sources only. No human or clinical-expert gold.'}
    save(round_dir/'freeze.json',frozen);print('FROZEN: 48 executions; no model calls',flush=True)


class StopRound(RuntimeError):pass


class RoundProvider:
    def __init__(self,round_dir,state,item,provider):
        self.directory=round_dir;self.state=state;self.item=item;self.provider=provider

    def structured_output(self,prompt,schema,*,purpose):
        state=self.state;remaining=(datetime.fromisoformat(state['execution_deadline'])-now()).total_seconds()
        # Reserve cleanup time so the existing CLI tree kill finishes by the deadline.
        if remaining<=15:
            state['phase']='TIMEBOX_STOP';save(self.directory/'round_state.json',state);raise StopRound('Timebox cleanup reserve')
        if state['attempts']>=96:
            state['phase']='BUDGET_STOP';save(self.directory/'round_state.json',state);raise StopRound('96-request ceiling')
        if len(self.item['calls'])>=2:raise StopRound('Two-request execution ceiling')
        frozen=read(self.directory/'freeze.json')
        identity=lambda p:{k:p[k] for k in ['execution_id','split','case_id','candidate','repeat']}
        if (any(sha(p)!=h for p,h in frozen['files'].items()) or
            any(state.get(k)!=v for k,v in frozen['limits'].items()) or
            [identity(p) for p in state['plan']]!=[identity(p) for p in fixed_plan()] or
            state['attempts']!=len(state['calls'])):
            state['phase']='BENCHMARK_INVALID';save(self.directory/'round_state.json',state);raise StopRound('Frozen version drift')
        number=state['attempts']+1;folder=self.directory/'calls'/f'call-{number:03d}';folder.mkdir(parents=True,exist_ok=False)
        call={'number':number,'execution_id':self.item['execution_id'],'purpose':purpose,'started_at':now().isoformat(),
              'folder':str(folder),'status':'reserved_before_provider_call','timeout_seconds':min(180,int(remaining)-12)}
        state['attempts']=number;state['calls'].append(call);self.item['calls'].append(number)
        save(self.directory/'round_state.json',state)
        (folder/'prompt.txt').write_text(prompt,encoding='utf-8');save(folder/'schema.json',schema)
        self.provider.audit_path=folder;self.provider.config.timeout_seconds=call['timeout_seconds']
        started=perf_counter()
        try:
            raw=self.provider.structured_output(prompt,schema,purpose=purpose)
            save(folder/'answer.json',raw);call['status']='completed';return raw
        except Exception as error:
            call.update(status='failed',error=str(error));save(folder/'failure.json',{'error':str(error)});raise
        finally:
            call.update(ended_at=now().isoformat(),seconds=perf_counter()-started)
            save(folder/'usage.json',self.provider.usage(0).model_dump(mode='json'))
            save(self.directory/'round_state.json',state)


def predict(round_dir):
    state=read(round_dir/'round_state.json');frozen=read(round_dir/'freeze.json')
    if state['phase'] in TERMINAL:print('Terminal state:',state['phase']);return
    if any(sha(p)!=h for p,h in frozen['files'].items()):
        state['phase']='BENCHMARK_INVALID';save(round_dir/'round_state.json',state);return
    lock=round_dir/'prediction.lock'
    with lock.open('x',encoding='utf-8') as handle:handle.write(str(os.getpid()))
    state['runner_pid']=os.getpid();state['phase']='PREDICTING';save(round_dir/'round_state.json',state)
    # The watchdog owns only this runner and its descendants. It never kills user processes.
    def expire():
        latest=read(round_dir/'round_state.json');latest.update(phase='TIMEBOX_STOP',interrupted_at=now().isoformat())
        save(round_dir/'round_state.json',latest)
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(os.getpid()),'/T','/F'],capture_output=True,timeout=10)
        else:os._exit(124)
    watchdog=threading.Timer(max(0,(datetime.fromisoformat(state['execution_deadline'])-now()).total_seconds()),expire)
    watchdog.daemon=True;watchdog.start()
    try:
        for item in state['plan']:
            if item['status']!='pending':
                if item['status']=='running':
                    item['status']='interrupted';state['phase']='BLOCKED';break
                continue
            if state['phase'] in TERMINAL:break
            if now()>=datetime.fromisoformat(state['execution_deadline']):state['phase']='TIMEBOX_STOP';break
            item['status']='running';save(round_dir/'round_state.json',state)
            path=round_dir/'inputs'/f"{item['case_id']}.json";case=CaseInput.model_validate_json(path.read_bytes())
            args=SimpleNamespace(model='gpt-6-luna',reasoning='high',timeout=180,
                ledger=Path(state['historical_ledger']['path']),trace_directory=round_dir/'unused_old_adapter')
            # Reuse the audited CLI transport, not the old phase's BudgetedProvider.
            old_adapter,usage=live_provider(args);base=old_adapter.provider
            provider=RoundProvider(round_dir,state,item,base);started=perf_counter()
            try:
                packet=run_review(case,mode='live',provider=provider,usage=usage,input_label=str(path),note_prompt=item['candidate'])
                output=round_dir/'predictions'/f"{item['execution_id']}.json"
                save(output,packet.model_dump(mode='json'));item.update(status='saved',output=str(output),output_sha256=sha(output),
                    execution_failed=packet.execution['execution_failed'],seconds=perf_counter()-started)
            except Exception as error:
                item.update(status='execution_failed',error=str(error),seconds=perf_counter()-started)
            save(round_dir/'round_state.json',state)
            print(item['execution_id'],item['status'],'calls',len(item['calls']),'total',state['attempts'],flush=True)
        if state['phase'] not in TERMINAL:state['phase']='COMPLETED' if all(i['status']!='pending' for i in state['plan']) else 'BLOCKED'
    except Exception as error:
        state.update(phase='BLOCKED',blocking_error=str(error))
    finally:
        watchdog.cancel();lock.unlink(missing_ok=True)
        if sha(state['historical_ledger']['path'])!=state['historical_ledger']['sha256']:state['phase']='BENCHMARK_INVALID'
        state['stopped_at']=now().isoformat();save(round_dir/'round_state.json',state)
        save(round_dir/'prediction-seal.json',{'phase':state['phase'],'sealed_at':now().isoformat(),
            'labels_decoded_by_predict':False,'outputs':{str(p):sha(p) for p in sorted((round_dir/'predictions').glob('*.json'))},
            'calls':state['attempts'],'completed_executions':sum(i['status']=='saved' for i in state['plan'])})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['freeze','predict']);p.add_argument('--round',type=Path,required=True)
    a=p.parse_args();freeze(a.round.resolve()) if a.phase=='freeze' else predict(a.round.resolve())

if __name__=='__main__':main()
