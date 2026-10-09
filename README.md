# Clinical Evidence Reconciliation Engine

A Python engine for turning conflicting clinical-document claims into auditable
patient-level answers. It preserves exact source passages, applies explicit corrections,
and calculates care utilization without asking a language model to do arithmetic.

The engineering focus is the boundary between **semantic extraction** and
**deterministic reconciliation, calculation, and evidence tracing**. A visit can span
several documents; a later copy should not undo a signed correction, and contradictory
authoritative claims should remain visible.

## Run the synthetic demo

Python 3.12+ is required; verified with 3.12.14. Run from the repository root.
Dependency installation needs a package index or populated cache. Once installed,
the demo and default tests need no credentials, network, or live model access.

```sh
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# POSIX: source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps .
clinical --db artifacts/demo.sqlite demo
clinical --db artifacts/demo.sqlite query --patient DEMO-CEDAR --family utilization --format audit
clinical --db artifacts/demo.sqlite query --patient DEMO-JUNIPER --family utilization
python -m pytest -q
```

`python -m clinical_intelligence` is equivalent to `clinical`. Global `--db` and
`--output` precede subcommands. Running `demo` again reuses persisted evidence.
Generated databases and expanded outputs stay local under ignored `artifacts/`.

## HbA1c monitoring evidence review

The independent `claims_review` module prepares sources, preserves structured facts,
extracts limited note evidence, and evaluates four scoped criteria into one JSON/Markdown
packet. It retains unknown values and competing sources and makes no approval, denial,
payment or final medical-necessity decision. It does not use the therapy database.
Its policy registry remains `draft_ai_reviewed`, without human or clinical expert review.

After installation, these commands need no credentials or model:

```sh
python -m clinical_intelligence.claims_review prepare --case examples/claims_review/development/DEV-002.json --output artifacts/claims-review/prepared.json
python -m clinical_intelligence.claims_review run --case examples/claims_review/development/DEV-002.json --mode structured-only --format json --output artifacts/claims-review/review.json
python -m clinical_intelligence.claims_review render --packet artifacts/claims-review/review.json --format markdown --output artifacts/claims-review/review.md
python tools/verify_claims_review_synthea.py --output artifacts/claims-review/synthea-verification.json
```

Structured-only execution explicitly leaves notes unprocessed. To include the note,
use the separately installed, authenticated Codex CLI:

```sh
python -m clinical_intelligence.claims_review run --case examples/claims_review/development/DEV-002.json --mode live --model gpt-6-luna --reasoning high --format markdown --output artifacts/claims-review/live.md
```

Live commands must share `artifacts/claims-review/live-budget.json` (or the same
explicit `--ledger` path) and trace directory across restarts/retests. The feature-round
ceiling is 20 calls, reserved before each request, including failures and at most one
validation repair per note. From another working directory, pass explicit paths to
the same ledger and trace directory. Application caching is disabled; raw responses
remain local and ignored.

The [integration report](docs/claims-review-integration.md) separates original preparation,
offline fixtures/replay, and six real Luna calls. Five development cases and a limited
Synthea slice are engineering examples. The six independent confirmation candidates
were not opened or used. See the [semantic contract](docs/claims-review-contract.md)
and [representative final packet](examples/claims_review/DEV-002-review.json).

## Original archive evidence demo

The review now starts from an original unfiltered official Synthea CSV archive plus
an explicitly constructed target request, rather than a preselected source list.
Retrieval preserves patient/encounter identities, original field strings, row/file
hashes, exclusions and uncertain event linkage. Only selected natural-language notes
would use Luna; the demonstrated CSV run contains no such notes and makes zero calls.

After the installation above, run from the repository root:

```sh
python -m clinical_intelligence.claims_review download --output artifacts/raw-source/original.zip
python -m clinical_intelligence.claims_review retrieve --archive artifacts/raw-source/original.zip --query examples/claims_review/raw/target-query.json --snapshot-available-at 2026-10-09 --output artifacts/raw-source/retrieval.json
python -m clinical_intelligence.claims_review run --retrieval artifacts/raw-source/retrieval.json --output artifacts/raw-source/review.json
python -m clinical_intelligence.claims_review render --packet artifacts/raw-source/review.json --format summary --output artifacts/raw-source/review.md
python tools/benchmark_claims_retrieval.py --archive artifacts/raw-source/original.zip --output artifacts/raw-source/benchmark
python tools/audit_claims_packet.py --retrieval artifacts/raw-source/retrieval.json --packet artifacts/raw-source/review.json --output artifacts/raw-source/citation-audit.json
```

