# Original B integration and new constructed-note comparison

**Decision: INCONCLUSIVE_SCORER / B_NOT_READY. Production default remains A.**
The original B is explicitly available through `--note-prompt B`, and the isolated
candidate wrapper defaults to B with prompt-selection provenance. No prompt,
schema, validator, repair, adapter, policy or therapy change was made. No push or
main merge was performed.

## Frozen conditions and executed work

Starting local HEAD was `65d2eb2b66862bb4245e373fcd77c9b2622c7ac6`, not an assumed
remote branch. The frozen candidate/data/tool commit is
`d2d03f951ff50a6bff99c3c2b80fce94cc295ade`, on
`feature/b-candidate-new-validation`. Both base prompt strings were checked against
the previous actually measured snapshots. A/B share one deployed `run_review`
path, `gpt-6-luna`, high reasoning, existing schema, source/anchors, validation,
one maximum repair, reconciliation and rules. CLI version was `codex-cli 0.159.3`;
the actual backend model snapshot remains unavailable.

The bounded local inventory found no qualified, unused, complete HbA1c notes.
All twelve new sources are **constructed_synthetic**, AI-assisted and author-nonblind,
not original EHR notes or clinical validation. Four multisection notes have
647-707 words; the other eight have 155-215 words. Ten contain substantive target
content; two are administrative or other-subject/analyte controls. The full text
is retained in each [source fixture](../examples/claims_review/b_candidate_v1/README.md)
and in separately readable local text files. The
[manifest](../examples/claims_review/b_candidate_v1/dataset_manifest.json) records
source hashes, families, lengths, rights and prior-use status.

Forty-three source-bound propositions and their labels were established before
inference. Per-source positive/paraphrase/context/order checks and 220 negative
mutations passed. Thirty-eight offline tests passed, including fake-provider
proof of A/B wiring, unchanged product default, identical source/schema context,
distinct candidate identity and bounded terminal/time guards. Preflight also
revealed and corrected source-label bookkeeping issues before freeze. It did not
prove that every future natural-language representation was covered.

The fixed order covered every source with both prompts before repeat 2. All 48
executions were saved, using 59 actual requests and no transport retries, extra
smoke calls, judge calls, embeddings, best-of selection or third repeats. Predictions
were sealed before totals were calculated. One formal scoring pass was run; no
rescoring, gold change or tuning followed the discovered evaluation gaps.

## Frozen descriptive results, not validated accuracy

| Candidate | First frozen matches | Final frozen matches | Frozen wrong-definite fields | Unnecessary null | Missing fields | Unresolved fields |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 251/264 | 251/264 | 5 | 5 | 3 | 4 |
| B | 260/263 | 260/263 | 3 | 0 | 0 | 5 |

Each candidate has 268 candidate field constraints. Four cells per candidate were
predeclared ambiguous target dates. B has one additional unresolved numeric
representation. Pairing excludes that same cell for A too: on 263 common fields,
the frozen counts are A 13 errors and B 3 errors (A 250/263, B 260/263).
Repeat 1 has 132 common fields and 5/2 A/B errors; repeat 2 has 131 and 8/1.
Long-note pairs have 135 common fields and 3/1 errors; short-note pairs have 128
and 10/2. These are **imperfect frozen evaluator counts**, not clinical false-
certainty rates. First/final stages, repetitions and fields are correlated.

The full per-note/repeat table is in the [machine-readable summary](b-candidate-new-validation.json)
and local paired CSV. Frozen totals suggest better explicit date binding and fewer
missing/unknown fields with B, including preservation of an unknown physician
signature status. They cannot certify the adoption gates because:

1. **Order scope:** N01/N08 labels required planned order intent even when a fact
   correctly describes a completed order issuance as `order_issued / actual`.
   That is not a claim that a test was performed. Several frozen wrong-definite
   counters are therefore contested scoring results, not proven model errors.
2. **No-target extras:** the frozen blanket rule rejected supported sibling,
   thyroid and albumin descriptions as unsupported. Supplemental source review
   identifies their separate scope without rewriting any score or expectation.
3. **Representation limit:** N01 B repeat 2 retains the correct result and specimen
   date in a full narrative value. The scalar numeric parser cannot project it;
   the field stays unresolved, not a model omission or an invented value.

No adjusted score is offered. The original new-round labels, responses and frozen
scores remain intact. A future evaluator repair would require a separate version;
this round does not perform it or initiate a new experiment.

## Actual errors, source review and repair

- **N06:** A makes unknown physician authentication false in both repetitions;
  B preserves null. The nurse's signature authenticates the message, not the
  attributed physician request. The errors start in the first model proposals.
- **N07 / N09:** B preserves explicit collection-date bindings that A leaves
  null in selected purpose/rationale facts. Some dates remain elsewhere in A's
  packet; this is a relation/field omission, not necessarily complete loss of
  the date from the document.
