# Evaluation-only semantic contract v2

All results are **POST_HOC_REANALYSIS** of saved proposals, not fresh inference,
unseen confirmation, human/expert labels or clinical validation. The AI reviewer
previously saw the outputs. Source-only review views hide candidate/repeat/score
columns but do not establish reviewer blinding. Original gold and scores are immutable.

Each source-bound proposition has a stable constraint ID and an AI_ASSISTED review
entry: old requirement, exact evidence locator/quote/hash, retain/revise/unresolved
decision, reason, allowed representation and affected fields. Review covers all 16
source notes rather than only the previously reported failure. Save the overlay,
contract and scorer hashes before candidate totals are produced.

Identity is patient + source + semantic proposition frame + grounded event scope.
Historical result, receipt/performance documentation, current nonimplementation,
future discussion, patient condition and another subject's condition are distinct.
An additional context span does not change identity. Order/array position and field
correctness never select the winning object. Unknown event matching is MATCH_UNRESOLVED.
All same-proposition objects are checked; contradictions cannot hide behind a correct
object. Every matched object must carry its own fields: never stitch a perfect result.

Explicit collection/slot dates remain test dates. Orders/requests "on" a date without
collection scope may mean issue date or requested test date. Mark only the target-date
constraint AMBIGUOUS_SOURCE. Preserve all other fields. Coupled roles remain coherent:
order_issued + issue fact_date + null target, or requested_test + stated target + null/
same fact_date. Ambiguity does not license invented performance or contradictory roles.
Month-only precision cannot establish a day. Signature/receipt never backfill dates.

Numeric equivalence parses the existing value only. Finite native numbers and original
bare-number string encodings remain permitted by the original scalar contract; their
unit is explicitly not encoded. Exact percent/HbA1c wrappers can normalize read-only.
Preserve original text and conversion basis. Wrong number, unit, analyte, patient,
negation and comparison are not equivalent; multiple/unsupported numbers are unresolved.
Do not supply a missing value from gold/source/statement. Information in statement
is separately inspectable and cannot make a missing required value field pass.
True is not 1; false is not 0; missing key, null and false have distinct outcomes.

Temporal status scopes its proposition. Current nonimplementation is actual false;
future discussion can be a separate planned assertion. Its boolean implementation
meaning may be CONTRACT_UNDERSPECIFIED; do not conflate it with current implementation.
Source-document authentication and the reporter/provider of a specific assertion
remain different. Runtime signature/repair behavior is preserved, not rerun or changed.

Extras are reviewed as SUPPORTED_IN_SCOPE, SUPPORTED_OUT_OF_SCOPE, DUPLICATE,
CONTRADICTORY/UNSUPPORTED or UNRESOLVED. Unreviewed definite extras never count correct.
No-target administrative null placeholders are scope deviations, not fictional completed
tests. Finite lexical classification has limits; retain original source/output hashes
and unresolved entries for audit instead of pretending to be a general NLU engine.

Report candidate, scored, unresolved and missing constraints. Pair A/B on the same
case/repeat and common decidable cells; unresolved cells do not waive other errors.
First and final are the same execution's stages, not independent samples. Historical
usage is deduplicated by 56 original call IDs; this task has zero calls/tokens.
No exhaustive fact precision/recall, significance or production generalization claim.
The old 192/192 criterion matches are retained, never used as extraction accuracy.

Ten offline self-test groups precede full rescoring: numeric meaning; coherent date
roles; null/false/zero/missing; current/future propositions; result/receipt separation;
context/order/paraphrase; identity/event controls; contradictions/no stitching;
scope/extra categories; candidate/repeat invariance and local unresolved denominators.
Tests have positive and substantive negative controls and a provider-fails-immediately
substitute. Maximum two full rescoring passes, persistent 45/55-minute deadlines.
A remains default regardless of post-hoc findings; no new model experiment is authorized.
