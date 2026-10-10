# Critical source-assertion review

Review method: non-independent direct reading of original CSV fields and runtime objects.
No human/clinical expert participated. This small purposeful review is not an
independent exhaustive gold set; no semantic precision percentage is reported.
Dataset SHA: `d61417b551e5b0997c33851b339c157421751f0ea68c18ea686ceb1850907c35`.
All following sources bind to patient `7af6b271-f16d-21e1-882a-7bff71005a7b`.

| Assertion reviewed | Inspectable source | Runtime meaning | non-independent finding / scope |
|---|---|---|---|
| A prior HbA1c result exists on 2017-02-14, value 5.9% | observations.csv data row 8765: CODE=4548-4, DATE=2017-02-14T22:51:41Z, VALUE=5.9, UNITS=% | actual test_event, printed date, original string value | Supported as a source result. No inference of target purpose, authentication or independent event count. |
| Diabetes background is recorded, not proven current activity | conditions.csv row 712: CODE=44054006, START=2000-11-14, STOP empty | historical diabetes_context=true, current_activity=null | The coded diagnosis supports background. Blank STOP interpretation is not independently validated here; current-activity abstention may underuse exporter semantics. Retained as a limitation, not silently rescored. |
| Prescription does not prove an implemented regimen change | medications.csv row 421: metformin 860975, START=2016-02-09T22:51:41Z, STOP=2017-02-14T22:51:41Z | regimen_change value=null, temporal_status=planned; separate order_issued_date | Avoids false implementation/date certainty. Administration/adherence is not present in this row. |
| The requested 2026-10-05 performance is not established | observations.csv row 10058 is the last selected patient's HbA1c result: DATE=2026-04-14T22:51:41Z, VALUE=5.9 | latest actual source remains April; constructed October request is not a test_event | Correct missing-source behavior within the inspected archive/scope. Does not prove no October test occurred elsewhere. |
| Same-encounter claims are not verified HbA1c bills | Original claims.csv PATIENTID/APPOINTMENTID links; 63 auxiliary records in full task | separate linked_records, counted_as_test=false; no procedure-code assignment | Association supports contextual linkage only. Billing identity/independent test linkage remains NOT VERIFIED. |
| Repeated result records are not automatically separate tests | Nineteen original observation rows, no explicit shared test-event ID | separate uncertain timeline groups, counted_as_tests=null | Avoids unsupported deduplication and overcounting. Conservatism can prevent a complete timeline conclusion; no independently labelled event identity exists here. |

Earliest gap attribution: fourteen omitted prior result rows were absent from the
old curated CaseInput before extraction. New retrieval restores them; Luna and rules
did not cause that omission. Missing target performance/order/note information is a
source gap, not a parser failure. All final commands returned success with
execution_failed=false while the evidence findings remain insufficient.

Policy meaning was separately inspected against official sections in the
[verification sheet](claims-review-policy-verification.md). Automated audit confirms
declared locator membership and source ownership, not that an arbitrary quoted clause
supports every clinical assertion. No false-certainty or unnecessary-unknown rate is
invented from this six-assertion purposeful review.
