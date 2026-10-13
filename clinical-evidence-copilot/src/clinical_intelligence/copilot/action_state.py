"""Versioned, conservative action detector; lexical evidence is not adjudication.

The detector reads source scopes, never the model's free-text status as proof.
It preserves multiple scope candidates rather than choosing a convenient event.
Unrecognized aliases, indirect answers and cross-sentence coreference need review.
"""
import re

from .models import digest

LEGACY_VERSION = 'copilot-action-state/v1'
VERSION = 'copilot-action-state/v2'
TOKEN = re.compile(r"[\w]+(?:['’][\w]+)?", re.UNICODE)
BOUNDARY = re.compile(r'(?<=[.!?;])\s+|\n|,\s*|\b(?:but|however|whereas|although)\b', re.I)
STOP = {'the','a','an','of','for','to','and','with','in','on','approximately','removing','documented','action'}
EXECUTED = {'completed','finished','performed','administered','took','taken'}
ONGOING = {'taking','receiving','continuing','ongoing'}
REFUSED = {'declined','refused','unwilling','cancelled','canceled'}
DISCUSSION = {'discussed','considered'}
FUTURE = {'will','scheduled','plan','planned'}
HYPOTHETICAL = {'would','could','might','hypothetical'}
NEGATION = {'not','never','no'}
UNCERTAIN = {'unclear','unknown','undocumented'}
DENIAL = {'deny','denies','denied','denying'}
CLAUSE_BREAKS = {'and','while','because','when','despite','before','after','since'}
OBJECT_END = CLAUSE_BREAKS | {'with','without','during','for','from','at','to'}


def words(text):
    return [m.group().casefold() for m in TOKEN.finditer(text)]


def anchors(concept):
    return {w for w in words(concept or '') if w not in STOP and not w.isdigit()}


def scopes(text, start=0):
    """Exact source fragments. These are lexical scopes, not semantic atoms."""
    begin = 0
    for match in BOUNDARY.finditer(text):
        end = match.start()
        if text[begin:end].strip():
            left = begin + len(text[begin:end]) - len(text[begin:end].lstrip())
            right = end - len(text[begin:end]) + len(text[begin:end].rstrip())
            yield {'start': start+left, 'end': start+right, 'quote': text[left:right]}
        begin = match.end()
    if text[begin:].strip():
        left = begin + len(text[begin:]) - len(text[begin:].lstrip())
        right = len(text.rstrip())
        yield {'start': start+left, 'end': start+right, 'quote': text[left:right]}


def negation_scope(tokens, action_index):
    """Directional token scopes, separating action objects from adjuncts.

    Prefix denial/negation can govern an embedded action. Post-verbal no/neither
    governs its object until an adjunct/conjunction boundary. Negative adjuncts
    after 'with/without' do not negate the preceding administration. Multiple
    cues and pseudo-negation are unresolved rather than cancelled into truth.
    """
    prefix = tokens[:action_index]
    boundary = max((i for i,t in enumerate(prefix) if t in CLAUSE_BREAKS), default=-1)
    prefix = prefix[boundary+1:]
    before = [(i,t) for i,t in enumerate(prefix) if t in NEGATION | DENIAL | {'neither','without'} or t.endswith(("n't",'n’t'))]
    if any(t=='not' and i+1 < len(prefix) and prefix[i+1]=='only' for i,t in before):
        return 'unresolved', {'direction':'prefix','cues':[t for _,t in before], 'reason':'pseudo_negation'}
    suffix = tokens[action_index+1:]
    end = next((i for i,t in enumerate(suffix) if t in OBJECT_END),len(suffix))
    after = [t for t in suffix[:end] if t in {'no','neither','not'}]
    cues = [t for _,t in before]+after
    if len(cues)>1:
        return 'unresolved', {'direction':'mixed_or_multiple','cues':cues,'reason':'multiple_negation_cues'}
    return ('negated' if cues else 'clear',
        {'direction':'prefix' if before else 'post_verbal_object' if after else 'none',
         'cues':cues, 'reason':'bounded_token_scope'})


