# Luna nullable follow-up delivery

This round adopts **clinical_partition + nullable_v1** to represent unknown facts correctly while retaining the previous clinical classification, staged extraction, and deterministic calculations. It has not demonstrated superiority on the original frozen strict score. Adoption is based on uncertainty correctness under the updated requirements, supported-fact coverage, and downstream regression results. This round is complete; Medical Necessity Evidence Review belongs to a separate next stage.

The starting commit is `861f2607b9aa8559fd860159439463d4d0229e4d`, on the isolated branch `experiment/luna-semantic-followup`. The requested model stayed `gpt-6-luna`, reasoning high, CLI 0.159.3; the actual backend snapshot was unavailable. No temperature search was conducted. Dependencies remain Pydantic 2.13.5, LangExtract 1.7.0, and IntervalTree 3.2.1; other versions are in requirements.lock.

## Adopted changes

- Typed JSON keys remain required, while unknown signatures, service classifications, patient identity, assessment instrument/score, plan thresholds, and other fact fields may be null. Ordinary unknown values use null; reporter/experiencer retain `not specified`. Strict numeric/boolean validation prevents false from becoming zero. See the [field uncertainty contract](uncertainty-contract-v1.md).
- Short uncertainty_notes distinguish undocumented, ambiguous, and inapplicable values. Supported conflicts remain multiple claims; 40/50 minutes are not collapsed into one null. Partial clocks preserve known endpoints; partial plans preserve known thresholds.
- The adapter, storage, reconciliation, and query layers preserve supported facts and propagate eligibility, date, time, and correction-authority uncertainty. Unknown patients remain isolated by document; unknown instruments/subjects are not forcibly merged or used for trends. Code still handles time arithmetic, corrections, internal IDs/offsets, and final calculations.
- Source validation collects independently observable errors together and still allows at most one repair. It no longer hides a second error behind an omitted ID. Uncertainty notes on partial intervals do not block known endpoints; unknown and named instruments can coexist in assessment sorting.
- Abstraction/source-contract/reconciliation versions are 6/7/11. Extraction cache identity includes generation configuration, schema/adapter/contract code, CLI, and dependencies. Old snapshots are not overwritten.

Broader source-layer separation, historical assessment mentions, and comprehensive prompt rewrites did not win consistently. They remain explicit non-default experimental profiles for replay, without a default-quality claim. The unrun semantic_v2 alias is excluded from delivery.

## Historical attribution and program fixes

The original difficult subset in stability-v13 had **8/80 failures**: D013 repeats 1/3/7, D108 repeat 3, D104 repeat 4, and D006 repeats 6/7/10. Reviewing final-confirmation-v13, field-semantics-v14, and deployment-original-final brought the audit to **21 failures and 48 original calls, with zero missing raw files**. The restricted `artifacts/semantic-followup/failure-audit.json` retains source/gold/output/mismatch, stages, call paths, earliest errors, and downstream effects.

Main mechanisms were first-generation interpretation of date/role/signature scope, granularity of supported facts, and some scorer-attribution disputes. D104 recognized retransmits; it was not a failure to recognize retransmission. D013 can contain correct current-form dates/scores alongside an incorrect historical mention; repeat-01 examples were not used to infer other repeats. D012 already contained walking: greedy matching selected another observation, so it cannot be described as omitted walking. The 21 reviews did not identify evidence of adapter changes to meaning.

An old attachment excluding new contact in the same mixed packet was a reproduced program defect. An experimental profile with explicit source scope received a regression fix. Default nullable does not add those model fields and cannot guarantee resolution of mixed-source ambiguity.

In semantic-stability-v1, D108 repeats 7/8 initially contained clinical facts but omitted an appointment ID and paraphrased a literal disposition. The old fail-fast repair saw only the first error; the complete document was ultimately lost. Its many FNs are an end-to-end failure, not separate clinical omissions. The final two real repair replays received both runtime errors together: **one call each, both accepted**. These validate targeted repair of saved proposals, not two new complete extractions. Historical failure scores remain unchanged, and validator acceptance is not proof of all semantic correctness.

All annotation/dispute reviews were **non-independent engineering reviews**, without human annotation, clinical-expert confirmation, or clinical validation. Original gold, scores, and sealed results remain preserved. The previous sealed set has been discussed and is no longer unseen data.

## Comparison

A is the previous final clinical_partition, N the minimal nullable profile, and U the unadopted broader uncertainty rewrite. This table uses the same fact sets and common semantic projection `critical-fields-11-role`; historical versions 9/10 remain preserved.

