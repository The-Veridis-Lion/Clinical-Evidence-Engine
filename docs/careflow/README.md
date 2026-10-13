# CareFlow Readiness Engine

Runnable Referral and Prior Authorization **documentation readiness** backend.
Requests are independent of medical bills. Versioned deterministic checklists
produce the same source-linked JSON packet and Markdown report for human and
advanced-AI reviewers. SQLite retains original sources, every case revision,
reviewer opinions, correction reasons and a verifiable audit chain.

This branch is `feature/careflow-readiness`, based on unmerged
[PR #3](https://github.com/The-Veridis-Lion/Clinical-Evidence-Engine/pull/3),
shared repair head `90adea7`. Its `claims_engine` is an explicit dependency. The two
shared safety fixes were isolated and integrated; prompts, policy, historical
scores and Copilot files remain unchanged. Current mapping and evaluation status is in
[the v3 checkpoint](completion-v3/README.md). Integration boundaries are recorded in
[the maintained project contract](../CAREFLOW_READINESS_ENGINE.md).

## Run without a model or network

Python 3.12+ and the existing repository dependencies are sufficient. From this
checkout, activate an existing project environment or use the root README's
pinned installation instructions. No new runtime dependency is needed.

```powershell
$env:PYTHONPATH = 'src'
python -m clinical_intelligence.careflow --db artifacts/my-demo.sqlite demo --output artifacts/my-demo
python -m clinical_intelligence.careflow --db artifacts/my-demo.sqlite packet --case-id CF-REF-001
python -m clinical_intelligence.careflow --db artifacts/my-demo.sqlite report --case-id CF-REF-001
python -m clinical_intelligence.careflow --db artifacts/my-demo.sqlite audit --case-id CF-REF-001
```

Use a fresh database and output directory for each demo. The command runs both
Referral and PA: a missing clinical summary yields `NEEDS_EVIDENCE`; receiving
a new request-specific summary yields `DOCUMENTATION_READY` at revision 2.
No real reviewer or model is called: example reviewer opinions are **constructed
intake fixtures**, not actual human sign-offs. Readiness does not require anyone
to sign each check. Original revision 1 remains available.

Committed reproducible inputs and outputs are in [examples/careflow](../../examples/careflow/).
For a stepwise workflow, use a fresh DB:

```powershell
python -m clinical_intelligence.careflow --db artifacts/stepwise.sqlite create --case examples/careflow/referral-case.json
python -m clinical_intelligence.careflow --db artifacts/stepwise.sqlite add-evidence --case-id CF-REF-001 --input examples/careflow/referral-update.json
python -m clinical_intelligence.careflow --db artifacts/stepwise.sqlite packet --case-id CF-REF-001 --revision 1
python -m clinical_intelligence.careflow --db artifacts/stepwise.sqlite reviews --case-id CF-REF-001
```

Packet hashes are deterministic for a case/revision; audit UTC timestamps vary
on replay. Existing case IDs cannot be overwritten. `rules` exports the pinned
rule registry; `review --input FILE` records a human or AI opinion without
changing any deterministic check. All CLI failures return nonzero.

## Local HTTP API

```powershell
python -m clinical_intelligence.careflow --db artifacts/api.sqlite serve --port 8765
```

The default address is `127.0.0.1`. This is a local synthetic-data prototype,
without production authentication, access controls, TLS or clinical validation.
Do not expose it as a real-patient service.

| Method | Route | Result |
| --- | --- | --- |
| GET | `/health` | Runtime health |
| GET | `/v1/rules` | Versioned rule sets and content hashes |
| GET | `/v1/schemas` | Strict JSON schemas for case, review and update |
| POST | `/v1/cases` | Create independent Referral/PA case and revision 1 |
| GET | `/v1/cases/{id}?revision=1` | Current or immutable historical JSON packet |
| GET | `/v1/cases/{id}/report` | Consistent Markdown report and separate opinions |
| POST | `/v1/cases/{id}/reviews` | Record human/AI review of a specific packet |
| POST | `/v1/cases/{id}/evidence` | Append new sources/facts, record review and recompute |
| POST | `/v1/cases/{id}/corrections` | Same update contract, requiring an amendment |
| GET | `/v1/cases/{id}/reviews` | Opinions with server UTC timestamps |
| GET | `/v1/cases/{id}/audit` | Verify event chain and all revision/packet hashes |
| GET | `/v1/cases/{id}/review-input` | Optional external reviewer packet and response schema |
| GET | `/v1/cases/{id}/model-calls` | Actual product-review attempts/failures; research stays zero |

URL-encode case IDs. Mutation bodies require `Content-Type: application/json`,
positive `Content-Length`, and at most 2 MB. Schema violations return 422,
unsupported rules/invalid evidence return 400, stale revisions or duplicate cases
return 409, and unknown cases/revisions return 404. Rules cannot be submitted or
overridden through a review or update.

For example, while the server runs:

```powershell
$case = Get-Content examples/careflow/referral-case.json -Raw
Invoke-RestMethod http://127.0.0.1:8765/v1/cases -Method Post -ContentType application/json -Body $case
$update = Get-Content examples/careflow/referral-update.json -Raw
Invoke-RestMethod http://127.0.0.1:8765/v1/cases/CF-REF-001/evidence -Method Post -ContentType application/json -Body $update
Invoke-RestMethod http://127.0.0.1:8765/v1/cases/CF-REF-001/audit
```

## Evidence and rules

The engine reuses `SourceInput`, `Citation`, `CriterionResult`, canonical digest,
source hashes, Unicode line anchors, JSON pointers and the existing field-scoped
`claims_review.relationships.reconcile`. It does not reimplement retrieval,
claim indexing or the specialized HbA1c/CMS criteria.

Each supplied fact declares patient, request, service code/system, requirement,
true/false/null assertion, original-source references and interpretation origin.
References are exact original fields or Unicode line anchors. Cross-patient,
request, service or encounter evidence is excluded; unknown/late availability,
future actual events and invalid locators cannot fill gaps. Future **orders**
are allowed for requests whose service has not yet occurred. Every excluded fact,
grounding error and unreferenced supplied source remains visible.

`SUPPORTED` requires traceable support. Explicit contradiction yields
`NOT_SUPPORTED`; missing or unknown yields `INSUFFICIENT_EVIDENCE`.
Contradictions or unresolved amendment authority yield `CONFLICTED`.
`NOT_APPLICABLE` requires a source-supported false condition, never an unknown
trigger. Any unresolved request-scoped assertion conflict prevents overall Ready,
even if a checklist item is inapplicable. Older copies never choose a winner.

Both version `1.0.0` checklists require provider intent, service reason and a
clinical summary. Investigation results and prior therapy documents are
conditional on explicit, source-backed request requirements. Referral also
requires a destination; PA requires its form and supplied payer/request identifiers.
Payer context is documentation, not eligibility verification. These are
**synthetic project requirements**, with no claim of insurer-policy authority.
The specialized engine's `policy_refs` remain separate; these checks do not
fabricate official policy citations. An unknown ruleset/version fails explicitly.

## Reviews and corrections

Review JSON identifies `reviewer_type` (`human` or `advanced_ai`), reviewer ID,
model/version for AI, basis revision and packet hash, fact IDs, judgment,
reason and proposed actions. Opinions remain separate from rule results.
Reviewers can disagree, identify missing evidence, propose corrections and
recommend escalation; they cannot set Ready or change rule definitions.

Updates require the current `expected_revision`, a review of that revision,
new immutable source/fact IDs and genuinely new source content. A relabelled old
document is not new evidence. Sources/facts are never overwritten. Concurrent
stale updates fail; saving the new revision, opinion and audit event is atomic.

An amended fact supplies `amends_fact_id` and a structured `authority_ref` into
the new corrective source. The corrective source explicitly declares
`amendment_authority_confirmed`, `amends_fact_id` and `amendment_scope: assertion`.
True asserted authority permits the existing reconciliation engine to derive a
corrected view; false/unknown or mismatched authority leaves the conflict visible.
This verifies an explicit declaration, **not signature authenticity**. The review
must name the old fact and explain the correction. All rules are recomputed and
all old facts/packets remain stored. See [the correction example](../../examples/careflow/correction-update.json).

```powershell
python -m clinical_intelligence.careflow --db artifacts/correction.sqlite create --case examples/careflow/correction-case.json
python -m clinical_intelligence.careflow --db artifacts/correction.sqlite add-evidence --case-id CF-CORRECTION-001 --input examples/careflow/correction-update.json
```

Its advanced-AI opinion is a constructed JSON fixture; no real model ran.

Optional programmatic AI review is available through
`CareFlow.risk_review(case_id, adapter, reviewer_id=..., model=..., model_version=...)`.
The adapter receives the complete packet and returns strict Review JSON.
Low-risk cases skip it. Conflicts, explicit contrary assertions, grounding failures
or corrections recommend a review. Every attempted adapter call is reserved in
the audit before dispatch; failures and unfinished reservations remain countable.
There is no implicit provider or mandatory model call. Snapshot packet execution
counts describe deterministic evaluation; `/model-calls` is authoritative for
subsequent optional product reviews. The demo/test callbacks do not call real AI.

## Existing Synthea context

```powershell
python -m clinical_intelligence.careflow --db artifacts/synthea-new.sqlite synthea-demo --archive PATH/TO/original.zip --split docs/general-claims/split.json --output artifacts/synthea-new
```

The hash-pinned existing archive is expected; substitute its actual path.
Only the first three **already frozen development patients** are indexed. Each
gets a constructed Referral and PA request, with clearly labelled constructed
supplementary documents. No holdout evaluation or prompt research is restarted.

`safe_index` bounds compressed bytes, every member and total decompressed size
before invoking PR #3's `ArchiveIndex` on an immutable temporary snapshot.
`retrieve_context` reuses its same-patient/encounter indexes and preserves raw CSV
fields, native IDs, record/physical line numbers and row/member/archive hashes.
CSV context creates zero documentary assertions. Exact original bytes are checked
again by the existing `verify_archive` through a legacy verification envelope;
saved CareFlow/PR #3 source IDs are preserved. This does not fix PR #3's own
unbounded CLI or its unassigned-claim split verifier.

To retrieve context for another explicitly constructed request:

```powershell
python -m clinical_intelligence.careflow retrieve --archive PATH/TO/original.zip --case REQUEST.json --received-at 2026-10-10 --output artifacts/context.json
```

Merge returned `sources` into the case before creation. They are labelled
`ENCOUNTER_CONTEXT_ONLY`; they cannot establish intent, missing notes or complete
history by themselves. No medical bill is converted into a PA request.

## Validation and limits

The historical v1 full run passed **637 tests**: 465 existing + 172 new. Tests cover
multiple patients, text/structured/Unicode/CRLF documents, Referral/PA, truth-state
and condition matrices, independent hand-written cases, corrections, concurrent
writes, rollback, restart, source tampering and actual local HTTP/CLI calls.
[Test report](TEST_REPORT.md) includes the failed-before result and limits;
[JUnit](test-results.xml) records the final run. No old expected answers or scoring
contracts were changed.

Exact quotations establish provenance, not the clinical truth of a supplied
assertion. Clinical extraction reuses the existing source-only Luna prompt, schema
and validator. Context preserves interpretation and provenance; documentation
assertions remain explicit, source-grounded inputs.
Insurer-specific policies, actual provider authenticity, real-patient validation,
production security and externally signed audit anchors remain future work.
Local hash chains detect ordinary inconsistency but are not tamper-proof against
an attacker who rewrites the entire database and all hashes.

Follow [AGENTS.md](../../AGENTS.md): reread the maintained direction document
before every autonomous round, solve generalizable problems, keep fixed tests,
validate across patients/documents/request types/conditions, and do not claim
clinical effectiveness from these synthetic software results. No auto-merge or deployment.

## Frozen evaluation and clinical source reuse

The maintained [acceptance contract](../CAREFLOW_READINESS_ENGINE.md) supersedes
arbitrary duration/five-round stops and mandatory human sign-off. Read it and
[actual progress](../CAREFLOW_PROGRESS.md) before each autonomous decision.
Version 2 reports are separate from historical v1 files in [evaluation-v2](evaluation-v2/).
The complete run currently passes 755 tests; source extraction Precision/Recall
and final holdout acceptance remain pending.

The unchanged ClinicalFact/dialogue packages were copied from a frozen existing
engine commit in a separate compatible addition; [the hash manifest](clinical-engine-compatibility.json)
records reuse. Optional `clinical_context` binds an original text source to an
existing `Extraction`. Quotes, offsets, supporting spans and source index
provenance are validated before persistence. Stable context fact IDs are reviewable
through the same HTTP interface. Context cannot automatically establish a PA form,
referral intent or documentary completeness.

Freeze by original case and duplicate content; raw labels stay in ignored artifacts.
ACN requires development/holdout >=200 groups. Old ACI cached encounters stay in
development. The current ACN prefix is not a random sample of all 30K records.
Public datasets have no PA approval/completeness gold.

```powershell
python -m clinical_intelligence.careflow.evaluation freeze-corpus --dataset acn --input ORIGINAL.jsonl --output artifacts/acn-frozen --development-groups 200 --holdout-groups 200
python -m clinical_intelligence.careflow.evaluation freeze-reference-inventory --source ORIGINAL.jsonl --frozen artifacts/acn-frozen --output artifacts/acn-original-references
```

The second command preserves malformed raw labels, strict parsed labels and hashes.
Its permissive JSON view is diagnostic only; it never substitutes repaired labels
for scoring or drops an invalid case.

Actual extraction uses the configured Codex provider, Luna/high, no reference input,
shared SQLite reservations and at most two mechanical or upstream retries. This
command makes product model calls, so run it deliberately:

```powershell
python -m clinical_intelligence.careflow extract-development --frozen artifacts/acn-frozen --groups 1 --ledger SHARED_CALLS.sqlite --output artifacts/acn-extraction
python -m clinical_intelligence.careflow --db artifacts/acn-product.sqlite replay-extraction --frozen artifacts/acn-frozen --extraction artifacts/acn-extraction --ledger SHARED_CALLS.sqlite --received-at 2026-10-13 --output artifacts/acn-product
```

Use the same ledger path in both projects. Participating callers have global cap50
and project cap25; until Copilot adopts it, accounting cannot cover its independent
calls. Successful first outputs are reused despite reference disagreements. Cache
replay reconstructs acceptance from original raw responses and immutable call
records; corruption fails without inference. Replay makes zero calls and constructs
both request types with missing paperwork visible. They are product fixtures,
not real insured cases.

To reproduce deterministic scoring with the pinned Synthea archive and split:

```powershell
python -m clinical_intelligence.careflow.evaluation material-demo-freeze --archive ORIGINAL.zip --split docs/general-claims/split.json --output artifacts/materials-frozen
python -m clinical_intelligence.careflow.evaluation run-materials --frozen artifacts/materials-frozen --partition development --output artifacts/materials-dev
```

The 26 fixed mechanisms cover five states, wrong scope, unavailable/ungrounded
evidence, future actual/order distinctions, amendment authority and trigger truth,
across both request types and text/structured sources. Six existing Synthea
development patients are split 3/3 for this new material corpus; they are not the
old claims benchmark's holdout. Expected results are declared before execution.
Development312 scenarios yield macro-F1 100%, serious false Ready0 and source/rule
mechanical validity100%; these are constructed software scenarios.

After final candidate freeze, `seal-candidate --frozen ROOT` followed by
`run-materials --partition holdout` permits the one-use final material test. Code
changes invalidate the seal. Never resample the final set or change references/
denominators to meet targets. Source-checked extraction metrics are separate;
advanced-AI silver findings are not medical ground truth.
