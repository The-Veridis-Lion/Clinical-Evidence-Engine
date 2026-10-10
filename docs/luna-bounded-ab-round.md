# Bounded Luna prompt A/B: completed execution, invalid semantic benchmark

> Historical phase report: scores and the phase-specific A/B decision below are
> preserved. The current release selects original B by explicit research decision;
> see [the engineering case study](engineering-case-study.md).

**Keep A. B is experimental and is not recommended for adoption from this round.**
All 48 preplanned note executions completed. Final delivery status is
`BENCHMARK_INVALID`: post-run inspection established frozen expectation and matcher
defects. Their original scores are preserved, without changing labels, scorer,
inputs, prompts or runtime, and without running additional predictions.

Baseline: `93384e21eb25a7014df96d5a7fe13ff06b8744bf` on
`feature/generalizable-review-reliability`. Experiment branch:
`feature/luna-bounded-ab`. Frozen measured code:
`0ebb2cbb26e7da00cf715cb94e8c9472a6819b0f`. The original workspace was clean.
Applicable user-supplied repository instructions were followed; no repository
AGENTS.md or supplied `isolated_contract_probes` file was found.

## Design and hard stop

A is the exact baseline instruction text, checked against the baseline Git object.
B reorganizes the same task around propositions, event binding, scoped dates,
negation, temporal roles and unknown values. Neither has few-shot examples.
Both share the same schema, input/context/anchors, gpt-6-luna/high, validator,
one bounded repair, adapter and criterion rules. No routing, verifier or schema
change was introduced. Therapy, retrieval, policy and reconciliation are unchanged.
A remains the CLI default; `--note-prompt B` is explicit and experimental.

Eight development notes each ran A/B once; eight new confirmation notes each ran
A/B twice. Different patients/template families across splits; mechanisms intentionally
overlap. There are two longer mixed-paragraph confirmation packets (851 and 732
characters). These are **non-independent fact-first constructed mechanism tests**, with
a nonblind designer, not original clinical notes, human gold or expert validation.
The schema, code, 16 inputs, labels, prompts, scorer and seed `20261009` were hashed
before inference. All feasible confirmation repeats were saved/sealed before the
evaluator decoded their labels. The inference process saw source/context/schema only.

Start: 2026-10-09 19:40:23 UTC. Execution deadline: 21:00:23 UTC;
delivery deadline: 21:10:23 UTC. Persistent `round_state.json` contains both deadlines,
the fixed 48-item interleaved plan, attempts and stop state. Every request checks
the immutable freeze, deadline, 96-request ceiling and two-request note ceiling.
Request timeout is at most 180 seconds and fits the remaining time with cleanup
reserve; a runner-owned watchdog terminates its process tree at the hard deadline.
No deadline, plan or budget reset on resume. Terminal rounds cannot call the model.

The old 20-call ledger remained **17/20**, SHA-256
`0a1bdec19319cab161d4bfc731f8ded0565617e19b70f37baa0b19ef74fd9eb7`.
This explicitly authorized new phase has its own 96-request persistent state.
The ordinary CLI's old ledger ceiling remains unchanged.

## Actual measurements

**48/48 notes saved; 56 actual provider requests; 8 repairs; no transport retries,
timeouts, parse failures or final execution failures.** Both confirmation candidates
used 20 requests (16 initial + 4 repair). Development used 8 each.
CLI 0.159.3; tools disabled, ephemeral read-only source-only contexts, no application
extraction cache. Server cached input usage is retained separately. Backend snapshot
and actual subscription dollar cost are unavailable.

Measured provider time: **941.86 seconds**. Tokens: **966,368 input**, **69,026 output**,
**56,320 cached input**; usage was available for all 56 requests. These are cumulative
round totals, not a per-document context limit.

The following are **original frozen strict constraint counters, not valid clinical
accuracy estimates or evidence that B wins**:

| Split / prompt | Executions | First selected field matches | First selected propositions fully matching | First / final selected complete notes | First / final null mismatches | Criterion states |
|---|---:|---:|---:|---:|---:|---:|
| Development A | 8 | 57/58 | 18/19 | 7/8, 7/8 | 0, 0 | 32/32 |
| Development B | 8 | 56/58 | 17/19 | 6/8, 6/8 | 1, 1 | 32/32 |
| Confirmation A | 16 | 101/116 | 21/36 | 4/16, 4/16 | 11, 11 | 64/64 |
| Confirmation B | 16 | 109/116 | 29/36 | 8/16, 8/16 | 5, 5 | 64/64 |

Confirmation repeats: A 51/58 then 50/58 selected field matches; B 55/58 then 54/58.
These repeat counts have the same semantic defects. Raw first non-null mismatch
counters A/B are 4/3; final counters 10/6, partly caused by matcher collisions,
not demonstrated clinical false certainty. Original full counters, long/short and
repeat strata are in [machine metadata](luna-bounded-ab-validation.json).
All required kinds/proposition patterns were found by the frozen matcher, but that
coverage is not reliable exhaustive supported-fact recall. Extra facts remained
unscored or disputed, never silently added to a precision numerator.

All 192 criterion states match their frozen expectations, but this cannot excuse
note errors. These note-only cases have no independently established actual target
performance/history, so timeline and interval findings remain insufficient; diagnostic
purpose cases defer outside monitoring scope. This is a deliberately limited test,
not broad evidence of end-to-end clinical reliability.

## Why the benchmark is invalid

1. **Ambiguous date expectation.** One confirmation card says a clinician "orders"
   a test "on" a date. Both prompts reasonably return `date_role=order_issued` and
   `target_date=null`. Frozen labels instead demand a collection date. Eight null
   field mismatches across four executions cannot be called proven abstention.
