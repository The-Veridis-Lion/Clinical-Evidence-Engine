# Generalizable reliability: bounded engineering delivery

Starting branch: `feature/frozen-confirmation-integrity`, commit `a194ac6`.
Implementation branch: `feature/generalizable-review-reliability`.
Actual first-pass confirmation candidate: `171c08f`. Historical artifacts, gold,
scores and the original persistent ledger remain preserved. No main merge.

## What changed and why

The [pre-change audit](reliability-audit.md) distinguishes three earliest failures:
the validator rejects a supported analyte phrase and repair erases specificity;
rules evaluate a policy without its date prerequisite; structured targeted
amendments never reach a derived view. These are different architectural layers.
The [versioned contract](reliability-contract.md) specifies the resulting boundaries.

Before: source -> raw note proposal -> narrow lexical validation -> optional repair
-> facts -> raw date grouping -> four criteria. Grounding success can mask missing
fields, semantic overreach and unknown applicability.

After: structured rows -> deterministic facts/typed source relationships; notes ->
the existing nullable factual contract -> terminology/date/provider grounding ->
bounded preservation-aware repair -> immutable facts + field-scoped derived view
-> explicit per-criterion applicability + clinical-evidence result -> evidence packet.
Original source citations remain, alongside mapping basis and reconciliation trace.

Changed runtime files are `grounding.py`, `applicability.py`, `relationships.py`,
`facts.py`, `note_extractor.py`, `review.py`, package version and policy registry.
New generic tools freeze/evaluate the synthetic suite, replay saved proposals and
audit complete call chains. Tests and seven lightweight owned synthetic inputs are
included. Therapy, CSV retrieval, archive verification and historical scorer/gold
are untouched. No additional dependency, terminology server, routing-model call,
new payer or adjudication engine was introduced.

The terminology vocabulary is bounded and evidence-grounded. Clinical-family
mapping is distinct from exact synonyms and verified printed LOINC codes. No assay
code is inferred from a bare phrase. Named-month dates can ground normalized dates;
ambiguous/partial dates stay unknown. Grounding is not clinical semantic proof.

Applicability reasons and `clinical_evidence_status` are separate. Missing service
date defers policy evaluation without erasing known facts. Unknown fields not required
for policy selection are not global applicability blockers. Availability/identity
constraints still screen the relevant sources before extraction and evaluation.

Explicit field relationships require patient/event/target/field/authority binding.
Copies cannot undo amendments through later receipt. Raw values stay immutable;
derived values and each decision are traceable. Null authority, competing amendments,
cycles, missing targets and mismatched patients do not pick a winner. Source-declared
signature authority is not independent authentication of a laboratory or clinician.

## Evidence and denominators

| Evidence type | Complete conformance | Criterion states | New calls | Interpretation |
|---|---:|---:|---:|---|
| Historical frozen real confirmation | 3/6 | 16/24 | 0 this round | Previously measured history, unchanged |
| Exposed-case chronological saved-response replay | 5/6 | 24/24 | 0 | Diagnosis/regression, not independent confirmation |
| New first-pass synthetic materials, frozen 171c08f | 5/7 | 28/28 | 4 | Three live-note cases + four deterministic cases |
| New live-note subset | 1/3 | 12/12 | 4 | Field incompleteness remains despite criterion matches |
| New structured subset | 4/4 | 16/16 | 0 | Offline deterministic source-relationship/control evidence |
| Final post-confirmation metadata fix replay | unchanged 5/7 | unchanged 28/28 | 0 | Saved responses, not another unseen evaluation |

Baseline tests were freshly executed: **314 passed in 4.53 s**. Final delivery:
**350 passed in 4.08 s**. This includes concept/date/signature controls, grounding,
repair preservation and augmentation, applicability dimensions, field corrections,
unsigned/wrong-target/wrong-patient/scope controls, competing amendments/cycles,
unknown result handling and raw-call audit preservation.

The initial sandbox run failed because of temporary-directory permissions and
subprocess import paths; those logs remain. Explicit workspace TEMP/TMP/PYTHONPATH
allowed the original frozen suite to pass. The runtime environment actually used
Pydantic 2.13.5, LangExtract 1.7.0, intervaltree 3.2.1 and pytest 9.1.1.
An isolated wheel build with pinned setuptools succeeded; final installed CLI was
tested outside the source import path, zero model calls. Earlier non-isolated build
attempts failed because setuptools was absent from the shared test virtualenv;
their logs remain. Dependencies were not silently changed.