def classify_scope(quote, *, version=VERSION):
    if version not in {LEGACY_VERSION,VERSION}:
        raise ValueError('Unsupported action detector version')
    tokens = words(quote)
    found = set(tokens)
    # A question or missing documentation is not evidence of execution/absence.
    if '?' in quote or found & UNCERTAIN or (found & {'record','documentation','documented','reported','evidence'} and found & NEGATION):
        return 'unknown', 'documentation_or_question', []
    markers = [(i, token) for i, token in enumerate(tokens) if token in EXECUTED | ONGOING | REFUSED | DISCUSSION | FUTURE | HYPOTHETICAL | {'started','received','underwent','proceeding','prescribed','ordered','requested'}]
    states = set()
    negative_scopes = []
    for index, token in markers:
        # Local negation is deliberately bounded. Cross-clause negation is unknown.
        prefix = tokens[max(0,index-5):index]
        if 'and' in prefix:
            prefix = prefix[len(prefix)-1-prefix[::-1].index('and')+1:]
        negated = bool(set(prefix) & NEGATION or any(t.endswith(("n't", 'n’t')) for t in prefix))
        if version == VERSION:
            disposition, scope = negation_scope(tokens,index)
            negative_scopes.append({'token_index':index,'token':token,'negation_status':disposition,'negation_scope':scope})
            if disposition == 'unresolved':
                states.add('unknown')
                continue
            negated = disposition == 'negated'
            if negated and token in FUTURE | HYPOTHETICAL | DISCUSSION:
                states.add('unknown')
                continue
        if token in REFUSED or (negated and token not in FUTURE | HYPOTHETICAL | DISCUSSION):
            states.add('not_completed')
        elif token in HYPOTHETICAL:
            states.add('discussed')
        elif token in FUTURE:
            states.add('planned')
        elif token in DISCUSSION:
            states.add('discussed')
        elif token in ONGOING or (token == 'received' and set(prefix) & {'still','currently'}):
            states.add('ongoing')
        elif token in EXECUTED:
            states.add('completed')
        else:
            # Started/received/underwent establishes exposure, not a completed course.
            states.add('unknown')
    if 'discussed' in states and 'planned' in states and not found & HYPOTHETICAL:
        states.discard('discussed')
    if found & HYPOTHETICAL:
        states.discard('completed')
    if found & FUTURE and not found & REFUSED:
        # "will perform" is prospective even if a past-tense verb occurs nearby.
        states.discard('completed')
        if states == {'planned','not_completed'}:
            states.discard('not_completed')
    return (next(iter(states)) if len(states) == 1 else 'unknown',
            'single_lexical_state' if len(states) == 1 else 'multiple_or_unrecognized_states',
            negative_scopes if version == VERSION else [{'token_index': i, 'token': t} for i,t in markers])


def inspect_action(item, source, *, version=VERSION):
    if version not in {LEGACY_VERSION,VERSION}:
        raise ValueError('Unsupported action detector version')
    fact = item.assertion
    if fact.category not in {'medication','procedure','treatment'}:
        return {'version': version, 'fact_id': item.fact_id, 'action_state': 'unknown', 'candidates': [], 'warnings': []}
    target = anchors(fact.concept)
    candidates = []
    for span in fact.provenance:
        for scope in scopes(span.quote, span.start):
            scope_words = set(words(scope['quote']))
            # This is only an anchor detector, not alias normalization/entailment.
            if target and len(target & scope_words) >= min(2,len(target)):
                state, reason, markers = classify_scope(scope['quote'],version=version)
                candidate = {**scope, 'candidate_id': 'act-'+digest([source.sha256,item.fact_id,scope])[:20],
                    'state': state, 'reason': reason, 'markers': markers,
                    'semantic_support': 'UNVERIFIED', 'scope_kind': 'quoted_lexical_scope'}
                if version == VERSION:
                    candidate['action_kinds'] = sorted({'course_completion' if m['token'] in {'completed','finished'} else
                        'administration_event' if m['token'] in {'administered','took','taken'} else
                        'procedure_event' if m['token']=='performed' else 'other_or_unresolved' for m in markers})
                candidates.append(candidate)
    states = {c['state'] for c in candidates}
    state = next(iter(states)) if len(states) == 1 else 'unknown'
    warnings = []
    status_words = set(words(fact.clinical_status or ''))
    proposed_complete = bool(status_words & EXECUTED)
    if not candidates:
        warnings.append('unresolved_action_source_anchor')
    if len(states) > 1 or state == 'unknown':
        warnings.append('unresolved_action_scope')
    if proposed_complete and state != 'completed':
        warnings.append('completion_not_supported_by_action_scope')
    if version == VERSION and proposed_complete and status_words & {'course','therapy','treatment'} and not any('course_completion' in c['action_kinds'] for c in candidates):
        warnings.append('course_completion_distinct_from_exposure_or_administration')
    if fact.temporality == 'planned' and state != 'planned':
        warnings.append('plan_disposition_mismatch')
    # Whole-source same-anchor candidates are review context only: never adopt
    # their state automatically (identity/time/coreference remain unverified).
    surrounding = []
    cited = {(c['start'],c['end']) for c in candidates}
    for scope in scopes(source.text):
        if target and len(target & set(words(scope['quote']))) >= min(2,len(target)) and (scope['start'],scope['end']) not in cited:
            other, reason, markers = classify_scope(scope['quote'],version=version)
            if other != 'unknown' and other != state:
                surrounding.append({**scope, 'state': other, 'reason': reason, 'markers': markers,
                    'semantic_support': 'UNVERIFIED', 'scope_kind': 'full_source_review_context'})
    if surrounding:
        warnings.append('other_source_action_state_requires_identity_time_review')
    return {'version': version, 'fact_id': item.fact_id, 'action_state': state,
        'candidates': candidates, 'surrounding_candidates': surrounding,
        'warnings': list(dict.fromkeys(warnings)), 'semantic_support': 'UNVERIFIED'}


def attribute_scope_warnings(item, facts):
    """Detect possible cross-entity duration binding, preserving disputed values."""
    fact = item.assertion
    duration = fact.attributes.duration if fact.attributes else None
    if not duration:
        return []
    for span in fact.provenance:
        text = span.quote.casefold()
        duration_start = text.find(duration.casefold())
        own = text.find((fact.concept or '').casefold()) if fact.concept else -1
        if duration_start < 0 or own < 0:
            continue
        for other in facts:
            if other.fact_id == item.fact_id or other.assertion.category != fact.category:
                continue
            concept = other.assertion.concept
            position = text.find(concept.casefold()) if concept else -1
            if own < position < duration_start and anchors(concept) != anchors(fact.concept):
                return ['attribute_entity_scope_requires_review']
    return []
