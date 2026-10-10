# Saved Luna A/B outputs: offline semantic reanalysis

> Historical phase report: scores and the phase-specific A/B decision below are
> preserved. The current release selects original B by explicit research decision;
> see [the engineering case study](engineering-case-study.md).

**POST_HOC_REANALYSIS â€” A remains the default.** This evaluation-only change
reanalyzes 48 saved executions from 16 notes. It makes no new model, embedding or
judge requests. It does not change production prompts, schema, validation,
repair, adapters or policy rules. The original `BENCHMARK_INVALID` report, gold,
responses and both historical ledgers remain unchanged.

The revised analysis shows a bounded benefit for B on the decidable confirmation
fields, with mixed development results. It does not establish generalization or
justify a default switch. Labels are non-independent; the reviewer had previously
seen outputs. Source-only review views reduce presentation bias but are not
blinding. No human or clinical-expert review occurred.

## Evidence and method

Starting HEAD: `d1950aa457980f46ed31d935bc9c0ea4904dbd74` on
`feature/luna-bounded-ab`; isolated delivery branch: `feature/luna-offline-rescore`.
The complete local `artifacts/luna-bounded-ab-round-01/` was available. The named
auxiliary attachments were not present in Downloads; none of their missing bytes
were reconstructed or claimed to be verified.

An immutable source review overlay covers 37 required propositions in all 16
notes. Each entry records its constraint ID, original fields, exact source
locators/quotes/hash, retain/revise/unresolved decision, reason and permissible
representation. The overlay and scorer hashes were saved before A/B totals.
The [evaluation contract](luna-ab-evaluation-contract-v2.md) specifies:

- Exact numeric result wrappers are projected from the existing value field;
  missing values are never supplied from statements, source text or gold. Wrong
  numbers, units, concepts, negation, comparisons and patients fail controls.
- A request "on" a date without collection scope can express an issue date.
  Only affected target-date cells become unresolved; other fields remain scored.
  Coupled date roles must remain coherent.
- Identity precedes correctness. Patient, source, semantic frame and event scope
  separate historical results, receipt documentation, current nonimplementation
  and future discussion. Correct context additions do not create duplicate tests.
- Every matched object is independently checked. Contradictions cannot hide
  behind a correct object, and fields cannot be stitched across partial objects.
- Missing keys, null, false and zero are distinct. Unresolved matches and extras
  are retained rather than silently classified as correct or incorrect.

The matcher is a finite evaluation tool, not a general semantic verifier. First
scores use actual first responses; final scores use saved packets. Neither
validation nor repair nor downstream rules are rerun. All 48 executions are
present; there are no missing materials or omitted failures.

## Results

The first and final stages have identical counts for the selected fields below;
they are stages of the same executions, not independent samples. Historical
strict first/final field-match totals are also identical, although historical
duplicate/error counters changed after context was added.

| Split / candidate | Executions | Historical strict matches | Revised first matches | Revised final matches | Unresolved | Wrong definite | Unnecessary null |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Development A | 8 | 57/58 | 54/55 | 54/55 | 3 | 1 | 0 |
| Development B | 8 | 56/58 | 54/55 | 54/55 | 3 | 0 | 1 |
| Confirmation A | 16 | 101/116 | 103/112 | 103/112 | 4 | 2 | 7 |
| Confirmation B | 16 | 109/116 | 111/112 | 111/112 | 4 | 0 | 1 |

There are 348 candidate field constraints per stage: 334 scored and 14 unresolved.
Required-field/proposition omissions are zero under this limited labelled scope;
unnecessary nulls still represent failures to populate supported values. Binding
error counts are respectively 1, 0, 2, 0; they overlap wrong-definite counts.
Do not add overlapping counters as independent errors.

Paired comparisons use the same note/repeat and common decidable cells. Development
has one B improvement, one regression and six ties, with one field gained and one
lost. Confirmation has six improvements and ten ties, with eight fields gained
and none lost in 112 common cells. Confirmation repeat 1 is A 52/56 versus B 56/56;
repeat 2 is A 51/56 versus B 55/56. Repeated outputs and fields are correlated;
the independent-material count is at most 16, not 48 executions or 334 fields.

The old/new denominators differ. Development A loses three formerly counted
ambiguous date matches. Development B loses those same three and gains one
equivalent numeric encoding. Each confirmation candidate gains two equivalent
numeric encodings and excludes four ambiguous target-date cells. These changes
repair scoring, not model extraction. Comparisons within the revised common
denominator support the limited B benefit; subtracting percentages across scoring
versions would misrepresent improvement.

## Five representative mechanisms

