"""Independent review entry point; offline paths never construct a real provider."""
import argparse
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
from .contracts import CaseInput, ReviewPacket
from .prepare import prepare_case
from .review import run_review, load_policy, markdown, concise_markdown
from .note_extractor import BudgetLedger, BudgetedProvider
from .retrieval import RetrievalQuery, retrieve, download, VERSION as RETRIEVAL_VERSION
from .prepare import digest
from datetime import date
from .archive_verification import verify_archive, VERSION as VERIFICATION_VERSION


def live_provider(args):
    # Import and instantiate only for explicitly requested live execution.
    from ..provider import CodexCLIProvider, ProviderConfig
    class AuditedProvider(CodexCLIProvider):
        def run_cli(self,command,request,folder):
            started=perf_counter()
            try:
                result=super().run_cli(command,request,folder)
                (self.audit_path/'stderr.txt').write_text(result.stderr,encoding='utf-8')
                (self.audit_path/'transport.json').write_text(json.dumps({'exit_code':result.returncode,'seconds':perf_counter()-started,'command':command},indent=2),encoding='utf-8')
                return result
            finally:
                answer=folder/'answer.json'
                if answer.exists():shutil.copy2(answer,self.audit_path/'visible_answer.txt')
    provider=AuditedProvider(ProviderConfig(model=args.model,reasoning_effort=args.reasoning,timeout_seconds=args.timeout))
    adapter=BudgetedProvider(provider,BudgetLedger(args.ledger),args.trace_directory)
    started=perf_counter()
    return adapter,lambda:provider.usage(perf_counter()-started).model_dump(mode='json')


def write_output(path,text):
    if path is None:
        print(text,end='');return
    output=Path(path);output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_name(output.name+'.tmp')
    try:
        temp.write_text(text,encoding='utf-8');temp.replace(output)
    except OSError:
        # A failed save must not leave an older successful packet at this path.
        output.unlink(missing_ok=True);temp.unlink(missing_ok=True);raise


