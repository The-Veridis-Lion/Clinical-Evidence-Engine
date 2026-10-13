"""Four-state source verification with independently retained dimension proofs."""
from __future__ import annotations
from .models import (BoundVerificationResult, Calibration, Claim, DimensionCheck, ENGINE_VERSION, METHOD_VERSION,
                     Source, SourceReview, Span, VerificationResult)
from .coverage import AUTO_SCOPE, automatic_symptom_scope, canonical_dimension, enumerate_source_assertions, inspect_source_context, norm, overlapping

DIMENSIONS=('category','concept','experiencer','reporting_basis','polarity','certainty',
            'temporality','event_time','action_type','action_state','completion_scope','attributes')
UNKNOWN={None,'','unknown','unspecified','uncertain','not_applicable'}


def _known(value):
    return not isinstance(value,dict) and value not in UNKNOWN


def _canonical(key,value):
    return canonical_dimension(key,value)


def _compare(claim,atom):
    checks=[]
    for key in DIMENSIONS:
        proposed=getattr(claim,key);actual=getattr(atom,key)
        if key=='attributes':
            for attr,value in proposed.items():
                if value is None:
                    continue
                found=actual.get(attr)
                # Exact entity-scoped quantities only; semantic units/aliases remain a reviewer task.
                match=found is not None and norm(found)==norm(value)
                checks.append(DimensionCheck(dimension='attributes.'+attr,
                    status='SUPPORTED' if match else 'UNVERIFIED',proposed=value,source_value=found,
                    reason='Exact value bound to this source entity.' if match else 'Attribute not independently bound to this entity.',spans=atom.spans))
            continue
        if not _known(proposed):
            state='NOT_ASSERTED';reason='Proposal leaves this dimension unknown; source value is a separate candidate.'
        elif not _known(actual):
            state='UNVERIFIED';reason='Bounded source grammar cannot establish this dimension.'
        elif _canonical(key,proposed)==_canonical(key,actual):
            state='SUPPORTED';reason='Independent explicit source assertion agrees in this dimension.'
        elif key in {'reporting_basis','certainty','category','action_type'}:
            state='UNVERIFIED';reason='Reporting/certainty expressions are not assumed interchangeable.'
        else:
            state='CONTRADICTED';reason='Explicit source assertion contradicts this proposed dimension.'
        checks.append(DimensionCheck(dimension=key,status=state,proposed=proposed,source_value=actual,
                                     reason=reason,spans=atom.spans))
    return checks


def _contradictory_atoms(left,right):
    if (left.category!=right.category or norm(left.concept)!=norm(right.concept) or
        left.experiencer!=right.experiencer or left.temporality!=right.temporality or
        left.event_time!=right.event_time):
        return False
    # Unresolved contradictory statements about the same event, not historical transitions.
    return (left.polarity!=right.polarity or
            (left.action_state not in UNKNOWN and right.action_state not in UNKNOWN and
             left.action_state!=right.action_state))


