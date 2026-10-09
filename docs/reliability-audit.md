# Reliability audit v1 (before runtime changes)

Starting commit: `a194ac6c56c3b947be9dd362db441b8070cf5161`.
The six former confirmation cases are exposed regression material. Historical
gold, predictions, 3/6 complete conformance and 16/24 states remain immutable.
Review method: AI-assisted code/source/visible-response inspection, not human or
clinical-expert review. The persistent ledger contains 13 of 20 allocations.

| Mechanism | Earliest incorrect stage | Propagation / evidence |
|---|---|---|
| Narrow analyte guard | Validator | Call 7 names glycated hemoglobin and sets specificity true; call 8 changes it to null following lexical errors. Monitoring/order become insufficient. |
| Unnecessary unknown | Model / repair | Call 10 purpose target_date is null despite an explicit source date; encounter binding masks this in criterion metrics. No deterministic date-role inference is justified. |
| Missing applicability prerequisites | Criterion evaluator | Call 11 preserves score 8.0 and unknown dates. Monitoring becomes SUPPORTED although policy selection is unresolved. |
| Missing amendment handling | Structured reconciliation | Call 12 extracts rationale and implementation; structured original/amendment/copy remain raw. Timeline uses competing dates without applying an explicit field relationship. |
| Patient isolation | No observed failure | Other-patient reused encounter token excluded before inference; call count zero. |
| Absence semantics | Representation risk | Call 13 false disease-background statement concerns missing established diagnosis in supplied history, not absence of disease. Do not broaden its meaning. |

Additional reproduced/code-derived risks:

- Dates require normalized ISO to literally occur in evidence, rejecting named
  month dates. Ambiguous numeric dates must not be arbitrarily interpreted.
- Provider comparison is case/whitespace sensitive. Authentication substring
  checks can accept `unauthenticated` and reject valid digital-signature language;
  a negative signature elsewhere can invalidate an unrelated positive one.
- Source-wide authentication is not assertion-level amendment authority.
- A response can pass lexical and positional checks while having the wrong
  meaning, role, reporter, negation or signature scope. These checks are not a
  semantic correctness proof.
- Single-note contract has many nullable fields but no controlled evidence of a
  routing-model benefit. Existing trustworthy structured/note routing should be
  retained; structured relationships can have their own deterministic contract.
- Therapy reconciliation's explicit-target, provenance and no-timestamp-winner
  principles are reusable; its therapy-specific service models are not.

Selected bounded implementation: concept/date grounding with explicit mapping
metadata; declared criterion prerequisites; immutable field-level source
relationships with a derived view; repair preservation checks. No broad prompt
search, no change to therapy/retrieval/archive verification or historical scorer.
