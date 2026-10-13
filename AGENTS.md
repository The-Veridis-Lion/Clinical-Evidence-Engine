# CareFlow autonomous development

Before **every autonomous development decision**, reread
`docs/CAREFLOW_READINESS_ENGINE.md`, `docs/CAREFLOW_PROGRESS.md`, the decision
log and relevant historical experiment logs. Check direction and frozen acceptance
criteria, then update the logs after actual validation.
This instruction applies to this isolated CareFlow worktree.

Every improvement must solve a generalizable evidence-processing,
deterministic-rule, or workflow problem. Never introduce patient IDs, document IDs,
case IDs, fixture phrases, or failure-specific exceptions into product logic.
Do not alter reference answers, denominators, scoring, or historical evaluations
to obtain a positive result. Validate changes across distinct patients, documents,
Referral/PA requests and rule conditions. Do not claim an improvement is effective
before this generalization validation passes. Clinical accuracy requires evidence
beyond synthetic software tests.

Use the existing Clinical Evidence Engine for retrieval, claim indexing,
provenance, source relationships and conflict handling. Add request documentation
rules without changing existing claims/policy semantics. Keep edits in CareFlow
modules, its tests, examples and documentation. Shared compatibility fixes belong
in a separate change. Work on `feature/careflow-readiness` in this worktree; do not
edit the parallel Copilot checkout. Never auto-merge or deploy.

There is no arbitrary development duration or five-round stop. Five-round
summaries are checkpoints only. Continue effective product work until runnable
Referral/PA material checks, citations, API, review/recalculation and audit satisfy
the frozen reliability contract. No human sign-off is a prerequisite for
development, tests, or product operation. Keep both human and advanced-AI review
interfaces; opinions cannot change deterministic states without new evidence.
These rules supersede any earlier five-round stop, mandatory-human-review rule,
or instruction prioritizing prompt research over product delivery.

Reuse cached ACI-BENCH and AGBonnet/augmented-clinical-notes sources/extractions.
Freeze case-grouped development and holdout partitions before candidates run;
Augmented Clinical Notes requires at least 200 groups in each. No case/content
leakage. These datasets have no reliable PA approval or documentation-completeness
gold. Never fabricate such labels. Report source extraction and deterministic
readiness evaluation separately. Freeze versioned material-test expectations
before candidate execution; use explicit requirements and original Synthea
sources for positive, missing, conflict, inapplicable and irrelevant cases.

Reference-first: compare Luna to frozen structured references. Matching portions
pass without Sol re-review. Sol reviews only discrepancies against source,
facts, references and relevant rules: MODEL_ERROR, REFERENCE_ERROR, EQUIVALENT,
BOTH_WRONG or UNRESOLVED. Preserve original labels/scores/denominators, Sol
findings and corrected auxiliary metrics separately. Source-checked silver labels
are not independent medical ground truth.

Frozen targets: readiness five-state macro-F1 >=98%; zero missing/conflict ->
Ready serious errors; source and rule-version mechanical validation 100%; core
API, audit, recalculation and regressions pass. Source-checked auxiliary extraction
targets: precision >=95%, recall >=90%. Do not claim completion before measured.
Do not use final holdout until candidate freeze. If targets are unmet, continue
other effective product work rather than falsifying completion.

GPT-6.1 Sol/high handles decisions, source/reference disputes, implementation
strategy and interpretation; GPT-6 Luna/high handles clinical extraction/batches.
Do not repeatedly review reference-matching material with Sol. Freeze baseline
before every improvement; validate across cases and rules; retain only measurable
benefit, otherwise roll back. Switch direction after two ineffective attempts.
Never resample Luna for better semantic scores or adjust labels/easy-case selection.

Across CareFlow/Copilot, Luna concurrency <=50 using a shared scheduler/call
ledger. Before a shared scheduler exists, each project <=25. Per document, at
most two extra attempts for upstream output, parsing or mechanical validation
failure only; retain all attempts/failures. Earlier zero-default research and
100-extra-research-attempt limits still apply unless explicitly superseded;
ordinary product extraction/review calls are separate, counted, and not silently
reclassified as research or vice versa. Never buy resources.

During actual active Codex work, update docs/CAREFLOW_PROGRESS.md about every
30 minutes: implemented Referral/PA behavior, rule metrics/serious errors,
source issues, Luna attempts/failures/retries, Sol decisions and next work.
Send Chinese progress in the current chat when supported. Do not pretend to run
in the background. If execution cannot continue, preserve recoverable work and
state the limitation. Do not repeat blocked experiments without benefit.
