"""Narrow note contract with source-scoped validation and one bounded repair."""
import json
import re
from pathlib import Path
from typing import Protocol
from datetime import datetime, timezone
from pydantic import ValidationError
from .contracts import Citation, EvidenceFact, NoteProposal
from .prepare import digest
from .config import DEFAULT_NOTE_PROMPT
from .facts import source_key
from .grounding import terminology, supports_monitoring_test, explicit_dates, provider_grounded, authentication

VERSION='claims-review-note/3'
PROMPT='''Extract source-supported HbA1c review facts only. No tools, files, clinical diagnosis,
policy evaluation, date arithmetic, or payment decision. The request is context, not evidence.
Extract every supported relevant fact. Use null only when evidence cannot establish a value;
do not guess or abstain when evidence is sufficient. Required keys may have null values.
Use purpose value monitoring/screening/initial_diagnosis, or null. Diabetes background is
true for established disease; missing documentation is null, not an absence diagnosis.
Regimen_change true means an implemented change, false an explicit nonimplementation;
a prescription or proposed change is planned, never proof of implementation.
Clinical_rationale value is implemented_change, altered_control_event, uncontrolled_diabetes,
or null. False is allowed only for affirmative evidence contradicting a specifically asserted
rationale, never for missing rationale. It must be explicitly connected to this test's reason;
do not infer control from numbers.
Order_intent true means explicit intent for this specific test; missing order paperwork is null,
not cancellation. false requires affirmative cancellation/refusal/withdrawal of intent.
An explicitly stated order issue date has date_role=order_issued; a requested collection
date has date_role=requested_test. A current disease statement is actual even when the
note was written before review_as_of. historical means explicitly historical content.
Clinical_rationale describes the documented reason for a test, including a planned test;
its statement time may be unknown/planned while a separate regimen_change proves actual
implementation. Extract an explicit target date when given; do not borrow a signature date.
Test dates mentioned in prose are test_mention, not automatically new independent test events.
Keep actual, historical and planned roles. fact_date is the assertion's explicitly documented
date in date_role; target_date is an explicitly stated date of the test being requested or discussed.
Never fill either date from signature/record/receipt/request context. Context can identify the
patient and encounter, but cannot prove purpose, clinical facts, or actual test performance.
Copy supplied patient_id/source_id exactly. Choose source span_ids, including all needed
context (multiple spans allowed). Authenticated=true requires applicable signature evidence
and provider attribution for this assertion; an unrelated signature is insufficient. Preserve
author, original reporter, patient and ordering provider distinctions. A signer alone does not
establish every statement's reporter. provider is the verbatim attributed provider name or null.
Readable statement retains negation/scope. Unknown clinical values remain null, not zero or
false. Preserve competing assertions as separate facts. Do not produce unsupported facts.
Recognize HbA1c, Hgb A1c, hemoglobin A1c and glycated/glycosylated hemoglobin
terminology in context. Glycated albumin/protein or fructosamine alone is not HbA1c.
Preserve the phrase in the evidence; do not generate assay/billing codes.
Return complete unambiguous dates in ISO form even when the source uses named
months or year/month/day. Ambiguous numeric or partial dates remain null.
Missing established-diagnosis documentation is null, not diabetes_context=false.
Digital/electronic signature declarations must be scoped to the assertion and
attributed provider; they do not establish authority to correct another record.
'''


class NoteProvider(Protocol):
    def structured_output(self,prompt:str,schema:dict,*,purpose:str)->dict: ...


class RuntimeValidationError(ValueError):pass


def preserves(original,final):
    """Allow citation augmentation, paraphrase and filling unknowns, not erasure.

    Positional grounding remains a necessary, not sufficient, semantic check.
    """
    for candidate in final:
        if not set(original['span_ids']) <= set(candidate['span_ids']):continue
        known={k:v for k,v in original.items() if k not in {'statement','span_ids'} and v is not None
               and not (k in {'date_role','temporal_status'} and v=='unknown')}
        if all(candidate[k]==v for k,v in known.items()):return True
    return False


def note_request(source,claim,*,prompt_variant=DEFAULT_NOTE_PROMPT):
    if prompt_variant not in {'A','B'}:raise ValueError('Unknown note prompt variant')
    from .note_prompt_b import PROMPT_B
    schema=NoteProposal.model_json_schema()
    schema['properties']['patient_id']={'type':'string','enum':[source['patient_id']]}
    schema['properties']['source_id']={'type':'string','enum':[source['source_id']]}
    schema['$defs']['NoteAssertion']['properties']['span_ids']['items']={'type':'string','enum':[a['span_id'] for a in source['line_anchors']]}
    context={k:source[k] for k in ['patient_id','source_id','encounter_id','recorded_at','available_at']}
    prompt=(PROMPT if prompt_variant=='A' else PROMPT_B)+'\nREQUEST CONTEXT (not clinical evidence):\n'+json.dumps(claim)+'\nSOURCE IDENTITY:\n'+json.dumps(context)+'\nSOURCE SPANS:\n'+json.dumps(source['line_anchors'],ensure_ascii=False)
    return prompt,schema


