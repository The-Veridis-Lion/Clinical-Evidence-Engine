# New constructed note sources v1

Twelve full newly authored synthetic notes, not original hospital records. Four are 647-707 words; eight are 155-215 words. All are AI_ASSISTED, with nonblind source authors and no human/expert validation. Anonymous source IDs are not mechanism labels. No prior DEV/CONF/REL note is reused or renamed. Sources cover ordinary orders, signatures and reporter scope, diagnosis uncertainty, conflicting assessments, multiple test dates, historical results/receipt, current nonimplementation, future discussion and two no-target controls.

Each Nxx.json is a complete CaseInput containing the entire note. Constructed claims provide identity/workflow context only, never clinical evidence. Unknown claim service dates deliberately preserve the boundary between note quality and evaluable policy prerequisites. No complete longitudinal history or actual target performance is asserted. dataset_manifest.json records content hashes, lengths, families, origin and prior-use status. expected.json contains the fixed source-bound selected constraints and offline answer fixtures; full AI source-review records remain private.

Licensed under the repository PolyForm Noncommercial 1.0.0 terms; see LICENSE.md and NOTICE in the repository root. These are engineering mechanism/length tests, not clinical performance evidence.

After the frozen run these notes are exposed regression material. The frozen evaluator has unresolved order-temporal and no-target-extra scope defects; its expectations are retained for auditing, not presented as validated gold. See docs/b-candidate-new-validation.md for INCONCLUSIVE_SCORER / B_NOT_READY and unchanged default A.
