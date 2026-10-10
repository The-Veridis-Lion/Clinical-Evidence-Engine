# Original-source retrieval delivery

This phase closes the preselected-source limitation. It does **not** establish
independent clinical or final-prompt accuracy. Baseline was the clean main commit
`962342103a5387188bcda7a86029014fc8c7c778`; code, contracts, tests and evaluators froze
at `814b1f81e8a2a174088598549c770e31ab9d6ba6` before confirmation discovery.
The delivery commit adds documentation and compact results only. No push/merge was
performed. Historical artifacts and the persistent call ledger were preserved.

## What existed and what changed

The baseline already had nullable note extraction, strict source identity, deterministic
structured facts, four scoped criteria, event-conflict handling and JSON/Markdown.
Its preparation function could filter CaseInput.sources but could not discover them
from a longitudinal archive. New retrieval streams the complete original relevant
CSV tables into that existing preparation/review path. No prompt, reasoning, note
schema, clinical partition, reconciliation or criterion rules were retuned.

New functionality: bounded official download; immutable archive/member/row hashes;
patient/code/window retrieval; per-row exclusion reasons; separate auxiliary claims;
explicit export receipt; retrieval JSON input to review; concise Markdown rendering;
fixed original-row benchmark and source-ownership citation audit. Both source and
non-editable installed CLI paths were executed. Pinned dependencies are unchanged.

## Actual dataset and measurements

