"""Reuse the existing mention scanner as a candidate detector, never an extractor.

Optional medSpaCy remains the existing pinned dependency. Its guesses cannot
create a fact or clear Review. Matching all available representations avoids
one-to-one mention-slot artifacts; original source and scanner signals remain.
"""
import re
from functools import lru_cache
from threading import RLock

from .models import digest

VERSION = 'existing-source-mention-scanner/1'
_lock = RLock()


def _text(value):
    return re.sub(r'\s+',' ',str(value or '')).casefold().strip(' .,:;')


def _contains(phrase, term):
    return bool(term and re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)',phrase,re.I))


def classify_candidates(scan, facts, fact_ids):
    rows = []
    for candidate in scan['candidates']:
        if candidate.get('covered_fact_index') is not None:
            continue
        mention = candidate['mention']
        term = _text(mention['quote'])
        overlap = [(i,f) for i,f in enumerate(facts)
            if f['evidence']['start'] < mention['end'] and mention['start'] < f['evidence']['end']]
        # A candidate can be inside a longer documented medication or condition
        # name. The model's category is retained as a hypothesis; this is an
        # existing representation discrepancy, not permission to assert absence.
        embedded = [(i,f) for i,f in overlap if f['category'] in {'medication','condition','diagnosis','treatment'}
            and _text(f.get('concept')) != term and _contains(_text(f.get('concept')),term)]
        represented = [(i,f) for i,f in overlap if f['category'] == 'symptom' and
            (_contains(_text(f.get('concept')),term) or
             _text(f.get('concept')) == _text(candidate['fact'].get('concept')))]
        if embedded:
            kind = 'DOCUMENTED_ENTITY_MODIFIER_REVIEW'
            related = [fact_ids[i] for i,_ in embedded]
        elif represented:
            kind = 'ALREADY_REPRESENTED_AT_SOURCE'
            related = [fact_ids[i] for i,_ in represented]
        else:
            kind = 'ATOMIC_MENTION_CANDIDATE'
            related = [fact_ids[i] for i,_ in overlap]
        same_entity_elsewhere = [fact_ids[i] for i,f in enumerate(facts)
            if i not in {j for j,_ in overlap} and f['category'] == 'symptom' and
            _text(f.get('concept')) == _text(candidate['fact'].get('concept'))]
        rows.append({'candidate_id':'mention-'+digest([scan['note_sha256'],mention])[:20],
            'legacy_candidate_id':candidate['candidate_id'],
            'classification':kind,'mention':mention,'context':candidate['context'],
            'detector_proposal':candidate['fact'],'detector_uncertainty':candidate.get('reasons',[]),
            'related_fact_ids':related,'same_entity_elsewhere_fact_ids':same_entity_elsewhere,
            'source_support_status':'UNVERIFIED','risk_route':'REVIEW_REQUIRED',
            'allow_fact_completion':False})
    return rows


@lru_cache(maxsize=1)
def _scanner():
    from ..luna_v2_independent.approach_a import CoverageScanner
    # The inherited sentence component otherwise writes the entire source to
    # DEBUG stderr. Candidate/provenance output is retained by this adapter.
    from loguru import logger
    logger.disable('PyRuSH')
    return CoverageScanner()


def detect_source_mentions(packet):
    """Scan full original source and cited units; no labels or model calls."""
    facts = [f.assertion.model_dump() for f in packet.facts]
    try:
        with _lock:
            scan = _scanner().scan(packet.source.document(),{'facts':facts})
    except ImportError as exc:
        return {'version':VERSION,'source_sha256':packet.source.sha256,
            'status':'UNAVAILABLE_OPTIONAL_DEPENDENCY','reason':str(exc),'candidates':[],
            'semantic_completeness':'UNVERIFIED','model_calls':0}
    return {'version':VERSION,'source_sha256':packet.source.sha256,
        'status':'PARTIAL_CANDIDATE_DETECTION','candidates':classify_candidates(scan,facts,[f.fact_id for f in packet.facts]),
        'detected_mentions':len(scan['candidates']),'uncovered_before_representation_triage':scan['uncovered_mentions'],
        'semantic_completeness':'UNVERIFIED','model_calls':0,
        'limitation':'Mention-level NLP candidates require independent whole-source verification; repeated mentions are not necessarily new clinical entities.'}
