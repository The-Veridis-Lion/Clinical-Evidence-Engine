"""Opt-in source-reviewed evaluation; never used to construct product facts.

Main assertions/events, structured attributes and source locations have separate
denominators. One extraction fact cannot satisfy two independent event references.
Unknown reference dimensions and out-of-scope predictions remain explicitly listed.
The historical matcher and all original labels are left unchanged.
"""
from collections import Counter
from datetime import datetime
import re

from .matching import normalize

VERSION = 'copilot-source-reviewed-evaluation/2'
ATTRIBUTE_FIELDS = ('frequency', 'event_time', 'duration', 'value', 'unit', 'assertion_basis')
CATEGORY_ALIASES = {'measurement': 'observation'}
CONCEPT_ALIASES = {'physical therapy course': 'physical therapy',
    'adverse effects documentation': 'documentation of adverse effects',
    'documented adverse effects': 'documentation of adverse effects'}


def canonical(value, field=None):
    value = normalize(value)
    if value is None:
        return None
    if field == 'event_time':
        value = re.sub(r'^in\s+', '', value)
        value = re.sub(r'^(?:when i was|at age)\s+(\d+)$', r'age \1', value)
        try:
            value = datetime.strptime(value, '%B %d, %Y').date().isoformat()
        except ValueError:
            pass
    if field in {'frequency','duration','value'}:
        numbers={'one':'1','two':'2','three':'3','four':'4','five':'5','six':'6',
                 'seven':'7','eight':'8','nine':'9','ten':'10','eleven':'11','twelve':'12'}
        value = re.sub(r'\b(?:'+'|'.join(numbers)+r')\b', lambda m:numbers[m.group()], value)
    if field == 'frequency':
        value = {'once daily':'daily','once per day':'daily','once a day':'daily'}.get(value,value)
        match = re.fullmatch(r'(?:every\s*|q\s*)(\d+)(?:\s*(?:to|-)\s*(\d+))?\s*(?:hours?|hrs?|h)\s*(as needed|prn)?',value)
        if match:
            value='q'+match[1]+('-'+match[2] if match[2] else '')+'h'+(' prn' if match[3] else '')
    if field == 'duration':
        value = re.sub(r'\ba (?=(?:day|week|month|year)\b)', '1 ', value)
        value = re.sub(r'\b(days|weeks|months|years)\b', lambda m:m[1][:-1], value)
    if field == 'value' and re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', value):
        value = value.replace(',', '')
    if field == 'unit':
        value = {'%': 'percent', 'year': 'years', 'yr': 'years', 'yrs': 'years', 'μm': 'um',
                 'milligram':'mg','milligrams':'mg'}.get(value, value)
    return CONCEPT_ALIASES.get(value, value) if field == 'concept' else value


def counts(tp, predictions, references):
    p = tp / predictions if predictions else None
    r = tp / references if references else None
    return {'tp': tp, 'fp': predictions-tp, 'fn': references-tp,
            'prediction_denominator': predictions, 'reference_denominator': references,
            'precision': p, 'recall': r,
            'f1': 2*tp/(predictions+references) if predictions+references else None}


def legacy_action_state(fact):
    """Read only the primary explicit legacy proposal; never infer from source.

    The second clause remains preserved text, not a manufactured second fact.
    Unrecognized clinical_status is explicitly unknown rather than guessed.
    """
    if fact['category'] not in {'medication', 'procedure', 'treatment'}:
        return None
    status = canonical(fact.get('clinical_status')) or ''
    primary = re.split(r';', status, maxsplit=1)[0].strip()
    if re.search(r'\bnot (?:started|taken|administered|completed)\b', primary):
        return 'not_completed'
    if re.match(r'^(?:may|might|would|could|consider|possible)\b', primary):
        return 'unknown'
    if re.match(r'^(?:will|to be|scheduled|planned|recommended)\b', primary):
        return 'planned'
    if re.search(r'\b(?:taken|administered|completed|performed)\b', primary):
        return 'completed'
    if re.search(r'\b(?:taking|ongoing|receiving)\b', primary):
        return 'ongoing'
    return 'unknown'


