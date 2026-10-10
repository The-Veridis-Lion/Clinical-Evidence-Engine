# Portfolio Summary

## Project Description

Built a Python evidence-review backend that retrieves original synthetic clinical
records, extracts typed nullable facts with GPT-6 Luna, and produces cited JSON/
Markdown packets through deterministic reconciliation and scoped policy checks.
The prototype preserves unknowns and conflicts while keeping clinical evidence
separate from policy evaluability and payment decisions.

## Resume Bullets

- Implemented patient/code/date retrieval over an original 201,657-row Synthea
  snapshot, preserving row/field provenance and matching 26/26 expected
  source-task pairs across three overlapping windows for one patient.
- Integrated typed GPT-6 Luna extraction, explicit source grounding, bounded
  repair, and Prompt B defaults across CLI/Python interfaces; measured $0.00301
  Standard API-equivalent cost per run on 24 synthetic-note workflows.
- Built deterministic field-scoped reconciliation and evidence packets, verified
  389 offline tests for release, and rejected an extra audit layer after it
  suppressed valid facts and reduced criterion conformance.

## Recruiter Explanation: 30 Seconds

This project shows how I build inspectable AI backends for healthcare evidence.
The model extracts facts, while Python retrieves records, reconciles corrections,
and applies limited policy checks. Every result points back to a source, and
unknown or conflicting evidence stays visible. The portfolio includes runnable
synthetic demos, measured cost, tests, and documented failures—not a claim of
clinical deployment or autonomous insurance approval.

## Technical Explanation: 60 Seconds

The entry point accepts a constructed claim and an original synthetic archive.
Retrieval narrows patient, code, and temporal scope without rewriting CSV values.
Structured facts are parsed deterministically; selected notes use nullable typed
Luna assertions and exact source spans. Reconciliation applies only explicit,
field-scoped relationships and preserves competing facts. Policy prerequisites
separate supported clinical evidence from whether a criterion is evaluable.

The final JSON/Markdown packet exposes citations, gaps, conflicts, and versioned
provenance. Original Prompt B is the normal research default; A is explicit
fallback. A separate scope audit was excluded because it removed true conflicts
and lowered criterion matches. The release passed 389 offline tests and makes
no new model calls; historical synthetic B runs cost about $0.00301 each at
Standard API-equivalent rates. I can explain failures at retrieval, proposal,
validation, repair, reconciliation, and rule evaluation rather than hiding them
behind a single accuracy number.

## Cold Outreach

I built a traceable Python/GPT-6 Luna clinical-evidence prototype with original-
archive retrieval, deterministic reconciliation, 389 offline tests, and a
reproducible synthetic-note cost benchmark; I would welcome feedback from your
healthcare AI/backend engineering team.

## 60–90 Second Demo

1. Show the [README results](../README.md) and distinguish synthetic evidence
   from clinical validation.
2. Run the documented structured-only review and render commands: zero model
   calls and no credentials. Open the packet's missing-evidence section.
3. Show an original-row locator and hash in the [archive example packet](../examples/claims_review/raw/review-summary.md).
4. Show [typed extraction and architecture](engineering-case-study.md): selected
   notes use B; structured sources and calculations stay deterministic.
5. Run the therapy demo and show the preserved 108/120-minute alternatives.
6. Close with the measured workload, explicit limitations, and why the failed
   Scope Audit remains outside the release.