The official [Synthea download](https://synthetichealth.github.io/downloads.html)
was fetched at 2026-10-09T04:37:06.928880Z. SHA-256:
`d61417b551e5b0997c33851b339c157421751f0ea68c18ea686ceb1850907c35`.
5,960,866 compressed bytes, 18 CSV members, 201,657 data rows. The new download
happened to match the earlier manifest; its identity was freshly verified, not assumed.
Member hashes/counts are in the [compact manifest](../examples/claims_review/raw/archive-manifest.json).
Latest may change; the benchmark refuses a changed archive.

| Executed measurement | Result | Interpretation |
|---|---|---|
| Baseline offline suite | 290 passed / 4.17 s | Fresh execution this phase |
| Frozen feature offline suite | 303 passed / 3.74 s | 13 new mechanism checks; zero live calls |
| Original full-history task | 19/19 critical rows; 60/60 scoped candidates; 1.363 s | One patient; 41 ancillary context rows |
| Original 2023+ task | 5/5 critical rows; 15/15 scoped candidates; 1.453 s | Overlaps full-history task |
| Original 2025+ task | 2/2 critical rows; 7/7 scoped candidates; 1.415 s | Overlaps the same patient/history |
| Aggregate retrieval | 26/26 source-task pairs, 19 unique critical rows | Not 26 independent tests/patients |
| Candidate retrieval errors | 0 misses, 0 false-positive rows, 0 wrong-patient rows | Relative to fixed finite-scope oracle |
| Date/availability/counting violations | 0 observed in the three tasks | Linkage conservatively remains unknown |
| Full task auxiliary claims | 63 separate encounter-associated rows | Burden retained locally; none verified as HbA1c billing or counted tests |
| Final packet audit | 1,644 citation occurrences, 0 positional/binding failures | Repeated field references; **not** semantic precision |
| Fresh saved-response replay | 5/5 development conformance | Old model answers, current rules; zero new inference |
| Non-editable wheel CLI | 5/5 command checks | Source-checkout cwd and PYTHONPATH absent |
| Independent confirmation | NOT AVAILABLE / NOT RUN, 0/6 executed | Six input and six expected files absent |
| New Luna calls / tokens | 0 / 0 | Existing ledger remains 6/20, 14 available |

The original-row oracle was an non-independent direct CSV inventory before runtime
retrieval; fixed source IDs and independently read CSV references define context.
It is not human gold. Original tasks test patient isolation, irrelevant code/window
exclusion, ambiguous linkage and absent target performance. Original availability is
unknown; a separate executed no-receipt retrieval preserves that uncertainty. Explicit
duplicate links, later availability, conflicting dates and malformed dates are covered
by **offline injected synthetic fixtures**, not falsely described as naturally labelled
events in this corpus. The archive is fully scanned; unsupported tables are counted
and hashed, not declared clinically relevant. This is a finite-scope prototype.

All four raw-source criteria remain INSUFFICIENT_EVIDENCE and overall
NEEDS_HUMAN_REVIEW. Latest result: 2026-04-14. Constructed request: 2026-10-05.
There is no source establishing target performance, purpose, provider intent or a
signed order. Nineteen observation records are not nineteen independently proved test
events. A downloaded archive is not a complete real clinical record.

## Citation meaning and error attribution

[The assertion review](raw-source-semantic-review.md) examines critical source meanings
individually. It is non-independent and separate from position checks. Independent semantic
citation precision, exhaustive clinical fact precision/recall, false-certainty rate and
unnecessary-unknown rate are **UNAVAILABLE** without independent semantic labels.
Zero SUPPORTED findings in this missing-source example is not an accuracy score.

An actual source-coverage gap is observable: the prior published slice held five
2023-2026 results; original-source discovery adds fourteen earlier results. That is a
retrieval gain, not a Luna improvement. The final review still exposes missing target
documentation. A separate historical DEV-002 rule defect rejected a planned rationale
despite a dated actual medication change; current-rule replay again passes it. This is
an existing program-fix regression result, not a new final-prompt measurement.

## Independent confirmation and full-text feasibility

After freeze, only the main preparation confirmation index was opened. Its six
input/expected paths do not exist in the local extraction or ZIP members. No separate
confirmation package was found in the relevant supplied-file locations; a requested
path was not provided. No confirmation text/expectation was opened, generated or
replaced with development fixtures. The final prompt is still freshly demonstrated
only on the previously reported DEV-002 targeted call, not the other four development
cases. Independent final-prompt confirmation is **NOT VERIFIED**.

[Coherent](https://registry.opendata.aws/synthea-coherent-data/) permits CC BY 4.0 use
and offers individually accessible FHIR bundles. Its full ZIP is about 9.23 GB and was
not downloaded. Bounded discovery downloaded two original bundles (1,328,697 and
3,082,774 bytes), decoded/keyword-screened 35 + 108 complete inline notes, and inspected
selected texts and patient/encounter references. No HbA1c note was found; second-bundle
keyword hits described old prediabetes, not applicable monitoring evidence. This is
not a corpus-wide absence claim. No unrelated patient was joined to the CSV claim;
no note was shortened, rewritten or sent to Luna. Full-text pilot: **NOT VERIFIED**.

## Reproduce and retain

Use [the README commands](../README.md#original-archive-evidence-demo), the fixed target
query, benchmark and citation audit. The [machine summary](raw-source-validation.json)
indexes local full JSON, command logs, expanded exclusions, replay and installed checks.
Full archives, expanded outputs, private raw responses and earlier trials remain ignored.
Git contains only implementation, tests, synthetic request, compact manifest/summary and
the concise packet. Failed prototype work was not committed. One installation attempt
failed due to sandbox temporary-directory permissions; workspace TEMP/TMP resolved it
without a runtime code change. Both the failure and successful install are disclosed.

Limits: finite vocabulary (including one independently unverified procedure selector),
medication-start-window scope, one evaluated CSV patient, day-level timestamps, uncertain
event linkage, unknown EHR availability, missing physician notes, no general FHIR import,
no unseen final-prompt confirmation, no human/expert policy/semantic review. No payer
expansion, autonomous decision, production accuracy or compliance certification.

Rollback: use baseline `9623421` in a separate worktree; do not reset this branch or
delete historical records. Frozen code is `814b1f8`; documentation-only delivery follows
it. Continuing confirmation must reuse the original absolute ledger path, not its
default relative path in a new checkout. There is no extraction-cache reuse in this
measurement. Stop here until genuine confirmation materials are available.
