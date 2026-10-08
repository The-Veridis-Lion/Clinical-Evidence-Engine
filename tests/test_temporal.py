"""Interval accounting is clinical patient time, not elapsed appointment time."""
import pytest
from pydantic import ValidationError

from clinical_intelligence.domain import TimeInterval
from clinical_intelligence.temporal import treatment_minutes
from clinical_intelligence.reconcile import reconcile


def intervals(*pairs):
    return [TimeInterval(start=a, end=b) for a, b in pairs]


def test_overlapping_and_touching_reports_count_time_once():
    assert treatment_minutes(intervals((540, 570), (560, 585), (585, 600)), []) == 60


def test_partial_overlap_length_equals_total_lengths_minus_union():
    actual = intervals((600, 645), (630, 660))
    total_lengths = sum(interval.end - interval.start for interval in actual)
    union_minutes = treatment_minutes(actual, [])
    assert total_lengths == 75
    assert union_minutes == 60
    assert total_lengths - union_minutes == 15  # Their geometric overlap is 10:30–10:45.


def test_late_arrival_early_departure_and_middle_break_use_actual_presence(evidence, service):
    abstract = reconcile([evidence("partial-patient-presence", [service(
        service_type="group", actual_intervals=[{"start": 615, "end": 675}],
        scheduled_intervals=[{"start": 600, "end": 690}], breaks=[{"start": 645, "end": 660}],
    )])])
    assert abstract.events[0].minute_options == [45]
    trace = abstract.events[0].calculations[0]
    assert trace.inputs["actual_intervals"] == [{"start": 615, "end": 675}]
    assert trace.output == {"minutes": 45}
    assert set(trace.claim_ids) == {"partial-patient-presence:0"}


def test_only_break_overlap_with_patient_presence_is_subtracted():
    assert treatment_minutes(intervals((615, 675)), intervals((600, 610), (645, 660), (670, 690))) == 40


def test_reconnection_gap_does_not_count_as_treatment():
    assert treatment_minutes(intervals((780, 800), (810, 835)), intervals((800, 810))) == 45


def test_duplicate_and_overlapping_breaks_are_not_subtracted_twice():
    assert treatment_minutes(intervals((600, 690)), intervals((645, 660), (650, 665), (645, 660))) == 70


@pytest.mark.parametrize("start,end", [(600, 600), (600, 590), (-1, 60), (1400, 1500)])
def test_invalid_same_day_intervals_are_rejected(start, end):
    with pytest.raises(ValidationError):
        TimeInterval(start=start, end=end)
