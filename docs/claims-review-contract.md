# Claims review contract, version 0.1.0

Input: `claims-review-prep/0.1`; runtime: `claims-review/0.1.0`;
note: `claims-review-note/2`; rules: `claims-review-rules/2`.
Scope: synthetic HbA1c monitoring evidence, not payment adjudication.

## Identity and uncertainty

Source identity includes patient/source/encounter, availability, event metadata,
original locator and content. Same content does not merge sources. Code computes
internal IDs, Unicode offsets, structured pointers, grouping and dates.
All note keys are required; clinical values may be null. Null means unavailable or
not uniquely established, never false or zero. Unknown availability is distinct from
explicitly late availability. Conflicting assertions retain separate sources/values.
Proven inapplicability requires a false trigger in a declared complete comparison scope.
No target evidence permits empty facts, not an invented unknown test.

| Field | Meaning and evidence |
|---|---|
| value | Source-supported value. Boolean kinds require true/false/null, not 1/0; numeric results retain original structured values. |
| fact_date | Explicit date in date_role; null when not stated. Never borrowed from signature, receipt or request context. |
| target_date | Explicit date of the test discussed/requested, or null. Same-patient supplied encounter plus explicit test specificity can alternatively support binding. |
| date_role | actual_test, requested_test, order_issued, adjustment_start, background_review, unknown. |
| temporal_status | actual, historical, planned, unknown. A current disease assertion is actual even when its note precedes review_as_of. |
| test_specific | Explicit specificity true, affirmative nonspecificity false, otherwise null. |
| provider / reporter | Attributed provider/original reporter, or null. Signer does not automatically become every assertion's reporter. |
| authenticated | Applicable authentication true, explicit absence false, otherwise null; scoped to the assertion and cited source. |
| span_ids | Source lines including necessary header/body/signature context; multiple spans allowed. |

Purpose uses monitoring/screening/initial_diagnosis/null. Undocumented diabetes is
not an absence diagnosis. Regimen change true requires implementation; a prescription
alone is planned with unknown implementation. False requires affirmative nonimplementation.
A continuation plan does not negate an earlier implemented change.

Clinical rationale describes a stated test reason, not test completion. An
implemented_change rationale requires a separate actual, dated change in the relevant
comparison period; its assertion time may remain planned/unknown. Altered-control or
uncontrolled context needs actual/historical support; no numerical threshold is invented.
False is only affirmative contradiction of a specifically asserted rationale.

Order intent true means intent, not completion. Missing paperwork is null, not
cancellation. An authenticated specific-test clinical record can support intent without
a standalone signed order. Unrelated signatures cannot be borrowed.

## Retrieval and calculation

Preparation preserves the supplied inclusive date-level availability/as-of/window
rules. Unknown availability cannot support an as-of conclusion. Available excluded-window
members of explicit event groups still expose conflicting dates. Cross-patient and
unavailable members cannot bypass guards. Dates, values and encounter equality do not
automatically establish duplicate events. Unlinked/undated events retain uncertain counts.

Actual target performance requires a source, not claim.service_date alone. Notes produce
test mentions, not automatically new independent counted events. Structured final/completed
records establish actual events under finite mappings; raw fields remain intact.

Add three calendar months to a prior date, clamping month-end. Strictly earlier targets
are short; equality is not. Observed short intervals survive incomplete history. Only
declared complete, known comparison coverage permits NOT_APPLICABLE. This is a project
convention, not the complete CMS frequency algorithm.

## Evidence and execution

Criteria expose support, insufficiency, conflict, proven inapplicability, registry-defined
affirmative contrary evidence or not-evaluated scope, with clinical and policy references.
Empty citations cannot count as complete evidence. No AND produces approval or denial.
Structured facts use input JSON pointers and original CSV locators. Notes use exact
left-closed/right-open Unicode character offsets with method unicode_line_anchor,
not purported LangExtract alignment. Lexical/date/binding validation is not a semantic proof.

Only live constructs the concrete restricted Codex provider. At most one repair receives
source and runtime errors, never expected constraints or evaluation. Failed repair may
retain independently valid assertions from that final response, while execution remains
failed. Other valid facts survive. Provider failure is not successful empty extraction.
CLI errors return nonzero and replace stale success outputs with explicit failures or
partial failed packets. Missing/conflicted evidence by itself is not an execution failure.