def record(fact, *, assertion_id, semantics=None, action_state=None, original_index=None):
    fact = dict(fact)
    attrs = dict(fact.get('attributes') or {})
    for key in ('frequency', 'event_time', 'completion_scope', 'action_type'):
        attrs[key] = None
    attrs['assertion_basis'] = fact.get('assertion_basis')
    if semantics is not None:
        for key in ('frequency', 'event_time', 'duration', 'assertion_basis', 'completion_scope', 'action_type'):
            attrs[key] = semantics.get(key)
    status = canonical(fact.get('clinical_status'))
    concept = canonical(fact.get('concept'), 'concept')
    scoped_documentation = concept and ('documentation' in concept or 'recording' in concept)
    doc_status = status in {'not_documented', 'not documented', 'none documented', 'no record',
                            'not recorded', 'no documentation present'}
    channel = 'documentation' if scoped_documentation or doc_status else 'clinical'
    if channel == 'documentation' and concept in {'adverse effects', 'adverse effects documentation'}:
        concept = 'documentation of adverse effects'
    polarity = 'absent' if channel == 'documentation' and doc_status else fact.get('polarity')
    state = (semantics.get('action_state') if semantics is not None else
             action_state if action_state is not None else legacy_action_state(fact))
    category = fact['category']
    # A measured value/unit must exist before the finite category alias applies.
    if (category == 'measurement' and re.search(r'\d', str(attrs.get('value') or ''))
            and attrs.get('unit') is not None):
        category = CATEGORY_ALIASES[category]
    spans = fact.get('provenance') or [fact.get('evidence'), *fact.get('supporting_evidence', [])]
    return {'assertion_id': assertion_id, 'origin_fact_index': original_index,
            'channel': channel, 'category': category, 'concept': concept,
            'fields': {'experiencer': fact.get('experiencer'), 'polarity': polarity,
                       'temporality': fact.get('temporality'), 'action_state': state,
                       'clinical_status': 'not_documented' if channel == 'documentation' and (doc_status or (scoped_documentation and polarity == 'absent')) else status},
            'attributes': attrs, 'spans': [s for s in spans if s is not None],
            'original_proposal': fact, 'semantic_proposal': semantics,
            'legacy_fields_unavailable': ['frequency', 'event_time'] if semantics is None else [],
            'compound_legacy_status_preserved': ';' in (fact.get('clinical_status') or '')}


def packet_records(packet, *, original=False):
    typed = {r['fact_id']: r['semantics'] for r in packet['extraction_metadata'].get('clinical_semantics_v2', [])}
    result = []
    for i, item in enumerate(packet['facts']):
        fact = item['original_fact'] if original else item['assertion']
        result.append(record(fact, assertion_id=item['fact_id'], semantics=typed.get(item['fact_id']),
                             action_state=None if original else item['action_status'], original_index=i))
    return result


