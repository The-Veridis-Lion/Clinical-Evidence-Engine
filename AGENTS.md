# CareFlow autonomous development

Before **every autonomous development round**, reread
`docs/CAREFLOW_READINESS_ENGINE.md`, check the proposed work against its goals,
constraints and acceptance criteria, and update the decision log after validation.
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

Record actual failures and before/after results. Switch tasks after two failures
of one approach. Summarize each five development decisions. Default research model
calls to zero; at most 100 explicitly justified attempts including failures and
retries. Count ordinary optional AI product calls separately.
