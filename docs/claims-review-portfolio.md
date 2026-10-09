# Engineering demonstration

## 60-90 second script

**0-15 seconds.** "This prototype prepares evidence for a specific HbA1c monitoring
request. It does not approve or deny claims. The target request is explicitly
constructed; the patient sources come from an original official synthetic archive."

**15-35 seconds.** Show `target-query.json`, the archive SHA/member manifest, and run
`retrieve`. "We stream full relevant CSV tables, enforce patient/code/date boundaries
and preserve row locators and hashes. This finds nineteen result records, including
fourteen older results missing from the previous five-row demonstration. Excluded
rows remain traceable locally. Same-encounter claims are not treated as HbA1c bills."

**35-55 seconds.** Run `run --retrieval ...`, then `render --format summary`.
"Structured rows use deterministic mappings. Only relevant natural-language notes
would enter the specialized nullable Luna extractor. This CSV archive has no such
selected notes, so this authentic run makes zero model calls. Historical note tests
are reported separately; they are not presented as this patient's original notes."

**55-75 seconds.** Show the four criteria and missing-source explanation.
"We have prior results but no source proving the October test, its purpose or provider
intent. All four findings remain insufficient. Unknown is not false or zero; uncertain
event identity is not an invented count. Policy and clinical citations are separate."

**75-90 seconds.** Show the benchmark table and audit command.
"Retrieval matched 26 of 26 source-task pairs across three overlapping windows for one
patient. Position checks are not semantic accuracy. Six reserved confirmation inputs
were unavailable, and no human policy review occurred. The reproducible branch and
limitations are part of the demonstration, not hidden behind a perfect score."

## Technical case study

The earlier wrapper exposed only five 2023-2026 HbA1c observations. Asking for a
longitudinal history could not discover the fourteen older original rows: filtering a
preselected list cannot recover absent records. The new entry point accepts archive
plus request, discovers original rows, and applies existing preparation/reconciliation.
The fixed original-row oracle is separate from runtime output. Different patients and
irrelevant codes/windows are excluded; event identity remains uncertain without
evidence. Restored history still does not manufacture a target test or physician intent.
The missing-source conclusion is a useful, explainable evidence-review result.

A complementary historical error illustrates layer isolation: DEV-002's first live
answer contained a planned rationale and an actual dated change. Rule-v1 rejected the
rationale because it required the rationale itself to be actual. Rule-v2 separates
reason assertion time from the linked implemented event. This phase reran the five
saved responses successfully. That supports a program-fix regression claim, not a
fresh prompt-accuracy claim. See the earlier integration report for the preserved
failure and one targeted real final-prompt call.

## Interview explanation

"Retrieval decides which source records are available and relevant, while preserving
their identities. The LLM extracts supported language facts into a nullable contract;
it does not calculate intervals or decide coverage. Deterministic rules evaluate four
explicit evidence criteria and propagate missing/conflicting information. Source tracing
lets us distinguish a missing row, a model misreading, a binding error and a rule defect.
We benchmark those layers separately because a correct-looking final status can hide
the wrong source or a failed extraction. This is a scoped engineering prototype using
synthetic data; independent clinical accuracy and full Medicare adjudication are not
demonstrated."
