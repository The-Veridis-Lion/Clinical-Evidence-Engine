# Measured Note Size and B-Only Inference Cost

These are historical saved-request measurements, not new model calls. The unit is
one document workflow, including existing repair. The notes are constructed synthetic sources, not original patient records.

## Verified Workload

12 distinct notes, each run twice with original B: 24 workflows, 28 requests,
four repairs. Usage totals: 498,270 input, 11,008 cached input (a subset),
44,704 output tokens; recorded cache writes are zero. Summed workflow duration
is 483.56095 seconds. Current Standard short-context rates were checked on
October 9, 2026 against the [model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
and [pricing page](https://developers.openai.com/api/docs/pricing).

```text
(498270 × $0.10 + 44704 × $0.50) / 1,000,000 = $0.072179 total
$0.072179 / 24 = $0.00300746 per document workflow
```

This estimate does not apply cached-input discounts or regional/fast-tier
surcharges. Reasoning tokens are already part of output. Actual Codex subscription
billing and backend snapshot are unavailable. Do not use the separate 50-request
Scope Audit experiment to estimate normal B costs. No production scaling or
linear cost extrapolation is established.

## Length Strata and Per-Run Distribution

| Group | Distinct notes / runs | Words: mean / median / range | Seconds/run: mean / median / range | USD/run: mean / median / range |
| --- | --- | --- | --- | --- |
| all | 12 / 24 | 349.92 / 197 / 155–707 | 20.15 / 16.75 / 5.28–40.87 | $0.003007 / $0.002705 / $0.001831–$0.005558 |
| long | 4 / 8 | 673.75 / 670.5 / 647–707 | 21.44 / 16.65 / 15.09–39.83 | $0.003385 / $0.002774 / $0.002607–$0.005558 |
| short | 8 / 16 | 188.00 / 187 / 155–215 | 19.50 / 16.75 / 5.28–40.87 | $0.002819 / $0.002632 / $0.001831–$0.004781 |

## Every Distinct Source and Both B Runs

Source word counts use whitespace splitting, matching the frozen manifest. UTF-8
byte length and character length are equal for these ASCII notes. Each request
usage snapshot accumulates earlier workflow metrics; the summarizer counts only
the newly appended metric, avoiding repair double counting.

| Source | Words | Characters / UTF-8 bytes | Run | Requests / repairs | Input / cached / output | Seconds | API-equivalent USD |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| N01 | 647 | 4319 / 4319 | n01-B-r1 | 1 / 0 | 18050 / 0 / 1919 | 16.41 | $0.0027645 |
| N01 | 647 | 4319 / 4319 | n01-B-r2 | 1 / 0 | 18048 / 0 / 1876 | 15.58 | $0.0027428 |
| N02 | 707 | 4638 / 4638 | n02-B-r1 | 1 / 0 | 18142 / 0 / 1585 | 15.09 | $0.0026067 |
| N02 | 707 | 4638 / 4638 | n02-B-r2 | 1 / 0 | 18144 / 0 / 1964 | 39.83 | $0.0027964 |
| N03 | 674 | 4372 / 4372 | n03-B-r1 | 2 / 1 | 37218 / 0 / 2733 | 24.30 | $0.0050883 |
| N03 | 674 | 4372 / 4372 | n03-B-r2 | 2 / 1 | 38850 / 0 / 3346 | 27.97 | $0.0055580 |
| N04 | 667 | 4506 / 4506 | n04-B-r1 | 1 / 0 | 18096 / 0 / 1852 | 15.46 | $0.0027356 |
| N04 | 667 | 4506 / 4506 | n04-B-r2 | 1 / 0 | 18098 / 0 / 1948 | 16.90 | $0.0027838 |
| N05 | 194 | 1302 / 1302 | n05-B-r1 | 1 / 0 | 17073 / 0 / 1598 | 15.19 | $0.0025063 |
| N05 | 194 | 1302 / 1302 | n05-B-r2 | 1 / 0 | 17073 / 0 / 2092 | 40.87 | $0.0027533 |
| N06 | 215 | 1390 / 1390 | n06-B-r1 | 1 / 0 | 17098 / 0 / 2766 | 23.07 | $0.0030928 |
| N06 | 215 | 1390 / 1390 | n06-B-r2 | 1 / 0 | 17098 / 0 / 1803 | 16.86 | $0.0026113 |
| N07 | 186 | 1256 / 1256 | n07-B-r1 | 1 / 0 | 18723 / 0 / 1604 | 15.17 | $0.0026743 |
| N07 | 186 | 1256 / 1256 | n07-B-r2 | 1 / 0 | 17067 / 0 / 1835 | 16.66 | $0.0026242 |
| N08 | 200 | 1266 / 1266 | n08-B-r1 | 1 / 0 | 18728 / 0 / 1835 | 17.83 | $0.0027903 |
| N08 | 200 | 1266 / 1266 | n08-B-r2 | 1 / 0 | 17076 / 11008 / 1879 | 36.93 | $0.0026471 |
| N09 | 188 | 1287 / 1287 | n09-B-r1 | 2 / 1 | 34944 / 0 / 1973 | 20.43 | $0.0044809 |
| N09 | 188 | 1287 / 1287 | n09-B-r2 | 2 / 1 | 34968 / 0 / 2568 | 36.25 | $0.0047808 |
| N10 | 184 | 1183 / 1183 | n10-B-r1 | 1 / 0 | 18706 / 0 / 1271 | 12.34 | $0.0025061 |
| N10 | 184 | 1183 / 1183 | n10-B-r2 | 1 / 0 | 17054 / 0 / 1315 | 11.68 | $0.0023629 |
| N11 | 155 | 1051 / 1051 | n11-B-r1 | 1 / 0 | 16942 / 0 / 274 | 5.28 | $0.0018312 |
| N11 | 155 | 1051 / 1051 | n11-B-r2 | 1 / 0 | 16940 / 0 / 1483 | 13.72 | $0.0024355 |
| N12 | 182 | 1289 / 1289 | n12-B-r1 | 1 / 0 | 17066 / 0 / 1318 | 12.90 | $0.0023656 |
| N12 | 182 | 1289 / 1289 | n12-B-r2 | 1 / 0 | 17068 / 0 / 1867 | 16.84 | $0.0026403 |

## Reproducible Calculation, Zero Inference

[Machine-readable measurements](release-measurements.json) contain all source
hashes, run IDs, per-request usage locators/hashes, and length/cost summaries.
The published [source manifest](../examples/claims_review/b_candidate_v1/dataset_manifest.json)
and [complete synthetic notes](../examples/claims_review/b_candidate_v1/README.md)
allow source-size verification. Full saved usage remains in the ignored local
`artifacts/b-candidate-new-validation-01/` round, alongside immutable predictions.

```sh
python tools/summarize_release_costs.py --round artifacts/b-candidate-new-validation-01 --output artifacts/recomputed-costs.json
```

This command only reads existing manifests, inputs, ledger plan and usage files.
It never imports or calls a provider. A checkout without private saved usage can
inspect the compact public measurements but cannot regenerate missing traces.
Historical runner freeze operations require `CLINICAL_HISTORICAL_LEDGER` to point
explicitly to the existing ledger; this is not authorization to rerun a closed
experiment or create a replacement ledger.

## Release Verification

The first release suite invocation had three child-process failures caused by
importing an older installed package. The permitted environment-only retry set
the release source path explicitly: **389 passed in 4.42 seconds**. No test or
production behavior was changed to pass. Live provider dispatch and Python
network connections were blocked. Publication edits subsequently changed only
documentation, the B module docstring, and explicit historical-runner ledger
configuration; original B text/schema and ordinary runtime remained unchanged.
