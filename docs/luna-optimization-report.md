# Luna extraction optimization: final delivery summary

This is the historical report for the preceding optimization round. The current default and later uncertainty changes are documented in the [nullable follow-up report](luna-followup-report.md); the scores below remain unchanged.

Conclusion: `clinical_partition` was selected within this round's data, requested model, and tested designs, prioritizing clinical-fact coverage and relationship correctness. It does not lead every metric and is not clinical validation. The requested model was `gpt-6-luna`, reasoning high, CLI 0.159.3; the actual backend model snapshot was unavailable.

## Implementation and program fixes

The selected extractor uses a Pydantic-derived typed object schema, complete-document examples, reversible line/span IDs, an identity object, identifier inventory, and clinical semantic rules. The first pass extracts all facts. A second pass still reads the complete source but extracts only observations and replaces the first-pass observations. Runtime validation allows at most one repair. Code handles offsets, clock conversion, interval arithmetic, cross-document reconciliation, and queries. Gold mismatches never trigger retries or answer selection.

Shared program fixes cover explicit patient/document/encounter identifiers, service-omission checks, contextual attribution of repeated quotations even with valid offsets, rejection of ignored parameters, and cache identity including provider/schema/adapter/CLI versions. Missing dates, scores, and unresolved corrections retain uncertainty. These gains are not attributable to prompts; fair comparisons use common validation, calculation, and `critical-fields-9` scoring. Original-task oracles are externalized to ignored directories and are not distributed with the software.

## Main experiments and final comparison

Forty-two configurations explored string versus typed contracts, fragment versus document examples, quotations versus line/span IDs, identity structures, semantic rules, task splitting, validation repair, review, matched-budget resampling, and reasoning settings. Typed schema alone did not improve consistently. Matched complete examples combined with identity and semantic rules were more effective. Full review, increased reasoning, alternative partitions, and additional field descriptions did not produce stable gains; iteration stopped under the convergence requirement.

| Three independent real repeats | Baseline | Selected profile | Matched-budget resampling |
|---|---:|---:|---:|
| Original task: 31 documents, fully correct | 63/93 | 90/93 | 92/93 |
| New synthetic set: 24 documents, fully correct | 58/72 | 71/72 | 71/72 |
| Public set: 8 documents, fully correct | 17/24 | 24/24 | 24/24 |
| Independent clinical-coverage assertions | 63/81 | 76/81 | 74/81 |
| Median latency, seconds | 12.40 | 20.16 | 27.54 |

The matched-budget control always uses the second extraction, with at most one validation repair; it is not manual selection of the best answer. Selection emphasizes clinical coverage and latency. These correlated samples do not support claims of statistical significance or comprehensive superiority. Original-task, public demonstration, and new synthetic materials are reported separately.

Nineteen difficult cases each received ten independent real repeats: original eight-document correctness improved from 53/80 to 72/80; ten new synthetic documents from 93/100 to 100/100; the public activity document from 2/10 to 10/10. Repeats do not replace evidence of generalization across different cases.

## Independent sealed evaluation and limitations

Ten new templates/patients were first called after freezing. Across three repeats, complete correctness was 19/30 for baseline and 21/30 for the selected profile; query correctness was 25/30 and 27/30. The selected profile's nine strict failures concentrated in cancellation calls, draft records, and signed letters. In the first two templates, gold labeled appointment IDs as encounters despite the source labels. In the third, gold treated signature date as service date without independent source support. One cancellation-call output also omitted recorded date. Frozen scores remain intact: gold was not changed, failures were not removed, and no tuning followed sealed evaluation. These scores cannot establish reliability on unseen clinical material, and all nine failures cannot be counted as model semantic errors. Published sealed fixtures are now regression materials only.

Actual production-default CLI extraction in that round: public documents 8/8 with 16 calls; original documents 27/31 with 64 calls, including two targeted repairs. Later database-cache reuse made no model calls and is not an independent repeat. The original offline regression had 206 passing tests, including fixed-response tests; these are not measurements of model quality.

Copy/signature scope, patient presence, time-role, relationship, and clinical-coverage errors were not eliminated consistently. Exact quotations and complete provenance do not establish clinical correctness. The system assumes one patient per document, same-day local times, and the existing categories. Cross-midnight/time-zone cases, large clinical corpora, and unseen instruments were not validated; model-generated functional-action taxonomy was not implemented.

## Concrete before/after examples

These are projections from fixed public synthetic runs, without manual best-answer selection. Code converts clocks to minutes.

