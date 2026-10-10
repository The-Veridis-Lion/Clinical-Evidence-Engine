# Engineering Case Study: Evidence Before Verdicts

## What Is Demonstrated

Clinical Evidence Engine is a Python backend prototype for traceable HbA1c
monitoring evidence review, alongside an independent therapy reconciliation
engine. The release ships original Prompt B as its normal note-extraction
default, with explicit A fallback and no Scope Audit implementation.

Fresh release verification passed 389 offline tests with live provider/network
dispatch blocked. A historical B-only workload processed 12 constructed notes
in 24 runs, including four repairs. Notes averaged 349.9 words; runs averaged
20.15 seconds and $0.00301 at Standard API-equivalent rates. Those metrics describe
this synthetic workload, not a subscription invoice or production throughput.
[Complete measurement accounting](release-measurements.md) keeps denominators,
length strata, and per-request usage references visible.

## Responsibility Boundaries

Original-archive retrieval streams original Synthea tables using explicit patient,
code, encounter, and date constraints. Preparation preserves original strings,
row/field locators, file hashes, availability uncertainty, and exclusions. The
finite original-row benchmark retrieved 26/26 source-task pairs across three
windows for one patient, representing 19 unique HbA1c rows. An associated
procedure or claim is not automatically another test or verified billing claim.
A supplied original archive can be reopened to verify row content before review.

Structured sources use deterministic parsing. Only selected notes go to Luna.
Typed nullable proposals keep unknown values distinct from false and zero;
code supplies internal identities and verifies exact quotes and offsets.
Validator checks and one bounded repair constrain transport/grounding errors,
but cannot certify clinical meaning. Request context cannot prove performance,
clinical purpose, or physician authentication.

Explicit field-scoped source relationships support amendments and retransmissions.
A correction needs patient/event/target/field identity and applicable authority.
Immutable source facts remain separate from derived values and reconciliation
traces; a later receipt cannot undo an earlier valid amendment. Ambiguous
relationships retain uncertainty or conflict rather than timestamp-based winners.

Policy prerequisites determine whether a specific criterion is evaluable.
Clinical evidence and policy applicability are separate dimensions. The registry
remains `draft_ai_reviewed` with no human verification. Four criteria produce
source-bound evidence states, never a claim-level payment decision. The three-
calendar-month comparison convention does not encode the entire CMS rule.

The therapy engine separately computes interval unions, breaks, encounter/day
counts, and uncertain totals. It is not replaced by the claims-review module.

## What Prompt B Improved—and What the Measurements Cannot Prove

Original B emphasizes propositions, actors, events, temporal roles, and source
support. A saved-output post-hoc analysis found 111/112 selected decidable
confirmation fields matching for B versus 103/112 for A, on 16 runs per prompt
from eight notes. It was **POST_HOC_REANALYSIS**, not fresh independent validation.
The later 12-note comparison suggested improved date binding and fewer nulls,
but frozen matcher gaps prevented a valid overall adoption score. All historical
scores remain intact. B was subsequently chosen as the research default; that
choice does not resolve model semantic failures or establish clinical accuracy.
See [post-hoc analysis](luna-ab-posthoc-reanalysis.md) and
[prospective comparison limitations](b-candidate-new-validation.md).

One useful source comparison: a nurse signature authenticated a message, while
the attributed physician's authentication was unknown. A produced false in both
selected repetitions; B preserved null. Conversely, B read a statement that a
new request did not establish an earlier collection as proof that the collection
did not occur. That unsupported negative appeared in the original model proposal
and survived grounding checks. Exact citation location was insufficient protection.

## Why the Scope Guard Was Excluded

The separate bounded experiment used 20 workflows and 50 requests, including
20 extra scope audits. Confirmation compared the same B facts before/after an
optional projection: criterion matches fell from 63/64 to 55/64, and complete
four-criterion executions fell from 15/16 to 8/16. Nine criterion states regressed;
one apparent improvement came from accidentally dropping a valid cancellation.

The audit isolated four clear family-background assertions, but also confused
ordering clinicians with patient beneficiaries, misread cancellation scalars,
and rejected grounded disease assertions as mere documentation. Authentication
requirements removed one side of genuine conflicts in both S08 repetitions.
An expensive extra model check did not establish safer downstream behavior.

In S07 repeat 1, the initial model supplied a date supported by broader source
context. A selected-span validator requirement triggered repair; repair changed
the date to null; the audit discarded the fact. This chain distinguishes initial
model correctness from validator pressure, repair changes, and projection failure.
The experimental branch preserves raw proposals, errors, repair changes, and
final views; the release does not import the regressive guard.

The scope experiment also had a missed split boundary: development CONTROL and
confirmation S03 reused a synthetic patient/event. Frozen results were not
rewritten or cases replaced. It is descriptive mechanism evidence, not eight
independent clinical holdout groups. Finite matching defects further prevent
reporting overall semantic citation precision or fact precision/recall.

## Reproducibility and Engineering Trade-offs

The release includes pinned dependencies, synthetic sources, offline tests,
source hashes, a compact results summary, and a no-inference cost summarizer.
Raw patient materials, complete call traces, ledgers, archives, and generated
SQLite databases stay local and ignored. Live work uses persistent call budgets;
this release used zero new provider requests.

This architecture makes failures inspectable rather than treating valid JSON as
correct medicine. It also has limits: whole-patient loads, limited terminology,
source/subject semantics, restrictive validation, and finite policy scope.
Evidence-supported synthetic demonstrations are appropriate for an engineering
portfolio. Clinical deployment, generalized reliability, semantic citation
precision, and compliance certification remain NOT VERIFIED.