Selected required-field constraints: **21/23 matched**. Known-value constraint
projection precision **16/17**, recall **16/18**. These are selected field-value
checks, not exhaustive clinical fact precision/recall; null expectations are scored
separately. One unnecessary null and one strict temporal-value mismatch remain.
False-certainty counter **1/23** includes that disputed temporal label. No frozen
label or denominator was edited after outputs were seen.

All 627 repeated citation occurrences passed positional/hash/patient/source checks;
wrong-patient inclusions 0. These are repeated references, not independent semantic
assertions. Full semantic citation precision remains **UNAVAILABLE**. A separate
non-independent 12-assertion source audit also identified unlabelled semantic risks;
human and clinical-expert review remain false.

Actual use: gpt-6-luna/high, CLI 0.159.3, timeout 180 s, tools disabled, ephemeral
source-only context, application extraction cache disabled. Calls 14-17: **4**, with
**1 repair**, 0 transport retries, parse failures or execution failures. Input tokens
69,431, output tokens 5,176, cached tokens 0. Provider latency total 59.92 s; complete
seven-case CLI execution total 61.62 s. Actual subscription dollar cost and backend
model snapshot are unavailable. The ledger advanced **13/20 -> 17/20**, leaving 3;
hash reconstruction confirms all previous 13 entries are unchanged. No quota reset
or parallel ledger was used. No further calls are planned for this round.

## Freeze, independence and complete failure retention

The candidate/evaluator/input/expected-byte hashes were recorded before inference.
All seven first-pass predictions were saved and sealed before the evaluator decoded
expected constraints. The new inputs were authored from explicit synthetic facts,
then checked against those facts. The engineer authored and knew the constraints;
this is new-material confirmation with model-blind expectations, **not author-blind,
human-labelled, real-clinical or clinical-expert validation**. Seven cases share
mechanisms/templates, and paired amendments are correlated counterfactuals. No
confidence interval or population-generalization claim is justified by this size.

The six former holdouts are exposed regressions. Neither their original gold nor
the historical 3/6 and 16/24 was overwritten. No new live calls tuned those cases.

All inputs, visible answers, exact prompts/schemas, validator errors quoted to repair,
repair deltas, final facts, applicability, reconciliation, criteria and resource logs
remain local. `audit_claims_calls.py` creates an expanded immutable-file-referenced
trace; its kind/ordinal diff is inspectable structural alignment, not clinical entity
proof. Raw trace directories and original packet files were not rewritten.

Failures are retained and separated:

- Historical lexical failure: correct specificity is present in the first proposal,
  then null in the repair after an overly narrow validator rejects it. This is not
  a first-response omission. New replay accepts the original phrase directly.
- Historical repair-preservation regression: a structurally grounded nonimplementation
  assertion disappears in repair. New code retains it but marks execution failed;
  all four criterion states can match while full conformance fails. The original
  statement concerns absent documentation, so semantic truth is not established by
  its positional validation. Conservative blocking remains a limitation.
- REL-01: purpose target_date=null despite an explicit July 16 request. The order
  contains the correct date, and encounter binding makes all criteria match. This
  is an unnecessary field abstention, never reported as full document success.
- REL-02: value=false correctly preserves nonimplementation, while temporal_status
  is actual rather than the frozen planned label. Current nonimplementation and
  future discussion are both source-supported roles. non-independent review flags a
  representation dispute; the strict mismatch remains, without calling it proven
  incorrect clinical certainty or changing expectations.
- REL-02 extra background assertion: routine monitoring language is promoted to
  definite established-disease background without explicit note-level establishment.
  Structured disease evidence separately supports the criterion, masking that note
  overreach. It is outside the selected field projection and explicitly disclosed.
- REL-03 extra background assertion inherits a planned time role from the repeat-test
  intention. This role uncertainty is visible although policy correctly defers.

## Separate program correction after confirmation

An independently constructed partial-result regression exposed a local defect:
`[known_result, null]` was marked as result conflict. `claims-review-structured/3`
requires two distinct non-null values and separately records `result_unknown`.
This was not prompted by a frozen-case scoring failure. Original values remain.
No note prompt/schema or criterion code changed. Seven saved-response replays retain
all clinical fields and all 28 criterion states. The final runtime includes this
offline-verified correction; its full fresh-live unseen workflow is **NOT VERIFIED**.
Actual model measurements belong specifically to frozen `171c08f`.

## Examples across source forms

- Letter: `glycated hemoglobin on July 16, 2026` plus `Digital signature: Dr. Mira Aster`
  grounds the order/date/provider without inventing a LOINC assay code. Purpose date
  omission remains visible alongside the successful order.