| Source and fixed sample | Old output | Selected output | Error and downstream effect |
|---|---|---|---|
| DEMO-ACTIVITY: `Facilitator signed LAB-G7 activity record dated 2026-04-06... equipment pause from 09:41 to 09:49.`; final-confirmation-v13 repeat-01 | encounter_ref=null, break=[581,589] | encounter_ref=LAB-G7, same break | Omitted unlabeled ID prevented the break from linking to its encounter. The final linkage retains corrected 71 minutes and the group's genuine conflict. |
| robust-1: signed individual therapy for 20 minutes, DOB present, service date absent; missing-date-before / final repeat-01 | Non-nullable candidate guesses 2026-03-01; honest null baseline rejected by Pydantic | service_date=null; 20-minute fact retained | Representation/time-role issue. Period contribution is 0..20, without inventing a date. This is a shared representation fix, not an isolated prompt gain. |
| robust-7: original PHQ-9, completed 2026-08-08, total score blank | Baseline null score rejected; old typed candidate omitted the whole assessment | Date retained, score=null; query score_options=[] | Omission/representation issue. No invented zero or false score change. |
| robust-8: address-format administrative record containing `No patient contact...`; final-confirmation-v13 repeat-01 | Old validator incorrectly required service; repair could manufacture an administrative service | This fixed run still extracted an extra administrative service; all ten later stability-v13 repeats correctly returned empty claims | Negated-cue program defect was fixed, but model over-extraction on no-target documents remained occasional. Empty-output successes alone would be misleading. |
| Sealed negation: `Parent says ... has no suicidal thoughts ... still losing sleep.`; fixed repeat-02 | Baseline observation lacked required fields and failed validation | safety/absent/current and symptom/present/current; reporter=parent, experiencer=patient | Parsed-contract, subject, and negation issue. Typed contracts and the clinical pass preserve distinct assertions. |
| Sealed letter: signature date and completed-treatment clocks, without a separate service date | service_date=null | service_date=null | Unresolved date ambiguity and gold issue. The final answer remains 0..32; the failure is preserved rather than selecting a date. |

## Call records and data boundaries

Twenty-nine local run directories retain 4250 runner tasks: 5826 CLI attempts, 5825 with visible generation usage, and one sandbox failure without usage. Cumulative input was 118,739,782 tokens, including 37,597,952 cached input; output was 6,092,364, with 2,775,914 reasoning tokens included in that output total. Summed call duration was 68,728.11 seconds across parallel calls, not wall time. Actual billing was unavailable. This is not a per-document 45k limit.

The machine-readable aggregate is [luna-results-summary.json](luna-results-summary.json). Complete candidate/failure registration, original inputs, full gold, requests/responses, and databases remain in local ignored directories and are excluded from publication. Model subprocesses see only source text, generic instructions, and configured examples; gold and scores are used only by the parent evaluation process.

The curated release's offline regression had **206 passed**. One parameterized test applying only to the discarded string candidate was removed; a behavior test requiring private oracles to match the full document group was added. All 16 prompt/schema pairs for the public eight-document, two-pass extraction hash-match the measured versions.

## Reproduction

Install locked dependencies as described in README and authenticate local Codex. Run from the repository root with new run names and databases; an existing run name is only for resumption. Each request has a 180-second timeout, at most three transport attempts, and 5/15-second backoff. All attempts are counted.

The commands below reproduce regression comparisons with the available code. Exact historical runtime reproduction requires commit `861f2607b9aa8559fd860159439463d4d0229e4d` and the retained historical manifests; the current checkout has later uncertainty and scoring fixes. Use `--extractor previous` in the current checkout for the preceding generation contract.

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m clinical_intelligence --db artifacts/best.sqlite process --input examples/synthetic/documents --extractor previous
.\.venv\Scripts\python.exe tools/validate_live.py artifacts/best.sqlite
.\.venv\Scripts\python.exe tools/luna_experiment.py --run public-repeat-01 --candidates baseline clinical_partition semantic_resample --splits public dev validation original --private tests/fixtures/luna/robustness.json --repeat 3 --workers 6
.\.venv\Scripts\python.exe tools/analyze_luna.py public-repeat-01 --private tests/fixtures/luna/robustness.json --revalidate
# Sealed fixtures are published: this is regression, not a new unseen evaluation.
.\.venv\Scripts\python.exe tools/luna_freeze.py --candidates baseline clinical_partition --output artifacts/sealed-freeze.json
.\.venv\Scripts\python.exe tools/luna_experiment.py --run sealed-regression-01 --candidates baseline clinical_partition --splits sealed --repeat 3 --workers 6 --freeze artifacts/sealed-freeze.json --allow-sealed
```

`--extractor baseline` uses the historical prompt/schema with the same shared program fixes, providing an extraction-design rollback. Development/validation/sealed splits separate patients and template families; synthetic facts and gold precede text construction. Public fixtures, independent query oracles, runner, and scorer support reproduction of public evaluations. Original-task reproduction requires separately authorized source materials and reviewed annotations; they are not included in the software.

Private numeric oracles may be placed in `artifacts/luna-private/query_oracles.json`, keyed by group with `sample_ids` and `utilization`. Scoring requires an exactly matching complete sample set. Clinical-query oracles may supply `instrument` and `assessments`, each with `date` and `scores`. Additional clinical facts belong in `artifacts/luna-private/clinical_supplement.json`. These enter offline scoring only. Manifests record code/data/configuration hashes, model/CLI, repeat, and cache policy. Request directories preserve prompt/schema, CLI events, response, usage, latency, and failures. Do not commit artifacts to GitHub.