2. **Equivalent result encoding excluded.** Strings containing the correct analyte
   and result are allowed by the existing schema, but the frozen value list accepts
   only the numeric value and a few short strings. Five strict mismatches preserve
   the actual result; they are not hallucinations or unsupported certainty.
3. **Repair-context collision.** After repair adds a historical-result span, the
   matcher conflates "receipt does not indicate a new blood draw" with the distinct
   historical result. Three executions acquire apparent extra value/date/temporal
   errors through scoring, although their propositions remain different.
4. **Split-proposition ambiguity.** A future discussion and a current nonimplementation
   statement share a line; the matcher can treat the former as a duplicate of the
   latter. This is not established as a model temporal error.

The old scores are not rewritten. `frozen-scoring-summary.json` preserves the original
bytes/hash. `summary.json` adds the invalidity decision and keeps every metric unchanged.
No corrected headline score or after-the-fact adoption decision is manufactured.

## Traceable observations and remaining failures

These are non-independent qualitative inspections, not a replacement benchmark:

- In the longer dispersed-order packet, A leaves the purpose date null in both
  repeats and the order date null in one; B fills the order date in both and the
  purpose date in one. B still unnecessarily abstains on the other purpose date.
- In the handover packet, B links the requested collection date to both purpose
  and order in both repeats; A omits one or both dates. Established disease and
  current nonimplementation remain separate from future discussion.
- In the voicemail case, A treats undocumented authentication as false in both
  repeats; B preserves null. In development, B instead loses an explicitly named
  requester's provider field, so improvement is not uniform.
- Both prompts create a null-valued review fact from an administrative no-target
  control. The absence wording is source-supported, but it is outside the requested
  fact scope. Neither creates an actual performed test; downstream stays insufficient.
- The conflicting-instruction packet retains both supported requested dates in
  both prompts/repeats. The current rules do not expose requested-date conflict as
  a separate finding. It must not be mistaken for an adjudicated, conflict-free order.

Seven repairs add named-test context; one fills an explicitly attributable provider
for a signed test mention (calls 26 -> 27). **38/38 independently grounded first rows
preserve known fields.** This is structural preservation, not proof their original
meaning was correct. No observed repair changes an existing grounded non-null value;
the reported post-repair counter increase is predominantly a scorer artifact.
Actual prompts preserve the errors sent to repair, not merely reconstructed errors.

Offline signature probes still accept a future "will be signed" phrase and a signature
over an unrelated attachment. Their lexical acceptance does not authenticate the
clinical assertion. First-value protection can also prevent correction of an initially
grounded but semantically unsupported value. These risks were inspected, not changed.

**48/48 positional packet audits pass, 675 repeated citation occurrences verified,
zero wrong-patient inclusions.** This is not semantic citation precision, which remains
UNAVAILABLE. Partial semantic review is non-independent; human/expert review is false.
The schema still has no event/subject reference, and `test_mention.value` has multiple
reasonable encodings. Those boundaries are documented rather than redesigned.

## Code, local evidence and reproduction

Runtime changes are only explicit prompt selection in `note_extractor.py`, `review.py`
and `cli.py`, plus `note_prompt_b.py`. New tools are `luna_bounded_ab.py` and the frozen
experimental `score_luna_ab.py`; targeted tests are `test_luna_bounded_ab.py`.
The scorer is retained for exact reproduction **with its documented defects**.
Do not use it as a reliable general semantic accuracy evaluator.

Pydantic 2.13.5, LangExtract 1.7.0, intervaltree 3.2.1, pytest 9.1.1.
Pre-freeze checks: **73 passed in 0.49 seconds** (experiment, claims reliability and
integration tests). No historical hundreds-call experiment or full test suite was
rerun. CLI help/default prompt path was checked offline.
Final experiment-only checks: **6 passed in 0.07 seconds**; no model calls.

The complete private round is `artifacts/luna-bounded-ab-round-01/`:

- `freeze.json`, `round_state.json`, `prediction-seal.json`, `result-index.json`;
- original inputs, immutable expected constraints and `semantic_contract.md`;
- exact A/B prompts, per-input generated schema, all 56 visible responses and usage;
- `call-audit.json`: all sources, first responses, validator errors, repair deltas,
  final facts, downstream criteria and constraint checks;
- original strict scores, final invalidity record, all failures, AI attribution,
  positional/preservation audit, offline probes and integrity checks.

Private materials are ignored and not uploaded. This public summary cannot recreate
the private input bytes without that local audit bundle; their hashes are published.
Do not regenerate labels from predictions. Keep the original round read-only; work
on a copy for replay. Commands actually executed with source/tools on PYTHONPATH:

```powershell
python tools/luna_bounded_ab.py freeze --round artifacts/luna-bounded-ab-round-01
python tools/luna_bounded_ab.py predict --round artifacts/luna-bounded-ab-round-01
python tools/score_luna_ab.py --round artifacts/luna-bounded-ab-round-01
python -m pytest tests/test_luna_bounded_ab.py tests/test_claims_reliability.py tests/test_claims_review_integration.py -q
python -m clinical_intelligence.claims_review run --help
```

Freeze cannot overwrite an existing freeze, and predict exits without model calls
in this terminal round. Those commands describe the completed measurement, not
permission to reset it or start a fresh round. Scoring requires the complete private
bundle and repeats the documented invalid strict comparison. No further calls are
planned. Revert safely by using a separate checkout at baseline `93384e2`, retaining
the current branch and private artifacts; no destructive reset is needed.

Execution ended because the fixed plan completed; delivery records the later
`BENCHMARK_INVALID` decision. Neither unused budget nor promising observations
authorized further work. No main merge or remote push; no experiment subprocess
or watchdog remains active. A future, separately authorized task may repair the
semantic benchmark, but it is not executed here.