| Materials | A fully correct | N fully correct | A / N precision | A / N recall | A / N calls |
|---|---:|---:|---:|---:|---:|
| 12 synthetic mechanisms, 2 repeats each | 12/24 | 24/24 | .9563 / 1.0000 | .9107 / 1.0000 | 49 / 48 |
| Original task, 31 documents, one new full extraction | 31/31 | **23/31** | 1.0000 / .9985 | 1.0000 / .9630 | 64 / 65 |
| 3 new confirmation templates after freeze, 3 repeats each | 3/9 | 9/9 | .9556 / 1.0000 | .9556 / 1.0000 | 18 / 19 |

A's original/development controls use recent existing fresh calls, not snapshot reads counted as repetitions. The previous A contract was checked against 78 actual request hashes. Common-runtime revalidation/scoring was offline and made no new model calls.

Version 10 only adds partial-clock sorting support. Version 11 makes the existing patient-name-to-patient role equality symmetric, for every candidate, without changing gold. Development scores under version 10 were A 10/24, U 20/24, N 20/24; version 11 gives 12/24, 23/24, 24/24. This difference is a **scoring-representation fix, not a prompt gain**. Original N remains 23/31; the field-level uncertainty checks below do not depend on that alias change.

| Predeclared uncertainty-field checks | A | N |
|---|---:|---:|
| Development correct / checked | 32/48 | 48/48 |
| Development false certainty / required-fact omissions | 12 / 4 | 0 / 0 |
| New confirmation correct / checked | 18/24 | 24/24 |
| New confirmation false certainty / unnecessary abstention | 6 / 0 | 0 / 0 |

These are scoped synthetic mechanism checks, not error rates for all fields. All 31 original N documents parsed and passed validation. Supplemental clinical coverage was **24/27, equal to A**. The utilization and assessment-timeline group queries were correct, without misleading definite zero or unnecessary unknown. Query provenance still has partial coverage; accepted does not mean semantically complete and correct.

The earlier broader semantic B profile scored 68/80 in the eight-document, ten-repeat stability check, versus A 73/80, with two validation blocks losing whole documents. U scored 22/31 on the original task, covered 22/27 clinical assertions, and showed unnecessary abstention. Neither became default. Historical scores, offline program-fix acceptance gains, scoring changes, and new generation results remain separately recorded.

## The eight original strict mismatches

| Documents | Frozen strict-score mismatch | Treatment in this round |
|---|---|---|
| D006 | Old labels treat Completed as positive presence/delivery and absent signature metadata as false; N uses null | Preserve administrative status and other explicit facts under the new requirements; do not change old labels |
| D015, D016, D108, D112 | Some administrative/cancelled/billing entries: signed=false under old labels, null in N | Missing applicable signature statements do not establish false; retain historical strict FNs |
| D104 | retransmits relationship signed=false under old labels, null in N | The source explicitly lacks a new signature, but the single relationship field's scope remains disputed; do not count this wholly as a correct improvement |
| D106 | An additional attendance record supported by platform connections | Supported splitting/duplication remains; this query did not double-count it, and extra_claim remains scored |
| D115 | copied=false under old labels, null in N | Copy/original status was not established; known completion date and score remain; retain the old FN |

The score cannot be relabeled 31/31, and not every extra_claim is a hallucination. Original N strict TP/FP/FN is 677/1/26. Differences concentrate in these labels and the uncertainty contract; identity, binding, and time groups retained their required fields.

## Five real-call examples

These are saved real Luna outputs. The first four use independently constructed synthetic mechanism texts available in fixtures. Original task texts and raw responses remain restricted.

| Case and repeat | Supported facts and missing information | A to N, or counterexample | Downstream effect |
|---|---|---|---|
| UNC-D03 r1 | Actual psychotherapy for 30 minutes; signature not supplied | signed=false to null; presence/delivery stay true | Retain contact facts and uncertain eligibility rather than definite zero |
| UNC-D04 r1 | Only administrative Completed; no actual presence, treatment, or signature statement | true/true/false to null/null/null; reason=Completed | Preserve the appointment without inventing actual treatment |
| UNC-D08 r1 | Date and score 5 established; copying unclear | copied=false to null; date/score retained | Missing provenance status does not delete an assessment |
| UNC-D07 r1 | Signed two-days-per-week plan; minutes threshold missing | A has no plan; N has required_days=2 and required_minutes=null | Preserve partial requirements; compliance cannot_determine, without a zero threshold |
| Original D005 r1 | Patient participation in clinical intervention supports delivery | Unadopted U sets two delivered fields null; A/N keep true | An unnecessary-abstention counterexample supporting retention of the earlier clinical rules and shorter nullable change |