- Table: `Hgb A1c | requested for 27 Sep 2026` and `order unsigned` preserve the
  clinician's unauthenticated intention. An administrative signature from a different
  provider does not authenticate that order. Repair adds a missing test-context span
  to a null rationale without changing known clinical fields.
- Mixed memo: a known result with unknown collection date and month-only intended
  repeat retains the score, null dates/providers, and separate clinical meaning.
  All policy criteria are NOT_EVALUATED with prerequisites explained.
- Structured date amendment: the original June 6 statement remains; authenticated
  event-bound amendment derives August 6; later unchanged original copy cannot
  revert it. With authority unknown, both dates and uncertainty remain instead.
- Structured result amendment: original 7.8 and amended 6.4 remain as raw facts;
  derived result is 6.4 for one explicit event, with the unchanged April 2 date.

## Routing decision, limits and portfolio recommendation

Keep the existing deterministic structured/note routing. Multiple compatible note
fact families remain. Structured relationships have a small separate typed contract.
No controlled evidence shows a routing-model or larger note schema improves quality;
neither was introduced and there is no additional routing latency. Free-text-only
amendment extraction, broader terminology/date locales, arbitrary corrected fields,
exhaustive semantic validator, historical payer code applicability and large-cohort
clinical performance are **NOT VERIFIED / outside this implementation**.

This version is suitable for an **honest engineering portfolio demonstration** of
layer separation, immutable evidence, explicit uncertainty and failure diagnosis.
It is not evidence of generalizable complete clinical accuracy, signature authenticity,
Medicare adjudication or production readiness. Improvements primarily come from
program contracts and reconciliation; no improved underlying Luna capability is
claimed. The retained failures, not a 100% criterion table, define the next boundary.

## Reproduce and inspect

Install the project and test dependencies, then:

```powershell
python -m pytest -q
python -m clinical_intelligence.claims_review run --case examples/claims_review/reliability_v1/inputs/REL-04.json --output artifacts/demo/REL-04.json
python -m clinical_intelligence.claims_review render --packet artifacts/demo/REL-04.json --format summary --output artifacts/demo/REL-04.md
```

For a fresh measurement, use a new output directory and the **same original ledger**;
the remaining allowance may prevent a complete fresh three-note pass. Never reset
or create another ledger. Freeze using `171c08f` to reproduce the measured workflow;
current HEAD includes the disclosed post-confirmation metadata correction.

```powershell
$env:PYTHONPATH="src;tools"
python tools/evaluate_claims_reliability.py freeze --suite examples/claims_review/reliability_v1 --output artifacts/FRESH_RUN
python tools/evaluate_claims_reliability.py predict --suite examples/claims_review/reliability_v1 --output artifacts/FRESH_RUN --ledger ORIGINAL_LEDGER --traces ORIGINAL_TRACES
python tools/evaluate_claims_reliability.py evaluate --suite examples/claims_review/reliability_v1 --output artifacts/FRESH_RUN
python tools/replay_claims_reliability.py --inputs PRIVATE_INPUTS --traces ORIGINAL_TRACES --output artifacts/FRESH_REPLAY
python tools/audit_claims_calls.py --inputs PRIVATE_INPUTS --packets PRIVATE_PACKETS --traces ORIGINAL_TRACES --output artifacts/FRESH_AUDIT.json
```

Do not execute a fresh run merely to improve this displayed score. The
[machine summary](reliability-validation.json) indexes the private freeze, original
predictions, full audits, semantic review, replay, tests and installed CLI checks.
Expanded outputs, original inputs/gold/archives and ledger remain ignored.
Rollback: create a separate checkout/worktree at `a194ac6`, preserving current work;
use `171c08f` for the exact first-pass candidate. No destructive reset is needed.

## 75-second demo

0-15 s: distinguish raw-source retrieval from the new synthetic mechanism fixtures;
show an explicitly constructed target and policy draft boundary.
15-35 s: run REL-04 offline and show immutable June 6, explicit August 6 amendment,
later original copy, one derived event and field-scoped trace.
35-50 s: render the saved real REL-01/REL-02 packets, identify actual calls 14-16,
show correct order evidence, unnecessary null and repair's citation augmentation.
50-65 s: show REL-03 known score/unknown date and policy NOT_EVALUATED reasons.
65-75 s: show the honest benchmark: 28/28 criteria but only 5/7 complete constraints,
an unlabelled semantic risk, no human review and no payment decision.

Interview explanation: retrieval controls which patient/time-bound sources are
available; the model proposes typed source facts; grounding checks references without
claiming clinical truth; explicit relationships produce a derived view without deleting
originals; prerequisites/rules determine narrowly scoped evidence findings. Each
layer has an independent failure surface and a preserved audit trail.