def validate_proposal(raw,source,as_of):
    errors=[];proposal=None;anchors={a['span_id']:a for a in source['line_anchors']}
    try:proposal=NoteProposal.model_validate_json(json.dumps(raw,allow_nan=False))
    except (ValidationError,ValueError,TypeError) as error:errors.append(str(error))
    if isinstance(raw,dict):
        for field in ['patient_id','source_id']:
            if raw.get(field)!=source[field]:errors.append(f'{field} must match the supplied source identity')
        rows=raw.get('facts',[])
        for index,row in enumerate(rows if isinstance(rows,list) else []):
            if not isinstance(row,dict):continue
            ids=row.get('span_ids',[])
            if isinstance(ids,list):
                for identifier in ids:
                    if not isinstance(identifier,str) or identifier not in anchors:errors.append(f'fact {index}: unknown span ID {identifier!r}')
    if proposal:
        for i,fact in enumerate(proposal.facts):
            selected=[anchors[s] for s in fact.span_ids if s in anchors]
            text='\n'.join(a['quote'] for a in selected)
            for anchor in selected:
                if source['content'][anchor['start']:anchor['end']]!=anchor['quote']:errors.append(f'fact {i}: anchor slice mismatch')
            for field in ['fact_date','target_date']:
                value=getattr(fact,field)
                if value is not None and value.isoformat() not in {d['date'] for d in explicit_dates(text)}:errors.append(f'fact {i}: {field} lacks an explicit date in its cited context')
            if fact.fact_date and fact.fact_date>as_of and fact.temporal_status in {'actual','historical'}:errors.append(f'fact {i}: future date cannot be actual/historical support as_of')
            if fact.provider and not provider_grounded(fact.provider,text):errors.append(f'fact {i}: provider attribution lacks verbatim linked evidence')
            if fact.authenticated is True and (not fact.provider or authentication(fact.provider,text) is None):
                errors.append(f'fact {i}: authentication needs applicable signature context and provider')
            if fact.authenticated is True and fact.provider and authentication(fact.provider,text) is False:
                errors.append(f'fact {i}: competing/negative authentication needs separate, applicable evidence')
            # Unknown vocabulary is a mapping uncertainty, not a repair command
            # to erase a potentially grounded fact. It cannot bind downstream.
            if fact.test_specific is True and not supports_monitoring_test(text) and supports_monitoring_test(source['content']):
                errors.append(f'fact {i}: test specificity needs the supporting named-test span already present in the source; preserve the fact and add its context')
            if fact.kind=='purpose' and fact.value not in {'monitoring','screening','initial_diagnosis',None}:errors.append(f'fact {i}: invalid purpose value')
            if fact.kind=='clinical_rationale' and fact.value is not False and fact.value not in {'implemented_change','altered_control_event','uncontrolled_diabetes',None}:errors.append(f'fact {i}: invalid rationale value')
            if fact.kind in {'diabetes_context','regimen_change','order_intent'} and fact.value is not None and not isinstance(fact.value,bool):errors.append(f'fact {i}: this assertion requires boolean or null')
            if fact.kind=='order_intent' and fact.value is False and not re.search(r'cancel|withdraw|refus|do not order|not ordered',text,re.I):
                errors.append(f'fact {i}: absent order paperwork is not affirmative contrary order intent')
    if errors:raise RuntimeValidationError('\n'.join(dict.fromkeys(errors)))
    return proposal


def adapt(proposal,source):
    anchors={a['span_id']:a for a in source['line_anchors']};facts=[]
    for a in proposal.facts:
        citations=[Citation(patient_id=source['patient_id'],source_id=source['source_id'],source_sha256=source_key(source),
            method='unicode_line_anchor',locator=identifier,quote=anchors[identifier]['quote'],
            start=anchors[identifier]['start'],end=anchors[identifier]['end']) for identifier in dict.fromkeys(a.span_ids)]
        body=a.model_dump(exclude={'span_ids'});body['citations']=citations
        text='\n'.join(anchors[s]['quote'] for s in a.span_ids)
        f=EvidenceFact(fact_id='pending',patient_id=source['patient_id'],source_id=source['source_id'],
            event_link_id=source['event_link_id'],details={'extraction':'note','semantic_validation':'Source binding/grounding checks; not a general semantic proof.',
                'terminology':terminology(text),'test_mapping_supported':supports_monitoring_test(text),
                'explicit_dates':explicit_dates(text)},**body)
        facts.append(f.model_copy(update={'fact_id':digest(f.model_dump(mode='json',exclude={'fact_id'}))[:24]}))
    return facts


