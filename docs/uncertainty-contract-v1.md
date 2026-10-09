# Uncertainty contract v1

This contract was reviewed through AI-assisted engineering analysis, without human annotation or clinical-expert confirmation. The default uses `uncertainty_contract=nullable_v1`: it retains the previous clinical_partition design and changes only rules and examples that contradict unknown-value semantics. The broader `uncertainty_contract=v1` rewrite remains a non-default experimental profile. Both use the same nullable typed schema. Every model key is required, while fact values may be nullable. The previous generation contract is frozen separately for comparison.

Extract every fact supported by the source. Use unknown values only when the evidence is insufficient; do not guess or abstain when sufficient evidence exists. Unknown fact values consistently use JSON `null`, except reporter/experiencer roles, which use `not specified`. Never substitute false, zero, or an empty string for missing information. An array `[]` means no supported items were extracted; it does not establish zero treatment.

| Model fields | Representation and boundary |
|---|---|
| patient_id, name, dob, declared_id | Nullable. Explicit IDs must not be omitted. Missing patient IDs remain unknown; storage isolates unlinked documents with internal keys rather than inventing an MRN. |
| statement | A source-supported, readable assertion preserving negation, ambiguity, and scope. kind is an output category label; neither field asks the model to invent an undocumented fact. |
| recorded_at, all service/observation/assessment/plan dates, references, reason | Nullable. Date roles are not interchangeable. ID prefixes do not establish entity roles. |
| signed (service, plan, relationship) | true for an applicable explicit signature; false for an explicit unsigned statement; null when not established. Final/export status is not a clinical signature. |
| patient_present, delivered | Respectively, patient presence and actual service provided to the patient. Administrative Completed status alone establishes neither. Explicit absence/nondelivery is false; insufficient evidence is null. Preserve administrative status in reason. |
| service_type, evidence_kind | Nullable. Uncertain classification does not erase other facts. Unsigned clinical contact remains source evidence but does not satisfy a signed-service review rule. |
| actual/scheduled/unspecified intervals, breaks | Arrays preserving each known endpoint; the other endpoint may be null. Do not invent intervals with both endpoints unknown. Calculate only complete intervals and propagate missing bounds. |
| reported_minutes, score, required_days, required_minutes | Nullable numbers. Only an explicit zero is 0; missing values do not imply zero. |
| plan effective_start/end, service_types, week_basis | Retain partial quantitative plans. Unknown types use []; an unknown weekly basis uses null. Only complete, signed, applicable plans support definite comparisons; partial plans can produce cannot_determine. Qualitative recommendations remain observations. |
| assessment instrument, copied | Nullable. copied is true for explicit copying, false for an explicit original, and null otherwise. Unknown instruments/subjects are not automatically merged or used for trends. |
| reporter, experiencer | The established original reporter/experiencer; otherwise `not specified`. A signer is not automatically the reporter of every assertion. |
| observation category, temporality, polarity | Nullable. The existing polarity=uncertain denotes an ambiguous assertion; null means polarity was not established. statement is not logically negated a second time. |
| relationship relation, field, targets, replacement/original values | Nullable. Do not force an unclear relationship into a correction. Apply only supported, signed relationships with matched targets and fields. |
| uncertainty_notes | Short `{field,state,explanation}` entries with state=not_documented, ambiguous, or not_applicable. Describe a null, empty array, or missing endpoint such as `actual_intervals[0].end`; do not erase known values. |

Known facts use supported nonempty values. A null without a note defaults to Not documented; uncertainty_notes distinguishes Ambiguous and Not applicable. Conflicting facts use multiple supported claims and the existing Conflict/State representation. Retain the different values and sources rather than replacing them with one null.

Code still owns internal IDs, exact offsets, clock conversion, interval arithmetic, correction application, and final calculations. Unknown duration retains an unknown upper bound/value. A contact with adequate time evidence but an unknown signature retains its known time and eligibility uncertainty, for example 0-30 minutes with value=null. Unknown correction authority/scope does not certify either an applied correction or the old value. A known nonqualifying contact can contribute a definite zero; that does not imply an unknown patient was absent. Pure administrative documents without service facts may contain zero service claims.

The audit covers every property in the six typed Luna output kinds. `functional_action` is a separate application type, not a Luna-generated kind in this round. Scoped source metadata and historical mentions remain experimental options; adding fields alone is not evidence of better extraction quality.