def raw_records(payload, source, *, task_version=None):
    """Replay the existing mechanical source adapter, never a provider.

    Invalid raw items remain in the prediction inventory. They cannot acquire a
    valid citation merely because a neighboring accepted item has one.
    """
    import json
    from ..models import Source
    from ..source_adapter import inspect
    typed = any(isinstance(f,dict) and 'semantics' in f for f in payload.get('facts',[]))
    options={'semantics_version':'clinical-fact-semantics/2' if typed else None}
    if task_version is not None:
        options['task_version']=task_version
    outcome = inspect(json.dumps(payload,ensure_ascii=False), Source.model_validate(source).document(), **options)
    extraction = outcome.get('result') or {}
    accepted = outcome.get('accepted_indices',[])
    expanded = dict(zip(accepted,extraction.get('facts',[])))
    # The adapter indexes its compact accepted-fact list, not the original raw
    # array. Rebind through accepted_indices before visiting rejected raw slots.
    sidecars = {accepted[x['fact_index']]:x['semantics'] for x in extraction.get('clinical_semantics',[])}
    records=[]
    for i,raw in enumerate(payload.get('facts',[])):
        if i in expanded:
            records.append(record(expanded[i],assertion_id=f'raw-fact:{i}',semantics=sidecars.get(i),original_index=i))
        else:
            fact=raw if isinstance(raw,dict) else {}
            invalid={'category':fact.get('category','other'),'concept':fact.get('concept'),
                'polarity':fact.get('polarity','uncertain'),'temporality':fact.get('temporality','unknown'),
                'experiencer':fact.get('experiencer','unknown'),'attributes':fact.get('attributes'),
                'clinical_status':fact.get('clinical_status'),'evidence':None,'assertion_basis':fact.get('assertion_basis')}
            value=record(invalid,assertion_id=f'raw-fact:{i}',semantics=fact.get('semantics'),original_index=i)
            value['source_adapter_failure']=True
            records.append(value)
    return records, {'status':outcome.get('status'),'errors':outcome.get('errors',[]),'task_version':task_version,
                     'raw_fact_denominator':len(payload.get('facts',[])),
                     'accepted_fact_count':len(expanded),'rejected_raw_indices':[i for i in range(len(records)) if i not in expanded]}


def reference_spans_valid(reference, source):
    spans = reference['source_spans']
    return bool(spans) and all(0 <= s['start'] < s['end'] <= len(source)
                              and source[s['start']:s['end']] == s['quote'] for s in spans)


def exact_spans(prediction, source):
    return bool(prediction['spans']) and all(0 <= s['start'] < s['end'] <= len(source)
        and source[s['start']:s['end']] == s['quote'] for s in prediction['spans'])


def same_concept(prediction, reference):
    aliases = {canonical(x, 'concept') for x in [reference['concept'], *reference.get('concept_aliases', [])]}
    return prediction['concept'] in aliases


def citation_covers(prediction, reference):
    # Full reference clauses are source-reviewed separately. Overlap proves only
    # location coverage; the semantic fields must also match, and this is silver.
    coverage = [any(p['start'] < r['end'] and r['start'] < p['end'] for p in prediction['spans'])
                for r in reference['source_spans']]
    return all(coverage) if reference.get('support_mode', 'any') == 'all' else any(coverage)


def main_matches(prediction, reference, source):
    if (prediction['channel'] != reference['channel'] or not same_concept(prediction, reference)
            or prediction['category'] not in reference['allowed_categories']
            or not exact_spans(prediction, source) or not citation_covers(prediction, reference)):
        return False
    for name, expected in reference['fields'].items():
        if expected is not None and canonical(prediction['fields'].get(name), name) != canonical(expected, name):
            return False
    return True


