# Original-source retrieval contract, version 0.1

Baseline: `962342103a5387188bcda7a86029014fc8c7c778`. The clinical partition,
nullable_v1 and specialized `claims-review-note/2` contract are unchanged.
Retrieval: `claims-review-retrieval/0.1`; benchmark: `retrieval-benchmark/1`;
packet audit: `claims-packet-audit/1`. Existing rules remain version 2.

## Scope and provenance

`RetrievalQuery` supplies a constructed target and date-level review window, never
preselected sources. Retrieval scans the complete official ZIP and preserves all
CSV strings. The clinical discovery vocabulary is deliberately finite: observation
4548-4; diabetes conditions 44054006/46635009; metformin 860975; procedure 43396009.
This is neither a comprehensive medication/diabetes vocabulary nor a billing crosswalk.
The procedure selector has no matching row for the measured patient and is **NOT
VERIFIED** against an independent terminology release. Its records are raw context;
this phase does not promote native procedure rows to proved independent tests.

Relevant tables are observations, conditions, medications, procedures, encounters
and associated claims. Every excluded row in those tables has its source ID, original
locator and reason in the local retrieval JSON. Tables outside that declared scope
have member-level exclusion roles and row counts, rather than millions of individual
clinical exclusion objects. All archive members are hashed and counted. This is
full-table discovery within an explicit scope, not unrestricted retrieval of all
medical information. Empty discovery is permitted.

CSV data-record numbers are one-based, excluding the header. Physical line spans
include multiline records. Row hashes cover original bytes and line endings; field
citations retain column names. File and archive hashes identify the complete original
files, not rewritten slices. Unsupported/malformed archives fail explicitly.

Same-patient clinical codes are discovered first; encounter context is resolved by
explicit references. The existing preparation layer applies the inclusive temporal
boundary. Historical diabetes background may precede the requested test window;
medications must start within that window. This finite rule does not discover an
older prescription continuing into the window, nor prove current disease activity.
Associated claims are separate auxiliary records, never clinical candidates or
verified HbA1c billing claims. Their broader date scope is explicit; the benchmark
reports their burden separately from candidate false positives.

## Dates, availability and linkage

Event dates use the printed CSV date component, without timezone conversion. Invalid
or missing event dates remain null. Original raw values survive. Receipt, export
download, review and event dates are separate roles. Original EHR availability is
always unknown unless separately evidenced; an export does not prove clinical access
or history completeness. `--snapshot-available-at` explicitly declares the downloaded
snapshot's receipt for this retrospective demo. Without it, availability is unknown
and sources cannot support an as-of conclusion.

Optional per-row metadata may supply availability or an event link only with matching
patient identity and an explicit evidence description. It annotates scope, never edits
CSV values. Such descriptions are traceable declarations, not machine-certified
semantic truth. Unknown/late availability cannot enter groups. Available members of
an explicit group retain competing dates even when one lies outside the window.

Equal dates/encounters/values do not establish duplicate events. Unlinked observations
retain uncertain event counts. Observations, procedures and claims are not summed as
independent tests. A constructed request establishes neither performance, purpose,
implementation, authentication nor provider intent. Unknown is neither false nor zero.
Missing clinician sources produce INSUFFICIENT_EVIDENCE, not fabricated notes.

## Evaluation and freeze

The original-row oracle was an non-independent direct CSV inventory made before runtime
retrieval, not copied from its output. Fixed clinical row IDs and a separate original
CSV join determine expected encounter context. Three overlapping windows for one
patient measure retrieval, not independent clinical accuracy. Synthetic mechanism
fixtures separately cover unknown/late availability, explicit duplicate links,
conflicting dates, malformed dates and absent target performance. They do not prove
that these phenomena are natively annotated in the downloaded corpus.

The packet audit checks positions, source identity/hash, availability, pointer source
ownership, declared policy locators and execution errors. It does not infer semantic
support, exhaustive fact recall, unnecessary unknowns or clinical correctness. A
separate non-independent assertion review records meaning and scope; no human or expert
review is claimed. Independent semantic citation precision remains unavailable.

Freeze code, contracts, tests and evaluators before opening confirmation inputs or
expectations. Do not retune or selectively rerun failures. Use the existing persistent
20-call ledger for any later confirmation; do not create a replacement ledger. The
CLI's default relative ledger is appropriate only for a new project run. Continuing
this round requires the original ledger's absolute path. No application extraction
cache is used. All attempts and finite repairs count.

Keep original archives, expanded outputs, notes and call traces local under ignored
`artifacts/`. A changed latest download requires a new manifest/oracle review; the
fixed benchmark rejects changed bytes. Rollback uses baseline 9623421 in a separate
worktree, preserving all research records.