- **N08:** B says the withdrawn collection did not occur in both repetitions
  (calls 28 and 55). The source only says that a new request does not establish
  prior occurrence. Nonoccurrence is not established either. The unsupported
  definite statement exists in the first responses, passes structural grounding
  and persists in final packets. No claim-level approval was observed.
- **Missing regimen documentation:** both prompts sometimes encode a statement
  that no change is documented as `regimen_change=false`. The readable statement
  can be faithful while its clinical scalar incorrectly substitutes absence for
  unknown. This is retained in the supplemental failure review.
- **N12 scope:** B's readable sibling-diabetes statement is supported. The common
  adapter stores it under the source patient's identity, while the policy's
  condition scan lacks assertion experiencer isolation. This is a shared
  representation/runtime risk, not proof that B failed to read the sibling
  qualifier. These note-only cases do not demonstrate its effect in an otherwise
  evaluable positive monitoring claim: that endpoint is **NOT VERIFIED**.

All 218 first/final extra review entries preserve frozen category, source quotes,
locators, fact/source hashes, supplemental decision and unresolved status. Candidate
labels were removed from the review view, but prior author/output exposure means
the AI review is not genuinely blinded. Some entries retain finite automated
classification; exhaustive independent semantic support is not established.
Semantic citation precision and overall fact precision/recall are **UNAVAILABLE**.
Correct source offsets alone do not establish clinical meaning.

Eleven actual repair chains are saved: seven for A, four for B. Eight preserve
the clinical scalar multiset; three A chains alter provider/authentication or
test-specificity fields. The selected-field totals do not change. Actual validator
messages, first answers, repair prompts/answers and final facts are all retained;
no validator or repair was rerun to create another final answer. Shared signature
and preservation risks were recorded rather than repaired.

## Costs, stopping and adoption

| Candidate | Workflows | Requests | Repairs | Sum of workflow seconds | Input tokens | Output tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 24 | 31 | 7 | 580.55 | 550,627 | 46,305 |
| B | 24 | 28 | 4 | 483.56 | 498,270 | 44,704 |

Totals are deduplicated per request: input 1,048,897, output 91,009, cached input
50,176 and reasoning output 53,002. Cached/reasoning figures are subsets, not extra
tokens to add again. Application extraction caching was disabled; server prompt
caching was allowed. Subscription billed cost is unavailable. All 48 workflows
completed without execution failure; this does not imply semantic conformance.

Persistent start was 2026-10-09 21:08:52 UTC. The data gate (21:43:52), work deadline
(22:28:52) and delivery deadline (22:38:52) were never reset. The dataset passed
before the gate; fixed inference ended at 21:37:50 UTC. The 96-request ceiling
was not a target. The existing 17/20 ledger and previous 56/96 phase remain
unchanged. The runner exited and its watchdog/lock were cleared.

Gates 1 and 5 fail because the scorer and critical extras are unresolved/unsafe.
Gate 2 is favorable only descriptively. Gate 4 has favorable selected-field and
execution counts, not exhaustive coverage. Consequently no B-default configuration
commit is created and no merge is recommended. A remains default, with B optional.
The twelve now-exposed notes are development/regression material for future work.
Some constructed prose includes unusually explicit record-scope explanations;
this author guidance further limits extrapolation to original clinical writing.

## Commands and retained evidence

Offline wiring/scorer tests:

```powershell
python -m pytest tests/test_b_candidate_validation.py tests/test_luna_ab_rescore.py tests/test_luna_bounded_ab.py -q
```

Executed fixed-round commands (with the existing project environment and `src;tools`
on `PYTHONPATH`):

```powershell
python tools/b_candidate_validation.py preflight --round artifacts/b-candidate-new-validation-01
python tools/b_candidate_validation.py freeze --round artifacts/b-candidate-new-validation-01
python tools/b_candidate_validation.py predict --round artifacts/b-candidate-new-validation-01
python tools/b_candidate_validation.py score --round artifacts/b-candidate-new-validation-01
```

The archived state is terminal; do not rerun inference or reset it. A fresh live
stage requires independent authorization and a new persistent state. Full replay
also requires the retained original prompt snapshots and private round bundle;
public summaries alone do not reconstruct their bytes. The current CLI remains
usable offline, and its explicit A/B switches remain available for separately
authorized live work:

```powershell
python -m clinical_intelligence.claims_review run --case examples/claims_review/b_candidate_v1/N05.json --mode structured-only --note-prompt B
```

Local `artifacts/b-candidate-new-validation-01/result-index.json` links full note
texts, source labels, freeze/order/gates, 48 prediction paths, 59 call traces,
frozen scores, paired CSV, every failure/unresolved item, source/repair reviews,
Chinese report and integrity evidence. Raw responses, ledgers and full reviews
stay ignored. Return to `feature/luna-offline-rescore` to inspect the original
delivery; no production default change needs reverting. The round ends here.
