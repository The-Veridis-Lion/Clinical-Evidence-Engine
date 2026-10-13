# CareFlow acceptance v2 — actual results

2026-10-13 11:54 UTC. Full regression: **755 passed, 0 failed, 0 skipped**,
8.67 seconds. [JUnit](regression-reviewable.xml). This includes 465 original
tests, 45 byte-identically reused dialogue tests and 245 CareFlow tests.
Historical v1 evidence remains in the parent directory; it was not overwritten.

The [material development score](material-development.json) covers 312 constructed
scenarios from three existing Synthea development patients, 2,028 checks:

| State | Support | TP | FP | FN | F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SUPPORTED | 1236 | 1236 | 0 | 0 | 1.0 |
| NOT_SUPPORTED | 24 | 24 | 0 | 0 | 1.0 |
| INSUFFICIENT_EVIDENCE | 156 | 156 | 0 | 0 | 1.0 |
| CONFLICTED | 48 | 48 | 0 | 0 | 1.0 |
| NOT_APPLICABLE | 564 | 564 | 0 | 0 | 1.0 |

Macro-F1 100%; serious missing/conflict -> Ready errors0; overall errors0;
source references2076/2076; rule references2340/2340. Explicit versioned oracles
were frozen before candidate execution. The 26 mechanisms span both request types,
source forms and trigger/amendment conditions. Another three patients/312 scenarios
are reserved; **final holdout has not run**. A development score is not acceptance,
clinical accuracy, insurance approval or 312 independent clinical encounters.

Public source corpora are separately frozen: ACN200 development groups and200
holdout groups, ACI47/20. Prior ACI exposure is development-only. Raw corpus hashes,
reference hashes and duplicate case grouping appear in the committed manifests.
Only the fixed first ACN development group was newly extracted:2 Luna/high calls,
2 successful first attempts,0 failures/retries,56 note facts and32 dialogue facts.
[Extraction receipt](acn-extraction-pilot.json). No Sol provider review or research
call occurred. Mechanical validity is not source-checked semantic correctness.

[ACI reuse](aci-context-reuse.json) replays10 old encounters/469 original facts into
20 constructed requests. [ACN replay](acn-context-replay.json) preserves88 facts
in two requests, with source bundle/rule checks and persistent audit passing.
Both modalities are bound to their original sources. Context alone keeps requests
NEEDS_EVIDENCE. Replay makes0 new calls. These receipts predate the later additive
execution-scope annotation; stored historical packets remain immutable.

[Original reference inventory](original-reference-inventory.json) retains all1500
ACN raw labels.1128 strict-JSON labels are readable;372 errors remain in the original
reference record. A permissive control-character diagnostic reads354 more, leaves18
unparsed, and is explicitly unused for scoring. No old label, manifest or denominator
was replaced. Source-checked extraction Precision/Recall are **not measured**.
The generated summaries and old advanced-AI findings are not medical gold.

Fixed failures are retained: [cache/context before](cache-reference-before.xml)
10 failed/22 passed; intermediate strict-date reconstruction6 failed/31 passed
in [intermediate](cache-reference-after.xml); final37 passed in
[after](cache-reference-final.xml). Multiple fact pairing and stale comparison
credit measured2 failed/12 passed in [before](review-association-before.xml), then
20 related tests passed in [after](review-association-final.xml). No failure-specific
patient/document/phrase branch was added. Existing expectations stayed fixed.

Run with the pinned Python3.12/Pydantic2.13.5/pytest9.1.1 environment:

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory -Force .work/test-temp | Out-Null
$env:TEMP = (Resolve-Path .work/test-temp).Path
$env:TMP = $env:TEMP
python -m pytest -q --basetemp=.work/fresh-regression --junitxml=artifacts/fresh-regression.xml
```

Actual loopback HTTP tests require local networking permission in this sandbox.
They passed without skipping or replacing the calls with mocks. Future candidate
freeze must pin implementation and references before the one-use holdout. Current
work is recoverable, but the complete v2 acceptance contract is **not yet achieved**.
