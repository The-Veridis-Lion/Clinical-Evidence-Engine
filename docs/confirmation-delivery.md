# Frozen confirmation and original-source integrity

This follow-up completes the original reserved synthetic confirmation and adds a
separate optional archive-verification boundary. No holdout tuning, selective rerun,
new clinical-note source, Coherent exploration or main merge occurred.

## Versions and separation

- Reviewed HEAD: `1b2ceac5522f2790e18407f3d02ba60dcbb0a2e9`.
- Frozen inference implementation: `814b1f81e8a2a174088598549c770e31ab9d6ba6`.
  Git comparison confirmed the intervening commit changed no runtime/tests/evaluators.
- Confirmation ZIP SHA-256:
  `b56d7f767065f59045ef7804222d58125afe58a6d9c6f3a79d16a906d9c58352`.
  Safe paths and all twelve original input/expected hashes matched the original manifest.
- Post-confirmation integrity code: `edb20fe532dc8a6003df7e56a4c2cb1195bd8c01`;
  verification `claims-review-archive-verification/1`.
- Read-only expected adapter: `claims-confirmation-evaluation/1`. Created only after
  prediction seal to handle scope and explicit amendment constraints absent from the
  development evaluator's format. It does not change expectations or inference.

Expected bytes were hashed without decoding values during ZIP verification. Runtime,
policy, prompt/schema hashes, dependency versions, case order and the absolute original
ledger were recorded before input decoding. Inputs were extracted alone to an ignored
directory with a current-user/SYSTEM ACL. Model subprocesses used isolated temporary
directories and disabled tools; they received source/context, never expected constraints.

All six packets finalized and their hashes were sealed at **2026-10-09 15:32:57.174633
UTC**. Expected values were first decoded at **15:33:25.530873 UTC**. Packet files are
read-only and hashes are retained alongside visible responses and exact requests.
This is auditable local process separation, not independent cryptographic proof that
no conceivable access occurred. Original expected/source contents are not redistributed.

## Frozen result table

Requested `gpt-6-luna`, high reasoning, Codex CLI 0.159.3, note v2, rules v2,
one validation repair maximum per note, no application cache. Actual backend snapshot
was unavailable. Every original workflow attempt is included.

| Case | Automatic conformance | Criterion matches | Real calls / repairs | Provider seconds | Earliest material issue |
|---|---|---|---|---|---|
| CONF-001 | Fail | 2/4 | 2/1 | 28.979 | Validator rejects the source's glycated-hemoglobin synonym; repair changes specificity to null |
| CONF-002 | Pass | 4/4 | 2/1 | 33.636 | One citation-context repair; planned adjustment remains unstarted |
| CONF-003 | Fail | 0/4 | 1/0 | 16.051 | Required date is null but policy/criterion evaluation is not deferred |
| CONF-004 | Fail | 2/4 | 1/0 | 17.685 | Scoped module preserves competing dates but does not apply explicit specimen-date amendment |
| CONF-005 | Pass | 4/4 | 0/0 | 0.003 | Other-patient note excluded before inference |
| CONF-006 | Pass | 4/4 | 1/0 | 20.100 | Initial diagnostic purpose correctly leaves monitoring scope |

Automatic conformance: **3/6**, overall-state match **4/6**, criterion-state match
**16/24**. The denominator includes eight NOT_EVALUATED scope expectations; there are
sixteen ordinary criterion expectations. The five live-note cases passed **2/5**;
the structured-only case passed **1/1**. These are non-independent synthetic constraints,
not human/clinical expert labels, exhaustive fact matching or production accuracy.

False SUPPORTED against original constraints: **1**, CONF-003 monitoring scope. Its
clinical facts are source-supported; the error is policy applicability without a date.
Unnecessary INSUFFICIENT_EVIDENCE: **2**, both CONF-001. Execution failures, parse
failures, timeouts and wrong-patient inclusions observed: **0**. Automated audit found
**0 failures in 612 citation occurrences**, with repeated references counted separately.
Position/source ownership checks do not establish semantic precision.

Direct non-independent source/visible-response review examined all original fact constraints,
including positive authenticated intent, unstarted plans, preserved undated result,
targeted amendment, signature scope, patient isolation and diagnostic purpose. Findings
are in the [machine summary](confirmation-validation.json). Two residual field concerns:
CONF-002 purpose target_date is unnecessarily null; CONF-006's false diabetes_context
is scoped in its readable statement to undocumented established diagnosis, not proof
of absent disease. Semantic citation precision and exhaustive precision/recall remain
**UNAVAILABLE**, rather than converting this purposeful review into an accuracy score.

No raw source/gold was edited. CONF-004's expectations exercise a capability the scoped
module did not implement; original strict failure is preserved rather than weakening
gold. Holdout material informing any later fix becomes development material for that
fix, requiring new independent confirmation.

## Actual resource accounting

Original ledger: `artifacts/claims-review/live-budget.json`.
Original trace root: the sibling `live-calls` directory. Existing six reservations
remain intact; this run adds calls **7-13**, two of which are runtime validation repairs.
Cumulative **13/20**, remaining **7**. No new ledger, reset or hidden sampling occurred.

Actual CLI usage: **119,822 input tokens**, **10,491 output tokens** across seven calls;
summed provider duration **116.455 seconds**, including repairs. These are CLI-reported
whole-request totals, not document character counts. Actual subscription cost is
**unknown**; no estimated price substitutes for billed cost. Baseline regression was
freshly run once: **303 passed, 4.61 seconds**, unedited log retained. Post-integrity
regression: **314 passed, 5.20 seconds**, eleven new independent mechanism checks.