def evaluate(predictions, references, source, *, scope='full_source'):
    if len({r['reference_id'] for r in references}) != len(references):
        raise ValueError('Duplicate source reference identity')
    if len({p['assertion_id'] for p in predictions}) != len(predictions):
        raise ValueError('Duplicate prediction identity')
    if any(not reference_spans_valid(r, source) for r in references):
        raise ValueError('Reference is not grounded in the frozen complete source')
    selected, outside = [], []
    for prediction in predictions:
        # Selected references are not full-document gold. All other predictions
        # remain listed and excluded from the selected denominator, never FP.
        in_scope = scope == 'full_source' or any(same_concept(prediction, r) and citation_covers(prediction, r) for r in references)
        (selected if in_scope else outside).append(prediction)
    edges = {ri: [pi for pi, p in enumerate(selected) if main_matches(p, r, source)] for ri, r in enumerate(references)}
    assigned = {}
    def visit(ri, seen):
        for pi in edges[ri]:
            if pi in seen:
                continue
            seen.add(pi)
            if pi not in assigned or visit(assigned[pi], seen):
                assigned[pi] = ri
                return True
        return False
    for ri in range(len(references)):
        visit(ri, set())
    pairs = []
    attribute_tp = attribute_pred = attribute_ref = 0
    attribute_rows = []
    unassessed_fields = []
    for pi, ri in sorted(assigned.items()):
        p, r = selected[pi], references[ri]
        pairs.append({'prediction_id': p['assertion_id'], 'reference_id': r['reference_id']})
        for field, expected in r.get('attributes', {}).items():
            actual = p['attributes'].get(field)
            both = actual is not None and expected is not None
            matched = both and canonical(actual, field) == canonical(expected, field)
            attribute_tp += matched
            attribute_pred += actual is not None
            attribute_ref += expected is not None
            attribute_rows.append({'prediction_id': p['assertion_id'], 'reference_id': r['reference_id'],
                'field': field, 'expected': expected, 'actual': actual,
                'status': 'MATCH' if matched else 'NOT_ASSERTED' if actual is None and expected is None else 'MISMATCH',
                'legacy_schema_unavailable': field in p['legacy_fields_unavailable']})
        unassessed_fields.extend({'prediction_id':p['assertion_id'],'field':field,'actual':actual,
                                 'reason':'REFERENCE_DID_NOT_AUDIT_THIS_ATTRIBUTE'}
                                 for field,actual in p['attributes'].items()
                                 if actual is not None and field not in r.get('attributes',{}))
    audited_attribute_fields = {field for r in references for field in r.get('attributes',{})}
    for pi,prediction in enumerate(selected):
        if pi in assigned:
            continue
        for field,actual in prediction['attributes'].items():
            if actual is None:
                continue
            if field in audited_attribute_fields:
                attribute_pred += 1
                attribute_rows.append({'prediction_id':prediction['assertion_id'],'reference_id':None,
                    'field':field,'expected':None,'actual':actual,'status':'UNMATCHED_MAIN_ASSERTION',
                    'legacy_schema_unavailable':field in prediction['legacy_fields_unavailable']})
            else:
                unassessed_fields.append({'prediction_id':prediction['assertion_id'],'field':field,
                    'actual':actual,'reason':'REFERENCE_DID_NOT_AUDIT_THIS_ATTRIBUTE'})
    # Missing main assertions still contribute every source-reviewed attribute FN.
    for ri, reference in enumerate(references):
        if ri not in assigned.values():
            attribute_ref += sum(v is not None for v in reference.get('attributes', {}).values())
    by_channel = {}
    for channel in ('clinical', 'documentation'):
        tp = sum(references[ri]['channel'] == channel for ri in assigned.values())
        by_channel[channel] = counts(tp, sum(p['channel'] == channel for p in selected), sum(r['channel'] == channel for r in references))
    return {'contract_version': VERSION, 'reference_type': 'SOURCE_FIRST_NONEXPERT_AI_ASSISTED_SILVER',
            'scope': scope, 'full_document_clinical_accuracy': False,
            'main_assertion_and_independent_event': counts(len(pairs), len(selected), len(references)),
            'channels': by_channel, 'attributes': counts(attribute_tp, attribute_pred, attribute_ref),
            'reference_denominator_all_channels': len(references), 'whole_raw_fact_count': len(predictions),
            'pairs': pairs, 'missing_reference_ids': [r['reference_id'] for i, r in enumerate(references) if i not in assigned.values()],
            'unmatched_prediction_ids': [p['assertion_id'] for i, p in enumerate(selected) if i not in assigned],
            'attribute_comparisons': attribute_rows,
            'not_evaluated_prediction_attributes': unassessed_fields,
            'not_evaluated_predictions': [{'assertion_id': p['assertion_id'], 'concept': p['concept'], 'reason': 'OUTSIDE_SELECTED_SOURCE_TARGETS'} for p in outside],
            'not_evaluated_reference_dimensions': [{'reference_id': r['reference_id'], 'dimensions': r.get('unresolved_dimensions', [])} for r in references if r.get('unresolved_dimensions')],
            'citation_exact': {'correct': sum(exact_spans(p, source) for p in predictions), 'denominator': len(predictions),
                               'boundary': 'Exact source alignment only; not clinical entailment.'}}