## Calls, verification, and limits

Eleven experiment runs produced 537 document results and 1130 CLI attempts. The actual default CLI used 16 calls for eight documents; saved-proposal repairs used two more, totaling **1148 real CLI calls/attempts**. Cumulative input/output tokens were **24,685,271 / 1,235,029**, with 5,852,416 server-cached input tokens and zero application-cache hits. Actual subscription billing in USD was unavailable. Cumulative tokens are not a per-document context window or token limit.

N's original full run had a median document latency of 36.85 seconds and cumulative document work time of 1194.84 seconds; A totaled 1178.28 seconds. These sum parallel task durations and are not wall time. The default CLI public eight-document run took 15.69 seconds wall time; all were extracted, cache hits=0. Stage usage, retries, schema/prompt hashes, and configurations are in the local index; hundreds of raw outputs are not published.

- Final offline regression: **238 passed**, covering known true/false, undocumented, ambiguous, inapplicable, conflicts, no-target documents, partial clocks/plans, unknown identity, and correction authority. The default CLI help works; its saved real-extraction database passed encounter-level validation.
- **NOT VERIFIED:** final N was not rerun on eight difficult documents ten times each. Its full original extraction has one new 31-document run. Earlier A/B stability results do not establish N's stability.
- **NOT VERIFIED with new live end-to-end calls:** late deterministic fixes for unknown correction propagation and mixed nullable instrument sorting have offline regressions/saved-output replay only. No further Luna calls were made to fill this gap.
- Remaining limitations: D104 relationship-signature scope, D106 splitting/duplication, 3/27 uncovered clinical facts, historical-mention granularity, mixed-attachment attribution, and conservative uncertainty propagation for plan revisions. Exact quotations and validator acceptance are not general semantic proofs.
- There are only 12 development mechanism templates and three new confirmation templates. Confirmation repeats are correlated; the original group also consists of linked patient materials. They are not treated as independent clinical cases for inflated statistics.

## Commands, index, and rollback

Install requirements.lock and this package from the current checkout, or use repository sources with PowerShell `PYTHONPATH=src`. The default luna_best.json equals luna_nullable.json. These commands are for future runs; no new model calls were made during final delivery.

```powershell
$env:PYTHONPATH='src;tools'
python -m pytest -q
python -m clinical_intelligence --db artifacts/nullable-new.sqlite process --input examples/synthetic/documents --model gpt-6-luna --reasoning high
python tools/validate_live.py artifacts/nullable-new.sqlite

# Previous prompt/schema, with a new database to preserve current snapshots.
python -m clinical_intelligence --db artifacts/previous-new.sqlite process --input examples/synthetic/documents --extractor previous --model gpt-6-luna --reasoning high
```

`previous` restores the previous generation contract while retaining this round's deterministic fixes. For complete old code, use starting commit 861f260 in a separate checkout/worktree; do not reset the current branch.

Publishable synthetic facts, texts, and splits are in `tests/fixtures/uncertainty/`. Facts/constraints preceded text construction and received non-independent evidence checking. Development conflict pairs stay grouped; confirmation has different patients/templates and was not used for debugging before freeze. Generation receives only source text and allowed generic instructions/examples; repair receives runtime information, without gold or scores.

```powershell
# Reproduction entry points; future execution calls Luna. Not run during delivery.
python tools/luna_freeze.py --candidates clinical_partition nullable_v1 --dataset tests/fixtures/uncertainty/confirmation.json --output artifacts/new-freeze.json
python tools/luna_experiment.py --run nullable-reproduction --candidates clinical_partition nullable_v1 --splits original --private tests/fixtures/uncertainty/confirmation.json --repeat 3 --workers 3 --freeze artifacts/new-freeze.json
python tools/analyze_luna.py nullable-reproduction --private tests/fixtures/uncertainty/confirmation.json --revalidate
```

The public aggregate is [luna-followup-summary.json](luna-followup-summary.json). The complete local index `artifacts/semantic-followup/final-delivery/experiment-index.json` locates manifests, results, and request/prompt/schema/raw hashes. That directory retains common-runtime offline replays, the eight remaining mismatches, and the final checkpoint. Original text/gold/raw/databases remain ignored, unpublished, and preserved. Early uncommitted semantic versions retain actual requests/responses and file hashes; the starting commit alone cannot reconstruct their complete source trees. Final nullable source and confirmation freezes have separate local snapshots; delivery commit identity is recorded separately.

The conclusion is limited to this round's data, model, and tested designs: **minimal nullable better fits the current uncertainty-handling objective; an overall improvement in the original frozen strict score or a zero-error guarantee has not been demonstrated.**
