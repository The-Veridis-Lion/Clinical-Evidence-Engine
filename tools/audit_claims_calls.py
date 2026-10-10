"""Preserve visible proposal -> validator -> repair -> packet trace, without calls.

This is a mechanical audit, not a semantic correctness proof or a scoring change.
All expanded audit output belongs in an ignored/private directory.
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def fingerprint(path):
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def changes(before,after):
    # Kind + ordinal is inspectable structural alignment, not event identity.
    def groups(rows):
        grouped=defaultdict(list)
        for row in rows:grouped[row['kind']].append(row)
        return grouped
    old,new=groups(before),groups(after);out=[]
    for kind in sorted(old.keys()|new.keys()):
        for index in range(max(len(old[kind]),len(new[kind]))):
            a=old[kind][index] if index<len(old[kind]) else None
            b=new[kind][index] if index<len(new[kind]) else None
            delta={k:{'before':(a or {}).get(k),'after':(b or {}).get(k)} for k in (a or {}).keys()|(b or {}).keys() if (a or {}).get(k)!=(b or {}).get(k)}
            if delta:out.append({'kind':kind,'ordinal':index,'removed':b is None,'added':a is None,'fields':delta})
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--packets',type=Path,required=True)
    p.add_argument('--traces',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();traces=defaultdict(list)
    for folder in sorted(a.traces.glob('call-*')):
        schema_path=folder/'schema.json'
        if not schema_path.exists():continue
        schema=json.loads(schema_path.read_text(encoding='utf-8'))
        try:key=(schema['properties']['patient_id']['enum'][0],schema['properties']['source_id']['enum'][0])
        except (KeyError,IndexError):continue
        traces[key].append(folder)
    out=[]
    for path in sorted(a.inputs.glob('*.json')):
        case=json.loads(path.read_text(encoding='utf-8'));packet_path=a.packets/path.name
        if not packet_path.exists():out.append({'input':fingerprint(path),'status':'PACKET_MISSING'});continue
        packet=json.loads(packet_path.read_text(encoding='utf-8'));notes=[]
        for source in case['sources']:
            if source['source_kind']!='synthetic_note':continue
            stages=[];previous=None
            for folder in traces[(source['patient_id'],source['source_id'])]:
                answer_path=folder/'answer.json';prompt_path=folder/'prompt.txt'
                answer=json.loads(answer_path.read_text(encoding='utf-8')) if answer_path.exists() else None
                prompt=prompt_path.read_text(encoding='utf-8') if prompt_path.exists() else ''
                reported=prompt.split('RUNTIME VALIDATION ERRORS:\n',1)[1].split('\nPREVIOUS PROPOSAL:',1)[0] if 'RUNTIME VALIDATION ERRORS:\n' in prompt else None
                stages.append({'call':folder.name,'files':{f.name:fingerprint(f) for f in folder.iterdir() if f.is_file()},
                    'original_visible_response':answer,'runtime_errors_reported_to_this_repair':reported,
                    'before_after_changes':changes(previous['facts'],answer['facts']) if previous and answer else [],
                    'alignment_limit':'kind/ordinal structural comparison; inspect full originals for clinical correspondence.'})
                previous=answer
            notes.append({'source':source,'stages':stages,'normalized_facts':[f for f in packet.get('facts',[]) if f['source_id']==source['source_id']],
                          'packet_note_record':next((n for n in packet.get('execution',{}).get('note_sources',[]) if n['source_id']==source['source_id']),None)})
        out.append({'case_id':case['case_id'],'input':fingerprint(path),'packet':fingerprint(packet_path),'notes':notes,
                    'downstream':{k:packet.get(k) for k in ['status','timeline','criteria','gaps','execution','identity']}})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({'version':'claims-call-audit/1','method':'Offline mechanical trace; no new calls, no semantic metric, no expected answers used','cases':out},indent=2)+'\n',encoding='utf-8')
    print(f'Preserved {len(out)} complete case traces; original files not modified.')


if __name__=='__main__':main()