def main(argv=None):
    parser=argparse.ArgumentParser(description='Scoped HbA1c monitoring evidence review; not a payment decision.')
    commands=parser.add_subparsers(dest='command',required=True)
    prep=commands.add_parser('prepare');prep.add_argument('--case',required=True,type=Path);prep.add_argument('--output',type=Path)
    fetch=commands.add_parser('download');fetch.add_argument('--output',type=Path,required=True)
    discovery=commands.add_parser('retrieve');discovery.add_argument('--archive',type=Path,required=True)
    discovery.add_argument('--query',type=Path,required=True);discovery.add_argument('--metadata',type=Path)
    discovery.add_argument('--snapshot-available-at',type=date.fromisoformat)
    discovery.add_argument('--output',type=Path,required=True)
    run=commands.add_parser('run');inputs=run.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--case',type=Path);inputs.add_argument('--retrieval',type=Path)
    run.add_argument('--verify-archive',type=Path,help='Reopen this original ZIP and verify every supplied clinical CSV source before review.')
    run.add_argument('--mode',choices=['structured-only','live'],default='structured-only')
    run.add_argument('--format',choices=['json','markdown','summary'],default='json');run.add_argument('--output',type=Path)
    run.add_argument('--model',default='gpt-6-luna');run.add_argument('--reasoning',default='high',choices=['none','low','medium','high','xhigh','max'])
    run.add_argument('--timeout',type=int,default=180)
    run.add_argument('--note-prompt',choices=['A','B'],default='A',help='B is an explicit experimental prompt; A remains the default.')
    run.add_argument('--ledger',type=Path,default=Path('artifacts/claims-review/live-budget.json'))
    run.add_argument('--trace-directory',type=Path,default=Path('artifacts/claims-review/live-calls'))
    run.add_argument('--policy-version')
    render=commands.add_parser('render');render.add_argument('--packet',type=Path,required=True)
    render.add_argument('--format',choices=['json','markdown','summary'],default='markdown');render.add_argument('--output',type=Path)
    args=parser.parse_args(argv);stage='input'
    input_path=getattr(args,'case',None) or getattr(args,'packet',None) or getattr(args,'query',None) or getattr(args,'retrieval',None)
    protected=[p for p in [input_path,getattr(args,'archive',None),getattr(args,'metadata',None),getattr(args,'verify_archive',None)] if p is not None]
    if args.output is not None and any(args.output.resolve()==p.resolve() for p in protected):
        print('Output must not overwrite the source input.',file=sys.stderr);return 1
    try:
        if args.command=='download':
            stage='download';value=download(args.output);print(json.dumps(value,indent=2));return 0
        if args.command=='retrieve':
            stage='retrieval_input';query=RetrievalQuery.model_validate_json(args.query.read_text(encoding='utf-8'))
            metadata=json.loads(args.metadata.read_text(encoding='utf-8')) if args.metadata else None
            stage='retrieval';value=retrieve(args.archive,query,snapshot_available_at=args.snapshot_available_at,metadata=metadata)
            stage='save';write_output(args.output,json.dumps(value,indent=2)+'\n');return 0
        if args.command=='render':
            stage='packet_validation';packet=ReviewPacket.model_validate_json(args.packet.read_text(encoding='utf-8'))
        else:
            retrieved=None;verification=None
            if getattr(args,'verify_archive',None) and not getattr(args,'retrieval',None):
                raise ValueError('--verify-archive requires --retrieval')
            if getattr(args,'retrieval',None):
                retrieved=json.loads(args.retrieval.read_text(encoding='utf-8'))
                case=CaseInput.model_validate_json(json.dumps(retrieved['case']))
                if retrieved['version']!=RETRIEVAL_VERSION or retrieved['case_sha256']!=digest(case.model_dump(mode='json')):
                    raise ValueError('Saved retrieval version or case identity mismatch')
                stage='archive_verification'
                verification=verify_archive(retrieved,args.verify_archive) if args.verify_archive else {
                    'version':VERIFICATION_VERSION,'mode':'lightweight_replay',
                    'original_archive_reverified':False,'status':'Original archive not reverified; internal case digest only.'}
            else:case=CaseInput.model_validate_json(args.case.read_text(encoding='utf-8'))
            if args.command=='prepare':
                stage='preparation';value=prepare_case(case,load_policy(),input_label=str(args.case))
                stage='save';write_output(args.output,json.dumps(value,ensure_ascii=False,indent=2)+'\n');return 0
            stage='provider_setup';provider,usage=live_provider(args) if args.mode=='live' else (None,None)
            stage='review';packet=run_review(case,mode=args.mode,provider=provider,usage=usage,input_label=str(input_path),requested_policy=args.policy_version,note_prompt=args.note_prompt)
            if retrieved:
                packet.execution['retrieval']={k:retrieved[k] for k in ['version','archive','case_sha256','matched_source_ids','latency_seconds','scope']}
                packet.execution['archive_verification']=verification
        stage='save';text=concise_markdown(packet) if args.format=='summary' else markdown(packet) if args.format=='markdown' else packet.model_dump_json(indent=2)+'\n'
        write_output(args.output,text)
        return int(packet.execution['execution_failed'])
    except Exception as error:
        if args.command=='download':
            print(f'Download failed; archive destination preserved: {error}',file=sys.stderr);return 1
        failure={'status':'PREPARATION_FAILED' if args.command=='prepare' else 'REVIEW_EXECUTION_FAILED','stage':stage,'error':str(error),'live_status':'Not a successful review'}
        try:
            text=json.dumps(failure,ensure_ascii=False,indent=2)+'\n'
            if getattr(args,'format','json')=='markdown':text='# Review execution failed\n\n'+text
            write_output(args.output,text)
        except OSError as save_error:print(f'Could not save failure: {save_error}',file=sys.stderr)
        print(f'{stage}: {error}',file=sys.stderr);return 1