class EvidenceVerifier:
    version=ENGINE_VERSION

    def __init__(self, *, calibrations=()):
        self.calibrations=[Calibration.model_validate(c) for c in calibrations]

    def _route(self,source,claim,status,checks,method,uncertainty,supporting_spans):
        if status=='CONFLICTED':
            return 'CONFLICT_REVIEW',None
        if status=='CONTRADICTED':
            return 'CORRECTION_CANDIDATE',None
        if status=='INSUFFICIENT_EVIDENCE':
            # A mechanically bound original document exists. Unrecognized meaning
            # requires semantic review; it does not prove a document is missing.
            return 'REVIEW_REQUIRED',None
        # Calibration cannot broaden the declared small low-risk grammar boundary.
        full_source=Span(start=0,end=len(source.text),quote=source.text,source_id=source.source_id)
        low_risk=(method==METHOD_VERSION and claim.category=='symptom' and claim.experiencer=='patient' and
                  claim.polarity in {'affirmed','absent','present'} and claim.temporality=='current' and
                  claim.action_state in {'unknown',''} and not any(v not in (None,'') for v in claim.attributes.values()) and
                  not uncertainty and automatic_symptom_scope(supporting_spans) and
                  automatic_symptom_scope(claim.spans) and automatic_symptom_scope([full_source]) and
                  all(c.status in {'SUPPORTED','NOT_ASSERTED'} for c in checks))
        if low_risk:
            for calibration in self.calibrations:
                if (calibration.method==method and calibration.scope==AUTO_SCOPE and claim.category in calibration.categories and
                    calibration.measured_precision>=calibration.minimum_precision):
                    return 'AUTO_ACCEPT_ELIGIBLE',calibration.calibration_id
        return 'REVIEW_REQUIRED',None

    def verify(self,source: Source | dict,claim: Claim | dict,*,reviews=()) -> VerificationResult:
        source=Source.model_validate(source);claim=Claim.model_validate(claim)
        identity=(source.source_id==claim.source_id and source.patient_id==claim.patient_id and
                  source.encounter_id==claim.encounter_id)
        valid_spans=all(source.check_span(s) for s in claim.spans)
        if not identity or not valid_spans:
            checks=[DimensionCheck(dimension='source_identity' if not identity else 'source_spans',
                status='CONTRADICTED',reason='Wrong source/patient/encounter or exact quotation.',proposed=claim.source_id,
                source_value=source.source_id)]
            return VerificationResult(claim_id=claim.claim_id,claim_fingerprint=claim.fingerprint(),source_hash=source.sha256,
                status='INSUFFICIENT_EVIDENCE',dimension_checks=checks,reasons=['Mechanical source binding failed.'],
                method='exact-source-binding/1',uncertainty=['invalid_source_binding'],risk_route='MISSING_EVIDENCE')
        enum=enumerate_source_assertions(source)
        candidates=[a for a in enum.assertions if norm(a.concept)==norm(claim.concept) and overlapping(a,claim)]
        atoms_same_entity=[a for a in enum.assertions if norm(a.concept)==norm(claim.concept) and
                           a.experiencer==claim.experiencer and a.temporality==claim.temporality and
                           (claim.event_time is None or a.event_time==claim.event_time)]
        checks=[];atom=None;uncertainty=[];reasons=[];support=[];counter=[];context_spans=[]
        status='INSUFFICIENT_EVIDENCE'
        if candidates:
            scored=[(a,_compare(claim,a)) for a in candidates]
            # Do not select the best competing event. Multiple compatible atoms require review.
            scoped=[pair for pair in scored if pair[0].experiencer==claim.experiencer and
                    pair[0].temporality==claim.temporality and
                    (claim.event_time is None or pair[0].event_time==claim.event_time)]
            if len(scoped)==1:
                atom,checks=scoped[0]
            elif len(scored)==1:
                atom,checks=scored[0]
            else:
                uncertainty.append('multiple_source_events_or_assertions')
            if atom is not None:
                contradictions=[c for c in checks if c.status=='CONTRADICTED']
                unknowns=[c for c in checks if c.status=='UNVERIFIED']
                if contradictions:
                    status='CONTRADICTED';counter=atom.spans
                    reasons=[c.reason+' '+c.dimension for c in contradictions]
                elif unknowns:
                    uncertainty.extend(c.dimension for c in unknowns)
                    reasons=['Required proposed dimensions are not independently supported.']
                elif atom.experiencer=='unknown':
                    uncertainty.append('source_subject_unresolved')
                else:
                    status='SUPPORTED_BY_SOURCE';support=atom.spans
                    reasons=['Explicit source assertion supports the asserted dimensions within the bounded grammar.']
        else:
            reasons=['No independent bounded assertion establishes this claim; incidental wording is not entailment.']
            uncertainty.append('unrecognized_source_semantics')
        if any(_contradictory_atoms(a,b) for i,a in enumerate(atoms_same_entity) for b in atoms_same_entity[i+1:]):
            status='CONFLICTED';reasons.append('Unresolved original statements disagree for the same subject/time.')
            counter=[s for a in atoms_same_entity for s in a.spans]
        if atom is not None:
            context_uncertainty,context_spans=inspect_source_context(source,claim,atom)
            if context_uncertainty:
                status='INSUFFICIENT_EVIDENCE'
                uncertainty.extend(context_uncertainty)
                reasons.append('Original/adjacent source scope contains unresolved subject, event time, modality or negation qualifiers. Local candidate is not a complete support proof.')
                support=[]
        method=METHOD_VERSION;model_version=None
        checked_reviews=[];invalid_reviews=[]
        for raw in reviews:
            try:
                review=SourceReview.model_validate(raw)
                self._validate_review(source,claim,review,context_spans=context_spans)
                checked_reviews.append(review)
            except (ValueError,TypeError) as exc:
                invalid_reviews.append(str(exc))
        if invalid_reviews:
            uncertainty.extend('invalid_review_binding: '+error for error in invalid_reviews)
        if checked_reviews:
            review_states={r.status for r in checked_reviews}
            if len(review_states)>1 or (status in {'SUPPORTED_BY_SOURCE','CONTRADICTED','CONFLICTED'} and status not in review_states):
                status='CONFLICTED';reasons.append('Independent source judgments materially disagree; no majority vote.')
                counter.extend(s for r in checked_reviews for s in r.counter_spans)
                support.extend(s for r in checked_reviews for s in r.supporting_spans)
                uncertainty.append('source_review_disagreement')
            else:
                first=checked_reviews[0]
                status=first.status;checks=first.dimension_checks
                support=first.supporting_spans;counter=first.counter_spans
                reasons.extend(r.reason for r in checked_reviews)
                # External opinions cannot claim the native implementation's
                # method identity and borrow its unrelated calibration registry.
                method='external-source-review/'+first.method;model_version=first.model_version
                uncertainty.extend(u for r in checked_reviews for u in r.uncertainty)
                if first.status=='SUPPORTED_BY_SOURCE' and context_spans:
                    uncertainty=[u for u in uncertainty if not u.startswith('source_context_')]
                    reasons.append('Independent source review explicitly addressed the retained original context qualifiers.')
        route,calibration_id=self._route(source,claim,status,checks,method,uncertainty,support)
        return VerificationResult(claim_id=claim.claim_id,claim_fingerprint=claim.fingerprint(),
            source_hash=source.sha256,status=status,dimension_checks=checks,supporting_spans=support,
            counter_spans=counter,source_assertion=atom,reasons=reasons or ['Source interpretation remains unresolved.'],
            context_spans=context_spans,
            method=method,model_version=model_version,uncertainty=list(dict.fromkeys(uncertainty)),
            risk_route=route,calibration_id=calibration_id)

    @staticmethod
    def _validate_review(source,claim,review,*,context_spans=()):
        if (review.source_id!=source.source_id or review.source_hash!=source.sha256 or
            review.claim_fingerprint!=claim.fingerprint() or review.patient_id!=source.patient_id or
            review.encounter_id!=source.encounter_id):
            raise ValueError('Source review must bind complete original claim/source identity')
        spans=[*review.supporting_spans,*review.counter_spans,*[s for c in review.dimension_checks for s in c.spans]]
        if not spans or not all(source.check_span(s) for s in spans):
            raise ValueError('Source review requires exact original evidence spans')
        required={'category','concept','experiencer','polarity','temporality'}
        if _known(claim.reporting_basis):
            required.add('reporting_basis')
        if _known(claim.certainty):
            required.add('certainty')
        if context_spans and review.status=='SUPPORTED_BY_SOURCE':
            required.add('source_context')
        if claim.action_state not in UNKNOWN:
            required.add('action_state')
        if claim.action_type:
            required.add('action_type')
        if claim.completion_scope:
            required.add('completion_scope')
        if claim.event_time:
            required.add('event_time')
        required.update('attributes.'+k for k,v in claim.attributes.items() if v is not None)
        by_name={c.dimension:c for c in review.dimension_checks}
        if len(by_name)!=len(review.dimension_checks) or not required<=by_name.keys():
            raise ValueError('Source review omits or duplicates required dimension proofs')
        for name in required:
            item=by_name[name]
            proposed=('full_source_scope_resolved' if name=='source_context' else
                claim.attributes.get(name.partition('.')[2]) if name.startswith('attributes.') else getattr(claim,name))
            if item.proposed!=proposed:
                raise ValueError('Source review proof disagrees with the bound proposal')
            if item.status=='SUPPORTED' and (not item.spans or _canonical(name,item.source_value)!=_canonical(name,proposed)):
                raise ValueError('Supported dimension needs exact source span and matching source value')
            if name=='source_context' and not all(any(s.start<=c.start and c.end<=s.end for s in item.spans) for c in context_spans):
                raise ValueError('Source-context review must cover retained original qualifier units')
        if review.status=='SUPPORTED_BY_SOURCE' and (not review.supporting_spans or review.counter_spans or
                any(by_name[k].status!='SUPPORTED' if _known(by_name[k].proposed) else
                    by_name[k].status not in {'SUPPORTED','NOT_ASSERTED'} for k in required)):
            raise ValueError('Supported review cannot contain missing/contradictory required dimensions')
        if review.status=='CONTRADICTED' and (not review.counter_spans or not any(c.status=='CONTRADICTED' for c in review.dimension_checks)):
            raise ValueError('Contradiction review requires counterevidence and contradicted dimension')

    def verify_sources(self,sources,claim,*,reviews=()):
        """Keep per-source results; unresolved same-event disagreement is explicit.

        Callers must supply identity-preserving claims for each source. This method
        does not infer cross-encounter patient/event equivalence or correction authority.
        """
        claim=Claim.model_validate(claim)
        results=[]
        for raw in sources:
            source=Source.model_validate(raw)
            if source.patient_id!=claim.patient_id or source.encounter_id!=claim.encounter_id:
                continue
            local=claim.model_copy(update={'source_id':source.source_id})
            # Original spans cannot be transplanted between sources without evidence.
            results.append(self.verify(source,local,reviews=reviews))
        return results

    def verify_bound_claims(self,sources,claims,*,reviews=()):
        """Verify each actual source binding, then retain unresolved same-event conflicts.

        This does not transplant one source's offsets to another source. Known
        encounter identity is necessary for cross-source event grouping; unknown
        encounters remain unresolved. Per-source judgments are retained separately
        from effective conflict routing, allowing later explicit amendments.
        """
        sources=[Source.model_validate(s) for s in sources]
        if len({s.source_id for s in sources})!=len(sources):
            raise ValueError('Duplicate source identities in cross-source verification')
        by_source={s.source_id:s for s in sources}
        claims=[Claim.model_validate(c) for c in claims]
        if len({c.claim_id for c in claims})!=len(claims):
            raise ValueError('Duplicate claim identities in cross-source verification')
        results=[]
        for claim in claims:
            if claim.source_id not in by_source:
                raise ValueError('Bound claim names absent original source')
            selected=[r for r in reviews if (r.model_dump() if isinstance(r,SourceReview) else r).get('claim_fingerprint')==claim.fingerprint()]
            results.append(self.verify(by_source[claim.source_id],claim,reviews=selected))
        effective=[r.model_copy(deep=True) for r in results]
        groups=[];unresolved=[]
        for i,left in enumerate(claims):
            for j,right in enumerate(claims[i+1:],start=i+1):
                if (left.source_id==right.source_id or left.patient_id!=right.patient_id or
                    left.category!=right.category or norm(left.concept)!=norm(right.concept) or
                    left.experiencer!=right.experiencer or left.temporality!=right.temporality):
                    continue
                if left.encounter_id is None or right.encounter_id is None:
                    unresolved.append({'claim_ids':[left.claim_id,right.claim_id],
                        'reason':'Unknown encounter identity cannot establish a shared source event.'})
                    continue
                if left.encounter_id!=right.encounter_id or left.event_time!=right.event_time:
                    continue
                a=results[i].source_assertion;b=results[j].source_assertion
                # Outside bounded grammar, source-reviewed clinical dimensions are
                # retained but not assumed to establish cross-source event identity.
                if a is None or b is None:
                    unresolved.append({'claim_ids':[left.claim_id,right.claim_id],
                        'reason':'Cross-source event identity is not independently established.'})
                    continue
                if not _contradictory_atoms(a,b):
                    continue
                group={'claim_ids':[left.claim_id,right.claim_id],
                    'source_ids':[left.source_id,right.source_id],
                    'source_hashes':[by_source[left.source_id].sha256,by_source[right.source_id].sha256],
                    'status':'CONFLICTED','reason':'Same scoped subject/time source assertions disagree; no source silently wins.'}
                groups.append(group)
                for index in (i,j):
                    effective[index].status='CONFLICTED'
                    effective[index].risk_route='CONFLICT_REVIEW'
                    effective[index].calibration_id=None
                    effective[index].reasons.append(group['reason'])
                    effective[index].uncertainty.append('unresolved_cross_source_conflict')
        return BoundVerificationResult(per_source_results=results,effective_results=effective,
            conflict_groups=groups,unresolved_event_groups=unresolved)
