"""Observable unknown-value behavior; fixed facts, no model or clock dependency."""
from clinical_intelligence.domain import AssessmentClaim, ClinicalObservation
from clinical_intelligence.query import query_patient, QuerySpec
from clinical_intelligence.reconcile import reconcile


def measure(**changes):
    value=dict(factory=AssessmentClaim,instrument='PHQ-9',assessment_date=None,
               score=11,reporter='patient',experiencer='patient')
    value.update(changes)
    return value


def test_undated_evidence_survives_without_becoming_today_or_receipt_date(evidence):
    abstract=reconcile([evidence('paper',[measure(recorded_at='2026-08-10T15:00:00'),
        dict(factory=ClinicalObservation,observation_date=None,category='safety',
             reporter='patient',experiencer='patient',polarity='absent',temporality='current',
             statement='Patient denies suicidal thoughts.')])])
    answer=query_patient(abstract,QuerySpec(family='progress',start='2026-08-01',end='2026-08-31'))['result']
    assert answer['assessments']==answer['observations']==answer['score_changes']==[]
    assert answer['undated_assessments'][0]['score_options']==[11]
    assert answer['undated_assessments'][0]['state']=='insufficient_evidence'
    assert answer['undated_observations'][0]['observation_date'] is None
    assert answer['undated_observations'][0]['polarity']=='absent'


def test_blank_score_never_creates_zero_or_a_score_change(evidence):
    abstract=reconcile([evidence('first',[measure(assessment_date='2026-08-01',score=11)]),
                        evidence('blank',[measure(assessment_date='2026-08-08',score=None)])])
    answer=query_patient(abstract,QuerySpec(family='assessments',start='2026-08-01',end='2026-08-31'))['result']
    assert [a['score_options'] for a in answer['assessments']]==[[11],[]]
    assert answer['score_changes']==[]


def test_missing_dates_alone_do_not_merge_different_forms(evidence):
    abstract=reconcile([evidence('one',[measure()]),evidence('two',[measure(score=9)])])
    assert len(abstract.assessments)==2
    assert all(a.assessment_date is None for a in abstract.assessments)


def test_explicit_same_form_can_link_a_known_completion_date(evidence):
    abstract=reconcile([evidence('paper',[measure(form_ref='Q-1')]),
                        evidence('dated-copy',[measure(form_ref='Q-1',assessment_date='2026-08-08',copied=True)])])
    assert len(abstract.assessments)==1
    assert abstract.assessments[0].assessment_date.isoformat()=='2026-08-08'
    assert abstract.source_claims[0].assessment_date is None
