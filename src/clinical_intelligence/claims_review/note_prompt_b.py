"""Frozen experimental proposition/event guidance; A remains the default."""

VERSION = 'claims-note-prompt-b/1'
PROMPT_B = '''Extract source-supported HbA1c review facts only, using the existing schema.
No tools, files, diagnosis, policy evaluation, arithmetic or payment decisions.
Request context is not clinical evidence. Return structured facts and source references
only, without an extended reasoning narrative.

Identify distinct propositions and the events or states they describe. Keep each
proposition's participants, negation, dates, temporal role and evidence together.
Extract every supported relevant fact. Use null only when the required information
cannot be established; do not guess, and do not abstain when evidence is sufficient.
Required keys may be null. Preserve competing assertions as separate facts.

Use these existing fact families:
- purpose: monitoring/screening/initial_diagnosis or null.
- diabetes_context: true for established disease, false for an explicit absence
  diagnosis, null for missing/ambiguous diagnosis documentation. Routine monitoring
  alone does not independently establish a diagnosis.
- regimen_change: true for an implemented change, false for explicit
  nonimplementation. A proposed change or prescription is planned, not implementation.
- clinical_rationale: implemented_change/altered_control_event/uncontrolled_diabetes
  or null, explicitly linked to this test's reason. False requires affirmative
  contradiction of a specifically asserted rationale, not missing documentation.
  Do not infer control from numeric results.
- order_intent: true for explicit intent for this specific test, false for affirmative
  cancellation/refusal/withdrawal, null for missing intent paperwork.
- test_mention: source test/date mentions, not automatically independent actual events.

Temporal_status describes the proposition itself: an established current disease is
actual even beside a planned test; historical requires explicitly historical content.
A current 'not started' statement is actual nonimplementation, distinct from a future
discussion. A future discussion does not prove a change was arranged or implemented.
A test's documented rationale may concern a planned test while a separate change
proposition establishes actual implementation. Do not inherit nearby temporal roles.

Identify the specific test discussed before attaching dates. Link dispersed purpose,
order and requested date only when source evidence establishes the same test.
Multiple tests can have different dates. Do not broadcast the only date in a document.
fact_date is an explicitly documented assertion/event date in date_role;
target_date is the explicitly stated date of the test requested or discussed.
Keep order_issued, requested_test, actual_test, adjustment_start and background_review
roles distinct; use unknown when no role is supported. Signature, record and receipt
dates cannot substitute for test or assertion dates. Never backfill from request context.
Complete unambiguous dates use ISO, including named months and year/month/day.
Month-only or ambiguous numeric dates remain null; retain their precision in statement.

Copy patient_id/source_id exactly. Select all necessary supplied span_ids, including
cross-paragraph context. Context may identify patient/encounter, but cannot prove
purpose, clinical facts or actual test performance. Preserve original terminology;
HbA1c/Hgb A1c/hemoglobin A1c/glycated or glycosylated hemoglobin are recognized in
context; glycated albumin/protein or fructosamine alone is not HbA1c. Generate no codes.
Provider is the verbatim attributed name or null. Distinguish author, original reporter,
patient and ordering provider. A signer is not automatically every assertion's reporter.
Authenticated=true requires applicable signature evidence and linked provider for that
assertion. Unrelated signatures and requests for signatures do not authenticate it.
Explicit unsigned is false; unknown authentication is null. Digital/electronic signature
declarations do not establish authority to correct another source.
Readable statement preserves negation and scope; unknown is neither false nor zero.

Before returning, check for omitted explicit facts, cross-event date leakage,
unsupported diagnosis/authentication and temporal-role inheritance. Preserve known
values while leaving only unsupported details unknown.
'''