| Saved example | Previous judgement / output | Revised interpretation |
| --- | --- | --- |
| CONFIRM-04, both candidates | Order date retained with null test target; strict scorer demanded a target date | Source says an order is made "on" a date without collection scope. Target date is unresolved; coherent issue-date representation is preserved. No fabricated test date. |
| DEV-06 B, repeat 1 | Wrapped HbA1c percent result rejected as the wrong value | Existing result wrapper has the same number, analyte and unit. Read-only projection accepts it; wrong unit/number/negation controls remain rejected. |
| CONFIRM-06, repaired outputs | Receipt assertion sharing named-test context was matched as a duplicate historical result | Receipt and historical result are separate propositions. Some boolean receipt values remain contract-underspecified; correct offsets alone do not resolve their meaning. |
| CONFIRM-03 A versus B | A supplies false authentication without an explicit signature status; B keeps null | Genuine B reduction in false certainty. B also preserves a supported target date that A omits in repeat 2. |
| DEV-03 A versus B | B omits a named provider that A preserves | Genuine B regression, retained as an unnecessary null. Better confirmation counts do not erase this omission. |

Full original text, outputs, hashes, call IDs and old/new constraint records for
these examples remain in the ignored local evidence directory. The table is a
mechanism summary, not republication of raw clinical material.

## Repair, extras and uncertainty

Eight saved repair chains were inspected. Seven add supporting context without
changing existing known scalar values. CONFIRM-01 A repeat 1 (calls 26 to 27) adds
a cited provider to a test mention whose provider was previously null, plus a
nonperformance assertion. This actual grounding completion is recorded separately
from the headline selected-field counts. No new required-field error is
demonstrated by these saved transitions. Old receipt/temporal mismatch counters
also contained matcher artifacts; these are not attributed to repair.

Final extra classifications, from limited automatic checks and non-independent source
constraints, are:

| Group | Supported in scope | Supported out of scope | Unsupported | Unresolved |
| --- | ---: | ---: | ---: | ---: |
| Development A | 15 | 0 | 2 | 2 |
| Development B | 13 | 0 | 0 | 0 |
| Confirmation A | 28 | 2 | 3 | 4 |
| Confirmation B | 34 | 4 | 0 | 2 |

Unsupported authentication extras can repeat the same failure already counted in
a required field. Administrative null placeholders are scope deviations, not
invented completed tests. Family-history and unrelated-analyte statements require
their own subject/scope; they do not establish patient HbA1c facts. Future
discussion versus implementation, boolean receipt assertions, and rationale
categories unavailable in the schema remain unresolved where appropriate.

Ambiguous target dates affect absolute scores under alternative interpretations;
they were removed equally from A/B's paired denominator, not assigned whichever
answer helps a candidate. Unresolved extra meanings could affect a comprehensive
ranking. This study cannot establish that B is better overall, or provide exact
sensitivity bounds without additional independent semantic labels. Exhaustive
fact precision/recall and source-semantic citation precision are **UNAVAILABLE**.
The historical 192/192 downstream-state matches are retained but are not an
extraction-accuracy result.

Runtime signature lexical acceptance and repair-protection risks are documented,
not fixed or freshly verified here. No production conformance claim follows from
the scorer self-tests.

## Verification and reproducibility

The 23 targeted offline tests passed, including positive/negative controls for
ten mechanisms and an entry-point test whose provider/CLI methods fail immediately
if invoked. Two full rescoring passes used the same scorer, overlay and contract;
their score files are byte-identical. The second pass was a deterministic
reproduction check. No third pass is permitted in the archived task state.

Commands actually used, with the project's Python environment:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path + ';' + (Resolve-Path tools).Path
python -m pytest tests/test_luna_ab_rescore.py -q
python tools/luna_ab_rescore.py --original artifacts/luna-bounded-ab-round-01 --output artifacts/luna-ab-rescore-v2
```

The archived output namespace now has its two-pass limit exhausted. Do not reset
its state. Reproduction requires the authorized private original bundle, reviewed
overlay and contract, plus a separately authorized fresh offline output namespace.
Before invoking the same scorer, copy the unchanged overlay and contract and save
`rescore_state.json` with UTC `started_at`, `work_deadline` (45 minutes),
`delivery_deadline` (55 minutes), `max_new_provider_calls: 0`,
`new_provider_calls: 0`, `full_rescore_passes: 0`, and
`max_full_rescore_passes: 2`. Record input hashes and reject an existing namespace;
never reopen historical state. Public self-tests run without the private bundle.
The public aggregate alone cannot reproduce unavailable original bytes.

The persistent task started at 2026-10-09 20:34:12 UTC; work/delivery deadlines are
21:19:12/21:29:12 UTC. It finishes early with **COMPLETED_WITH_UNRESOLVED** after
the two permitted passes and delivery. No background experiment remains.

Historical usage is deduplicated by 56 call IDs, taking each request's own token
metrics rather than summing cumulative execution totals: input 966,368, output
69,026, cached input 56,320 and reasoning output 41,147. Cached/reasoning counts
are subsets, not additional totals. Historical billed cost is unavailable. This
task adds **0 requests and 0 experimental tokens**; coding-agent activity is not
reported as experiment inference.

See [compact validation results](luna-ab-posthoc-validation.json). Local full
records are indexed by `artifacts/luna-ab-rescore-v2/result-index.json`: source
overlay, both score files, 24 paired rows, eight repair traces, five examples,
Chinese report, state and integrity evidence. Historical file/runtime/ledger hashes
are checked again at delivery. Raw text, responses, ledgers and private review
records are retained locally and excluded from this commit. No push or main merge.