Download refuses to overwrite an existing archive; reuse your verified local file.
These dates reproduce the recorded 2026-10-09 snapshot-receipt experiment. For a later
new download, use its actual receipt date and update the query's as_of date; do not
backdate availability. Without a receipt declaration, sources have unknown
availability. Receipt never establishes original EHR availability or history completeness.
The fixed benchmark requires SHA
`d61417b551e5b0997c33851b339c157421751f0ea68c18ea686ceb1850907c35`;
changed latest downloads need a new source inventory. Expanded JSON and the archive
remain ignored. The [concise example packet](examples/claims_review/raw/review-summary.md)
retains visible gaps; full machine JSON is generated separately.

```mermaid
flowchart LR
    A[Original CSV archive + constructed request] --> R[Patient/code/date retrieval]
    R --> P[Prepared sources + exclusion provenance]
    P --> S[Deterministic structured facts]
    P --> N[Selected notes, when available]
    N --> L[Nullable Luna facts + exact offsets]
    S --> C[Four scoped evidence criteria]
    L --> C
    C --> E[JSON + concise packet + missing/conflicting evidence]
```

Actual new evidence: 18 original tables / 201,657 rows; 19 prior HbA1c result rows
instead of the old slice's five. Three overlapping retrieval windows matched **26/26
source-task pairs**, with no observed candidate false positives or wrong-patient
inclusions under the finite oracle. They represent one patient, not independent
clinical validation. The freshly executed suite passed 303 tests; current-rule replay
passed 5/5 saved development responses. Six reserved confirmation inputs/expectations
were unavailable, so independent final-prompt confirmation is **NOT VERIFIED**.
The prior 4/5 live development result and one final-prompt DEV-002 check remain historical.

The raw-source example correctly exposes absent target-performance/order/intent
documentation: all four criteria remain INSUFFICIENT_EVIDENCE. An archive result is
not a verified billing claim. Positional citation checks do not certify meaning;
independent semantic precision is unavailable. See the [delivery and benchmark](docs/raw-source-delivery.md),
[versioned machine summary](docs/raw-source-validation.json),
[retrieval contract](docs/raw-source-retrieval-contract.md),
[AI-assisted assertion review](docs/raw-source-semantic-review.md),
[official policy verification sheet](docs/claims-review-policy-verification.md), and
[90-second demonstration/interview notes](docs/claims-review-portfolio.md).

## Architecture

```mermaid
flowchart LR
    D[Source documents] --> E[LLM / LangExtract extraction]
    E --> G[Validated claims + exact passages]
    F[Synthetic claim fixtures] --> G
    G --> S[(SQLite evidence)]
    S --> R[Deterministic reconciliation]
    R --> C[Deterministic calculations]
    Q[Validated QuerySpec] --> C
    C --> A[Answer + provenance]
    S --> A
    N[Natural-language question] --> T[LLM QuerySpec translation]
    T --> Q
```

- **Extraction:** the model records what each document states; Pydantic validates
  contracts and the adapter verifies contiguous verbatim spans and character offsets.
- **Reconciliation:** patient-scoped encounter matching, field-specific corrections,
  retransmission relationships, and unresolved alternatives are ordinary Python rules.
- **Calculation:** half-open local-time intervals are unioned and intersecting breaks
  subtracted; encounter/day counts and plan comparisons use the reconciled evidence.
- **Provenance:** one evidence index links answer contributions to calculations,
  events, claim fields, source passages, and filenames. JSON and audit use the same result.
- **Persistence:** content hashes deduplicate documents; versioned extraction snapshots
  are immutable. Patient caches depend on active evidence and policy versions and survive restarts.

## One concrete evidence chain

The eight [synthetic documents](examples/synthetic/documents) describe two independent
patients in April 2026. They are engineering fixtures, not real clinical records.

For Cedar's `LAB-G7`, attendance states **09:12–10:46**, a separate activity record
states a **09:41–09:49** pause, and a signed correction replaces departure with **10:31**.
A subsequent copy repeats the old departure. Grounded claims preserve each statement;
reconciliation retains the correction; calculation yields **79 − 8 = 71 minutes**;
the audit links arrival, corrected departure, and pause to their respective source passages.

Cedar's second encounter has unresolved signed **37 / 49 minute** claims, so totals
remain **108 / 120 minutes across two encounters and two days**. A 115-minute weekly
plan cannot be conclusively assessed. Juniper has **one encounter / 23 minutes**, even
though the encounter token overlaps Cedar's. Duplicate ingestion changes neither total.

## Correctness and evaluation

```sh
clinical --db artifacts/demo.sqlite query --patient DEMO-CEDAR --family compliance --format audit
clinical --db artifacts/demo.sqlite experiment
clinical --db artifacts/demo.sqlite benchmark --iterations 5
```

