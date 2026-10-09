"""Four scoped evidence checks from the supplied draft policy registry."""
import calendar
import hashlib
import json
from datetime import date
from importlib.resources import files
from pathlib import Path
from . import __version__
from .contracts import Citation, CriterionResult, PolicyReference, ReviewPacket
from .facts import structured_facts, test_timeline
from .note_extractor import extract_note
from .prepare import prepare_case, digest

RULE_VERSION='claims-review-rules/2'
BASELINE='54553dd36095d4d2047f30d66747031a75ecafa5'


def load_policy():
    return json.loads(files(__package__).joinpath('resources/policy_registry.json').read_text(encoding='utf-8'))


def add_months(day,months):
    year,month=divmod(day.year*12+day.month-1+months,12);month+=1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))


def citations(facts):
    unique={}
    for fact in facts:
        for c in fact.citations:unique[digest(c.model_dump(mode='json'))]=c
    return list(unique.values())


def bound_to_target(f,case,sources):
    if f.test_specific is not True:return False
    if f.target_date is not None:return f.target_date==case.claim.service_date
    s=sources[f.source_id]
    return case.claim.encounter_id is not None and s.encounter_id==case.claim.encounter_id


def evaluate(case,prepared,facts,notes,policy,mode,usage=None,requested_policy=None):
    sources={s.source_id:s for s in case.sources}
    timeline=test_timeline(case,prepared,facts)
    purpose=[f for f in facts if f.kind=='purpose' and bound_to_target(f,case,sources)]
    values={f.value for f in purpose if f.value is not None}
    diabetes=[f for f in facts if f.kind=='diabetes_context' and f.temporal_status=='actual'
        and (f.fact_date is None or case.claim.service_date is None or f.fact_date<=case.claim.service_date)]
    order=[f for f in facts if f.kind=='order_intent' and bound_to_target(f,case,sources)]
    rationale=[f for f in facts if f.kind=='clinical_rationale' and bound_to_target(f,case,sources)]
    unsupported=prepared['preparation_status']=='UNSUPPORTED_SCOPE' or bool(values and values <= {'screening','initial_diagnosis'})
    if requested_policy is not None and requested_policy!=policy['registry_version']:unsupported=True
    findings={};gaps=[]
    def result(name,status,reason,refs=(),*,issues=(),conflicts=(),derivation=None):
        rule=next(r for r in policy['criteria'] if r['criterion_id']==name)
        policy_refs=[]
        for ref in rule['source_refs']:
            s=next(s for s in policy['sources'] if s['source_id']==ref['source_id'])
            policy_refs.append(PolicyReference(source_id=s['source_id'],source_version=s.get('source_version') or s.get('publication_month') or s['publication_date'],official_url=s['official_url'],locator=ref['locator']))
        clinical_refs=citations(refs)
        findings[name]=CriterionResult(criterion_id=name,criterion_role=rule['criterion_role'],status=status,reason=reason,
            clinical_refs=clinical_refs,policy_refs=policy_refs,gaps=list(issues),conflicts=list(conflicts),derivation=derivation or {},
            evidence_complete=status in {'SUPPORTED','NOT_APPLICABLE'} and bool(clinical_refs) and bool(policy_refs))
    if len(values)>1 or {f.value for f in diabetes if f.value is not None}=={True,False}:
        result('MONITORING_CONTEXT','CONFLICTED','Relevant purpose/background assertions disagree.',purpose+diabetes,conflicts=[{'purposes':sorted(values)}])
    elif 'monitoring' in values and any(f.value is True for f in diabetes):
        result('MONITORING_CONTEXT','SUPPORTED','Target-linked monitoring purpose and current diabetes background are documented.',purpose+diabetes)
    else:
        result('MONITORING_CONTEXT','INSUFFICIENT_EVIDENCE','The request/result alone cannot establish monitoring purpose or current relevant background.',purpose+diabetes,issues=['Target purpose or relevant current background is missing/ambiguous.'])

    actual=[f for f in facts if f.kind=='test_event']
    candidates=[]
    if case.claim.service_date is not None:
        for event in timeline:
            if case.claim.service_date.isoformat() in event['dates'] and (case.claim.encounter_id is None or
                any(sources[s].encounter_id==case.claim.encounter_id for s in event['source_ids'])):candidates.append(event)
    target=candidates[0] if len(candidates)==1 and not candidates[0]['conflicted'] and not candidates[0]['date_unknown'] else None
    target_date=case.claim.service_date if target else None
    conflicts=[e for e in timeline if e['conflicted']]
    ambiguous=any(not e['identity_explicit'] or e['date_unknown'] for e in timeline) or len(candidates)>1
    coverage=case.review_context.history_completeness=='complete_within_constructed_case' and target_date is not None and case.review_context.history_end>=target_date
    unresolved=prepared['unresolved_source_metadata']
    timeline_refs=citations(actual)
    for event in timeline:
        for c in event['citations']:
            candidate=Citation.model_validate_json(json.dumps(c))
            if candidate not in timeline_refs:timeline_refs.append(candidate)
    if conflicts:
        result('TEST_TIMELINE','CONFLICTED','Explicitly linked actual-event dates disagree; arrival timestamps do not choose a winner.',actual,conflicts=conflicts)
    elif target is None or ambiguous or not coverage or unresolved:
        result('TEST_TIMELINE','INSUFFICIENT_EVIDENCE','The actual target, event identity, dates or declared comparison coverage are incomplete.',actual,
            issues=['Actual target event or complete, unambiguous history scope is not established.'])
    else:
        result('TEST_TIMELINE','SUPPORTED','Actual target/prior events and the declared complete synthetic window are traceable; this is not frequency compliance.',actual,
            derivation={'counted_events':len(timeline),'history_scope':case.review_context.model_dump(mode='json')})
    # Include available excluded-window members as actual conflict evidence.
    findings['TEST_TIMELINE'].clinical_refs=timeline_refs

    trigger=False;interval_conflict=False;comparisons=[]
    if target_date:
        for event in timeline:
            if event is target:continue
            options=[]
            for d in event['dates']:
                prior=date.fromisoformat(d)
                if prior>=target_date:continue
                boundary=add_months(prior,3);short=target_date<boundary
                options.append(short);comparisons.append({'event_key':event['event_key'],'prior':d,'target':target_date.isoformat(),'three_month_boundary':boundary.isoformat(),'short':short})
            if options and all(options):trigger=True
            if len(set(options))>1:interval_conflict=True
    sufficient_no_trigger=coverage and not ambiguous and not conflicts and not unresolved and target_date is not None and case.review_context.history_start<=add_months(target_date,-3)
    relevant_changes=[f for f in facts if f.kind=='regimen_change' and f.value is True and f.temporal_status=='actual'
        and f.fact_date is not None and target_date is not None and f.fact_date<=target_date
        and any(f.fact_date>=date.fromisoformat(c['prior']) for c in comparisons if c['short'])]
    # The reason for ordering a planned test is distinct from whether the change
    # it refers to actually occurred. Unknown assertion time is not counterevidence.
    supported_rationale=[f for f in rationale if
        (f.value in {'altered_control_event','uncontrolled_diabetes'} and f.temporal_status in {'actual','historical'})
        or (f.value=='implemented_change' and bool(relevant_changes))]
    contrary_rationale=[f for f in rationale if f.value is False and f.temporal_status in {'actual','historical'}]
    disputed_changes=[f for f in facts if f.kind=='regimen_change' and f.value is False
        and f.temporal_status in {'actual','historical'} and f.fact_date is not None
        and any(f.fact_date==positive.fact_date for positive in relevant_changes)]
    if not trigger and interval_conflict:
        result('SHORT_INTERVAL_RATIONALE','CONFLICTED','Competing actual dates put the same event on different sides of the declared three-month boundary.',actual,conflicts=conflicts,derivation={'comparisons':comparisons})
    elif trigger and supported_rationale and (contrary_rationale or disputed_changes):
        result('SHORT_INTERVAL_RATIONALE','CONFLICTED','Relevant positive and affirmative contrary rationale evidence coexist.',
            actual+supported_rationale+relevant_changes+contrary_rationale+disputed_changes,
            conflicts=[{'fact_ids':[f.fact_id for f in supported_rationale+contrary_rationale+disputed_changes]}],derivation={'comparisons':comparisons,'trigger':True})
    elif trigger and contrary_rationale:
        result('SHORT_INTERVAL_RATIONALE','NOT_SUPPORTED','Affirmative evidence contradicts a specifically asserted rationale; missing documentation alone is insufficient.',
            actual+contrary_rationale,derivation={'comparisons':comparisons,'trigger':True})
    elif trigger and supported_rationale:
        result('SHORT_INTERVAL_RATIONALE','SUPPORTED','An observed short interval and linked implemented clinical rationale are supported; no exception or payment adjudication is made.',actual+supported_rationale+relevant_changes,derivation={'comparisons':comparisons,'trigger':True})
    elif trigger:
        result('SHORT_INTERVAL_RATIONALE','INSUFFICIENT_EVIDENCE','A short interval is observed, but linked implemented rationale is insufficient.',actual+rationale,issues=['A prescription or future plan alone does not confirm an implemented change.'],derivation={'comparisons':comparisons,'trigger':True})
    elif sufficient_no_trigger:
        result('SHORT_INTERVAL_RATIONALE','NOT_APPLICABLE','Known actual events and the declared complete comparison window establish no short interval under the project convention.',actual,derivation={'comparisons':comparisons,'trigger':False,'history_scope':case.review_context.model_dump(mode='json')})
    else:
        result('SHORT_INTERVAL_RATIONALE','INSUFFICIENT_EVIDENCE','Unavailable dates/history do not establish a false trigger.',actual+rationale,issues=['Interval applicability remains unknown.'],derivation={'comparisons':comparisons,'trigger':None})
    # Interval evidence also retains grouped, excluded-window members.
    existing={digest(c.model_dump(mode='json')) for c in findings['SHORT_INTERVAL_RATIONALE'].clinical_refs}
    findings['SHORT_INTERVAL_RATIONALE'].clinical_refs += [c for c in timeline_refs if digest(c.model_dump(mode='json')) not in existing]

    positive=[f for f in order if f.value is True and f.provider is not None and f.authenticated is True]
    if any(f.value is False for f in order) and any(f.value is True for f in order):
        result('ORDER_INTENT','CONFLICTED','Unresolved target-specific order and cancellation statements coexist.',order,conflicts=[{'fact_ids':[f.fact_id for f in order]}])
    elif positive:
        result('ORDER_INTENT','SUPPORTED','A specific-test signed order or authenticated treating-provider record supports intent. A separate signed order is not mandatory.',order)
    else:
        result('ORDER_INTENT','INSUFFICIENT_EVIDENCE','Target-specific provider intent and applicable authentication are not established.',order,issues=['A result, generic request or unsupported unsigned order is insufficient.'])

    if unsupported:
        for r in findings.values():
            r.status='NOT_EVALUATED';r.evidence_complete=False
            r.reason='Requested purpose, mapping or policy version is outside this monitoring demonstration; no coverage denial is issued.'
    missing_target=target is None
    if missing_target:gaps.append('Actual target date/performance is not established by the constructed request.')
    if values!={'monitoring'} and not unsupported:gaps.append('Target monitoring purpose is missing, ambiguous or conflicted.')
    gaps+=prepared['reasons']
    failed=any(n['status']=='failed' for n in notes)
    if failed:gaps.append('One or more note extractions failed; validated structured/other facts remain available.')
    if mode=='structured-only' and any(s['source_kind']=='synthetic_note' for s in prepared['source_candidates']):
        gaps.append('Notes were not extracted in structured-only mode; this is not a full live review.')
    status='UNSUPPORTED_SCOPE' if unsupported else 'NEEDS_HUMAN_REVIEW' if (
        missing_target or failed or mode=='structured-only' and notes or
        any(r.status in {'INSUFFICIENT_EVIDENCE','CONFLICTED','NOT_SUPPORTED'} for r in findings.values())) else 'EVIDENCE_READY_FOR_HUMAN_REVIEW'
    runtime={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    runtime['provider.py']=hashlib.sha256((Path(__file__).parent.parent/'provider.py').read_bytes()).hexdigest()
    identity=dict(baseline_commit=BASELINE,rule_version=RULE_VERSION,policy_version=policy['registry_version'],policy_sha256=digest(policy),runtime_sha256=runtime,
        input_sha256=prepared['input_sha256'],review_input_sha256=digest({'input':case.model_dump(mode='json'),'policy':policy,'runtime':runtime,'mode':mode,'requested_policy':requested_policy,'settings':(usage or {}).get('settings')}))
    return ReviewPacket(version=__version__,case_id=case.case_id,status=status,target=case.claim,review_context=case.review_context,
        preparation=prepared,facts=facts,criteria=[findings[r['criterion_id']] for r in policy['criteria']],timeline=timeline,gaps=gaps,
        execution={'preparation':'completed','structured_facts':'completed','note_extraction':'failed' if failed else 'not_run' if mode=='structured-only' else 'completed',
            'note_sources':notes,'policy_evaluation':'not_evaluated_scope' if unsupported else 'completed','execution_failed':failed,
            'actual_provider_calls':(usage or {}).get('model_calls',0),'usage':usage,'cache_enabled':False,'application_cache_hit':False,'backend_model_snapshot':'unavailable','uses_expected':False},
        identity=identity,policy_review_status=policy['review_status'],human_review_completed=policy['human_review_completed'],clinical_expert_review_completed=policy['clinical_expert_review_completed'])


def run_review(case,*,mode='structured-only',provider=None,input_label='case.json',usage=None,requested_policy=None):
    if mode not in {'structured-only','live','fixture'}:raise ValueError('Unsupported review mode')
    if mode!='structured-only' and provider is None:raise ValueError('Note mode requires an explicitly injected provider')
    policy=load_policy();prepared=prepare_case(case,policy,input_label=input_label);facts=structured_facts(prepared);notes=[]
    for source in prepared['source_candidates']:
        if source['source_kind']!='synthetic_note':continue
        if mode=='structured-only':notes.append({'source_id':source['source_id'],'status':'not_run','calls':0,'repairs':0});continue
        extracted,record=extract_note(provider,source,case.claim.model_dump(mode='json'),case.review_context.as_of)
        facts+=extracted;notes.append(record)
    actual_usage=usage() if callable(usage) else usage
    return evaluate(case,prepared,facts,notes,policy,mode,actual_usage,requested_policy)


def markdown(packet):
    p=packet.model_dump(mode='json')
    lines=[f'# HbA1c evidence review: {p["case_id"]}',f'\nStatus: **{p["status"]}**',
        p['decision_boundary'],f'\nPolicy: {p["identity"]["policy_version"]}; {p["policy_review_status"]}; human review completed: false.',
        '\n## Target and scope',json.dumps({'target':p['target'],'review_context':p['review_context']},indent=2),
        '\n## Criteria']
    for r in p['criteria']:
        lines += [f'\n### {r["criterion_id"]}: {r["status"]}',r['reason'],f'Role: {r["criterion_role"]}',f'Evidence complete: {r["evidence_complete"]}']
        for c in r['clinical_refs']:
            lines.append(f'- Clinical: {c["source_id"]} / {c["locator"]} / {c["method"]}: '+json.dumps(c['quote'] if c['quote'] is not None else c['raw_value'],ensure_ascii=False))
        for c in r['policy_refs']:lines.append(f'- Policy: [{c["source_id"]}]({c["official_url"]}), version {c["source_version"]}, {c["locator"]}')
        if r['gaps']:lines.append('Gaps: '+'; '.join(r['gaps']))
        if r['conflicts']:lines.append('Conflicts: '+json.dumps(r['conflicts'],ensure_ascii=False))
        lines.append('Derivation: '+json.dumps(r['derivation'],ensure_ascii=False))
    lines += ['\n## Facts',json.dumps(p['facts'],ensure_ascii=False,indent=2),'\n## Timeline',json.dumps(p['timeline'],ensure_ascii=False,indent=2),
        '\n## Gaps']+['- '+g for g in p['gaps']]+['\n## Execution',json.dumps(p['execution'],indent=2),'\n## Version identity',json.dumps(p['identity'],indent=2)]
    return '\n'.join(lines)+'\n'