## Integrity hypothesis: reproduced and bounded fix

In a separate copy of the original retrieval JSON, an observation value was changed
from 5.9 to 95.9 and the self-contained case digest recomputed. The frozen run path
accepted it and emitted the changed result with the retained original locator. An
internal checksum detects accidental edits only when not recomputed; it does not
attest to original archive bytes. The genuine snapshot was never changed.

New optional mode:

```sh
python -m clinical_intelligence.claims_review run --retrieval artifacts/raw-source/retrieval.json --verify-archive artifacts/raw-source/original.zip --output artifacts/raw-source/verified-review.json
```

Before any provider setup, it reopens the supplied ZIP and verifies archive identity,
used member SHA/size/row count, every supplied clinical source's original data-record
number, physical line span, row digest, field strings, patient/encounter, source role
and printed event date. All **60** authentic supplied records passed. Tampered content,
wrong patient/encounter/date, member/row/line mismatches and missing/wrong archives fail.
The non-editable wheel accepted the genuine case and rejected the recomputed-digest
tamper with PYTHONPATH absent and cwd outside the source checkout.

Without the option, lightweight replay remains possible, explicitly labelled **original
archive not reverified**. Verified mode does not silently fall back when ZIP is missing.
Its attestation excludes availability/event-link annotations, official-origin signatures,
retrieval completeness, auxiliary claim semantics and clinical meaning. An operator
must select a trusted original file. The fixed corpus hash provides reproducible identity,
not a CMS/source authenticity certification. This fix makes no new clinical-quality
claim and does not rewrite the sealed confirmation outputs.

## Two honest demo tracks, 60-90 seconds

**0-15 s:** Show the constructed raw target and official CSV archive identity. Explain
that retrieval, language facts, rules and evidence tracing are separate layers.

**15-35 s:** Run archive retrieval and verified review. Show nineteen original prior
HbA1c result records versus the previous curated five. The October constructed target
lacks performance, purpose and intent sources; all four findings remain insufficient.
This authentic CSV track uses zero Luna calls and does not assert complete EHR history.

**35-55 s:** Switch explicitly to the unrelated, already public synthetic DEV-002
patient. Render its previously measured final-note-v2 live packet. Show the actual
implemented-change citation and target-specific intent. This is rendering a historical
real-call result (call 6), not a new call or an original full clinical note. Do not join
it to the CSV patient. A fresh run requires the same ledger and would consume quota.

**55-75 s:** Show the new reserved result table: 3/6 automatic conformance and 16/24
criterion states, with lexical validation, missing-date gating and amendment gaps.
Show that original predictions precede expected decoding and failures were not rerun.

**75-90 s:** Show the tamper test: recomputed JSON digest passed the old path; optional
original-byte verification now rejects it. Finish with the policy draft, synthetic-only
and semantic-review limits. SUPPORTED is one evidence criterion, never claim approval.

The bounded Coherent search remains historical: 143 complete inline notes from two
bundles, no qualifying monitoring note; no further exploration or download. Policy
registry remains draft_ai_reviewed with human/clinical review false. Screening/diagnosis
scope abstention is not Medicare denial; three-calendar-month arithmetic is not the
full CMS medical-necessity policy.

## Reproduction, local index and recommendation

Use the original supplied confirmation ZIP and an isolated checkout of **814b1f8**
for frozen inference. Verify the ZIP and twelve manifest hashes before decoding inputs;
extract only inputs, save fresh outputs in an unused directory, and run ascending IDs
with the original explicit ledger/trace paths. Keep expected closed until predictions
and trace hashes are sealed. The six original outputs are local immutable records;
fresh generation reproduces the procedure, not identical answers.

```powershell
$ledger='artifacts/claims-review/live-budget.json'
$traces='artifacts/claims-review/live-calls'
# Run only after freeze/hash checks, with expected still closed and a fresh output directory.
foreach ($id in 1..6) {
  $name='CONF-{0:D3}' -f $id
  python -m clinical_intelligence.claims_review run --case "PRIVATE_INPUTS/$name.json" --mode live --model gpt-6-luna --reasoning high --ledger $ledger --trace-directory $traces --output "FRESH_PREDICTIONS/$name.json"
}
# After all predictions have been sealed, evaluate original expectations separately.
python tools/evaluate_claims_confirmation.py --inputs PRIVATE_INPUTS --predictions FRESH_PREDICTIONS --expected PRIVATE_EXPECTED --output artifacts/confirmation/evaluation.json
python -m pytest -q
```

Do not execute this loop to rerun the existing holdout for a better score. Seven
reservations remain and all attempts count; a repeat is a separate measurement.
The [machine summary](confirmation-validation.json) indexes private freeze, seal,
predictions, evaluation, assertion audit, tamper checks and installed verification.
Full sources/expected, raw responses, archives and expanded logs remain ignored.
Rollback uses frozen 814b1f8 in a separate worktree; do not reset or erase history.

**Recommendation:** ready for engineering outreach as a bounded provenance/uncertainty
prototype with disclosed failures, not a reliable complete medical-necessity review.
Material next-stage blockers are the lexical synonym guard, missing-date policy gating
and explicit HbA1c specimen-date amendment handling. Address them only in a separately
scoped task with new independent confirmation; no prompt search is recommended here.