The offline suite covers exact grounding, patient isolation, deduplication, corrections,
retransmissions, conflicts, interval arithmetic, persistence in a new interpreter,
QuerySpec behavior, and runtime provenance. It also exercises real LangExtract alignment
with a fixed model response. Synthetic clock expectations use independent datetime arithmetic.

[Evaluation](docs/evaluation.md) records actual results, a reproducible comparison with
naive latest-record selection, benchmark boundaries, and the earlier live extraction
failure. Fixture/replay success is not a measure of live model accuracy.

## Live model workflow

Install and authenticate Codex CLI separately and put it on PATH. The provider uses
`gpt-6-luna` with high reasoning and `clinical_partition + nullable_v1`;
typed extraction is followed by a dedicated clinical-observation pass, with at most
one repair triggered by runtime validation. Live commands
require the operator's account and network. No credentials or model weights are included.

```sh
clinical --db artifacts/live.sqlite process --input examples/synthetic/documents --model gpt-6-luna --reasoning high
clinical --db artifacts/live.sqlite query --patient DEMO-CEDAR --family utilization --format audit
python tools/validate_live.py artifacts/live.sqlite
clinical --db artifacts/demo.sqlite ask --patient DEMO-CEDAR "How many therapy minutes were delivered from April 6 through April 12, 2026?"
```

`process --extractor previous` selects the previous final `clinical_partition`
prompt/schema; use a separate database. `--extractor baseline` retains the older
string-payload historical comparator. [The nullable follow-up report](docs/luna-followup-report.md),
[field uncertainty contract](docs/uncertainty-contract-v1.md), and
[machine-readable summary](docs/luna-followup-summary.json) record this delivery,
including the unchanged 23/31 original strict score and its limitations. The larger
`semantic` and `uncertainty` profiles remain explicit experimental options.
[The Luna optimization report](docs/luna-optimization-report.md)
documents 42 tested configurations, real independent repetitions, a frozen holdout,
residual failures, and exact reproduction commands. [The aggregate summary](docs/luna-results-summary.json)
records final comparisons, call accounting and holdout limitations. Full experiment
history remains local; live calls are distinguished from offline replay and cache reuse. Raw original materials, responses, and databases remain
in ignored `artifacts/` and are not publication-approved.

`validate_live.py` compares reconstructed encounters with the synthetic fact fixtures
and exits nonzero on differences. `ask` proposes a validated QuerySpec; the engine
calculates the answer. Unsupported or ambiguous interpretations have explicit states.
Manual queries support utilization, weekly utilization, compliance, encounters,
period comparison, consecutive under-target weeks, assessments, progress, and cohort thresholds.

## Limitations

The earlier live run omitted an activity encounter ID and failed the semantic comparison;
it is retained as a historical failure. The optimized default passed the public synthetic
encounter comparison through the real CLI, while repeated original-task extraction still
showed copied-record, presence, role, and clinical-coverage errors. The frozen holdout also
exposed annotation/wording inconsistencies; its original scores are preserved in the report.
These are engineering measurements, not clinical validation. The current plan-field locator
misses wording such as "115 patient-present minutes", so compliance provenance reports
partial coverage even though the full plan quote remains available.

The engine assumes one patient per document, explicit encounter identities, same-day
local intervals, and quantitative Monday–Sunday plans. Missing midweek applicability
rules remain ambiguous. The baseline live extractor does not emit functional-action
claims, and neither does the optimized contract; structured stored actions are supported
by the domain and progress queries. Missing dates and scores are represented explicitly,
with undated facts and uncertain bounds retained rather than invented dates or zero scores.
Exact quotation does not guarantee semantic accuracy. Whole-patient loads and detailed
evidence output constrain scale; no large-corpus throughput is demonstrated. There is
no production deployment, real-patient validation, regulatory certification, fine-tuning,
or autonomous medical decision-making claim.

## License and attribution

Source-available under [PolyForm Noncommercial License 1.0.0](LICENSE.md).
Noncommercial use, modification, and redistribution are permitted subject to its
conditions. Commercial use requires separate permission or licensing from the relevant
copyright holder. Specified notices must be preserved, including [NOTICE](NOTICE):

Required Notice: Copyright (c) 2026 The-Veridis-Lion

This applies only to original material owned and licensable by The-Veridis-Lion;
it does not claim ownership of external dependencies or excluded third-party inputs.
This is not described as OSI-approved open source. [Third-party notices](THIRD_PARTY_NOTICES.md)
preserve dependency attribution and LangExtract health-use terms. AI coding assistance
supported implementation and verification; runtime inference is separately identified.

## Contact

For project inquiries or commercial licensing:

[theveridislion@duck.com](mailto:theveridislion@duck.com)

The-Veridis-Lion