def extract_note(provider:NoteProvider,source,claim,as_of,*,prompt_variant=DEFAULT_NOTE_PROMPT):
    prompt,schema=note_request(source,claim,prompt_variant=prompt_variant);raw=None;calls=0;failures=[];protected=[]
    for attempt in range(2):
        request=prompt if attempt==0 else prompt+'\nRUNTIME VALIDATION ERRORS:\n'+'\n'.join(failures)+'\nPREVIOUS PROPOSAL:\n'+json.dumps(raw,ensure_ascii=False)+'\nRepair only source-supported assertions; do not invent values. Preserve independently valid assertions and their known fields. Do not replace them with null to satisfy validation.'
        calls+=1
        try:raw=provider.structured_output(request,schema,purpose='claims_review_note_extraction')
        except Exception as error:
            retained=adapt(validate_proposal({'patient_id':source['patient_id'],'source_id':source['source_id'],'facts':protected},source,as_of),source) if protected else []
            return retained,dict(source_id=source['source_id'],status='failed',stage='provider_or_parse',error=str(error),calls=calls,repairs=attempt,retained_facts=len(retained))
        try:
            proposal=validate_proposal(raw,source,as_of)
            if attempt and protected:
                # A repair may fix invalid rows, but cannot erase a separately
                # grounded row silently. Record a failure rather than choosing
                # whichever sample agrees with an evaluator.
                final=[f.model_dump(mode='json') for f in proposal.facts]
                if any(not preserves(f,final) for f in protected):
                    raise RuntimeValidationError('Repair removed or changed an independently valid assertion.')
            return adapt(proposal,source),dict(source_id=source['source_id'],status='completed',calls=calls,repairs=attempt,
                prompt_sha256=digest(prompt),schema_sha256=digest(schema),proposal_sha256=digest(raw))
        except RuntimeValidationError as error:
            failures.append(str(error))
            if attempt==0 and isinstance(raw,dict) and raw.get('patient_id')==source['patient_id'] and raw.get('source_id')==source['source_id']:
                for row in raw.get('facts',[]) if isinstance(raw.get('facts'),list) else []:
                    try:protected.extend(f.model_dump(mode='json') for f in validate_proposal({**raw,'facts':[row]},source,as_of).facts)
                    except RuntimeValidationError:pass
    retained=[]
    # After the bounded repair, salvage independently validated assertions from
    # that final proposal only. Failure remains explicit; no sample selection.
    if isinstance(raw,dict) and raw.get('patient_id')==source['patient_id'] and raw.get('source_id')==source['source_id']:
        for row in raw.get('facts',[]) if isinstance(raw.get('facts'),list) else []:
            try:
                one=validate_proposal({**raw,'facts':[row]},source,as_of)
                retained+=adapt(one,source)
            except RuntimeValidationError:pass
    for row in protected:
        original=adapt(validate_proposal({'patient_id':source['patient_id'],'source_id':source['source_id'],'facts':[row]},source,as_of),source)
        for fact in original:
            if fact.fact_id not in {f.fact_id for f in retained}:retained.append(fact)
    return retained,dict(source_id=source['source_id'],status='failed',stage='validation',errors=failures,calls=calls,repairs=1,retained_facts=len(retained))


class BudgetLedger:
    """Small persistent, serial-call ledger for this feature round (hard ceiling 20)."""
    def __init__(self,path):self.path=Path(path)

    def consume(self,identity):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        lock=self.path.with_suffix('.lock')
        try:
            with lock.open('x',encoding='utf-8') as handle:handle.write('serial reservation')
        except FileExistsError as error:raise RuntimeError('Budget ledger is locked; do not run concurrent live commands.') from error
        try:
            data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'limit':20,'calls':[]}
            if data['limit']!=20 or len(data['calls'])>=20:raise RuntimeError('This feature round has reached its 20-call ceiling.')
            number=len(data['calls'])+1
            data['calls'].append(dict(call=number,allocated_at=datetime.now(timezone.utc).isoformat(),identity=identity,status='reserved_before_provider_call'))
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');temp.replace(self.path)
            return number
        finally:lock.unlink()

    def finish(self,number,status,folder):
        data=json.loads(self.path.read_text(encoding='utf-8'))
        data['calls'][number-1].update(status=status,output=str(folder),finished_at=datetime.now(timezone.utc).isoformat())
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');temp.replace(self.path)


class BudgetedProvider:
    def __init__(self,provider,ledger,output):self.provider=provider;self.ledger=ledger;self.output=Path(output)

    def structured_output(self,prompt,schema,*,purpose):
        number=self.ledger.consume({'purpose':purpose,'prompt_sha256':digest(prompt),'schema_sha256':digest(schema)})
        folder=self.output/f'call-{number:03d}';folder.mkdir(parents=True,exist_ok=False)
        (folder/'prompt.txt').write_text(prompt,encoding='utf-8');(folder/'schema.json').write_text(json.dumps(schema,indent=2),encoding='utf-8')
        self.provider.audit_path=folder
        status='failed'
        try:
            raw=self.provider.structured_output(prompt,schema,purpose=purpose)
            (folder/'answer.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
            status='completed';return raw
        except Exception as error:
            (folder/'failure.json').write_text(json.dumps({'error':str(error)}),encoding='utf-8');raise
        finally:
            usage=self.provider.usage(0).model_dump(mode='json')
            (folder/'usage.json').write_text(json.dumps({'status':status,'provider_usage_cumulative':usage},indent=2),encoding='utf-8')
            self.ledger.finish(number,status,folder)
