# CareFlow validation report — 2026-10-13

Final full regression: **637 passed, 0 failed, 0 skipped** in 6.05 seconds.
465 pre-existing tests plus 172 new CareFlow tests; original expected answers,
historical scoring and datasets were unchanged. [JUnit](test-results.xml) and
[machine summary](validation-summary.json) record the actual results.

Run from the independent `feature/careflow-readiness` checkout, with Python
3.12, Pydantic 2.13.5 and pytest 9.1.1 in the existing pinned environment:

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory -Force .work/test-temp | Out-Null
$env:TEMP = (Resolve-Path .work/test-temp).Path
$env:TMP = $env:TEMP
python -m pytest -q --basetemp=.work/fresh-test-run --junitxml=artifacts/fresh-test-results.xml
```

HTTP tests make real `127.0.0.1` connections, with temporary servers shut down
after each test. This environment's sandbox initially blocked loopback with
WinError10013. The same tests passed with approved local networking; no test was
skipped or replaced with a mock to avoid the boundary.

| Coverage | New tests | Actual checks |
| --- | ---: | --- |
| Preparation/rules | 119 | Three patient identities, Unicode, text/structured evidence, both request types, five states, two conditional rules, patient/request/code/system/encounter isolation, source availability |
| Lifecycle | 32 | Human/AI opinions remain separate, model identity, cited basis, correction authority true/false/null, old snapshots, no evidence reuse, two concurrent writes, rollback injection, append-only DB, restart, tamper detection, risk callbacks/failures, future orders versus actual events, invalid locators |
| HTTP/CLI/report | 5 | Actual create→review→new evidence→recompute→history→audit flows for two different patients/request types; invalid overrides, schema errors, body limit, Unicode offsets, literal evidence rendering, persisted CLI demo |
| Original archive adapter | 8 | Two patient/encounter/request contexts, exact original field/hash preservation, existing independent byte verifier, changed-field rejection, unknown/mismatched identity, missing encounter, compressed/member/total limits including non-CSV |
| Independent generalization | 8 | Hand-written fixtures independent of demo generator; mixed triggers/results, CRLF offsets, order invariance, two patients and both request types, relabelled retransmissions, conflicts preserved when a criterion is inapplicable |

The parameter matrix validates reusable software conditions; it is not 172
independent clinical encounters, a clinical accuracy score or a population estimate.
Supplied assertion semantics and source authority are not independently certified.

## Fixed before/after regressions

An independent hand-written suite exposed two real issues: previously received
content under a new source ID could count as new material; source disagreements
could disappear from the conflict summary when their requirement was inapplicable.
The fixed suite measured **6 failed / 2 passed → 8 passed**. Generic content
identity checks and full request-scoped conflict retention fixed both; no patient,
case, document ID or fixture phrase appears in the decision logic.

The first full run measured **636 passed / 1 failed**. The oversized-body HTTP
client could receive a Windows TCP reset instead of 413 because the server closed
with unread body bytes. A bounded drain of rejected bodies fixed the actual
protocol behavior. The unchanged full suite then passed 637/637.
[The failed-before JUnit](test-results-before-http.xml) is preserved.
Earlier module-collection and pytest/temp-directory errors are recorded in the
[direction log](../CAREFLOW_READINESS_ENGINE.md); they are not counted as clinical
or business-oracle measurements.

## Actual original-data workflow

[Synthea receipt](synthea-validation.json) records the existing hash-pinned ZIP
`d61417b551e5b0997c33851b339c157421751f0ea68c18ea686ceb1850907c35`.
Only three patients from PR #3's already frozen **development partition** were
selected, producing six constructed requests: Referral and PA for each patient.
The selected encounters contained **4, 60 and 3 unique native sources** respectively
(67 unique rows, reused across the two request types).

All six workflows persisted a missing-summary packet, accepted an explicitly
constructed new summary, recomputed Ready, retained the original revision and
verified their audit. The existing original-byte verifier rechecked fields,
patient/encounter identity, printed dates, physical line spans and row/member/archive
hashes. Native CSV context generated **zero documentary assertions**. Readiness
was achieved using constructed supplementary documentation, not inferred from
bills or observations. This is a preservation/lifecycle demonstration, not
clinical correctness, retrieval completeness or policy accuracy measurement.

Holdout/reserve source content was not used for CareFlow development or evaluation.
The historical split and completed holdout receipt were not modified or rerun.
Research model calls and actual product model calls: **0**. The optional-review
tests use offline callbacks; synthetic reservations/failures are tested in their
temporary databases and do not imply actual provider calls.

## Reuse and limitations

[Shared integrity receipt](shared-integrity.json) records hashes of all existing
tracked source/test files and checks that none was modified relative to PR #3
head `f91768e`. The unchanged 465-test suite passed along with CareFlow.
Source identity, citations, byte verification and amendment reconciliation reuse
the existing engine. Request checklists are new and explicitly synthetic.

PR #3 is still an unmerged dependency with two unresolved P2 findings. CareFlow
guards its own archive entry point and avoids that PR's split verifier; it does
not claim to fix those shared paths. No automatic merge, deployment, insurer
approval, eligibility determination or compliance certification occurred.

Remaining validation needs: real-world documentation policies, clinical semantic
review, provider/signature authenticity, production authentication/authorization,
externally anchored audit integrity, and real-patient performance. These results
support the tested software contracts, not those future claims.
