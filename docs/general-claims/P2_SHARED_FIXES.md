# Shared claims safety fixes

2026-10-13. Dependency baseline PR #3 `f91768e`; isolated worktree and
`fix/claims-coverage-archive-bounds`, without touching Copilot's checkout.

Full saved-output verification now accounts for original **claim row source IDs**,
including blank, missing and ambiguous patient linkage. Split eligibility remains
restricted to unique patient identities; no old split is changed. Independent
verification counts duplicate patient rows, checks emitted patient linkage state,
and reports unassigned claim rows. Duplicate claim-ID processing failures retain
their distinct source-row identities rather than silently disappearing.

Shared `BoundedArchive` validates compressed bytes, member count, every declared
member size and aggregate size before any decompression, including non-CSV files.
Each member read is bounded and checked against its declared size. An immutable
compressed snapshot supplies both archive SHA and member bytes, preventing a path
replacement between checks and reads. The bounds cover ArchiveIndex and all its
CLI routes, saved-output verification, legacy retrieval/download and original-source
verification. No policy, clinical interpretation or claim indexing semantics changed.

Defaults: compressed12MB, member60MB, total150MB, member count10,000. These are the
existing sample workflow's finite data limits, not unlimited production-size support.

Validation: six fixed patient-linkage cases originally failed coverage; eight new
archive-entry tests initially could not import the missing shared safety mechanism.
After implementation,18 added tests cover two patient identities, three linkage
states, CSV/non-CSV files across four entrypoints, total/compressed/count bounds and
path replacement.35 focused tests and483 full shared-engine tests passed. Before
and after JUnit files are preserved under `artifacts/` and copied to CareFlow's
committed integration evidence. This is software/source verification, not clinical
or payment accuracy. Original labels, splits and historical evaluations remain intact.
