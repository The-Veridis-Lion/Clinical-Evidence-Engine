# Main preparation-package integration

## Scope and provenance

Baseline: `54553dd36095d4d2047f30d66747031a75ecafa5`. Actual local/remote main matched;
no successor was present. Work used independent branch feature/claims-review-preparation.
Old clinical_partition + nullable_v1 defaults, history and other workspaces remain unchanged.
Main package SHA-256: `4b82277e1f5f16cb547552167cb4a5238190dd5c021a72450e8806b4b538cc4e`;
all 51 manifest entries verified. Original preparation reports, manifest, ZIP and
PREPARED_NOT_EVALUATED remain historical local records. Confirmation input/expected
were not opened, used or published.

Selective integration adds an independent module, scoped JSON input, finite structured
mappings, limited note extraction, four criterion checks and JSON/Markdown snapshots.
Pydantic and concrete Codex structured_output are reused. Old therapy claims, reconciliation,
utilization, SQLite and old validators are not used. No dependencies changed and application
caching is disabled; input digests are not cache hits.

The registry remains exactly the supplied 0.1.0-draft-ai-20261008, draft_ai_reviewed,
human_review_completed=false, clinical_expert_review_completed=false. Its preparation-only
artifact description remains historical; packet execution records newly executed evaluation.
NCD, screening boundary and MLN official sources were checked without adding criteria.
Order patterns follow [MLN909221, May 2026, pages 2–3](https://www.cms.gov/files/document/mln909221-complying-documentation-requirements-lab-services.pdf).
The calendar boundary remains a declared project convention.

## Executed verification

See [machine-readable summary](claims-review-validation.json). Per-call prompts/schemas,
visible responses, usage, packets, failure records and cumulative ledger stay ignored
under artifacts/claims-review. No confirmation material appears there.

| Stage | Actual result | Meaning |
|---|---|---|
| Starting regressions | 238 passed | Actually rerun before modifications. |
| Migrated preparation | 20 passed | Patient, availability, window, Unicode, strict values and stale-output boundaries. |
| New integration tests | 32 passed | Five injected proposals plus behavior, calendar, partial unknown, identity, conflict, budget and failure propagation. |
| Final offline suite | 290 passed | No real provider/authentication. |
| Injected offline proposals | 5/5 packets conform | Zero model calls; not model accuracy. |
| Initial real Luna round | 4/5 packets; 19/20 criterion states | Five new combined note proposals, no repair. |
| Saved-response replay, rule v2 | 5/5 packets; 20/20 states | Same saved responses, zero new calls. |
| Targeted DEV-002 live check | 1/1 packet; 4/4 states | One new call with note v2, no repair. |
| Synthea | 8 rows/2 files verified; expected gaps | Zero calls; no invented target event. |
| Non-editable wheel | PASSED | Policy loading, prepare, structured-only Synthea and saved-packet Markdown from outside the repository, without source PYTHONPATH. |

Total actual calls: **6/20**; failures/timeouts/repairs: **0**. CLI 0.159.3 requested
gpt-6-luna/high, timeout 180 seconds, tools disabled/read-only. CLI-reported input tokens
104,339; output tokens 9,227; cached input tokens 0; summed provider latency about 90.75
seconds. These include CLI overhead, not just document tokens. Billed cost and precise
backend snapshot are unavailable. These correlated development/retest denominators are
not independent clinical accuracy measurements. The other four final-prompt cases were
replayed, not freshly called with note v2: **NOT VERIFIED** for final-prompt live coverage.

## Localized defect, source checks and residuals

Initial DEV-002 extracted actual adjustment 2026-08-10 and the reason for ordering the
2026-09-22 test. Its rationale assertion time was unknown. Rule v1 incorrectly required
actual/historical assertion time, confusing a reason with underlying implementation.
Facts survived; the criterion abstained. Rule v2 accepts that stated reason only with
a separately evidenced actual, dated change; removing the change still fails support.
Note v2 clarifies current versus historical disease, order-issued versus requested dates,
and reason assertion time. All five saved proposals replayed successfully, demonstrating
a code-fix benefit without attributing it to a new prompt. One new DEV-002 response
marked rationale planned/change actual and passed. Prompt causal benefit is not isolated.

Initial criterion false support: 0; unnecessary criterion abstention: 1, caused by
the rule defect. Conformance does not measure exhaustive field precision/recall.
non-independent source review found residual field issues: initial DEV-001 labeled current
diabetes historical and an order-issued date requested_test; initial DEV-003 omitted
fact_date despite storing the literal specimen date in target_date. Final DEV-002 purpose
target_date remained null despite an explicit date elsewhere in context; supplied
encounter/test binding still supported it. These are not claimed universally fixed.
No expected/gold was changed. Review was non-independent, not human or clinical review.

DEV-003 retains 7.1/date 2026-09-25 and 6.9/date null; the later order and future schedule
cannot resolve the review. Missing paperwork is unknown, not cancellation. DEV-004 retains
both 2026-05-20 and 2026-08-20 dates of one accession, with no latest-receipt winner.
DEV-005 remains screening/outside scope, not denial or an invented diabetes diagnosis/code.

## Synthea and limits

Published slice: five observation rows, three condition rows, provenance manifest and
explicitly constructed wrapper. Subset hashes, raw fields, patient/encounter, printed
dates and preserved locators were checked. Full original archive and original row hashes
were **NOT independently reverified**; their identities remain preparation provenance.
Original EHR availability stays unknown; export receipt is not original clinical access.

The 2026-10-05 request is constructed; latest actual observation is 2026-04-14. No target
test, clinician note, order, purpose or billing identity is fabricated. Four criteria
remain insufficient and overall NEEDS_HUMAN_REVIEW. This bounded slice is not full history.

Other limitations: finite vocabulary; day-level precision; unlinked identities; prose
mentions not promoted to counted independent events; signature/role ambiguities beyond
lexical checks; no general HbA1c correction engine or full policy/payer/credentials/billing
review. Positional validation does not certify semantic correctness. Affirmative contrary
rationale is a source-supported model judgment, not a formal semantic proof. Human/clinical
review, full historical applicability and six reserved confirmations are **NOT VERIFIED**.

## Reproduction, freeze and rollback

README lists installed module commands. Source-checkout tools/tests need PYTHONPATH=src;tools
on PowerShell (src:tools on POSIX), or an installed package plus tools for test helper imports.

```sh
python -m pytest -q
python tools/evaluate_claims_review.py --results artifacts/claims-review/live-round-01 --output artifacts/claims-review/live-round-01/evaluation.json
python tools/replay_claims_review.py --packets artifacts/claims-review/live-round-01 --traces artifacts/claims-review/live-calls --output artifacts/claims-review/replay-rules-02
python tools/evaluate_claims_review.py --results artifacts/claims-review/replay-rules-02 --output artifacts/claims-review/replay-rules-02/evaluation.json
python -m pip wheel --no-deps . --wheel-dir artifacts/claims-review/wheel
```

Replay requires retained local raw records, deliberately not redistributed. A fresh run
reproduces the procedure, not identical model answers. Each packet records input, actual
prompt/schema and runtime/rule/policy identities. The commit containing this report is the
frozen candidate (`git rev-parse HEAD`); local post-commit checkpoint records its full SHA.
The representative packet records the exact runtime of the targeted live check.
Git normalizes published text to LF; the summary retains both published-tree hashes
and actual measured-runtime hashes. Original subset CSV bytes are unchanged.
Rollback by checking out 54553dd in a separate worktree, not resetting this one or deleting
records. Integration is complete; independent confirmation is a separate next phase.
