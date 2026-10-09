# Reliability semantic contract v1

This change is confined to claims review. Therapy `clinical_partition + nullable_v1`,
raw CSV retrieval and optional original-archive verification remain unchanged.

## Terminology and grounding

`claims-review-grounding/1` preserves original phrases, character locations within
the cited context, concept, mapping status, authoritative reference and code fields.
The existing exact citations remain the original-source coordinate system.
Offsets in terminology metadata refer to the newline-joined citation context,
not directly to the complete source. Never substitute them for Citation offsets.

- HbA1c/Hgb A1c/hemoglobin or haemoglobin A1c/A1c are a bounded concept vocabulary.
- Glycated/glycosylated hemoglobin is a contextually recognized monitoring family,
  not verified equivalence to a particular assay. This distinction permits scoped
  monitoring intent without inventing a LOINC code, specimen, unit or method.
- Glycated protein, glycated albumin and fructosamine alone are different concepts.
- Only an explicitly printed `LOINC 4548-4` maps to that verified code. Bare
  clinical phrases receive null code/system. [LOINC's definition](https://loinc.org/4548-4/)
  is a blood mass-fraction observation, not a billing claim translation.
  [CMS NCD 190.21](https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDid=100)
  discusses glycated hemoglobin and other glycated proteins separately.
- Unrecognized vocabulary remains mapping-unresolved. Preserve the proposal and
  known clinical fields; do not issue a lexical repair to turn true into null.
  Unresolved/different concepts cannot establish target binding.
- A missing cited test span when the same source clearly names a recognized test
  is a grounding error; repair must add the evidence, not erase the assertion.

Complete ISO, year/month/day and English named-month dates can ground normalized
ISO outputs. Ambiguous numeric dates and month-only precision cannot establish a
day. Roles remain model assertions: signature/receipt dates never fill service dates.
Provider comparison normalizes Unicode, case and whitespace while retaining the
source quote. Authentication requires provider-linked positive textual declaration;
mixed/negative declarations remain unresolved/false. No signature authenticity or
assertion-level semantic authority is certified by lexical checks.

## Repair

At most one repair, with runtime errors and source only. Independently validated
rows must preserve known fields and cited context; added citations, paraphrase and
filling previously unknown fields are allowed. An erasure fails explicitly and
retains first-proposal grounded rows alongside validated final rows. All provenance
is available in the call trace. This is deterministic preservation, not gold-based
sample selection. Structural validity does not establish semantic truth: a weak
first assertion can therefore cause conservative repair blocking. Report it.

## Applicability

`claims-review-applicability/1` implements per-criterion declared prerequisites:
service date, requested monitoring concept, inspected policy version and patient
identity. A missing prerequisite yields `NOT_EVALUATED`, reasons, and a separately
retained `clinical_evidence_status`. Known facts remain visible. Availability/binding
are evaluated for the evidence actually needed, not as an unknown-everywhere blocker.

The inspected NCD narrative effective-from boundary is checked. The MLN publication
month is not an enactment date. This draft mechanism does not certify historical
billing files or complete legal applicability. `draft_ai_reviewed`, human review
false and the four criteria remain. SUPPORTED is not claim approval.

## Field-scoped relationships

`claims-review-relationships/1` is a typed structured declaration, separate from
therapy claims and the note schema. A `source_relationship` object has relation
(`amends`, `supersedes`, `retransmits`), target source, field, replacement,
authentication and field authority scope. Source patient/event identity and exact
citations are supplied deterministically. Supported fields: `event_date`,
`content/value`. Declared `correction_scope=specimen_date` maps to the input's
event-date role; result/value labels map to `content/value`. Other fields remain
unresolved or explicitly outside this implementation.

Corrections require an available target, matching patient and explicit event ID,
no contradictory encounter IDs, authenticated=true, matching authority scope and
a replacement evidenced by the declaring record field. Document-wide signed status
alone is insufficient. For the original structured amendment convention, an amended
record, explicit correction target/scope and signature declaration provide that
scoped assertion; they are not independently authenticated laboratory credentials.
Ambiguous/missing scope does not supersede anything. Null replacement is not deletion.

Original facts and source rows are immutable. The derived view follows explicit
field relationships. Competing amendments, cycles and invalid authority retain
conflict/uncertainty. A valid copy points to the original record's derived view; later
receipt does not revert a correction. A result correction does not correct the date.
Date/identity uncertainty blocks event counting; result conflict remains independently
visible and does not invent additional events. Source relationship trace includes
raw citation pointers, reasons and derived values.

Free-text-only corrections are not extracted into relationships in this version.
No routing-model call was added. Existing trustworthy structured/note routing is
retained; mixed notes retain multiple fact families. There is no measured evidence
that a larger schema hierarchy or classifier improves quality within this budget.

## Evaluation boundary

New `reliability_v1` materials are fact-first AI-assisted synthetic labels, authored
separately from inference and frozen before predictions. The engineer knows those
constraints, so this is new-material confirmation, not author-blind or human gold.
The model receives only source/context/general instructions. Three note cases and
four deterministic cases use different patients, letter/table/memo layouts and
date/result/unsigned relationships. They are not seven independent clinical patients
sampled from a real population. No holdout-driven runtime tuning is permitted.

The six original exposed cases remain regression, never new holdout. Historical
scores and gold are not overwritten. Field constraints include unknown expectations;
known-value projection precision/recall, false certainty, unnecessary unknown and
execution failures are separate. Neither selected constraints nor exact offset checks
are exhaustive clinical semantic accuracy. Citation semantic review is AI-assisted;
full semantic precision remains unavailable without independent exhaustive labels.

## Separate post-confirmation program correction

After the first-pass confirmation, an independently constructed offline partial-result
counterexample exposed a derived-metadata defect: `[known_result, null]` was marked
as a conflict. `claims-review-structured/3` keeps the unknown flag but requires two
distinct non-null values for result conflict. Neither note extraction nor criterion
rules change. Actual Luna measurements belong to frozen `171c08f`; the final code
adds this separately versioned fix, verified offline and by saved-response replay.
There are no new live calls for this metadata correction. Do not describe the final
post-confirmation runtime as a freshly tested unseen candidate.
