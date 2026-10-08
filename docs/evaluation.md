# Evaluation on the synthetic corpus

This evaluation asks whether explicit source relationships preserve corrections and
uncertainty, whether persistent queries reproduce answers, and what the small local
query workload costs. All numerical results below concern the eight April 2026
synthetic documents and two patients. They do not measure real-patient clinical accuracy.

## Reproduce the offline workflow

After following the README installation steps, run from the repository root:

```sh
python -m pytest -q
clinical --db artifacts/demo.sqlite demo
clinical --db artifacts/demo.sqlite demo
clinical --db artifacts/demo.sqlite query --patient DEMO-CEDAR --family utilization --format audit
clinical --db artifacts/demo.sqlite query --patient DEMO-CEDAR --family compliance --format audit
clinical --db artifacts/demo.sqlite experiment
clinical --db artifacts/demo.sqlite benchmark --iterations 5
```

For saved output, place global `--output artifacts/result.json` before the subcommand.
Databases, full answers, expanded audits, and model streams are not committed.

The demo loads explicitly hand-authored claims through the real content registry,
grounding validation, storage, reconciliation, query, and audit paths. It does not run
a model. A separate fixed-response test exercises real LangExtract alignment and parsing.
The source text and claim fixtures are packaged for standalone installed execution;
tests require them to match the readable documents under `examples/synthetic/documents`.

## Correctness checks

The final offline suite covers **170 passing cases, zero failures and zero skips**.
These exercise independent datetime arithmetic, exact span rejection and repeated-quote
disambiguation, patient identity isolation, duplicate idempotency, configuration-key
invalidation, immutable snapshots, incomplete-evidence blocking, bounded concurrency,
correction target constraints, retransmissions, conflicts, date and service uncertainty,
plan comparisons, QuerySpec validation, source contribution references, and restarts in
a new interpreter. Fixed-response natural-language tests check request translation and
provider error behavior; they do not establish broad language-model accuracy.

On first demo ingestion, eight unique sources and one duplicate alias produce eight
extractions and one cache hit. The second run produces nine cache hits, zero new
documents or extractions, and identical patient answers. Both runs make zero model calls.
Cedar has two encounters, two days, and minute alternatives 108/120; Juniper has one
encounter and 23 minutes. The audit references the actual attendance, amendment, and
activity passages, including their character offsets. The 115-minute plan threshold
straddles Cedar's alternatives, so compliance remains `cannot_determine`.

## Same-evidence policy comparison

`experiment` rebuilds both policies from the same persisted claims. No inference,
source changes, or alternate fact fixtures are involved. The normal policy is `explicit`;
`latest_wins` is a deliberately naive comparison, never an automatic failure fallback.

| Synthetic result | Explicit relationships | Naive latest-record selection |
|---|---:|---:|
| Cedar corrected group | 71 minutes | 86 minutes |
| Cedar disputed individual encounter | 37 or 49 minutes | 49 minutes |
| Cedar total | 108 or 120 minutes | 135 minutes |
| Juniper total | 23 minutes | 23 minutes |

The later copy restores the superseded departure under the naive policy. Undated
duration claims have no justified temporal priority; a deterministic tie-break selects
one in that policy. Its apparently precise total hides the unresolved conflict. Both
policies retain identical source-claim identities. These selected cases demonstrate
policy consequences, not general accuracy or superiority over every alternative design.

## Local timing methodology

Measured on Windows 11, Python 3.12.14, SQLite 3.53.1; eight documents, two patients,
nine source claims. Five iterations per in-process boundary, and three new-process
CLI requests. Medians are wall-clock measurements from the included benchmark utility.

| Boundary | Median |
|---|---:|
| In-memory numerical compliance, no provenance assembly | 0.040 ms |
| Public patient compliance query with provenance, preloaded data | 0.743 ms |
| Public collection compliance query, preloaded data | 0.976 ms |
| New interpreter CLI compliance query, including JSON capture | 260.211 ms |

The CLI measurement includes startup, database loading, provenance, serialization,
and parent-process validation. In-process timings exclude those startup costs and use
loaded abstractions/registry. The first in-process load is not a cold-restart benchmark.
CLI provenance is correctly reported as partial for this plan wording. The tiny corpus,
five samples, filesystem cache, and machine environment limit comparison; there is no
500K-document throughput result, cost projection, or performance guarantee.

## Earlier live extraction result

The earlier 2026-10-08 run used real LangExtract and authenticated Codex CLI inference
with `gpt-6-luna`, high reasoning, the baseline contract, and one extraction pass. First
pass: seven accepted documents and one failure for missing grounded patient identity;
one separately initiated retry succeeded. Nine actual extraction calls were made.

Accepted structured output still failed the semantic comparison for Cedar: the model
omitted `LAB-G7` from the activity claim. The break remained grounded but did not join
attendance, leaving a 79-minute group event and an additional insufficient event.
The correction survived retransmission and the 37/49 conflict remained visible.
Juniper matched one encounter / 23 minutes. A separate real interpretation call returned
the expected utilization QuerySpec for an April 6–12 question on the fixture database.

To perform your own live comparison after a real extraction run:

```sh
python tools/validate_live.py artifacts/live.sqlite
```

It compares reconstructed encounter fields with hand-authored synthetic fact fixtures
and exits nonzero on differences. Its expected abstractions use the same reconciler;
independent arithmetic and reconciliation correctness are checked separately in tests.
No raw provider responses are distributed. The curation pass performed **no fresh live
inference**; removing the unpromoted sparse path leaves the baseline prompt, examples,
contract, cache key, and alignment behavior unchanged. Cached evidence is not a new
semantic extraction validation.

## Limitations

The quantitative locator misses intervening wording in "115 patient-present minutes".
The complete plan quote remains stored, but its required-minute field is `not_located`
and compliance provenance is partial. Complete provenance elsewhere means reference
coverage, not clinical truth. The baseline live extractor omits functional-action claims;
the stored domain and progress queries can represent them. Single-patient documents,
explicit encounter identifiers, same-day local clocks, and Monday–Sunday requirements
bound the current implementation. No real-patient validation, regulatory approval,
autonomous medical decisions, or large-scale deployment is demonstrated.
