"""Chronological saved-proposal replay, explicitly not a new Luna measurement."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.review import run_review


class Replay:
    def __init__(self,rows):self.rows={k:iter(v) for k,v in rows.items()};self.consumed=[]
    def structured_output(self,prompt,schema,*,purpose):
        key=(schema['properties']['patient_id']['enum'][0],schema['properties']['source_id']['enum'][0])
        path,answer=next(self.rows[key]);self.consumed.append(str(path));return answer


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--traces',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();rows=defaultdict(list)
    for path in sorted(a.traces.glob('call-*/answer.json')):
        answer=json.loads(path.read_text(encoding='utf-8'))
        rows[(answer['patient_id'],answer['source_id'])].append((path,answer))
    a.output.mkdir(parents=True,exist_ok=False)
    for path in sorted(a.inputs.glob('*.json')):
        case=CaseInput.model_validate_json(path.read_bytes());provider=Replay(rows)
        packet=run_review(case,mode='fixture',provider=provider,input_label=str(path))
        packet.execution['saved_response_replay']={'consumed_chronologically':provider.consumed,'new_model_calls':0,
           'missing_trace_behavior':'Explicit extraction failure; not recovered historical data.'}
        (a.output/path.name).write_text(packet.model_dump_json(indent=2)+'\n',encoding='utf-8')
        print(case.case_id,packet.status,packet.execution['execution_failed'])


if __name__=='__main__':main()
